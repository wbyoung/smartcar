"""Tests for how the webhook handler classifies Smartcar signal errors.

Smartcar V3 webhook payloads carry a per-signal ``status`` field. When
``status.value == "ERROR"``, ``status.error`` describes why. Most of
those error types are normal, recurring conditions (the vehicle just
isn't in the right state, Smartcar's upstream OEM connection hiccupped,
the OEM returned data that didn't parse, etc.) — none of them are
things the user can act on. They should not be logged at error level.

The integration's rule: only ``PERMISSION`` and ``AUTHENTICATION``
errors trigger error-level logging — those map to "re-authorise to grant
the missing scope or refresh the token". Everything else is debug.

What we exercise:

  * ``VEHICLE_STATE`` on an integrated signal → ``debug`` (the case
    reported as `ChargeRate / NOT_CHARGING` after unplugging).
  * ``UPSTREAM`` on an integrated signal → ``debug`` (the
    `TimeToComplete / UPSTREAM:INVALID_DATA` case reported when charging
    is suspended).
  * ``PERMISSION`` on an integrated signal → ``error`` (re-auth path).
  * ``AUTHENTICATION`` on an integrated signal → ``error``.
  * Errors on non-integrated signals always log at ``debug``,
    regardless of error type.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from custom_components.smartcar.webhooks import _handle_webhook_signals  # noqa: PLC2701


def _make_coordinator() -> MagicMock:
    """Build a coordinator stub with the minimum surface ``_handle_webhook_signals`` uses."""
    coord = MagicMock()
    coord.data = {}
    fake_adder = MagicMock()
    coord.create_updated_data.return_value.__enter__.return_value = (fake_adder, {})
    coord.create_updated_data.return_value.__exit__.return_value = False
    return coord


def _make_signal(
    code: str, error_type: str, error_code: str, name: str | None = None
) -> dict:
    return {
        "code": code,
        "name": name or code,
        "body": {"value": None},
        "meta": {"oemUpdatedAt": 0, "retrievedAt": 0},
        "status": {
            "value": "ERROR",
            "error": {"type": error_type, "code": error_code},
        },
    }


def test_vehicle_state_error_on_integrated_signal_logs_debug(
    caplog: object,
) -> None:
    """``VEHICLE_STATE:NOT_CHARGING`` on ChargeRate must not log at error level."""
    coord = _make_coordinator()
    signal = _make_signal(
        "charge-chargerate", "VEHICLE_STATE", "NOT_CHARGING", name="ChargeRate"
    )

    with caplog.at_level(logging.DEBUG, logger="custom_components.smartcar.webhooks"):
        _handle_webhook_signals(coord, [signal])

    matching = [r for r in caplog.records if "ChargeRate" in r.getMessage()]
    assert matching, "expected a log record mentioning ChargeRate"
    assert all(r.levelno == logging.DEBUG for r in matching), (
        f"expected DEBUG-level only, got {[r.levelname for r in matching]}"
    )


def test_upstream_error_on_integrated_signal_logs_debug(
    caplog: object,
) -> None:
    """``UPSTREAM:INVALID_DATA`` on TimeToComplete (charging suspended) → DEBUG.

    Reproduces the issue reported with the suspended-charging case:
    Smartcar returns ``UPSTREAM:INVALID_DATA`` for TimeToComplete while
    charging is in the suspended state. The user can't fix that and
    doesn't need an error-log entry for every webhook delivery that
    happens during the suspension.
    """
    coord = _make_coordinator()
    signal = _make_signal(
        "charge-timetocomplete",
        "UPSTREAM",
        "INVALID_DATA",
        name="TimeToComplete",
    )

    with caplog.at_level(logging.DEBUG, logger="custom_components.smartcar.webhooks"):
        _handle_webhook_signals(coord, [signal])

    matching = [r for r in caplog.records if "TimeToComplete" in r.getMessage()]
    assert matching
    assert all(r.levelno == logging.DEBUG for r in matching), (
        f"expected DEBUG-level only, got {[r.levelname for r in matching]}"
    )


def test_permission_error_on_integrated_signal_logs_error(
    caplog: object,
) -> None:
    """A PERMISSION error stays at error level — that's actionable.

    Missing-scope failures are the kind of thing a user can fix from the
    Smartcar dashboard by re-authorising. Burying them in debug would
    leave them mysteriously stuck.
    """
    coord = _make_coordinator()
    signal = _make_signal(
        "charge-chargerate",
        "PERMISSION",
        "INSUFFICIENT_PERMISSIONS",
        name="ChargeRate",
    )

    with caplog.at_level(logging.DEBUG, logger="custom_components.smartcar.webhooks"):
        _handle_webhook_signals(coord, [signal])

    matching = [r for r in caplog.records if "ChargeRate" in r.getMessage()]
    assert matching
    assert any(r.levelno == logging.ERROR for r in matching), (
        f"expected ERROR-level for PERMISSION error, got "
        f"{[r.levelname for r in matching]}"
    )


def test_authentication_error_on_integrated_signal_logs_error(
    caplog: object,
) -> None:
    """An AUTHENTICATION error also stays at error level — also actionable."""
    coord = _make_coordinator()
    signal = _make_signal(
        "charge-chargerate",
        "AUTHENTICATION",
        "INVALID_TOKEN",
        name="ChargeRate",
    )

    with caplog.at_level(logging.DEBUG, logger="custom_components.smartcar.webhooks"):
        _handle_webhook_signals(coord, [signal])

    matching = [r for r in caplog.records if "ChargeRate" in r.getMessage()]
    assert matching
    assert any(r.levelno == logging.ERROR for r in matching), (
        f"expected ERROR-level for AUTHENTICATION error, got "
        f"{[r.levelname for r in matching]}"
    )


def test_error_on_non_integrated_signal_always_debug(caplog: object) -> None:
    """A signal we don't expose as an entity logs at debug regardless of type."""
    coord = _make_coordinator()
    signal = _make_signal(
        "some-unmapped-code",
        "PERMISSION",
        "INSUFFICIENT_PERMISSIONS",
        name="WeirdSignal",
    )

    with caplog.at_level(logging.DEBUG, logger="custom_components.smartcar.webhooks"):
        _handle_webhook_signals(coord, [signal])

    matching = [r for r in caplog.records if "WeirdSignal" in r.getMessage()]
    assert matching
    assert all(r.levelno == logging.DEBUG for r in matching), (
        f"non-integrated signal must stay at DEBUG, got "
        f"{[r.levelname for r in matching]}"
    )
