from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, List, Optional

import httpx
import pendulum

from .config import HotelConfig

logger = logging.getLogger(__name__)


class PrevioClient:
    def __init__(self, cfg: HotelConfig):
        self.cfg = cfg
        self.base_url = cfg.previo.api_url.rstrip("/")

    async def search_reservations(self, client: httpx.AsyncClient, from_dt: dt.date, to_dt: dt.date) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/x1/hotel/searchReservations"
        statuses_xml = "".join(f"<cosId>{s}</cosId>" for s in self.cfg.previo.search.statuses)
        body = f"""<?xml version=\"1.0\"?>
<request>
    <login>{self.cfg.previo.login}</login>
    <password>{self.cfg.previo.password}</password>
    <hotId>{self.cfg.previo.hot_id}</hotId>
    <term>
        <from>{from_dt:%Y-%m-%d}</from>
        <to>{to_dt:%Y-%m-%d}</to>
    </term>
    <statuses>{statuses_xml}</statuses>
    <limit><offset>0</offset><limit>{self.cfg.previo.search.limit}</limit></limit>
</request>
"""
        headers = {"Content-Type": "application/xml"}
        resp = await client.post(url, content=body, headers=headers, timeout=30)
        resp.raise_for_status()
        return self._parse_reservations(resp.text)

    async def get_pin_code(self, client: httpx.AsyncClient, reservation_room_id: str) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/rest/reservations/rooms/card-locking-keys"
        params = {"reservationRoomId": reservation_room_id}
        headers = {
            "Content-Type": "application/json",
            "X-Previo-Hotel-ID": str(self.cfg.previo.hot_id),
        }
        auth = (self.cfg.previo.login, self.cfg.previo.password)
        resp = await client.get(url, params=params, headers=headers, auth=auth, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return data.get("cardData")

    async def get_hotel_info(self, client: httpx.AsyncClient) -> Dict[str, Any]:
        url = f"{self.base_url}/x1/hotel/get"
        body = f"""<?xml version=\"1.0\"?>
<request>
    <login>{self.cfg.previo.login}</login>
    <password>{self.cfg.previo.password}</password>
    <hotId>{self.cfg.previo.hot_id}</hotId>
    <lanId>{self.cfg.previo.lan_id}</lanId>
</request>
"""
        headers = {"Content-Type": "application/xml"}
        resp = await client.post(url, content=body, headers=headers, timeout=30)
        resp.raise_for_status()
        return self._parse_hotel_info(resp.text)

    def _parse_hotel_info(self, xml_text: str) -> Dict[str, Any]:
        # Very small XPath-free parse for timezone/arrival/departure
        data: Dict[str, Any] = {}
        for tag in ("arrival", "departure"):
            start = xml_text.find(f"<{tag}>")
            if start != -1:
                end = xml_text.find(f"</{tag}>")
                data[tag] = xml_text[start + len(tag) + 2 : end]
        return data

    def _parse_reservations(self, xml_text: str) -> List[Dict[str, Any]]:
        # Lightweight parsing to extract reservation blocks; in production consider xmltodict
        reservations: List[Dict[str, Any]] = []
        cursor = 0
        while True:
            start = xml_text.find("<reservation>", cursor)
            if start == -1:
                break
            end = xml_text.find("</reservation>", start)
            if end == -1:
                break
            block = xml_text[start:end]
            reservations.append(self._parse_reservation_block(block))
            cursor = end + len("</reservation>")
        return reservations

    def _extract(self, block: str, tag: str) -> Optional[str]:
        start = block.find(f"<{tag}>")
        if start == -1:
            return None
        end = block.find(f"</{tag}>", start)
        if end == -1:
            return None
        return block[start + len(tag) + 2 : end]

    def _parse_reservation_block(self, block: str) -> Dict[str, Any]:
        term_from = self._extract(block, "from")
        term_to = self._extract(block, "to")
        reservation = {
            "comId": self._extract(block, "comId"),
            "resId": self._extract(block, "resId"),
            "objectName": self._extract(block, "name"),
            "term": {
                "from": term_from,
                "to": term_to,
            },
        }
        guest_first = self._extract(block, "firstName")
        guest_last = self._extract(block, "lastName")
        guest_name = self._extract(block, "name")
        reservation["guest"] = {
            "firstName": guest_first,
            "lastName": guest_last,
            "name": guest_name,
        }
        return reservation

    def compute_window(self, now: dt.datetime, tz: str, override_before: int, override_after: int) -> tuple[dt.date, dt.date]:
        base = pendulum.instance(now).in_timezone(tz)
        start_date = base.add(days=-override_before).date()
        end_date = base.add(days=override_after).date()
        return start_date, end_date
