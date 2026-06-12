"""Smartcar V3 webhook handling."""

from __future__ import annotations

from collections.abc import Callable
import copy
from functools import wraps
import hmac
from http import HTTPStatus
import json
import logging
from typing import Any, Literal, cast

from aiohttp import web
from homeassistant.components import cloud, webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import util
from .const import CONF_APPLICATION_MANAGEMENT_TOKEN
from .coordinator import (
    DATAPOINT_CODE_MAP,
    IMPERIAL_UNITS,
    SmartcarVehicleCoordinator,
    normalize_signal_body_percent,
)
from .types import SmartcarData

_LOGGER = logging.getLogger(__name__)

# Smartcar signal-error types that warrant ``error``-level logging.
# Anything else lands at ``debug``. We invert the previous "demote
# these" approach because the list of normal/transient error types
# keeps growing as users report new ones (``VEHICLE_STATE:NOT_CHARGING``,
# ``UPSTREAM:INVALID_DATA`` when charging is suspended, …) — none of
# them are actionable. The only types a user can actually do something
# about are:
#
#   * ``PERMISSION`` — a granted scope is missing on the dashboard. The
#     user can re-authorise to fix it.
#   * ``AUTHENTICATION`` — the access token is invalid. Same fix path.
#
# Everything else (``VEHICLE_STATE``, ``UPSTREAM``, ``INTEGRATION``,
# ``RATE_LIMIT``, ``COMPATIBILITY``, ``CONNECTION``, …) is transient or
# Smartcar-side and the user can't fix it from the HA UI; those go to
# debug. The corresponding entity still goes ``unavailable`` either way
# (we set ``body = {"value": None}`` in the merge path), which is the
# right behaviour — only the log level changes.
_ACTIONABLE_ERROR_TYPES = frozenset({"PERMISSION", "AUTHENTICATION"})


async def webhook_url_from_id(hass: HomeAssistant, webhook_id: str) -> tuple[str, bool]:
    """Return (url, is_cloudhook) for the configured webhook id."""
    if cloud.async_active_subscription(hass):
        webhook_url = await cloud.async_get_or_create_cloudhook(hass, webhook_id)
        cloudhook = True
    else:
        webhook_url = webhook.async_generate_url(hass, webhook_id)
        cloudhook = False
    return webhook_url, cloudhook


def update_meta_coordinator_data[F: Callable[..., Any], ReturnT](fn: F) -> F:
    """Capture the last webhook request/response into the meta coordinator.

    Returns:
        The wrapped function with its response data mirrored into the meta
        coordinator for diagnostic / debugging visibility.
    """

    @wraps(fn)
    async def wrapper(*args, **kwargs) -> ReturnT:  # noqa: ANN002, ANN003
        response = await fn(*args, **kwargs)
        config_entry = kwargs["config_entry"]
        request = args[2]
        status = response.status
        data = response.text or (response.body and response.body.decode("utf-8"))
        meta_coordinator = config_entry.runtime_data.meta_coordinator
        meta_coordinator.async_set_updated_data(
            {
                **meta_coordinator.data,
                "last_webhook_received_at": dt_util.utcnow(),
                "last_webhook_response": {
                    "status": status,
                    **({"data": data} if data else {}),
                },
                "last_webhook_request": await request.text(),
            }
        )
        return cast("ReturnT", response)

    return cast("F", wrapper)


@update_meta_coordinator_data
async def handle_webhook(
    hass: HomeAssistant,  # noqa: ARG001
    webhook_id: str,  # noqa: ARG001
    request: web.Request,
    *,
    config_entry: ConfigEntry,
) -> web.Response:
    """Process an incoming Smartcar V3 webhook.

    Returns:
        An HTTP response. ``200`` is returned for processed payloads and for
        Smartcar's URL-verification handshake; ``400``/``401`` for malformed
        or unauthenticated requests.
    """
    try:
        body = await request.text()
        message = json.loads(body)
    except ValueError:
        _LOGGER.warning("Received invalid JSON from Smartcar")
        return web.json_response(
            {"error": {"code": "invalid_json", "message": "invalid JSON body"}},
            status=HTTPStatus.BAD_REQUEST,
        )

    _LOGGER.debug("Received JSON from Smartcar: %r", body)

    app_token: str = config_entry.data[CONF_APPLICATION_MANAGEMENT_TOKEN]
    signature = request.headers.get("SC-Signature")
    data = message.get("data", {})

    # Verification handshake — not signed.
    if message.get("eventType") == "VERIFY":
        return web.json_response(
            {"challenge": util.hmac_sha256_hexdigest(app_token, data["challenge"])}
        )

    # Every other payload must be signed.
    if not hmac.compare_digest(util.hmac_sha256_hexdigest(app_token, body), signature):
        _LOGGER.error("Ignoring webhook message with invalid signature")
        return web.json_response(
            {
                "error": {
                    "code": "invalid_signature",
                    "message": "invalid signature on request body",
                }
            },
            status=HTTPStatus.UNAUTHORIZED,
        )

    # TEST mode acknowledgements for dashboard setup.
    if message.get("meta", {}).get("mode") == "TEST":
        vehicle = data.get("vehicle", {})
        _LOGGER.debug("TEST webhook for vehicle %s; no action", vehicle.get("id"))
        return web.json_response(
            {
                "status": {
                    "code": "acknowledged",
                    "message": "no action taken; (mode=TEST)",
                },
                "vehicle": vehicle,
            },
            status=HTTPStatus.ACCEPTED,
        )

    errors = data.get("errors", [])
    signals = data.get("signals", [])
    vehicle = data.get("vehicle", {})
    vehicle_id = vehicle.get("id")
    runtime_data: SmartcarData = config_entry.runtime_data
    coordinators = runtime_data.coordinators

    # Map the webhook's vehicle id → our locally-keyed coordinator (by VIN).
    vehicle_vin: str | None = next(
        (
            vin
            for coordinator in coordinators.values()
            if (
                vin := coordinator.config_entry.data.get("vehicles", {})
                .get(vehicle_id, {})
                .get("vin")
            )
        ),
        None,
    )
    coordinator = coordinators.get(vehicle_vin) if vehicle_vin else None

    if not coordinator:
        _LOGGER.debug(
            "Ignoring webhook for unknown vehicle id=%s, vin=%s",
            vehicle_id,
            vehicle_vin or "unknown",
        )
        return web.json_response(
            {
                "error": {
                    "code": "unknown_vehicle",
                    "message": "unknown vehicle included",
                }
            },
            status=HTTPStatus.CONFLICT,
        )

    _handle_webhook_errors(coordinator, errors)
    _handle_webhook_signals(coordinator, signals)

    return web.Response(status=HTTPStatus.NO_CONTENT)


def _handle_webhook_errors(
    coordinator: SmartcarVehicleCoordinator,
    errors: list[dict],
) -> None:
    hass = coordinator.hass
    config_entry = coordinator.config_entry

    for error in errors:
        error_type = error.get("type")
        resolution = error.get("resolution", {}).get("type")
        signals = error.get("signals", [])
        if (
            error_type == "PERMISSION"
            and resolution == "REAUTHENTICATE"
            and (not signals or any(_is_integrated(s) for s in signals))
        ):
            _LOGGER.info("Requesting reauth due to webhook message: %s", error)
            config_entry.async_start_reauth(hass)
        else:
            _LOGGER.debug("Ignoring error in webhook: %s", error)


def _is_integrated(signal: dict) -> bool:
    code: str | None = signal.get("code")
    return code in DATAPOINT_CODE_MAP


def _handle_webhook_signals(
    coordinator: SmartcarVehicleCoordinator,
    signals: list[dict],
) -> None:
    """Apply webhook signals to the coordinator's stored data."""
    with coordinator.create_updated_data() as (add, updated_data):
        data_changed = False

        for signal in signals:
            name: str | None = signal.get("name")
            status = signal.get("status", {})
            is_error = status.get("value") == "ERROR"
            code: str | None = signal.get("code")
            body = copy.deepcopy(signal.get("body", {}))
            meta = signal.get("meta", {})

            if is_error:
                error_obj = status.get("error", {})
                # An error from Smartcar gets logged at error-level only
                # when it's both (a) for a signal we actually surface as
                # an entity and (b) of a type the user can do something
                # about. Everything else — vehicle-state errors,
                # OEM upstream blips, rate limits, etc. — is informational
                # and goes to debug.
                is_actionable = (
                    _is_integrated(signal)
                    and error_obj.get("type") in _ACTIONABLE_ERROR_TYPES
                )
                _handle_webhook_signal_error(
                    name,
                    error_obj,
                    level="error" if is_actionable else "debug",
                )
                body = {"value": None}

            normalize_signal_body_percent(code, body)

            if code in DATAPOINT_CODE_MAP:
                assert code is not None

                data_age = meta.get("oemUpdatedAt") if not is_error else None
                fetched_at = meta.get("retrievedAt") if not is_error else None
                unit = body.pop("unit", None)
                unit_system = (
                    "imperial" if unit in IMPERIAL_UNITS else "metric" if unit else None
                )

                # Webhook timestamps are ms-since-epoch (numeric); /signals
                # uses ISO strings. Handle ms here.
                if isinstance(data_age, (int, float)):
                    data_age = dt_util.utc_from_timestamp(data_age / 1000)
                if isinstance(fetched_at, (int, float)):
                    fetched_at = dt_util.utc_from_timestamp(fetched_at / 1000)

                add.from_response_body(
                    code,
                    body=body,
                    unit_system=unit_system,
                    data_age=data_age,
                    fetched_at=fetched_at,
                    can_clear_meta=not is_error,
                )
                data_changed = True

        if data_changed:
            coordinator.async_set_updated_data(updated_data)


def _handle_webhook_signal_error(
    signal_name: str | None,
    error: dict,
    *,
    level: Literal["error", "debug"] = "error",
) -> None:
    error_type = error.get("type")
    error_code = error.get("code")
    logger_method = getattr(_LOGGER, level)
    logger_method("error for signal %s: %s:%s", signal_name, error_type, error_code)
