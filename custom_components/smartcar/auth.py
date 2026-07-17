from abc import ABC, abstractmethod
import logging

from aiohttp import ClientResponse, ClientSession

from .types import APIVersion

_LOGGER = logging.getLogger(__name__)


# note: this could be the start of allowing a separate client library to be
# designed that would be compatible with HA integrations. this is following the
# recommended design patterns for separating auth concerns from making api
# requests. this integration, however, chooses to make raw http requests
# instead of going through a library.
class AbstractAuth(ABC):
    """Abstract class to make authenticated requests."""

    def __init__(
        self,
        websession: ClientSession,
        endpoints: dict[APIVersion, str],
        *,
        version: APIVersion,
        user_id: str | None = None,
    ) -> None:
        """Initialize the auth."""
        self._websession = websession
        self._endpoints = endpoints
        self._version = version
        self._user_id = user_id

    @property
    def user_id(self) -> str | None:
        return self._user_id

    @user_id.setter
    def user_id(self, user_id: str) -> None:
        self._user_id = user_id

    @property
    def version(self) -> APIVersion:
        """API version these credentials will work for."""
        return self._version

    @abstractmethod
    async def async_get_access_token(self) -> str:
        """Return a valid access token."""

    async def request_v2(
        self,
        method: str,
        path: str,
        **kwargs,  # noqa: ANN003
    ) -> ClientResponse:
        return await self.request(method, path, version="v2", **kwargs)

    async def request_v3(
        self,
        method: str,
        path: str,
        **kwargs,  # noqa: ANN003
    ) -> ClientResponse:
        return await self.request(method, path, version="v3", **kwargs)

    async def request(
        self,
        method: str,
        path: str,
        version: APIVersion,
        **kwargs,  # noqa: ANN003
    ) -> ClientResponse:
        """Make a request.

        Returns:
            The client response.
        """
        assert version == self.version, (
            f"Cannot use {version} API with {self.version} credentials"
        )

        access_token = await self.async_get_access_token()
        headers = dict(kwargs.pop("headers", {}))
        headers["authorization"] = f"Bearer {access_token}"

        if self.user_id is not None:
            headers["sc-user-id"] = self.user_id

        _LOGGER.debug(
            "HTTP %s request %s/%s %r headers=%r",
            method,
            self._endpoints[version],
            path,
            kwargs,
            headers,
        )

        return await self._websession.request(
            method,
            f"{self._endpoints[version]}/{path}",
            **kwargs,
            headers=headers,
        )
