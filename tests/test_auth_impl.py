"""Tests for the V3 auth implementations.

The V3 auth model is structurally different from the V2 one:

  * :class:`ClientCredentialsTokenManager` mints app-level tokens at
    ``iam.smartcar.com/oauth2/token`` using the OAuth 2.0 ``client_credentials``
    grant. Tokens are cached until they near expiry, then re-minted on demand.
  * :class:`AsyncConfigEntryAuth` and :class:`ClientCredentialsAuthImpl` both
    delegate to a shared token manager and return a stored Smartcar user id
    for the ``sc-user-id`` header.

These tests use HA's managed ``ClientSession`` (via ``async_get_clientsession``)
combined with the ``aioclient_mock`` fixture. The mocker patches
``ClientSession.request`` globally, so HA's session transparently uses the
mock without needing a hand-built session that the test would have to clean
up itself.
"""

from datetime import timedelta

from aiohttp import ClientResponseError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.smartcar.auth_impl import (
    AsyncConfigEntryAuth,
    ClientCredentialsAuthImpl,
    ClientCredentialsTokenManager,
)
from custom_components.smartcar.const import IAM_TOKEN_URL
from custom_components.smartcar.errors import InvalidAuthError


async def test_token_manager_mints_token_on_first_use(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """First ``async_get_access_token`` call hits IAM and caches the result."""
    aioclient_mock.post(
        IAM_TOKEN_URL,
        json={"access_token": "iam-token-1", "expires_in": 3600},
    )

    manager = ClientCredentialsTokenManager(
        async_get_clientsession(hass), "client_id_x", "client_secret_x"
    )

    token = await manager.async_get_access_token()
    assert token == "iam-token-1"  # noqa: S105
    assert aioclient_mock.call_count == 1

    # Second call within the expiry window must NOT hit the IAM endpoint.
    token2 = await manager.async_get_access_token()
    assert token2 == "iam-token-1"
    assert aioclient_mock.call_count == 1


async def test_token_manager_refreshes_when_near_expiry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """When the cached token is near expiry, the manager mints a new one."""
    aioclient_mock.post(
        IAM_TOKEN_URL,
        json={"access_token": "iam-token-old", "expires_in": 3600},
    )
    manager = ClientCredentialsTokenManager(
        async_get_clientsession(hass), "client_id_x", "client_secret_x"
    )
    await manager.async_get_access_token()
    assert aioclient_mock.call_count == 1

    # Move the cached expiry inside the 5-minute buffer.
    manager._expires_at = dt_util.utcnow() + timedelta(seconds=10)

    aioclient_mock.clear_requests()
    aioclient_mock.post(
        IAM_TOKEN_URL,
        json={"access_token": "iam-token-new", "expires_in": 3600},
    )

    token = await manager.async_get_access_token()
    assert token == "iam-token-new"  # noqa: S105
    assert aioclient_mock.call_count == 1


async def test_token_manager_invalid_credentials_raises_invalid_auth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Smartcar 401/403 on the IAM endpoint surfaces as ``InvalidAuthError``."""
    aioclient_mock.post(IAM_TOKEN_URL, status=401)

    manager = ClientCredentialsTokenManager(
        async_get_clientsession(hass), "bad_client", "bad_secret"
    )
    with pytest.raises(InvalidAuthError):
        await manager.async_get_access_token()


async def test_token_manager_malformed_response_raises_invalid_auth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """An IAM 200 response missing ``access_token`` is treated as auth failure."""
    aioclient_mock.post(IAM_TOKEN_URL, json={"expires_in": 3600})

    manager = ClientCredentialsTokenManager(
        async_get_clientsession(hass), "client", "secret"
    )
    with pytest.raises(InvalidAuthError):
        await manager.async_get_access_token()


async def test_token_manager_other_http_errors_propagate(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Non-401/403 errors propagate as ``ClientResponseError``, not auth failure."""
    aioclient_mock.post(IAM_TOKEN_URL, status=500)

    manager = ClientCredentialsTokenManager(
        async_get_clientsession(hass), "client", "secret"
    )
    with pytest.raises(ClientResponseError):
        await manager.async_get_access_token()


async def test_token_manager_invalidate_forces_refresh(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Calling ``invalidate`` causes the next access-token call to re-fetch."""
    aioclient_mock.post(
        IAM_TOKEN_URL,
        json={"access_token": "iam-token-1", "expires_in": 3600},
    )
    manager = ClientCredentialsTokenManager(
        async_get_clientsession(hass), "client", "secret"
    )
    await manager.async_get_access_token()
    assert aioclient_mock.call_count == 1

    aioclient_mock.clear_requests()
    aioclient_mock.post(
        IAM_TOKEN_URL,
        json={"access_token": "iam-token-2", "expires_in": 3600},
    )

    manager.invalidate()
    token = await manager.async_get_access_token()
    assert token == "iam-token-2"  # noqa: S105
    assert aioclient_mock.call_count == 1


async def test_config_entry_auth_returns_token_and_user_id(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """``AsyncConfigEntryAuth`` delegates to the token manager and returns user id."""
    aioclient_mock.post(
        IAM_TOKEN_URL,
        json={"access_token": "token-via-manager", "expires_in": 3600},
    )
    session = async_get_clientsession(hass)
    manager = ClientCredentialsTokenManager(session, "c", "s")
    auth = AsyncConfigEntryAuth(session, manager, "http://test.local", "user-123")

    assert await auth.async_get_access_token() == "token-via-manager"
    assert await auth.async_get_user_id() == "user-123"


async def test_client_credentials_auth_impl_with_user_id(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """``ClientCredentialsAuthImpl`` supports re-binding to a discovered user id."""
    aioclient_mock.post(
        IAM_TOKEN_URL,
        json={"access_token": "t", "expires_in": 3600},
    )
    session = async_get_clientsession(hass)
    manager = ClientCredentialsTokenManager(session, "c", "s")

    auth = ClientCredentialsAuthImpl(session, manager, "http://test.local")
    assert await auth.async_get_user_id() is None

    rebound = auth.with_user_id("user-xyz")
    assert await rebound.async_get_user_id() == "user-xyz"
    assert await rebound.async_get_access_token() == "t"
