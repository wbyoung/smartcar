"""Diagnostics support for Smartcar."""

from http import HTTPStatus
import json
from typing import Any, cast

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_WEBHOOK_ID,
)
from homeassistant.core import HomeAssistant

from .const import CONF_APPLICATION_MANAGEMENT_TOKEN
from .coordinator import SmartcarVehicleCoordinator
from .webhooks import webhook_url_from_id

CONF_REFRESH_TOKEN = "refresh_token"  # noqa: S105
CONF_VIN = "vin"

TO_REDACT = {
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_ACCESS_TOKEN,
    CONF_APPLICATION_MANAGEMENT_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_VIN,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinators: dict[str, SmartcarVehicleCoordinator] = (
        entry.runtime_data.coordinators
    )

    meta_coordinator = entry.runtime_data.meta_coordinator
    metadata = {**meta_coordinator.data}

    if "last_webhook_request" in metadata:
        include_raw = False
        response = metadata.get("last_webhook_response", {})
        response_status = response.get("status")
        request = metadata.pop("last_webhook_request")
        include_raw = response_status == HTTPStatus.UNAUTHORIZED

        try:
            metadata["last_webhook_request"] = json.loads(request)
        except json.JSONDecodeError:
            include_raw = True

        if include_raw:
            metadata["last_webhook_request_raw"] = request

    return cast(
        "dict[str, Any]",
        async_redact_data(
            {
                "entry": entry.as_dict(),
                "webhook_url": (
                    await webhook_url_from_id(hass, entry.data[CONF_WEBHOOK_ID])
                )[0]
                if CONF_WEBHOOK_ID in entry.data
                else None,
                "data": {
                    coordinator_name: coordinator.data
                    for coordinator_name, coordinator in coordinators.items()
                },
                "version": next(
                    iter(coordinator.version for coordinator in coordinators.values())
                ),
                "metadata": metadata,
            },
            TO_REDACT,
        ),
    )
