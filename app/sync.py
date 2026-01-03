from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Dict, Optional

import httpx
import pendulum

from .config import HotelConfig
from .db import session_scope
from .logger import persist_log
from .loxone import LoxoneClient
from .models import HotelSettings, HotelState, IssuedUser
from .previo import PrevioClient

logger = logging.getLogger(__name__)


class SyncService:
    def __init__(self, configs: Dict[str, HotelConfig]):
        self.configs = configs
        self.running = False

    async def ensure_defaults(self):
        from .db import Base, engine

        Base.metadata.create_all(engine)
        with session_scope() as session:
            for hotel_id, cfg in self.configs.items():
                db_settings = session.get(HotelSettings, hotel_id)
                if not db_settings:
                    session.add(
                        HotelSettings(
                            hotel_id=hotel_id,
                            dashboard_read_key=cfg.dashboard.read_key,
                            interval_minutes=cfg.sync.interval_minutes,
                            delete_after_hours=cfg.sync.delete_after_hours,
                            offset_minutes_before=cfg.sync.offset_minutes_before,
                            offset_minutes_after=cfg.sync.offset_minutes_after,
                            window_days_before=cfg.previo.search.window_days_before,
                            window_days_after=cfg.previo.search.window_days_after,
                            verify_tls=cfg.loxone.verify_tls,
                        )
                    )

    async def run_forever(self):
        self.running = True
        schedule: Dict[str, dt.datetime] = {hid: dt.datetime.utcnow() for hid in self.configs}
        while self.running:
            now = dt.datetime.utcnow()
            tasks = []
            for hotel_id, cfg in self.configs.items():
                due = schedule.get(hotel_id, now)
                interval_minutes = cfg.sync.interval_minutes
                with session_scope() as session:
                    db_settings = session.get(HotelSettings, hotel_id)
                    if db_settings:
                        interval_minutes = db_settings.interval_minutes
                if now >= due:
                    tasks.append(self.sync_hotel(hotel_id, cfg))
                    schedule[hotel_id] = now + dt.timedelta(minutes=interval_minutes)
            if tasks:
                await asyncio.gather(*tasks)
            await asyncio.sleep(30)

    async def sync_hotel(self, hotel_id: str, cfg: HotelConfig):
        now = pendulum.now(tz=cfg.timezone or "UTC")
        logger.info("Sync start %s", hotel_id)
        lox_verify = cfg.loxone.verify_tls
        with session_scope() as session:
            db_settings = session.get(HotelSettings, hotel_id)
            if db_settings:
                before = db_settings.window_days_before
                after = db_settings.window_days_after
                offset_before = db_settings.offset_minutes_before
                offset_after = db_settings.offset_minutes_after
                delete_after = db_settings.delete_after_hours
                lox_verify = db_settings.verify_tls
            else:
                before = cfg.previo.search.window_days_before
                after = cfg.previo.search.window_days_after
                offset_before = cfg.sync.offset_minutes_before
                offset_after = cfg.sync.offset_minutes_after
                delete_after = cfg.sync.delete_after_hours

        previo = PrevioClient(cfg)
        lox = LoxoneClient(cfg, verify_override=lox_verify)
        async with httpx.AsyncClient() as previo_client, httpx.AsyncClient(verify=lox_verify) as lox_client:
            start_date, end_date = previo.compute_window(now, cfg.timezone or "UTC", before, after)
            try:
                reservations = await previo.search_reservations(previo_client, start_date, end_date)
            except Exception as exc:
                persist_log(hotel_id, "ERROR", f"Previo search failed: {exc}")
                return

            try:
                groups = await lox.get_group_map(lox_client)
            except Exception as exc:
                persist_log(hotel_id, "ERROR", f"Loxone get groups failed: {exc}")
                return

            for res in reservations:
                await self._process_reservation(
                    previo_client,
                    lox_client,
                    hotel_id,
                    cfg,
                    res,
                    groups,
                    offset_before,
                    offset_after,
                    delete_after,
                    lox,
                    previo,
                )

            with session_scope() as session:
                state = session.get(HotelState, hotel_id)
                if not state:
                    state = HotelState(hotel_id=hotel_id)
                    session.add(state)
                state.last_sync_at = now
                state.last_success_at = now

            await self._cleanup_expired(lox_client, hotel_id, cfg, delete_after, lox)

    async def _process_reservation(
        self,
        prev_client: httpx.AsyncClient,
        lox_client: httpx.AsyncClient,
        hotel_id: str,
        cfg: HotelConfig,
        reservation: dict,
        groups: dict,
        offset_before: int,
        offset_after: int,
        delete_after: int,
        lox: LoxoneClient,
        previo: PrevioClient,
    ):
        com_id = reservation.get("comId")
        res_id = reservation.get("resId")
        term = reservation.get("term", {})
        raw_from = term.get("from")
        raw_to = term.get("to")
        pin_data = await previo.get_pin_code(prev_client, com_id)
        keys = (pin_data or {}).get("keys") or []
        key_entry = keys[0] if keys else None
        code = (key_entry or {}).get("code")
        validity = (key_entry or {}).get("validity") or {}

        start = self._parse_dt(validity.get("from")) or self._parse_dt(raw_from)
        end = self._parse_dt(validity.get("to")) or self._parse_dt(raw_to)
        if not start or not end:
            persist_log(hotel_id, "WARNING", f"Skipping reservation {res_id}: missing validity")
            return

        start = start.add(minutes=-offset_before)
        end = end.add(minutes=offset_after)

        userid = f"PLUSCONNECT - {res_id}"
        group_name = (key_entry or {}).get("lockGuestName") or reservation.get("objectName")
        group_uuid = groups.get(group_name)
        if not group_uuid:
            persist_log(hotel_id, "WARNING", f"Reservation {res_id}: group '{group_name}' not found")
            return

        try:
            existing_uuid = await lox.check_userid(lox_client, userid)
            payload = {
                "name": reservation.get("guest", {}).get("name") or userid,
                "userid": userid,
                "userState": 4,
                "validFrom": lox.to_seconds_since_2009(start),
                "validUntil": lox.to_seconds_since_2009(end),
                "expirationAction": 1,
                "usergroups": [group_uuid],
                "changePassword": False,
            }
            uuid = await lox.add_or_edit_user(lox_client, payload, existing_uuid)
            if code:
                await lox.update_access_code(lox_client, uuid, code)
            expires_at = end.add(hours=delete_after)
            with session_scope() as session:
                row = session.query(IssuedUser).filter_by(hotel_id=hotel_id, userid=userid).one_or_none()
                if not row:
                    row = IssuedUser(hotel_id=hotel_id, userid=userid)
                    session.add(row)
                row.loxone_uuid = uuid
                row.valid_until = end
                row.expires_at = expires_at
            persist_log(hotel_id, "INFO", f"Synced reservation {res_id} -> user {uuid}")
        except Exception as exc:
            persist_log(hotel_id, "ERROR", f"Failed reservation {res_id}: {exc}")

    async def _cleanup_expired(self, lox_client: httpx.AsyncClient, hotel_id: str, cfg: HotelConfig, delete_after: int, lox: LoxoneClient):
        now = pendulum.now(tz=cfg.timezone or "UTC")
        with session_scope() as session:
            rows = session.query(IssuedUser).filter(IssuedUser.hotel_id == hotel_id).all()
        for row in rows:
            if row.expires_at and now > pendulum.instance(row.expires_at):
                try:
                    if row.loxone_uuid:
                        await lox.delete_user(lox_client, row.loxone_uuid)
                    with session_scope() as session:
                        session.query(IssuedUser).filter(IssuedUser.id == row.id).delete()
                    persist_log(hotel_id, "INFO", f"Deleted expired user {row.userid}")
                except Exception as exc:
                    persist_log(hotel_id, "ERROR", f"Failed delete user {row.userid}: {exc}")

    def _parse_dt(self, value: Optional[str]) -> Optional[pendulum.DateTime]:
        if not value:
            return None
        try:
            return pendulum.parse(value)
        except Exception:
            return None
