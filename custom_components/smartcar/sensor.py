from dataclasses import dataclass
import datetime as dt
from datetime import date, datetime
from decimal import Decimal
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfPower,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util.unit_conversion import DistanceConverter, PressureConverter

from .const import DOMAIN, EntityDescriptionKey
from .coordinator import (
    VEHICLE_BACK_ROW,
    VEHICLE_FRONT_ROW,
    VEHICLE_LEFT_COLUMN,
    VEHICLE_RIGHT_COLUMN,
    SmartcarVehicleCoordinator,
)
from .entity import (
    SmartcarEntity,
    SmartcarEntityDescription,
    SmartcarMetaEntityDescription,
)

_LOGGER = logging.getLogger(__name__)


def _diag_status(body: object) -> object:
    """Extract a diagnostic system status string from a webhook signal body.

    Field name is inferred from Smartcar conventions; falls back across the
    likely keys so it keeps working once real data flows for this vehicle.

    Returns:
        The extracted status or the body unchanged.
    """
    if not isinstance(body, dict):
        return body
    return body.get("status") or body.get("value")


def _dtc_count(body: object) -> object:
    if not isinstance(body, dict):
        return body
    value = body.get("value")
    return body.get("count") if value is None else value


def _dtc_list(body: object) -> object:
    if not isinstance(body, dict):
        return body
    items = body.get("value") or body.get("values") or body.get("codes") or []
    if not isinstance(items, list):
        return str(items)
    codes = [str(i.get("code", i)) if isinstance(i, dict) else str(i) for i in items]
    return ", ".join(codes) if codes else "none"


def _hvac_number(body: object) -> object:
    if not isinstance(body, dict):
        return body
    return body.get("value")


@dataclass(frozen=True, kw_only=True)
class SmartcarSensorDescription(SensorEntityDescription, SmartcarEntityDescription):
    """Class describing Smartcar sensor entities."""


@dataclass(frozen=True, kw_only=True)
class SmartcarMetaSensorDescription(
    SensorEntityDescription, SmartcarMetaEntityDescription
):
    """Class describing Smartcar meta sensor entities."""


SENSOR_TYPES: tuple[SmartcarSensorDescription, ...] = (
    SmartcarSensorDescription(
        key=EntityDescriptionKey.BATTERY_CAPACITY,
        name="Battery Capacity",
        value_key_path="tractionbattery-nominalcapacity.capacity",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.BATTERY_LEVEL,
        name="Battery",
        value_key_path="tractionbattery-stateofcharge.value",
        value_cast=lambda pct: pct and round(pct * 100),
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.LOW_VOLTAGE_BATTERY_LEVEL,
        name="Low Voltage Battery",
        value_key_path="lowvoltagebattery-stateofcharge.value",
        value_cast=lambda pct: pct and round(pct * 100),
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.CHARGING_STATE,
        name="Charging Status",
        value_key_path="charge-detailedchargingstatus.value",
        icon="mdi:ev-station",
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.CHARGE_CHARGERATE,
        name="Charge Rate",
        value_key_path="charge-chargerate.value",
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        icon="mdi:speedometer",
        imperial_conversion=lambda v: DistanceConverter.convert(
            v, UnitOfSpeed.MILES_PER_HOUR, UnitOfSpeed.KILOMETERS_PER_HOUR
        ),
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.CHARGE_ENERGYADDED,
        name="Energy Added",
        value_key_path="charge-energyadded.value",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:lightning-bolt",
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.CHARGE_TIMETOCOMPLETE,
        name="Time to Complete",
        value_key_path="charge-timetocomplete.value",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:timer",
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.ENGINE_OIL,
        name="Engine Oil Life",
        value_key_path="internalcombustionengine-oillife.value",
        icon="mdi:oil-level",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.FUEL,
        name="Fuel",
        value_key_path="internalcombustionengine-amountremaining.value",
        icon="mdi:gas-station",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        imperial_conversion=lambda v: DistanceConverter.convert(
            v, UnitOfVolume.GALLONS, UnitOfVolume.LITERS
        ),
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.FUEL_PERCENT,
        name="Fuel Percent",
        value_key_path="internalcombustionengine-fuellevel.value",
        value_cast=lambda pct: pct and round(pct * 100),
        icon="mdi:gas-station",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.FUEL_RANGE,
        name="Fuel Range",
        value_key_path="internalcombustionengine-range.value",
        icon="mdi:map-marker-distance",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        imperial_conversion=lambda v: DistanceConverter.convert(
            v, UnitOfLength.MILES, UnitOfLength.KILOMETERS
        ),
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.ODOMETER,
        name="Odometer",
        value_key_path="odometer-traveleddistance.value",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        imperial_conversion=lambda v: DistanceConverter.convert(
            v, UnitOfLength.MILES, UnitOfLength.KILOMETERS
        ),
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.RANGE,
        name="Range",
        value_key_path="tractionbattery-range.value",
        icon="mdi:map-marker-distance",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        imperial_conversion=lambda v: DistanceConverter.convert(
            v, UnitOfLength.MILES, UnitOfLength.KILOMETERS
        ),
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.GEAR_STATE,
        name="Gear State",
        value_key_path="transmission-gearstate.value",
        icon="mdi:car-brake-parking",
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.TIRE_PRESSURE_BACK_LEFT,
        name="Tire Pressure Back Left",
        value_key_path="wheel-tires.values",
        value_cast=lambda values: next(
            (
                value["tirePressure"]
                for value in values or []
                if value["row"] == VEHICLE_BACK_ROW
                and value["column"] == VEHICLE_LEFT_COLUMN
            ),
            None,
        ),
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        native_unit_of_measurement=UnitOfPressure.KPA,
        imperial_conversion=lambda v: PressureConverter.convert(
            v, UnitOfPressure.PSI, UnitOfPressure.KPA
        ),
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.TIRE_PRESSURE_BACK_RIGHT,
        name="Tire Pressure Back Right",
        value_key_path="wheel-tires.values",
        value_cast=lambda values: next(
            (
                value["tirePressure"]
                for value in values or []
                if value["row"] == VEHICLE_BACK_ROW
                and value["column"] == VEHICLE_RIGHT_COLUMN
            ),
            None,
        ),
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        native_unit_of_measurement=UnitOfPressure.KPA,
        imperial_conversion=lambda v: PressureConverter.convert(
            v, UnitOfPressure.PSI, UnitOfPressure.KPA
        ),
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.TIRE_PRESSURE_FRONT_LEFT,
        name="Tire Pressure Front Left",
        value_key_path="wheel-tires.values",
        value_cast=lambda values: next(
            (
                value["tirePressure"]
                for value in values or []
                if value["row"] == VEHICLE_FRONT_ROW
                and value["column"] == VEHICLE_LEFT_COLUMN
            ),
            None,
        ),
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        native_unit_of_measurement=UnitOfPressure.KPA,
        imperial_conversion=lambda v: PressureConverter.convert(
            v, UnitOfPressure.PSI, UnitOfPressure.KPA
        ),
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.TIRE_PRESSURE_FRONT_RIGHT,
        name="Tire Pressure Front Right",
        value_key_path="wheel-tires.values",
        value_cast=lambda values: next(
            (
                value["tirePressure"]
                for value in values or []
                if value["row"] == VEHICLE_FRONT_ROW
                and value["column"] == VEHICLE_RIGHT_COLUMN
            ),
            None,
        ),
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        native_unit_of_measurement=UnitOfPressure.KPA,
        imperial_conversion=lambda v: PressureConverter.convert(
            v, UnitOfPressure.PSI, UnitOfPressure.KPA
        ),
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.CHARGE_VOLTAGE,
        name="Charging Voltage",
        value_key_path="charge-voltage.value",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.CHARGE_AMPERAGE,
        name="Charging Current",
        value_key_path="charge-amperage.value",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.CHARGE_WATTAGE,
        name="Charging Power",
        value_key_path="charge-wattage.value",
        value_cast=lambda w: w and round(w / 1000, 2),
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.CHARGE_TIME_TO_COMPLETE,
        name="Charging Time Remaining",
        value_key_path="charge-timetocomplete.value",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.CHARGE_AMPERAGE_MAX,
        name="Charging Current Max",
        value_key_path="charge-amperagemax.value",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.FIRMWARE_VERSION,
        name="Firmware Version",
        value_key_path="connectivitysoftware-currentfirmwareversion.value",
        icon="mdi:chip",
    ),
    # --- Diagnostics (read_diagnostics) ---
    SmartcarSensorDescription(
        key=EntityDescriptionKey.DIAG_ABS,
        name="ABS Status",
        value_key_path="diagnostics-abs",
        value_cast=_diag_status,
        icon="mdi:car-brake-abs",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.DIAG_MIL,
        name="Malfunction Indicator Lamp",
        value_key_path="diagnostics-mil",
        value_cast=_diag_status,
        icon="mdi:engine",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.DIAG_DTC_COUNT,
        name="Trouble Code Count",
        value_key_path="diagnostics-dtccount",
        value_cast=_dtc_count,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:alert-circle",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.DIAG_DTC_LIST,
        name="Trouble Codes",
        value_key_path="diagnostics-dtclist",
        value_cast=_dtc_list,
        icon="mdi:format-list-bulleted",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.DIAG_EV_BATTERY_CONDITIONING,
        name="EV Battery Conditioning Status",
        value_key_path="diagnostics-evbatteryconditioning",
        value_cast=_diag_status,
        icon="mdi:battery-heart-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.DIAG_EV_CHARGING,
        name="EV Charging Status",
        value_key_path="diagnostics-evcharging",
        value_cast=_diag_status,
        icon="mdi:ev-station",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.DIAG_EV_DRIVE_UNIT,
        name="EV Drive Unit Status",
        value_key_path="diagnostics-evdriveunit",
        value_cast=_diag_status,
        icon="mdi:cog",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SmartcarSensorDescription(
        key=EntityDescriptionKey.DIAG_EV_HV_BATTERY,
        name="EV High Voltage Battery Status",
        value_key_path="diagnostics-evhvbattery",
        value_cast=_diag_status,
        icon="mdi:car-battery",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # --- Climate status (read_climate) ---
    SmartcarSensorDescription(
        key=EntityDescriptionKey.CABIN_TARGET_TEMPERATURE,
        name="Cabin Target Temperature",
        value_key_path="hvac-cabintargettemperature",
        value_cast=_hvac_number,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:thermostat",
    ),
)

META_SENSOR_TYPES: tuple[SmartcarMetaSensorDescription, ...] = (
    SmartcarMetaSensorDescription(
        key=EntityDescriptionKey.LAST_WEBHOOK_RECEIVED,
        name="Last Webhook Received",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("last_webhook_received_at"),
        attr_fn=lambda data: (
            {
                f"response_{key}": value
                for key, value in data.get("last_webhook_response", {}).items()
            }
        ),
        icon="mdi:clock",
    ),
)


async def async_setup_entry(  # noqa: RUF029
    hass: HomeAssistant,  # noqa: ARG001
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from coordinator."""
    coordinators: dict[str, SmartcarVehicleCoordinator] = (
        entry.runtime_data.coordinators
    )
    meta_coordinator = entry.runtime_data.meta_coordinator
    _LOGGER.debug("Setting up sensors for vehicles: %s", list(coordinators.keys()))
    entities = [
        SmartcarSensor(coordinator, description)
        for coordinator in coordinators.values()
        for description in SENSOR_TYPES
        if coordinator.is_scope_enabled(description.key, verbose=True)
    ] + [
        SmartcarMetaSensor(
            meta_coordinator,
            description,
            {"identifiers": {(DOMAIN, device_id)}},
        )
        for vehicle_coordinator in coordinators.values()
        for description in META_SENSOR_TYPES
        if (
            vehicle_coordinator.version == "v3"
            and (device_id := vehicle_coordinator.vehicle_id)
        )
        or (
            vehicle_coordinator.version == "v2"
            and (
                device_id := (vehicle_coordinator.vin or vehicle_coordinator.vehicle_id)
            )
        )
    ]
    _LOGGER.info("Adding %s Smartcar sensor entities", len(entities))
    async_add_entities(entities)


class SmartcarSensor[ValueT, RawValueT](
    SmartcarEntity[ValueT, RawValueT], SensorEntity
):
    """Sensor entity."""

    _attr_has_entity_name = True

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        return self._extract_value()


class SmartcarMetaSensor(CoordinatorEntity[DataUpdateCoordinator], SensorEntity):
    """Meta sensor entity."""

    _attr_has_entity_name = True
    entity_description: SmartcarMetaEntityDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        description: SmartcarMetaEntityDescription,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)

        (_, device_id) = next(iter(device_info["identifiers"]))

        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> str | int | float | dt.datetime | None:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return self.entity_description.attr_fn(self.coordinator.data)
