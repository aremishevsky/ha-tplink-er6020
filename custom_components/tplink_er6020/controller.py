"""Open selected port forwarding rules while the tracked device is away.

Away  = tracked MAC missing from the router's ARP table for `away_delay` minutes.
Home  = tracked MAC seen again (ports are closed immediately).
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .api import ER6020Error
from .const import (
    CONF_AWAY_DELAY,
    CONF_NOTIFY_ON_CLOSE,
    CONF_NOTIFY_ON_OPEN,
    CONF_NOTIFY_SERVICE,
    CONF_RULES,
    CONF_TRACKED_MAC,
    DEFAULT_AWAY_DELAY,
    DOMAIN,
)
from .coordinator import ER6020Coordinator

_LOGGER = logging.getLogger(__name__)


class PortController:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ER6020Coordinator) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        opts = entry.options
        self._mac: str | None = opts.get(CONF_TRACKED_MAC)
        self._rules: list[str] = opts.get(CONF_RULES, [])
        self._delay = timedelta(minutes=opts.get(CONF_AWAY_DELAY, DEFAULT_AWAY_DELAY))
        self._last_seen = dt_util.utcnow()
        # None = unknown (e.g. right after HA restart while the device is absent):
        # don't touch the rules until we either see the device or the delay passes.
        self._away: bool | None = None
        self._lock = asyncio.Lock()

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        return self.coordinator.async_add_listener(self._handle_update)

    @callback
    def _handle_update(self) -> None:
        if self._mac and self._rules and self.coordinator.last_update_success:
            self.entry.async_create_background_task(
                self.hass, self._evaluate(), f"{DOMAIN}_evaluate"
            )

    async def _evaluate(self) -> None:
        async with self._lock:
            now = dt_util.utcnow()
            present = self._mac in self.coordinator.data.present
            if present:
                self._last_seen = now
            away = now - self._last_seen >= self._delay
            if not present and not away and self._away is None:
                return
            if away == self._away:
                return
            self._away = away
            try:
                await self._apply(enable=away)
            except ER6020Error as err:
                _LOGGER.error("Failed to %s ports: %s", "open" if away else "close", err)
                self._away = None  # retry on next poll

    async def _apply(self, enable: bool) -> None:
        rules = self.coordinator.data.virtual_servers
        changed: list[str] = []
        for name in self._rules:
            rule = rules.get(name)
            if rule is None:
                _LOGGER.warning("Virtual server rule '%s' no longer exists", name)
                continue
            if (rule.get("enable") == "on") != enable:
                await self.coordinator.client.set_virtual_server_enabled(name, enable)
                changed.append(name)

        if not changed:
            return
        _LOGGER.info("%s ports: %s", "Opened" if enable else "Closed", ", ".join(changed))
        await self.coordinator.async_request_refresh()

        opts = self.entry.options
        if enable and opts.get(CONF_NOTIFY_ON_OPEN, True):
            await self._notify(f"Ports opened (you left home): {', '.join(changed)}")
        elif not enable and opts.get(CONF_NOTIFY_ON_CLOSE, True):
            await self._notify(f"Ports closed (you're home): {', '.join(changed)}")

    async def _notify(self, message: str) -> None:
        title = "TL-ER6020"
        if service := self.entry.options.get(CONF_NOTIFY_SERVICE):
            try:
                await self.hass.services.async_call(
                    "notify", service, {"title": title, "message": message}, blocking=True
                )
                return
            except HomeAssistantError as err:
                _LOGGER.warning("notify.%s failed: %s", service, err)
        persistent_notification.async_create(
            self.hass, message, title, notification_id=f"{DOMAIN}_{self.entry.entry_id}"
        )
