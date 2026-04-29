"""
SDR Device Manager — enumerates, pools, and health-checks RTL-SDR and HackRF devices.
"""
import asyncio
import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..db.database import get_session_factory
from ..db.models import Device

logger = logging.getLogger("raven.devices")


@dataclass
class SDRDevice:
    index: int
    serial: str
    model: str
    device_type: str  # "rtlsdr" or "hackrf"
    usb_bus: str = ""
    status: str = "free"  # free | busy | error | offline
    assigned_task: str = ""
    db_id: Optional[int] = None


class DeviceManager:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._devices: Dict[int, SDRDevice] = {}
        self._locks: Dict[int, asyncio.Lock] = {}
        self._hackrf_devices: List[SDRDevice] = []

    async def enumerate(self) -> List[SDRDevice]:
        """Detect all connected SDR devices."""
        rtl_devices = await self._enumerate_rtlsdr()
        hackrf_devices = await self._enumerate_hackrf()

        self._devices.clear()
        self._locks.clear()
        self._hackrf_devices.clear()

        for dev in rtl_devices:
            self._devices[dev.index] = dev
            self._locks[dev.index] = asyncio.Lock()

        # HackRF gets indices starting after RTL-SDRs (offset by 100)
        for i, dev in enumerate(hackrf_devices):
            idx = 100 + i
            dev.index = idx
            self._hackrf_devices.append(dev)
            self._devices[idx] = dev
            self._locks[idx] = asyncio.Lock()

        # Sync to database
        await self._sync_db()

        logger.info(
            "Enumerated %d RTL-SDR(s), %d HackRF(s)",
            len(rtl_devices), len(hackrf_devices),
        )
        return list(self._devices.values())

    async def _enumerate_rtlsdr(self) -> List[SDRDevice]:
        """Parse rtl_test output for connected RTL-SDR devices."""
        devices = []
        try:
            proc = await asyncio.create_subprocess_exec(
                "rtl_test", "-t",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            # rtl_test -t hangs doing a tuner test; give it 5 seconds
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                # rtl_test writes device info to stderr before the tuner test
                stderr = b""

            # Also try rtl_eeprom for device listing
            proc2 = await asyncio.create_subprocess_exec(
                "rtl_test", "-d", "99",  # nonexistent device forces device listing
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr2 = await asyncio.wait_for(proc2.communicate(), timeout=3)
            except asyncio.TimeoutError:
                proc2.kill()
                await proc2.wait()
                stderr2 = b""

            combined = (stderr + stderr2).decode(errors="replace")

            # Parse lines like:
            #   0:  RTLSDRBlog, Blog V4, SN: 00000002
            for m in re.finditer(
                r"(\d+):\s+(\S.*?),\s+(\S.*?),\s+SN:\s+(\S+)", combined
            ):
                idx = int(m.group(1))
                manufacturer = m.group(2).strip()
                product = m.group(3).strip()
                serial = m.group(4).strip()
                devices.append(SDRDevice(
                    index=idx,
                    serial=serial,
                    model=f"{manufacturer} {product}",
                    device_type="rtlsdr",
                ))
        except FileNotFoundError:
            logger.warning("rtl_test not found — RTL-SDR enumeration skipped")
        except Exception as e:
            logger.error("RTL-SDR enumeration failed: %s", e)

        return devices

    async def _enumerate_hackrf(self) -> List[SDRDevice]:
        """Parse hackrf_info output for connected HackRF devices."""
        devices = []
        try:
            proc = await asyncio.create_subprocess_exec(
                "hackrf_info",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            output = stdout.decode(errors="replace")

            # Parse serial numbers
            for m in re.finditer(r"Serial number:\s+(\S+)", output):
                serial = m.group(1)
                devices.append(SDRDevice(
                    index=0,  # re-assigned later
                    serial=serial,
                    model="HackRF One",
                    device_type="hackrf",
                ))
        except FileNotFoundError:
            logger.debug("hackrf_info not found — HackRF enumeration skipped")
        except asyncio.TimeoutError:
            logger.warning("hackrf_info timed out")
        except Exception as e:
            logger.error("HackRF enumeration failed: %s", e)

        return devices

    async def _sync_db(self):
        """Write current device state to database."""
        session_factory = get_session_factory(self._db_path)
        async with session_factory() as session:
            for dev in self._devices.values():
                db_dev = Device(
                    sdr_index=dev.index,
                    serial=dev.serial,
                    model=dev.model,
                    device_type=dev.device_type,
                    usb_bus=dev.usb_bus,
                    status="free",
                    last_seen=datetime.now(timezone.utc),
                )
                session.add(db_dev)
            await session.commit()

            # Read back IDs
            from sqlalchemy import select
            result = await session.execute(select(Device))
            for db_dev in result.scalars():
                if db_dev.sdr_index in self._devices:
                    self._devices[db_dev.sdr_index].db_id = db_dev.id

    @asynccontextmanager
    async def acquire(self, sdr_index: int):
        """Acquire exclusive access to an SDR device."""
        if sdr_index not in self._devices:
            raise ValueError(f"No device with index {sdr_index}")

        dev = self._devices[sdr_index]
        lock = self._locks[sdr_index]

        if lock.locked():
            raise RuntimeError(f"Device {sdr_index} is busy (task: {dev.assigned_task})")

        async with lock:
            dev.status = "busy"
            try:
                yield dev
            finally:
                dev.status = "free"
                dev.assigned_task = ""

    def get_device(self, sdr_index: int) -> Optional[SDRDevice]:
        return self._devices.get(sdr_index)

    def list_devices(self) -> List[SDRDevice]:
        return list(self._devices.values())

    def is_busy(self, sdr_index: int) -> bool:
        lock = self._locks.get(sdr_index)
        return lock.locked() if lock else False

    async def health_check(self, sdr_index: int) -> bool:
        """Quick health check — try to briefly access the device."""
        dev = self._devices.get(sdr_index)
        if dev is None:
            return False

        if dev.device_type == "rtlsdr":
            return await self._rtl_health(sdr_index)
        elif dev.device_type == "hackrf":
            return await self._hackrf_health()
        return False

    async def _rtl_health(self, index: int) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "rtl_test", "-d", str(index), "-t",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                # If it started the tuner test, device is alive
                return True
            return proc.returncode == 0 or b"Found" in stderr
        except Exception:
            return False

    async def _hackrf_health(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "hackrf_info",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            return b"Serial number" in stdout
        except Exception:
            return False

    async def health_check_all(self):
        """Run health check on all devices, update status."""
        for idx, dev in self._devices.items():
            if dev.status == "busy":
                continue
            healthy = await self.health_check(idx)
            dev.status = "free" if healthy else "error"
            dev.last_seen = datetime.now(timezone.utc) if healthy else dev.last_seen
            logger.debug("Health check device %d (%s): %s", idx, dev.model, dev.status)
