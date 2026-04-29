"""
Capture Service — wraps engine scripts as managed async subprocesses.
"""

import asyncio
import json
import logging
import os
import signal
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..db.database import get_session_factory
from ..db.models import Event

logger = logging.getLogger("raven.capture")

TASK_SCRIPTS = {
    "burst_detect": "burst_detector.py",
    "squelch_record": "squelch_recorder.py",
    "power_sweep": "power_logger.py",
    "signal_alert": "signal_alerter.py",
    "baseline_capture": None,  # uses rtl_433 directly
}


@dataclass
class CaptureTask:
    task_id: str
    task_type: str
    sdr_index: int
    freq_mhz: float
    started_at: datetime
    pid: Optional[int] = None
    status: str = "running"  # running | stopped | error | completed
    process: Optional[asyncio.subprocess.Process] = None
    output_file: str = ""
    log_file: str = ""
    extra_args: Dict = field(default_factory=dict)


class CaptureService:
    def __init__(
        self,
        engine_dir: str,
        device_manager,
        gps_poller,
        db_path: str,
        capture_config,
        classifier=None,
    ):
        self._engine_dir = engine_dir
        self._dm = device_manager
        self._gps = gps_poller
        self._db_path = db_path
        self._config = capture_config
        self._tasks: Dict[str, CaptureTask] = {}
        self._event_callback: Optional[Callable] = None
        self._classifier = classifier

    def set_event_callback(self, cb: Callable):
        """Set callback for real-time event broadcasting (WebSocket push)."""
        self._event_callback = cb

    async def start_capture(
        self,
        task_type: str,
        sdr_index: int,
        freq_mhz: float,
        duration: int = 0,
        **kwargs,
    ) -> CaptureTask:
        """Start a capture task on a specific SDR."""
        if task_type not in TASK_SCRIPTS:
            raise ValueError(f"Unknown task type: {task_type}")

        if self._dm.is_busy(sdr_index):
            dev = self._dm.get_device(sdr_index)
            raise RuntimeError(
                f"Device {sdr_index} busy (task: {dev.assigned_task if dev else 'unknown'})"
            )

        task_id = str(uuid.uuid4())[:8]
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

        task = CaptureTask(
            task_id=task_id,
            task_type=task_type,
            sdr_index=sdr_index,
            freq_mhz=freq_mhz,
            started_at=datetime.now(timezone.utc),
            extra_args=kwargs,
        )

        if task_type == "baseline_capture":
            await self._start_baseline(task, duration, ts)
        else:
            await self._start_engine_script(task, duration, ts, **kwargs)

        self._tasks[task_id] = task
        logger.info(
            "Started %s (id=%s) on SDR %d @ %.4f MHz",
            task_type,
            task_id,
            sdr_index,
            freq_mhz,
        )
        return task

    async def _start_engine_script(
        self, task: CaptureTask, duration: int, ts: str, **kwargs
    ):
        """Launch an engine script as a subprocess."""
        script = TASK_SCRIPTS[task.task_type]
        script_path = str(Path(self._engine_dir) / script)

        # Use system python3 — GNU Radio + osmosdr are system packages
        # power_sweep (power_logger) uses different args than GNU Radio scripts
        if task.task_type == "power_sweep":
            cmd = [
                "/usr/bin/python3",
                script_path,
                "-l",
                str(kwargs.get("freq_low", task.freq_mhz - 5)),
                "-u",
                str(kwargs.get("freq_high", task.freq_mhz + 5)),
                "-g",
                str(kwargs.get("gain", self._config.default_gain)),
                "-o",
                self._config.log_dir,
                "--device",
                str(task.sdr_index),
                "--json-events",
            ]
            if duration > 0:
                cmd.extend(["--duration", str(duration)])
        else:
            cmd = [
                "/usr/bin/python3",
                script_path,
                "-f",
                str(task.freq_mhz),
                "-g",
                str(kwargs.get("gain", self._config.default_gain)),
                "-d",
                str(task.sdr_index),
                "--json-events",
            ]

        # Task-specific args
        if task.task_type == "burst_detect":
            log_file = os.path.join(
                self._config.log_dir, f"bursts_{task.task_id}_{ts}.csv"
            )
            cmd.extend(["--log", log_file])
            task.log_file = log_file

        elif task.task_type == "squelch_record":
            out_dir = os.path.join(self._config.output_dir, f"squelch_{ts}")
            cmd.extend(["-o", out_dir, "--headless"])
            task.output_file = out_dir

        elif task.task_type == "signal_alert":
            log_file = os.path.join(
                self._config.log_dir, f"alerts_{task.task_id}_{ts}.csv"
            )
            cmd.extend(
                [
                    "--log",
                    log_file,
                    "--threshold",
                    str(kwargs.get("threshold", -40)),
                ]
            )
            task.log_file = log_file

        # Squelch threshold
        if "squelch" in kwargs and task.task_type in ("burst_detect", "squelch_record"):
            cmd.extend(["-s", str(kwargs["squelch"])])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        task.process = proc
        task.pid = proc.pid

        # Mark device busy
        dev = self._dm.get_device(task.sdr_index)
        if dev:
            dev.status = "busy"
            dev.assigned_task = f"{task.task_type}:{task.task_id}"

        # Start output reader
        asyncio.create_task(self._read_output(task))

        # Schedule auto-stop after duration (if specified)
        if duration > 0:
            asyncio.create_task(self._auto_stop(task, duration))

    async def _auto_stop(self, task: CaptureTask, duration: int):
        """Auto-stop a capture after the specified duration."""
        await asyncio.sleep(duration)
        if task.status == "running":
            logger.info("Auto-stopping %s after %ds", task.task_id, duration)
            await self.stop_capture(task.task_id)

    async def _start_baseline(self, task: CaptureTask, duration: int, ts: str):
        """Run rtl_433 baseline capture."""
        duration = duration or 120
        out_file = os.path.join(self._config.baseline_dir, f"baseline_{ts}.csv")
        task.output_file = out_file

        freq_args = []
        for f in (task.freq_mhz, 315.0):
            freq_args.extend(["-f", f"{f}M"])

        cmd = [
            "rtl_433",
            *freq_args,
            "-d",
            str(task.sdr_index),
            "-F",
            f"csv:{out_file}",
            "-T",
            str(duration),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        task.process = proc
        task.pid = proc.pid

        dev = self._dm.get_device(task.sdr_index)
        if dev:
            dev.status = "busy"
            dev.assigned_task = f"baseline:{task.task_id}"

        asyncio.create_task(self._wait_completion(task))

    async def _read_output(self, task: CaptureTask):
        """Read stdout from engine script, parse JSON events."""
        try:
            async for line in task.process.stdout:
                text = line.decode(errors="replace").strip()
                if not text:
                    continue

                # Try to parse as JSON event (from --json-events flag)
                if text.startswith("{"):
                    try:
                        event_data = json.loads(text)
                        await self._handle_event(task, event_data)
                    except json.JSONDecodeError:
                        pass

            await task.process.wait()
            task.status = "completed" if task.process.returncode == 0 else "error"
        except Exception as e:
            logger.error("Output reader error for %s: %s", task.task_id, e)
            task.status = "error"
        finally:
            self._release_device(task)

    async def _wait_completion(self, task: CaptureTask):
        """Wait for a subprocess to complete."""
        try:
            await task.process.wait()
            task.status = "completed" if task.process.returncode == 0 else "error"
        except Exception as e:
            logger.error("Wait error for %s: %s", task.task_id, e)
            task.status = "error"
        finally:
            self._release_device(task)

    async def _handle_event(self, task: CaptureTask, event_data: dict):
        """Process a real-time event from an engine script."""
        # Spectrum frames are ephemeral — broadcast only, don't persist to DB
        if event_data.get("event_type") == "spectrum":
            if self._event_callback:
                await self._event_callback(event_data)
            return

        session_factory = get_session_factory(self._db_path)
        async with session_factory() as session:
            gps_fix_id = await self._gps.get_latest_fix_id()
            dev = self._dm.get_device(task.sdr_index)

            event = Event(
                event_type=event_data.get("event_type", task.task_type),
                freq_mhz=event_data.get("freq_mhz", task.freq_mhz),
                duration_ms=event_data.get("duration_ms"),
                peak_power_db=event_data.get(
                    "peak_power_db", event_data.get("power_db")
                ),
                device_id=dev.db_id if dev else None,
                gps_fix_id=gps_fix_id,
                metadata_=event_data,
            )
            session.add(event)
            await session.commit()

        # Classify the event
        if self._classifier:
            try:
                result = self._classifier.classify(event_data)
                event_data["classification"] = result.to_dict()
            except Exception as e:
                logger.debug("Classification failed: %s", e)

        # Broadcast via WebSocket callback
        if self._event_callback:
            await self._event_callback(event_data)

    def _release_device(self, task: CaptureTask):
        dev = self._dm.get_device(task.sdr_index)
        if dev:
            dev.status = "free"
            dev.assigned_task = ""

    async def stop_capture(self, task_id: str) -> bool:
        """Stop a running capture task."""
        task = self._tasks.get(task_id)
        if not task or task.status != "running":
            return False

        if task.process and task.process.returncode is None:
            task.process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(task.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                task.process.kill()
                await task.process.wait()

        task.status = "stopped"
        self._release_device(task)
        logger.info("Stopped capture %s", task_id)
        return True

    def list_active(self) -> List[CaptureTask]:
        return [t for t in self._tasks.values() if t.status == "running"]

    def get_task(self, task_id: str) -> Optional[CaptureTask]:
        return self._tasks.get(task_id)
