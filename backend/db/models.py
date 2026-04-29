"""
SQLAlchemy ORM models for Recon-Raven.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text,
    JSON,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sdr_index = Column(Integer, nullable=False)
    serial = Column(String(64), default="")
    model = Column(String(128), default="")
    device_type = Column(String(32), default="rtlsdr")  # rtlsdr | hackrf
    usb_bus = Column(String(32), default="")
    status = Column(String(16), default="offline")  # free | busy | error | offline
    assigned_task = Column(String(256), default="")
    last_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    events = relationship("Event", back_populates="device")
    baselines = relationship("Baseline", back_populates="device")


class GPSFix(Base):
    __tablename__ = "gps_fixes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    altitude_m = Column(Float, nullable=True)
    speed_mps = Column(Float, nullable=True)
    heading_deg = Column(Float, nullable=True)
    error_m = Column(Float, nullable=True)
    satellites = Column(Integer, nullable=True)

    events = relationship("Event", back_populates="gps_fix")
    baselines = relationship("Baseline", back_populates="gps_fix")


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    event_type = Column(String(32), nullable=False, index=True)  # burst | alert | baseline_new | capture_start | capture_stop
    freq_mhz = Column(Float, nullable=True)
    duration_ms = Column(Float, nullable=True)
    peak_power_db = Column(Float, nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)

    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    gps_fix_id = Column(Integer, ForeignKey("gps_fixes.id"), nullable=True)

    device = relationship("Device", back_populates="events")
    gps_fix = relationship("GPSFix", back_populates="events")
    classification = relationship("Classification", back_populates="event", uselist=False)


class Baseline(Base):
    __tablename__ = "baselines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    filepath = Column(String(512), nullable=False)
    device_count = Column(Integer, default=0)
    duration_s = Column(Integer, default=0)
    frequencies = Column(JSON, default=list)  # [433.92, 315.0]

    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    gps_fix_id = Column(Integer, ForeignKey("gps_fixes.id"), nullable=True)

    device = relationship("Device", back_populates="baselines")
    gps_fix = relationship("GPSFix", back_populates="baselines")

    diffs_as_old = relationship("BaselineDiff", foreign_keys="BaselineDiff.old_baseline_id", back_populates="old_baseline")
    diffs_as_new = relationship("BaselineDiff", foreign_keys="BaselineDiff.new_baseline_id", back_populates="new_baseline")


class BaselineDiff(Base):
    __tablename__ = "baseline_diffs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    old_baseline_id = Column(Integer, ForeignKey("baselines.id"), nullable=False)
    new_baseline_id = Column(Integer, ForeignKey("baselines.id"), nullable=False)
    new_signals = Column(Integer, default=0)
    disappeared = Column(Integer, default=0)
    power_changes = Column(Integer, default=0)
    rate_changes = Column(Integer, default=0)
    report_text = Column(Text, default="")

    old_baseline = relationship("Baseline", foreign_keys=[old_baseline_id], back_populates="diffs_as_old")
    new_baseline = relationship("Baseline", foreign_keys=[new_baseline_id], back_populates="diffs_as_new")


class Classification(Base):
    __tablename__ = "classifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False, unique=True)
    method = Column(String(16), default="rule")  # rule | ml | manual
    label = Column(String(128), default="unknown")
    confidence = Column(Float, default=0.0)
    rule_name = Column(String(128), default="")
    model_name = Column(String(128), default="")
    features = Column(JSON, default=dict)

    event = relationship("Event", back_populates="classification")


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    filepath = Column(String(512), nullable=False)
    title = Column(String(256), default="")
    event_count = Column(Integer, default=0)
    auto_generated = Column(Boolean, default=False)


class TXLog(Base):
    __tablename__ = "tx_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    freq_mhz = Column(Float, nullable=False)
    gain_db = Column(Float, default=0)
    duration_s = Column(Float, default=0)
    tx_type = Column(String(32), default="")  # replay | generate | fissure
    file_path = Column(String(512), default="")
    result = Column(String(32), default="")  # success | rejected | error | timeout
    rejection_reason = Column(String(256), default="")
    metadata_ = Column("metadata", JSON, default=dict)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    endpoint = Column(String(1024), nullable=False, unique=True)
    p256dh_key = Column(String(256), nullable=False)
    auth_key = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
