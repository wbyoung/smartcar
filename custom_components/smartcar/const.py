"""Constants for the Smartcar integration."""

from enum import StrEnum, auto

DOMAIN = "smartcar"
DEFAULT_NAME = "Smartcar"

# V3 Vehicle API base host. The "/v3" path segment is added by the auth layer.
API_HOST = "https://vehicle.api.smartcar.com"

PLATFORMS = [
    "sensor",
    "switch",
    "lock",
    "device_tracker",
    "binary_sensor",
    "number",
]

# Smartcar Connect — user-consent endpoint. Identifies the application by
# Application ID (NOT the V3 Client ID), and returns an auth code plus userId
# in the redirect. The auth code is discarded; only userId is kept.
OAUTH2_AUTHORIZE = "https://connect.smartcar.com/oauth/authorize"

# V3 IAM token endpoint — application-level access tokens via the
# OAuth 2.0 client_credentials grant. Tokens last 1 hour and are minted
# on demand using the V3 Client ID + Client Secret (separate from the
# Application ID used by Connect).
IAM_TOKEN_URL = "https://iam.smartcar.com/oauth2/token"  # noqa: S105

SMARTCAR_MODE = "live"

# Config entry data keys.
CONF_APPLICATION_ID = "application_id"  # Connect URL client_id parameter.
CONF_CLIENT_ID = "client_id"  # V3 IAM client_id.
CONF_CLIENT_SECRET = "client_secret"  # V3 IAM client_secret.  # noqa: S105
CONF_APPLICATION_MANAGEMENT_TOKEN = "application_management_token"  # noqa: S105
CONF_CLOUDHOOK = "cloudhook"
CONF_SC_USER_ID = "sc_user_id"  # Smartcar user id; sent as sc-user-id header.
CONF_SCOPES = "scopes"  # Permissions returned from /connections after Connect.

# Polling cadence. All intervals are fixed constants — users can't tune
# them in the UI, just toggle whether backup polling runs at all when
# webhooks are configured.
#
#   * Idle (always polling, regardless of webhook configuration) →
#     ``POLL_INTERVAL_MINUTES`` (1 h). Smartcar's API ceiling under the
#     free tier is ~500 calls/vehicle/month; 1 h hits ~720/month for
#     full-time idle, ~480 in practice once charging windows take over.
#   * Charging → ``POLL_INTERVAL_CHARGING_MINUTES`` (15 min). Charging
#     is when missed state hurts most, so the faster cadence applies.
#   * Webhooks + backup polling disabled (default) → no polling.
#
# ``CONF_WEBHOOK_BACKUP_POLLING`` is a boolean exposed in the config and
# options flows; it has no effect when webhooks aren't configured.
CONF_WEBHOOK_BACKUP_POLLING = "webhook_backup_polling"
POLL_INTERVAL_MINUTES = 60
POLL_INTERVAL_CHARGING_MINUTES = 15


class Scope(StrEnum):
    """Smartcar permission scope."""

    READ_VEHICLE_INFO = auto()
    READ_VIN = auto()
    READ_BATTERY = auto()
    READ_CHARGE = auto()
    READ_ENGINE_OIL = auto()
    READ_FUEL = auto()
    READ_LOCATION = auto()
    READ_ODOMETER = auto()
    READ_SECURITY = auto()
    READ_TIRES = auto()
    CONTROL_CHARGE = auto()
    CONTROL_SECURITY = auto()


REQUIRED_SCOPES = [
    Scope.READ_VEHICLE_INFO,
    Scope.READ_VIN,
]

CONFIGURABLE_SCOPES = [scope for scope in Scope if scope not in REQUIRED_SCOPES]

DEFAULT_SCOPES = [
    Scope.READ_BATTERY,
    Scope.READ_CHARGE,
    Scope.READ_LOCATION,
    Scope.READ_ODOMETER,
    Scope.READ_SECURITY,
    Scope.READ_VEHICLE_INFO,
    Scope.READ_VIN,
    Scope.CONTROL_CHARGE,
]


class EntityDescriptionKey(StrEnum):
    """Entity description key enumeration."""

    PLUG_STATUS = auto()
    PLUG_LATCHED = auto()
    CHARGE_PORT_STATUS_COLOR = auto()
    LOCATION = auto()
    DOOR_LOCK = auto()
    DOOR_BACK_LEFT = auto()
    DOOR_BACK_RIGHT = auto()
    DOOR_FRONT_LEFT = auto()
    DOOR_FRONT_RIGHT = auto()
    DOOR_BACK_LEFT_LOCK = auto()
    DOOR_BACK_RIGHT_LOCK = auto()
    DOOR_FRONT_LEFT_LOCK = auto()
    DOOR_FRONT_RIGHT_LOCK = auto()
    CHARGE_LIMIT = auto()
    CHARGE_CHARGERATE = auto()
    CHARGE_ENERGYADDED = auto()
    CHARGE_TIMETOCOMPLETE = auto()
    CHARGING = auto()
    BATTERY_CAPACITY = auto()
    BATTERY_LEVEL = auto()
    BATTERY_HEATER_ACTIVE = auto()
    CHARGING_STATE = auto()
    ENGINE_OIL = auto()
    ENGINE_COVER = auto()
    FUEL = auto()
    FUEL_PERCENT = auto()
    FUEL_RANGE = auto()
    GEAR_STATE = auto()
    LOW_VOLTAGE_BATTERY_LEVEL = auto()
    ODOMETER = auto()
    RANGE = auto()
    TIRE_PRESSURE_BACK_LEFT = auto()
    TIRE_PRESSURE_BACK_RIGHT = auto()
    TIRE_PRESSURE_FRONT_LEFT = auto()
    TIRE_PRESSURE_FRONT_RIGHT = auto()
    WINDOW_BACK_LEFT = auto()
    WINDOW_BACK_RIGHT = auto()
    WINDOW_FRONT_LEFT = auto()
    WINDOW_FRONT_RIGHT = auto()
    FRONT_TRUNK = auto()
    FRONT_TRUNK_LOCK = auto()
    REAR_TRUNK = auto()
    REAR_TRUNK_LOCK = auto()
    SUNROOF = auto()
    ONLINE = auto()
    ASLEEP = auto()
    DIGITAL_KEY_PAIRED = auto()
    SURVEILLANCE_ENABLED = auto()
    CHARGE_VOLTAGE = auto()
    CHARGE_AMPERAGE = auto()
    CHARGE_WATTAGE = auto()
    CHARGE_TIME_TO_COMPLETE = auto()
    CHARGE_AMPERAGE_MAX = auto()
    CHARGE_FAST_CHARGER_PRESENT = auto()
    FIRMWARE_VERSION = auto()
    LAST_WEBHOOK_RECEIVED = auto()
    LAST_POLLED = auto()


DEFAULT_ENABLED_ENTITY_DESCRIPTION_KEYS = {
    EntityDescriptionKey.BATTERY_LEVEL,
    EntityDescriptionKey.CHARGING_STATE,
    EntityDescriptionKey.CHARGING,
    EntityDescriptionKey.DOOR_LOCK,
    EntityDescriptionKey.LOCATION,
    EntityDescriptionKey.PLUG_STATUS,
    EntityDescriptionKey.RANGE,
}
