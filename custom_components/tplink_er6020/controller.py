"""Open selected port forwarding rules while the tracked device is away.

Away     = tracked MAC missing from the router's ARP table for `away_delay` minutes.
Home     = tracked MAC seen again (ports are closed immediately).
Schedule = outside active hours the ports are always closed.
Nothing happens while router polling is off.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .api import ER6020Error
from .const import (
    CONF_ACTIVE_FROM,
    CONF_ACTIVE_TO,
    CONF_AWAY_DELAY,
    CONF_NOTIFY_ON_CLOSE,
    CONF_NOTIFY_ON_OPEN,
    CONF_RULES,
    CONF_TRACKED_MAC,
    DEFAULT_ACTIVE_FROM,
    DEFAULT_ACTIVE_TO,
    DEFAULT_AWAY_DELAY,
    DOMAIN,
    SOURCE_AWAY,
    SOURCE_HOME,
    SOURCE_SCHEDULE,
)
from .coordinator import ER6020Coordinator
from .notify import async_notify, notify_targets

_LOGGER = logging.getLogger(__name__)

RETRY_INTERVAL = timedelta(minutes=2)
_KEEP = object()

MESSAGES = {
    SOURCE_AWAY: "Ports opened (you left home): {}",
    SOURCE_HOME: "Ports closed (you're home): {}",
    SOURCE_SCHEDULE: "Ports closed (outside active hours): {}",
}


def in_window(now: time, start: time, end: time) -> bool:
    """start == end means always active; the window may cross midnight."""
    if start == end:
        return True
    if start < end:
        return start <= now < end
    return now >= start or now < end


class PortController:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ER6020Coordinator) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        opts = entry.options
        self._mac: str | None = opts.get(CONF_TRACKED_MAC)
        self._rules: list[str] = opts.get(CONF_RULES, [])
        self._delay = timedelta(minutes=opts.get(CONF_AWAY_DELAY, DEFAULT_AWAY_DELAY))
        self._start = time.fromisoformat(opts.get(CONF_ACTIVE_FROM, DEFAULT_ACTIVE_FROM))
        self._end = time.fromisoformat(opts.get(CONF_ACTIVE_TO, DEFAULT_ACTIVE_TO))
        self._last_seen = dt_util.utcnow()
        # Last applied decision; None = nothing applied yet.
        self._applied: tuple[bool, str] | None = None
        self._failed: tuple[bool, str] | None = None
        self._retry_at: datetime | None = None
        self._lock = asyncio.Lock()
        # Set while we push our own status to listeners, so it doesn't re-trigger us.
        self._publishing = False

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        return self.coordinator.async_add_listener(self._handle_update)

    @callback
    def _handle_update(self) -> None:
        if self._publishing or self._lock.locked():
            return
        if self._mac and self._rules:
            self.entry.async_create_background_task(
                self.hass, self._evaluate(), f"{DOMAIN}_evaluate"
            )

    def _decide(self, now: datetime) -> tuple[bool, str] | None:
        """Return (open?, reason) or None when the state is unknown."""
        data = self.coordinator.data
        if not in_window(dt_util.as_local(now).time(), self._start, self._end):
            return False, SOURCE_SCHEDULE
        if data.present is None:
            return None
        if self._mac in data.present:
            self._last_seen = now
            return False, SOURCE_HOME
        if now - self._last_seen >= self._delay:
            return True, SOURCE_AWAY
        # Absent but within the delay: keep whatever was decided before.
        # Right after a restart nothing was decided yet, so don't touch the rules.
        return (self._applied[0], "leaving") if self._applied else None

    async def _evaluate(self) -> None:
        async with self._lock:
            if not self.coordinator.polling or not self.coordinator.last_update_success:
                self._set_state("paused" if not self.coordinator.polling else None)
                return
            now = dt_util.utcnow()
            decision = self._decide(now)
            failing = decision is not None and decision == self._failed
            if not failing:
                # Situation changed (e.g. back home): the old error no longer applies.
                self._failed = self._retry_at = None
            self._set_state(
                "error" if failing else None if decision is None else decision[1],
                _KEEP if failing else None,
            )
            if decision is None or decision[0] == (self._applied or (None,))[0]:
                return
            if failing and self._retry_at and now < self._retry_at:
                return
            try:
                await self._apply(*decision)
            except ER6020Error as err:
                action = "open" if decision[0] else "close"
                message = f"Failed to {action} ports: {err}"
                _LOGGER.error(message)
                self._retry_at = now + RETRY_INTERVAL
                self._set_state("error", message)
                # Alert once per decision; it is retried every RETRY_INTERVAL.
                if self._failed != decision:
                    self._failed = decision
                    await async_notify(self.hass, notify_targets(self.entry.options), message)
                return
            self._failed = self._retry_at = None
            self._applied = decision
            self._set_state(decision[1], None)

    @callback
    def _set_state(self, state: str | None, error: str | None | object = _KEEP) -> None:
        """Publish automation state/error for the polling switch and the card."""
        c = self.coordinator
        new_error = c.automation_error if error is _KEEP else error
        if c.automation_state == state and c.automation_error == new_error:
            return
        c.automation_state, c.automation_error = state, new_error
        self._publishing = True
        try:
            c.async_update_listeners()
        finally:
            self._publishing = False

    async def _apply(self, enable: bool, source: str) -> None:
        rules = self.coordinator.data.virtual_servers
        changed: list[str] = []
        for name in self._rules:
            rule = rules.get(name)
            if rule is None:
                _LOGGER.warning("Virtual server rule '%s' no longer exists", name)
                continue
            if (rule.get("enable") == "on") != enable:
                await self.coordinator.async_set_rule(name, enable, source)
                changed.append(name)

        if not changed:
            return
        _LOGGER.info("%s ports (%s): %s", "Opened" if enable else "Closed", source, ", ".join(changed))
        opts = self.entry.options
        if opts.get(CONF_NOTIFY_ON_OPEN if enable else CONF_NOTIFY_ON_CLOSE, True):
            await async_notify(
                self.hass, notify_targets(opts), MESSAGES[source].format(", ".join(changed))
            )
