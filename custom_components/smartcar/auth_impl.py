from typing import cast

from aiohttp import ClientSession
from homeassistant.helpers.config_entry_oauth2_flow import (
    LocalOAuth2Implementation,
    OAuth2Session,
)

from .auth import AbstractAuth
from .types import APIVersion
from .util import api_version_for_client_id


class AsyncConfigEntryAuth(AbstractAuth):
    """Provide Smartcar authentication tied to an OAuth2 based config entry."""

    def __init__(
        self,
        websession: ClientSession,
        implementation: LocalOAuth2Implementation,
        oauth_session: OAuth2Session,
        endpoints: dict[APIVersion, str],
        *,
        user_id: str | None = None,
    ) -> None:
        """Initialize Smartcar auth."""
        super().__init__(
            websession,
            endpoints,
            version=api_version_for_client_id(implementation.client_id),
            user_id=user_id,
        )
        self._oauth_impl = implementation
        self._oauth_session = oauth_session

    async def async_get_access_token(self) -> str:
        """Return a valid access token for Smartcar API."""
        await self._oauth_session.async_ensure_token_valid()
        return cast("str", self._oauth_session.token["access_token"])


class AccessTokenAuthImpl(AbstractAuth):
    """Authentication implementation used during config flow, without refresh.

    This exists to allow the config flow to use the API before it has fully
    created a config entry required by OAuth2Session. This does not support
    refreshing tokens, which is fine since it should have been just created.
    """

    def __init__(
        self,
        websession: ClientSession,
        access_token: str,
        endpoints: dict[APIVersion, str],
        *,
        version: APIVersion,
        user_id: str | None = None,
    ) -> None:
        """Initialize Smartcar auth with pre-defined access token."""
        super().__init__(websession, endpoints, version=version, user_id=user_id)
        self._access_token = access_token

    async def async_get_access_token(self) -> str:
        """Return the access token."""
        return self._access_token
