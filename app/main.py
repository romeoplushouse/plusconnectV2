from __future__ import annotations

import asyncio
import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import load_configs
from .dashboard import router as dashboard_router
from .logger import setup_file_logger
from .sync import SyncService

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Plusconnect Sync")
configs = load_configs()
app.state.hotels = configs  # type: ignore[attr-defined]

for cfg in configs.values():
    setup_file_logger(cfg.logging.file)

sync_service = SyncService(configs)


@app.on_event("startup")
async def startup_event():
    await sync_service.ensure_defaults()
    # Run sync loop in background
    asyncio.create_task(sync_service.run_forever())


app.include_router(dashboard_router)

static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/health")
async def health():
    return {"status": "ok", "hotels": list(configs.keys())}
