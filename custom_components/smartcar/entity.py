"""Base entity classes for the Smartcar integration."""

from __future__ import annotations

from collections.abc import Callable
import datetime as dt
from enum import Enum
from http import HTTPStatus
import logging
from typing import Any, Literal, Self

from aiohttp import ClientConnectionError, ClientResponseError, ClientTimeout
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.restore_state import (
    ExtraStoredData,
    RestoredExtraData,
    RestoreEntity,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import const as smartcar_const
from .const import DOMAIN
from .coordinator import SmartcarVehicleCoordinator
from .types import SmartcarAPIError
from .util import async_request_with_retry, key_path_get

_LOGGER = logging.getLogger(__name__)

# Smartcar V3 error statuses that should bubble up to the user instead of
# triggering a reauth. See https://smartcar.com/docs/api-reference/api-errors
ERROR_STATUS_VEHICLE_STATE = 409
ERROR_STATUS_RATE_LIMIT = 429
ERROR_STATUS_BILLING = 430
ERROR_STATUS_SERVER_ERROR = 500
ERROR_STATUS_COMPATIBILITY = 501
ERROR_STATUS_UPSTREAM = 502


# Smartcar V3 commands can return HTTP 202 with the connection held open
# while the vehicle responds. The OpenAPI spec shows examples taking ~3 min.
# Allow up to 4 minutes; commands that genuinely exceed this will fail and
# the next poll/webhook will reflect the real state.
_COMMAND_TIMEOUT = ClientTimeout(total=240)


class SmartcarEntity[ValueT, RawValueT](
    CoordinatorEntity[SmartcarVehicleCoordinator], RestoreEntity
):
    """Base entity for Smartcar V3 signals."""

    def __init__(
        self,
        coordinator: SmartcarVehicleCoordinator,
        description: EntityDescription,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.vin = coordinator.vin
        self.entity_description = description
        self._attr_unique_id = f"{self.vin}_{description.key}"
        self._attr_device_info = {"identifiers": {(DOMAIN, self.vin)}}

    @property
    def available(self) -> bool:
        """Return True only when both the raw and casted value are present."""
        return (
            super().available
            and self._extract_raw_value() is not None
            and self._extract_value() is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the data freshness attributes."""
        result: dict[str, Any] = {}
        if data_age := self._extract_data_age():
            result["age"] = data_age.isoformat()
        if fetched_at := self._extract_fetched_at():
            result["fetched_at"] = fetched_at.isoformat()
        return result or None

    async def async_update(self) -> None:
        """Request a coordinator refresh for this entity.

        With V3 ``/signals`` returning everything in one call there's no
        per-entity batching; we just delegate to the coordinator.
        """
        if not self.enabled:
            return
        await super().async_update()

    async def async_added_to_hass(self) -> None:
        """Restore last known state, if available."""
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
        """Persist the raw value + metadata across restarts."""
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
        root = self.entity_description.value_key_path.split(".")[0]
        return data.get(f"{root}:unit_system")

    def _extract_data_age(self) -> dt.datetime | None:
        data = self.coordinator.data or {}
        root = self.entity_description.value_key_path.split(".")[0]
        return data.get(f"{root}:data_age")

    def _extract_fetched_at(self) -> dt.datetime | None:
        data = self.coordinator.data or {}
        root = self.entity_description.value_key_path.split(".")[0]
        return data.get(f"{root}:fetched_at")

    def _extract_raw_value(self) -> RawValueT | None:
        return key_path_get(
            self.coordinator.data or {},
            self.entity_description.value_key_path,
            None,
        )

    def _extract_value(self) -> ValueT:
        description = self.entity_description
        unit_system = self._extract_unit_system()
        raw_value: RawValueT | None = self._extract_raw_value()
        value_cast: Callable[[RawValueT | None], ValueT] = description.value_cast
        value: ValueT = value_cast(raw_value)

        if (
            value is not None
            and unit_system == "imperial"
            and (imperial_conversion := description.imperial_conversion)
        ):
            value = imperial_conversion(value)
        return value

    def _inject_raw_value(
        self, value: RawValueT, extra_data: dict | None = None
    ) -> None:
        inject_raw_value(self.coordinator, self.entity_description, value, extra_data)

    async def _async_send_command(
        self,
        command_path: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Send a V3 command for this vehicle.

        ``command_path`` is appended to ``vehicles/{id}/commands/`` — for
        example, ``"security/lock"`` or ``"charge/start"``. Body defaults to
        an empty JSON object since most V3 commands take no parameters.

        Returns:
            ``True`` on success, ``False`` if the command failed in a way
            the integration recognises (auth / API error).
        """
        try:
            return await async_send_command(self.coordinator, command_path, payload)
        except SmartcarAPIError:
            return False


class IndirectDescriptorDefaultType(Enum):
    """Sentinel for IndirectDescriptor's default value."""

    _singleton = False


class IndirectDescriptor:
    """Dataclass descriptor that resolves at access time from a const collection."""

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

    def __set__(self, obj: Self, value: Any) -> None:  # noqa: ANN401
        if value == IndirectDescriptor.DEFAULT:
            return
        msg = f"readonly; configure via smartcar.const.{self._collection_name}"
        raise AttributeError(msg)


class SmartcarEntityDescription(EntityDescription):
    """Entity description with a Smartcar value path."""

    value_key_path: str
    value_cast: Callable[[Any], Any] = lambda x: x
    imperial_conversion: Callable[[float], float] | None = None
    entity_registry_enabled_default = IndirectDescriptor(
        "DEFAULT_ENABLED_ENTITY_DESCRIPTION_KEYS"
    )


class SmartcarMetaEntityDescription(EntityDescription):
    """Entity description for meta sensors (e.g. last webhook timestamp)."""

    value_fn: Callable[[dict[str, Any]], str | int | float | dt.datetime | None]
    attr_fn: Callable[[dict[str, Any]], dict[str, Any]] = lambda _: {}


def inject_raw_value[RawValueT](
    coordinator: SmartcarVehicleCoordinator,
    description: EntityDescription,
    value: RawValueT,
    extra_data: dict | None = None,
) -> None:
    """Optimistically write a value into the coordinator's data dict."""
    if extra_data is None:
        extra_data = {}

    unit_system = extra_data.get("unit_system")
    data_age = extra_data.get("data_age")
    fetched_at = extra_data.get("fetched_at")
    if isinstance(data_age, str):
        data_age = dt_util.parse_datetime(data_age)
    if isinstance(fetched_at, str):
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
    command_path: str,
    payload: dict[str, Any] | None = None,
) -> bool:
    """POST a V3 command for the given coordinator's vehicle.

    The full URL ends up as
    ``POST /v3/vehicles/{vehicleId}/commands/{command_path}``.

    Returns:
        ``True`` if Smartcar accepted the command, ``False`` otherwise.

    Raises:
        SmartcarAPIError: For non-recoverable command failures returned by
            the Smartcar API.
        ClientResponseError: For other unhandled HTTP errors after retries.
    """
    full_path = f"vehicles/{coordinator.vehicle_id}/commands/{command_path}"
    _LOGGER.info("Sending command %s for %s", command_path, coordinator.vin)

    try:
        resp = await async_request_with_retry(
            lambda: coordinator.auth.request(
                "post",
                full_path,
                json=payload or {},
                timeout=_COMMAND_TIMEOUT,
            ),
            logger=_LOGGER,
            context=f"Command {command_path} for {coordinator.vin}",
        )
        resp.raise_for_status()
    except ClientResponseError as err:
        if err.status == HTTPStatus.UNAUTHORIZED:
            _LOGGER.warning(
                "Auth error %s sending command %s for %s; triggering reauth",
                err.status,
                command_path,
                coordinator.vin,
            )
            coordinator.config_entry.async_start_reauth(coordinator.hass)
            return False
        if err.status in {
            ERROR_STATUS_VEHICLE_STATE,
            ERROR_STATUS_RATE_LIMIT,
            ERROR_STATUS_BILLING,
            ERROR_STATUS_SERVER_ERROR,
            ERROR_STATUS_COMPATIBILITY,
            ERROR_STATUS_UPSTREAM,
        }:
            raise SmartcarAPIError(err.status, err.message) from err
        raise
    except (ClientConnectionError, TimeoutError) as err:
        # All retries inside async_request_with_retry exhausted. Return False
        # so the calling entity reports the command as unsuccessful instead
        # of propagating a raw network exception up the stack.
        _LOGGER.warning(
            "Network error after retries sending command %s for %s: %s: %s",
            command_path,
            coordinator.vin,
            type(err).__name__,
            err,
        )
        return False
    else:
        # V3 commands return 200 (sync) or 202 (delayed) with the final result
        # in the body. Both indicate the request was accepted; surface either
        # as success to the entity. A FAILURE status inside the body would be
        # an interesting future enhancement but isn't critical for parity.
        return True
