"""
Recon-Raven configuration — loads from config.yml + environment overrides.
"""
import os
from pathlib import Path
from typing import List, Tuple

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


_CONFIG_SEARCH = [
    Path("config.yml"),
    Path("/etc/recon-raven/config.yml"),
    Path.home() / ".config" / "recon-raven" / "config.yml",
]


def _find_config() -> dict:
    for p in _CONFIG_SEARCH:
        if p.exists():
            with open(p) as f:
                return yaml.safe_load(f) or {}
    return {}


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class GPSConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 2947
    poll_interval: float = 2.0


class SchedulerConfig(BaseModel):
    baseline_cron: str = "0 */6 * * *"
    baseline_duration: int = 120
    baseline_frequencies: List[float] = [433.92, 315.0]
    auto_diff: bool = True
    auto_report: bool = True
    report_cron: str = "0 0 * * *"


class CaptureConfig(BaseModel):
    default_gain: float = 38.0
    default_rate: float = 2.4
    output_dir: str = "/var/lib/recon-raven/captures"
    log_dir: str = "/var/lib/recon-raven/logs"
    baseline_dir: str = "/var/lib/recon-raven/baselines"
    report_dir: str = "/var/lib/recon-raven/reports"


class TXConfig(BaseModel):
    enabled: bool = False
    max_gain_db: int = 30
    max_duration_s: int = 30
    authorized_bands_mhz: List[Tuple[float, float]] = [
        (144.0, 148.0),
        (420.0, 450.0),
        (902.0, 928.0),
    ]


class FissureConfig(BaseModel):
    install_path: str = "/home/kama/Tools/FISSURE"
    enabled: bool = True


class DevicesConfig(BaseModel):
    health_check_interval: int = 60
    auto_enumerate: bool = True


class Settings(BaseSettings):
    # Top-level
    data_dir: str = "/var/lib/recon-raven"
    db_path: str = "/var/lib/recon-raven/raven.db"
    engine_dir: str = ""  # auto-resolved

    # Sub-configs
    server: ServerConfig = ServerConfig()
    gps: GPSConfig = GPSConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
    capture: CaptureConfig = CaptureConfig()
    tx: TXConfig = TXConfig()
    fissure: FissureConfig = FissureConfig()
    devices: DevicesConfig = DevicesConfig()

    model_config = {"env_prefix": "RAVEN_"}


def load_settings() -> Settings:
    """Load settings from config.yml, overridden by environment variables."""
    file_cfg = _find_config()
    flat = {}

    # Flatten nested YAML into Settings fields
    for key in ("data_dir", "db_path"):
        if key in file_cfg:
            flat[key] = file_cfg[key]

    settings = Settings(**flat)

    # Apply nested sections
    for section_name in ("server", "gps", "scheduler", "capture", "tx", "fissure", "devices"):
        if section_name in file_cfg and isinstance(file_cfg[section_name], dict):
            section_cls = type(getattr(settings, section_name))
            setattr(settings, section_name, section_cls(**file_cfg[section_name]))

    # Auto-resolve engine directory
    if not settings.engine_dir:
        settings.engine_dir = str(Path(__file__).parent.parent / "engine")

    # Ensure data directories exist
    for d in (
        settings.data_dir,
        settings.capture.output_dir,
        settings.capture.log_dir,
        settings.capture.baseline_dir,
        settings.capture.report_dir,
    ):
        os.makedirs(d, exist_ok=True)

    return settings
