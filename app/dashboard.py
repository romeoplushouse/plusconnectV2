from __future__ import annotations

import base64
import pathlib
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import HotelConfig
from .db import session_scope
from .models import HotelSettings, HotelState, LogEntry

security = HTTPBasic()
TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=select_autoescape())
router = APIRouter()


def verify_basic(credentials: HTTPBasicCredentials, cfg: HotelConfig):
    if credentials.username != cfg.dashboard.basic_auth_user or credentials.password != cfg.dashboard.basic_auth_password:
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})


def require_key(request: Request, cfg: HotelConfig):
    key = request.query_params.get("key")
    if key != cfg.dashboard.read_key:
        raise HTTPException(status_code=403, detail="Invalid key")


def _render(template: str, **context):
    tmpl = jinja_env.get_template(template)
    return HTMLResponse(tmpl.render(**context))


def _safe_obj(obj, fields):
    if not obj:
        return None
    return {f: getattr(obj, f, None) for f in fields}


from .deps import get_hotels


@router.get("/", response_class=HTMLResponse)
async def dashboard_root(request: Request, hotels: Dict[str, HotelConfig] = Depends(get_hotels)):
    items = []
    with session_scope() as session:
        for hotel_id, cfg in hotels.items():
            state = session.get(HotelState, hotel_id)
            items.append(
                {
                    "hotel_id": hotel_id,
                    "last_sync": state.last_sync_at if state else None,
                    "last_success": state.last_success_at if state else None,
                    "read_key": cfg.dashboard.read_key,
                }
            )
    return _render("index.html", hotels=items, request=request)


@router.get("/hotels/{hotel_id}", response_class=HTMLResponse)
async def hotel_detail(request: Request, hotel_id: str, hotels: Dict[str, HotelConfig] = Depends(get_hotels)):
    cfg = hotels.get(hotel_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Hotel not found")
    require_key(request, cfg)
    with session_scope() as session:
        state = session.get(HotelState, hotel_id)
        logs = session.query(LogEntry).filter(LogEntry.hotel_id == hotel_id).order_by(LogEntry.id.desc()).limit(50).all()
        settings = session.get(HotelSettings, hotel_id)
        state_data = _safe_obj(state, ["last_sync_at", "last_success_at"])
        settings_data = _safe_obj(
            settings,
            [
                "interval_minutes",
                "delete_after_hours",
                "offset_minutes_before",
                "offset_minutes_after",
                "window_days_before",
                "window_days_after",
                "verify_tls",
            ],
        )
        logs_data = [
            {
                "created_at": log.created_at,
                "level": log.level,
                "message": log.message,
            }
            for log in logs
        ]
    logo_data = _load_logo_data()
    return _render(
        "hotel.html",
        hotel_id=hotel_id,
        state=state_data,
        logs=logs_data,
        settings=settings_data,
        request=request,
        logo_data=logo_data,
    )


@router.post("/hotels/{hotel_id}/settings", response_class=HTMLResponse)
async def update_settings(
    request: Request,
    hotel_id: str,
    hotels: Dict[str, HotelConfig] = Depends(get_hotels),
    credentials: HTTPBasicCredentials = Depends(security),
):
    cfg = hotels.get(hotel_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Hotel not found")
    verify_basic(credentials, cfg)
    form = await request.form()
    with session_scope() as session:
        settings = session.get(HotelSettings, hotel_id)
        if not settings:
            raise HTTPException(status_code=404, detail="Settings not found")
        settings.interval_minutes = int(form.get("interval_minutes", settings.interval_minutes))
        settings.delete_after_hours = int(form.get("delete_after_hours", settings.delete_after_hours))
        settings.offset_minutes_before = int(form.get("offset_minutes_before", settings.offset_minutes_before))
        settings.offset_minutes_after = int(form.get("offset_minutes_after", settings.offset_minutes_after))
        settings.window_days_before = int(form.get("window_days_before", settings.window_days_before))
        settings.window_days_after = int(form.get("window_days_after", settings.window_days_after))
        settings.verify_tls = bool(int(form.get("verify_tls", int(settings.verify_tls))))
    return await hotel_detail(request, hotel_id, hotels)


def _load_logo_data() -> str:
    logo_path = TEMPLATES_DIR.parent.parent / "static" / "logos" / "plushouse.svg"
    if logo_path.exists():
        data = logo_path.read_bytes()
        b64 = base64.b64encode(data).decode("utf-8")
        return f"data:image/svg+xml;base64,{b64}"
    return ""
