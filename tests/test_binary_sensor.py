"""Test binary sensors."""

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

from homeassistant.const import STATE_OFF, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartcar import binary_sensor as binary_sensor_module
from custom_components.smartcar.const import REQUIRED_SCOPES, Scope

from . import setup_integration


def test_hvac_bool_cast() -> None:
    """Test extraction of HVAC booleans from webhook signal bodies."""
    assert binary_sensor_module._hvac_bool({"value": True}) is True
    assert binary_sensor_module._hvac_bool({"value": False}) is False
    assert binary_sensor_module._hvac_bool({}) is None
    assert binary_sensor_module._hvac_bool(False) is False  # noqa: FBT003
    assert binary_sensor_module._hvac_bool(None) is None


def test_unlocked_cast() -> None:
    """Test conversion of locked values to lock binary sensor states."""
    assert binary_sensor_module._unlocked(True) is False  # noqa: FBT003
    assert binary_sensor_module._unlocked(False) is True  # noqa: FBT003
    assert binary_sensor_module._unlocked(None) is None


@pytest.mark.usefixtures("enable_all_entities")
@pytest.mark.parametrize("client_id_version", ["v3"])
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
@pytest.mark.parametrize(
    ("enabled_scopes", "expect_binary_sensor", "expect_lock"),
    [
        ([*REQUIRED_SCOPES, Scope.READ_SECURITY], True, False),
        (
            [*REQUIRED_SCOPES, Scope.READ_SECURITY, Scope.CONTROL_SECURITY],
            False,
            True,
        ),
    ],
    ids=["read_only", "read_and_control"],
)
async def test_door_lock_status(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    vehicle: AsyncMock,
    entity_registry: er.EntityRegistry,
    expect_binary_sensor: bool,
    expect_lock: bool,
) -> None:
    """Test the read-only door lock status is only used without lock control."""
    binary_sensor_id = "binary_sensor.vw_id_4_door_lock"
    lock_id = "lock.vw_id_4_door_lock"

    await setup_integration(hass, mock_config_entry)

    assert (entity_registry.async_get(binary_sensor_id) is not None) is (
        expect_binary_sensor
    )
    assert (entity_registry.async_get(lock_id) is not None) is expect_lock

    if expect_binary_sensor:
        # the fixture reports the doors as locked, which is `off` for a binary
        # sensor with the lock device class.
        state = hass.states.get(binary_sensor_id)
        assert state is not None
        assert state.state == STATE_OFF
        assert state.attributes["device_class"] == "lock"


@pytest.mark.usefixtures("enable_all_entities")
@pytest.mark.parametrize("platform", [Platform.BINARY_SENSOR])
@pytest.mark.parametrize(
    "vehicle_fixture", ["vw_id_4", "jaguar_ipace", "byd_seal", "polestar_2"]
)
@pytest.mark.parametrize(
    ("webhook_body", "webhook_headers", "expected"),
    [("all", {"sc-signature": "1234"}, {})],  # JSON fixture
    indirect=["webhook_body"],
    ids=["vehicle_state_all"],
)
async def test_webhook_update(webhook_scenario: Callable[[], Awaitable[None]]) -> None:
    await webhook_scenario()
