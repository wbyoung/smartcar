"""Test binary sensors."""

from collections.abc import Awaitable, Callable

from homeassistant.const import Platform
import pytest

from custom_components.smartcar import binary_sensor as binary_sensor_module


def test_hvac_bool_cast() -> None:
    """Test extraction of HVAC booleans from webhook signal bodies."""
    assert binary_sensor_module._hvac_bool({"value": True}) is True
    assert binary_sensor_module._hvac_bool({"value": False}) is False
    assert binary_sensor_module._hvac_bool({}) is None
    assert binary_sensor_module._hvac_bool(False) is False  # noqa: FBT003
    assert binary_sensor_module._hvac_bool(None) is None


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
