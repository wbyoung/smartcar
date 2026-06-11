"""Shared helpers for the Smartcar V3 test suite."""

from . import bootstrap as bootstrap  # noqa: I001

import datetime as dt
import json
import pathlib
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

MOCK_API_ENDPOINT = "http://test.local"
MOCK_UTC_NOW = dt.datetime(2026, 2, 17, 16, 21, 32, 3842, tzinfo=dt.UTC)

_FIXTURE_ROOT = pathlib.Path(__file__).parent / "fixtures"


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


def load_fixture_json(relative_path: str) -> Any:
    """Load a JSON fixture from ``tests/fixtures/``.

    Returns:
        The decoded JSON content.
    """
    return json.loads((_FIXTURE_ROOT / relative_path).read_text())


def load_coordinator_data(fixture_name: str) -> dict[str, Any]:
    """Load processed coordinator data from a fixture.

    The diagnostic JSON serialises ``data_age`` and ``fetched_at`` values as
    ISO-8601 strings, but the running coordinator stores them as
    ``datetime`` instances. We re-hydrate so entity attributes derived from
    those fields look exactly like production.

    Returns:
        The fixture as a ready-to-inject coordinator data dict.
    """
    data = load_fixture_json(f"coordinator_data/{fixture_name}.json")
    rehydrated: dict[str, Any] = {}
    for key, value in data.items():
        if (key.endswith((":data_age", ":fetched_at"))) and isinstance(value, str):
            rehydrated[key] = dt_util.parse_datetime(value)
        else:
            rehydrated[key] = value
    return rehydrated
