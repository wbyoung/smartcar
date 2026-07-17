"""Test services for the Smartcar integration."""

from typing import Any
from unittest.mock import AsyncMock

from homeassistant.components.lock import LockState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from syrupy.assertion import SnapshotAssertion

from custom_components.smartcar.const import DOMAIN
from custom_components.smartcar.services import (
    ATTR_CONFIG_ENTRY,
    ATTR_VIN,
    SERVICE_NAME_LOCK_DOORS,
    SERVICE_NAME_UNLOCK_DOORS,
)
from custom_components.smartcar.types import APIVersion, SmartcarAPIError

from . import MOCK_API_ENDPOINT, MOCK_API_ENDPOINT_LEGACY, setup_added_integration

NO_ERROR = None.__class__


@pytest.mark.usefixtures("init_integration")
def test_has_services(
    hass: HomeAssistant,
) -> None:
    """Test the existence of the Smartcar Service."""
    assert hass.services.has_service(DOMAIN, SERVICE_NAME_LOCK_DOORS)
    assert hass.services.has_service(DOMAIN, SERVICE_NAME_UNLOCK_DOORS)


@pytest.mark.parametrize("client_id_version", ["v2", "v3"])
@pytest.mark.parametrize("vehicle_fixture", ["unknown_make"])
@pytest.mark.parametrize(
    "scenario",
    [
        {
            "call": SERVICE_NAME_LOCK_DOORS,
            "expected_state": LockState.LOCKED,
        },
        {
            "call": SERVICE_NAME_UNLOCK_DOORS,
            "expected_state": LockState.UNLOCKED,
        },
        {
            "call": SERVICE_NAME_LOCK_DOORS,
            "expected_state": LockState.LOCKED,
            "attrs": {
                ATTR_VIN: "",
            },
        },
        {
            "call": SERVICE_NAME_LOCK_DOORS,
            "status": 409,
            "status_slug": "unreachable",
            "expected_state": STATE_UNAVAILABLE,
            "expected_raises": SmartcarAPIError,
            "expected_api_calls": 1,
        },
        {
            "call": SERVICE_NAME_LOCK_DOORS,
            "attrs": {
                ATTR_CONFIG_ENTRY: "invalid_entry",
            },
            "expected_state": STATE_UNAVAILABLE,
            "expected_raises": ServiceValidationError,
            "expected_api_calls": 0,
        },
    ],
    ids=[
        "lock_doors",
        "unlock_doors",
        "lock_doors_no_vin",
        "unreachable",
        "invalid_config_entry",
    ],
)
async def test_door_closure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    scenario: dict[str, Any],
    vehicle: AsyncMock,
    client_id_version: APIVersion,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
):
    """Test door closure related service calls."""

    call = scenario["call"]
    attrs = scenario.get("attrs", {})
    api_status = scenario.get("status", 200)
    api_status_slug = scenario.get("status_slug", "success")
    expected_state = scenario["expected_state"]
    expected_raises = scenario.get("expected_raises", NO_ERROR)
    expected_api_calls = scenario.get("expected_api_calls", 1)

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        pref_disable_polling=True,
    )

    await setup_added_integration(hass, mock_config_entry)
    assert len(aioclient_mock.mock_calls) == 0

    if client_id_version == "v2":
        aioclient_mock.post(
            f"{MOCK_API_ENDPOINT_LEGACY}/vehicles/{vehicle['id']}/security",
            status=api_status,
            json={
                "message": "Some message related to the action unused by our code",
                "status": api_status_slug,
            },
        )
    else:
        assert client_id_version == "v3"
        aioclient_mock.post(
            f"{MOCK_API_ENDPOINT}/vehicles/{vehicle['id']}/commands/security/lock",
            status=api_status,
            json={
                "message": "Some message related to the action unused by our code",
                "status": api_status_slug,
            },
        )
        aioclient_mock.post(
            f"{MOCK_API_ENDPOINT}/vehicles/{vehicle['id']}/commands/security/unlock",
            status=api_status,
            json={
                "message": "Some message related to the action unused by our code",
                "status": api_status_slug,
            },
        )

    try:
        await hass.services.async_call(
            DOMAIN,
            call,
            {ATTR_VIN: vehicle["vin"], ATTR_CONFIG_ENTRY: mock_config_entry.entry_id}
            | attrs,
            blocking=True,
        )
    except Exception as error:  # noqa: BLE001
        raised_error = error
    else:
        raised_error = None  # type: ignore[assignment]

    await hass.async_block_till_done()

    lock_state = hass.states.get("lock.smartcar_784n_door_lock")
    assert lock_state.state == expected_state
    assert isinstance(
        raised_error,
        expected_raises,
    )

    assert len(aioclient_mock.mock_calls) == expected_api_calls
    assert [tuple(mock_call) for mock_call in aioclient_mock.mock_calls] == snapshot(
        name="api-calls"
    )

    if expected_raises != NO_ERROR:
        assert raised_error == snapshot(name="error")
