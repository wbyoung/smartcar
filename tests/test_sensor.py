"""Test sensors."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import datetime as dt
from operator import itemgetter
from typing import Any, cast
from unittest.mock import AsyncMock

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_component import async_update_entity
from homeassistant.helpers.restore_state import STORAGE_KEY as RESTORE_STATE_KEY
from homeassistant.util.dt import utcnow
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_restore_state_shutdown_restart,
    mock_restore_cache_with_extra_data,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from syrupy.assertion import SnapshotAssertion

from custom_components.smartcar import sensor as sensor_module
from custom_components.smartcar.const import (
    DEFAULT_ENABLED_ENTITY_DESCRIPTION_KEYS,
    OAUTH2_TOKEN_LEGACY,
    REQUIRED_SCOPES,
    EntityDescriptionKey,
)
from custom_components.smartcar.coordinator import (
    VEHICLE_BACK_ROW,
    VEHICLE_FRONT_ROW,
    VEHICLE_LEFT_COLUMN,
    VEHICLE_RIGHT_COLUMN,
)
from custom_components.smartcar.entity import SmartcarEntity
from custom_components.smartcar.sensor import SmartcarSensorDescription
from custom_components.smartcar.types import APIVersion

from . import setup_added_integration, setup_integration


def test_diag_status_cast() -> None:
    """Test extraction of diagnostic statuses from webhook signal bodies."""
    assert sensor_module._diag_status({"status": "OK"}) == "OK"
    assert sensor_module._diag_status({"value": "WARNING"}) == "WARNING"
    assert sensor_module._diag_status({}) is None
    assert sensor_module._diag_status("OK") == "OK"
    assert sensor_module._diag_status(None) is None


def test_dtc_count_cast() -> None:
    """Test extraction of trouble code counts from webhook signal bodies."""
    assert sensor_module._dtc_count({"value": 2}) == 2
    assert sensor_module._dtc_count({"count": 3}) == 3
    assert sensor_module._dtc_count({}) is None
    assert sensor_module._dtc_count(4) == 4
    assert sensor_module._dtc_count(None) is None


def test_dtc_list_cast() -> None:
    """Test extraction of trouble code lists from webhook signal bodies."""
    assert (
        sensor_module._dtc_list({"value": [{"code": "P0100"}, "P0200"]})
        == "P0100, P0200"
    )
    assert sensor_module._dtc_list({"values": ["P0300"]}) == "P0300"
    assert sensor_module._dtc_list({"codes": ["P0400"]}) == "P0400"
    assert sensor_module._dtc_list({"value": "P0500"}) == "P0500"
    assert sensor_module._dtc_list({}) == "none"
    assert sensor_module._dtc_list(None) is None


def test_hvac_number_cast() -> None:
    """Test extraction of HVAC numbers from webhook signal bodies."""
    assert sensor_module._hvac_number({"value": 21.5}) == 21.5
    assert sensor_module._hvac_number({}) is None
    assert sensor_module._hvac_number(19) == 19
    assert sensor_module._hvac_number(None) is None


@pytest.mark.usefixtures("enable_all_entities")
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
async def test_polling_updates(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
    vehicle: AsyncMock,
    vehicle_fixture: str,
    vehicle_attributes: dict,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test sensors when polling is enabled."""

    entity_id = "sensor.vw_id_4_odometer"
    expected_calls = 0

    await setup_integration(hass, mock_config_entry)
    assert entity_registry.async_get(entity_id) == snapshot(
        name="sensor.vw_id_4_odometer-registry"
    )
    assert hass.states.get(entity_id) == snapshot(name=entity_id)

    # check the first refresh based update (a full batch)
    batch_request_mock_call = aioclient_mock.mock_calls[-1]
    assert aioclient_mock.call_count == (expected_calls := expected_calls + 1)
    assert batch_request_mock_call == snapshot(
        name=f"{entity_id}-api-full-batch-request"
    )

    # trigger a polling based update (another full batch update)
    async_fire_time_changed(hass, utcnow() + dt.timedelta(hours=6))
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == (expected_calls := expected_calls + 1)
    assert aioclient_mock.mock_calls[-1] == batch_request_mock_call

    # trigger an update for a single entity (the batch update should only
    # include a request for the odometer)
    await async_update_entity(hass, entity_id)
    assert aioclient_mock.call_count == (expected_calls := expected_calls + 1)
    assert aioclient_mock.mock_calls[-1] == snapshot(
        name=f"{entity_id}-api-odometer-request"
    )

    # disable the entity & update it -- this should not result in any api calls
    entity_registry.async_update_entity(
        entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )
    await async_update_entity(hass, entity_id)
    assert aioclient_mock.call_count == expected_calls  # no update should have occurred

    # trigger a polling based update (which should not include the disabled
    # odometer in the request)
    async_fire_time_changed(hass, utcnow() + dt.timedelta(hours=12))
    await hass.async_block_till_done()
    batch_request_without_odometer_mock_call = aioclient_mock.mock_calls[-1]
    assert aioclient_mock.call_count == (expected_calls := expected_calls + 1)
    assert batch_request_without_odometer_mock_call == snapshot(
        name=f"{entity_id}-api-batch-without-odometer-request"
    )


@pytest.mark.usefixtures("enable_all_entities")
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
async def test_update_with_polling_disabled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
    vehicle: AsyncMock,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test sensors when polling is disabled."""

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        pref_disable_polling=True,
    )

    entity_id = "sensor.vw_id_4_odometer"
    expected_calls = 0

    await setup_added_integration(hass, mock_config_entry)

    assert entity_registry.async_get(entity_id) == snapshot(
        name="sensor.vw_id_4_odometer-registry"
    )
    assert hass.states.get(entity_id) == snapshot(name=entity_id)

    # no requests should have been made during setup when polling is disabled.
    # this is different from the default behavior, but intended to help reduce
    # excessive api usage.
    assert aioclient_mock.call_count == expected_calls

    await async_update_entity(hass, entity_id)

    assert aioclient_mock.call_count == (expected_calls := expected_calls + 1)
    assert aioclient_mock.mock_calls[-1] == snapshot(
        name=f"{entity_id}-api-odometer-request"
    )

    entity_registry.async_update_entity(
        entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )

    # after another update, no more api calls should have occurred
    await async_update_entity(hass, entity_id)
    assert aioclient_mock.call_count == expected_calls


@pytest.mark.usefixtures("enable_all_entities")
@pytest.mark.parametrize("platform", [Platform.SENSOR])
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
@pytest.mark.parametrize(
    ("webhook_body", "webhook_headers", "expected"),
    [
        (
            "verify",  # JSON fixture
            {},
            {
                "response_status": 200,
                "response": {
                    "challenge": "1234",  # from mock_hmac_sha256_hexdigest
                },
            },
        ),
        (
            "all",  # JSON fixture
            {
                "sc-signature": "1234",
            },
            {
                "log_messages": [
                    "error for signal FuelLevel: COMPATIBILITY:VEHICLE_NOT_CAPABLE"
                ],
            },
        ),
        (
            "fuel",  # JSON fixture
            {
                "sc-signature": "1234",
            },
            {},
        ),
        (
            "mismatch",  # JSON fixture
            {
                "sc-signature": "1234",
            },
            {
                "response_status": 409,
                "response": {
                    "error": {
                        "code": "unknown_vehicle",
                        "message": "unknown vehicle included",
                    }
                },
                "log_messages": [
                    "unknown vehicle with id: 70076e4a-d774-464c-8241-60de654ccb24, vin: unknown"
                ],
            },
        ),
        (
            "error",  # JSON fixture
            {
                "sc-signature": "1234",
            },
            {
                "reauth_calls": 1,
                "log_messages": ["ignoring error", "requesting reauth"],
            },
        ),
        (
            "test_mode",  # JSON fixture
            {
                "sc-signature": "1234",
            },
            {
                "response_status": 202,
                "response": {
                    "status": {
                        "code": "acknowledged",
                        "message": "no action taken; (mode=TEST)",
                    },
                    "vehicle": {
                        "id": "a1d50709-3502-4faa-ba43-a5c7565e6a09",
                        "make": "BMW",
                        "model": "118i",
                        "year": 2025,
                    },
                },
                "log_messages": [
                    "Validating signature",
                    "mode=TEST; no action taken",
                    "vehicle with id: a1d50709-3502-4faa-ba43-a5c7565e6a09",
                ],
            },
        ),
        (
            "broad_auth_error",
            {
                "sc-signature": "1234",
            },
            {
                "reauth_calls": 1,
                "log_messages": ["requesting reauth"],
            },
        ),
        (
            "irrelevant_auth_error",
            {
                "sc-signature": "1234",
            },
            {
                "reauth_calls": 0,
                "log_messages": ["ignoring error"],
            },
        ),
        (
            b"invalid-json",
            {
                "sc-signature": "1234",
            },
            {
                "response_status": 400,
                "response": {
                    "error": {"code": "invalid_json", "message": "invalid JSON body"}
                },
                "log_messages": ["invalid JSON"],
            },
        ),
        (
            {},
            {"sc-signature": "invalid-4321"},
            {
                "response_status": 401,
                "response": {
                    "error": {
                        "code": "invalid_signature",
                        "message": "invalid signature on request body",
                    }
                },
                "log_messages": ["invalid signature"],
            },
        ),
    ],
    indirect=["webhook_body"],
    ids=[
        "verify",
        "vehicle_state",
        "vehicle_state_fuel",
        "vehicle_mismatch",
        "vehicle_error",
        "test_mode",
        "broad_auth_error",
        "irrelevant_auth_error",
        "invalid_json",
        "invalid_signature",
    ],
)
async def test_webhook_scenarios(
    webhook_scenario: Callable[[], Awaitable[None]],
) -> None:
    await webhook_scenario()


@pytest.mark.usefixtures("enable_all_entities")
@pytest.mark.parametrize("platform", [Platform.SENSOR])
@pytest.mark.parametrize(
    "vehicle_fixture",
    ["vw_id_4", "jaguar_ipace", "jaguar_ipace2", "byd_seal", "polestar_2"],
)
@pytest.mark.parametrize(
    ("webhook_body", "webhook_headers", "expected"),
    [("all", {"sc-signature": "1234"}, {})],  # JSON fixture
    indirect=["webhook_body"],
    ids=["vehicle_state_all"],
)
async def test_webhook_update(webhook_scenario: Callable[[], Awaitable[None]]) -> None:
    await webhook_scenario()


@pytest.mark.usefixtures("enable_specified_entities")
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
@pytest.mark.parametrize(
    "enabled_entities",
    [{EntityDescriptionKey.LOW_VOLTAGE_BATTERY_LEVEL}],
)
async def test_polling_v3_sensor(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test sensor refresh fails on v3 only items."""

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        pref_disable_polling=True,
    )

    await setup_added_integration(hass, mock_config_entry)
    assert aioclient_mock.call_count == 0

    await async_update_entity(hass, "sensor.vw_id_4_low_voltage_battery")

    assert aioclient_mock.call_count == 0
    assert "Unsupported update requests for: low_voltage_battery_level" in caplog.text


@pytest.mark.usefixtures("enable_specified_entities")
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
@pytest.mark.parametrize(
    "enabled_entities",
    [
        {
            EntityDescriptionKey.BATTERY_LEVEL,
            EntityDescriptionKey.LOW_VOLTAGE_BATTERY_LEVEL,
        }
    ],
)
async def test_polling_v3_sensor_retains_healthy_coordinator(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle: AsyncMock,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
) -> None:
    """Test sensor refresh on v3 only item does not make others unavailable."""

    mock_config_entry.add_to_hass(hass)
    await setup_added_integration(hass, mock_config_entry)
    assert hass.states.get("sensor.vw_id_4_battery").state != "unavailable"
    await async_update_entity(hass, "sensor.vw_id_4_low_voltage_battery")
    assert hass.states.get("sensor.vw_id_4_battery").state != "unavailable"
    assert "Unsupported update requests for: low_voltage_battery_level" in caplog.text


@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
@pytest.mark.parametrize("enabled_scopes", [[*REQUIRED_SCOPES, "read_battery"]])
@pytest.mark.parametrize(
    "enabled_entities",
    [DEFAULT_ENABLED_ENTITY_DESCRIPTION_KEYS | {EntityDescriptionKey.BATTERY_CAPACITY}],
)
async def test_limited_scopes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
    vehicle: AsyncMock,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test sensors when only limited scopes are enabled."""

    entity_id = "sensor.vw_id_4_battery"
    expected_calls = 0

    await setup_integration(hass, mock_config_entry)
    assert entity_registry.async_get(entity_id) == snapshot(
        name=f"{entity_id}-registry"
    )
    assert hass.states.get(entity_id) == snapshot(name=entity_id)
    assert aioclient_mock.call_count == (expected_calls := expected_calls + 1)
    assert aioclient_mock.mock_calls[-1] == snapshot(
        name=f"{entity_id}-api-battery-request"
    )


@pytest.mark.usefixtures("enable_all_entities")
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
@pytest.mark.parametrize("api_response_type", ["imperial"])
async def test_unit_conversion(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
    vehicle: AsyncMock,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test sensors that could return imperial units."""

    entity_id = "sensor.vw_id_4_odometer"
    expected_calls = 0

    await setup_integration(hass, mock_config_entry)
    assert entity_registry.async_get(entity_id) == snapshot(
        name=f"{entity_id}-registry"
    )
    assert hass.states.get(entity_id) == snapshot(name=entity_id)

    assert aioclient_mock.call_count == (expected_calls := expected_calls + 1)
    assert aioclient_mock.mock_calls[-1] == snapshot(
        name=f"{entity_id}-api-full-batch-request"
    )

    await async_update_entity(hass, entity_id)

    assert aioclient_mock.call_count == (expected_calls := expected_calls + 1)
    assert aioclient_mock.mock_calls[-1] == snapshot(
        name=f"{entity_id}-api-odometer-request"
    )


@pytest.mark.usefixtures("enable_all_entities")
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
@pytest.mark.parametrize("expires_at", [1756764425])
@pytest.mark.parametrize("api_response_type", ["unauthorized"])
async def test_expired_token_update_with_polling_disabled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
    vehicle: AsyncMock,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test update for expired token when polling is disabled."""

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        pref_disable_polling=True,
    )

    aioclient_mock.post(
        OAUTH2_TOKEN_LEGACY,
        status=400,
        json={
            "error": "invalid_grant",
            "error_description": "Invalid or expired refresh token.",
        },
    )

    await setup_added_integration(hass, mock_config_entry)

    assert len(hass.config_entries.flow.async_progress()) == 0
    await async_update_entity(hass, "sensor.vw_id_4_battery")
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["step_id"] == "reauth_confirm"
    assert flows[0]["context"]["source"] == "reauth"


@pytest.mark.usefixtures("enable_all_entities")
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
@pytest.mark.parametrize("expires_at", [1756764425])
@pytest.mark.parametrize("api_response_type", ["unauthorized"])
async def test_expired_token_invalid_update_with_polling_disabled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
    vehicle: AsyncMock,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test update for expired token when polling is disabled."""

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        pref_disable_polling=True,
    )

    aioclient_mock.post(
        OAUTH2_TOKEN_LEGACY,
        status=500,
        json={
            "error": "server_error",
            "error_description": "A server error occurred.",
        },
    )

    await setup_added_integration(hass, mock_config_entry)

    assert len(hass.config_entries.flow.async_progress()) == 0
    await async_update_entity(hass, "sensor.vw_id_4_battery")
    await hass.async_block_till_done()
    assert len(hass.config_entries.flow.async_progress()) == 0


RESTORE_STATE_PARAMETRIZE_ARGS = [
    (
        "entity_id",
        "stored_data",
        "sensor_state",
        "coordinator_data",
    ),
    [
        (
            "sensor.vw_id_4_battery",
            {"raw_value": 0.34},
            "34",
            {"tractionbattery-stateofcharge": {"value": 0.34}},
        ),
        (
            "sensor.vw_id_4_range",
            {"raw_value": 45.2, "unit_system": "imperial"},
            "72.7423488",
            {
                "tractionbattery-range": {"value": 45.2},
                "tractionbattery-range:unit_system": "imperial",
            },
        ),
        (
            "sensor.vw_id_4_range",
            {
                "raw_value": 45.2,
                "data_age": "2025-05-29T19:47:32+00:00",
                "fetched_at": "2025-05-29T20:09:57+00:00",
            },
            "45.2",
            {
                "tractionbattery-range": {"value": 45.2},
                "tractionbattery-range:data_age": dt.datetime(
                    2025, 5, 29, 19, 47, 32, tzinfo=dt.UTC
                ),
                "tractionbattery-range:fetched_at": dt.datetime(
                    2025, 5, 29, 20, 9, 57, tzinfo=dt.UTC
                ),
            },
        ),
        (
            "sensor.vw_id_4_tire_pressure_front_right",
            {
                "raw_value": [
                    {
                        "column": VEHICLE_RIGHT_COLUMN,
                        "row": VEHICLE_FRONT_ROW,
                        "tirePressure": 234,
                    },
                ],
            },
            "234",
            {
                "wheel-tires": {
                    "values": [
                        {
                            "column": VEHICLE_RIGHT_COLUMN,
                            "row": VEHICLE_FRONT_ROW,
                            "tirePressure": 234,
                        },
                    ],
                },
            },
        ),
    ],
]
RESTORE_STATE_PARAMETRIZE_IDS = [
    "value_only",
    "value_and_unit_system",
    "value_and_timestamps",
    "value_complex",
]


@pytest.mark.usefixtures("enable_all_entities")
@pytest.mark.parametrize(
    *RESTORE_STATE_PARAMETRIZE_ARGS,
    ids=RESTORE_STATE_PARAMETRIZE_IDS,
)
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
async def test_restore_sensor_save_state(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
    vehicle_attributes: dict,
    entity_id: str,
    stored_data: dict,
    sensor_state: Any,
    coordinator_data: dict,
) -> None:
    """Test saving sensor/coordinator state."""

    await setup_integration(hass, mock_config_entry)

    coordinator = mock_config_entry.runtime_data.coordinators[vehicle_attributes["id"]]
    coordinator.data = coordinator_data

    await async_mock_restore_state_shutdown_restart(hass)  # trigger saving state

    stored_entity_data = [
        item["extra_data"]
        for item in hass_storage[RESTORE_STATE_KEY]["data"]
        if item["state"]["entity_id"] == entity_id
    ]

    assert stored_entity_data[0] == stored_data
    assert stored_entity_data == snapshot


@pytest.mark.usefixtures("enable_all_entities")
@pytest.mark.parametrize(
    *RESTORE_STATE_PARAMETRIZE_ARGS,
    ids=RESTORE_STATE_PARAMETRIZE_IDS,
)
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
async def test_restore_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    vehicle_attributes: dict,
    entity_id: str,
    stored_data: dict,
    sensor_state: Any,
    coordinator_data: dict,
) -> None:
    """Test sensor restore state."""

    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State(
                    entity_id,
                    "does-not-matter-for-this-test",
                ),
                stored_data,
            ),
        ),
    )

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        pref_disable_polling=True,
    )

    await setup_added_integration(hass, mock_config_entry)

    coordinator = mock_config_entry.runtime_data.coordinators[vehicle_attributes["id"]]
    state = hass.states.get(entity_id)
    assert state
    assert state.state == sensor_state
    assert coordinator.data == coordinator_data


RESTORE_STATE_V2_PARAMETRIZE_ARGS = [
    (
        "entities",
        "expected_coordinator_data",
        "values_sort_key",
    ),
    [
        (
            {
                "sensor.vw_id_4_tire_pressure_front_left": {
                    "stored_data": {"raw_value": 235},
                    "expected_state": "235",
                },
                "sensor.vw_id_4_tire_pressure_back_left": {
                    "stored_data": {"raw_value": 234},
                    "expected_state": "234",
                },
                "sensor.vw_id_4_tire_pressure_front_right": {
                    "stored_data": {"raw_value": 233},
                    "expected_state": "233",
                },
                "sensor.vw_id_4_tire_pressure_back_right": {
                    "stored_data": {"raw_value": 232},
                    "expected_state": "232",
                },
            },
            {
                "wheel-tires": {
                    "columnCount": 2,
                    "rowCount": 2,
                    "values": [
                        {
                            "column": VEHICLE_LEFT_COLUMN,
                            "row": VEHICLE_FRONT_ROW,
                            "tirePressure": 235,
                        },
                        {
                            "column": VEHICLE_LEFT_COLUMN,
                            "row": VEHICLE_BACK_ROW,
                            "tirePressure": 234,
                        },
                        {
                            "column": VEHICLE_RIGHT_COLUMN,
                            "row": VEHICLE_FRONT_ROW,
                            "tirePressure": 233,
                        },
                        {
                            "column": VEHICLE_RIGHT_COLUMN,
                            "row": VEHICLE_BACK_ROW,
                            "tirePressure": 232,
                        },
                    ],
                },
            },
            itemgetter("column", "row"),
        )
    ],
]

RESTORE_STATE_V2_PARAMETRIZE_IDS = ["tire_pressures"]


@pytest.mark.usefixtures("enable_all_entities")
@pytest.mark.parametrize(
    *RESTORE_STATE_V2_PARAMETRIZE_ARGS,
    ids=RESTORE_STATE_V2_PARAMETRIZE_IDS,
)
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
async def test_restore_state_from_v2(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    vehicle_attributes: dict,
    entities: dict,
    expected_coordinator_data: dict,
    values_sort_key: Callable[[dict], tuple] | None,
) -> None:
    """Test sensor restore state."""

    mock_restore_cache_with_extra_data(
        hass,
        tuple(
            (
                State(
                    entity_id,
                    "does-not-matter-for-this-test",
                ),
                entity_config["stored_data"],
            )
            for entity_id, entity_config in entities.items()
        ),
    )

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        pref_disable_polling=True,
    )

    await setup_added_integration(hass, mock_config_entry)

    coordinator = mock_config_entry.runtime_data.coordinators[vehicle_attributes["id"]]

    coordinator_data = {
        key: data
        | (
            {"values": sorted(data["values"], key=values_sort_key)}
            if values_sort_key and "values" in data
            else {}
        )
        for key, data in coordinator.data.items()
    }

    assert coordinator_data == expected_coordinator_data

    for entity_id, entity_config in entities.items():
        state = hass.states.get(entity_id)
        assert state
        assert state.state == entity_config["expected_state"]


async def test_async_update_internals(
    hass: HomeAssistant,
) -> None:
    """Test that coordinator does not have sensor added during update of a disabled entity."""

    @dataclass(kw_only=True)
    class MockCoordinator:
        vehicle_id: str | None = None
        vin: str | None = None
        version: APIVersion | None = None

    @dataclass(kw_only=True)
    class MockEntityDescription:
        key: str | None = None

    @dataclass(kw_only=True)
    class MockRegistryEntry:
        disabled: bool = False

    coordinator = MockCoordinator()
    description = MockEntityDescription()
    description.key = EntityDescriptionKey.BATTERY_LEVEL
    entity = SmartcarEntity[float, float](cast("Any", coordinator), description)
    entity.registry_entry = MockRegistryEntry()

    # prove that the failure occurs when enabled
    with pytest.raises(AttributeError) as excinfo:
        await entity.async_update()
    assert excinfo.value.obj == coordinator
    assert excinfo.value.name == "batch_sensor"

    # and then it does not when it's disabled
    entity.registry_entry.disabled = True
    await entity.async_update()


def test_entity_registry_enabled_default_readonly(
    hass: HomeAssistant,
) -> None:
    """Test entity_registry_enabled_default is readonly."""

    with pytest.raises(AttributeError) as excinfo:
        SmartcarSensorDescription(
            key="mock_description",
            value_key_path="mock_path",
            entity_registry_enabled_default=False,
        )

    assert (
        excinfo.value.args[0]
        == "readonly; configure via smartcar.const.DEFAULT_ENABLED_ENTITY_DESCRIPTION_KEYS"
    )
