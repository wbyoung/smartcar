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

from custom_components.smartcar.auth_impl import (
    AsyncConfigEntryAuth,
    ClientCredentialsAuthImpl,
    ClientCredentialsTokenManager,
)
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

from . import MOCK_UTC_NOW
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


@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    """Allow timers from HA-core's legacy ``device_tracker`` to linger.

    The ``device_tracker`` platform schedules a 5-second interval timer
    (``DeviceTracker.async_update_stale``) inside ``LegacyDeviceTracker``
    that isn't reliably cancelled at test teardown. It's an HA-core
    concern, not the integration's, and flipping the pytest-HA leak
    detector from a fail to a warning is the documented escape hatch.

    Returns:
        ``True`` to tell pytest-HA the suite expects lingering timers.
    """
    return True


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
    """Bypass the IAM round-trip by patching ``async_get_access_token``.

    The patches target *methods on the existing class objects* rather than
    replacing the classes themselves. Replacing the class via
    ``patch("...ClientCredentialsTokenManager", autospec=True)`` is unsafe
    here because pytest-homeassistant-custom-component can re-import the
    integration during another test's setup, and config_flow's
    ``from .auth_impl import ClientCredentialsTokenManager`` would then
    rebind to the active MagicMock. That binding survives the patch
    unwinding in ``sys.modules`` and breaks subsequent tests that try to
    use the real class. Patching the method keeps the class identity
    stable while still short-circuiting the network call.
    """
    with (
        patch.object(
            ClientCredentialsTokenManager,
            "async_get_access_token",
            new_callable=AsyncMock,
            return_value="mock-token",
        ) as mock_token,
        patch.object(
            AsyncConfigEntryAuth,
            "async_get_access_token",
            new_callable=AsyncMock,
            return_value="mock-token",
        ),
        patch.object(
            ClientCredentialsAuthImpl,
            "async_get_access_token",
            new_callable=AsyncMock,
            return_value="mock-token",
        ),
    ):
        yield mock_token


@pytest.fixture(name="enabled_scopes")
def mock_enabled_scopes() -> list[Scope]:
    """The list of granted Smartcar scopes for the config entry."""
    return list(Scope)


@pytest.fixture(name="vehicle_data")
def mock_vehicle_data() -> dict[str, Any]:
    """Default vehicle metadata for ``mock_config_entry``.

    Tests that need a specific vehicle should override this fixture.
    """
    return {
        "make": "Volkswagen",
        "model": "ID.4",
        "year": 2023,
        "vin": MOCK_VEHICLE_ID,
    }


@pytest.fixture
def mock_config_entry(
    enabled_scopes: list[Scope],
    enabled_entities: set[EntityDescriptionKey],
    vehicle_data: dict[str, Any],
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
            "vehicles": {MOCK_VEHICLE_ID: vehicle_data},
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


@pytest.fixture
def setup_with_data(
    hass: HomeAssistant,
    mock_smartcar_auth: AsyncMock,
):
    """Return an async helper that sets up the integration with canned coordinator data.

    Patches :meth:`SmartcarVehicleCoordinator._async_update_data` to return
    a caller-supplied dict, then runs ``async_setup_entry`` end-to-end so
    entities are added to ``hass`` with the canned state already loaded.

    Use this in tests that want to exercise the entity layer (sensor,
    binary_sensor, lock, switch, diagnostics) without paying the cost of
    standing up an HTTP mock for the V3 ``/signals`` endpoint. The
    coordinator's first refresh runs as part of setup and pulls from the
    patched method.
    """
    from .__init__ import setup_integration  # noqa: PLC0415

    async def _run(
        entry: MockConfigEntry, coordinator_data: dict[str, Any]
    ) -> MockConfigEntry:
        with patch(
            "custom_components.smartcar.coordinator."
            "SmartcarVehicleCoordinator._async_update_data",
            return_value=coordinator_data,
        ):
            await setup_integration(hass, entry)
        return entry

    return _run
