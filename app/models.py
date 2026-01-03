from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from .db import Base


class HotelSettings(Base):
    __tablename__ = "hotel_settings"

    hotel_id = Column(String, primary_key=True)
    dashboard_read_key = Column(String, nullable=False)
    interval_minutes = Column(Integer, nullable=False, default=5)
    delete_after_hours = Column(Integer, nullable=False, default=48)
    offset_minutes_before = Column(Integer, nullable=False, default=0)
    offset_minutes_after = Column(Integer, nullable=False, default=0)
    window_days_before = Column(Integer, nullable=False, default=1)
    window_days_after = Column(Integer, nullable=False, default=1)
    verify_tls = Column(Boolean, nullable=False, default=True)


class HotelState(Base):
    __tablename__ = "hotel_state"

    hotel_id = Column(String, primary_key=True)
    last_sync_at = Column(DateTime(timezone=True))
    last_success_at = Column(DateTime(timezone=True))


class LogEntry(Base):
    __tablename__ = "log_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hotel_id = Column(String, nullable=False)
    level = Column(String, nullable=False, default="INFO")
    message = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=dt.datetime.utcnow)
    extra = Column(JSONB)


class IssuedUser(Base):
    __tablename__ = "issued_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hotel_id = Column(String, nullable=False, index=True)
    userid = Column(String, nullable=False, index=True)
    loxone_uuid = Column(String, nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=dt.datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)
