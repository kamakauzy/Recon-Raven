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
from .api.routes import (
    router as api_router,
    set_session_factory,
    set_services,
    set_scheduler,
    set_classifier,
    set_tx_service,
    set_fissure_service,
    set_push_service,
    set_federation_service,
)
from .api.tile_proxy import router as tile_router
from .api.websocket import (
    ws_manager,
    spectrum_endpoint,
    alerts_endpoint,
    status_endpoint,
)
from .services.device_manager import DeviceManager
from .services.gps_poller import GPSPoller
from .services.capture_service import CaptureService
from .services.scheduler import RavenScheduler
from .services.classifier import Classifier
from .services.tx_service import TXService
from .services.fissure_service import FissureService
from .services.push_service import PushService
from .services.federation_service import FederationService

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
scheduler: RavenScheduler = None
_health_task: asyncio.Task = None


async def _periodic_health_check():
    """Run device health checks on a timer."""
    while True:
        try:
            await asyncio.sleep(settings.devices.health_check_interval)
            await device_manager.health_check_all()
            # Broadcast status update
            devices = device_manager.list_devices()
            await ws_manager.broadcast_device_status(
                {
                    "devices": [
                        {
                            "sdr_index": d.index,
                            "model": d.model,
                            "status": d.status,
                            "assigned_task": d.assigned_task,
                        }
                        for d in devices
                    ]
                }
            )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Health check error: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global device_manager, gps_poller, capture_service, scheduler, _health_task

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
    classifier = Classifier(
        rules_dir=str(
            Path(settings.engine_dir).parent / "backend" / "classifier" / "rules"
        ),
    )
    capture_service = CaptureService(
        engine_dir=settings.engine_dir,
        device_manager=device_manager,
        gps_poller=gps_poller,
        db_path=settings.db_path,
        capture_config=settings.capture,
        classifier=classifier,
    )

    # 5. Wire up API routes
    set_services(device_manager, gps_poller, capture_service)
    set_classifier(classifier)

    # 5b. TX Service
    tx_service = TXService(settings, device_manager, settings.db_path)
    set_tx_service(tx_service)

    # 5c. FISSURE Service
    fissure_service = FissureService(settings)
    set_fissure_service(fissure_service)

    # 5d. Push notification service
    push_service = PushService(db_path=settings.db_path)
    set_push_service(push_service)

    # Wire push notifications into the alert broadcast chain
    original_broadcast = ws_manager.broadcast_alert

    async def broadcast_with_push(event_data):
        # Route spectrum frames to spectrum WS channel
        if event_data.get("event_type") == "spectrum":
            await ws_manager.broadcast_spectrum_frame(event_data)
            return
        await original_broadcast(event_data)
        try:
            await push_service.send_signal_alert(event_data)
        except Exception as e:
            logger.debug("Push notification error: %s", e)

    capture_service.set_event_callback(broadcast_with_push)

    # 5e. Federation service
    federation_service = FederationService(settings)
    set_federation_service(federation_service)
    await federation_service.start()

    # Wire federation event sharing into the broadcast chain
    _prev_broadcast = broadcast_with_push

    async def broadcast_with_federation(event_data):
        await _prev_broadcast(event_data)
        try:
            await federation_service.share_event(event_data)
        except Exception as e:
            logger.debug("Federation share error: %s", e)

    capture_service.set_event_callback(broadcast_with_federation)

    # 6. Scheduler
    scheduler = RavenScheduler(
        settings=settings,
        capture_service=capture_service,
        device_manager=device_manager,
        db_path=settings.db_path,
    )
    scheduler.start()
    set_scheduler(scheduler)

    # 7. Start periodic health checks
    _health_task = asyncio.create_task(_periodic_health_check())

    logger.info(
        "Recon-Raven ready — http://%s:%d", settings.server.host, settings.server.port
    )

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

    scheduler.stop()
    await federation_service.stop()
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
app.include_router(tile_router)
app.include_router(api_router)

# WebSocket endpoints
app.add_api_websocket_route("/ws/spectrum", spectrum_endpoint)
app.add_api_websocket_route("/ws/alerts", alerts_endpoint)
app.add_api_websocket_route("/ws/status", status_endpoint)

# Static frontend
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
