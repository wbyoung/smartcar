"""Test auth concrete subclasses."""

from custom_components.smartcar.auth_impl import (
    AccessTokenAuthImpl,
    AsyncConfigEntryAuth,
)

from . import MOCK_API_ENDPOINTS


async def test_config_entry_auth():
    class MockOAuth2Implementation:
        def __init__(self):
            self.client_id = "mock-id"

    class MockOAuth2Session:
        async def async_ensure_token_valid(self):
            self.token = {"access_token": "mock-token"}

    websession = None
    oauth_impl = MockOAuth2Implementation()
    oauth_session = MockOAuth2Session()
    auth = AsyncConfigEntryAuth(
        websession,
        oauth_impl,
        oauth_session,
        MOCK_API_ENDPOINTS,
    )

    assert await auth.async_get_access_token() == "mock-token"
    assert auth.version == "v2"  # based on `mock-id` not starting with `client_`


async def test_token_auth():
    websession = None
    auth = AccessTokenAuthImpl(
        websession, "mock-token", MOCK_API_ENDPOINTS, version="v3"
    )

    assert await auth.async_get_access_token() == "mock-token"
    assert auth.version == "v3"
