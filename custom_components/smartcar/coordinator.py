"""Per-vehicle data coordinator backed by the Smartcar V3 Signals endpoint."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
import datetime as dt
from datetime import timedelta
from http import HTTPStatus
import logging
from typing import Any

from aiohttp import ClientConnectionError, ClientResponseError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .auth import AbstractAuth
from .const import (
    CONF_APPLICATION_MANAGEMENT_TOKEN,
    CONF_SCOPES,
    DOMAIN,
    EntityDescriptionKey,
)
from .util import async_request_with_retry, key_path_update

_LOGGER = logging.getLogger(__name__)

VEHICLE_FRONT_ROW = 0
VEHICLE_BACK_ROW = 1
VEHICLE_LEFT_COLUMN = 0
VEHICLE_RIGHT_COLUMN = 1

UPDATE_INTERVAL = timedelta(hours=6)

# Smartcar returns values in either imperial or metric depending on the
# vehicle/account. Signal bodies use these unit strings to flag imperial,
# matching what's already done in webhooks.py.
IMPERIAL_UNITS = frozenset({"miles", "psi", "gallons"})

# Some signals encode multi-value fields with a different "value" key. This
# mirrors the existing webhook handling so percent normalisation works the
# same way for both push and pull paths.
SIGNAL_BODY_MULTIVALUE_ITEM_KEY_MAP: dict[str | None, str] = {
    "charge-chargelimits": "limit",
}


@dataclass(frozen=True)
class DatapointConfig:
    """Mapping from an entity description key to a Smartcar V3 signal code."""

    code: str | None  # None = the signal is not yet exposed by this integration.
    required_scopes: list[str] = field(default_factory=list)

    @property
    def storage_key(self) -> str:
        """Return the key under which the signal body is stored in `data`."""
        assert self.code is not None
        return self.code


# Each entity description key maps to exactly one V3 signal code. Several
# entity keys may share the same signal (e.g. all four door entities read
# from the ``closure-doors`` signal body).
DATAPOINT_ENTITY_KEY_MAP: dict[EntityDescriptionKey, DatapointConfig] = {
    EntityDescriptionKey.BATTERY_CAPACITY: DatapointConfig(
        "tractionbattery-nominalcapacity", ["read_battery"]
    ),
    EntityDescriptionKey.BATTERY_LEVEL: DatapointConfig(
        "tractionbattery-stateofcharge", ["read_battery"]
    ),
    EntityDescriptionKey.BATTERY_HEATER_ACTIVE: DatapointConfig(
        "tractionbattery-isheateractive", ["read_battery"]
    ),
    EntityDescriptionKey.RANGE: DatapointConfig(
        "tractionbattery-range", ["read_battery"]
    ),
    EntityDescriptionKey.LOW_VOLTAGE_BATTERY_LEVEL: DatapointConfig(
        "lowvoltagebattery-stateofcharge", ["read_battery"]
    ),
    EntityDescriptionKey.CHARGING: DatapointConfig(
        "charge-ischarging", ["read_charge", "control_charge"]
    ),
    EntityDescriptionKey.CHARGING_STATE: DatapointConfig(
        "charge-detailedchargingstatus", ["read_charge"]
    ),
    EntityDescriptionKey.PLUG_STATUS: DatapointConfig(
        "charge-ischargingcableconnected", ["read_charge"]
    ),
    EntityDescriptionKey.CHARGE_LIMIT: DatapointConfig(
        "charge-chargelimits", ["read_charge", "control_charge"]
    ),
    EntityDescriptionKey.CHARGE_CHARGERATE: DatapointConfig(
        "charge-chargerate", ["read_charge"]
    ),
    EntityDescriptionKey.CHARGE_ENERGYADDED: DatapointConfig(
        "charge-energyadded", ["read_charge"]
    ),
    EntityDescriptionKey.CHARGE_TIMETOCOMPLETE: DatapointConfig(
        "charge-timetocomplete", ["read_charge"]
    ),
    EntityDescriptionKey.CHARGE_TIME_TO_COMPLETE: DatapointConfig(
        "charge-timetocomplete", ["read_charge"]
    ),
    EntityDescriptionKey.CHARGE_VOLTAGE: DatapointConfig(
        "charge-voltage", ["read_charge"]
    ),
    EntityDescriptionKey.CHARGE_AMPERAGE: DatapointConfig(
        "charge-amperage", ["read_charge"]
    ),
    EntityDescriptionKey.CHARGE_AMPERAGE_MAX: DatapointConfig(
        "charge-amperagemax", ["read_charge"]
    ),
    EntityDescriptionKey.CHARGE_WATTAGE: DatapointConfig(
        "charge-wattage", ["read_charge"]
    ),
    EntityDescriptionKey.CHARGE_FAST_CHARGER_PRESENT: DatapointConfig(
        "charge-isfastchargerpresent", ["read_charge"]
    ),
    EntityDescriptionKey.DOOR_LOCK: DatapointConfig(
        "closure-islocked", ["read_security", "control_security"]
    ),
    EntityDescriptionKey.DOOR_BACK_LEFT: DatapointConfig(
        "closure-doors", ["read_security"]
    ),
    EntityDescriptionKey.DOOR_BACK_RIGHT: DatapointConfig(
        "closure-doors", ["read_security"]
    ),
    EntityDescriptionKey.DOOR_FRONT_LEFT: DatapointConfig(
        "closure-doors", ["read_security"]
    ),
    EntityDescriptionKey.DOOR_FRONT_RIGHT: DatapointConfig(
        "closure-doors", ["read_security"]
    ),
    EntityDescriptionKey.DOOR_BACK_LEFT_LOCK: DatapointConfig(
        "closure-doors", ["read_security"]
    ),
    EntityDescriptionKey.DOOR_BACK_RIGHT_LOCK: DatapointConfig(
        "closure-doors", ["read_security"]
    ),
    EntityDescriptionKey.DOOR_FRONT_LEFT_LOCK: DatapointConfig(
        "closure-doors", ["read_security"]
    ),
    EntityDescriptionKey.DOOR_FRONT_RIGHT_LOCK: DatapointConfig(
        "closure-doors", ["read_security"]
    ),
    EntityDescriptionKey.WINDOW_BACK_LEFT: DatapointConfig(
        "closure-windows", ["read_security"]
    ),
    EntityDescriptionKey.WINDOW_BACK_RIGHT: DatapointConfig(
        "closure-windows", ["read_security"]
    ),
    EntityDescriptionKey.WINDOW_FRONT_LEFT: DatapointConfig(
        "closure-windows", ["read_security"]
    ),
    EntityDescriptionKey.WINDOW_FRONT_RIGHT: DatapointConfig(
        "closure-windows", ["read_security"]
    ),
    EntityDescriptionKey.FRONT_TRUNK: DatapointConfig(
        "closure-fronttrunk", ["read_security"]
    ),
    EntityDescriptionKey.FRONT_TRUNK_LOCK: DatapointConfig(
        "closure-fronttrunk", ["read_security"]
    ),
    EntityDescriptionKey.REAR_TRUNK: DatapointConfig(
        "closure-reartrunk", ["read_security"]
    ),
    EntityDescriptionKey.REAR_TRUNK_LOCK: DatapointConfig(
        "closure-reartrunk", ["read_security"]
    ),
    EntityDescriptionKey.SUNROOF: DatapointConfig("closure-sunroof", ["read_security"]),
    EntityDescriptionKey.ENGINE_COVER: DatapointConfig(
        "closure-enginecover", ["read_security"]
    ),
    EntityDescriptionKey.ENGINE_OIL: DatapointConfig(
        "internalcombustionengine-oillife", ["read_engine_oil"]
    ),
    EntityDescriptionKey.FUEL: DatapointConfig(
        "internalcombustionengine-amountremaining", ["read_fuel"]
    ),
    EntityDescriptionKey.FUEL_PERCENT: DatapointConfig(
        "internalcombustionengine-fuellevel", ["read_fuel"]
    ),
    EntityDescriptionKey.FUEL_RANGE: DatapointConfig(
        "internalcombustionengine-range", ["read_fuel"]
    ),
    EntityDescriptionKey.LOCATION: DatapointConfig(
        "location-preciselocation", ["read_location"]
    ),
    EntityDescriptionKey.ODOMETER: DatapointConfig(
        "odometer-traveleddistance", ["read_odometer"]
    ),
    EntityDescriptionKey.GEAR_STATE: DatapointConfig("transmission-gearstate", []),
    EntityDescriptionKey.TIRE_PRESSURE_BACK_LEFT: DatapointConfig(
        "wheel-tires", ["read_tires"]
    ),
    EntityDescriptionKey.TIRE_PRESSURE_BACK_RIGHT: DatapointConfig(
        "wheel-tires", ["read_tires"]
    ),
    EntityDescriptionKey.TIRE_PRESSURE_FRONT_LEFT: DatapointConfig(
        "wheel-tires", ["read_tires"]
    ),
    EntityDescriptionKey.TIRE_PRESSURE_FRONT_RIGHT: DatapointConfig(
        "wheel-tires", ["read_tires"]
    ),
    EntityDescriptionKey.ONLINE: DatapointConfig("connectivitystatus-isonline", []),
    EntityDescriptionKey.ASLEEP: DatapointConfig("connectivitystatus-isasleep", []),
    EntityDescriptionKey.DIGITAL_KEY_PAIRED: DatapointConfig(
        "connectivitystatus-isdigitalkeypaired", []
    ),
    EntityDescriptionKey.SURVEILLANCE_ENABLED: DatapointConfig(
        "surveillance-isenabled", []
    ),
    EntityDescriptionKey.FIRMWARE_VERSION: DatapointConfig(
        "connectivitysoftware-currentfirmwareversion", []
    ),
}

# Reverse index: signal code → tuple of entity description keys that read it.
DATAPOINT_CODE_MAP: dict[str | None, tuple[DatapointConfig, ...]] = {
    code: tuple(
        datapoint
        for datapoint in DATAPOINT_ENTITY_KEY_MAP.values()
        if datapoint.code == code
    )
    for code in {datapoint.code for datapoint in DATAPOINT_ENTITY_KEY_MAP.values()}
}


def normalize_signal_body_percent(code: str | None, body: dict[str, Any]) -> None:
    """Convert percent-unit bodies to decimal in place.

    Smartcar reports percentages with ``unit: "percent"`` and an integer value
    (e.g. 85). Internally the integration stores values as decimals (0.85) for
    consistency with the existing sensor descriptions in ``sensor.py``.
    """
    if body.get("unit") != "percent":
        return
    if "values" in body:
        item_key = SIGNAL_BODY_MULTIVALUE_ITEM_KEY_MAP.get(code) or "value"
        body["values"] = [v | {item_key: v[item_key] / 100} for v in body["values"]]
    elif "value" in body and body["value"] is not None:
        body["value"] /= 100
    body.pop("unit", None)


class SmartcarVehicleCoordinator(DataUpdateCoordinator):
    """Polls the V3 ``GET /vehicles/{id}/signals`` endpoint.

    Unlike the V2 batch endpoint, ``/signals`` returns every signal the vehicle
    knows about in a single response, so there is no batching to do here. We
    just fetch on the interval and apply the response to ``self.data``.

    When webhooks are configured the polling interval is disabled and the
    coordinator is updated by the webhook handler in ``webhooks.py``.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        auth: AbstractAuth,
        vehicle_id: str,
        vin: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize."""
        self.auth = auth
        self.vehicle_id = vehicle_id
        self.vin = vin
        self.entry = entry
        self.data: dict[str, Any] = {}

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{vin}",
            update_interval=(
                UPDATE_INTERVAL
                if CONF_APPLICATION_MANAGEMENT_TOKEN not in entry.data
                else None
            ),
        )

    def is_scope_enabled(
        self,
        sensor_key: EntityDescriptionKey,
        *,
        verbose: bool = False,
    ) -> bool:
        """Return whether the granted scopes cover this entity's needs."""
        granted = self.config_entry.data.get(CONF_SCOPES, [])
        required = DATAPOINT_ENTITY_KEY_MAP[sensor_key].required_scopes
        missing = [s for s in required if s not in granted]
        enabled = not missing

        if not enabled and verbose:
            _LOGGER.warning(
                "Skipping `%s` which requires %r; granted: %r, missing: %r",
                sensor_key,
                required,
                granted,
                missing,
            )

        return enabled

    def _has_any_active_entity(self) -> bool:
        """Return True when at least one enabled entity backs a polled signal.

        Used to short-circuit polling when the user has disabled every entity
        for this vehicle — avoids wasting API calls against the monthly quota.
        """
        registry = er.async_get(self.hass)
        for entity in er.async_entries_for_config_entry(
            registry, self.config_entry.entry_id
        ):
            if "_" not in entity.unique_id:
                continue
            _, key = entity.unique_id.split("_", 1)
            if key not in DATAPOINT_ENTITY_KEY_MAP:
                continue
            if DATAPOINT_ENTITY_KEY_MAP[key].code and not entity.disabled:
                return True
        return False

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all signals for this vehicle.

        Returns:
            The new coordinator data dict (signal-keyed). Returns the
            previously-stored data unchanged when polling is disabled or
            no entities are active.

        Raises:
            ConfigEntryAuthFailed: On 400/401/403 from Smartcar — triggers
                HA's reauth flow.
            UpdateFailed: On exhausted retries against 429/5xx, on network
                failures, and on malformed responses.
            ClientResponseError: For other HTTP errors not handled above.
        """
        if self.config_entry.pref_disable_polling:
            _LOGGER.debug("Coordinator %s: polling disabled, skipping", self.name)
            return self.data

        if not self._has_any_active_entity():
            _LOGGER.debug(
                "Coordinator %s: no active entities, skipping poll", self.name
            )
            return self.data

        _LOGGER.debug("Coordinator %s: fetching /signals", self.name)

        try:
            response = await async_request_with_retry(
                lambda: self.auth.request("get", f"vehicles/{self.vehicle_id}/signals"),
                logger=_LOGGER,
                context=f"Coordinator {self.name}",
            )
        except ClientResponseError as exc:
            if exc.status in {
                HTTPStatus.BAD_REQUEST,
                HTTPStatus.UNAUTHORIZED,
                HTTPStatus.FORBIDDEN,
            }:
                raise ConfigEntryAuthFailed from exc
            raise
        except (ClientConnectionError, TimeoutError) as exc:
            # All retries inside async_request_with_retry exhausted. Mark the
            # update as failed so HA reports entities unavailable and tries
            # again on the next interval, instead of bubbling a raw exception.
            msg = f"Network error after retries: {type(exc).__name__}: {exc}"
            raise UpdateFailed(msg) from exc

        if response.status in {
            HTTPStatus.TOO_MANY_REQUESTS,
            HTTPStatus.INTERNAL_SERVER_ERROR,
            HTTPStatus.BAD_GATEWAY,
            HTTPStatus.SERVICE_UNAVAILABLE,
            HTTPStatus.GATEWAY_TIMEOUT,
        }:
            response.release()
            msg = f"API returned {response.status} after retries"
            raise UpdateFailed(msg)

        response.raise_for_status()
        payload = await response.json()

        if "data" not in payload:
            msg = "Invalid signals response: missing 'data' array"
            raise UpdateFailed(msg)

        return self._merge_signals_data(payload["data"])

    def _merge_signals_data(self, signals: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply a list of signal resources to ``self.data``.

        The V3 ``GET /signals`` resource format nests ``code``, ``body``, and
        ``status`` inside ``attributes`` (JSON:API style), unlike webhook
        payloads where they are flat. We normalise here and reuse the same
        ``_DataAdder.from_response_body`` logic that webhooks use.

        Returns:
            The updated coordinator data dict.
        """
        with self.create_updated_data() as (add, updated_data):
            for item in signals:
                attrs = item.get("attributes", {})
                code = attrs.get("code")
                if code not in DATAPOINT_CODE_MAP:
                    continue

                status = attrs.get("status", {})
                is_error = status.get("value") == "ERROR"
                body = dict(attrs.get("body") or {})
                meta = item.get("meta", {})

                if is_error:
                    body = {"value": None}
                    data_age = None
                    fetched_at = None
                    unit_system = None
                else:
                    normalize_signal_body_percent(code, body)
                    unit = body.pop("unit", None)
                    unit_system = (
                        "imperial"
                        if unit in IMPERIAL_UNITS
                        else "metric"
                        if unit
                        else None
                    )
                    data_age = meta.get("oemUpdatedAt")
                    fetched_at = meta.get("retrievedAt")
                    if isinstance(data_age, str):
                        data_age = dt_util.parse_datetime(data_age)
                    if isinstance(fetched_at, str):
                        fetched_at = dt_util.parse_datetime(fetched_at)

                add.from_response_body(
                    code,
                    body=body,
                    unit_system=unit_system,
                    data_age=data_age,
                    fetched_at=fetched_at,
                    can_clear_meta=not is_error,
                )

            _LOGGER.debug("Coordinator %s: signals processed", self.name)
            return updated_data

    @contextmanager
    def create_updated_data(
        self,
    ) -> Generator[tuple[_DataAdder, dict[str, Any]]]:
        """Yield a writer + the mutable copy of ``self.data``."""
        updated_data = dict(self.data or {})
        yield _DataAdder(updated_data), updated_data


class _DataAdder:
    """Helper that stages signal bodies into the coordinator's data dict.

    Kept as a separate class so the polling path (``_merge_signals_data``),
    the webhook path (``_handle_webhook_signals``) and the optimistic command
    write-through path (``inject_raw_value``) all go through the same code.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        """Initialize."""
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
        """Merge a single signal body into ``data`` and update its metadata."""
        for datapoint in DATAPOINT_CODE_MAP[code]:
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
        """Set a raw value at the given key path.

        Used both for restoring entity state across restarts and for
        optimistic write-through after a successful command.
        """
        datapoint = DATAPOINT_ENTITY_KEY_MAP[entity_description_key]
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
            for meta_key, value in (
                ("unit_system", unit_system),
                ("data_age", data_age),
                ("fetched_at", fetched_at),
            ):
                full_key = f"{storage_key}:{meta_key}"
                if value:
                    self.data[full_key] = value
                elif can_clear:
                    self.data.pop(full_key, None)
