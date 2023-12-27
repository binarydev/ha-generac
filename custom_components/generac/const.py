"""Constants for generac."""
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
DEFAULT_SCAN_INTERVAL = 30

# Platforms
BINARY_SENSOR = "binary_sensor"
SENSOR = "sensor"
WEATHER = "weather"
IMAGE = "image"
PLATFORMS = [BINARY_SENSOR, SENSOR, WEATHER, IMAGE]

# Configuration labels
CONF_ENABLED = "enabled"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"

# Options
bool_opts = {}
for p in PLATFORMS:
    bool_opts[p] = {"type": bool, "default": True}
CONF_OPTIONS = {
    **bool_opts,
    CONF_SCAN_INTERVAL: {"type": int, "default": DEFAULT_SCAN_INTERVAL},
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
