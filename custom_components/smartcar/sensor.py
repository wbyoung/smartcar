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
    _LOGGER.debug("Setting up sensors for VINs: %s", list(coordinators.keys()))
    entities = (
        [
            SmartcarSensor(coordinator, description)
            for coordinator in coordinators.values()
            for description in SENSOR_TYPES
            if coordinator.is_scope_enabled(description.key, verbose=True)
        ]
        + [
            SmartcarMetaSensor(
                meta_coordinator,
                description,
                {"identifiers": {(DOMAIN, vehicle_coordinator.vin)}},
            )
            for vehicle_coordinator in coordinators.values()
            for description in META_SENSOR_TYPES
        ]
        + [
            SmartcarLastPolledSensor(coordinator)
            for coordinator in coordinators.values()
        ]
    )
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

        (_, vin) = next(iter(device_info["identifiers"]))

        self.entity_description = description
        self._attr_unique_id = f"{vin}_{description.key}"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> str | int | float | dt.datetime | None:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return self.entity_description.attr_fn(self.coordinator.data)


class SmartcarLastPolledSensor(
    CoordinatorEntity[SmartcarVehicleCoordinator], SensorEntity
):
    """Per-vehicle sensor showing the time of the last successful HTTP poll.

    Backed by ``SmartcarVehicleCoordinator.last_poll_time`` rather than
    ``coordinator.data``, so it only ticks on actual ``/v3/.../signals``
    pulls — webhook deliveries don't update this. That's the whole point:
    it tells the user whether the polling pipeline is healthy
    independently of the webhook pipeline. The state is ``unknown`` until
    the first successful poll, which is informative in webhooks-only
    mode (confirms no polls are happening).
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_polled"
    _attr_name = "Last Polled"
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coordinator: SmartcarVehicleCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_{EntityDescriptionKey.LAST_POLLED}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.vin)},
        )

    @property
    def native_value(self) -> dt.datetime | None:
        """Return the time of the last successful poll."""
        return self.coordinator.last_poll_time

    @property
    def available(self) -> bool:
        """Always available — ``None`` is a meaningful state ("never polled")."""
        return True
