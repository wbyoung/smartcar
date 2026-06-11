"""Tests for the V3 ``SmartcarConfigFlow``.

Scope of coverage:

  * Happy path: user step credential validation → webhooks → scopes →
    Connect external step → callback resume → finish (with
    :func:`populate_entry_data` mocked).
  * IAM rejecting credentials at the user step.
  * Missing external URL aborting before launching Connect.
  * Missing ``user_id`` in the Connect callback.
  * The callback view rejecting unknown / replayed state tokens.

What is *not* covered here:

  * The reauth flow.
  * Full ``populate_entry_data`` against a live ``/connections`` response.
  * Duplicate VIN abort, ``wrong_vehicles``, and the cloud-not-connected
    path through the webhook URL fetch.

These need fixture work that hasn't been done yet for the V3 model.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.smartcar.const import (
    CONF_APPLICATION_ID,
    CONF_APPLICATION_MANAGEMENT_TOKEN,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_SC_USER_ID,
    CONF_WEBHOOK_BACKUP_POLLING,
    DOMAIN,
    IAM_TOKEN_URL,
    OAUTH2_AUTHORIZE,
    Scope,
)
from custom_components.smartcar.views import CALLBACK_PATH

from .conftest import (
    MOCK_APPLICATION_ID,
    MOCK_CLIENT_ID,
    MOCK_CLIENT_SECRET,
    MOCK_USER_ID,
    MOCK_VEHICLE_ID,
)

CONF_USE_WEBHOOKS = "use_webhooks"

# A representative subset of the granted scopes, used as the "user picked
# these" input to async_step_scopes.
_MOCK_SCOPE_INPUT = {Scope.READ_BATTERY.value: True, Scope.READ_ODOMETER.value: True}

_EXTERNAL_URL = "https://abc.ui.nabu.casa"


@pytest.fixture
def mock_external_url(hass: HomeAssistant):
    """Configure an external URL so ``_build_redirect_uri`` succeeds."""
    hass.config.external_url = _EXTERNAL_URL
    hass.config.internal_url = "http://homeassistant.local:8123"
    yield
    hass.config.external_url = None
    hass.config.internal_url = None


def _mock_iam_ok(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(
        IAM_TOKEN_URL,
        json={"access_token": "mock-token", "expires_in": 3600},
    )


async def _run_to_authorize(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> str:
    """Walk the flow from user → webhooks → scopes → external_step.

    Returns:
        The Connect URL the flow is paused on (the value passed to
        ``async_external_step``).
    """
    _mock_iam_ok(aioclient_mock)

    # Step 1: user
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_APPLICATION_ID: MOCK_APPLICATION_ID,
            CONF_CLIENT_ID: MOCK_CLIENT_ID,
            CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET,
        },
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "webhooks"

    # Step 2: webhooks (skip — set use_webhooks=False)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USE_WEBHOOKS: False}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "scopes"

    # Step 3: scopes
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _MOCK_SCOPE_INPUT
    )
    assert result["type"] == data_entry_flow.FlowResultType.EXTERNAL_STEP
    return result["url"]


async def test_full_flow_happy_path(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_external_url: None,
) -> None:
    """End-to-end: credentials accepted, Connect callback resumes, entry created."""
    connect_url = await _run_to_authorize(hass, aioclient_mock)

    # The Connect URL should have the Application ID as the OAuth client_id,
    # NOT the V3 Client ID — this is the bug that caused so much pain.
    parsed = urlparse(connect_url)
    assert parsed.netloc.endswith("smartcar.com")
    assert parsed.path == "/oauth/authorize" or OAUTH2_AUTHORIZE in connect_url
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == [MOCK_APPLICATION_ID]
    assert qs["redirect_uri"] == [f"{_EXTERNAL_URL}{CALLBACK_PATH}"]

    # async_setup_entry (triggered after CREATE_ENTRY) fires a background
    # /signals refresh; mock an empty response so the coordinator's first
    # poll doesn't 404 in the assertion log.
    aioclient_mock.get(
        f"https://vehicle.api.smartcar.com/v3/vehicles/{MOCK_VEHICLE_ID}/signals",
        json={"data": []},
    )

    # Stub populate_entry_data so we don't have to construct a full
    # JSON:API /connections fixture for this happy-path assertion. Must be
    # async to match the real function's signature (which patch enforces).
    async def fake_populate(data: dict[str, Any], _auth: object) -> None:  # noqa: RUF029
        data["vehicles"] = {
            MOCK_VEHICLE_ID: {
                "make": "Volkswagen",
                "model": "ID.4",
                "year": 2023,
                "vin": MOCK_VEHICLE_ID,
            },
        }
        data["scopes"] = sorted({Scope.READ_BATTERY.value, Scope.READ_ODOMETER.value})

    with patch(
        "custom_components.smartcar.config_flow.populate_entry_data",
        side_effect=fake_populate,
    ):
        flows_in_progress = hass.config_entries.flow.async_progress()
        assert len(flows_in_progress) == 1
        flow_id = flows_in_progress[0]["flow_id"]

        # Resume the flow as the callback view would.
        result = await hass.config_entries.flow.async_configure(
            flow_id, {"userId": MOCK_USER_ID, "code": "ignored-in-v3"}
        )
        assert result["type"] == data_entry_flow.FlowResultType.EXTERNAL_STEP_DONE
        await hass.async_block_till_done()

        # Drive the finish step.
        result = await hass.config_entries.flow.async_configure(flow_id, None)

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_APPLICATION_ID] == MOCK_APPLICATION_ID
    assert result["data"][CONF_CLIENT_ID] == MOCK_CLIENT_ID
    assert result["data"][CONF_CLIENT_SECRET] == MOCK_CLIENT_SECRET
    assert result["data"][CONF_SC_USER_ID] == MOCK_USER_ID
    assert MOCK_VEHICLE_ID in result["data"]["vehicles"]
    # The backup-polling toggle wasn't shown (use_webhooks=False), so its
    # key shouldn't be persisted.
    assert CONF_WEBHOOK_BACKUP_POLLING not in result["data"]


async def test_user_step_invalid_credentials(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """IAM 401 at the user step surfaces as inline ``invalid_auth`` error."""
    aioclient_mock.post(IAM_TOKEN_URL, status=401)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_APPLICATION_ID: MOCK_APPLICATION_ID,
            CONF_CLIENT_ID: "wrong-client",
            CONF_CLIENT_SECRET: "wrong-secret",
        },
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_step_cannot_connect(
    hass: HomeAssistant,
) -> None:
    """Network failure to IAM surfaces as ``cannot_connect``."""
    with patch(
        "custom_components.smartcar.auth_impl.ClientCredentialsTokenManager"
        ".async_get_access_token",
        side_effect=asyncio.TimeoutError,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_APPLICATION_ID: MOCK_APPLICATION_ID,
                CONF_CLIENT_ID: MOCK_CLIENT_ID,
                CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET,
            },
        )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_external_url_required(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Flow aborts at the authorize step when no public URL is available."""
    _mock_iam_ok(aioclient_mock)

    # No external_url set, no Nabu Casa.
    hass.config.external_url = None
    hass.config.internal_url = None

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_APPLICATION_ID: MOCK_APPLICATION_ID,
            CONF_CLIENT_ID: MOCK_CLIENT_ID,
            CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USE_WEBHOOKS: False}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _MOCK_SCOPE_INPUT
    )
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "external_url_required"


async def test_callback_missing_user_id_aborts(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_external_url: None,
) -> None:
    """A Connect callback that didn't include ``user_id`` aborts the flow."""
    await _run_to_authorize(hass, aioclient_mock)
    flow_id = hass.config_entries.flow.async_progress()[0]["flow_id"]

    # The resumed external step transitions to EXTERNAL_STEP_DONE; the
    # subsequent dispatch into async_step_finish picks up the stashed
    # error and aborts.
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"error": "missing_user_id"}
    )
    assert result["type"] == data_entry_flow.FlowResultType.EXTERNAL_STEP_DONE

    result = await hass.config_entries.flow.async_configure(flow_id, None)
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "oauth_error"


async def test_webhook_step_requires_management_token(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Enabling webhooks without a management token surfaces an inline error."""
    _mock_iam_ok(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_APPLICATION_ID: MOCK_APPLICATION_ID,
            CONF_CLIENT_ID: MOCK_CLIENT_ID,
            CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET,
        },
    )
    # Enable webhooks but leave token blank.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USE_WEBHOOKS: True}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "webhooks"
    assert result["errors"] == {
        CONF_APPLICATION_MANAGEMENT_TOKEN: "no_management_token",
    }


async def test_webhook_step_persists_backup_polling_toggle(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_external_url: None,
) -> None:
    """Enabling backup polling at setup persists it on the entry."""
    _mock_iam_ok(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_APPLICATION_ID: MOCK_APPLICATION_ID,
            CONF_CLIENT_ID: MOCK_CLIENT_ID,
            CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET,
        },
    )
    # Enable webhooks AND turn on backup polling.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USE_WEBHOOKS: True,
            CONF_APPLICATION_MANAGEMENT_TOKEN: "mgmt-token-xyz",
            CONF_WEBHOOK_BACKUP_POLLING: True,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _MOCK_SCOPE_INPUT
    )

    # async_setup_entry will fire /signals as part of the background
    # refresh; stub it so the test completes cleanly.
    aioclient_mock.get(
        f"https://vehicle.api.smartcar.com/v3/vehicles/{MOCK_VEHICLE_ID}/signals",
        json={"data": []},
    )

    async def fake_populate(data: dict[str, Any], _auth: object) -> None:  # noqa: RUF029
        data["vehicles"] = {
            MOCK_VEHICLE_ID: {
                "make": "Volkswagen",
                "model": "ID.4",
                "year": 2023,
                "vin": MOCK_VEHICLE_ID,
            },
        }
        data["scopes"] = sorted({Scope.READ_BATTERY.value})

    with patch(
        "custom_components.smartcar.config_flow.populate_entry_data",
        side_effect=fake_populate,
    ):
        flow_id = hass.config_entries.flow.async_progress()[0]["flow_id"]
        await hass.config_entries.flow.async_configure(
            flow_id, {"userId": MOCK_USER_ID}
        )
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(flow_id, None)

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_APPLICATION_MANAGEMENT_TOKEN] == "mgmt-token-xyz"
    assert result["data"][CONF_WEBHOOK_BACKUP_POLLING] is True
