from dataclasses import dataclass
import logging

from homeassistant.components.device_tracker import (
    TrackerEntity,
    TrackerEntityDescription,
)
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import EntityDescriptionKey
from .coordinator import SmartcarVehicleCoordinator
from .entity import SmartcarEntity, SmartcarEntityDescription

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SmartcarTrackerDescription(TrackerEntityDescription, SmartcarEntityDescription):
    """Class describing Smartcar tracker entities."""


ENTITY_DESCRIPTIONS: tuple[TrackerEntityDescription, ...] = (
    SmartcarTrackerDescription(
        key=EntityDescriptionKey.LOCATION,
        name="Location",
        value_key_path="location-preciselocation",
        value_cast=lambda location: location or {},
        icon="mdi:car",
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
        SmartcarLocationTracker(coordinator, description)
        for coordinator in coordinators.values()
        for description in ENTITY_DESCRIPTIONS
        if coordinator.is_scope_enabled(description.key, verbose=True)
    ]
    _LOGGER.info("Adding %s Smartcar device tracker entities", len(entities))
    async_add_entities(entities)


class SmartcarLocationTracker(
    SmartcarEntity[dict[str, float], dict[str, float]], TrackerEntity
):
    """Device tracker entity."""

    _attr_has_entity_name = True

    @property
    def latitude(self) -> float | None:
        return self._extract_value().get("latitude")

    @property
    def longitude(self) -> float | None:
        return self._extract_value().get("longitude")

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS
