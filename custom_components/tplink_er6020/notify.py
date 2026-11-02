"""Send AutoPortOnOff notifications to the configured channels."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant

from .const import CONF_NOTIFY_SERVICE, CONF_NOTIFY_SERVICES, DOMAIN

_LOGGER = logging.getLogger(__name__)

TITLE = "AutoPortOnOff"
# Pseudo-channel: notification in the Home Assistant UI (bell icon).
HA_UI = "persistent_notification"


def notify_targets(options: Mapping[str, Any]) -> list[str]:
    """Configured channels; migrates the single `notify_service` of 0.2.x/0.3.0."""
    if CONF_NOTIFY_SERVICES in options:
        return list(options[CONF_NOTIFY_SERVICES])
    if legacy := options.get(CONF_NOTIFY_SERVICE):
        return [legacy]
    return [HA_UI]


async def async_notify(
    hass: HomeAssistant, targets: list[str], message: str, title: str = TITLE
) -> dict[str, str]:
    """Send to every target; return {target: error} for the ones that failed."""
    errors: dict[str, str] = {}
    for target in targets:
        if target == HA_UI:
            persistent_notification.async_create(
                hass, message, title, notification_id=f"{DOMAIN}_{hash(message)}"
            )
            continue
        try:
            await hass.services.async_call(
                "notify", target, {"title": title, "message": message}, blocking=True
            )
        except Exception as err:  # noqa: BLE001 - report any failure per channel
            _LOGGER.warning("notify.%s failed: %s", target, err)
            errors[target] = str(err) or type(err).__name__
    return errors
