"""Concrete auth implementations for the Smartcar V3 client.

Architecture
------------
Smartcar V3 dropped per-user OAuth tokens with refresh in favour of a single
application-level access token minted via the OAuth 2.0 ``client_credentials``
grant against ``https://iam.smartcar.com/oauth2/token``. Tokens last 1 hour
and have no refresh token — when one expires you simply request another.

To scope a request to a specific user's vehicle, V3 requires the
``sc-user-id`` header on every call. We capture that user id once during the
Smartcar Connect flow (from the callback URL's ``userId`` query parameter)
and persist it in the config entry data.

This module provides:
  * :class:`ClientCredentialsTokenManager` — fetches and caches the
    application-level token, refreshing on demand.
  * :class:`AsyncConfigEntryAuth` — the runtime ``AbstractAuth``
    implementation that the coordinator/entities use.
  * :class:`ClientCredentialsAuthImpl` — bootstrap variant used during the
    config flow before any entry exists.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any, cast

from aiohttp import BasicAuth, ClientResponseError, ClientSession
from homeassistant.util import dt as dt_util

from .auth import AbstractAuth
from .const import IAM_TOKEN_URL
from .errors import InvalidAuthError

_LOGGER = logging.getLogger(__name__)

# Refresh slightly before the actual expiry so we don't race the clock on
# in-flight requests. 5 minutes of buffer against a 60-minute token leaves
# 55 minutes of useful life per fetch.
_TOKEN_EXPIRY_BUFFER = timedelta(minutes=5)


class ClientCredentialsTokenManager:
    """Caches an application-level access token and refreshes on expiry.

    Thread-safe via an ``asyncio.Lock`` so concurrent ``async_get_access_token``
    calls during a refresh result in exactly one network round-trip.
    """

    def __init__(
        self,
        websession: ClientSession,
        client_id: str,
        client_secret: str,
    ) -> None:
        """Initialize."""
        self._websession = websession
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._expires_at = None
        self._lock = asyncio.Lock()

    async def async_get_access_token(self) -> str:
        """Return a valid app-level access token, fetching/refreshing as needed."""
        async with self._lock:
            if self._token is None or self._is_expiring_soon():
                await self._fetch_token()
            assert self._token is not None
            return self._token

    def _is_expiring_soon(self) -> bool:
        if self._expires_at is None:
            return True
        return self._expires_at - dt_util.utcnow() <= _TOKEN_EXPIRY_BUFFER

    async def _fetch_token(self) -> None:
        """POST to the IAM endpoint to mint a fresh access token.

        Uses HTTP Basic Auth for client credentials (``client_secret_basic``);
        Smartcar's IAM endpoint also accepts ``client_secret_post`` per their
        docs, but Basic is the safer default since the V2-style endpoint
        required it.
        """
        _LOGGER.debug("Requesting new client_credentials token from %s", IAM_TOKEN_URL)
        auth = BasicAuth(self._client_id, self._client_secret)
        try:
            resp = await self._websession.post(
                IAM_TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=auth,
            )
            resp.raise_for_status()
            payload = await resp.json()
        except ClientResponseError as err:
            # 401 / 403 here mean the V3 client_id+secret are wrong; raise as
            # auth failure so the config flow / coordinator can react.
            if err.status in (401, 403):
                msg = f"Smartcar IAM rejected credentials: {err.status} {err.message}"
                raise InvalidAuthError(msg) from err
            raise

        access_token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if not access_token or not isinstance(expires_in, (int, float)):
            msg = "IAM response missing access_token or expires_in"
            raise InvalidAuthError(msg)

        self._token = access_token
        self._expires_at = dt_util.utcnow() + timedelta(seconds=int(expires_in))
        _LOGGER.debug(
            "Got new access token, expires at %s (%s seconds)",
            self._expires_at,
            expires_in,
        )

    def invalidate(self) -> None:
        """Force the next ``async_get_access_token`` to fetch a new token.

        Use after receiving an unexpected 401 from a vehicle API call — the
        token may have been revoked server-side ahead of its declared expiry.
        """
        self._token = None
        self._expires_at = None


class AsyncConfigEntryAuth(AbstractAuth):
    """Runtime auth backed by a :class:`ClientCredentialsTokenManager`.

    The token manager keeps the bearer token fresh in the background; this
    class just delegates and reads the stored Smartcar user id for the
    ``sc-user-id`` header.
    """

    def __init__(
        self,
        websession: ClientSession,
        token_manager: ClientCredentialsTokenManager,
        host: str,
        user_id: str | None,
    ) -> None:
        """Initialize."""
        super().__init__(websession, host)
        self._token_manager = token_manager
        self._user_id = user_id

    async def async_get_access_token(self) -> str:
        """Return a valid V3 application access token."""
        return await self._token_manager.async_get_access_token()

    async def async_get_user_id(self) -> str | None:  # noqa: RUF029
        """Return the Smartcar user id captured during Connect."""
        return self._user_id

    @property
    def token_manager(self) -> ClientCredentialsTokenManager:
        """Expose the token manager so callers can invalidate on 401."""
        return self._token_manager


class ClientCredentialsAuthImpl(AbstractAuth):
    """Auth used during the config flow before a config entry exists.

    Functionally identical to :class:`AsyncConfigEntryAuth` but instantiated
    directly from the credentials the user just typed in, rather than from a
    persisted entry. After the entry is created, the runtime swaps to the
    config-entry-backed variant.
    """

    def __init__(
        self,
        websession: ClientSession,
        token_manager: ClientCredentialsTokenManager,
        host: str,
        user_id: str | None = None,
    ) -> None:
        """Initialize."""
        super().__init__(websession, host)
        self._token_manager = token_manager
        self._user_id = user_id

    async def async_get_access_token(self) -> str:
        """Return a valid V3 application access token."""
        return await self._token_manager.async_get_access_token()

    async def async_get_user_id(self) -> str | None:  # noqa: RUF029
        """Return the user id (may be None during the first ``/connections`` call)."""
        return self._user_id

    def with_user_id(self, user_id: str) -> ClientCredentialsAuthImpl:
        """Return a copy bound to a discovered user id."""
        return ClientCredentialsAuthImpl(
            self._websession, self._token_manager, self._host, user_id
        )
