"""Fixtures for testing."""

from . import bootstrap as bootstrap  # noqa: I001, PLC0414

from freezegun.api import FrozenDateTimeFactory

from collections.abc import Awaitable, Callable, Generator
import json
import logging
import time
from typing import Any
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

from aiohttp import ClientSession
from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.const import CONF_WEBHOOK_ID, CONTENT_TYPE_JSON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.config_entry_oauth2_flow import (
    OAuth2Session,
    LocalOAuth2Implementation,
)
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    load_json_object_fixture,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    mock_aiohttp_client,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator
from syrupy.assertion import SnapshotAssertion
from .syrupy import SmartcarSnapshotExtension
from . import MOCK_UTC_NOW
from custom_components.smartcar import util
from custom_components.smartcar.types import APIVersion

from custom_components.smartcar.auth import AbstractAuth
from custom_components.smartcar.const import (
    CONF_APPLICATION_MANAGEMENT_TOKEN,
    DOMAIN,
    EntityDescriptionKey,
    Scope,
)

from . import (
    MOCK_API_ENDPOINTS,
    aioclient_mock_append_vehicle_request,
    setup_added_integration,
    setup_integration,
)


class AdvancedPropertyMock(PropertyMock):
    def __get__(self, obj, obj_type=None):
        return self(obj)

    def __set__(self, obj, val):
        self(obj, val)


_LOGGER = logging.getLogger(__name__)


def pytest_configure(config) -> None:
    is_capturing = config.getoption("capture") != "no"

    if not is_capturing and config.pluginmanager.hasplugin("logging"):
        _LOGGER.warning(
            "pytest run with `-s/--capture=no` and the logging plugin enabled "
            "run with `-p no:logging` to disable all sources of log capturing.",
        )

    # `pytest_homeassistant_custom_component` calls `logging.basicConfig` which
    # creates the `stderr` stream handler. in most cases that will result in
    # logs being duplicated, reported in the "stderr" and "logging" capture
    # sections. force reconfiguration, removing handlers when not running with
    # the `-s/--capture=no` flag.
    if is_capturing:
        logging.basicConfig(level=logging.INFO, handlers=[], force=True)

    logging.getLogger("custom_components.smartcar").setLevel(logging.DEBUG)
    logging.getLogger("homeassistant").setLevel(logging.INFO)
    logging.getLogger("pytest_homeassistant_custom_component").setLevel(logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.ERROR)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    return


@pytest.fixture(autouse=True)
def auto_shorten_retry_delays() -> Generator[Mock]:
    """Shorten the default retry delay values."""

    original = util.async_request_with_retry

    async def replacement(
        request_fn,
        **kwargs,  # noqa: ANN003
    ):
        if "base_delay" not in kwargs:
            kwargs["base_delay"] = 0.01
        if "max_delay" not in kwargs:
            kwargs["max_delay"] = 1
        return await original(request_fn, **kwargs)

    with patch(
        "custom_components.smartcar.util.async_request_with_retry"
    ) as mock_request:
        mock_request.side_effect = replacement
        yield mock_request


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Return snapshot assertion fixture with the Home Assistant extension."""
    return snapshot.use_extension(SmartcarSnapshotExtension)


@pytest.fixture
def mock_now(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
):
    """Return a mock now & utcnow datetime."""
    freezer.move_to(MOCK_UTC_NOW)


@pytest.fixture
def mock_hmac_sha256_hexdigest_value() -> str:
    return "1234"


@pytest.fixture
def mock_hmac_sha256_hexdigest(
    mock_hmac_sha256_hexdigest_value: str,
) -> Generator[Mock]:
    """Fixture to mock HMAC digests."""
    with patch("custom_components.smartcar.util.hmac_sha256_hexdigest") as mock_hmac:
        mock_hmac.return_value = mock_hmac_sha256_hexdigest_value
        yield mock_hmac


@pytest.fixture
def aioclient_mock() -> Generator[AiohttpClientMocker]:
    """Fixture to mock aioclient calls."""
    with mock_aiohttp_client() as mock_session:
        yield mock_session


@pytest.fixture
def mock_smartcar_auth(
    aioclient_mock: AiohttpClientMocker,
) -> Generator[AsyncMock]:
    """Mock a Smartcar auth."""

    class MockAuth(AbstractAuth):
        def __init__(
            self,
            websession: ClientSession,
            implementation: LocalOAuth2Implementation = None,
            oauth_session: OAuth2Session = None,
            *,
            version: APIVersion,
            user_id: str | None = None,
        ) -> None:
            super().__init__(
                websession,
                MOCK_API_ENDPOINTS,
                version=version,
                user_id=user_id,
            )
            self._oauth_impl = implementation
            self._oauth_session = oauth_session

        async def async_get_access_token(self) -> str:
            if self._oauth_session:
                await self._oauth_session.async_ensure_token_valid()
            return "mock-token"

    with (
        patch(
            "custom_components.smartcar.auth.AbstractAuth", autospec=True
        ) as mock_auth,
        patch(
            "custom_components.smartcar.AsyncConfigEntryAuth",
            new=lambda session, impl, oauth, _endpoint, **kwargs: MockAuth(
                session,
                impl,
                oauth,
                version=util.api_version_for_client_id(impl.client_id),
                **kwargs,
            ),
        ),
        patch(
            "custom_components.smartcar.AccessTokenAuthImpl",
            new=lambda session, *_args, **kwargs: MockAuth(session, **kwargs),
        ),
        patch(
            "custom_components.smartcar.config_flow.AccessTokenAuthImpl",
            new=lambda session, *_args, **kwargs: MockAuth(session, **kwargs),
        ),
    ):
        yield mock_auth.return_value


@pytest.fixture(autouse=True)
async def setup_credentials(
    request: pytest.FixtureRequest,
    hass: HomeAssistant,
    client_id_version: APIVersion,
) -> None:
    """Fixture to setup credentials."""
    assert await async_setup_component(hass, "application_credentials", {})

    client_id = None
    if client_id_version == "v2":
        client_id = "mock-id"
    else:
        assert client_id_version == "v3"
        client_id = "client_mock-id"

    if "no_credentials" in request.keywords:
        pass
    else:
        await async_import_client_credential(
            hass,
            DOMAIN,
            ClientCredential(client_id, "mock-secret"),
            DOMAIN,
        )


@pytest.fixture(name="api_response_type")
def mock_api_response_type() -> str:
    """Fixture to define the API response fixture to use."""
    return "ok"


@pytest.fixture(name="client_id_version")
def mock_client_id_version() -> APIVersion:
    """Fixture to define the client id version to use."""
    return "v2"


@pytest.fixture(name="enabled_scopes")
def mock_enabled_scopes() -> list[Scope]:
    """Fixture to define the scopes to use."""
    return list(Scope)


@pytest.fixture(params=["vw_id_4", "unknown_make"])
def vehicle_fixture(request: pytest.FixtureRequest) -> str:
    """Return every vehicle."""
    return str(request.param)


@pytest.fixture
def vehicle_attributes(vehicle_fixture: str) -> dict:
    """Return a specific vehicle's attributes."""
    return dict(load_json_object_fixture(f"vehicles/{vehicle_fixture}.json", DOMAIN))


@pytest.fixture
def vehicle(
    mock_smartcar_auth: AsyncMock,
    aioclient_mock: AiohttpClientMocker,
    api_response_type: str,
    vehicle_fixture: str,
    vehicle_attributes: dict,
    client_id_version: APIVersion,
) -> dict:
    """Return a specific vehicle."""

    http_calls = aioclient_mock_append_vehicle_request(
        aioclient_mock,
        api_response_type,
        vehicle_fixture,
        vehicle_attributes,
        client_id_version,
    )

    return dict(vehicle_attributes, _api=http_calls)


@pytest.fixture(name="expires_at")
def mock_expires_at() -> int:
    """Fixture to set the oauth token expiration time."""
    return int(time.time()) + 3600


@pytest.fixture
def mock_config_entry(
    expires_at: int,
    vehicle_attributes: dict,
    enabled_scopes: list[Scope],
    enabled_entities: set[EntityDescriptionKey],
) -> MockConfigEntry:
    """Return the default mocked config entry for a single vehicle."""
    vehicle = dict(vehicle_attributes)
    vehicle_id = vehicle.pop("id")
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=vehicle_id,
        version=2,
        minor_version=0,
        data={
            "auth_implementation": DOMAIN,
            "token": {
                "access_token": "mock-access-token",
                "refresh_token": "mock-refresh-token",
                "expires_at": expires_at,
                "scopes": " ".join(enabled_scopes),
                "access_tier": 0,
                "installed_app_id": "2d474f47-bab5-4438-9d37-478148b9d073",
            },
            "vehicles": {
                vehicle_id: vehicle,
            },
        },
    )


@pytest.fixture(name="enabled_entities")
def mock_enabled_entities() -> set[EntityDescriptionKey]:
    """Fixture to pre-enable entities.

    To use, pair with the `mock_entity_registry_enabled_default` fixture and
    extend the list prior to setting up the config entry.
    """
    return set()


@pytest.fixture(name="enable_all_entities")
def mock_enable_all_entities(
    enabled_entities: set[EntityDescriptionKey],
    mock_entity_registry_enabled_default: AsyncMock,
) -> None:
    """Fixture to pre-enable all entity entities."""

    enabled_entities.update(set(EntityDescriptionKey))


@pytest.fixture(name="enable_specified_entities")
def mock_enable_specified_entities(
    enabled_entities: set[EntityDescriptionKey],
    mock_entity_registry_enabled_default: AsyncMock,
) -> None:
    """Fixture to pre-enable entities specified in `enabled_entities` fixture."""


@pytest.fixture
def mock_entity_registry_enabled_default(
    enabled_entities: list[str],
) -> Generator[AsyncMock]:
    with patch(
        "custom_components.smartcar.entity.SmartcarEntityDescription.entity_registry_enabled_default",
        new_callable=AdvancedPropertyMock,
    ) as mock:
        mock.side_effect = lambda entity_description, _=None: (
            entity_description.key in enabled_entities if entity_description else ...
        )
        yield mock


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_smartcar_auth: AsyncMock,
) -> MockConfigEntry:
    """Set up the Smartcar integration for testing."""
    await setup_integration(hass, mock_config_entry)

    return mock_config_entry


@pytest.fixture
def webhook_body(request, vehicle_fixture: str):
    if isinstance(request.param, str):
        return json.dumps(
            dict(
                load_json_object_fixture(
                    f"webhooks/{vehicle_fixture}_{request.param}.json", DOMAIN
                )
            )
        )
    if isinstance(request.param, bytes):
        return request.param
    return json.dumps(request.param)


@pytest.fixture
def webhook_scenario(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_hmac_sha256_hexdigest: Mock,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
    platform: str,
    vehicle_fixture: str,
    vehicle_attributes: dict,
    client_id_version: APIVersion,
    webhook_body: str,
    webhook_headers: dict[str, Any],
    expected: dict[str, Any],
    mock_now: Any,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    caplog: pytest.LogCaptureFixture,
) -> Callable[[], Awaitable[None]]:
    async def run_scenario():
        mock_config_entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(
            mock_config_entry,
            data={
                **mock_config_entry.data,
                CONF_WEBHOOK_ID: "smartcar_test",
                CONF_APPLICATION_MANAGEMENT_TOKEN: "test_amt",
            },
        )

        expected_calls = 0
        expected_response = expected.get("response", "")
        expected_response_status = expected.get("response_status", 204)
        expected_reauth_calls = expected.get("reauth_calls", 0)
        expected_log_messages = expected.get("log_messages", [])

        with patch("custom_components.smartcar.PLATFORMS", [platform]):
            await setup_added_integration(hass, mock_config_entry)

        # no requests should have been made during setup when webhooks are enabled
        # because this automatically disables polling.
        assert aioclient_mock.call_count == expected_calls

        with patch(
            "homeassistant.config_entries.ConfigEntry.async_start_reauth"
        ) as mock_start_reauth:
            client = await hass_client()
            resp = await client.post(
                "/api/webhook/smartcar_test",
                data=webhook_body,
                headers={
                    "content-type": CONTENT_TYPE_JSON,
                    **webhook_headers,
                },
            )
            assert resp.status == expected_response_status
            assert (
                await (
                    resp.json()
                    if resp.content_type == "application/json"
                    else resp.text()
                )
                == expected_response
            )
            await hass.async_block_till_done()

        # still no calls since webhooks will update from the data it received
        assert aioclient_mock.call_count == expected_calls
        assert mock_start_reauth.call_count == expected_reauth_calls

        device_id = (
            vehicle_attributes["vin"]
            if client_id_version == "v2"
            else vehicle_attributes["id"]
        )
        device = device_registry.async_get_device({(DOMAIN, device_id)})
        entities = entity_registry.entities.get_entries_for_device_id(device.id)

        for entity in entities:
            assert hass.states.get(entity.entity_id) == snapshot(name=entity.entity_id)

        for expected_log_message in expected_log_messages:
            assert expected_log_message in caplog.text

    return run_scenario
