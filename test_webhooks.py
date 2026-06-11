"""Tests for how the webhook handler classifies Smartcar signal errors.

Smartcar V3 webhook payloads carry a per-signal ``status`` field. When
``status.value == "ERROR"``, ``status.error`` describes why. Some of those
``error.type`` values are normal, recurring conditions (the vehicle just
isn't in the right state to read this signal), not problems the user can
act on. Those should not be logged at error level.

What we exercise here:

  * ``VEHICLE_STATE`` errors on an integrated signal log at ``debug`` —
    the case the user actually reported, where ``ChargeRate`` reports
    ``VEHICLE_STATE:NOT_CHARGING`` every time the car isn't actively
    charging.
  * Non-``VEHICLE_STATE`` errors on an integrated signal still log at
    ``error`` — we don't want to silently swallow actionable failures.
  * Errors on non-integrated signals always log at ``debug``, regardless
    of error type. (Preserves the prior behaviour.)
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from custom_components.smartcar.webhooks import _handle_webhook_signals  # noqa: PLC2701


def _make_coordinator() -> MagicMock:
    """Build a coordinator stub with the minimum surface ``_handle_webhook_signals`` uses."""
    coord = MagicMock()
    coord.data = {}
    # ``create_updated_data`` is a context manager yielding (adder, dict).
    # Return a no-op adder so signal-error log routing is the only thing
    # we exercise here.
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


def test_other_error_type_on_integrated_signal_still_logs_error(
    caplog: object,
) -> None:
    """A non-VEHICLE_STATE error on an integrated signal stays at error level.

    These are actionable: permission revoked, OEM upstream broken, etc.
    Burying them in debug would be a regression.
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
        f"expected ERROR-level for PERMISSION error, got {[r.levelname for r in matching]}"
    )


def test_error_on_non_integrated_signal_always_debug(caplog: object) -> None:
    """A signal we don't expose as an entity logs at debug regardless of type."""
    coord = _make_coordinator()
    signal = _make_signal(
        "some-unmapped-code", "INTEGRATION", "UNKNOWN", name="WeirdSignal"
    )

    with caplog.at_level(logging.DEBUG, logger="custom_components.smartcar.webhooks"):
        _handle_webhook_signals(coord, [signal])

    matching = [r for r in caplog.records if "WeirdSignal" in r.getMessage()]
    assert matching
    assert all(r.levelno == logging.DEBUG for r in matching), (
        f"non-integrated signal must stay at DEBUG, got "
        f"{[r.levelname for r in matching]}"
    )
