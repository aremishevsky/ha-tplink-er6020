"""Config and options flow for the TP-Link ER6020 integration."""
from __future__ import annotations

from collections.abc import Mapping
import ipaddress
import logging
from typing import Any

from aiohttp import CookieJar
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TimeSelector,
)

from .api import ER6020AuthError, ER6020Client, ER6020Error
from .const import (
    CONF_ACTIVE_FROM,
    CONF_ACTIVE_TO,
    CONF_AWAY_DELAY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_ON_CLOSE,
    CONF_NOTIFY_ON_OPEN,
    CONF_NOTIFY_SERVICES,
    CONF_SEND_TEST,
    CONF_RULES,
    CONF_POLL_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_SCHEDULE_ENABLED,
    CONF_TRACKED_MAC,
    DEFAULT_ACTIVE_FROM,
    DEFAULT_ACTIVE_TO,
    DEFAULT_AWAY_DELAY,
    DEFAULT_HOST,
    DEFAULT_USERNAME,
    DOMAIN,
    poll_interval,
)
from .coordinator import Client, RouterData, fetch_router_data
from .notify import HA_UI, async_notify, notify_targets

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


def _ip_sort_key(ip: str | None) -> int:
    try:
        return int(ipaddress.ip_address(ip or ""))
    except ValueError:
        return 1 << 32


def _client_label(c: Client) -> str:
    prefix = "★ " if c.reserved else ""
    return f"{prefix}{c.name or 'Unknown'} — {c.ip or '?'} ({c.mac.upper()})"


def _rule_label(name: str, rule: dict[str, Any]) -> str:
    return (
        f"{name}: {rule.get('external_port')} → {rule.get('ipaddr')}:"
        f"{rule.get('internal_port')} {rule.get('protocol') or ''}".rstrip()
    )


def settings_schema(
    hass: HomeAssistant, router: RouterData, defaults: Mapping[str, Any]
) -> vol.Schema:
    """Main settings: tracked device, rules, timings, which optional steps to show."""
    # Reserved (saved) devices first, then the rest; each group by IP.
    clients = sorted(router.clients.values(), key=lambda c: (not c.reserved, _ip_sort_key(c.ip)))
    devices = [SelectOptionDict(value=c.mac, label=_client_label(c)) for c in clients]
    tracked = defaults.get(CONF_TRACKED_MAC)
    if tracked and tracked not in router.clients:
        devices.insert(0, SelectOptionDict(value=tracked, label=f"{tracked.upper()} (offline)"))

    rules = [
        SelectOptionDict(value=name, label=_rule_label(name, rule))
        for name, rule in router.virtual_servers.items()
    ]
    selected_rules = [r for r in defaults.get(CONF_RULES, []) if r in router.virtual_servers]

    tracked_key = (
        vol.Required(CONF_TRACKED_MAC, default=tracked)
        if tracked
        else vol.Required(CONF_TRACKED_MAC)
    )
    return vol.Schema(
        {
            tracked_key: SelectSelector(
                SelectSelectorConfig(options=devices, mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(CONF_RULES, default=selected_rules): SelectSelector(
                SelectSelectorConfig(options=rules, multiple=True, mode=SelectSelectorMode.LIST)
            ),
            vol.Required(
                CONF_AWAY_DELAY, default=defaults.get(CONF_AWAY_DELAY, DEFAULT_AWAY_DELAY)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=1440, step=1, unit_of_measurement="min", mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(CONF_POLL_INTERVAL, default=poll_interval(defaults)): NumberSelector(
                NumberSelectorConfig(
                    min=30, max=3600, step=1, unit_of_measurement="s", mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_SCHEDULE_ENABLED, default=defaults.get(CONF_SCHEDULE_ENABLED, True)
            ): BooleanSelector(),
            vol.Required(
                CONF_NOTIFY_ENABLED, default=defaults.get(CONF_NOTIFY_ENABLED, True)
            ): BooleanSelector(),
        }
    )


def schedule_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    """Shown only when "Use schedule" is ticked."""
    return vol.Schema(
        {
            vol.Required(
                CONF_ACTIVE_FROM, default=defaults.get(CONF_ACTIVE_FROM, DEFAULT_ACTIVE_FROM)
            ): TimeSelector(),
            vol.Required(
                CONF_ACTIVE_TO, default=defaults.get(CONF_ACTIVE_TO, DEFAULT_ACTIVE_TO)
            ): TimeSelector(),
        }
    )


def notifications_schema(hass: HomeAssistant, defaults: Mapping[str, Any]) -> vol.Schema:
    """Shown only when "Use notifications" is ticked."""
    services = sorted(
        s for s in hass.services.async_services().get("notify", {}) if s not in ("send_message", HA_UI)
    )
    channels = [SelectOptionDict(value=HA_UI, label="Home Assistant UI (notification bell)")] + [
        SelectOptionDict(value=s, label=f"notify.{s}") for s in services
    ]
    selected = [t for t in notify_targets(defaults) if t == HA_UI or t in services]
    return vol.Schema(
        {
            vol.Required(
                CONF_NOTIFY_ON_OPEN, default=defaults.get(CONF_NOTIFY_ON_OPEN, True)
            ): BooleanSelector(),
            vol.Required(
                CONF_NOTIFY_ON_CLOSE, default=defaults.get(CONF_NOTIFY_ON_CLOSE, True)
            ): BooleanSelector(),
            vol.Optional(CONF_NOTIFY_SERVICES, default=selected): SelectSelector(
                SelectSelectorConfig(options=channels, multiple=True, mode=SelectSelectorMode.LIST)
            ),
            vol.Optional(CONF_SEND_TEST, default=False): BooleanSelector(),
        }
    )


# Values from optional steps that survive when the step is switched off.
_KEPT = (CONF_ACTIVE_FROM, CONF_ACTIVE_TO, CONF_NOTIFY_ON_OPEN, CONF_NOTIFY_ON_CLOSE, CONF_NOTIFY_SERVICES)


def _normalize(user_input: dict[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Clean main-step input; keep values of the optional steps from before."""
    previous = previous or {}
    data = {k: v for k, v in previous.items() if k in _KEPT}
    if previous and CONF_NOTIFY_SERVICES not in data:
        data[CONF_NOTIFY_SERVICES] = notify_targets(previous)  # legacy notify_service
    data |= {k: v for k, v in user_input.items() if k != CONF_SCAN_INTERVAL}
    data[CONF_AWAY_DELAY] = int(data[CONF_AWAY_DELAY])
    data[CONF_POLL_INTERVAL] = int(data.get(CONF_POLL_INTERVAL, poll_interval(previous)))
    return data


async def _send_test(hass: HomeAssistant, targets: list[str]) -> str:
    """Send a test notification; return a line for the form description."""
    if not targets:
        return "⚠️ Select at least one notification channel."
    errors = await async_notify(hass, targets, "Test notification — notifications work ✅")
    parts = []
    if ok := [t for t in targets if t not in errors]:
        parts.append("✅ Test sent to: " + ", ".join(ok))
    if errors:
        parts.append("⚠️ Failed: " + "; ".join(f"{t} ({e})" for t, e in errors.items()))
    return "\n\n".join(parts) + "\n\nUntick *Send a test notification* and press Submit to save."


class _SettingsSteps:
    """Settings → (schedule) → (notifications); shared by the config and options flows."""

    hass: HomeAssistant
    _options: dict[str, Any]
    _previous: Mapping[str, Any]

    def _get_router(self) -> RouterData:
        raise NotImplementedError

    def _finish(self) -> ConfigFlowResult:
        raise NotImplementedError

    async def _settings_step(self, step_id: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        if user_input is not None:
            self._options = _normalize(user_input, self._previous)
            if self._options[CONF_SCHEDULE_ENABLED]:
                return await self.async_step_schedule()
            return await self._after_schedule()
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id=step_id, data_schema=settings_schema(self.hass, self._get_router(), self._previous)
        )

    async def async_step_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._options |= user_input
            return await self._after_schedule()
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="schedule", data_schema=schedule_schema(self._options)
        )

    async def _after_schedule(self) -> ConfigFlowResult:
        if self._options[CONF_NOTIFY_ENABLED]:
            return await self.async_step_notifications()
        return self._finish()

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        result = ""
        if user_input is not None:
            send_test = user_input.get(CONF_SEND_TEST, False)
            self._options |= {k: v for k, v in user_input.items() if k != CONF_SEND_TEST}
            self._options.setdefault(CONF_NOTIFY_SERVICES, [])
            if not send_test:
                return self._finish()
            result = await _send_test(self.hass, self._options[CONF_NOTIFY_SERVICES])
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="notifications",
            data_schema=notifications_schema(self.hass, self._options),
            description_placeholders={"test_result": result},
        )


class ER6020ConfigFlow(_SettingsSteps, ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, Any] = {}
        self._router_data: RouterData | None = None
        self._options: dict[str, Any] = {}
        self._previous: Mapping[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()

            errors, router = await self._validate(user_input)
            if not errors:
                self._credentials = user_input
                self._router_data = router
                return await self.async_step_settings()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._settings_step("settings", user_input)

    def _get_router(self) -> RouterData:
        assert self._router_data is not None
        return self._router_data

    def _finish(self) -> ConfigFlowResult:
        return self.async_create_entry(
            title=f"AutoPortOnOff ({self._credentials[CONF_HOST]})",
            data=self._credentials,
            options=self._options,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            errors, _ = await self._validate(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    async def _validate(self, data: dict[str, Any]) -> tuple[dict[str, str], RouterData | None]:
        session = async_create_clientsession(self.hass, cookie_jar=CookieJar(unsafe=True))
        client = ER6020Client(
            session, data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD]
        )
        try:
            await client.login()
            router = await fetch_router_data(client)
        except ER6020AuthError as err:
            _LOGGER.warning("Login to %s rejected: %s", data[CONF_HOST], err)
            return {"base": "invalid_auth"}, None
        except ER6020Error as err:
            _LOGGER.warning("Cannot connect to %s: %s", data[CONF_HOST], err)
            return {"base": "cannot_connect"}, None
        return {}, router

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ER6020OptionsFlow()


class ER6020OptionsFlow(_SettingsSteps, OptionsFlow):
    def __init__(self) -> None:
        self._options: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is None or coordinator.data is None:
            return self.async_abort(reason="not_loaded")
        self._previous = self.config_entry.options
        return await self._settings_step("init", user_input)

    def _get_router(self) -> RouterData:
        return self.config_entry.runtime_data.data

    def _finish(self) -> ConfigFlowResult:
        return self.async_create_entry(data=self._options)
