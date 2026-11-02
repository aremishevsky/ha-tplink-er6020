"""Constants for the TP-Link ER6020 integration."""
from datetime import timedelta

DOMAIN = "tplink_er6020"

CONF_TRACKED_MAC = "tracked_mac"
CONF_RULES = "rules"
CONF_AWAY_DELAY = "away_delay"
CONF_NOTIFY_ON_OPEN = "notify_on_open"
CONF_NOTIFY_ON_CLOSE = "notify_on_close"
CONF_NOTIFY_SERVICE = "notify_service"

DEFAULT_HOST = "192.168.0.1"
DEFAULT_USERNAME = "admin"
DEFAULT_AWAY_DELAY = 10  # minutes

SCAN_INTERVAL = timedelta(seconds=30)
