from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
import os
import secrets
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pendulum
from tenacity import retry, stop_after_attempt, wait_fixed

from .config import HotelConfig

logger = logging.getLogger(__name__)


class LoxoneAuthError(Exception):
    pass


class LoxoneClient:
    def __init__(self, cfg: HotelConfig, verify_override: Optional[bool] = None):
        self.cfg = cfg
        self.base_host = cfg.loxone.cloud_dns_host
        self.scheme = "https" if cfg.loxone.https else "http"
        self.verify = cfg.loxone.verify_tls if verify_override is None else verify_override

    def _url(self, path: str) -> str:
        return f"{self.scheme}://{self.base_host}/{path.lstrip('/')}"

    async def _request(self, client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.RequestError as exc:
            raise LoxoneAuthError(f"{method} {url} request failed: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:200]
            raise LoxoneAuthError(
                f"{method} {url} HTTP {exc.response.status_code}: {body}"
            ) from exc

    async def _getkey2(self, client: httpx.AsyncClient) -> Dict[str, Any]:
        url = self._url(f"jdev/sys/getkey2/{self.cfg.loxone.username}")
        resp = await self._request(client, "GET", url, timeout=20)
        data = resp.json().get("LL", {}).get("value", {})
        return data

    def _hash_password(self, password: str, salt: str, hash_alg: str) -> str:
        algo = hashlib.sha256 if hash_alg.lower() == "sha256" else hashlib.sha1
        digest = algo(f"{password}:{salt}".encode("utf-8")).hexdigest().upper()
        return digest

    def _hmac(self, key_hex: str, data: str, hash_alg: str) -> str:
        key_bytes = bytes.fromhex(key_hex)
        if hash_alg.lower() == "sha256":
            h = hmac.new(key_bytes, data.encode("utf-8"), hashlib.sha256)
        else:
            h = hmac.new(key_bytes, data.encode("utf-8"), hashlib.sha1)
        return h.hexdigest()

    async def acquire_token(self, client: httpx.AsyncClient) -> Tuple[str, str]:
        meta = await self._getkey2(client)
        key = meta.get("key")
        salt = meta.get("salt")
        hash_alg = meta.get("hashAlg", "sha1")
        if not key or not salt:
            raise LoxoneAuthError("Missing key/salt from getkey2")

        pass_hash = self._hash_password(self.cfg.loxone.password, salt, hash_alg)
        hash_value = self._hmac(key, f"{self.cfg.loxone.username}:{pass_hash}", hash_alg)
        cmd = (
            f"jdev/sys/getjwt/{hash_value}/{self.cfg.loxone.username}/"
            f"{self.cfg.loxone.permission}/{self.cfg.loxone.client_uuid}/"
            f"{self.cfg.loxone.client_info}"
        )
        url = self._url(cmd)
        resp = await self._request(client, "GET", url, timeout=20)
        value = resp.json().get("LL", {}).get("value", {})
        token = value.get("token")
        token_key = value.get("key")
        if not token or not token_key:
            raise LoxoneAuthError("Failed to get JWT token")
        return token, token_key

    def _token_hash(self, token: str, key_hex: str) -> str:
        return hmac.new(bytes.fromhex(key_hex), token.encode("utf-8"), hashlib.sha1).hexdigest()

    async def _auth_params(self, client: httpx.AsyncClient) -> Dict[str, str]:
        token, key = await self.acquire_token(client)
        return {"autht": self._token_hash(token, key), "user": self.cfg.loxone.username}

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def get_group_map(self, client: httpx.AsyncClient) -> Dict[str, str]:
        params = await self._auth_params(client)
        url = self._url("jdev/sps/getgrouplist")
        resp = await self._request(client, "GET", url, params=params, timeout=20)
        try:
            root = resp.json()
        except Exception as exc:
            raise LoxoneAuthError(f"getgrouplist invalid JSON: {exc} body={resp.text[:200]}") from exc
        if not isinstance(root, dict):
            raise LoxoneAuthError(f"Unexpected getgrouplist root type: {type(root)} body={resp.text[:200]}")
        try:
            ll = root.get("LL", {})
            if not isinstance(ll, dict):
                raise LoxoneAuthError(f"Unexpected getgrouplist LL type: {type(ll)} body={resp.text[:200]}")
            payload = ll.get("value", [])
            if not isinstance(payload, list):
                raise LoxoneAuthError(f"Unexpected getgrouplist payload type: {type(payload)} body={resp.text[:200]}")
            groups = {
                g.get("name"): g.get("uuid")
                for g in payload
                if isinstance(g, dict) and g.get("name") and g.get("uuid")
            }
        except TypeError as exc:
            raise LoxoneAuthError(f"TypeError parsing getgrouplist payload: {exc} body={resp.text[:200]}") from exc
        if not groups:
            raise LoxoneAuthError(f"No groups returned from getgrouplist body={resp.text[:200]}")
        return groups

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def check_userid(self, client: httpx.AsyncClient, userid: str) -> Optional[str]:
        params = await self._auth_params(client)
        url = self._url(f"jdev/sps/checkuserid/{userid}")
        resp = await self._request(client, "GET", url, params=params, timeout=20)
        val = resp.json().get("LL", {}).get("value", {})
        return val.get("uuid") if val else None

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def add_or_edit_user(self, client: httpx.AsyncClient, payload: Dict[str, Any], uuid: Optional[str]) -> str:
        params = await self._auth_params(client)
        if uuid:
            payload["uuid"] = uuid
        url = self._url("jdev/sps/addoredituser")
        resp = await self._request(client, "POST", url, params=params, json=payload, timeout=20)
        val = resp.json().get("LL", {}).get("value")
        if not val:
            raise LoxoneAuthError("addoredituser returned empty value")
        return val if isinstance(val, str) else val.get("uuid", "")

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def update_access_code(self, client: httpx.AsyncClient, uuid: str, code: str):
        params = await self._auth_params(client)
        url = self._url(f"jdev/sps/updateuseraccesscode/{uuid}/{code}")
        resp = await self._request(client, "GET", url, params=params, timeout=20)
        return resp.json().get("LL", {}).get("Code")

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def delete_user(self, client: httpx.AsyncClient, uuid: str):
        params = await self._auth_params(client)
        url = self._url(f"jdev/sps/deleteuser/{uuid}")
        await self._request(client, "GET", url, params=params, timeout=20)

    @staticmethod
    def to_seconds_since_2009(dt_value: dt.datetime) -> int:
        epoch = pendulum.datetime(2009, 1, 1, tz="UTC")
        return int((pendulum.instance(dt_value).in_timezone("UTC") - epoch).total_seconds())
