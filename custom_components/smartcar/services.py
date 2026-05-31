"""Smartcar custom services."""

from functools import partial
import logging
from typing import Final, Literal

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    selector,
)
from homeassistant.helpers.entity_component import DATA_INSTANCES
import voluptuous as vol

from .const import DOMAIN, EntityDescriptionKey
from .entity import async_send_command, inject_raw_value
from .lock import ENTITY_DESCRIPTIONS as LOCK_ENTITY_DESCRIPTIONS

_LOGGER = logging.getLogger(__name__)

SERVICE_NAME_LOCK_DOORS: Final = "lock_doors"
SERVICE_NAME_UNLOCK_DOORS: Final = "unlock_doors"
ATTR_CONFIG_ENTRY: Final = "config_entry"
ATTR_VIN: Final = "vin"


_SERVICE_SCHEMA_DOORS_SECURITY: Final = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): selector.ConfigEntrySelector(
            {"integration": DOMAIN},
        ),
        vol.Optional(ATTR_VIN): cv.string,
    },
)
SERVICE_SCHEMA_LOCK_DOORS: Final = _SERVICE_SCHEMA_DOORS_SECURITY
SERVICE_SCHEMA_UNLOCK_DOORS: Final = _SERVICE_SCHEMA_DOORS_SECURITY


def _async_write_entity_state(hass: HomeAssistant, entity_id: str) -> None:
    """Write entity state for a specific entity."""
    domain = entity_id.partition(".")[0]
    entity_comp = hass.data.get(DATA_INSTANCES, {}).get(domain)
    assert entity_comp is not None
    entity_obj = entity_comp.get_entity(entity_id)
    assert entity_obj is not None
    entity_obj.async_write_ha_state()


async def _send_security_command(
    call: ServiceCall,
    action: Literal["lock", "unlock"],
    *,
    hass: HomeAssistant,
) -> None:
    entry_id: str = call.data[ATTR_CONFIG_ENTRY]
    entry: ConfigEntry | None = hass.config_entries.async_get_entry(entry_id)
    vin: str = call.data.get(ATTR_VIN)

    if not entry:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_config_entry",
            translation_placeholders={"config_entry": entry_id},
        )

    if not vin:
        vin = next(iter(entry.runtime_data.coordinators.keys()))

    coordinator = entry.runtime_data.coordinators[vin]
    description = next(
        d for d in LOCK_ENTITY_DESCRIPTIONS if d.key == EntityDescriptionKey.DOOR_LOCK
    )

    # V3 command paths: commands/security/lock and commands/security/unlock
    if await async_send_command(coordinator, f"security/{action}"):
        inject_raw_value(coordinator, description, value=action == "lock")

        for entity in er.async_entries_for_config_entry(er.async_get(hass), entry_id):
            if "_" not in entity.unique_id:
                continue
            _, key = entity.unique_id.split("_", 1)
            if key == EntityDescriptionKey.DOOR_LOCK:
                _async_write_entity_state(hass, entity.entity_id)


async def _lock_doors(call: ServiceCall, *, hass: HomeAssistant) -> ServiceResponse:
    await _send_security_command(call, "lock", hass=hass)


async def _unlock_doors(call: ServiceCall, *, hass: HomeAssistant) -> ServiceResponse:
    await _send_security_command(call, "unlock", hass=hass)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the Smartcar services."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_NAME_LOCK_DOORS,
        partial(_lock_doors, hass=hass),
        schema=SERVICE_SCHEMA_LOCK_DOORS,
        supports_response=SupportsResponse.NONE,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_NAME_UNLOCK_DOORS,
        partial(_unlock_doors, hass=hass),
        schema=SERVICE_SCHEMA_UNLOCK_DOORS,
        supports_response=SupportsResponse.NONE,
    )
