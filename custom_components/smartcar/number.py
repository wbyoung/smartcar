"""Smartcar charge limit number entity."""

from dataclasses import dataclass
import logging
from typing import TypedDict

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
    """Smartcar number entity description."""


ENTITY_DESCRIPTIONS: tuple[NumberEntityDescription, ...] = (
    SmartcarNumberDescription(
        key=EntityDescriptionKey.CHARGE_LIMIT,
        name="Charge Limit",
        value_key_path="charge-chargelimits.values",
        value_cast=lambda values: next(
            (
                round(value["limit"] * 100)
                for value in values or []
                if value["type"].lower() == "global" and value["condition"] is None
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
    """Set up number entities for each vehicle."""
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
    """Charge limit number entity."""

    _attr_has_entity_name = True

    @property
    def native_value(self) -> float | None:
        """Return the current global charge limit as a percentage."""
        return self._extract_value()

    async def async_set_native_value(self, value: float) -> None:
        """Send a new charge limit via V3 commands/charge/limit."""
        assert 50 <= value <= 100, "Value must be between 50 and 100"

        raw_value = value / 100.0
        if await self._async_send_command("charge/limit", {"limit": raw_value}):
            non_global_or_conditional_limits = [
                v
                for v in self._extract_raw_value() or []
                if v["type"] != "global" or v["condition"] is not None
            ]
            self._inject_raw_value(
                [
                    {"type": "global", "limit": raw_value, "condition": None},
                    *non_global_or_conditional_limits,
                ]
            )
            self.async_write_ha_state()
