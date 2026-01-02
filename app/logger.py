from __future__ import annotations

import logging
import pathlib
from typing import Optional

from .db import session_scope
from .models import LogEntry


def setup_file_logger(log_file: str) -> logging.Logger:
    logger = logging.getLogger(log_file)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    pathlib.Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    return logger


def persist_log(hotel_id: str, level: str, message: str, extra: Optional[dict] = None):
    with session_scope() as session:
        session.add(LogEntry(hotel_id=hotel_id, level=level, message=message, extra=extra or {}))
