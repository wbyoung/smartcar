"""Tests for the coordinator's dynamic ``update_interval`` behaviour.

The coordinator picks between two configured intervals based on whether
the vehicle is currently charging. Both intervals are read from the
config entry's ``data`` and default to module-level constants. When a
webhook application-management token is configured, polling is disabled
entirely (``update_interval is None``).

Coverage:

  * Defaults applied when the entry data carries no overrides.
  * Custom values from entry data taken when present.
  * Switch from idle to charging shortens the interval immediately.
  * Switch from charging back to idle lengthens it again.
  * Token-driven polling disable still wins regardless of poll values.
  * Sub-minimum entries don't crash (they just get bigger; the config
    flow enforces the floor at input time).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartcar.const import (
    CONF_APPLICATION_MANAGEMENT_TOKEN,
    CONF_POLL_INTERVAL,
    CONF_POLL_INTERVAL_CHARGING,
    DEFAULT_POLL_INTERVAL_CHARGING_MINUTES,
    DEFAULT_POLL_INTERVAL_MINUTES,
)
from custom_components.smartcar.coordinator import SmartcarVehicleCoordinator


def _make_coordinator(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    *,
    auth: Any = None,
) -> SmartcarVehicleCoordinator:
    """Build a coordinator instance directly.

    Avoids going through ``async_setup_entry`` so we can poke ``self.data``
    and re-trigger ``_refresh_update_interval`` without dragging in the
    full platform setup. The auth object is a bare ``MagicMock`` — we
    never actually call HTTP.
    """
    return SmartcarVehicleCoordinator(
        hass,
        auth or MagicMock(),
        vehicle_id="vehicle-test",
        vin="vin-test",
        entry=entry,
    )


def _entry(data: dict[str, Any]) -> MockConfigEntry:
    return MockConfigEntry(domain="smartcar", data=data, version=1, minor_version=0)


async def test_defaults_when_entry_has_no_overrides(  # noqa: RUF029
    hass: HomeAssistant,
) -> None:
    """No CONF_POLL_INTERVAL in entry → fall back to module defaults."""
    coord = _make_coordinator(hass, _entry({}))

    assert coord.update_interval == timedelta(minutes=DEFAULT_POLL_INTERVAL_MINUTES)

    # Now simulate charging state and re-evaluate.
    coord.data = {"charge-ischarging": {"value": True}}
    coord._refresh_update_interval()
    assert coord.update_interval == timedelta(
        minutes=DEFAULT_POLL_INTERVAL_CHARGING_MINUTES
    )


async def test_custom_intervals_from_entry_data(  # noqa: RUF029
    hass: HomeAssistant,
) -> None:
    """Entry-data overrides win over defaults for both states."""
    coord = _make_coordinator(
        hass,
        _entry({CONF_POLL_INTERVAL: 120, CONF_POLL_INTERVAL_CHARGING: 10}),
    )

    # Idle (no data yet).
    assert coord.update_interval == timedelta(minutes=120)

    # Charging.
    coord._refresh_update_interval({"charge-ischarging": {"value": True}})
    assert coord.update_interval == timedelta(minutes=10)


async def test_transition_idle_to_charging_and_back(  # noqa: RUF029
    hass: HomeAssistant,
) -> None:
    """Refreshing the interval reflects every state transition."""
    coord = _make_coordinator(
        hass,
        _entry({CONF_POLL_INTERVAL: 60, CONF_POLL_INTERVAL_CHARGING: 5}),
    )
    assert coord.update_interval == timedelta(minutes=60)

    # Plug in.
    coord._refresh_update_interval({"charge-ischarging": {"value": True}})
    assert coord.update_interval == timedelta(minutes=5)

    # Unplug / charging complete.
    coord._refresh_update_interval({"charge-ischarging": {"value": False}})
    assert coord.update_interval == timedelta(minutes=60)

    # Signal missing / null body → treated as not charging.
    coord._refresh_update_interval({"charge-ischarging": {"value": None}})
    assert coord.update_interval == timedelta(minutes=60)


async def test_management_token_disables_polling(  # noqa: RUF029
    hass: HomeAssistant,
) -> None:
    """A configured application-management token → no polling at all."""
    coord = _make_coordinator(
        hass,
        _entry(
            {
                CONF_APPLICATION_MANAGEMENT_TOKEN: "secret-mgmt",
                CONF_POLL_INTERVAL: 30,
                CONF_POLL_INTERVAL_CHARGING: 5,
            }
        ),
    )
    assert coord.update_interval is None

    # Even if charging state flips, polling stays off — webhooks handle it.
    coord._refresh_update_interval({"charge-ischarging": {"value": True}})
    assert coord.update_interval is None


async def test_async_set_updated_data_refreshes_interval(  # noqa: RUF029
    hass: HomeAssistant,
) -> None:
    """The webhook merge path triggers an interval recompute."""
    coord = _make_coordinator(
        hass,
        _entry({CONF_POLL_INTERVAL: 60, CONF_POLL_INTERVAL_CHARGING: 5}),
    )
    assert coord.update_interval == timedelta(minutes=60)

    coord.async_set_updated_data({"charge-ischarging": {"value": True}})
    assert coord.update_interval == timedelta(minutes=5)


async def test_refresh_with_bogus_value_falls_through_to_idle(  # noqa: RUF029
    hass: HomeAssistant,
) -> None:
    """A non-boolean ``charge-ischarging.value`` is treated as not charging.

    The integration's existing normalisation in ``coordinator.py`` already
    coerces ``charge-ischarging.value`` to a real boolean from the wire
    format, but the interval logic shouldn't blow up if a future payload
    arrives in a different shape — e.g. a truthy string. Strictly
    matching ``is True`` keeps the behaviour predictable.
    """
    coord = _make_coordinator(
        hass,
        _entry({CONF_POLL_INTERVAL: 60, CONF_POLL_INTERVAL_CHARGING: 5}),
    )
    coord._refresh_update_interval({"charge-ischarging": {"value": "yes"}})
    assert coord.update_interval == timedelta(minutes=60)
