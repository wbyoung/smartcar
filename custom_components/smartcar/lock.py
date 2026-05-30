"""Smartcar door lock entity."""

from dataclasses import dataclass
import logging

from homeassistant.components.lock import LockEntity, LockEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import EntityDescriptionKey
from .coordinator import SmartcarVehicleCoordinator
from .entity import SmartcarEntity, SmartcarEntityDescription

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SmartcarLockDescription(LockEntityDescription, SmartcarEntityDescription):
    """Smartcar lock entity description."""


ENTITY_DESCRIPTIONS: tuple[LockEntityDescription, ...] = (
    SmartcarLockDescription(
        key=EntityDescriptionKey.DOOR_LOCK,
        name="Door Lock",
        value_key_path="closure-islocked.value",
    ),
)


async def async_setup_entry(  # noqa: RUF029
    hass: HomeAssistant,  # noqa: ARG001
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up lock entities for each vehicle."""
    coordinators: dict[str, SmartcarVehicleCoordinator] = (
        entry.runtime_data.coordinators
    )
    entities = [
        SmartcarDoorLock(coordinator, description)
        for coordinator in coordinators.values()
        for description in ENTITY_DESCRIPTIONS
        if coordinator.is_scope_enabled(description.key, verbose=True)
    ]
    _LOGGER.info("Adding %s Smartcar lock entities", len(entities))
    async_add_entities(entities)


class SmartcarDoorLock(SmartcarEntity[bool, bool], LockEntity):
    """Door lock entity."""

    _attr_has_entity_name = True

    @property
    def is_locked(self) -> bool:
        """Return whether the doors are locked."""
        return self._extract_value()

    async def async_lock(self, **kwargs) -> None:  # noqa: ARG002, ANN003
        """Lock the doors via V3 commands/security/lock."""
        if await self._async_send_command("security/lock"):
            self._inject_raw_value(value=True)
            self.async_write_ha_state()

    async def async_unlock(self, **kwargs) -> None:  # noqa: ARG002, ANN003
        """Unlock the doors via V3 commands/security/unlock."""
        if await self._async_send_command("security/unlock"):
            self._inject_raw_value(value=False)
            self.async_write_ha_state()
