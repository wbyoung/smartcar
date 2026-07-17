from dataclasses import dataclass
import logging

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import EntityDescriptionKey
from .coordinator import SmartcarVehicleCoordinator
from .entity import SmartcarEntity, SmartcarEntityDescription

_LOGGER = logging.getLogger(__name__)


def _hvac_bool(body: object) -> object:
    """Extract a boolean from an HVAC webhook signal body ({"value": bool}).

    Returns:
        The extracted boolean or the body unchanged.
    """
    if isinstance(body, dict):
        return body.get("value")
    return body


@dataclass(frozen=True, kw_only=True)
class SmartcarSwitchDescription(SwitchEntityDescription, SmartcarEntityDescription):
    """Class describing Smartcar switch entities."""


ENTITY_DESCRIPTIONS: tuple[SwitchEntityDescription, ...] = (
    SmartcarSwitchDescription(
        key=EntityDescriptionKey.CHARGING,
        name="Charging",
        value_key_path="charge-ischarging.value",
        icon="mdi:ev-plug-type2",
    ),
)

CLIMATE_ENTITY_DESCRIPTIONS: tuple[SwitchEntityDescription, ...] = (
    SmartcarSwitchDescription(
        key=EntityDescriptionKey.CLIMATE,
        name="Climate",
        value_key_path="hvac-iscabinhvacactive",
        value_cast=_hvac_bool,
        icon="mdi:air-conditioner",
    ),
)


async def async_setup_entry(  # noqa: RUF029
    hass: HomeAssistant,  # noqa: ARG001
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches from coordinator."""
    coordinators: dict[str, SmartcarVehicleCoordinator] = (
        entry.runtime_data.coordinators
    )
    entities: list[SwitchEntity] = [
        SmartcarChargingSwitch(coordinator, description)
        for coordinator in coordinators.values()
        for description in ENTITY_DESCRIPTIONS
        if coordinator.is_scope_enabled(description.key, verbose=True)
    ]
    entities += [
        SmartcarClimateSwitch(coordinator, description)
        for coordinator in coordinators.values()
        for description in CLIMATE_ENTITY_DESCRIPTIONS
        if coordinator.is_scope_enabled(description.key, verbose=True)
    ]
    _LOGGER.info("Adding %s Smartcar switch entities", len(entities))
    async_add_entities(entities)


class SmartcarChargingSwitch(SmartcarEntity[bool, bool], SwitchEntity):
    """Switch entity."""

    _attr_has_entity_name = True

    @property
    def is_on(self) -> bool:
        return self._extract_value()

    async def async_turn_on(
        self,
        **kwargs,  # noqa: ARG002, ANN003
    ) -> None:
        version = self.coordinator.auth.version
        command = "/charge/start"
        payload = None

        if version == "v2":
            command = "/charge"
            payload = {"action": "START"}

        if await self._async_send_command(command, payload):
            self._inject_raw_value(value=True)
            self.async_write_ha_state()

    async def async_turn_off(
        self,
        **kwargs,  # noqa: ARG002, ANN003
    ) -> None:
        version = self.coordinator.auth.version
        command = "/charge/stop"
        payload = None

        if version == "v2":
            command = "/charge"
            payload = {"action": "STOP"}

        if await self._async_send_command(command, payload):
            self._inject_raw_value(value=False)
            self.async_write_ha_state()


class SmartcarClimateSwitch(SmartcarEntity[bool, bool], SwitchEntity):
    """Switch entity to start/stop cabin climate (preconditioning)."""

    _attr_has_entity_name = True

    @property
    def is_on(self) -> bool:
        return self._extract_value()

    async def async_turn_on(
        self,
        **kwargs,  # noqa: ARG002, ANN003
    ) -> None:
        version = self.coordinator.auth.version
        command = "/climate/start"
        payload = None

        if version == "v2":
            command = "/climate"
            payload = {"action": "START"}

        if await self._async_send_command(command, payload):
            self._inject_raw_value(value=True)
            self.async_write_ha_state()

    async def async_turn_off(
        self,
        **kwargs,  # noqa: ARG002, ANN003
    ) -> None:
        version = self.coordinator.auth.version
        command = "/climate/stop"
        payload = None

        if version == "v2":
            command = "/climate"
            payload = {"action": "STOP"}

        if await self._async_send_command(command, payload):
            self._inject_raw_value(value=False)
            self.async_write_ha_state()
