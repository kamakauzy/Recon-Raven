"""
REST API routes for Recon-Raven.
"""
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Baseline, BaselineDiff, Device, Event, GPSFix, Report

router = APIRouter(prefix="/api")


# ── Pydantic schemas ─────────────────────────────────────────

class DeviceOut(BaseModel):
    id: int
    sdr_index: int
    serial: str
    model: str
    device_type: str
    status: str
    assigned_task: str

    class Config:
        from_attributes = True


class CaptureStartRequest(BaseModel):
    task_type: str
    sdr_index: int
    freq_mhz: float
    duration: int = 0
    gain: float = 38.0
    squelch: float = -40.0
    threshold: float = -40.0
    freq_low: Optional[float] = None
    freq_high: Optional[float] = None


class CaptureOut(BaseModel):
    task_id: str
    task_type: str
    sdr_index: int
    freq_mhz: float
    status: str
    started_at: str
    output_file: str


class EventOut(BaseModel):
    id: int
    timestamp: str
    event_type: str
    freq_mhz: Optional[float]
    duration_ms: Optional[float]
    peak_power_db: Optional[float]
    device_id: Optional[int]

    class Config:
        from_attributes = True


class BaselineOut(BaseModel):
    id: int
    timestamp: str
    filepath: str
    device_count: int
    duration_s: int

    class Config:
        from_attributes = True


class GPSOut(BaseModel):
    latitude: Optional[float]
    longitude: Optional[float]
    altitude_m: Optional[float]
    speed_mps: Optional[float]
    heading_deg: Optional[float]
    error_m: Optional[float]
    satellites: Optional[int]
    timestamp: Optional[str]
    has_fix: bool


class ReportOut(BaseModel):
    id: int
    timestamp: str
    filepath: str
    title: str
    event_count: int
    auto_generated: bool

    class Config:
        from_attributes = True


class HealthOut(BaseModel):
    status: str
    version: str
    uptime_s: float
    devices: int
    gps_connected: bool
    active_captures: int


# ── Dependency for DB session ────────────────────────────────

_session_factory = None
_start_time = datetime.now(timezone.utc)


def set_session_factory(sf):
    global _session_factory
    _session_factory = sf


async def get_db() -> AsyncSession:
    async with _session_factory() as session:
        yield session


# ── Service references (set by main.py on startup) ──────────

_device_manager = None
_gps_poller = None
_capture_service = None


def set_services(dm, gps, capture):
    global _device_manager, _gps_poller, _capture_service
    _device_manager = dm
    _gps_poller = gps
    _capture_service = capture


# ── Health ───────────────────────────────────────────────────

@router.get("/health", response_model=HealthOut)
async def health():
    uptime = (datetime.now(timezone.utc) - _start_time).total_seconds()
    return HealthOut(
        status="ok",
        version="0.1.0",
        uptime_s=uptime,
        devices=len(_device_manager.list_devices()) if _device_manager else 0,
        gps_connected=_gps_poller.connected if _gps_poller else False,
        active_captures=len(_capture_service.list_active()) if _capture_service else 0,
    )


# ── Devices ──────────────────────────────────────────────────

@router.get("/devices")
async def list_devices():
    if not _device_manager:
        return []
    devices = _device_manager.list_devices()
    return [
        DeviceOut(
            id=d.db_id or 0,
            sdr_index=d.index,
            serial=d.serial,
            model=d.model,
            device_type=d.device_type,
            status=d.status,
            assigned_task=d.assigned_task,
        )
        for d in devices
    ]


@router.post("/devices/enumerate")
async def enumerate_devices():
    if not _device_manager:
        raise HTTPException(503, "Device manager not initialized")
    devices = await _device_manager.enumerate()
    return {"count": len(devices)}


@router.get("/devices/{sdr_index}/health")
async def device_health(sdr_index: int):
    if not _device_manager:
        raise HTTPException(503, "Device manager not initialized")
    healthy = await _device_manager.health_check(sdr_index)
    return {"sdr_index": sdr_index, "healthy": healthy}


# ── GPS ──────────────────────────────────────────────────────

@router.get("/gps/current", response_model=GPSOut)
async def gps_current():
    if not _gps_poller:
        return GPSOut(has_fix=False, latitude=None, longitude=None, altitude_m=None,
                      speed_mps=None, heading_deg=None, error_m=None, satellites=None,
                      timestamp=None)
    fix = _gps_poller.current_fix
    return GPSOut(**fix.to_dict())


@router.get("/gps/history")
async def gps_history(
    limit: int = Query(100, le=1000),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(GPSFix).order_by(desc(GPSFix.timestamp)).limit(limit)
    )
    fixes = result.scalars().all()
    return [
        {
            "id": f.id,
            "timestamp": f.timestamp.isoformat() if f.timestamp else None,
            "latitude": f.latitude,
            "longitude": f.longitude,
            "altitude_m": f.altitude_m,
            "satellites": f.satellites,
        }
        for f in fixes
    ]


# ── Captures ─────────────────────────────────────────────────

@router.post("/captures/start", response_model=CaptureOut)
async def start_capture(req: CaptureStartRequest):
    if not _capture_service:
        raise HTTPException(503, "Capture service not initialized")
    try:
        task = await _capture_service.start_capture(
            task_type=req.task_type,
            sdr_index=req.sdr_index,
            freq_mhz=req.freq_mhz,
            duration=req.duration,
            gain=req.gain,
            squelch=req.squelch,
            threshold=req.threshold,
            freq_low=req.freq_low,
            freq_high=req.freq_high,
        )
        return CaptureOut(
            task_id=task.task_id,
            task_type=task.task_type,
            sdr_index=task.sdr_index,
            freq_mhz=task.freq_mhz,
            status=task.status,
            started_at=task.started_at.isoformat(),
            output_file=task.output_file,
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/captures/{task_id}/stop")
async def stop_capture(task_id: str):
    if not _capture_service:
        raise HTTPException(503, "Capture service not initialized")
    stopped = await _capture_service.stop_capture(task_id)
    if not stopped:
        raise HTTPException(404, "Task not found or not running")
    return {"task_id": task_id, "status": "stopped"}


@router.get("/captures/active")
async def list_active_captures():
    if not _capture_service:
        return []
    tasks = _capture_service.list_active()
    return [
        CaptureOut(
            task_id=t.task_id,
            task_type=t.task_type,
            sdr_index=t.sdr_index,
            freq_mhz=t.freq_mhz,
            status=t.status,
            started_at=t.started_at.isoformat(),
            output_file=t.output_file,
        )
        for t in tasks
    ]


# ── Events ───────────────────────────────────────────────────

@router.get("/events")
async def list_events(
    event_type: Optional[str] = None,
    freq: Optional[float] = None,
    since: Optional[str] = None,
    limit: int = Query(100, le=5000),
    db: AsyncSession = Depends(get_db),
):
    q = select(Event).order_by(desc(Event.timestamp)).limit(limit)

    if event_type:
        q = q.where(Event.event_type == event_type)
    if freq:
        q = q.where(Event.freq_mhz == freq)
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            q = q.where(Event.timestamp >= since_dt)
        except ValueError:
            pass

    result = await db.execute(q)
    events = result.scalars().all()
    return [
        EventOut(
            id=e.id,
            timestamp=e.timestamp.isoformat() if e.timestamp else "",
            event_type=e.event_type,
            freq_mhz=e.freq_mhz,
            duration_ms=e.duration_ms,
            peak_power_db=e.peak_power_db,
            device_id=e.device_id,
        )
        for e in events
    ]


# ── Baselines ────────────────────────────────────────────────

@router.get("/baselines")
async def list_baselines(
    limit: int = Query(50, le=500),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Baseline).order_by(desc(Baseline.timestamp)).limit(limit)
    )
    return [
        BaselineOut(
            id=b.id,
            timestamp=b.timestamp.isoformat() if b.timestamp else "",
            filepath=b.filepath,
            device_count=b.device_count,
            duration_s=b.duration_s,
        )
        for b in result.scalars().all()
    ]


@router.get("/baselines/{baseline_id}/diff")
async def get_baseline_diff(
    baseline_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BaselineDiff).where(BaselineDiff.new_baseline_id == baseline_id)
    )
    diff = result.scalar_one_or_none()
    if not diff:
        raise HTTPException(404, "No diff found for this baseline")
    return {
        "id": diff.id,
        "old_baseline_id": diff.old_baseline_id,
        "new_baseline_id": diff.new_baseline_id,
        "new_signals": diff.new_signals,
        "disappeared": diff.disappeared,
        "power_changes": diff.power_changes,
        "rate_changes": diff.rate_changes,
        "report_text": diff.report_text,
    }


# ── Reports ──────────────────────────────────────────────────

@router.get("/reports")
async def list_reports(
    limit: int = Query(50, le=500),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Report).order_by(desc(Report.timestamp)).limit(limit)
    )
    return [
        ReportOut(
            id=r.id,
            timestamp=r.timestamp.isoformat() if r.timestamp else "",
            filepath=r.filepath,
            title=r.title,
            event_count=r.event_count,
            auto_generated=r.auto_generated,
        )
        for r in result.scalars().all()
    ]


@router.get("/reports/{report_id}")
async def get_report(report_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "Report not found")

    content = ""
    if os.path.exists(report.filepath):
        with open(report.filepath, "r") as f:
            content = f.read()

    return {
        "id": report.id,
        "title": report.title,
        "timestamp": report.timestamp.isoformat() if report.timestamp else "",
        "content": content,
    }
