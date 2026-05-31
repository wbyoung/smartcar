"""Shared helpers for the Smartcar V3 test suite."""

from . import bootstrap as bootstrap  # noqa: I001

import datetime as dt

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

MOCK_API_ENDPOINT = "http://test.local"
MOCK_UTC_NOW = dt.datetime(2026, 2, 17, 16, 21, 32, 3842, tzinfo=dt.UTC)


async def setup_integration(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Add the entry to hass and run ``async_setup_entry`` for it."""
    config_entry.add_to_hass(hass)
    await setup_added_integration(hass, config_entry)


async def setup_added_integration(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Run ``async_setup_entry`` for an entry that has already been added."""
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
