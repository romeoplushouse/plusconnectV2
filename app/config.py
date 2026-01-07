from __future__ import annotations

import pathlib
import secrets
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml


BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config" / "hotels"


@dataclass
class PrevioSearchSettings:
    statuses: List[int]
    window_days_before: int
    window_days_after: int
    limit: int


@dataclass
class PrevioConfig:
    api_url: str
    login: str
    password: str
    hot_id: int
    lan_id: int = 1
    search: PrevioSearchSettings = field(default_factory=lambda: PrevioSearchSettings([1, 2, 3], 1, 1, 200))


@dataclass
class LoxoneConfig:
    cloud_dns_host: str
    serial_number: str
    username: str
    password: str
    https: bool = True
    verify_tls: bool = True
    permission: int = 4
    client_uuid: str = "098802e1-02b4-603c-ffffeee000d80cfd"
    client_info: str = "plusconnect-sync"


@dataclass
class DashboardConfig:
    read_key: str
    basic_auth_user: str
    basic_auth_password: str


@dataclass
class SyncConfig:
    interval_minutes: int = 5
    delete_after_hours: int = 48
    offset_minutes_before: int = 0
    offset_minutes_after: int = 0


@dataclass
class LoggingConfig:
    file: str


@dataclass
class HotelConfig:
    hotel_id: str
    timezone: Optional[str]
    previo: PrevioConfig
    loxone: LoxoneConfig
    dashboard: DashboardConfig
    sync: SyncConfig
    logging: LoggingConfig


class ConfigLoader:
    def __init__(self, config_dir: pathlib.Path = CONFIG_DIR):
        self.config_dir = config_dir

    def load_all(self) -> Dict[str, HotelConfig]:
        configs: Dict[str, HotelConfig] = {}
        for path in sorted(self.config_dir.glob("*.yaml")):
            raw = self._read_yaml(path)
            hotel_cfg = self._build_hotel_config(raw)
            configs[hotel_cfg.hotel_id] = hotel_cfg
        return configs

    def _read_yaml(self, path: pathlib.Path) -> dict:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _ensure_read_key(self, value: Optional[str]) -> str:
        if value and value != "<GENERATED_AT_RUNTIME>":
            return value
        return secrets.token_urlsafe(24)

    def _build_hotel_config(self, raw: dict) -> HotelConfig:
        search = raw.get("previo", {}).get("search", {})
        prev = PrevioConfig(
            api_url=raw["previo"]["api_url"],
            login=raw["previo"]["login"],
            password=raw["previo"]["password"],
            hot_id=int(raw["previo"]["hot_id"]),
            lan_id=int(raw["previo"].get("lan_id", 1)),
            search=PrevioSearchSettings(
                statuses=[int(s) for s in search.get("statuses", [1, 2, 3])],
                window_days_before=int(search.get("window_days_before", 1)),
                window_days_after=int(search.get("window_days_after", 1)),
                limit=int(search.get("limit", 200)),
            ),
        )

        lox = raw["loxone"]
        lox_cfg = LoxoneConfig(
            cloud_dns_host=lox["cloud_dns_host"],
            serial_number=lox["serial_number"],
            username=lox["username"],
            password=lox["password"],
            https=bool(lox.get("https", True)),
            verify_tls=bool(lox.get("verify_tls", True)),
            permission=int(lox.get("permission", 4)),
            client_uuid=lox.get("client_uuid", "098802e1-02b4-603c-ffffeee000d80cfd"),
            client_info=lox.get("client_info", "plusconnect-sync"),
        )

        dash_raw = raw["dashboard"]
        dash_cfg = DashboardConfig(
            read_key=self._ensure_read_key(dash_raw.get("read_key")),
            basic_auth_user=dash_raw["basic_auth_user"],
            basic_auth_password=dash_raw["basic_auth_password"],
        )

        sync_raw = raw.get("sync", {})
        sync_cfg = SyncConfig(
            interval_minutes=int(sync_raw.get("interval_minutes", 5)),
            delete_after_hours=int(sync_raw.get("delete_after_hours", 48)),
            offset_minutes_before=int(sync_raw.get("offset_minutes_before", 0)),
            offset_minutes_after=int(sync_raw.get("offset_minutes_after", 0)),
        )

        log_raw = raw.get("logging", {})
        log_cfg = LoggingConfig(file=log_raw.get("file", f"logs/{raw['hotel_id']}.log"))

        return HotelConfig(
            hotel_id=raw["hotel_id"],
            timezone=raw.get("timezone"),
            previo=prev,
            loxone=lox_cfg,
            dashboard=dash_cfg,
            sync=sync_cfg,
            logging=log_cfg,
        )


def load_configs() -> Dict[str, HotelConfig]:
    loader = ConfigLoader()
    return loader.load_all()
