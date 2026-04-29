"""
Recon-Raven — FastAPI application entry point.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import load_settings
from .db.database import init_db, get_session_factory
from .api.routes import router as api_router, set_session_factory, set_services
from .api.websocket import (
    ws_manager, spectrum_endpoint, alerts_endpoint, status_endpoint,
)
from .services.device_manager import DeviceManager
from .services.gps_poller import GPSPoller
from .services.capture_service import CaptureService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("raven")

settings = load_settings()

# ── Services (initialized in lifespan) ───────────────────────
device_manager: DeviceManager = None
gps_poller: GPSPoller = None
capture_service: CaptureService = None
_health_task: asyncio.Task = None


async def _periodic_health_check():
    """Run device health checks on a timer."""
    while True:
        try:
            await asyncio.sleep(settings.devices.health_check_interval)
            await device_manager.health_check_all()
            # Broadcast status update
            devices = device_manager.list_devices()
            await ws_manager.broadcast_device_status({
                "devices": [
                    {
                        "sdr_index": d.index,
                        "model": d.model,
                        "status": d.status,
                        "assigned_task": d.assigned_task,
                    }
                    for d in devices
                ]
            })
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Health check error: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global device_manager, gps_poller, capture_service, _health_task

    logger.info("Starting Recon-Raven v0.1.0")
    logger.info("Data dir: %s", settings.data_dir)
    logger.info("Database: %s", settings.db_path)

    # 1. Initialize database
    await init_db(settings.db_path)
    sf = get_session_factory(settings.db_path)
    set_session_factory(sf)
    logger.info("Database initialized")

    # 2. Device manager
    device_manager = DeviceManager(settings.db_path)
    if settings.devices.auto_enumerate:
        try:
            devices = await device_manager.enumerate()
            logger.info("Found %d SDR device(s)", len(devices))
        except Exception as e:
            logger.warning("Device enumeration failed: %s", e)

    # 3. GPS poller
    gps_poller = GPSPoller(
        db_path=settings.db_path,
        host=settings.gps.host,
        port=settings.gps.port,
        poll_interval=settings.gps.poll_interval,
    )
    if settings.gps.enabled:
        await gps_poller.start()

    # 4. Capture service
    capture_service = CaptureService(
        engine_dir=settings.engine_dir,
        device_manager=device_manager,
        gps_poller=gps_poller,
        db_path=settings.db_path,
        capture_config=settings.capture,
    )
    capture_service.set_event_callback(ws_manager.broadcast_alert)

    # 5. Wire up API routes
    set_services(device_manager, gps_poller, capture_service)

    # 6. Start periodic health checks
    _health_task = asyncio.create_task(_periodic_health_check())

    logger.info("Recon-Raven ready — http://%s:%d", settings.server.host, settings.server.port)

    yield

    # ── Shutdown ─────────────────────────────────────────────
    logger.info("Shutting down Recon-Raven...")

    if _health_task:
        _health_task.cancel()
        try:
            await _health_task
        except asyncio.CancelledError:
            pass

    # Stop active captures
    for task in capture_service.list_active():
        await capture_service.stop_capture(task.task_id)

    await gps_poller.stop()
    logger.info("Shutdown complete")


# ── App ──────────────────────────────────────────────────────

app = FastAPI(
    title="Recon-Raven",
    description="F3EAD-aligned SIGINT automation platform",
    version="0.1.0",
    lifespan=lifespan,
)

# REST API
app.include_router(api_router)

# WebSocket endpoints
app.add_api_websocket_route("/ws/spectrum", spectrum_endpoint)
app.add_api_websocket_route("/ws/alerts", alerts_endpoint)
app.add_api_websocket_route("/ws/status", status_endpoint)

# Static frontend
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
