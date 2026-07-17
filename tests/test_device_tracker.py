"""Test device trackers."""

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.restore_state import STORAGE_KEY as RESTORE_STATE_KEY
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_restore_state_shutdown_restart,
    mock_restore_cache_with_extra_data,
)
from syrupy.assertion import SnapshotAssertion

from custom_components.smartcar.const import (
    DEFAULT_ENABLED_ENTITY_DESCRIPTION_KEYS,
    EntityDescriptionKey,
)

from . import setup_added_integration, setup_integration


@pytest.mark.usefixtures("enable_all_entities")
@pytest.mark.parametrize("platform", [Platform.DEVICE_TRACKER])
@pytest.mark.parametrize(
    "vehicle_fixture", ["vw_id_4", "jaguar_ipace", "byd_seal", "polestar_2"]
)
@pytest.mark.parametrize(
    ("webhook_body", "webhook_headers", "expected"),
    [("all", {"sc-signature": "1234"}, {})],  # JSON fixture
    indirect=["webhook_body"],
    ids=["vehicle_state_all"],
)
async def test_webhook_update(webhook_scenario: Callable[[], Awaitable[None]]) -> None:
    await webhook_scenario()


RESTORE_STATE_PARAMETRIZE_ARGS = [
    (
        "entity_id",
        "stored_data",
        "device_tracker_state",
        "coordinator_data",
    ),
    [
        (
            "device_tracker.vw_id_4_location",
            {"raw_value": {"latitude": 37.4292, "longitude": 122.1381}},
            "not_home",
            {"location-preciselocation": {"latitude": 37.4292, "longitude": 122.1381}},
        ),
    ],
]
RESTORE_STATE_PARAMETRIZE_IDS = [
    "location",
]


@pytest.mark.parametrize(
    *RESTORE_STATE_PARAMETRIZE_ARGS,
    ids=RESTORE_STATE_PARAMETRIZE_IDS,
)
@pytest.mark.usefixtures("enable_specified_entities")
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
@pytest.mark.parametrize(
    "enabled_entities",
    [DEFAULT_ENABLED_ENTITY_DESCRIPTION_KEYS | {EntityDescriptionKey.LOCATION}],
)
async def test_restore_device_tracker_save_state(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
    vehicle_attributes: dict,
    entity_id: str,
    stored_data: dict,
    device_tracker_state: Any,
    coordinator_data: dict,
) -> None:
    """Test saving device tracker/coordinator state."""

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


@pytest.mark.parametrize(
    *RESTORE_STATE_PARAMETRIZE_ARGS,
    ids=RESTORE_STATE_PARAMETRIZE_IDS,
)
@pytest.mark.usefixtures("enable_specified_entities")
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
@pytest.mark.parametrize(
    "enabled_entities",
    [DEFAULT_ENABLED_ENTITY_DESCRIPTION_KEYS | {EntityDescriptionKey.LOCATION}],
)
async def test_restore_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    vehicle_attributes: dict,
    entity_id: str,
    stored_data: dict,
    device_tracker_state: Any,
    coordinator_data: dict,
) -> None:
    """Test device tracker restore state."""

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
    assert state.state == device_tracker_state
    assert coordinator.data == coordinator_data
