from __future__ import annotations

from typing import Dict

from fastapi import Request

from .config import HotelConfig


def get_hotels(request: Request) -> Dict[str, HotelConfig]:
    return request.app.state.hotels  # type: ignore[attr-defined]
