from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any, cast

from aiohttp import ClientConnectorError, ClientError
from homeassistant.components import cloud, webhook
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import (
    AbstractOAuth2FlowHandler,
    AbstractOAuth2Implementation,
    async_get_config_entry_implementation,
)
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from . import populate_entry_data, vehicle_vins_in_use
from .auth_impl import AccessTokenAuthImpl
from .const import (
    API_ENDPOINTS,
    CONF_APPLICATION_ID,
    CONF_APPLICATION_MANAGEMENT_TOKEN,
    CONF_CLOUDHOOK,
    CONFIGURABLE_SCOPES,
    DEFAULT_NAME,
    DEFAULT_SCOPES,
    DOMAIN,
    REQUIRED_SCOPES,
    SMARTCAR_MODE,
    Scope,
)
from .errors import (
    EmptyVehicleListError,
    InvalidAuthError,
    UnsupportedUserConfigurationError,
)
from .util import (
    api_version_for_client_id,
    unique_id_from_entry_data,
    vins_from_entry_data,
)
from .webhooks import webhook_url_from_id

_LOGGER = logging.getLogger(__name__)

CONF_USE_WEBHOOKS = "use_webhooks"

GENERAL_CONFIGURATION_SCHEMA = {
    vol.Optional(CONF_APPLICATION_ID): TextSelector(
        config=TextSelectorConfig(type=TextSelectorType.TEXT)
    ),
    vol.Optional(CONF_APPLICATION_MANAGEMENT_TOKEN): TextSelector(
        config=TextSelectorConfig(type=TextSelectorType.TEXT)
    ),
    vol.Required(CONF_USE_WEBHOOKS, default=True): bool,
}
BASE_DESCRIPTION_PLACEHOLDERS = {
    "webhook_url": "webhooks-not-enabled",
    "smartcar_url": "https://dashboard.smartcar.com/configuration",
    "docs_url": "https://github.com/wbyoung/smartcar/#webhooks",
}


def _validate_general_configuration_input(
    user_input: dict[str, Any],
    flow_impl: AbstractOAuth2Implementation,
    errors: dict[str, str],
) -> None:
    application_id = user_input.get(CONF_APPLICATION_ID)
    use_webhooks = user_input[CONF_USE_WEBHOOKS]
    management_token = user_input.get(CONF_APPLICATION_MANAGEMENT_TOKEN)

    if use_webhooks and not management_token:
        errors[CONF_APPLICATION_MANAGEMENT_TOKEN] = "no_management_token"

    if not use_webhooks and management_token:
        errors["base"] = "extraneous_management_token"

    if not application_id and api_version_for_client_id(flow_impl.client_id) == "v3":
        errors["base"] = "no_application_id"

    if not management_token:
        user_input.pop(CONF_APPLICATION_MANAGEMENT_TOKEN, None)


def _add_dynamic_values_to_entry_data(
    data: dict[str, Any],
) -> dict[str, Any]:
    return (
        {
            **data,
            CONF_USE_WEBHOOKS: bool(data.get(CONF_APPLICATION_MANAGEMENT_TOKEN)),
        }
        if data
        else data
    )


class SmartcarOAuth2FlowHandler(AbstractOAuth2FlowHandler, domain=DOMAIN):  # type: ignore[call-arg]
    """Config flow to handle Smartcar OAuth2 authentication."""

    DOMAIN = DOMAIN
    VERSION = 2
    MINOR_VERSION = 0
    entry_data: dict[str, Any] | None = None
    scope_data: dict[str, Any] | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,  # noqa: ARG004
    ) -> OptionsFlow:
        """Get the options flow for this handler.

        Returns:
            The options flow.
        """
        return SmartcarOptionsFlow()

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Extra data that needs to be appended to the authorize url."""

        assert self.entry_data is not None

        return {
            "mode": SMARTCAR_MODE,
            "scope": " ".join(self.requested_scopes),
        } | (
            {
                # for v3, smartcar shifted to what they refer to as application-
                # level access tokens. they use oauth to describe their auth
                # scheme, but this is something seemingly much more customized
                # or specific to their end goals as it's different from most
                # flows. in particular:
                #
                #   - client_id is actually expected to be the application_id.
                #   - client_id is not used here at all & instead only used
                #     for token requests (which happen outside of the oauth
                #     flow).
                #   - the flow is used to add a connection for a user and a
                #     vehicle.
                #   - the resulting token is basically discarded.
                #   - a non-standard `user_id` is included in the redirect URL
                #     which they expect will be captured & used for future
                #     requests. (this allows a backend app to determine the
                #     correct end-user in multi-user app configurations).
                "client_id": self.entry_data.get(CONF_APPLICATION_ID, ""),
            }
            if api_version_for_client_id(self.flow_impl.client_id) == "v3"
            else {}
        )

    def _initial_data(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.source == SOURCE_REAUTH:
            result = self._get_reauth_entry().data
        if self.source == SOURCE_RECONFIGURE:
            result = self._get_reconfigure_entry().data
        return result

    @property
    def selected_scopes(self) -> list[Scope]:
        assert self.scope_data

        return sorted(
            [
                cast("Scope", scope)
                for scope, selected in self.scope_data.items()
                if selected
            ]
        )

    @property
    def requested_scopes(self) -> list[Scope]:
        return REQUIRED_SCOPES + self.selected_scopes

    async def async_step_webhooks(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the webhooks config step.

        Returns:
            The config flow result.
        """
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {**BASE_DESCRIPTION_PLACEHOLDERS}

        if user_input is not None:
            user_input = {**user_input}
            _validate_general_configuration_input(user_input, self.flow_impl, errors)

        if user_input is not None and not errors:
            self.entry_data = {**user_input}
            self.entry_data.pop(CONF_USE_WEBHOOKS, None)
            return await self.async_step_scopes()

        return self.async_show_form(
            step_id="webhooks",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(GENERAL_CONFIGURATION_SCHEMA),
                _add_dynamic_values_to_entry_data(self._initial_data())
                if user_input is None
                else user_input,
            ),
            errors=errors,
            last_step=False,
            description_placeholders=description_placeholders,
        )

    async def async_step_scopes(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the scopes selection step.

        Returns:
            The config flow result.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            self.scope_data = user_input

            if self.selected_scopes:
                return await self.async_step_auth()
            errors["base"] = "no_scopes"

        return self.async_show_form(
            step_id="scopes",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(str(scope), default=scope in DEFAULT_SCOPES): bool
                        for scope in CONFIGURABLE_SCOPES
                    }
                ),
                dict.fromkeys(
                    self._initial_data().get(CONF_TOKEN, {}).get("scopes", []), True
                )
                if user_input is None
                else user_input,
            ),
            errors=errors,
            last_step=False,
        )

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # add in the start of our customized flow if that hasn't been done yet
        if self.source == SOURCE_REAUTH:
            if self.scope_data is None:
                return await self.async_step_scopes()
        elif self.entry_data is None:
            return await self.async_step_webhooks()
        return await super().async_step_auth(user_input)

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry.

        Replays the customized flow (webhooks then scopes) before re-running
        the OAuth authorization so permissions can be changed after setup.

        Returns:
            The config flow result.
        """
        return await self.async_step_user()

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Perform reauth upon an API authentication error.

        Returns:
            The config flow result.
        """
        self.entry_data = {**self._initial_data()}
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dialog that informs the user that reauth is required.

        Returns:
            The config flow result.
        """
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict) -> ConfigFlowResult:
        assert self.entry_data is not None

        session = async_get_clientsession(self.hass)
        token = data[CONF_TOKEN][CONF_ACCESS_TOKEN]
        auth = AccessTokenAuthImpl(
            session,
            token,
            API_ENDPOINTS,
            version=api_version_for_client_id(self.flow_impl.client_id),
        )
        data = {**self.entry_data, **data}
        data.pop(CONF_USE_WEBHOOKS, None)
        description_placeholders = {**BASE_DESCRIPTION_PLACEHOLDERS}

        try:
            await populate_entry_data(
                data,
                auth,
                self.requested_scopes,
            )
        except EmptyVehicleListError:
            _LOGGER.exception("No vehicles returned")
            return self.async_abort(reason="no_vehicles")
        except UnsupportedUserConfigurationError:
            _LOGGER.exception(
                "Unsupported user configuration detected; expected single user"
            )
            return self.async_abort(reason="not_single_user_app")
        except InvalidAuthError:
            _LOGGER.exception("Failed to authenticate")
            return self.async_abort(reason="invalid_access_token")
        except (ClientConnectorError, ClientError):
            _LOGGER.exception("Failed to fetch vehicles")
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(unique_id_from_entry_data(data))

        current_entry = (
            self._get_reauth_entry()
            if self.source == SOURCE_REAUTH
            else self._get_reconfigure_entry()
            if self.source == SOURCE_RECONFIGURE
            else None
        )

        other_vins = vehicle_vins_in_use(self.hass, current_entry)
        duplicate_vins = [
            details["vin"]
            for details in data.get("vehicles", {}).values()
            if details.get("vin") in other_vins
        ]

        if duplicate_vins:
            return self.async_abort(
                reason="duplicate_vehicles",
                description_placeholders={"vins": duplicate_vins},
            )

        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(
                reason="wrong_vehicles",
                description_placeholders={
                    "vins": vins_from_entry_data(self._initial_data())
                },
            )

            return self.async_update_reload_and_abort(
                current_entry, data={**self._initial_data(), **data}
            )

        if self.source == SOURCE_RECONFIGURE:
            self._abort_if_unique_id_mismatch(
                reason="wrong_vehicles",
                description_placeholders={
                    "vins": vins_from_entry_data(self._initial_data())
                },
            )
        else:
            self._abort_if_unique_id_configured()

        # populate webhook details
        if CONF_APPLICATION_MANAGEMENT_TOKEN in data:
            try:
                webhook_id, webhook_url, cloudhook = await _get_webhook_details(
                    self.hass,
                    self._initial_data().get(CONF_WEBHOOK_ID)
                    if self.source == SOURCE_RECONFIGURE
                    else None,
                )
            except cloud.CloudNotConnected:
                return self.async_abort(reason="cloud_not_connected")
            data = {
                **data,
                CONF_WEBHOOK_ID: webhook_id,
                CONF_CLOUDHOOK: cloudhook,
            }
            description_placeholders = {
                **description_placeholders,
                "webhook_url": webhook_url,
            }

        if self.source == SOURCE_RECONFIGURE:
            reconfigure_data = {**self._initial_data(), **data}
            if CONF_APPLICATION_MANAGEMENT_TOKEN not in data:
                # webhooks were disabled during reconfigure; drop stale details
                reconfigure_data.pop(CONF_APPLICATION_MANAGEMENT_TOKEN, None)
                reconfigure_data.pop(CONF_WEBHOOK_ID, None)
                reconfigure_data.pop(CONF_CLOUDHOOK, None)

            return self.async_update_reload_and_abort(
                current_entry,
                data=reconfigure_data,
                reason="reconfigure_successful",
            )

        return self.async_create_entry(
            title=DEFAULT_NAME,
            data=data,
            description_placeholders=description_placeholders,
        )


class SmartcarOptionsFlow(OptionsFlow):
    """Handle a option flow."""

    def _initial_data(self) -> dict[str, Any]:
        result: dict[str, Any] = self.config_entry.data
        return result

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle options flow.

        Returns:
            The config flow result.
        """
        return await self.async_step_webhooks(user_input)

    async def async_step_webhooks(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the webhooks config step.

        Returns:
            The config flow result.
        """
        entry_data = {**self.config_entry.data}
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {**BASE_DESCRIPTION_PLACEHOLDERS}

        if user_input is not None:
            user_input = {**user_input}
            impl = await async_get_config_entry_implementation(
                self.hass, self.config_entry
            )
            _validate_general_configuration_input(user_input, impl, errors)

        if user_input is not None and not errors:
            entry_data.pop(CONF_APPLICATION_MANAGEMENT_TOKEN, None)
            entry_data.update(user_input)
            entry_data.pop(CONF_USE_WEBHOOKS, None)

        # always try to populate webhook details since the url is used in the
        # description placeholders. (the entry_data will not be saved if there
        # were errors.)
        if entry_data.get(CONF_APPLICATION_MANAGEMENT_TOKEN):
            try:
                webhook_id, webhook_url, cloudhook = await _get_webhook_details(
                    self.hass, entry_data.get(CONF_WEBHOOK_ID)
                )
            except cloud.CloudNotConnected:
                return self.async_abort(reason="cloud_not_connected")
            entry_data = {
                **entry_data,
                CONF_WEBHOOK_ID: webhook_id,
                CONF_CLOUDHOOK: cloudhook,
            }
            description_placeholders = {
                **description_placeholders,
                "webhook_url": webhook_url,
            }
        else:
            entry_data.pop(CONF_WEBHOOK_ID, None)
            entry_data.pop(CONF_CLOUDHOOK, None)

        if user_input is not None and not errors:
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=entry_data,
            )
            return self.async_create_entry(
                data={},
                description_placeholders=description_placeholders,
            )

        return self.async_show_form(
            step_id="webhooks",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(GENERAL_CONFIGURATION_SCHEMA),
                _add_dynamic_values_to_entry_data(
                    self._initial_data(),
                )
                if user_input is None
                else user_input,
            ),
            errors=errors,
            last_step=True,
            description_placeholders=description_placeholders,
        )


async def _get_webhook_details(
    hass: HomeAssistant, webhook_id: str | None = None
) -> tuple[str, str, bool]:
    if webhook_id is None:
        webhook_id = webhook.async_generate_id()
    return (webhook_id, *(await webhook_url_from_id(hass, webhook_id)))
