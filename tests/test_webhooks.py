"""Test webhook authentication and logging."""

import json
import logging

from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.smartcar.const import CONF_APPLICATION_MANAGEMENT_TOKEN
from custom_components.smartcar.util import hmac_sha256_hexdigest

from . import setup_added_integration


@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
@pytest.mark.parametrize("valid_signature", [True, False])
async def test_webhook_does_not_log_management_token(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    vehicle_attributes: dict,
    caplog: pytest.LogCaptureFixture,
    valid_signature: bool,
) -> None:
    """Never log the signing secret, even for an invalid signature."""
    token = "synthetic-management-token-for-log-regression"  # noqa: S105
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **mock_config_entry.data,
            CONF_WEBHOOK_ID: "smartcar_log_test",
            CONF_APPLICATION_MANAGEMENT_TOKEN: token,
        },
    )
    await setup_added_integration(hass, mock_config_entry)

    body = json.dumps(
        {
            "eventType": "VEHICLE_STATE",
            "data": {"vehicle": {"id": vehicle_attributes["id"]}, "signals": []},
        }
    )
    signature = hmac_sha256_hexdigest(token, body) if valid_signature else "invalid"
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="custom_components.smartcar.webhooks"):
        client = await hass_client()
        response = await client.post(
            "/api/webhook/smartcar_log_test",
            data=body,
            headers={"Content-Type": "application/json", "SC-Signature": signature},
        )
        await hass.async_block_till_done()

    assert response.status == (204 if valid_signature else 401)
    assert "Validating" in caplog.text
    assert token not in caplog.text
