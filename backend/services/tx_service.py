"""
TX Service — HackRF transmission with comprehensive safety controls.

All transmissions go through safety gates:
  - Frequency whitelist (only authorized amateur/ISM bands)
  - Power cap (max VGA gain)
  - Duration limit (hardware kill after timeout)
  - Full audit log (every attempt logged, success and rejected)
"""

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Tuple

import numpy as np

from ..db.database import get_session_factory
from ..db.models import TXLog

logger = logging.getLogger("raven.tx")


@dataclass
class TXRequest:
    freq_hz: int
    gain_db: int
    duration_s: float
    sample_rate: int = 2_000_000
    iq_file: str = ""
    waveform: str = ""  # tone, fm, am, sweep
    operator: str = "system"
    rf_amp: bool = False


class TXService:
    def __init__(self, settings, device_manager, db_path: str):
        self._enabled = settings.tx.enabled
        self._max_gain = settings.tx.max_gain_db
        self._max_duration = settings.tx.max_duration_s
        self._authorized_bands = settings.tx.authorized_bands_mhz
        self._dm = device_manager
        self._db_path = db_path
        self._active_tx = None
        self._tx_count = 0

    @property
    def enabled(self):
        return self._enabled

    def enable(self):
        self._enabled = True
        logger.warning("TX ENABLED by operator")

    def disable(self):
        self._enabled = False
        logger.info("TX DISABLED")

    def validate(self, req: TXRequest) -> Tuple[bool, str]:
        """Validate a TX request against all safety gates. Returns (ok, reason)."""
        # Gate 1: TX master switch
        if not self._enabled:
            return False, "TX is disabled — enable via API first"

        # Gate 2: Frequency whitelist
        freq_mhz = req.freq_hz / 1e6
        in_band = False
        for band_low, band_high in self._authorized_bands:
            if band_low <= freq_mhz <= band_high:
                in_band = True
                break
        if not in_band:
            return False, f"Frequency {freq_mhz:.3f} MHz not in authorized bands"

        # Gate 3: Power cap
        if req.gain_db > self._max_gain:
            return False, f"Gain {req.gain_db} dB exceeds max {self._max_gain} dB"

        # Gate 4: Duration limit
        if req.duration_s > self._max_duration:
            return (
                False,
                f"Duration {req.duration_s}s exceeds max {self._max_duration}s",
            )

        # Gate 5: RF amp requires explicit flag
        if req.rf_amp:
            return False, "RF amplifier enable not permitted via API"

        return True, "OK"

    async def transmit(self, req: TXRequest) -> dict:
        """Execute a validated TX operation."""
        # Validate
        ok, reason = self.validate(req)

        # Log every attempt (success or rejected)
        await self._log_tx(req, ok, reason)

        if not ok:
            logger.warning(
                "TX REJECTED: %s (freq=%d Hz, gain=%d dB)",
                reason,
                req.freq_hz,
                req.gain_db,
            )
            return {"status": "rejected", "reason": reason}

        # Find HackRF
        hackrf = self._dm.get_free_device("hackrf")
        if not hackrf:
            return {"status": "error", "reason": "No HackRF available"}

        hackrf.status = "tx"
        hackrf.assigned_task = "tx"

        try:
            # Generate or use provided IQ file
            iq_path = req.iq_file
            if req.waveform and not iq_path:
                iq_path = self._generate_waveform(req)

            if not iq_path or not os.path.exists(iq_path):
                return {"status": "error", "reason": "No IQ file"}

            # Execute hackrf_transfer
            cmd = [
                "hackrf_transfer",
                "-t",
                iq_path,
                "-f",
                str(req.freq_hz),
                "-s",
                str(req.sample_rate),
                "-x",
                str(req.gain_db),
            ]

            self._tx_count += 1
            logger.info(
                "TX #%d START: %d Hz, %d dB, %.1fs",
                self._tx_count,
                req.freq_hz,
                req.gain_db,
                req.duration_s,
            )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._active_tx = proc

            # Hardware kill after duration
            try:
                _, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=req.duration_s + 2,
                )
            except asyncio.TimeoutError:
                proc.terminate()
                await proc.wait()
                logger.warning("TX #%d KILLED (timeout)", self._tx_count)

            self._active_tx = None
            logger.info("TX #%d COMPLETE", self._tx_count)

            return {
                "status": "completed",
                "tx_num": self._tx_count,
                "freq_hz": req.freq_hz,
                "gain_db": req.gain_db,
                "duration_s": req.duration_s,
            }

        except Exception as e:
            logger.error("TX error: %s", e)
            return {"status": "error", "reason": str(e)}
        finally:
            hackrf.status = "free"
            hackrf.assigned_task = ""

    async def stop_tx(self):
        """Emergency stop current transmission."""
        if self._active_tx:
            self._active_tx.terminate()
            self._active_tx = None
            logger.warning("TX EMERGENCY STOP")
            return True
        return False

    def _generate_waveform(self, req: TXRequest) -> str:
        """Generate IQ file for built-in waveform types."""
        num_samples = int(req.sample_rate * req.duration_s)
        t = np.arange(num_samples, dtype=np.float32) / req.sample_rate

        if req.waveform == "tone":
            # CW tone (DC — appears at center freq)
            iq = np.ones(num_samples, dtype=np.complex64) * 0.5

        elif req.waveform == "fm":
            # FM carrier with 1kHz tone
            mod_freq = 1000
            deviation = 5000
            phase = (
                2
                * np.pi
                * deviation
                * np.cumsum(np.sin(2 * np.pi * mod_freq * t))
                / req.sample_rate
            )
            iq = (0.5 * np.exp(1j * phase)).astype(np.complex64)

        elif req.waveform == "sweep":
            # Swept tone for DF calibration
            sweep_bw = 100000  # 100 kHz sweep
            phase = (
                2
                * np.pi
                * np.cumsum(np.linspace(-sweep_bw / 2, sweep_bw / 2, num_samples))
                / req.sample_rate
            )
            iq = (0.5 * np.exp(1j * phase)).astype(np.complex64)

        else:
            return ""

        # Write to temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".cf32", delete=False)
        iq.tofile(tmp.name)
        tmp.close()
        return tmp.name

    async def _log_tx(self, req: TXRequest, approved: bool, reason: str):
        """Audit log every TX attempt."""
        try:
            session_factory = get_session_factory(self._db_path)
            async with session_factory() as session:
                log = TXLog(
                    freq_mhz=req.freq_hz / 1e6,
                    gain_db=req.gain_db,
                    duration_s=req.duration_s,
                    tx_type=req.waveform or "replay",
                    file_path=req.iq_file,
                    result="success" if approved else "rejected",
                    rejection_reason="" if approved else reason,
                    metadata_={"operator": req.operator, "rf_amp": req.rf_amp},
                )
                session.add(log)
                await session.commit()
        except Exception as e:
            logger.error("TX audit log error: %s", e)

    def get_status(self):
        return {
            "enabled": self._enabled,
            "active": self._active_tx is not None,
            "tx_count": self._tx_count,
            "max_gain_db": self._max_gain,
            "max_duration_s": self._max_duration,
            "authorized_bands": [
                {"low_mhz": b[0], "high_mhz": b[1]} for b in self._authorized_bands
            ],
        }
