"""Presence based on the router's ARP table (with consider_home grace period).

Entities are created for every known client but disabled by default;
enable the ones you want to track (e.g. your phone).
"""
from __future__ import annotations

from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ER6020ConfigEntry
from .coordinator import ER6020Coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ER6020ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [mac for mac in coordinator.data.clients if mac not in known]
        known.update(new)
        async_add_entities(ClientTracker(coordinator, mac) for mac in new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class ClientTracker(CoordinatorEntity[ER6020Coordinator], ScannerEntity):
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: ER6020Coordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = mac

    @property
    def _client(self) -> dict:
        return self.coordinator.data.clients.get(self._mac, {})

    @property
    def name(self) -> str:
        return self._client.get("name") or self._mac

    @property
    def is_connected(self) -> bool:
        return self.coordinator.is_home(self._mac)

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def ip_address(self) -> str | None:
        return self._client.get("ip")

    @property
    def hostname(self) -> str | None:
        return self._client.get("name")
