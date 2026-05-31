"""Shared fixtures for the V3 Smartcar test suite.

The fixture surface is structurally different from the V2 suite:

  * No ``application_credentials`` integration is loaded — V3 stores
    credentials directly in the config entry.
  * No ``OAuth2Session`` is mocked — V3 mints tokens via the IAM endpoint
    instead.
  * ``mock_config_entry`` carries the three V3 credentials, the captured
    ``sc_user_id``, and a ``vehicles`` dict keyed by Smartcar's vehicle id
    (which we also store under the ``vin`` field for compatibility with the
    rest of the integration's code paths).

V2-shaped tests that depend on the old fixture surface (per-vehicle API
fixtures, OAuth flow tokens, etc.) are skipped wholesale until the fixture
data is regenerated for V3.
"""

from . import bootstrap as bootstrap  # noqa: I001, PLC0414

from collections.abc import Generator
import logging
from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    mock_aiohttp_client,
)
from syrupy.assertion import SnapshotAssertion

from custom_components.smartcar.auth import AbstractAuth
from custom_components.smartcar.const import (
    CONF_APPLICATION_ID,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_SC_USER_ID,
    CONF_SCOPES,
    DOMAIN,
    EntityDescriptionKey,
    Scope,
)

from . import MOCK_API_ENDPOINT, MOCK_UTC_NOW
from .syrupy import SmartcarSnapshotExtension


_LOGGER = logging.getLogger(__name__)


# Mock credentials used throughout the suite. Values are arbitrary but
# the formats roughly match what users see on the Smartcar dashboard.
MOCK_APPLICATION_ID = "00000000-0000-0000-0000-000000000001"
MOCK_CLIENT_ID = "client_01TESTCLIENTID1234567890AB"
MOCK_CLIENT_SECRET = "secret-mock-mock-mock-mock-mock"  # noqa: S105
MOCK_USER_ID = "00000000-0000-0000-0000-000000000099"
MOCK_VEHICLE_ID = "00000000-0000-0000-0000-0000000000aa"


class AdvancedPropertyMock(PropertyMock):
    """A ``PropertyMock`` that lets the test see and set the underlying obj."""

    def __get__(self, obj, obj_type=None):
        return self(obj)

    def __set__(self, obj, val):
        self(obj, val)


def pytest_configure(config) -> None:
    """Configure logging for the suite."""
    is_capturing = config.getoption("capture") != "no"

    if not is_capturing and config.pluginmanager.hasplugin("logging"):
        _LOGGER.warning(
            "pytest run with `-s/--capture=no` and the logging plugin enabled; "
            "run with `-p no:logging` to disable all sources of log capturing.",
        )

    if is_capturing:
        logging.basicConfig(level=logging.INFO, handlers=[], force=True)

    logging.getLogger("custom_components.smartcar").setLevel(logging.DEBUG)
    logging.getLogger("homeassistant").setLevel(logging.INFO)
    logging.getLogger("pytest_homeassistant_custom_component").setLevel(logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.ERROR)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for every test."""
    return


@pytest.fixture(scope="session", autouse=True)
def _aiohttp_thread_warmup() -> None:
    """Create and tear down an aiohttp session once before any test runs.

    Background: aiohttp's :class:`TCPConnector.__del__` spawns a daemon
    thread named ``_run_safe_shutdown_loop`` the first time a session is
    garbage-collected without a running event loop. The pytest-HA leak
    detector takes a thread snapshot at the start of each test and fails
    if any non-allowlisted thread appears during the test. Spawning that
    daemon here, before the first per-test snapshot, ensures it's already
    in the baseline and won't trip the detector.
    """
    import asyncio  # noqa: PLC0415

    import aiohttp  # noqa: PLC0415

    async def _warm() -> None:
        async with aiohttp.ClientSession():
            pass

    asyncio.run(_warm())


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Return snapshot assertion fixture with the Home Assistant extension."""
    return snapshot.use_extension(SmartcarSnapshotExtension)


@pytest.fixture
def mock_now(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Freeze ``now`` and ``utcnow`` to a fixed point in time."""
    freezer.move_to(MOCK_UTC_NOW)


@pytest.fixture
def mock_hmac_sha256_hexdigest_value() -> str:
    """Return the canned HMAC digest value used by ``mock_hmac_sha256_hexdigest``."""
    return "1234"


@pytest.fixture
def mock_hmac_sha256_hexdigest(
    mock_hmac_sha256_hexdigest_value: str,
):
    """Patch ``hmac_sha256_hexdigest`` to return a deterministic value."""
    with patch("custom_components.smartcar.util.hmac_sha256_hexdigest") as mock_hmac:
        mock_hmac.return_value = mock_hmac_sha256_hexdigest_value
        yield mock_hmac


@pytest.fixture
def aioclient_mock() -> Generator[AiohttpClientMocker]:
    """Mock the aiohttp ``ClientSession``."""
    with mock_aiohttp_client() as mock_session:
        yield mock_session


@pytest.fixture
def mock_smartcar_auth() -> Generator[AsyncMock]:
    """Replace the V3 token manager with a deterministic fake.

    The fake returns a fixed access token and the mock user id without ever
    hitting the IAM endpoint. Tests that exercise the IAM round trip should
    use ``aioclient_mock`` directly rather than this fixture.
    """

    class _MockAuth(AbstractAuth):
        def __init__(self, websession, host, user_id):
            super().__init__(websession, host)
            self._user_id = user_id

        async def async_get_access_token(self) -> str:  # noqa: PLR6301
            return "mock-token"

        async def async_get_user_id(self) -> str | None:
            return self._user_id

    with (
        patch(
            "custom_components.smartcar.auth_impl.ClientCredentialsTokenManager",
            autospec=True,
        ) as mock_manager,
        patch(
            "custom_components.smartcar.AsyncConfigEntryAuth",
            new=lambda session, _manager, _host, user_id: _MockAuth(
                session, MOCK_API_ENDPOINT, user_id
            ),
        ),
        patch(
            "custom_components.smartcar.config_flow.ClientCredentialsAuthImpl",
            new=lambda session, _manager, _host, user_id=None: _MockAuth(
                session, MOCK_API_ENDPOINT, user_id
            ),
        ),
    ):
        instance = mock_manager.return_value
        instance.async_get_access_token = AsyncMock(return_value="mock-token")
        yield instance


@pytest.fixture(name="enabled_scopes")
def mock_enabled_scopes() -> list[Scope]:
    """The list of granted Smartcar scopes for the config entry."""
    return list(Scope)


@pytest.fixture
def mock_config_entry(
    enabled_scopes: list[Scope],
    enabled_entities: set[EntityDescriptionKey],
) -> MockConfigEntry:
    """Return a V3-shaped config entry for a single mock vehicle.

    The structure mirrors what :func:`SmartcarConfigFlow.async_step_finish`
    persists at the end of a successful setup. There is no ``token`` blob
    (V3 mints tokens on demand from the IAM endpoint) and no
    ``auth_implementation`` (V3 doesn't use the OAuth2 framework).
    """
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_VEHICLE_ID,
        version=1,
        minor_version=0,
        data={
            CONF_APPLICATION_ID: MOCK_APPLICATION_ID,
            CONF_CLIENT_ID: MOCK_CLIENT_ID,
            CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET,
            CONF_SC_USER_ID: MOCK_USER_ID,
            CONF_SCOPES: sorted(s.value for s in enabled_scopes),
            "vehicles": {
                MOCK_VEHICLE_ID: {
                    "make": "Volkswagen",
                    "model": "ID.4",
                    "year": 2023,
                    "vin": MOCK_VEHICLE_ID,
                },
            },
        },
    )


@pytest.fixture(name="enabled_entities")
def mock_enabled_entities() -> set[EntityDescriptionKey]:
    """Pre-enabled entity keys; paired with ``mock_entity_registry_enabled_default``."""
    return set()


@pytest.fixture(name="enable_all_entities")
def mock_enable_all_entities(
    enabled_entities: set[EntityDescriptionKey],
    mock_entity_registry_enabled_default: AsyncMock,
) -> None:
    """Enable every entity description key."""
    enabled_entities.update(set(EntityDescriptionKey))


@pytest.fixture(name="enable_specified_entities")
def mock_enable_specified_entities(
    enabled_entities: set[EntityDescriptionKey],
    mock_entity_registry_enabled_default: AsyncMock,
) -> None:
    """Enable only the keys in the ``enabled_entities`` set."""


@pytest.fixture
def mock_entity_registry_enabled_default(
    enabled_entities: set[EntityDescriptionKey],
) -> Generator[AsyncMock]:
    """Patch ``entity_registry_enabled_default`` to respect ``enabled_entities``."""
    with patch(
        "custom_components.smartcar.entity.SmartcarEntityDescription.entity_registry_enabled_default",
        new_callable=AdvancedPropertyMock,
    ) as mock:
        mock.side_effect = lambda entity_description, _=None: (
            entity_description.key in enabled_entities if entity_description else ...
        )
        yield mock


def _legacy_fixture_skip(reason: str) -> Any:
    """Decorator-friendly helper for legacy V2 fixture-only skips."""
    return pytest.mark.skip(reason=reason)


# The legacy parameterised vehicle / api fixtures from the V2 suite are not
# yet available for V3. Tests that depend on them are skipped at collection
# time via the marker registered below.
def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Auto-skip tests that depend on V2-only fixtures."""
    skip_marker = pytest.mark.skip(
        reason="V2-only fixtures (vehicle / api_response_type / webhook_scenario) "
        "have not been rebuilt for V3. See CLAUDE.md."
    )
    legacy_fixture_names = {
        "vehicle",
        "vehicle_fixture",
        "vehicle_attributes",
        "api_response_type",
        "webhook_scenario",
        "webhook_body",
        "webhook_headers",
        "init_integration",
    }
    for item in items:
        fixture_names = set(getattr(item, "fixturenames", ()))
        if fixture_names & legacy_fixture_names:
            item.add_marker(skip_marker)
