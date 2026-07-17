from collections.abc import Callable
import datetime as dt
from enum import Enum
from http import HTTPStatus
import logging
from typing import Any, Literal, Self

from aiohttp import ClientResponseError
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.restore_state import (
    ExtraStoredData,
    RestoredExtraData,
    RestoreEntity,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import const as smartcar_const, util
from .const import DOMAIN
from .coordinator import DATAPOINT_ENTITY_KEY_MAP, SmartcarVehicleCoordinator
from .types import SmartcarAPIError
from .util import key_path_get

_LOGGER = logging.getLogger(__name__)

ERROR_STATUS_VEHICLE_STATE = 409
ERROR_STATUS_RATE_LIMIT = 429
ERROR_STATUS_BILLING = 430
ERROR_STATUS_SERVER_ERROR = 500
ERROR_STATUS_COMPATIBILITY = 501
ERROR_STATUS_UPSTREAM = 502


class SmartcarEntity[ValueT, RawValueT](
    CoordinatorEntity[SmartcarVehicleCoordinator], RestoreEntity
):
    """Base Smartcar entity class."""

    def __init__(
        self, coordinator: SmartcarVehicleCoordinator, description: EntityDescription
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        device_id = coordinator.vehicle_id

        if coordinator.version == "v2" and coordinator.vin:
            device_id = coordinator.vin

        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._attr_device_info = {"identifiers": {(DOMAIN, device_id)}}

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._extract_raw_value() is not None
            and self._extract_value() is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        result = {}

        if data_age := self._extract_data_age():
            result["age"] = data_age.isoformat()

        if fetched_at := self._extract_fetched_at():
            result["fetched_at"] = fetched_at.isoformat()

        return result or None

    async def async_update(self) -> None:
        if not self.enabled:
            return

        if DATAPOINT_ENTITY_KEY_MAP[self.entity_description.key].endpoint_v2 is None:
            msg = f"Unsupported update requests for: {self.entity_description.key}"
            raise NotImplementedError(msg)

        self.coordinator.batch_sensor(self)

        await super().async_update()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        if (
            (last_state := await self.async_get_last_state()) is not None  # noqa: PLR0916
            and last_state.state not in {STATE_UNKNOWN, STATE_UNAVAILABLE}
            and (extra_data := await self.async_get_last_extra_data()) is not None
            and (extra_data_dict := extra_data.as_dict())
            and (extra_data_raw_value := extra_data_dict.get("raw_value")) is not None
            and not self.available
        ):
            extra_data_dict.pop("raw_value")

            self._inject_raw_value(extra_data_raw_value, extra_data_dict)

    @property
    def extra_restore_state_data(self) -> ExtraStoredData | None:
        data: dict[str, Any] = {"raw_value": self._extract_raw_value()}

        if unit_system := self._extract_unit_system():
            data["unit_system"] = unit_system

        if data_age := self._extract_data_age():
            data["data_age"] = data_age.isoformat()

        if fetched_at := self._extract_fetched_at():
            data["fetched_at"] = fetched_at.isoformat()

        return RestoredExtraData(data)

    def _extract_unit_system(self) -> str | None:
        data = self.coordinator.data or {}
        description = self.entity_description
        key_path = description.value_key_path.split(".")
        return data.get(f"{key_path[0]}:unit_system")

    def _extract_data_age(self) -> dt.datetime | None:
        data = self.coordinator.data or {}
        description = self.entity_description
        key_path = description.value_key_path.split(".")
        return data.get(f"{key_path[0]}:data_age")

    def _extract_fetched_at(self) -> dt.datetime | None:
        data = self.coordinator.data or {}
        description = self.entity_description
        key_path = description.value_key_path.split(".")
        return data.get(f"{key_path[0]}:fetched_at")

    def _extract_raw_value(self) -> RawValueT | None:
        data = self.coordinator.data or {}
        description = self.entity_description
        value: RawValueT | None = key_path_get(data, description.value_key_path, None)
        return value

    def _extract_value(self) -> ValueT:
        description = self.entity_description
        unit_system = self._extract_unit_system()
        raw_value: RawValueT | None = self._extract_raw_value()
        value_cast: Callable[[RawValueT | None], ValueT] = description.value_cast
        value: ValueT = value_cast(raw_value)

        if (
            value is not None
            and (unit_system == "imperial")
            and (imperial_conversion := self.entity_description.imperial_conversion)
        ):
            value = imperial_conversion(value)

        return value

    def _inject_raw_value(
        self, value: RawValueT, extra_data: dict | None = None
    ) -> None:
        inject_raw_value(self.coordinator, self.entity_description, value, extra_data)

    async def _async_send_command(
        self,
        subpath: str,
        payload: dict[str, Any] | None,
        *,
        method: str = "post",
        **kwargs,  # noqa: ARG002, ANN003
    ) -> bool:
        try:
            return await async_send_command(
                self.coordinator, subpath, payload, method=method
            )
        except SmartcarAPIError:
            return False


class IndirectDescriptorDefaultType(Enum):
    """IndirectDescriptor DEFAULT singleton."""

    _singleton = False


class IndirectDescriptor:
    """Descriptor to override a dataclass field.

    It will instead lookup a value from a named collection defined in the
    `smartcar.const` module.
    """

    DEFAULT = IndirectDescriptorDefaultType._singleton  # noqa: SLF001

    def __init__(self, collection_name: str) -> None:
        """Initialize."""
        self._collection_name = collection_name
        self._collection = getattr(smartcar_const, collection_name)

    def __get__(
        self,
        entity_description: EntityDescription | None,
        objtype: type[EntityDescription],
    ) -> bool | Literal[IndirectDescriptorDefaultType._singleton]:
        if entity_description is None:
            return IndirectDescriptor.DEFAULT

        return entity_description.key in self._collection

    def __set__(
        self,
        obj: Self,
        value: Any,  # noqa: ANN401
    ) -> None:
        # dataclasses will set the value to the default value from the
        # __init__ method they create, so the default value needs to be a
        # unique value that we can allow to be set (by being ignored) here
        # while raising for any other value being set.
        if value == IndirectDescriptor.DEFAULT:
            return
        msg = f"readonly; configure via smartcar.const.{self._collection_name}"
        raise AttributeError(msg)


class SmartcarEntityDescription(EntityDescription):
    """Class describing Smartcar sensor entities."""

    value_key_path: str
    value_cast: Callable[[Any], Any] = lambda x: x
    imperial_conversion: Callable[[float], float] | None = None
    entity_registry_enabled_default = IndirectDescriptor(
        "DEFAULT_ENABLED_ENTITY_DESCRIPTION_KEYS"
    )


class SmartcarMetaEntityDescription(EntityDescription):
    """Class describing Smartcar meta sensor entities."""

    value_fn: Callable[[dict[str, Any]], str | int | float | dt.datetime | None]
    attr_fn: Callable[[dict[str, Any]], dict[str, Any]] = lambda _: {}


def inject_raw_value[RawValueT](
    coordinator: SmartcarVehicleCoordinator,
    description: EntityDescription,
    value: RawValueT,
    extra_data: dict | None = None,
) -> None:
    if extra_data is None:
        extra_data = {}

    unit_system = extra_data.get("unit_system")

    if data_age := extra_data.get("data_age"):
        data_age = dt_util.parse_datetime(data_age)

    if fetched_at := extra_data.get("fetched_at"):
        fetched_at = dt_util.parse_datetime(fetched_at)

    with coordinator.create_updated_data() as (add, updated_data):
        add.from_storage_raw_value(
            description.key,
            description.value_key_path,
            value=value,
            unit_system=unit_system,
            data_age=data_age,
            fetched_at=fetched_at,
            can_clear_meta=False,
        )
        coordinator.data = updated_data


async def async_send_command(
    coordinator: SmartcarVehicleCoordinator,
    subpath: str,
    payload: dict[str, Any] | None,
    *,
    method: str = "post",
) -> bool:
    _LOGGER.info(
        "Sending %s request for %s (VIN: %s)",
        subpath,
        coordinator.vehicle_id,
        coordinator.vin,
    )
    success = False
    version = coordinator.auth.version

    if version == "v3":
        subpath = f"/commands{subpath}"

    try:
        resp = await util.async_request_with_retry(
            lambda: coordinator.auth.request(
                method,
                f"vehicles/{coordinator.vehicle_id}{subpath}",
                version=version,
                json=payload,
            ),
            logger=_LOGGER,
            context=f"Command {subpath} for {coordinator.vehicle_id} (VIN : {coordinator.vin}",
        )
        resp.raise_for_status()
        success = True
    except ClientResponseError as err:
        if err.status == HTTPStatus.UNAUTHORIZED:
            _LOGGER.warning(
                "Auth error %s sending %s request for %s (VIN: %s)",
                err.status,
                subpath,
                coordinator.vehicle_id,
                coordinator.vin,
            )
            coordinator.config_entry.async_start_reauth(coordinator.hass)
        elif err.status in {
            ERROR_STATUS_VEHICLE_STATE,
            ERROR_STATUS_RATE_LIMIT,
            ERROR_STATUS_BILLING,
            ERROR_STATUS_SERVER_ERROR,
            ERROR_STATUS_COMPATIBILITY,
            ERROR_STATUS_UPSTREAM,
        }:
            raise SmartcarAPIError(err.status, err.message) from err
        else:
            raise

    return success
