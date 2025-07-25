from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_entry_oauth2_flow import (
    AUTH_CALLBACK_PATH,
    MY_AUTH_CALLBACK_PATH,
)

from .const import OAUTH2_AUTHORIZE, OAUTH2_TOKEN


async def async_get_authorization_server(  # noqa: RUF029
    hass: HomeAssistant,  # noqa: ARG001
) -> AuthorizationServer:
    """Return authorization server details."""
    return AuthorizationServer(
        authorize_url=OAUTH2_AUTHORIZE,
        token_url=OAUTH2_TOKEN,
    )


async def async_get_description_placeholders(  # noqa: RUF029
    hass: HomeAssistant,
) -> dict[str, str]:
    """Return description placeholders for the credentials dialog."""
    if "my" in hass.config.components:
        redirect_url = MY_AUTH_CALLBACK_PATH
    else:
        ha_host = hass.config.external_url or "https://YOUR_DOMAIN:PORT"
        redirect_url = f"{ha_host}{AUTH_CALLBACK_PATH}"
    return {
        "more_info_url": "https://github.com/tube0013/Smartcar-HA?tab=readme-ov-file#configuration",
        "oauth_creds_url": "https://dashboard.smartcar.com/team/applications",
        "redirect_url": redirect_url,
    }
