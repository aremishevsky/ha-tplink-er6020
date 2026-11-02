"""Data update coordinator for the TP-Link ER6020 integration."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ER6020AuthError, ER6020Client, ER6020Error
from .const import DOMAIN, LOG_SIZE, SOURCE_ROUTER, poll_interval

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


@dataclass
class Client:
    mac: str
    ip: str | None = None
    name: str | None = None
    reserved: bool = False


@dataclass
class RouterData:
    virtual_servers: dict[str, dict[str, Any]] = field(default_factory=dict)
    clients: dict[str, Client] = field(default_factory=dict)
    # MACs currently in the router's ARP table; None = unknown (polling off / cached)
    present: set[str] | None = field(default_factory=set)

    def to_cache(self) -> dict[str, Any]:
        return {
            "virtual_servers": self.virtual_servers,
            "clients": {mac: asdict(c) for mac, c in self.clients.items()},
        }

    @classmethod
    def from_cache(cls, data: dict[str, Any]) -> RouterData:
        return cls(
            virtual_servers=data.get("virtual_servers", {}),
            clients={mac: Client(**c) for mac, c in data.get("clients", {}).items()},
            present=None,
        )


async def fetch_router_data(client: ER6020Client) -> RouterData:
    """Fetch rules and merge reservations, DHCP leases and ARP into one client list."""
    rules = await client.get_virtual_servers()
    reservations = await client.get_dhcp_reservations()
    leases = await client.get_dhcp_clients()
    arp = await client.get_arp_list()

    data = RouterData(virtual_servers={r["name"]: r for r in rules if r.get("name")})

    def _client(raw_mac: str | None) -> Client | None:
        if not raw_mac:
            return None
        mac = format_mac(raw_mac)
        return data.clients.setdefault(mac, Client(mac))

    for res in reservations:
        if c := _client(res.get("mac")):
            c.reserved = True
            c.ip = res.get("ip") or c.ip
            c.name = res.get("note") or c.name
    for lease in leases:
        if c := _client(lease.get("macaddr")):
            c.ip = c.ip or lease.get("ipaddr")
            c.name = c.name or lease.get("name") or None
    for entry in arp:
        if c := _client(entry.get("mac")):
            c.ip = c.ip or entry.get("ipaddr")
            data.present.add(c.mac)

    return data


class ER6020Coordinator(DataUpdateCoordinator[RouterData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: ER6020Client) -> None:
        self._interval = timedelta(seconds=poll_interval(entry.options))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=self._interval,
        )
        self.client = client
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._stored: dict[str, Any] = {}
        # Written by the controller, shown by the card.
        self.automation_state: str | None = None
        self.automation_error: str | None = None

    async def async_load(self) -> None:
        self._stored = await self._store.async_load() or {}
        self._stored.setdefault("polling", True)
        self._stored.setdefault("automation", True)
        self._stored.setdefault("log", {})
        if not self.polling:
            self.update_interval = None

    def _save(self) -> None:
        self._store.async_delay_save(lambda: self._stored, 5)

    async def async_shutdown(self) -> None:
        """Flush pending log/cache writes before the entry is unloaded/reloaded."""
        await super().async_shutdown()
        await self._store.async_save(self._stored)

    # --- polling -----------------------------------------------------------

    @property
    def polling(self) -> bool:
        return self._stored.get("polling", True)

    @property
    def automation_enabled(self) -> bool:
        return self._stored.get("automation", True)

    @callback
    def async_set_automation(self, enabled: bool) -> None:
        self._stored["automation"] = enabled
        self._save()
        self.async_update_listeners()

    @property
    def last_poll(self) -> str | None:
        """Time of the last successful read from the router (ISO, UTC)."""
        return self._stored.get("last_poll")

    async def async_set_polling(self, enabled: bool) -> None:
        self._stored["polling"] = enabled
        self._save()
        self.update_interval = self._interval if enabled else None
        if enabled:
            await self.async_refresh()
        elif self.data is not None:
            # Presence becomes unknown while we don't look at the router.
            self.data.present = None
            self.async_set_updated_data(self.data)

    async def _async_update_data(self) -> RouterData:
        cache = self._stored.get("cache")
        if not self.polling and (self.data is not None or cache):
            return self.data or RouterData.from_cache(cache)

        try:
            data = await fetch_router_data(self.client)
        except ER6020AuthError as err:
            # Router locks login after ~10 failures: stop polling, ask to reauth.
            raise ConfigEntryAuthFailed(str(err)) from err
        except ER6020Error as err:
            raise UpdateFailed(str(err)) from err

        # Persisted together with the next cache/log save, not on every poll.
        self._stored["last_poll"] = dt_util.utcnow().isoformat()
        previous = self.data or (RouterData.from_cache(cache) if cache else None)
        if previous is not None:
            for name, rule in data.virtual_servers.items():
                old = previous.virtual_servers.get(name)
                if old is not None and old.get("enable") != rule.get("enable"):
                    self._log(name, rule.get("enable") == "on", SOURCE_ROUTER)

        new_cache = data.to_cache()
        if new_cache != cache:
            self._stored["cache"] = new_cache
            self._save()
        return data

    # --- rule changes ------------------------------------------------------

    async def async_set_rule(self, name: str, enabled: bool, source: str) -> None:
        """Change a rule on the router and update local state without a re-poll."""
        await self.client.set_virtual_server_enabled(name, enabled)
        if self.data is not None and (rule := self.data.virtual_servers.get(name)):
            rule["enable"] = "on" if enabled else "off"
            self._stored["cache"] = self.data.to_cache()
        self._log(name, enabled, source)
        if self.data is not None:
            self.async_set_updated_data(self.data)

    def _log(self, name: str, enabled: bool, source: str) -> None:
        events = self._stored["log"].setdefault(name, [])
        events.append(
            {"ts": dt_util.utcnow().isoformat(), "state": "on" if enabled else "off", "source": source}
        )
        del events[:-LOG_SIZE]
        self._save()

    def rule_log(self, name: str) -> list[dict[str, str]]:
        return self._stored["log"].get(name, [])
