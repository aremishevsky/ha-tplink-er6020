"""Constants for the TP-Link ER6020 integration."""
DOMAIN = "tplink_er6020"

CONF_TRACKED_MAC = "tracked_mac"
CONF_RULES = "rules"
CONF_AWAY_DELAY = "away_delay"
CONF_SCAN_INTERVAL = "scan_interval"  # legacy, minutes (0.3.2-0.3.3)
CONF_POLL_INTERVAL = "poll_interval"  # seconds
CONF_SCHEDULE_ENABLED = "schedule_enabled"
CONF_ACTIVE_FROM = "active_from"
CONF_ACTIVE_TO = "active_to"
CONF_NOTIFY_ENABLED = "notify_enabled"
CONF_NOTIFY_ON_OPEN = "notify_on_open"
CONF_NOTIFY_ON_CLOSE = "notify_on_close"
CONF_NOTIFY_SERVICE = "notify_service"  # legacy single channel (<= 0.3.0)
CONF_NOTIFY_SERVICES = "notify_services"
CONF_SEND_TEST = "send_test"

DEFAULT_HOST = "192.168.0.1"
DEFAULT_USERNAME = "admin"
DEFAULT_AWAY_DELAY = 10  # minutes
# Outside this window the controlled ports are always closed (night).
DEFAULT_ACTIVE_FROM = "07:00:00"
DEFAULT_ACTIVE_TO = "23:00:00"

DEFAULT_POLL_INTERVAL = 120  # seconds

# Why a rule changed state (shown in the card's log).
SOURCE_AWAY = "away"
SOURCE_HOME = "home"
SOURCE_SCHEDULE = "schedule"
SOURCE_MANUAL = "manual"
SOURCE_ROUTER = "router"

LOG_SIZE = 30  # events kept per rule

CARD_URL = "/tplink_er6020/tplink-er6020-card.js"


def poll_interval(options) -> int:
    """Polling interval in seconds; migrates the minutes-based option of 0.3.2."""
    if CONF_POLL_INTERVAL in options:
        return int(options[CONF_POLL_INTERVAL])
    if CONF_SCAN_INTERVAL in options:
        return int(options[CONF_SCAN_INTERVAL]) * 60
    return DEFAULT_POLL_INTERVAL
