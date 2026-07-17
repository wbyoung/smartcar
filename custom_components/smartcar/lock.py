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
    """Class describing Smartcar lock entities."""


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
    """Lock entity for doors/windows."""

    _attr_has_entity_name = True

    @property
    def is_locked(self) -> bool:
        return self._extract_value()

    async def async_lock(
        self,
        **kwargs,  # noqa: ARG002, ANN003
    ) -> None:
        version = self.coordinator.auth.version
        command = "/security/lock"
        payload = None

        if version == "v2":
            command = "/security"
            payload = {"action": "LOCK"}

        if await self._async_send_command(command, payload):
            self._inject_raw_value(value=True)
            self.async_write_ha_state()

    async def async_unlock(
        self,
        **kwargs,  # noqa: ARG002, ANN003
    ) -> None:
        version = self.coordinator.auth.version
        command = "/security/unlock"
        payload = None

        if version == "v2":
            command = "/security"
            payload = {"action": "UNLOCK"}

        if await self._async_send_command(command, payload):
            self._inject_raw_value(value=False)
            self.async_write_ha_state()
