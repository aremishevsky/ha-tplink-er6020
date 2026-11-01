"""Constants for the TP-Link ER6020 integration."""
from datetime import timedelta

DOMAIN = "tplink_er6020"

CONF_SCAN_INTERVAL = "scan_interval"
CONF_CONSIDER_HOME = "consider_home"

DEFAULT_USERNAME = "admin"
DEFAULT_SCAN_INTERVAL = 60  # seconds
DEFAULT_CONSIDER_HOME = 180  # seconds

MIN_SCAN_INTERVAL = timedelta(seconds=15)
