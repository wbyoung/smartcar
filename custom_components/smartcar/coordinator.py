from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
import datetime as dt
from datetime import timedelta
from http import HTTPStatus
import logging
import numbers
from typing import Any

from aiohttp import ClientResponseError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .auth import AbstractAuth
from .const import DOMAIN, EntityDescriptionKey
from .util import key_path_get, key_path_update

_LOGGER = logging.getLogger(__name__)

VEHICLE_FRONT_ROW = 0
VEHICLE_BACK_ROW = 1
VEHICLE_LEFT_COLUMN = 0
VEHICLE_RIGHT_COLUMN = 1

UPDATE_INTERVAL = timedelta(hours=6)


@dataclass
class DatapointConfig:
    """Datapoint config class."""

    code: str | None  # none indicates no v3 equivalent
    required_scopes: list[str]
    endpoint_v2: str | None  # the read (and batch) endpoint
    value_key_path_v2: str | None
    value_transform_v2: Callable[[Any], Any] = lambda x: {"value": x}
    value_merge_v2: Callable[[dict, dict], dict] = (
        lambda current, update: current | update
    )
    is_v2_value: Callable[[Any], bool] = (  # for saved restore-state values
        lambda _x: False
    )

    @property
    def storage_key(self) -> str:
        assert self.code
        return self.code

    @property
    def storage_key_v2(self) -> str:
        endpoint_v2 = self.endpoint_v2
        assert endpoint_v2 is not None
        return endpoint_v2.strip("/").replace("/", "_")


def _tire_pressure_merge_v2(current: dict, update: dict) -> dict:
    values = []
    seen = set()

    for value in (*update.get("values", []), *current.get("values", [])):
        key = (value["row"], value["column"])
        if key not in seen:
            values.append(value)
            seen.add(key)

    return update | {"values": values}


def _is_v2_value_if_numeric(
    value: Any,  # noqa: ANN401
) -> bool:
    return isinstance(value, numbers.Number)


def _is_v2_value_if_string(
    value: Any,  # noqa: ANN401
) -> bool:
    return isinstance(value, str)


DATAPOINT_ENTITY_KEY_MAP = {
    EntityDescriptionKey.BATTERY_CAPACITY: DatapointConfig(
        "tractionbattery-nominalcapacity",
        ["read_battery"],
        "/battery/nominal_capacity",
        "capacity.nominal",
        lambda nominal: {"capacity": nominal, "availableCapacities": []},
    ),
    EntityDescriptionKey.BATTERY_LEVEL: DatapointConfig(
        "tractionbattery-stateofcharge",
        ["read_battery"],
        "/battery",
        "percentRemaining",
    ),
    EntityDescriptionKey.CHARGE_CHARGERATE: DatapointConfig(
        "charge-chargerate",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.CHARGE_ENERGYADDED: DatapointConfig(
        "charge-energyadded",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.CHARGE_TIMETOCOMPLETE: DatapointConfig(
        "charge-timetocomplete",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.BATTERY_HEATER_ACTIVE: DatapointConfig(
        "tractionbattery-isheateractive",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.CHARGE_LIMIT: DatapointConfig(
        "charge-chargelimits",
        ["read_charge", "control_charge"],
        "/charge/limit",
        "limit",
        lambda limit: {
            "values": [{"type": "global", "limit": limit, "condition": None}]
        },
        is_v2_value=_is_v2_value_if_numeric,  # for saved restore-state values
    ),
    EntityDescriptionKey.CHARGING: DatapointConfig(  # for the switch
        "charge-ischarging",
        ["read_charge", "control_charge"],
        "/charge",
        "state",
        lambda state: {"value": state == "CHARGING" if state is not None else None},
        is_v2_value=_is_v2_value_if_string,  # for saved restore-state values
    ),
    EntityDescriptionKey.CHARGING_STATE: DatapointConfig(
        "charge-detailedchargingstatus",
        ["read_charge", "control_charge"],
        "/charge",
        "state",
    ),
    EntityDescriptionKey.DOOR_LOCK: DatapointConfig(
        "closure-islocked",
        ["read_security", "control_security"],
        "/security",
        "isLocked",
    ),
    EntityDescriptionKey.DOOR_BACK_LEFT_LOCK: DatapointConfig(
        "closure-doors",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.DOOR_BACK_RIGHT_LOCK: DatapointConfig(
        "closure-doors",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.DOOR_FRONT_LEFT_LOCK: DatapointConfig(
        "closure-doors",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.DOOR_FRONT_RIGHT_LOCK: DatapointConfig(
        "closure-doors",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.DOOR_BACK_LEFT: DatapointConfig(
        "closure-doors",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.DOOR_BACK_RIGHT: DatapointConfig(
        "closure-doors",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.DOOR_FRONT_LEFT: DatapointConfig(
        "closure-doors",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.DOOR_FRONT_RIGHT: DatapointConfig(
        "closure-doors",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.ENGINE_OIL: DatapointConfig(
        "internalcombustionengine-oillife",
        ["read_engine_oil"],
        "/engine/oil",
        "lifeRemaining",
    ),
    EntityDescriptionKey.ENGINE_COVER: DatapointConfig(
        "closure-enginecover",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.FUEL: DatapointConfig(
        "internalcombustionengine-amountremaining",
        ["read_fuel"],
        "/fuel",
        "amountRemaining",
    ),
    EntityDescriptionKey.FUEL_PERCENT: DatapointConfig(
        "internalcombustionengine-fuellevel",
        ["read_fuel"],
        "/fuel",
        "percentRemaining",
    ),
    EntityDescriptionKey.FUEL_RANGE: DatapointConfig(
        "internalcombustionengine-range",
        ["read_fuel"],
        "/fuel",
        "range",
    ),
    EntityDescriptionKey.FRONT_TRUNK: DatapointConfig(
        "closure-fronttrunk",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.FRONT_TRUNK_LOCK: DatapointConfig(
        "closure-fronttrunk",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.SUNROOF: DatapointConfig(
        "closure-sunroof",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.LOCATION: DatapointConfig(
        "location-preciselocation",
        ["read_location"],
        "/location",
        None,
        lambda location: location,
    ),
    EntityDescriptionKey.LOW_VOLTAGE_BATTERY_LEVEL: DatapointConfig(
        "lowvoltagebattery-stateofcharge",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.ODOMETER: DatapointConfig(
        "odometer-traveleddistance", ["read_odometer"], "/odometer", "distance"
    ),
    EntityDescriptionKey.PLUG_STATUS: DatapointConfig(
        "charge-ischargingcableconnected",
        ["read_charge"],
        "/charge",
        "isPluggedIn",
    ),
    EntityDescriptionKey.RANGE: DatapointConfig(
        "tractionbattery-range",
        ["read_battery"],
        "/battery",
        "range",
    ),
    EntityDescriptionKey.GEAR_STATE: DatapointConfig(
        "transmission-gearstate",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.TIRE_PRESSURE_BACK_LEFT: DatapointConfig(
        "wheel-tires",
        ["read_tires"],
        "/tires/pressure",
        "backLeft",
        lambda pressure: {
            "values": [
                {
                    "tirePressure": pressure,
                    "column": VEHICLE_LEFT_COLUMN,
                    "row": VEHICLE_BACK_ROW,
                }
            ],
            "rowCount": 2,
            "columnCount": 2,
        },
        _tire_pressure_merge_v2,
        _is_v2_value_if_numeric,  # for saved restore-state values
    ),
    EntityDescriptionKey.TIRE_PRESSURE_BACK_RIGHT: DatapointConfig(
        "wheel-tires",
        ["read_tires"],
        "/tires/pressure",
        "backRight",
        lambda pressure: {
            "values": [
                {
                    "tirePressure": pressure,
                    "column": VEHICLE_RIGHT_COLUMN,
                    "row": VEHICLE_BACK_ROW,
                }
            ],
            "rowCount": 2,
            "columnCount": 2,
        },
        _tire_pressure_merge_v2,
        _is_v2_value_if_numeric,  # for saved restore-state values
    ),
    EntityDescriptionKey.TIRE_PRESSURE_FRONT_LEFT: DatapointConfig(
        "wheel-tires",
        ["read_tires"],
        "/tires/pressure",
        "frontLeft",
        lambda pressure: {
            "values": [
                {
                    "tirePressure": pressure,
                    "column": VEHICLE_LEFT_COLUMN,
                    "row": VEHICLE_FRONT_ROW,
                }
            ],
            "rowCount": 2,
            "columnCount": 2,
        },
        _tire_pressure_merge_v2,
        _is_v2_value_if_numeric,  # for saved restore-state values
    ),
    EntityDescriptionKey.TIRE_PRESSURE_FRONT_RIGHT: DatapointConfig(
        "wheel-tires",
        ["read_tires"],
        "/tires/pressure",
        "frontRight",
        lambda pressure: {
            "values": [
                {
                    "tirePressure": pressure,
                    "column": VEHICLE_RIGHT_COLUMN,
                    "row": VEHICLE_FRONT_ROW,
                }
            ],
            "rowCount": 2,
            "columnCount": 2,
        },
        _tire_pressure_merge_v2,
        _is_v2_value_if_numeric,  # for saved restore-state values
    ),
    EntityDescriptionKey.WINDOW_BACK_LEFT: DatapointConfig(
        "closure-windows",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.WINDOW_BACK_RIGHT: DatapointConfig(
        "closure-windows",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.WINDOW_FRONT_LEFT: DatapointConfig(
        "closure-windows",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.WINDOW_FRONT_RIGHT: DatapointConfig(
        "closure-windows",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.REAR_TRUNK: DatapointConfig(
        "closure-reartrunk",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.REAR_TRUNK_LOCK: DatapointConfig(
        "closure-reartrunk",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.ONLINE: DatapointConfig(
        "connectivitystatus-isonline",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.ASLEEP: DatapointConfig(
        "connectivitystatus-isasleep",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.DIGITAL_KEY_PAIRED: DatapointConfig(
        "connectivitystatus-isdigitalkeypaired",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.SURVEILLANCE_ENABLED: DatapointConfig(
        "surveillance-isenabled",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.CHARGE_VOLTAGE: DatapointConfig(
        "charge-voltage",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.CHARGE_AMPERAGE: DatapointConfig(
        "charge-amperage",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.CHARGE_WATTAGE: DatapointConfig(
        "charge-wattage",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.CHARGE_TIME_TO_COMPLETE: DatapointConfig(
        "charge-timetocomplete",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.CHARGE_AMPERAGE_MAX: DatapointConfig(
        "charge-amperagemax",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.CHARGE_FAST_CHARGER_PRESENT: DatapointConfig(
        "charge-isfastchargerpresent",
        [],
        None,
        None,
    ),
    EntityDescriptionKey.FIRMWARE_VERSION: DatapointConfig(
        "connectivitysoftware-currentfirmwareversion",
        [],
        None,
        None,
    ),
}

DATAPOINT_STORAGE_KEY_V2_MAP = {
    storage_key_v2: tuple(
        datapoint
        for datapoint in DATAPOINT_ENTITY_KEY_MAP.values()
        if datapoint.endpoint_v2 is not None
        and datapoint.storage_key_v2 == storage_key_v2
    )
    for storage_key_v2 in {
        datapoint.storage_key_v2
        for datapoint in DATAPOINT_ENTITY_KEY_MAP.values()
        if datapoint.endpoint_v2 is not None
    }
}

DATAPOINT_CODE_MAP = {
    code: tuple(
        datapoint
        for datapoint in DATAPOINT_ENTITY_KEY_MAP.values()
        if datapoint.code == code
    )
    for code in {datapoint.code for datapoint in DATAPOINT_ENTITY_KEY_MAP.values()}
}


class SmartcarVehicleCoordinator(DataUpdateCoordinator):
    """Coordinates updates with selective batch paths and dynamic interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        auth: AbstractAuth,
        vehicle_id: str,
        vin: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize coordinator."""
        self.auth = auth
        self.vehicle_id = vehicle_id
        self.vin = vin
        self.entry = entry
        self.batch_requests: set[EntityDescriptionKey] = set()
        self.data: dict[str, Any] = {}

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{vin}",
            update_interval=UPDATE_INTERVAL,
        )

    def is_scope_enabled(
        self, sensor_key: EntityDescriptionKey, *, verbose: bool = False
    ) -> bool:
        token_scopes = self.config_entry.data.get("token", {}).get("scopes", [])
        required_scopes = DATAPOINT_ENTITY_KEY_MAP[sensor_key].required_scopes
        missing = [scope for scope in required_scopes if scope not in token_scopes]
        enabled = len(missing) == 0

        if not enabled and verbose:
            _LOGGER.warning(
                "Skipping `%s` which requires %r, but "
                "user is missing %r with enabled scopes of %r.",
                sensor_key,
                required_scopes,
                missing,
                token_scopes,
            )

        return enabled

    def batch_sensor(self, sensor: CoordinatorEntity) -> None:
        """Mark a sensor to be included in the next update batch."""
        self._batch_add(sensor.entity_description.key)

    def _batch_add(self, key: EntityDescriptionKey) -> None:
        """Mark data as needing to be fetched in the next update batch."""

        assert self.is_scope_enabled(key)

        self.batch_requests.add(key)

    def _batch_add_defaults(self) -> None:
        """Add default batch paths to request when none were explicitly requested.

        Explicit requests are considered to have been made when:

        - There are already requests that have been made (via the
          `home_assistant.update_entity` action). This method will
          short-circuit and not add additional items to the batch.
        - When polling is disabled, no defaults are added to the batch. This
          prevents requests being made across all endpoints that apply to
          (enabled) entities when Home Assistant starts or the config entry is
          reloaded.

        When polling is enabled and there have been no explicit update
        requests, requests will be added to the batch for all entities that are
        active (not marked as disabled) in the entity registry. (Note: this
        means that during config entry setup, platform initialization needs to
        occur before the first refresh or the entity registry will be empty.)
        """
        if self.batch_requests:
            return
        if self.config_entry.pref_disable_polling:
            return

        entities: list[er.RegistryEntry] = er.async_entries_for_config_entry(
            er.async_get(self.hass), self.config_entry.entry_id
        )

        for entity in entities:
            _, key = entity.unique_id.split("_", 1)
            if key not in DATAPOINT_ENTITY_KEY_MAP:
                continue
            config = DATAPOINT_ENTITY_KEY_MAP[key]

            # currently polling is only supported via the v2 api
            if config.endpoint_v2 and not entity.disabled:
                self._batch_add(key)

    def _batch_process(self) -> list[EntityDescriptionKey]:
        """Process a batch of paths to request.

        Returns:
            The list of entity description keys that need to be processed.
        """
        self._batch_add_defaults()

        result: list[EntityDescriptionKey] = list(self.batch_requests)

        self.batch_requests.clear()

        return result

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API using selective batch endpoint.

        Returns:
            The updated data.

        Raises:
            ConfigEntryAuthFailed: If an authentication failure occurs.
            ClientResponseError: If the update fails for any reason.
            UpdateFailed: If the update fails to provide the proper response.
        """

        batch_requests = self._batch_process()

        assert not any(
            DATAPOINT_ENTITY_KEY_MAP[key].endpoint_v2 is None for key in batch_requests
        )

        request_path = f"vehicles/{self.vehicle_id}/batch"
        request_batch_paths = sorted(
            {
                v2_endpoint
                for key in batch_requests
                if (v2_endpoint := DATAPOINT_ENTITY_KEY_MAP[key].endpoint_v2)
                is not None
            }
        )
        request_body = {"requests": [{"path": path} for path in request_batch_paths]}

        if not batch_requests:
            _LOGGER.warning(
                "Coordinator %s: No updates to request based on granted scopes and context.",
                self.name,
            )
            return self.data

        _LOGGER.debug(
            "Coordinator %s: Requesting batch update (Interval: %s) for paths: %s",
            self.name,
            self.update_interval,
            request_batch_paths,
        )

        try:
            response = await self.auth.request("post", request_path, json=request_body)

        # response errors here for responses that have actually completed, i.e.
        # 4xx responses are for errors related to requests made in the
        # underlying oauth handler. for instance, the implementation will raise
        # for invalid an invalid status while negotiating a new token if there's
        # an issue. unfortunately, it consumes the JSON response to log about
        # the error, so we can only match on the status code.
        except ClientResponseError as exception:
            if exception.status in {
                HTTPStatus.BAD_REQUEST,
                HTTPStatus.UNAUTHORIZED,
                HTTPStatus.FORBIDDEN,
            }:
                raise ConfigEntryAuthFailed from exception
            raise

        response.raise_for_status()
        response_data = await response.json()

        if "responses" not in response_data:
            msg = "Invalid batch response format"
            raise UpdateFailed(msg)

        return self._merge_batch_data(response_data)

    def _merge_batch_data(self, batch_data: dict[str, Any]) -> dict[str, Any]:
        """Merge data from the responses from a batch request.

        Returns:
            The newly merged data.
        """

        with self.create_updated_data() as (add, updated_data):
            for item in batch_data["responses"]:
                path = item["path"]
                code = item["code"]
                body = item["body"]
                headers = item.get("headers") or {}
                unit_system = headers.get("sc-unit-system")
                data_age = headers.get("sc-data-age")
                fetched_at = headers.get("sc-fetched-at")
                key = path.strip("/").replace("/", "_")

                if code != 200:
                    body = None
                    unit_system = None
                    data_age = None
                    fetched_at = None

                if data_age:
                    data_age = dt_util.parse_datetime(data_age)
                if fetched_at:
                    fetched_at = dt_util.parse_datetime(fetched_at)

                add.from_response_body_v2(
                    key,
                    body=body,
                    unit_system=unit_system,
                    data_age=data_age,
                    fetched_at=fetched_at,
                )

                if code not in {200, 404}:
                    _LOGGER.warning(
                        "Coordinator %s: Status %s for path %s",
                        self.name,
                        code,
                        path,
                    )

            _LOGGER.debug("Coordinator %s: Batch update processed", self.name)

            return updated_data

    @contextmanager
    def create_updated_data(
        self,
    ) -> Generator[tuple[_DataAdder, dict[str, Any]]]:
        updated_data = dict(self.data or {})

        yield _DataAdder(updated_data), updated_data


class _DataAdder:
    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__()
        self.data = data

    def from_response_body(
        self,
        code: str,
        *,
        body: dict[str, Any] | None,
        data_age: dt.datetime | None = None,
        fetched_at: dt.datetime | None = None,
        unit_system: str | None = None,
        can_clear_meta: bool = True,
    ) -> None:
        for datapoint in DATAPOINT_CODE_MAP[code]:
            assert code == datapoint.code

            self.data[datapoint.storage_key] = (
                ((self.data.get(datapoint.storage_key) or {}) | body)
                if body is not None
                else None
            )

        self._update_meta(
            DATAPOINT_CODE_MAP[code],
            data_age=data_age,
            fetched_at=fetched_at,
            unit_system=unit_system,
            can_clear=can_clear_meta,
        )

    def from_response_body_v2(
        self,
        storage_key_v2: str,
        *,
        body: dict[str, Any] | None,
        data_age: dt.datetime | None = None,
        fetched_at: dt.datetime | None = None,
        unit_system: str | None = None,
        can_clear_meta: bool = True,
    ) -> None:
        for datapoint in DATAPOINT_STORAGE_KEY_V2_MAP[storage_key_v2]:
            assert storage_key_v2 == datapoint.storage_key_v2

            value = (
                None
                if body is None
                else key_path_get(body, datapoint.value_key_path_v2)
                if datapoint.value_key_path_v2
                else body
            )

            self.data[datapoint.storage_key] = datapoint.value_merge_v2(
                self.data.get(datapoint.storage_key) or {},
                datapoint.value_transform_v2(value),
            )

        self._update_meta(
            DATAPOINT_STORAGE_KEY_V2_MAP[storage_key_v2],
            data_age=data_age,
            fetched_at=fetched_at,
            unit_system=unit_system,
            can_clear=can_clear_meta,
        )

    def from_storage_raw_value(
        self,
        entity_description_key: EntityDescriptionKey,
        value_key_path: str,
        *,
        value: Any,  # noqa: ANN401
        data_age: dt.datetime | None = None,
        fetched_at: dt.datetime | None = None,
        unit_system: str | None = None,
        can_clear_meta: bool = True,
    ) -> None:
        datapoint = DATAPOINT_ENTITY_KEY_MAP[entity_description_key]

        # when needed, transform stored v2 raw values by using the
        # `value_transform_v2`, but since this changes a value into
        # an object that looks like the v3 body, i.e. it is nested
        # inside a dict with a `value(s)` key, we need to strip off
        # the final key from the key path (and ensure it matches
        # something within the new value as a sanity check).
        if datapoint.is_v2_value(value):
            value = datapoint.value_transform_v2(value)
            storage_key, final_key = value_key_path.rsplit(".", 1)
            assert final_key in value
            _LOGGER.debug("merge %s into %s", value, self.data.get(storage_key))
            self.data[storage_key] = datapoint.value_merge_v2(
                self.data.get(storage_key) or {},
                value,
            )
        else:
            key_path_update(self.data, value_key_path, value)

        self._update_meta(
            (datapoint,),
            data_age=data_age,
            fetched_at=fetched_at,
            unit_system=unit_system,
            can_clear=can_clear_meta,
        )

    def _update_meta(
        self,
        datapoints: tuple[DatapointConfig, ...],
        *,
        data_age: dt.datetime | None,
        fetched_at: dt.datetime | None,
        unit_system: str | None,
        can_clear: bool,
    ) -> None:
        for datapoint in datapoints:
            storage_key = datapoint.storage_key

            if unit_system:
                self.data[f"{storage_key}:unit_system"] = unit_system
            elif can_clear:
                self.data.pop(f"{storage_key}:unit_system", None)

            if data_age:
                self.data[f"{storage_key}:data_age"] = data_age
            elif can_clear:
                self.data.pop(f"{storage_key}:data_age", None)

            if fetched_at:
                self.data[f"{storage_key}:fetched_at"] = fetched_at
            elif can_clear:
                self.data.pop(f"{storage_key}:fetched_at", None)
