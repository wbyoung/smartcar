from . import bootstrap as bootstrap  # noqa: I001, PLC0414

import importlib

import datetime as dt
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    load_json_array_fixture,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.smartcar.const import DOMAIN
from custom_components.smartcar.types import APIVersion

MOCK_API_ENDPOINT = "http://test.local/v3"
MOCK_API_ENDPOINT_LEGACY = "http://test.local/v2.0"
MOCK_API_ENDPOINTS: dict[APIVersion, str] = {
    "v2": MOCK_API_ENDPOINT_LEGACY,
    "v3": MOCK_API_ENDPOINT,
}
MOCK_UTC_NOW = dt.datetime(2026, 2, 17, 16, 21, 32, 3842, tzinfo=dt.UTC)


async def setup_integration(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Helper for setting up the component."""
    config_entry.add_to_hass(hass)
    await setup_added_integration(hass, config_entry)


async def setup_added_integration(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Helper for setting up a previously added component."""

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


def aioclient_mock_append_vehicle_request(
    aioclient_mock: AiohttpClientMocker,
    api_response_type: str,
    vehicle_fixture: str,
    vehicle_attributes: dict,
    client_id_version: APIVersion,
):
    vehicle_id = vehicle_attributes["id"]
    fixture_name = (
        "api/"
        f"{vehicle_fixture}.{api_response_type}"
        f"{'.v3' if client_id_version == 'v3' else ''}.json"
    )
    http_calls = load_json_array_fixture(fixture_name, DOMAIN)

    for http_call in http_calls:
        method = http_call.get("method", "get")
        params = http_call.get("params", {})
        status = http_call.get("status", 200)
        side_effect = http_call.get("side_effect")
        json = http_call.get("response")
        path = http_call.get("path")
        vehicle_path = http_call.get("vehicle_path")
        assert path or vehicle_path, (
            f"{fixture_name} fixture should provide one of `path` or `vehicle_path`"
        )
        assert json or side_effect or status != 200, (
            f"{fixture_name} fixture should provide `response`"
        )

        if not path:
            path = f"/vehicles/{vehicle_id}{vehicle_path}"

        if side_effect:
            module_path, class_name = side_effect.rsplit(".", 1)
            module = importlib.import_module(module_path)
            side_effect_class = getattr(module, class_name)

            def side_effect(
                *args,  # noqa: ANN002
                side_effect_class=side_effect_class,
            ):
                raise side_effect_class()

        getattr(aioclient_mock, method)(
            f"{MOCK_API_ENDPOINTS[client_id_version]}{path}",
            params=params,
            status=status,
            side_effect=side_effect,
            json=json,
        )

    return http_calls
