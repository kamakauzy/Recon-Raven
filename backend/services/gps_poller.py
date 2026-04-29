"""
GPS Poller — connects to gpsd, caches latest fix, persists to database.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ..db.database import get_session_factory
from ..db.models import GPSFix

logger = logging.getLogger("raven.gps")


@dataclass
class CachedFix:
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[float] = None
    speed_mps: Optional[float] = None
    heading_deg: Optional[float] = None
    error_m: Optional[float] = None
    satellites: Optional[int] = None
    timestamp: Optional[datetime] = None
    db_id: Optional[int] = None

    @property
    def has_fix(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def to_dict(self) -> dict:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude_m": self.altitude_m,
            "speed_mps": self.speed_mps,
            "heading_deg": self.heading_deg,
            "error_m": self.error_m,
            "satellites": self.satellites,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "has_fix": self.has_fix,
        }


class GPSPoller:
    def __init__(
        self,
        db_path: str,
        host: str = "127.0.0.1",
        port: int = 2947,
        poll_interval: float = 2.0,
    ):
        self._db_path = db_path
        self._host = host
        self._port = port
        self._poll_interval = poll_interval
        self._current_fix = CachedFix()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._connected = False

    @property
    def current_fix(self) -> CachedFix:
        return self._current_fix

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self):
        """Start the GPS polling background task."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("GPS poller started (gpsd @ %s:%d)", self._host, self._port)

    async def stop(self):
        """Stop the GPS polling task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("GPS poller stopped")

    async def _poll_loop(self):
        """Main polling loop — connects to gpsd and reads TPV sentences."""
        while self._running:
            try:
                reader, writer = await asyncio.open_connection(self._host, self._port)
                self._connected = True
                logger.info("Connected to gpsd")

                # Enable JSON streaming
                writer.write(b'?WATCH={"enable":true,"json":true}\n')
                await writer.drain()

                while self._running:
                    try:
                        line = await asyncio.wait_for(
                            reader.readline(), timeout=self._poll_interval * 3
                        )
                        if not line:
                            break

                        data = json.loads(line.decode(errors="replace"))
                        if data.get("class") == "TPV":
                            await self._handle_tpv(data)
                        elif data.get("class") == "SKY":
                            self._handle_sky(data)

                    except asyncio.TimeoutError:
                        continue
                    except json.JSONDecodeError:
                        continue

                writer.close()
                await writer.wait_closed()

            except (ConnectionRefusedError, OSError) as e:
                self._connected = False
                logger.warning("gpsd not available (%s) — retrying in 10s", e)
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                logger.error("GPS poller error: %s", e)
                await asyncio.sleep(10)

    async def _handle_tpv(self, data: dict):
        """Process a TPV (Time-Position-Velocity) sentence."""
        lat = data.get("lat")
        lon = data.get("lon")

        if lat is None or lon is None:
            return

        # Parse 'n/a' values that gpsd sometimes returns
        def _val(key):
            v = data.get(key)
            if v is None or v == "n/a":
                return None
            try:
                return float(v)
            except (ValueError, TypeError):
                return None

        self._current_fix = CachedFix(
            latitude=lat,
            longitude=lon,
            altitude_m=_val("alt"),
            speed_mps=_val("speed"),
            heading_deg=_val("track"),
            error_m=_val("epx"),  # horizontal error
            satellites=self._current_fix.satellites,  # from SKY
            timestamp=datetime.now(timezone.utc),
        )

        # Persist to DB
        await self._persist_fix()

    def _handle_sky(self, data: dict):
        """Process satellite count from SKY sentence."""
        sats = data.get("nSat") or data.get("uSat")
        if sats is not None:
            self._current_fix.satellites = int(sats)

    async def _persist_fix(self):
        """Save current fix to database."""
        fix = self._current_fix
        if not fix.has_fix:
            return

        try:
            session_factory = get_session_factory(self._db_path)
            async with session_factory() as session:
                db_fix = GPSFix(
                    timestamp=fix.timestamp,
                    latitude=fix.latitude,
                    longitude=fix.longitude,
                    altitude_m=fix.altitude_m,
                    speed_mps=fix.speed_mps,
                    heading_deg=fix.heading_deg,
                    error_m=fix.error_m,
                    satellites=fix.satellites,
                )
                session.add(db_fix)
                await session.commit()
                fix.db_id = db_fix.id
        except Exception as e:
            logger.debug("Failed to persist GPS fix: %s", e)

    async def get_latest_fix_id(self) -> Optional[int]:
        """Return the DB id of the most recent GPS fix, or None."""
        return self._current_fix.db_id if self._current_fix.has_fix else None
