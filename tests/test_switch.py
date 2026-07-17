"""Test switch entities."""

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

from aiohttp import ClientResponseError
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    Platform,
)
from homeassistant.core import HomeAssistant, State
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from syrupy.assertion import SnapshotAssertion

from custom_components.smartcar import switch as switch_module
from custom_components.smartcar.types import APIVersion

from . import (
    MOCK_API_ENDPOINT,
    MOCK_API_ENDPOINT_LEGACY,
    setup_added_integration,
    setup_integration,
)

NO_ERROR = None.__class__


@pytest.mark.parametrize("client_id_version", ["v2", "v3"])
@pytest.mark.parametrize(
    (
        "service_action",
        "api_status",
        "api_status_slug",
        "expected_state",
        "expected_raises",
        "api_calls",
    ),
    [
        (SERVICE_TURN_ON, 200, "success", STATE_ON, NO_ERROR, 1),
        (SERVICE_TURN_OFF, 200, "success", STATE_OFF, NO_ERROR, 1),
        (SERVICE_TURN_ON, 409, "unreachable", STATE_OFF, NO_ERROR, 1),
        (SERVICE_TURN_OFF, 409, "unreachable", STATE_OFF, NO_ERROR, 1),
        (SERVICE_TURN_ON, 401, "unauthroized", STATE_OFF, NO_ERROR, 1),
        (SERVICE_TURN_OFF, 401, "unauthroized", STATE_OFF, NO_ERROR, 1),
        (SERVICE_TURN_OFF, 500, "server", STATE_OFF, NO_ERROR, 4),
        (SERVICE_TURN_OFF, 503, "unavailable", STATE_OFF, ClientResponseError, 1),
    ],
)
@pytest.mark.parametrize("vehicle_fixture", ["unknown_make"])
async def test_switch(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
    vehicle: AsyncMock,
    service_action: str,
    api_status: int,
    api_status_slug: str,
    expected_state: str,
    expected_raises: Exception,
    api_calls: int,
    client_id_version: APIVersion,
) -> None:
    """Test switching charging on/off."""

    await setup_integration(hass, mock_config_entry)
    assert len(aioclient_mock.mock_calls) == 1

    if client_id_version == "v2":
        aioclient_mock.post(
            f"{MOCK_API_ENDPOINT_LEGACY}/vehicles/{vehicle['id']}/charge",
            status=api_status,
            json={
                "message": "Some message related to the action unused by our code",
                "status": api_status_slug,
            },
        )
    else:
        assert client_id_version == "v3"
        aioclient_mock.post(
            f"{MOCK_API_ENDPOINT}/vehicles/{vehicle['id']}/commands/charge/start",
            status=api_status,
            json={
                "message": "Some message related to the action unused by our code",
                "status": api_status_slug,
            },
        )
        aioclient_mock.post(
            f"{MOCK_API_ENDPOINT}/vehicles/{vehicle['id']}/commands/charge/stop",
            status=api_status,
            json={
                "message": "Some message related to the action unused by our code",
                "status": api_status_slug,
            },
        )

    try:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            service_action,
            {ATTR_ENTITY_ID: "switch.smartcar_784n_charging"},
            blocking=True,
        )
    except Exception as error:  # noqa: BLE001
        raised_error = error
    else:
        raised_error = None  # type: ignore[assignment]

    switch_state = hass.states.get("switch.smartcar_784n_charging")
    assert switch_state.state == expected_state
    assert isinstance(
        raised_error,
        expected_raises,  # type: ignore[arg-type]
    )

    assert len(aioclient_mock.mock_calls) == 1 + api_calls
    assert [tuple(mock_call) for mock_call in aioclient_mock.mock_calls[1:]] == snapshot


@pytest.mark.usefixtures("enable_all_entities")
@pytest.mark.parametrize("platform", [Platform.SWITCH])
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4", "jaguar_ipace", "byd_seal"])
@pytest.mark.parametrize(
    ("webhook_body", "webhook_headers", "expected"),
    [("all", {"sc-signature": "1234"}, {})],  # JSON fixture
    indirect=["webhook_body"],
    ids=["vehicle_state_all"],
)
async def test_webhook_update(webhook_scenario: Callable[[], Awaitable[None]]) -> None:
    await webhook_scenario()


def test_hvac_bool_cast() -> None:
    """Test extraction of HVAC booleans from webhook signal bodies."""
    assert switch_module._hvac_bool({"value": True}) is True
    assert switch_module._hvac_bool({"value": False}) is False
    assert switch_module._hvac_bool({}) is None
    assert switch_module._hvac_bool(True) is True  # noqa: FBT003
    assert switch_module._hvac_bool(None) is None


@pytest.mark.parametrize("client_id_version", ["v2", "v3"])
@pytest.mark.parametrize(
    (
        "service_action",
        "api_status",
        "api_status_slug",
        "expected_state",
        "expected_v2_action",
    ),
    [
        (SERVICE_TURN_ON, 200, "success", STATE_ON, "START"),
        (SERVICE_TURN_OFF, 200, "success", STATE_OFF, "STOP"),
        (SERVICE_TURN_ON, 409, "unreachable", STATE_OFF, "START"),
        (SERVICE_TURN_OFF, 409, "unreachable", STATE_OFF, "STOP"),
    ],
    ids=["turn_on", "turn_off", "turn_on_unreachable", "turn_off_unreachable"],
)
@pytest.mark.parametrize("vehicle_fixture", ["unknown_make"])
async def test_climate_switch(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle: AsyncMock,
    service_action: str,
    api_status: int,
    api_status_slug: str,
    expected_state: str,
    expected_v2_action: str,
    client_id_version: APIVersion,
) -> None:
    """Test starting/stopping climate (preconditioning)."""

    await setup_integration(hass, mock_config_entry)
    assert len(aioclient_mock.mock_calls) == 1

    # seed HVAC data (not present in the vehicle fixture) so the climate
    # switch becomes available and starts from a known state
    coordinator = mock_config_entry.runtime_data.coordinators[vehicle["id"]]
    coordinator.async_set_updated_data(
        {**(coordinator.data or {}), "hvac-iscabinhvacactive": {"value": False}}
    )
    await hass.async_block_till_done()

    assert hass.states.get("switch.smartcar_784n_climate").state == STATE_OFF

    if client_id_version == "v2":
        aioclient_mock.post(
            f"{MOCK_API_ENDPOINT_LEGACY}/vehicles/{vehicle['id']}/climate",
            status=api_status,
            json={
                "message": "Some message related to the action unused by our code",
                "status": api_status_slug,
            },
        )
    else:
        assert client_id_version == "v3"
        aioclient_mock.post(
            f"{MOCK_API_ENDPOINT}/vehicles/{vehicle['id']}/commands/climate/start",
            status=api_status,
            json={
                "message": "Some message related to the action unused by our code",
                "status": api_status_slug,
            },
        )
        aioclient_mock.post(
            f"{MOCK_API_ENDPOINT}/vehicles/{vehicle['id']}/commands/climate/stop",
            status=api_status,
            json={
                "message": "Some message related to the action unused by our code",
                "status": api_status_slug,
            },
        )

    await hass.services.async_call(
        SWITCH_DOMAIN,
        service_action,
        {ATTR_ENTITY_ID: "switch.smartcar_784n_climate"},
        blocking=True,
    )

    switch_state = hass.states.get("switch.smartcar_784n_climate")
    assert switch_state.state == expected_state

    assert len(aioclient_mock.mock_calls) == 2

    (method, url, data, _headers) = aioclient_mock.mock_calls[1]
    expected_subpath = "start" if service_action == SERVICE_TURN_ON else "stop"

    assert method == "post"

    if client_id_version == "v2":
        assert str(url).endswith(f"/vehicles/{vehicle['id']}/climate")
        assert data == {"action": expected_v2_action}
    else:
        assert str(url).endswith(
            f"/vehicles/{vehicle['id']}/commands/climate/{expected_subpath}"
        )
        assert data is None


RESTORE_STATE_V2_PARAMETRIZE_ARGS = [
    (
        "entities",
        "expected_coordinator_data",
        "values_sort_key",
    ),
    [
        (
            {
                "switch.vw_id_4_charging": {
                    "stored_data": {"raw_value": "CHARGING"},
                    "expected_state": "on",
                },
            },
            {
                "charge-ischarging": {
                    "value": True,
                },
            },
            None,
        )
    ],
]

RESTORE_STATE_V2_PARAMETRIZE_IDS = ["is_charging"]


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
