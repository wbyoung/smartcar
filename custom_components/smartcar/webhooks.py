from collections.abc import Callable
from functools import wraps
import hmac
from http import HTTPStatus
import json
import logging
from typing import Any, cast

from aiohttp import web
from homeassistant.components import cloud, webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import util
from .const import CONF_APPLICATION_MANAGEMENT_TOKEN
from .coordinator import SmartcarVehicleCoordinator, _is_integrated
from .types import SmartcarData

_LOGGER = logging.getLogger(__name__)


async def webhook_url_from_id(hass: HomeAssistant, webhook_id: str) -> tuple[str, bool]:
    if cloud.async_active_subscription(hass):
        webhook_url = await cloud.async_get_or_create_cloudhook(hass, webhook_id)
        cloudhook = True
    else:
        webhook_url = webhook.async_generate_url(hass, webhook_id)
        cloudhook = False

    return webhook_url, cloudhook


def update_meta_coordinator_data[F: Callable[..., Any], ReturnT](fn: F) -> F:
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
    """Handle webhook callback.

    Returns:
        The response to send back to Smartcar.
    """
    try:
        body = await request.text()
        message = json.loads(body)
    except ValueError:
        _LOGGER.warning("Received invalid JSON from Smartcar")
        return web.json_response(
            {
                "error": {
                    "code": "invalid_json",
                    "message": "invalid JSON body",
                }
            },
            status=HTTPStatus.BAD_REQUEST,
        )

    _LOGGER.debug("Received JSON from Smartcar: %r", body)

    app_token: str = config_entry.data[CONF_APPLICATION_MANAGEMENT_TOKEN]
    signature = request.headers.get("SC-Signature")
    data = message.get("data", {})

    if message.get("eventType") == "VERIFY":
        return web.json_response(
            {"challenge": util.hmac_sha256_hexdigest(app_token, data["challenge"])}
        )

    _LOGGER.debug("Validating signature: %s; app_token: %s", signature, app_token)

    # the verify message is not signed, so that's done before this check. all
    # other messages must be signed & validated before we process the data from
    # them.
    if not hmac.compare_digest(util.hmac_sha256_hexdigest(app_token, body), signature):
        _LOGGER.error("ignoring message with invalid signature")
        return web.json_response(
            {
                "error": {
                    "code": "invalid_signature",
                    "message": "invalid signature on request body",
                }
            },
            status=HTTPStatus.UNAUTHORIZED,
        )

    # respond to test mode payloads to aid with setup
    if message.get("meta", {}).get("mode") == "TEST":
        vehicle = data.get("vehicle", {})
        vehicle_id = vehicle.get("id")
        _LOGGER.debug(
            "mode=TEST; no action taken for vehicle with id: %s",
            vehicle_id,
        )
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
    coordinator = coordinators.get(vehicle_id) or (
        coordinators.get(vehicle_vin) if vehicle_vin else None
    )

    if not coordinator:
        _LOGGER.debug(
            "ignoring message for unknown vehicle with id: %s, vin: %s",
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
            _LOGGER.info("requesting reauth due to webhook message: %s", error)
            config_entry.async_start_reauth(hass)
        else:
            _LOGGER.debug("ignoring error in webhook: %s", error)


def _handle_webhook_signals(
    coordinator: SmartcarVehicleCoordinator,
    signals: list[dict],
) -> None:
    with coordinator.create_updated_data() as (add, updated_data):
        for signal in signals:
            add.from_signal_attributes(signal)

        if add.addition_made:
            coordinator.async_set_updated_data(updated_data)
