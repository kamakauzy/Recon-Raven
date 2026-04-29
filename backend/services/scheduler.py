"""
Scheduler — APScheduler-based cron jobs for baselines, diffs, reports, health checks.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..db.database import get_session_factory
from ..db.models import Baseline, BaselineDiff, Report

logger = logging.getLogger("raven.scheduler")


class RavenScheduler:
    def __init__(self, settings, capture_service, device_manager, db_path: str):
        self._settings = settings
        self._capture = capture_service
        self._dm = device_manager
        self._db_path = db_path
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._engine_dir = settings.engine_dir or str(
            Path(__file__).parent.parent.parent / "engine"
        )

    def start(self):
        """Register all scheduled jobs and start the scheduler."""
        sched_cfg = self._settings.scheduler

        # Baseline capture — default every 6 hours
        cron_parts = sched_cfg.baseline_cron.split()
        if len(cron_parts) == 5:
            trigger = CronTrigger(
                minute=cron_parts[0],
                hour=cron_parts[1],
                day=cron_parts[2],
                month=cron_parts[3],
                day_of_week=cron_parts[4],
            )
        else:
            trigger = IntervalTrigger(hours=6)

        self._scheduler.add_job(
            self._run_baseline,
            trigger=trigger,
            id="baseline_capture",
            name="Scheduled baseline capture",
            replace_existing=True,
        )

        # Health check — every N seconds
        self._scheduler.add_job(
            self._run_health_check,
            trigger=IntervalTrigger(
                seconds=self._settings.devices.health_check_interval
            ),
            id="health_check",
            name="Device health check",
            replace_existing=True,
        )

        # Auto-report — daily
        report_parts = sched_cfg.report_cron.split()
        if len(report_parts) == 5 and sched_cfg.auto_report:
            report_trigger = CronTrigger(
                minute=report_parts[0],
                hour=report_parts[1],
                day=report_parts[2],
                month=report_parts[3],
                day_of_week=report_parts[4],
            )
            self._scheduler.add_job(
                self._run_auto_report,
                trigger=report_trigger,
                id="auto_report",
                name="Daily intel report",
                replace_existing=True,
            )

        self._scheduler.start()
        logger.info("Scheduler started — %d job(s)", len(self._scheduler.get_jobs()))

    def stop(self):
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    def get_jobs(self):
        """Return list of scheduled jobs as dicts."""
        jobs = []
        for job in self._scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat()
                    if job.next_run_time
                    else None,
                    "paused": job.next_run_time is None,
                }
            )
        return jobs

    def trigger_job(self, job_id: str):
        """Manually trigger a job now."""
        job = self._scheduler.get_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        job.modify(next_run_time=datetime.now(timezone.utc))
        logger.info("Manually triggered job: %s", job_id)

    def pause_job(self, job_id: str):
        self._scheduler.pause_job(job_id)
        logger.info("Paused job: %s", job_id)

    def resume_job(self, job_id: str):
        self._scheduler.resume_job(job_id)
        logger.info("Resumed job: %s", job_id)

    # ── Job implementations ──────────────────────────────────────────────

    async def _run_baseline(self):
        """Capture a baseline using rtl_433 on the first free SDR."""
        logger.info("Starting scheduled baseline capture")
        sched_cfg = self._settings.scheduler
        cap_cfg = self._settings.capture

        # Find a free SDR
        free_dev = self._dm.get_free_device("rtlsdr")
        if not free_dev:
            logger.warning("No free RTL-SDR for baseline capture — skipping")
            return

        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_file = os.path.join(cap_cfg.baseline_dir, f"baseline_{ts}.csv")

        # Build rtl_433 command
        freq_args = []
        for f in sched_cfg.baseline_frequencies:
            freq_args.extend(["-f", f"{f}M"])

        cmd = [
            "rtl_433",
            *freq_args,
            "-d",
            str(free_dev.index),
            "-F",
            f"csv:{out_file}",
            "-T",
            str(sched_cfg.baseline_duration),
        ]

        # Mark device busy
        free_dev.status = "busy"
        free_dev.assigned_task = "baseline:scheduled"

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=sched_cfg.baseline_duration + 30,
            )

            if proc.returncode != 0:
                logger.error(
                    "Baseline capture failed: %s", stderr.decode(errors="replace")[:500]
                )
                return

            # Count lines in output
            line_count = 0
            if Path(out_file).exists():
                with open(out_file) as f:
                    line_count = sum(1 for _ in f) - 1  # minus header

            # Persist to DB
            session_factory = get_session_factory(self._db_path)
            async with session_factory() as session:
                baseline = Baseline(
                    filepath=out_file,
                    device_count=line_count,
                    duration_s=sched_cfg.baseline_duration,
                )
                session.add(baseline)
                await session.commit()
                baseline_id = baseline.id

            logger.info("Baseline captured: %s (%d signals)", out_file, line_count)

            # Auto-diff if enabled
            if sched_cfg.auto_diff:
                await self._run_auto_diff(baseline_id, out_file)

        except asyncio.TimeoutError:
            logger.error("Baseline capture timed out")
        except Exception as e:
            logger.error("Baseline capture error: %s", e)
        finally:
            free_dev.status = "free"
            free_dev.assigned_task = ""

    async def _run_auto_diff(self, new_baseline_id: int, new_file: str):
        """Diff the latest baseline against the previous one."""
        session_factory = get_session_factory(self._db_path)
        async with session_factory() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(Baseline).order_by(Baseline.timestamp.desc()).limit(2)
            )
            baselines = result.scalars().all()

        if len(baselines) < 2:
            logger.info("No previous baseline for diff — skipping")
            return

        old_baseline = baselines[1]  # previous
        old_file = old_baseline.filepath

        if not Path(old_file).exists():
            logger.warning("Previous baseline file missing: %s", old_file)
            return

        # Run baseline_diff.py
        diff_script = os.path.join(self._engine_dir, "baseline_diff.py")
        cmd = [
            "/usr/bin/python3",
            diff_script,
            "--old",
            old_file,
            "--new",
            new_file,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            report_text = stdout.decode(errors="replace")

            # Parse counts from diff output
            new_signals = report_text.count("NEW SIGNAL")
            disappeared = report_text.count("DISAPPEARED")
            power_changes = report_text.count("POWER CHANGE")
            rate_changes = report_text.count("RATE CHANGE")

            # Persist diff
            session_factory = get_session_factory(self._db_path)
            async with session_factory() as session:
                diff = BaselineDiff(
                    old_baseline_id=old_baseline.id,
                    new_baseline_id=new_baseline_id,
                    new_signals=new_signals,
                    disappeared=disappeared,
                    power_changes=power_changes,
                    rate_changes=rate_changes,
                    report_text=report_text,
                )
                session.add(diff)
                await session.commit()

            logger.info(
                "Baseline diff: +%d new, -%d gone, %d power, %d rate",
                new_signals,
                disappeared,
                power_changes,
                rate_changes,
            )

        except Exception as e:
            logger.error("Baseline diff error: %s", e)

    async def _run_auto_report(self):
        """Generate daily intel report using intel_packager."""
        logger.info("Generating daily intel report")
        cap_cfg = self._settings.capture

        ts = datetime.now(timezone.utc).strftime("%Y%m%d")
        report_file = os.path.join(cap_cfg.report_dir, f"report_{ts}.md")

        report_script = os.path.join(self._engine_dir, "intel_packager.py")
        cmd = [
            "/usr/bin/python3",
            report_script,
            "--log-dir",
            cap_cfg.log_dir,
            "--baseline-dir",
            cap_cfg.baseline_dir,
            "--output",
            report_file,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

            if proc.returncode != 0:
                logger.error(
                    "Report generation failed: %s",
                    stderr.decode(errors="replace")[:500],
                )
                return

            # Persist report record
            session_factory = get_session_factory(self._db_path)
            async with session_factory() as session:
                report = Report(
                    filepath=report_file,
                    title=f"Daily Report — {ts}",
                    auto_generated=True,
                )
                session.add(report)
                await session.commit()

            logger.info("Report generated: %s", report_file)

        except Exception as e:
            logger.error("Report generation error: %s", e)

    async def _run_health_check(self):
        """Check health of all devices."""
        try:
            results = await self._dm.health_check_all()
            unhealthy = [r for r in results if not r.get("healthy", True)]
            if unhealthy:
                logger.warning(
                    "Unhealthy devices: %s",
                    ", ".join(str(r.get("sdr_index")) for r in unhealthy),
                )
        except Exception as e:
            logger.error("Health check error: %s", e)
