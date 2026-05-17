"""Constants for generac."""
from datetime import timedelta

from homeassistant.helpers import selector

# Base component constants
NAME = "generac"
DOMAIN = "generac"
DOMAIN_DATA = f"{DOMAIN}_data"
VERSION = "0.0.0"

ATTRIBUTION = (
    "Data provided by https://app.mobilelinkgen.com/api. "
    "This is reversed engineered. Heavily inspired by "
    "https://github.com/digitaldan/openhab-addons/blob/generac-2.0/bundles/org.openhab.binding.generacmobilelink/README.md"
)
ISSUE_URL = "https://github.com/binarydev/ha-generac/issues"

# Device types
# 0 = generator
# 1 = ?
# 2 = propane tank monitor
DEVICE_TYPE_GENERATOR = 0
DEVICE_TYPE_UNKNOWN = 1
DEVICE_TYPE_PROPANE_MONITOR = 2
DEVICE_NAME_LIST = ["Generator", "Unknown", "Propane Tank"]

# Allowlisted device types
ALLOWED_DEVICES = [DEVICE_TYPE_GENERATOR, DEVICE_TYPE_PROPANE_MONITOR]

# Defaults
DEFAULT_NAME = DOMAIN
DEFAULT_SCAN_INTERVAL = 120

# Platforms
BINARY_SENSOR = "binary_sensor"
SENSOR = "sensor"
WEATHER = "weather"
IMAGE = "image"
PLATFORMS = [BINARY_SENSOR, SENSOR, WEATHER, IMAGE]

# Configuration labels
CONF_ENABLED = "enabled"
CONF_SESSION_COOKIE = "session_cookie"
CONF_SCAN_INTERVAL = "scan_interval"

# Auto-login (added in 0.5.0)
CONF_EMAIL = "email"
CONF_AUTH_PASSWORD = "auth_password"
CONF_DEVICE_COOKIES = "device_cookies"
CONF_COOKIE_MINTED_AT = "cookie_minted_at"
CONF_IMPERSONATE_PROFILE = "impersonate_profile"

# Cookie lifecycle (epoch seconds compared via time.time())
COOKIE_NOMINAL_TTL = timedelta(days=7)          # observed; documentation only
REMINT_THRESHOLD = timedelta(days=5)            # mint when older than this
MINT_COOLDOWN = timedelta(minutes=10)           # post-failure backoff
MINT_FAIL_LIMIT = 3                              # consecutive failures → reauth

DEFAULT_IMPERSONATE = "chrome120"

# Known curl_cffi==0.7.4 Chrome impersonation profiles. Limits the
# Options field to valid values so a typo surfaces at form-submit
# rather than as a confusing ImpersonationError on the next mint.
# When curl_cffi is upgraded, update this list — keep it in sync with
# scripts/README.md.
IMPERSONATE_PROFILES = [
    "chrome99", "chrome100", "chrome101", "chrome104", "chrome107",
    "chrome110", "chrome116", "chrome119", "chrome120", "chrome123",
    "chrome124",
]

# Options
bool_opts = {}
for p in PLATFORMS:
    bool_opts[p] = {"type": bool, "default": True}
CONF_OPTIONS = {
    **bool_opts,
    CONF_SCAN_INTERVAL: {"type": int, "default": DEFAULT_SCAN_INTERVAL},
    CONF_IMPERSONATE_PROFILE: {
        "type": selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=IMPERSONATE_PROFILES,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        "default": DEFAULT_IMPERSONATE,
    },
}

STARTUP_MESSAGE = f"""
-------------------------------------------------------------------
{NAME}
Version: {VERSION}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""


API_BASE = "https://app.mobilelinkgen.com/api"
LOGIN_BASE = "https://generacconnectivity.b2clogin.com/generacconnectivity.onmicrosoft.com/B2C_1A_MobileLink_SignIn"
