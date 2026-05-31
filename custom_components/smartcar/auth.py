"""Authenticated HTTP requests against the Smartcar V3 API."""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging
from typing import Any

from aiohttp import ClientResponse, ClientSession, ClientTimeout

_LOGGER = logging.getLogger(__name__)

# All vehicle API requests go under /v3/. The host is configurable so the
# integration can be pointed at a sandbox in the future without code changes.
API_VERSION_PATH = "v3"

# Default per-request timeout. Polling and discovery calls use this; the
# command path overrides with a longer value via kwargs because V3 commands
# can return HTTP 202 with the connection held open for several minutes
# while the vehicle responds.
_DEFAULT_TIMEOUT = ClientTimeout(total=30)


class AbstractAuth(ABC):
    """Abstract base for making authenticated Smartcar V3 requests.

    Two implementations exist:
      * :class:`AsyncConfigEntryAuth` (in ``auth_impl``) for the runtime path,
        backed by a :class:`ClientCredentialsTokenManager` that mints
        application-level tokens at IAM on demand.
      * :class:`ClientCredentialsAuthImpl` for the brief bootstrap during the
        config flow, when no config entry exists yet.
    """

    def __init__(self, websession: ClientSession, host: str) -> None:
        """Initialize the auth."""
        self._websession = websession
        self._host = host

    @abstractmethod
    async def async_get_access_token(self) -> str:
        """Return a valid bearer token, refreshing if necessary."""

    @abstractmethod
    async def async_get_user_id(self) -> str | None:
        """Return the Smartcar user id used as the ``sc-user-id`` header.

        May be ``None`` during the brief bootstrap window of the config flow,
        before the Connect callback has populated it.
        """

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> ClientResponse:
        """Send an authenticated request to the Smartcar V3 API.

        The ``Authorization`` header is set from the current access token
        and the ``sc-user-id`` header is set from the stored user id (when
        available). Callers should not set these headers themselves.

        Returns:
            The ``ClientResponse`` from aiohttp. Callers are responsible for
            calling ``raise_for_status()`` and ``release()`` / ``read()`` as
            appropriate.
        """
        access_token = await self.async_get_access_token()
        user_id = await self.async_get_user_id()

        headers = dict(kwargs.pop("headers", {}))
        headers["authorization"] = f"Bearer {access_token}"
        if user_id:
            headers["sc-user-id"] = user_id

        # Apply the default total timeout if the caller hasn't provided one.
        # Callers that need longer (e.g. command POSTs that may hold the
        # connection open with a 202) pass timeout=ClientTimeout(...) in kwargs.
        kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)

        url = f"{self._host}/{API_VERSION_PATH}/{path.lstrip('/')}"

        _LOGGER.debug(
            "HTTP %s %s (sc-user-id=%s, body=%r)",
            method,
            url,
            user_id,
            kwargs.get("json"),
        )

        return await self._websession.request(method, url, headers=headers, **kwargs)
