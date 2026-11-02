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
    CONF_NOTIFY_ON_CLOSE,
    CONF_NOTIFY_ON_OPEN,
    CONF_NOTIFY_SERVICES,
    CONF_SEND_TEST,
    CONF_RULES,
    CONF_SCAN_INTERVAL,
    CONF_TRACKED_MAC,
    DEFAULT_ACTIVE_FROM,
    DEFAULT_ACTIVE_TO,
    DEFAULT_AWAY_DELAY,
    DEFAULT_HOST,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USERNAME,
    DOMAIN,
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
    """Step 2: tracked device, rules to control, delay, notifications."""
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

    services = sorted(
        s for s in hass.services.async_services().get("notify", {}) if s not in ("send_message", HA_UI)
    )
    channels = [SelectOptionDict(value=HA_UI, label="Home Assistant UI (notification bell)")] + [
        SelectOptionDict(value=s, label=f"notify.{s}") for s in services
    ]
    selected_channels = [t for t in notify_targets(defaults) if t == HA_UI or t in services]

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
            vol.Required(
                CONF_SCAN_INTERVAL, default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=60, step=1, unit_of_measurement="min", mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_ACTIVE_FROM, default=defaults.get(CONF_ACTIVE_FROM, DEFAULT_ACTIVE_FROM)
            ): TimeSelector(),
            vol.Required(
                CONF_ACTIVE_TO, default=defaults.get(CONF_ACTIVE_TO, DEFAULT_ACTIVE_TO)
            ): TimeSelector(),
            vol.Required(
                CONF_NOTIFY_ON_OPEN, default=defaults.get(CONF_NOTIFY_ON_OPEN, True)
            ): BooleanSelector(),
            vol.Required(
                CONF_NOTIFY_ON_CLOSE, default=defaults.get(CONF_NOTIFY_ON_CLOSE, True)
            ): BooleanSelector(),
            vol.Optional(CONF_NOTIFY_SERVICES, default=selected_channels): SelectSelector(
                SelectSelectorConfig(options=channels, multiple=True, mode=SelectSelectorMode.LIST)
            ),
            vol.Optional(CONF_SEND_TEST, default=False): BooleanSelector(),
        }
    )


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    data = {**user_input, CONF_AWAY_DELAY: int(user_input[CONF_AWAY_DELAY])}
    if CONF_SCAN_INTERVAL in data:
        data[CONF_SCAN_INTERVAL] = int(data[CONF_SCAN_INTERVAL])
    data.pop(CONF_SEND_TEST, None)
    data.setdefault(CONF_NOTIFY_SERVICES, [])
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


class ER6020ConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, Any] = {}
        self._router: RouterData | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()

            errors, router = await self._validate(user_input)
            if not errors:
                self._credentials = user_input
                self._router = router
                return await self.async_step_settings()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._router is not None
        result = ""
        if user_input is not None:
            if not user_input.get(CONF_SEND_TEST):
                return self.async_create_entry(
                    title=f"AutoPortOnOff ({self._credentials[CONF_HOST]})",
                    data=self._credentials,
                    options=_normalize(user_input),
                )
            result = await _send_test(self.hass, user_input.get(CONF_NOTIFY_SERVICES, []))
        return self.async_show_form(
            step_id="settings",
            data_schema=settings_schema(self.hass, self._router, _normalize(user_input) if user_input else {}),
            description_placeholders={"test_result": result},
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


class ER6020OptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is None or coordinator.data is None:
            return self.async_abort(reason="not_loaded")

        result = ""
        defaults: Mapping[str, Any] = self.config_entry.options
        if user_input is not None:
            if not user_input.get(CONF_SEND_TEST):
                return self.async_create_entry(data=_normalize(user_input))
            result = await _send_test(self.hass, user_input.get(CONF_NOTIFY_SERVICES, []))
            defaults = _normalize(user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=settings_schema(self.hass, coordinator.data, defaults),
            description_placeholders={"test_result": result},
        )
