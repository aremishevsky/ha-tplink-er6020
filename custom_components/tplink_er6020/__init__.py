"""TP-Link ER6020 AutoPortOnOff: open port forwarding while you're away."""
from __future__ import annotations

from pathlib import Path

from aiohttp import CookieJar

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import ER6020Client
from .const import CARD_URL, CONF_TRACKED_MAC, DOMAIN
from .controller import PortController
from .coordinator import ER6020Coordinator

PLATFORMS = [Platform.SWITCH, Platform.DEVICE_TRACKER]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type ER6020ConfigEntry = ConfigEntry[ER6020Coordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the Lovelace card and load it on every dashboard."""
    card = Path(__file__).parent / "frontend" / "tplink-er6020-card.js"
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(card), False)])
    version = (await async_get_integration(hass, DOMAIN)).version
    add_extra_js_url(hass, f"{CARD_URL}?v={version}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ER6020ConfigEntry) -> bool:
    # Router is addressed by IP, so cookies must be accepted for IP hosts.
    session = async_create_clientsession(hass, cookie_jar=CookieJar(unsafe=True))
    client = ER6020Client(
        session,
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = ER6020Coordinator(hass, entry, client)
    await coordinator.async_load()
    # With polling off this uses cached data and makes no requests.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    _async_cleanup_registry(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(PortController(hass, entry, coordinator).async_start())
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ER6020ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: ER6020ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


@callback
def _async_cleanup_registry(hass: HomeAssistant, entry: ER6020ConfigEntry) -> None:
    """Drop trackers/devices for clients other than the tracked one
    (v0.1.x created one per LAN client)."""
    tracked = entry.options.get(CONF_TRACKED_MAC)

    ent_reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if ent.domain != "device_tracker":
            continue
        if ent.unique_id != tracked:
            ent_reg.async_remove(ent.entity_id)
        elif ent.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
            # 0.1.x registered every tracker disabled; the chosen one must work.
            ent_reg.async_update_entity(ent.entity_id, disabled_by=None)

    dev_reg = dr.async_get(hass)
    for dev in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        if (DOMAIN, entry.entry_id) in dev.identifiers:
            continue
        if tracked and (dr.CONNECTION_NETWORK_MAC, tracked) in dev.connections:
            continue
        dev_reg.async_remove_device(dev.id)
