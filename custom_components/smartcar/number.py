from dataclasses import dataclass
import logging
from typing import Any, TypedDict

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import EntityDescriptionKey
from .coordinator import SmartcarVehicleCoordinator
from .entity import SmartcarEntity, SmartcarEntityDescription

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SmartcarNumberDescription(NumberEntityDescription, SmartcarEntityDescription):
    """Class describing Smartcar number entities."""


ENTITY_DESCRIPTIONS: tuple[NumberEntityDescription, ...] = (
    SmartcarNumberDescription(
        key=EntityDescriptionKey.CHARGE_LIMIT,
        name="Charge Limit",
        value_key_path="charge-chargelimits.values",
        value_cast=lambda values: next(
            (
                round(value["limit"] * 100)
                for value in values or []
                if value["type"].lower() == "global" and value.get("condition") is None
            ),
            None,
        ),
        icon="mdi:battery-charging-80",
        mode=NumberMode.BOX,
        native_min_value=50.0,
        native_max_value=100.0,
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
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
        SmartcarChargeLimitNumber(coordinator, description)
        for coordinator in coordinators.values()
        for description in ENTITY_DESCRIPTIONS
        if coordinator.is_scope_enabled(description.key, verbose=True)
    ]
    _LOGGER.info("Adding %s Smartcar number entities", len(entities))
    async_add_entities(entities)


class _StorageValue(TypedDict):
    type: str
    limit: float
    condition: str | None


class SmartcarChargeLimitNumber(
    SmartcarEntity[float, list[_StorageValue]], NumberEntity
):
    """Number entity for charge limit."""

    _attr_has_entity_name = True

    @property
    def native_value(self) -> float | None:
        return self._extract_value()

    async def async_set_native_value(self, value: float) -> None:
        assert value >= 50, "Value must be between 50 and 100"
        assert value <= 100, "Value must be between 50 and 100"

        version = self.coordinator.auth.version
        raw_value = value / 100.0
        command = "/charge/set-limit"
        payload: dict[str, Any] = {"data": {"attributes": {"percent": value}}}

        if version == "v2":
            command = "/charge/limit"
            payload = {"limit": (raw_value := value / 100.0)}

        if await self._async_send_command(command, payload):
            non_global_or_conditional_limits = [
                value
                for value in self._extract_raw_value() or []
                if value["type"] != "global" or value["condition"] is not None
            ]

            self._inject_raw_value(
                [
                    {"type": "global", "limit": raw_value, "condition": None},
                    *non_global_or_conditional_limits,
                ]
            )
            self.async_write_ha_state()
