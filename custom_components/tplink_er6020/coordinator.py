"""Data update coordinator for the TP-Link ER6020 integration."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ER6020AuthError, ER6020Client, ER6020Error
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


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
    # MACs currently in the router's ARP table
    present: set[str] = field(default_factory=set)


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
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> RouterData:
        try:
            return await fetch_router_data(self.client)
        except ER6020AuthError as err:
            # Router locks login after ~10 failures: stop polling, ask to reauth.
            raise ConfigEntryAuthFailed(str(err)) from err
        except ER6020Error as err:
            raise UpdateFailed(str(err)) from err
