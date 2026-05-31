"""Switch-entity tests for the V3 integration.

Smartcar V3 maps ``charge-ischarging`` to a switch (``switch.<vehicle>_charging``):
turning it on POSTs ``commands/charge/start``, turning it off POSTs
``commands/charge/stop``. The fixture data captured the vehicle at
``charge-ischarging: false`` (fully charged, cable still connected), so
the switch starts in state ``off``.

These tests verify:

  * Initial state reflects the signal value.
  * ``turn_on`` issues the ``charge/start`` command via the auth layer.
  * ``turn_off`` issues the ``charge/stop`` command.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF
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


_SWITCH = "switch.volkswagen_id_7_charging"


@pytest.mark.usefixtures("enable_all_entities")
async def test_initial_state_reflects_signal(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator_data: dict[str, Any],
    setup_with_data,
) -> None:
    """``charge-ischarging: false`` in the fixture → switch state ``off``."""
    await setup_with_data(mock_config_entry, coordinator_data)
    state = hass.states.get(_SWITCH)
    assert state is not None
    assert state.state == STATE_OFF


@pytest.mark.usefixtures("enable_all_entities")
async def test_turn_on_dispatches_charge_start(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator_data: dict[str, Any],
    setup_with_data,
) -> None:
    """Calling ``switch.turn_on`` sends a ``commands/charge/start`` POST."""
    await setup_with_data(mock_config_entry, coordinator_data)

    with patch(
        "custom_components.smartcar.entity.async_send_command",
        new=AsyncMock(return_value=True),
    ) as mock_send:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: _SWITCH},
            blocking=True,
        )

    assert mock_send.call_count == 1
    # First positional arg is the coordinator, second is the command path.
    assert mock_send.call_args.args[1] == "charge/start"


@pytest.mark.usefixtures("enable_all_entities")
async def test_turn_off_dispatches_charge_stop(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator_data: dict[str, Any],
    setup_with_data,
) -> None:
    """Calling ``switch.turn_off`` sends a ``commands/charge/stop`` POST."""
    await setup_with_data(mock_config_entry, coordinator_data)

    with patch(
        "custom_components.smartcar.entity.async_send_command",
        new=AsyncMock(return_value=True),
    ) as mock_send:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: _SWITCH},
            blocking=True,
        )

    assert mock_send.call_count == 1
    assert mock_send.call_args.args[1] == "charge/stop"
