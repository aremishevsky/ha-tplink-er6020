"""Switches: one per Virtual Server rule, plus the router polling toggle."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ER6020ConfigEntry
from .api import ER6020Error
from .const import (
    CONF_ACTIVE_FROM,
    CONF_ACTIVE_TO,
    CONF_AWAY_DELAY,
    CONF_RULES,
    CONF_TRACKED_MAC,
    DEFAULT_ACTIVE_FROM,
    DEFAULT_ACTIVE_TO,
    DEFAULT_AWAY_DELAY,
    DOMAIN,
    SOURCE_MANUAL,
)
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
        if coordinator.data is None:
            return
        new = [n for n in coordinator.data.virtual_servers if n not in known]
        known.update(new)
        async_add_entities(VirtualServerSwitch(coordinator, name) for name in new)

    async_add_entities([PollingSwitch(coordinator)])
    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


def _device_info(coordinator: ER6020Coordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        manufacturer="TP-Link",
        model="TL-ER6020",
        name="TL-ER6020",
    )


class VirtualServerSwitch(CoordinatorEntity[ER6020Coordinator], SwitchEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:lan-connect"
    # The log is for the card; keep it out of the recorder database.
    _unrecorded_attributes = frozenset({"log"})

    def __init__(self, coordinator: ER6020Coordinator, rule_name: str) -> None:
        super().__init__(coordinator)
        self._rule_name = rule_name
        self._attr_name = f"Port forward {rule_name}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_vs_{rule_name}"
        self._attr_device_info = _device_info(coordinator)

    @property
    def _rule(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        return data.virtual_servers.get(self._rule_name) if data else None

    @property
    def available(self) -> bool:
        return self._rule is not None

    @property
    def is_on(self) -> bool | None:
        rule = self._rule
        return None if rule is None else rule.get("enable") == "on"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        rule = self._rule
        if rule is None:
            return None
        log = self.coordinator.rule_log(self._rule_name)
        last = {
            state: next((e["ts"] for e in reversed(log) if e["state"] == state), None)
            for state in ("on", "off")
        }
        return {
            "rule": self._rule_name,
            **{
                k: rule.get(k)
                for k in ("interface", "external_port", "internal_port", "ipaddr", "protocol")
            },
            "controlled": self._rule_name in self.coordinator.config_entry.options.get(CONF_RULES, []),
            "last_on": last["on"],
            "last_off": last["off"],
            "log": log,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        try:
            await self.coordinator.async_set_rule(self._rule_name, enabled, SOURCE_MANUAL)
        except ER6020Error as err:
            raise HomeAssistantError(str(err)) from err


class PollingSwitch(CoordinatorEntity[ER6020Coordinator], SwitchEntity):
    """Turn off to stop all requests to the router (e.g. while using its web UI).

    Port switches still work: toggling one sends a request on demand.
    """

    _attr_has_entity_name = True
    _attr_name = "Router polling"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ER6020Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_polling"
        self._attr_device_info = _device_info(coordinator)

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.polling

    @property
    def icon(self) -> str:
        return "mdi:sync" if self.coordinator.polling else "mdi:sync-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        opts = self.coordinator.config_entry.options
        c = self.coordinator
        error = c.automation_error
        if error is None and c.polling and not c.last_update_success:
            error = f"Router not reachable: {c.last_exception}"
        return {
            "automation": c.automation_state,
            "error": error,
            "last_update": c.last_poll,
            "tracked_device": opts.get(CONF_TRACKED_MAC),
            "controlled_rules": opts.get(CONF_RULES, []),
            "away_delay": opts.get(CONF_AWAY_DELAY, DEFAULT_AWAY_DELAY),
            "active_from": opts.get(CONF_ACTIVE_FROM, DEFAULT_ACTIVE_FROM),
            "active_to": opts.get(CONF_ACTIVE_TO, DEFAULT_ACTIVE_TO),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_polling(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_polling(False)
        self.async_write_ha_state()
