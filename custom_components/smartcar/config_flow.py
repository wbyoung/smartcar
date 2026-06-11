"""Smartcar V3 config flow.

This flow no longer uses Home Assistant's ``AbstractOAuth2FlowHandler``.
Smartcar V3 dropped per-user OAuth tokens with refresh, so the standard
authorization-code-grant + refresh-token framework doesn't fit. Instead:

  1. The user enters three credentials (Application ID, V3 Client ID, V3
     Client Secret) plus optional webhook settings.
  2. We verify the V3 Client ID/Secret immediately by minting a token at
     ``iam.smartcar.com/oauth2/token`` — this fails fast on bad creds.
  3. The user picks the scopes to request.
  4. We show them the redirect URI they need to register on the Smartcar
     dashboard, then send them to Smartcar Connect.
  5. After consent, Smartcar redirects to ``/api/smartcar/callback`` on this
     HA instance, where :class:`SmartcarConnectCallbackView` resumes the flow
     with the ``userId`` from the URL.
  6. We fetch ``/v3/connections`` using the just-discovered ``userId`` to
     enumerate vehicles, then create the config entry.

There is no my.home-assistant.io intermediary in this flow — the callback
goes directly to the HA instance's external URL. That sidesteps Safari's
ITP-blocked localStorage issue from the earlier OAuth2 path.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
import secrets
from typing import Any, cast
from urllib.parse import urlencode

from aiohttp import ClientConnectorError, ClientError
from homeassistant.components import cloud, webhook
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.selector import (
    BooleanSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from . import populate_entry_data, vehicle_vins_in_use
from .auth_impl import ClientCredentialsAuthImpl, ClientCredentialsTokenManager
from .const import (
    API_HOST,
    CONF_APPLICATION_ID,
    CONF_APPLICATION_MANAGEMENT_TOKEN,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_CLOUDHOOK,
    CONF_WEBHOOK_BACKUP_POLLING,
    CONFIGURABLE_SCOPES,
    DEFAULT_NAME,
    DEFAULT_SCOPES,
    DOMAIN,
    OAUTH2_AUTHORIZE,
    REQUIRED_SCOPES,
    SMARTCAR_MODE,
    Scope,
)
from .errors import EmptyVehicleListError, InvalidAuthError, MissingVINError
from .util import unique_id_from_entry_data, vins_from_entry_data
from .views import CALLBACK_PATH, async_register_view, register_state
from .webhooks import webhook_url_from_id

_LOGGER = logging.getLogger(__name__)

CONF_USE_WEBHOOKS = "use_webhooks"

CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_APPLICATION_ID): TextSelector(
            config=TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Required(CONF_CLIENT_ID): TextSelector(
            config=TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Required(CONF_CLIENT_SECRET): TextSelector(
            config=TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)

WEBHOOKS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USE_WEBHOOKS, default=True): bool,
        vol.Optional(CONF_APPLICATION_MANAGEMENT_TOKEN): TextSelector(
            config=TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_WEBHOOK_BACKUP_POLLING, default=False): BooleanSelector(),
    }
)


def _validate_webhook_input(
    user_input: dict[str, Any],
    errors: dict[str, str],
) -> None:
    """Validate the webhooks step.

    The webhook backup-polling toggle has no validation beyond what the
    schema enforces (it's a boolean). The only real check is that an
    application management token is present when ``use_webhooks`` is set
    — without it, webhook delivery can't be configured at all.
    """
    use_webhooks = user_input[CONF_USE_WEBHOOKS]
    management_token = user_input.get(CONF_APPLICATION_MANAGEMENT_TOKEN)

    if use_webhooks and not management_token:
        errors[CONF_APPLICATION_MANAGEMENT_TOKEN] = "no_management_token"
    if not use_webhooks and management_token:
        errors["base"] = "extraneous_management_token"
    if not management_token:
        user_input.pop(CONF_APPLICATION_MANAGEMENT_TOKEN, None)

    # The backup-polling toggle only meaningfully applies when webhooks
    # are configured. When the user explicitly disabled webhooks, drop
    # the value rather than persisting a dead flag in entry data.
    if not use_webhooks:
        user_input.pop(CONF_WEBHOOK_BACKUP_POLLING, None)


def _build_redirect_uri(hass: HomeAssistant) -> str | None:
    """Construct the absolute callback URL Smartcar will redirect to.

    Uses Home Assistant's :func:`get_url` helper which considers, in order
    of preference:

      * a user-configured ``external_url`` (configuration.yaml or
        Settings → System → Network),
      * the Nabu Casa Cloud remote URL (when the user has an active
        subscription),
      * other publicly-reachable URLs HA knows about.

    Internal URLs and IP-only addresses are rejected — Smartcar's redirect
    target must be a publicly reachable HTTPS URL.

    Returns:
        The fully-qualified callback URL, or ``None`` if no publicly
        reachable URL is configured.
    """
    try:
        url = get_url(
            hass,
            allow_internal=False,
            allow_ip=False,
            allow_cloud=True,
            require_ssl=True,
            require_standard_port=False,
        )
    except NoURLAvailableError:
        return None
    return f"{url.rstrip('/')}{CALLBACK_PATH}"


class SmartcarConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Smartcar V3 config flow."""

    VERSION = 1
    MINOR_VERSION = 0

    def __init__(self) -> None:
        """Initialize per-flow state."""
        self._credentials: dict[str, Any] = {}
        self._webhook_data: dict[str, Any] = {}
        self._scope_data: dict[str, Any] = {}
        self._state: str | None = None
        self._user_id: str | None = None
        self._oauth_error: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,  # noqa: ARG004
    ) -> OptionsFlow:
        """Return the options flow."""
        return SmartcarOptionsFlow()

    # ------------------------------------------------------------------ #
    # Steps                                                              #
    # ------------------------------------------------------------------ #

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First step: collect & verify the three Smartcar credentials.

        Returns:
            A form result with validation errors when credentials are
            invalid, otherwise advances to the webhooks step.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await self._test_credentials(
                    user_input[CONF_CLIENT_ID],
                    user_input[CONF_CLIENT_SECRET],
                )
            except InvalidAuthError:
                errors["base"] = "invalid_auth"
            except (ClientConnectorError, ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                self._credentials = {
                    CONF_APPLICATION_ID: user_input[CONF_APPLICATION_ID].strip(),
                    CONF_CLIENT_ID: user_input[CONF_CLIENT_ID].strip(),
                    CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET].strip(),
                }
                return await self.async_step_webhooks()

        # On reauth, pre-fill from the existing entry where possible.
        prefill: dict[str, Any] = {}
        if self.source == SOURCE_REAUTH:
            existing = self._get_reauth_entry().data
            prefill = {
                CONF_APPLICATION_ID: existing.get(CONF_APPLICATION_ID, ""),
                CONF_CLIENT_ID: existing.get(CONF_CLIENT_ID, ""),
            }

        # Show the user the redirect URI they need to register on Smartcar's
        # dashboard. Without external_url this will be a placeholder warning.
        redirect_uri = _build_redirect_uri(self.hass) or (
            "<your-home-assistant-external-url>" + CALLBACK_PATH
        )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                CREDENTIALS_SCHEMA, prefill or user_input
            ),
            errors=errors,
            last_step=False,
            description_placeholders={"redirect_url": redirect_uri},
        )

    async def _test_credentials(self, client_id: str, client_secret: str) -> None:
        """Mint a token at the IAM endpoint to verify the V3 client creds.

        Propagates whatever the token manager raises:
        :class:`InvalidAuthError` for 401/403 from Smartcar, and the various
        aiohttp ``ClientError`` subclasses for network failures.
        """
        session = async_get_clientsession(self.hass)
        manager = ClientCredentialsTokenManager(
            session, client_id.strip(), client_secret.strip()
        )
        # InvalidAuthError raised on 401/403, ClientError on network issues.
        await manager.async_get_access_token()

    async def async_step_webhooks(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: webhook configuration (optional).

        Returns:
            A form result with validation errors, or advances to the scopes
            step on valid input.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            input_copy = {**user_input}
            _validate_webhook_input(input_copy, errors)
            if not errors:
                self._webhook_data = {**input_copy}
                self._webhook_data.pop(CONF_USE_WEBHOOKS, None)
                return await self.async_step_scopes()
            user_input = input_copy

        prefill = {CONF_USE_WEBHOOKS: False} if user_input is None else user_input

        return self.async_show_form(
            step_id="webhooks",
            data_schema=self.add_suggested_values_to_schema(WEBHOOKS_SCHEMA, prefill),
            errors=errors,
            last_step=False,
        )

    async def async_step_scopes(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: select scopes to request from Connect.

        Returns:
            A form result with validation errors, or advances to the
            authorize step when at least one scope is selected.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            self._scope_data = user_input
            if self._selected_scopes:
                return await self.async_step_authorize()
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
                user_input if user_input is not None else {},
            ),
            errors=errors,
            last_step=False,
        )

    async def async_step_authorize(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 4: send the user to Smartcar Connect.

        When ``user_input`` arrives, it has been forwarded by the callback
        view and contains either ``{"userId": "...", "code": "..."}`` (happy
        path) or ``{"error": "..."}`` (Connect surfaced an error).

        On the resume we *always* return :meth:`async_external_step_done` —
        even for error cases. Returning a CREATE_ENTRY or ABORT directly
        from a resumed external step would violate the flow framework's
        state-machine contract (it must transition to EXTERNAL_STEP_DONE
        first). The next step (``async_step_finish``) consults the data we
        stashed and decides whether to create the entry or abort.

        Returns:
            An external-step result that pauses the flow until the callback
            view resumes it, or — on resume — an external-step-done signal
            that hands control to ``async_step_finish``.
        """
        if user_input is not None:
            if "error" in user_input:
                self._oauth_error = user_input["error"]
            else:
                self._user_id = user_input.get("userId")
            return self.async_external_step_done(next_step_id="finish")

        # First time through: confirm we have an external URL, generate state,
        # park it for the callback view, build the Connect URL, and hand off.
        redirect_uri = _build_redirect_uri(self.hass)
        if not redirect_uri:
            return self.async_abort(reason="external_url_required")

        # Register the view here so the very first config flow works.
        # `async_setup` only runs after the first config entry exists, which
        # is too late for the initial setup's redirect. The function is
        # idempotent so calling it again does nothing.
        async_register_view(self.hass)

        self._state = secrets.token_urlsafe(32)
        register_state(self.hass, self._state, self.flow_id)

        connect_url = self._build_connect_url(redirect_uri, self._state)
        return self.async_external_step(step_id="authorize", url=connect_url)

    def _build_connect_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self._credentials[CONF_APPLICATION_ID],
            "redirect_uri": redirect_uri,
            "scope": " ".join(self._requested_scopes),
            "mode": SMARTCAR_MODE,
            "state": state,
        }
        return f"{OAUTH2_AUTHORIZE}?{urlencode(params)}"

    async def async_step_finish(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Step 5: discover vehicles via /connections and create the entry.

        Returns:
            A create-entry result on success, or an abort result with a
            specific reason on any of the failure modes (no vehicles, auth
            failure, duplicates, cloud not connected, etc.).
        """
        # Errors deferred from async_step_authorize (resumed-external-step
        # handlers cannot abort directly).
        if self._oauth_error:
            return self.async_abort(
                reason="oauth_error",
                description_placeholders={"error": self._oauth_error},
            )
        if not self._user_id:
            return self.async_abort(reason="missing_user_id")

        assert self._user_id is not None
        assert self._credentials

        session = async_get_clientsession(self.hass)
        token_manager = ClientCredentialsTokenManager(
            session,
            self._credentials[CONF_CLIENT_ID],
            self._credentials[CONF_CLIENT_SECRET],
        )
        auth = ClientCredentialsAuthImpl(
            session, token_manager, API_HOST, self._user_id
        )

        data: dict[str, Any] = {
            **self._credentials,
            **self._webhook_data,
            "sc_user_id": self._user_id,
        }

        try:
            await populate_entry_data(data, auth)
        except EmptyVehicleListError:
            _LOGGER.exception("No vehicles returned by /connections")
            return self.async_abort(reason="no_vehicles")
        except MissingVINError:
            _LOGGER.exception("Missing vehicle VIN")
            return self.async_abort(reason="unknown")
        except InvalidAuthError:
            _LOGGER.exception("Authentication failed during /connections fetch")
            return self.async_abort(reason="invalid_auth")
        except (ClientConnectorError, ClientError, TimeoutError):
            _LOGGER.exception("Failed to fetch vehicles")
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(unique_id_from_entry_data(data))

        # Block accidental duplicate entries that would create overlapping
        # device records for the same VIN.
        other_vins = vehicle_vins_in_use(
            self.hass,
            self._get_reauth_entry() if self.source == SOURCE_REAUTH else None,
        )
        duplicate_vins = [
            details["vin"]
            for details in data.get("vehicles", {}).values()
            if details["vin"] in other_vins
        ]
        if duplicate_vins:
            return self.async_abort(
                reason="duplicate_vehicles",
                description_placeholders={"vins": ", ".join(duplicate_vins)},
            )

        if self.source == SOURCE_REAUTH:
            reauth_entry = self._get_reauth_entry()
            self._abort_if_unique_id_mismatch(
                reason="wrong_vehicles",
                description_placeholders={
                    "vins": vins_from_entry_data(reauth_entry.data)
                },
            )
            return self.async_update_reload_and_abort(
                reauth_entry, data={**reauth_entry.data, **data}
            )

        self._abort_if_unique_id_configured()

        # Generate the webhook id (Smartcar's "vehicle data callback URI"
        # is a separate URL from our OAuth callback path).
        description_placeholders: dict[str, str] = {}
        if CONF_APPLICATION_MANAGEMENT_TOKEN in data:
            try:
                webhook_id, webhook_url, cloudhook = await _get_webhook_details(
                    self.hass
                )
            except cloud.CloudNotConnected:
                return self.async_abort(reason="cloud_not_connected")
            data = {
                **data,
                CONF_WEBHOOK_ID: webhook_id,
                CONF_CLOUDHOOK: cloudhook,
            }
            description_placeholders["webhook_url"] = webhook_url

        return self.async_create_entry(
            title=DEFAULT_NAME,
            data=data,
            description_placeholders=description_placeholders,
        )

    # ------------------------------------------------------------------ #
    # Reauth                                                             #
    # ------------------------------------------------------------------ #

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Start a reauth flow.

        Returns:
            The reauth-confirm step.
        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm and re-run credential entry.

        Returns:
            Either a confirmation form, or — on confirmation — the user step
            of the regular flow which collects credentials afresh.
        """
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    @property
    def _selected_scopes(self) -> list[Scope]:
        """Return the user-selected optional scopes, sorted alphabetically."""
        return sorted(
            [
                cast("Scope", scope)
                for scope, selected in (self._scope_data or {}).items()
                if selected
            ]
        )

    @property
    def _requested_scopes(self) -> list[Scope]:
        """Return ``REQUIRED_SCOPES`` plus the user-selected optional scopes."""
        return REQUIRED_SCOPES + self._selected_scopes


class SmartcarOptionsFlow(OptionsFlow):
    """Adjust webhook settings post-setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Entry point for the options flow.

        Returns:
            The webhooks step result.
        """
        return await self.async_step_webhooks(user_input)

    async def async_step_webhooks(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow toggling webhooks and rotating the application management token.

        Returns:
            A form, abort, or create-entry result depending on whether the
            user submitted valid input.
        """
        entry_data = {**self.config_entry.data}
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}

        if user_input is not None:
            input_copy = {**user_input}
            _validate_webhook_input(input_copy, errors)
            if not errors:
                entry_data.pop(CONF_APPLICATION_MANAGEMENT_TOKEN, None)
                entry_data.update(input_copy)
                entry_data.pop(CONF_USE_WEBHOOKS, None)

        if entry_data.get(CONF_APPLICATION_MANAGEMENT_TOKEN):
            try:
                webhook_id, webhook_url, cloudhook = await _get_webhook_details(
                    self.hass, entry_data.get(CONF_WEBHOOK_ID)
                )
            except cloud.CloudNotConnected:
                return self.async_abort(reason="cloud_not_connected")
            entry_data.update({CONF_WEBHOOK_ID: webhook_id, CONF_CLOUDHOOK: cloudhook})
            description_placeholders["webhook_url"] = webhook_url
        else:
            entry_data.pop(CONF_WEBHOOK_ID, None)
            entry_data.pop(CONF_CLOUDHOOK, None)

        if user_input is not None and not errors:
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=entry_data
            )
            return self.async_create_entry(
                data={}, description_placeholders=description_placeholders
            )

        prefill = {
            CONF_USE_WEBHOOKS: bool(entry_data.get(CONF_APPLICATION_MANAGEMENT_TOKEN)),
            CONF_WEBHOOK_BACKUP_POLLING: bool(
                entry_data.get(CONF_WEBHOOK_BACKUP_POLLING)
            ),
            **{
                k: entry_data[k]
                for k in (CONF_APPLICATION_MANAGEMENT_TOKEN,)
                if k in entry_data
            },
        }

        return self.async_show_form(
            step_id="webhooks",
            data_schema=self.add_suggested_values_to_schema(
                WEBHOOKS_SCHEMA, prefill if user_input is None else user_input
            ),
            errors=errors,
            last_step=True,
            description_placeholders=description_placeholders,
        )


async def _get_webhook_details(
    hass: HomeAssistant, webhook_id: str | None = None
) -> tuple[str, str, bool]:
    """Generate (or reuse) a webhook id and resolve its public URL.

    Returns:
        A 3-tuple of ``(webhook_id, public_url, is_cloudhook)``. ``is_cloudhook``
        is ``True`` when the URL was generated via Nabu Casa Cloud.
    """
    if webhook_id is None:
        webhook_id = webhook.async_generate_id()
    url, cloudhook = await webhook_url_from_id(hass, webhook_id)
    return webhook_id, url, cloudhook


# Re-export so __init__ can call it from async_setup if needed.
__all__ = ["SmartcarConfigFlow", "SmartcarOptionsFlow", "async_register_view"]
