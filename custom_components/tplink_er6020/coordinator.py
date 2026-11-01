"""Data update coordinator for the TP-Link ER6020 integration."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ER6020AuthError, ER6020Client, ER6020Error
from .const import (
    CONF_CONSIDER_HOME,
    CONF_SCAN_INTERVAL,
    DEFAULT_CONSIDER_HOME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class RouterData:
    virtual_servers: dict[str, dict[str, Any]] = field(default_factory=dict)
    # mac -> {"ip": ..., "name": ...}
    clients: dict[str, dict[str, Any]] = field(default_factory=dict)


class ER6020Coordinator(DataUpdateCoordinator[RouterData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: ER6020Client) -> None:
        interval = timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=max(interval, MIN_SCAN_INTERVAL),
        )
        self.client = client
        self.consider_home = timedelta(
            seconds=entry.options.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME)
        )
        self.last_seen: dict[str, datetime] = {}

    async def _async_update_data(self) -> RouterData:
        try:
            rules = await self.client.get_virtual_servers()
            dhcp = await self.client.get_dhcp_clients()
            arp = await self.client.get_arp_list()
        except ER6020AuthError as err:
            # Router locks login after ~10 failures: stop polling, ask to reauth.
            raise ConfigEntryAuthFailed(str(err)) from err
        except ER6020Error as err:
            raise UpdateFailed(str(err)) from err

        data = RouterData(virtual_servers={r["name"]: r for r in rules if r.get("name")})

        for lease in dhcp:
            if mac := lease.get("macaddr"):
                data.clients[format_mac(mac)] = {
                    "ip": lease.get("ipaddr"),
                    "name": lease.get("name") or None,
                }

        now = dt_util.utcnow()
        for entry in arp:
            if not (mac := entry.get("mac")):
                continue
            mac = format_mac(mac)
            self.last_seen[mac] = now
            data.clients.setdefault(mac, {"ip": entry.get("ipaddr"), "name": None})

        return data

    def is_home(self, mac: str) -> bool:
        seen = self.last_seen.get(mac)
        return seen is not None and dt_util.utcnow() - seen < self.consider_home
