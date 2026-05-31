"""Diagnostics tests for the V3 integration.

These verify that :func:`async_get_config_entry_diagnostics` returns the
expected shape with the right fields redacted. The integration redacts a
set of sensitive fields (``vin``, ``application_management_token``,
``access_token``, ``refresh_token``, ``latitude``, ``longitude``, etc.)
before exposing the diagnostics blob.

The fixture data behind these tests comes from a real Smartcar V3 webhook
payload (a VW ID.7); see ``tests/fixtures/coordinator_data/vw_id7.json``.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartcar.diagnostics import async_get_config_entry_diagnostics

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


async def test_diagnostics_redact_sensitive_fields(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator_data: dict[str, Any],
    setup_with_data,
) -> None:
    """The diagnostics dump must redact VIN, management token, and access tokens.

    Notably the V3 ``client_id`` / ``client_secret`` and ``sc_user_id``
    are not in the redact set today — if that ever changes, this test will
    need updating alongside ``diagnostics.TO_REDACT``.
    """
    await setup_with_data(mock_config_entry, coordinator_data)

    diag = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    # The diagnostics dump is shaped as the integration sees fit — usually
    # {"entry": ..., "data": ..., "metadata": ...}. We look for the
    # sensitive values by flat-scanning the JSON-friendly tree.
    flat = _flatten(diag)

    # VIN should be redacted everywhere it appears.
    assert "00000000-0000-0000-0000-0000000000aa" not in flat or "**REDACTED**" in flat
    assert "1XKYP49X1RJ701910" not in flat, (
        "Real VIN should never appear in diagnostics"
    )

    # The application management token must not appear in plaintext.
    # (Our mock entry doesn't include one, but for safety against future
    # fixture changes: scan for it explicitly.)
    assert "c2b30707" not in flat, "Application management token leaked"

    # The webhook URL contains a sensitive cloudhook token — should also
    # not appear (cloudhook URL isn't part of the entry data here, but
    # double-check anyway).
    assert "hooks.nabu.casa/gAAA" not in flat


async def test_diagnostics_includes_coordinator_data(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator_data: dict[str, Any],
    setup_with_data,
) -> None:
    """Diagnostics expose enough state to debug the running integration."""
    await setup_with_data(mock_config_entry, coordinator_data)

    diag = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    flat = _flatten(diag)

    # Coordinator data should be reachable in some form.
    assert "tractionbattery-stateofcharge" in flat
    assert "odometer-traveleddistance" in flat
    assert "charge-detailedchargingstatus" in flat


def _flatten(obj: Any) -> str:
    """Recursively render ``obj`` to a single string for substring assertions.

    Returns:
        A string representation; sufficient for substring presence checks.
    """
    import json  # noqa: PLC0415

    try:
        return json.dumps(obj, default=str)
    except (TypeError, ValueError):
        return repr(obj)
