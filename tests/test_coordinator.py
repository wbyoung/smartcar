"""Test signal timestamp handling across polling and webhooks."""

import copy
import datetime as dt
import logging

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartcar import coordinator as coordinator_module

from . import setup_integration


@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
@pytest.mark.parametrize("client_id_version", ["v3"])
async def test_v3_polling_preserves_signal_metadata(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    vehicle: dict,
) -> None:
    """Expose per-signal OEM and retrieval times from the v3 response."""
    original_response = copy.deepcopy(vehicle["_api"])
    await setup_integration(hass, mock_config_entry)
    assert vehicle["_api"] == original_response
    state = hass.states.get("sensor.vw_id_4_battery")
    assert state is not None
    assert state.attributes["age"] == "2026-06-29T23:55:53+00:00"
    assert state.attributes["fetched_at"] == "2026-06-30T00:03:53.743000+00:00"


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        (
            "2026-06-29T23:55:53.000Z",
            dt.datetime(2026, 6, 29, 23, 55, 53, tzinfo=dt.UTC),
        ),
        (
            "2026-06-30T01:55:53+02:00",
            dt.datetime(2026, 6, 29, 23, 55, 53, tzinfo=dt.UTC),
        ),
        (1782777353000, dt.datetime(2026, 6, 29, 23, 55, 53, tzinfo=dt.UTC)),
        (1782777353743.0, dt.datetime(2026, 6, 29, 23, 55, 53, 743000, tzinfo=dt.UTC)),
        (0, None),
        (None, None),
        ("not-a-timestamp", None),
    ],
    ids=[
        "iso-utc",
        "iso-offset",
        "milliseconds",
        "fractional-milliseconds",
        "zero-unavailable",
        "missing",
        "invalid",
    ],
)
def test_signal_timestamps(timestamp, expected: dt.datetime | None) -> None:
    """Parse both API timestamp formats without changing the payload."""
    signal = {
        "code": "tractionbattery-stateofcharge",
        "body": {"value": 73, "unit": "percent"},
        "meta": {"oemUpdatedAt": timestamp, "retrievedAt": timestamp},
    }
    original = copy.deepcopy(signal)
    old_time = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    data: dict = {
        "tractionbattery-stateofcharge:data_age": old_time,
        "tractionbattery-stateofcharge:fetched_at": old_time,
    }
    coordinator_module._DataAdder(data).from_signal_attributes(signal)

    assert data["tractionbattery-stateofcharge"] == {"value": 0.73}
    assert data.get("tractionbattery-stateofcharge:data_age") == expected
    assert data.get("tractionbattery-stateofcharge:fetched_at") == expected
    assert signal == original


def test_failed_signal_preserves_previous_timestamps() -> None:
    """A failed signal must not replace the last successful observation time."""
    old_time = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    data: dict = {
        "tractionbattery-stateofcharge": {"value": 0.73},
        "tractionbattery-stateofcharge:data_age": old_time,
        "tractionbattery-stateofcharge:fetched_at": old_time,
    }
    coordinator_module._DataAdder(data).from_signal_attributes(
        {
            "code": "tractionbattery-stateofcharge",
            "status": {"value": "ERROR"},
            "meta": {
                "oemUpdatedAt": "2026-06-29T23:55:53.000Z",
                "retrievedAt": "2026-06-30T00:03:53.743Z",
            },
        }
    )
    assert data["tractionbattery-stateofcharge"] == {"value": None}
    assert data["tractionbattery-stateofcharge:data_age"] == old_time
    assert data["tractionbattery-stateofcharge:fetched_at"] == old_time


@pytest.mark.parametrize(
    ("code", "error", "token_scopes", "expected_level"),
    [
        (
            "closure-doors",
            {"type": "PERMISSION", "code": None},
            frozenset({"read_battery"}),
            logging.DEBUG,
        ),
        (
            "closure-islocked",
            {"type": "PERMISSION", "code": None},
            frozenset({"read_battery"}),
            logging.DEBUG,
        ),
        (
            "closure-doors",
            {"type": "PERMISSION", "code": None},
            frozenset({"read_security"}),
            logging.ERROR,
        ),
        (
            "closure-islocked",
            {"type": "PERMISSION", "code": None},
            frozenset({"read_security"}),
            logging.ERROR,
        ),
        (
            "closure-windows",
            {"type": "PERMISSION", "code": None},
            frozenset({"read_battery"}),
            logging.ERROR,
        ),
        (
            "closure-doors",
            {"type": "SERVER", "code": None},
            frozenset({"read_battery"}),
            logging.ERROR,
        ),
    ],
    ids=[
        "unheld_scope_v3_only_signal",
        "unheld_scope_declared_datapoint",
        "held_scope_is_genuine",
        "held_read_scope_without_control_scope",
        "no_known_scope_is_genuine",
        "non_permission_error_is_genuine",
    ],
)
def test_signal_error_for_unheld_scope_is_debug(
    caplog: pytest.LogCaptureFixture,
    code: str,
    error: dict,
    token_scopes: frozenset[str],
    expected_level: int,
) -> None:
    """Permission errors for scopes the user never granted are expected noise."""
    with caplog.at_level(logging.DEBUG, logger="custom_components.smartcar"):
        coordinator_module._DataAdder(
            {}, token_scopes=token_scopes
        ).from_signal_attributes(
            {
                "code": code,
                "name": "Signal",
                "status": {"value": "ERROR", "error": error},
            }
        )

    record = next(r for r in caplog.records if "error for signal" in r.message)
    assert record.levelno == expected_level
