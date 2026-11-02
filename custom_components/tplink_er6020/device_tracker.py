"""Presence of the tracked device, based on the router's ARP table."""
from __future__ import annotations

from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ER6020ConfigEntry
from .const import CONF_TRACKED_MAC
from .coordinator import Client, ER6020Coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ER6020ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if mac := entry.options.get(CONF_TRACKED_MAC):
        async_add_entities([ClientTracker(entry.runtime_data, mac)])


class ClientTracker(CoordinatorEntity[ER6020Coordinator], ScannerEntity):
    def __init__(self, coordinator: ER6020Coordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = mac

    @property
    def entity_registry_enabled_default(self) -> bool:
        # ScannerEntity disables MAC trackers unknown to other integrations;
        # this one was explicitly chosen by the user.
        return True

    @property
    def _client(self) -> Client | None:
        return self.coordinator.data.clients.get(self._mac)

    @property
    def name(self) -> str:
        client = self._client
        return (client and client.name) or self._mac

    @property
    def available(self) -> bool:
        # Presence is unknown while polling is off.
        return super().available and self.coordinator.data.present is not None

    @property
    def is_connected(self) -> bool:
        return self._mac in (self.coordinator.data.present or ())

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def ip_address(self) -> str | None:
        client = self._client
        return client.ip if client else None

    @property
    def hostname(self) -> str | None:
        client = self._client
        return client.name if client else None
