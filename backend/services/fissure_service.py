"""
FISSURE integration — protocol DB queries from extracted SOI data.

Loads protocol/SOI data from data/fissure_protocols.json (extracted from
FISSURE's old_library_3_10.yaml).
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("raven.fissure")

# Path to extracted protocol JSON (relative to project root)
_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_PROTOCOL_JSON = _DATA_DIR / "fissure_protocols.json"


class FissureService:
    def __init__(self, settings):
        self._install_path = Path(settings.fissure.install_path)
        self._enabled = settings.fissure.enabled
        self._protocols: List[Dict] = []
        self._available = False

        if self._enabled:
            self._load_protocol_db()

    def _load_protocol_db(self):
        """Load protocol SOI data from extracted JSON."""
        if _PROTOCOL_JSON.exists():
            try:
                with open(_PROTOCOL_JSON, "r") as f:
                    self._protocols = json.load(f)
                self._available = True
                logger.info(
                    "Loaded %d FISSURE protocol entries from %s",
                    len(self._protocols),
                    _PROTOCOL_JSON,
                )
            except Exception as e:
                logger.error("Failed to load FISSURE protocol JSON: %s", e)
                self._available = False
        else:
            logger.warning("FISSURE protocol JSON not found at %s", _PROTOCOL_JSON)
            self._available = False

    def get_status(self) -> Dict:
        return {
            "available": self._available,
            "protocol_count": len(self._protocols),
            "install_path": str(self._install_path),
            "full_install": self._install_path.exists()
            and (self._install_path / "fissure").exists(),
        }

    def list_protocols(self, search: str = "") -> List[Dict]:
        """List protocols, optionally filtered by search term."""
        if not search:
            return self._protocols[:200]

        search_lower = search.lower()
        return [
            p
            for p in self._protocols
            if search_lower in p.get("protocol", "").lower()
            or search_lower in p.get("soi_name", "").lower()
            or search_lower in p.get("modulation", "").lower()
            or search_lower in str(p.get("frequency_mhz", "")).lower()
        ][:200]

    def query_protocol(
        self, freq_mhz: float, modulation: str = "", bandwidth_khz: float = 0
    ) -> List[Dict]:
        """Query protocols matching given signal parameters."""
        matches = []
        for p in self._protocols:
            score = 0

            # Frequency match — check if freq falls within start/end range
            p_freq = p.get("frequency_mhz")
            p_start = p.get("start_frequency_mhz")
            p_end = p.get("end_frequency_mhz")

            if p_start is not None and p_end is not None:
                if p_start <= freq_mhz <= p_end:
                    score += 60
                elif abs((p_start + p_end) / 2 - freq_mhz) < 10:
                    score += 30
            elif p_freq is not None:
                diff = abs(p_freq - freq_mhz)
                if diff < 1:
                    score += 60
                elif diff < 5:
                    score += 40
                elif diff < 20:
                    score += 20

            # Modulation match
            if modulation:
                p_mod = p.get("modulation", "")
                if modulation.upper() in p_mod.upper():
                    score += 30

            # Bandwidth match
            if bandwidth_khz > 0 and p.get("bandwidth_mhz"):
                p_bw_khz = p["bandwidth_mhz"] * 1000
                if abs(p_bw_khz - bandwidth_khz) < bandwidth_khz * 0.5:
                    score += 10

            if score > 0:
                matches.append({**p, "match_score": score})

        matches.sort(key=lambda x: x["match_score"], reverse=True)
        return matches[:20]

    def get_demod_flowgraphs(self, protocol: str = "") -> List[Dict]:
        """Find demodulation flowgraphs for a protocol."""
        if not self._install_path.exists():
            return []

        lib_path = self._install_path / "Flow Graph Library"
        if not lib_path.exists():
            return []

        flowgraphs = []
        for grc in lib_path.rglob("*.grc"):
            if "demod" in grc.stem.lower() or "rx" in grc.stem.lower():
                if not protocol or protocol.lower() in grc.stem.lower():
                    flowgraphs.append(
                        {
                            "name": grc.stem,
                            "path": str(grc),
                            "type": "demodulation",
                        }
                    )

        for py in lib_path.rglob("*.py"):
            if "demod" in py.stem.lower() or "rx" in py.stem.lower():
                if not protocol or protocol.lower() in py.stem.lower():
                    flowgraphs.append(
                        {
                            "name": py.stem,
                            "path": str(py),
                            "type": "demodulation",
                        }
                    )

        return flowgraphs[:50]

    def get_attack_flowgraphs(self, protocol: str = "") -> List[Dict]:
        """Find TX/attack flowgraphs for a protocol."""
        if not self._install_path.exists():
            return []

        lib_path = self._install_path / "Flow Graph Library"
        if not lib_path.exists():
            return []

        flowgraphs = []
        for py in lib_path.rglob("*.py"):
            if any(
                kw in py.stem.lower() for kw in ("tx", "attack", "mod", "replay", "jam")
            ):
                if not protocol or protocol.lower() in py.stem.lower():
                    flowgraphs.append(
                        {
                            "name": py.stem,
                            "path": str(py),
                            "type": "attack",
                        }
                    )

        return flowgraphs[:50]

    async def run_modulation_detection(self, iq_file: str) -> Optional[Dict]:
        """Run FISSURE's TSI modulation detector on an IQ file."""
        if not self._install_path.exists():
            return None

        tsi_scripts = list(
            (self._install_path / "Flow Graph Library").rglob("*modulation*detect*.py")
        )
        if not tsi_scripts:
            logger.warning("FISSURE TSI modulation detector not found")
            return None

        script = str(tsi_scripts[0])
        cmd = ["/usr/bin/python3", script, "--file", iq_file]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            return {"result": stdout.decode().strip(), "error": stderr.decode().strip()}
        except asyncio.TimeoutError:
            return {"error": "Modulation detection timed out"}
        except Exception as e:
            return {"error": str(e)}

    async def launch_gui(self, context: dict) -> dict:
        """Attempt to launch FISSURE GUI (requires X display on sensor node)."""
        if not self._install_path.exists():
            return {"status": "error", "message": "FISSURE not installed"}

        # FISSURE GUI requires a running X server and full install
        fissure_main = self._install_path / "fissure" / "cli.py"
        if not fissure_main.exists():
            return {
                "status": "error",
                "message": "FISSURE CLI not found — full install required",
            }

        return {
            "status": "info",
            "message": "FISSURE GUI launch requires desktop session on sensor node. "
            "SSH with X forwarding: ssh -X kama@<host> 'cd ~/Tools/FISSURE && python3 -m fissure'",
            "freq_mhz": context.get("freq_mhz", 0),
        }
