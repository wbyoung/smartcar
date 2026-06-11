"""Mock implementation of homeassistant.components.cloud.

This avoids having to import the module and all of its dependencies which would
create a large dependency tree including modules that fail to import in certain
environments.
"""

from homeassistant.core import HomeAssistant


def async_active_subscription(hass: HomeAssistant) -> bool:
    return False


async def async_delete_cloudhook(hass: HomeAssistant, webhook_id: str) -> None:  # noqa: RUF029
    raise CloudNotAvailable


async def async_get_or_create_cloudhook(hass: HomeAssistant, webhook_id: str) -> str:  # noqa: RUF029
    raise CloudNotConnected


class CloudNotAvailable(Exception):
    pass


class CloudNotConnected(Exception):
    pass
