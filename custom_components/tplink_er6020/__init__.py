"""TP-Link TL-ER6020 integration: virtual server switches + presence."""
from __future__ import annotations

from aiohttp import CookieJar

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import ER6020Client
from .coordinator import ER6020Coordinator

PLATFORMS = [Platform.SWITCH, Platform.DEVICE_TRACKER]

type ER6020ConfigEntry = ConfigEntry[ER6020Coordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ER6020ConfigEntry) -> bool:
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, False)
    # Router is addressed by IP, so cookies must be accepted for IP hosts.
    session = async_create_clientsession(
        hass, verify_ssl=verify_ssl, cookie_jar=CookieJar(unsafe=True)
    )
    client = ER6020Client(
        session,
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        verify_ssl,
    )
    coordinator = ER6020Coordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ER6020ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: ER6020ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
