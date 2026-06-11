"""Tests for the coordinator's ``update_interval`` selection.

Polling intervals are now fixed constants — only the
``CONF_WEBHOOK_BACKUP_POLLING`` boolean influences behaviour when webhooks
are configured. The selection logic:

  * No webhooks (always poll):
      * idle → ``POLL_INTERVAL_MINUTES`` (6 h)
      * charging → ``POLL_INTERVAL_CHARGING_MINUTES`` (15 min)
  * Webhooks + backup polling toggle off (default) → ``None`` (no polling)
  * Webhooks + backup polling toggle on:
      * idle → ``POLL_INTERVAL_MINUTES`` (now 1 h — same as the no-webhooks idle cadence)
      * charging → ``POLL_INTERVAL_CHARGING_MINUTES`` (15 min)
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartcar.const import (
    CONF_APPLICATION_MANAGEMENT_TOKEN,
    CONF_WEBHOOK_BACKUP_POLLING,
    POLL_INTERVAL_CHARGING_MINUTES,
    POLL_INTERVAL_MINUTES,
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


async def test_no_webhooks_idle_uses_fixed_interval(  # noqa: RUF029
    hass: HomeAssistant,
) -> None:
    """Without webhooks the idle cadence is the fixed 6 h."""
    coord = _make_coordinator(hass, _entry({}))
    assert coord.update_interval == timedelta(minutes=POLL_INTERVAL_MINUTES)


async def test_no_webhooks_charging_uses_fixed_interval(  # noqa: RUF029
    hass: HomeAssistant,
) -> None:
    """Without webhooks the charging cadence is the fixed 15 min."""
    coord = _make_coordinator(hass, _entry({}))
    coord._refresh_update_interval({"charge-ischarging": {"value": True}})
    assert coord.update_interval == timedelta(minutes=POLL_INTERVAL_CHARGING_MINUTES)


async def test_no_webhooks_transitions(hass: HomeAssistant) -> None:  # noqa: RUF029
    """Idle ↔ charging transitions update the interval each time."""
    coord = _make_coordinator(hass, _entry({}))
    assert coord.update_interval == timedelta(minutes=POLL_INTERVAL_MINUTES)

    coord._refresh_update_interval({"charge-ischarging": {"value": True}})
    assert coord.update_interval == timedelta(minutes=POLL_INTERVAL_CHARGING_MINUTES)

    coord._refresh_update_interval({"charge-ischarging": {"value": False}})
    assert coord.update_interval == timedelta(minutes=POLL_INTERVAL_MINUTES)

    # Null/missing value also falls through to idle.
    coord._refresh_update_interval({"charge-ischarging": {"value": None}})
    assert coord.update_interval == timedelta(minutes=POLL_INTERVAL_MINUTES)


async def test_webhooks_default_disables_polling(  # noqa: RUF029
    hass: HomeAssistant,
) -> None:
    """Webhooks configured + backup toggle absent (default off) → no polling."""
    coord = _make_coordinator(
        hass,
        _entry({CONF_APPLICATION_MANAGEMENT_TOKEN: "secret-mgmt"}),
    )
    assert coord.update_interval is None

    # Charging doesn't override — the toggle says "no polling at all".
    coord._refresh_update_interval({"charge-ischarging": {"value": True}})
    assert coord.update_interval is None


async def test_webhooks_with_backup_toggle_on_idle(  # noqa: RUF029
    hass: HomeAssistant,
) -> None:
    """Webhooks + backup toggle on → idle uses the 1 h backup cadence."""
    coord = _make_coordinator(
        hass,
        _entry(
            {
                CONF_APPLICATION_MANAGEMENT_TOKEN: "secret-mgmt",
                CONF_WEBHOOK_BACKUP_POLLING: True,
            }
        ),
    )
    assert coord.update_interval == timedelta(minutes=POLL_INTERVAL_MINUTES)


async def test_webhooks_with_backup_toggle_on_charging(  # noqa: RUF029
    hass: HomeAssistant,
) -> None:
    """Webhooks + backup toggle on + charging → faster cadence applies."""
    coord = _make_coordinator(
        hass,
        _entry(
            {
                CONF_APPLICATION_MANAGEMENT_TOKEN: "secret-mgmt",
                CONF_WEBHOOK_BACKUP_POLLING: True,
            }
        ),
    )
    coord._refresh_update_interval({"charge-ischarging": {"value": True}})
    assert coord.update_interval == timedelta(minutes=POLL_INTERVAL_CHARGING_MINUTES)


async def test_webhooks_with_backup_toggle_transitions(  # noqa: RUF029
    hass: HomeAssistant,
) -> None:
    """Idle → charging → idle cycles between backup and charging cadences."""
    coord = _make_coordinator(
        hass,
        _entry(
            {
                CONF_APPLICATION_MANAGEMENT_TOKEN: "secret-mgmt",
                CONF_WEBHOOK_BACKUP_POLLING: True,
            }
        ),
    )
    assert coord.update_interval == timedelta(minutes=POLL_INTERVAL_MINUTES)

    coord._refresh_update_interval({"charge-ischarging": {"value": True}})
    assert coord.update_interval == timedelta(minutes=POLL_INTERVAL_CHARGING_MINUTES)

    coord._refresh_update_interval({"charge-ischarging": {"value": False}})
    assert coord.update_interval == timedelta(minutes=POLL_INTERVAL_MINUTES)


async def test_async_set_updated_data_refreshes_interval(  # noqa: RUF029
    hass: HomeAssistant,
) -> None:
    """The webhook merge path triggers an interval recompute."""
    coord = _make_coordinator(hass, _entry({}))
    assert coord.update_interval == timedelta(minutes=POLL_INTERVAL_MINUTES)

    coord.async_set_updated_data({"charge-ischarging": {"value": True}})
    assert coord.update_interval == timedelta(minutes=POLL_INTERVAL_CHARGING_MINUTES)


async def test_non_boolean_ischarging_treated_as_idle(  # noqa: RUF029
    hass: HomeAssistant,
) -> None:
    """A non-bool ``charge-ischarging.value`` falls through to idle behaviour.

    The integration normalises wire payloads, but the interval logic
    should be robust to a malformed value anyway.
    """
    coord = _make_coordinator(hass, _entry({}))
    coord._refresh_update_interval({"charge-ischarging": {"value": "yes"}})
    assert coord.update_interval == timedelta(minutes=POLL_INTERVAL_MINUTES)
