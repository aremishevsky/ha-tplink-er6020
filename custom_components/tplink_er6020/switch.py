"""Switches that enable/disable Virtual Server (port forwarding) rules."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ER6020ConfigEntry
from .api import ER6020Error
from .const import DOMAIN
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
        new = [n for n in coordinator.data.virtual_servers if n not in known]
        known.update(new)
        async_add_entities(VirtualServerSwitch(coordinator, name) for name in new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class VirtualServerSwitch(CoordinatorEntity[ER6020Coordinator], SwitchEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:lan-connect"

    def __init__(self, coordinator: ER6020Coordinator, rule_name: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._rule_name = rule_name
        self._attr_name = f"Port forward {rule_name}"
        self._attr_unique_id = f"{entry_id}_vs_{rule_name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            manufacturer="TP-Link",
            model="TL-ER6020",
            name="TL-ER6020",
        )

    @property
    def _rule(self) -> dict[str, Any] | None:
        return self.coordinator.data.virtual_servers.get(self._rule_name)

    @property
    def available(self) -> bool:
        return super().available and self._rule is not None

    @property
    def is_on(self) -> bool | None:
        rule = self._rule
        return None if rule is None else rule.get("enable") == "on"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        rule = self._rule
        if rule is None:
            return None
        return {
            k: rule.get(k)
            for k in ("interface", "external_port", "internal_port", "ipaddr", "protocol")
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        try:
            await self.coordinator.client.set_virtual_server_enabled(self._rule_name, enabled)
        except ER6020Error as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()
