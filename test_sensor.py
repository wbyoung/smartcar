"""Sensor-entity tests for the V3 integration.

The fixture data behind these tests comes from a real Smartcar V3 webhook
payload (a VW ID.7), already processed through the integration's webhook
handler and captured from the config-entry diagnostics dump. See
``tests/fixtures/coordinator_data/vw_id7.json``.

Expected entity states from the captured payload:

  * ``sensor.volkswagen_id_7_battery`` → ``80`` (% — the integration
    stores stateofcharge normalised to 0..1 and re-scales to 0..100 for
    display).
  * ``sensor.volkswagen_id_7_range`` → ``472`` (km).
  * ``sensor.volkswagen_id_7_odometer`` → ``16342`` (km).
  * ``sensor.volkswagen_id_7_charging_status`` → ``FULLY_CHARGED``.
  * ``sensor.volkswagen_id_7_charging_power`` → ``0`` (watts).
  * ``sensor.volkswagen_id_7_time_to_complete`` → ``0``.

Signals with ``status: ERROR`` (``charge-chargerate`` here, with
``NOT_CHARGING`` as the error code) render the corresponding entity as
``unavailable``, *not* ``unknown``. Same for signals missing from the
payload entirely. Both are exercised below.
"""

from __future__ import annotations

from typing import Any

from homeassistant.const import STATE_UNAVAILABLE
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


_BASE = "sensor.volkswagen_id_7"


@pytest.mark.usefixtures("enable_all_entities")
async def test_populated_signals_surface_on_their_sensors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator_data: dict[str, Any],
    setup_with_data,
) -> None:
    """Every populated signal in the fixture maps to its expected sensor state."""
    await setup_with_data(mock_config_entry, coordinator_data)

    cases = {
        f"{_BASE}_battery": "80",
        f"{_BASE}_range": "472",
        f"{_BASE}_odometer": "16342",
        f"{_BASE}_charging_status": "FULLY_CHARGED",
        f"{_BASE}_charging_power": "0",
        f"{_BASE}_time_to_complete": "0",
    }
    for entity_id, expected in cases.items():
        state = hass.states.get(entity_id)
        assert state is not None, f"{entity_id} was not created"
        assert state.state == expected, (
            f"{entity_id} expected {expected!r}, got {state.state!r}"
        )


@pytest.mark.usefixtures("enable_all_entities")
async def test_error_status_signal_renders_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator_data: dict[str, Any],
    setup_with_data,
) -> None:
    """``charge-chargerate`` arrived with ``status: ERROR`` → ``unavailable``.

    The webhook payload contains this signal but with ``status.value:
    ERROR`` and ``error.code: NOT_CHARGING``. The coordinator stores
    ``value: None`` and the sensor reports ``unavailable``.
    """
    await setup_with_data(mock_config_entry, coordinator_data)
    state = hass.states.get(f"{_BASE}_charge_rate")
    assert state is not None
    assert state.state == STATE_UNAVAILABLE


@pytest.mark.usefixtures("enable_all_entities")
async def test_signals_absent_from_payload_render_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator_data: dict[str, Any],
    setup_with_data,
) -> None:
    """Sensors whose backing signal isn't in the payload show ``unavailable``.

    Engine oil, fuel level, tire pressure, low-voltage battery, gear
    state, etc. don't apply to a fully-electric VW ID.7. The corresponding
    entities should still be discoverable when ``enable_all_entities``
    is in effect, but their state must be ``unavailable``.
    """
    await setup_with_data(mock_config_entry, coordinator_data)
    for entity_id in (
        f"{_BASE}_engine_oil_life",
        f"{_BASE}_fuel",
        f"{_BASE}_fuel_percent",
        f"{_BASE}_fuel_range",
        f"{_BASE}_tire_pressure_front_left",
        f"{_BASE}_tire_pressure_back_right",
        f"{_BASE}_low_voltage_battery",
        f"{_BASE}_gear_state",
        f"{_BASE}_battery_capacity",
    ):
        state = hass.states.get(entity_id)
        assert state is not None, f"{entity_id} was not created"
        assert state.state == STATE_UNAVAILABLE, (
            f"{entity_id} expected unavailable (signal not in payload), "
            f"got {state.state!r}"
        )


@pytest.mark.usefixtures("enable_all_entities")
async def test_last_polled_sensor_renders_unknown_when_no_poll_yet(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator_data: dict[str, Any],
    setup_with_data,
) -> None:
    """The ``last_polled`` sensor exists and is ``unknown`` until a poll succeeds.

    ``setup_with_data`` patches the coordinator's ``_async_update_data``
    method so the integration's setup-time first refresh never executes
    the real HTTP path — which means ``last_poll_time`` is never set,
    even though entity state gets populated. The sensor should
    correctly reflect that no polls have happened yet.
    """
    await setup_with_data(mock_config_entry, coordinator_data)
    state = hass.states.get(f"{_BASE}_last_polled")
    assert state is not None, "expected a last_polled sensor on the vehicle device"
    assert state.state == "unknown"


@pytest.mark.usefixtures("enable_all_entities")
async def test_last_polled_sensor_updates_when_coordinator_polls(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator_data: dict[str, Any],
    setup_with_data,
) -> None:
    """When the coordinator's ``last_poll_time`` updates, the sensor reflects it."""
    from datetime import UTC, datetime  # noqa: PLC0415

    await setup_with_data(mock_config_entry, coordinator_data)

    # Find the coordinator and stamp the last_poll_time directly, then
    # tell HA the coordinator data changed so entity state refreshes.
    coordinator = mock_config_entry.runtime_data.coordinators[
        "00000000-0000-0000-0000-0000000000aa"
    ]
    stamp = datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC)
    coordinator.last_poll_time = stamp
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    state = hass.states.get(f"{_BASE}_last_polled")
    assert state is not None
    # HA serialises TIMESTAMP sensors as ISO-8601 UTC strings.
    assert state.state == stamp.isoformat()
