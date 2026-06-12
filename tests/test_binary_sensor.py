"""Binary-sensor entity tests for the V3 integration.

The fixture data behind these tests comes from a real Smartcar V3 webhook
payload (a VW ID.7), already processed through the integration's webhook
handler and captured from the config-entry diagnostics dump. See
``tests/fixtures/coordinator_data/vw_id7.json``.

The integration maps the ``charge-ischargingcableconnected`` signal to a
``charging_cable_plugged_in`` binary sensor, which is the only
binary-sensor signal populated in the fixture payload. The remaining
binary sensors (doors, windows, trunk, etc.) have either no signal in
the payload or have one with ``value: null`` — both render as
``unavailable``.

Note that ``charge-ischarging`` is exposed as a ``switch`` entity in V3,
not a binary sensor, so the charging state itself is covered by
``test_switch.py`` (when present).
"""

from __future__ import annotations

from typing import Any

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import load_coordinator_data


@pytest.fixture(name="vehicle_data")
def vw_id7_vehicle_data() -> dict[str, Any]:
    """Override the default vehicle metadata with the VW ID.7 fixture."""
    return {
        "make": "VOLKSWAGEN",
        "model": "ID.7",
        "year": 2025,
        "vin": "00000000-0000-0000-0000-0000000000aa",
    }


@pytest.fixture(name="coordinator_data")
def vw_id7_coordinator_data() -> dict[str, Any]:
    """Load the processed VW ID.7 signal data."""
    return load_coordinator_data("vw_id7")


_BASE = "binary_sensor.volkswagen_id_7"


@pytest.mark.usefixtures("enable_all_entities")
async def test_charging_cable_plugged_in_reflects_signal(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator_data: dict[str, Any],
    setup_with_data,
) -> None:
    """``charge-ischargingcableconnected: true`` surfaces as state ``on``."""
    await setup_with_data(mock_config_entry, coordinator_data)
    state = hass.states.get(f"{_BASE}_charging_cable_plugged_in")
    assert state is not None, "expected the plug binary sensor to exist"
    assert state.state == STATE_ON


@pytest.mark.usefixtures("enable_all_entities")
async def test_doors_windows_trunk_render_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator_data: dict[str, Any],
    setup_with_data,
) -> None:
    """Closure signals absent from the payload render as ``unavailable``."""
    await setup_with_data(mock_config_entry, coordinator_data)
    for entity_id in (
        f"{_BASE}_front_trunk",
        f"{_BASE}_rear_trunk",
        f"{_BASE}_door_front_left",
        f"{_BASE}_door_back_right",
        f"{_BASE}_window_front_left",
        f"{_BASE}_sunroof",
    ):
        state = hass.states.get(entity_id)
        assert state is not None, f"{entity_id} should be registered"
        assert state.state == STATE_UNAVAILABLE, (
            f"{entity_id} expected unavailable (no signal in payload), "
            f"got {state.state}"
        )


@pytest.mark.usefixtures("enable_all_entities")
async def test_meta_signals_render_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator_data: dict[str, Any],
    setup_with_data,
) -> None:
    """Meta signals (online, asleep, fast_charger_connected, …) are unavailable.

    The fixture payload doesn't carry any of these meta signals, so the
    entities should be discoverable but report ``unavailable``.
    """
    await setup_with_data(mock_config_entry, coordinator_data)
    for entity_id in (
        f"{_BASE}_online",
        f"{_BASE}_asleep",
        f"{_BASE}_digital_key_paired",
        f"{_BASE}_fast_charger_connected",
        f"{_BASE}_surveillance_enabled",
    ):
        state = hass.states.get(entity_id)
        assert state is not None, f"{entity_id} should be registered"
        assert state.state == STATE_UNAVAILABLE


@pytest.mark.usefixtures("enable_all_entities")
async def test_charging_cable_latched_reflects_signal(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator_data: dict[str, Any],
    setup_with_data,
) -> None:
    """``charge-ischargingcablelatched: true`` surfaces as state ``on``."""
    await setup_with_data(mock_config_entry, coordinator_data)
    state = hass.states.get(f"{_BASE}_charging_cable_latched")
    assert state is not None, "expected charging_cable_latched binary sensor to exist"
    assert state.state == STATE_ON
