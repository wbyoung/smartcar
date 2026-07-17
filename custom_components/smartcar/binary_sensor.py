from dataclasses import dataclass
import logging
import operator

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import EntityDescriptionKey
from .coordinator import (
    VEHICLE_BACK_ROW,
    VEHICLE_FRONT_ROW,
    VEHICLE_LEFT_COLUMN,
    VEHICLE_RIGHT_COLUMN,
    SmartcarVehicleCoordinator,
)
from .entity import SmartcarEntity, SmartcarEntityDescription

_LOGGER = logging.getLogger(__name__)


def _hvac_bool(body: object) -> object:
    """Extract a boolean from an HVAC webhook signal body ({"value": bool}).

    Returns:
        The extracted boolean or the body unchanged.
    """
    if isinstance(body, dict):
        return body.get("value")
    return body


@dataclass(frozen=True, kw_only=True)
class SmartcarBinarySensorDescription(
    BinarySensorEntityDescription, SmartcarEntityDescription
):
    """Class describing Smartcar binary sensor entities."""


SENSOR_TYPES: tuple[BinarySensorEntityDescription, ...] = (
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.PLUG_STATUS,
        name="Charging Cable Plugged In",
        value_key_path="charge-ischargingcableconnected.value",
        device_class=BinarySensorDeviceClass.PLUG,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.BATTERY_HEATER_ACTIVE,
        name="Battery Heater Active",
        value_key_path="tractionbattery-isheateractive.value",
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.FRONT_TRUNK,
        name="Front Trunk",
        value_key_path="closure-fronttrunk.isOpen",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.FRONT_TRUNK_LOCK,
        name="Front Trunk Lock",
        value_key_path="closure-fronttrunk.isLocked",
        value_cast=operator.not_,
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.SUNROOF,
        name="Sunroof",
        value_key_path="closure-sunroof.isOpen",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.DOOR_BACK_LEFT_LOCK,
        name="Door Back Left Lock",
        value_key_path="closure-doors.values",
        icon="mdi:car-door-lock",
        value_cast=lambda values: next(
            (
                not value["isLocked"]
                for value in values or []
                if value["row"] == VEHICLE_BACK_ROW
                and value["column"] == VEHICLE_LEFT_COLUMN
            ),
            None,
        ),
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.DOOR_BACK_RIGHT_LOCK,
        name="Door Back Right Lock",
        value_key_path="closure-doors.values",
        icon="mdi:car-door-lock",
        value_cast=lambda values: next(
            (
                not value["isLocked"]
                for value in values or []
                if value["row"] == VEHICLE_BACK_ROW
                and value["column"] == VEHICLE_RIGHT_COLUMN
            ),
            None,
        ),
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.DOOR_FRONT_LEFT_LOCK,
        name="Door Front Left Lock",
        value_key_path="closure-doors.values",
        icon="mdi:car-door-lock",
        value_cast=lambda values: next(
            (
                not value["isLocked"]
                for value in values or []
                if value["row"] == VEHICLE_FRONT_ROW
                and value["column"] == VEHICLE_LEFT_COLUMN
            ),
            None,
        ),
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.DOOR_FRONT_RIGHT_LOCK,
        name="Door Front Right Lock",
        value_key_path="closure-doors.values",
        icon="mdi:car-door-lock",
        value_cast=lambda values: next(
            (
                not value["isLocked"]
                for value in values or []
                if value["row"] == VEHICLE_FRONT_ROW
                and value["column"] == VEHICLE_RIGHT_COLUMN
            ),
            None,
        ),
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.DOOR_BACK_LEFT,
        name="Door Back Left",
        value_key_path="closure-doors.values",
        icon="mdi:car-door",
        value_cast=lambda values: next(
            (
                value["isOpen"]
                for value in values or []
                if value["row"] == VEHICLE_BACK_ROW
                and value["column"] == VEHICLE_LEFT_COLUMN
            ),
            None,
        ),
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.DOOR_BACK_RIGHT,
        name="Door Back Right",
        value_key_path="closure-doors.values",
        icon="mdi:car-door",
        value_cast=lambda values: next(
            (
                value["isOpen"]
                for value in values or []
                if value["row"] == VEHICLE_BACK_ROW
                and value["column"] == VEHICLE_RIGHT_COLUMN
            ),
            None,
        ),
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.DOOR_FRONT_LEFT,
        name="Door Front Left",
        value_key_path="closure-doors.values",
        icon="mdi:car-door",
        value_cast=lambda values: next(
            (
                value["isOpen"]
                for value in values or []
                if value["row"] == VEHICLE_FRONT_ROW
                and value["column"] == VEHICLE_LEFT_COLUMN
            ),
            None,
        ),
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.DOOR_FRONT_RIGHT,
        name="Door Front Right",
        value_key_path="closure-doors.values",
        icon="mdi:car-door",
        value_cast=lambda values: next(
            (
                value["isOpen"]
                for value in values or []
                if value["row"] == VEHICLE_FRONT_ROW
                and value["column"] == VEHICLE_RIGHT_COLUMN
            ),
            None,
        ),
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.ENGINE_COVER,
        name="Engine Cover",
        value_key_path="closure-enginecover.isOpen",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.REAR_TRUNK,
        name="Rear Trunk",
        value_key_path="closure-reartrunk.isOpen",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.REAR_TRUNK_LOCK,
        name="Rear Trunk Lock",
        value_key_path="closure-reartrunk.isLocked",
        value_cast=operator.not_,
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.WINDOW_BACK_LEFT,
        name="Window Back Left",
        value_key_path="closure-windows.values",
        value_cast=lambda values: next(
            (
                value["isOpen"]
                for value in values or []
                if value["row"] == VEHICLE_BACK_ROW
                and value["column"] == VEHICLE_LEFT_COLUMN
            ),
            None,
        ),
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.WINDOW_BACK_RIGHT,
        name="Window Back Right",
        value_key_path="closure-windows.values",
        value_cast=lambda values: next(
            (
                value["isOpen"]
                for value in values or []
                if value["row"] == VEHICLE_BACK_ROW
                and value["column"] == VEHICLE_RIGHT_COLUMN
            ),
            None,
        ),
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.WINDOW_FRONT_LEFT,
        name="Window Front Left",
        value_key_path="closure-windows.values",
        value_cast=lambda values: next(
            (
                value["isOpen"]
                for value in values or []
                if value["row"] == VEHICLE_FRONT_ROW
                and value["column"] == VEHICLE_LEFT_COLUMN
            ),
            None,
        ),
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.WINDOW_FRONT_RIGHT,
        name="Window Front Right",
        value_key_path="closure-windows.values",
        value_cast=lambda values: next(
            (
                value["isOpen"]
                for value in values or []
                if value["row"] == VEHICLE_FRONT_ROW
                and value["column"] == VEHICLE_RIGHT_COLUMN
            ),
            None,
        ),
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.ONLINE,
        name="Online",
        value_key_path="connectivitystatus-isonline",
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.ASLEEP,
        name="Asleep",
        value_key_path="connectivitystatus-isasleep",
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.DIGITAL_KEY_PAIRED,
        name="Digital Key Paired",
        value_key_path="connectivitystatus-isdigitalkeypaired",
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.SURVEILLANCE_ENABLED,
        name="Surveillance Enabled",
        value_key_path="surveillance-isenabled",
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.CHARGE_FAST_CHARGER_PRESENT,
        name="Fast Charger Connected",
        value_key_path="charge-isfastchargerpresent.value",
        device_class=BinarySensorDeviceClass.PLUG,
    ),
    # --- Climate status (read_climate) ---
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.IS_CABIN_HVAC_ACTIVE,
        name="Cabin HVAC Active",
        value_key_path="hvac-iscabinhvacactive",
        value_cast=_hvac_bool,
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:air-conditioner",
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.IS_FRONT_DEFROSTER_ACTIVE,
        name="Front Defroster Active",
        value_key_path="hvac-isfrontdefrosteractive",
        value_cast=_hvac_bool,
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:car-defrost-front",
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.IS_REAR_DEFROSTER_ACTIVE,
        name="Rear Defroster Active",
        value_key_path="hvac-isreardefrosteractive",
        value_cast=_hvac_bool,
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:car-defrost-rear",
    ),
    SmartcarBinarySensorDescription(
        key=EntityDescriptionKey.IS_STEERING_HEATER_ACTIVE,
        name="Steering Wheel Heater Active",
        value_key_path="hvac-issteeringheateractive",
        value_cast=_hvac_bool,
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:steering",
    ),
)


async def async_setup_entry(  # noqa: RUF029
    hass: HomeAssistant,  # noqa: ARG001
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, SmartcarVehicleCoordinator] = (
        entry.runtime_data.coordinators
    )
    entities = [
        SmartcarBinarySensor(coordinator, description)
        for coordinator in coordinators.values()
        for description in SENSOR_TYPES
        if coordinator.is_scope_enabled(description.key, verbose=True)
    ]
    _LOGGER.info("Adding %s Smartcar binary sensor entities", len(entities))
    async_add_entities(entities)


class SmartcarBinarySensor(SmartcarEntity[bool, bool], BinarySensorEntity):
    """Binary sensor entity for plugged in status."""

    _attr_has_entity_name = True

    @property
    def is_on(self) -> bool:
        return self._extract_value()
