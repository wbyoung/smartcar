from homeassistant.exceptions import HomeAssistantError


class EmptyVehicleListError(HomeAssistantError):
    """Error to indicate no vehicles were returned by the API."""


class UnsupportedUserConfigurationError(HomeAssistantError):
    """Error to indicate multiple users are linked to a Smartcar application."""


class InvalidAuthError(HomeAssistantError):
    """Error to indicate there is invalid auth."""
