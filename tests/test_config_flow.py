"""Test the Smartcar config flow."""

from contextlib import nullcontext
from copy import deepcopy
from http import HTTPStatus
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    load_json_object_fixture,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator
from syrupy.assertion import SnapshotAssertion

from custom_components.smartcar.const import (
    CONF_APPLICATION_ID,
    CONF_APPLICATION_MANAGEMENT_TOKEN,
    CONF_CLOUDHOOK,
    CONFIGURABLE_SCOPES,
    DEFAULT_NAME,
    DOMAIN,
    OAUTH2_AUTHORIZE,
    OAUTH2_TOKEN,
    OAUTH2_TOKEN_LEGACY,
    REQUIRED_SCOPES,
)
from custom_components.smartcar.types import APIVersion

from . import MOCK_API_ENDPOINT, MOCK_API_ENDPOINT_LEGACY, setup_integration

REDIRECT_URL = "https://example.com/auth/external/callback"


@pytest.mark.parametrize("client_id_version", ["v2", "v3"])
@pytest.mark.usefixtures("current_request_with_host")
@pytest.mark.parametrize(
    ("setup", "entry_data", "user_input", "expected_result"),
    [
        (set(), {}, {CONF_APPLICATION_ID: "my-app-id", "use_webhooks": False}, {}),
        (
            {"missing_vin"},
            {},
            {CONF_APPLICATION_ID: "my-app-id", "use_webhooks": False},
            {},
        ),
        (
            set(),
            {},
            {
                "use_webhooks": True,
                CONF_APPLICATION_ID: "my-app-id",
                CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt",
            },
            {
                "data": {
                    CONF_APPLICATION_ID: "my-app-id",
                    CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt",
                    CONF_CLOUDHOOK: False,
                    CONF_WEBHOOK_ID: "mock_webhook_id",
                }
            },
        ),
        (
            set(),
            {},
            {CONF_APPLICATION_ID: "my-app-id", "use_webhooks": True},
            {
                "final_step": "webhooks",
                "errors": {
                    "application_management_token": "no_management_token",
                },
                "description_placeholders": {
                    "webhook_url": "webhooks-not-enabled",
                    "smartcar_url": "https://dashboard.smartcar.com/configuration",
                    "docs_url": "https://github.com/wbyoung/smartcar/#webhooks",
                },
            },
        ),
        (
            set(),
            {},
            {
                "use_webhooks": False,
                CONF_APPLICATION_ID: "my-app-id",
                CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt",
            },
            {
                "final_step": "webhooks",
                "errors": {
                    "base": "extraneous_management_token",
                },
                "description_placeholders": {
                    "webhook_url": "webhooks-not-enabled",
                    "smartcar_url": "https://dashboard.smartcar.com/configuration",
                    "docs_url": "https://github.com/wbyoung/smartcar/#webhooks",
                },
            },
        ),
        (
            {"cloud"},
            {},
            {
                "use_webhooks": True,
                CONF_APPLICATION_ID: "my-app-id",
                CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt",
            },
            {
                "data": {
                    CONF_APPLICATION_ID: "my-app-id",
                    CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt",
                    CONF_CLOUDHOOK: True,
                    CONF_WEBHOOK_ID: "mock_webhook_id",
                }
            },
        ),
        (
            {"cloud", "cloud_not_connected"},
            {},
            {
                "use_webhooks": True,
                CONF_APPLICATION_ID: "my-app-id",
                CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt",
            },
            {
                "form_type": FlowResultType.ABORT,
                "errors": {},
            },
        ),
    ],
    ids=[
        "no_webhooks",
        "no_webhooks_missing_vin",
        "webhooks",
        "webhooks_missing_token",
        "webhooks_extraneous_token",
        "cloud_webhooks",
        "cloud_not_connected",
    ],
)
async def test_full_flow(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    setup: set[str],
    entry_data: dict,
    user_input: dict,
    expected_result: dict,
    mock_smartcar_auth: AsyncMock,
    client_id_version: APIVersion,
    snapshot: SnapshotAssertion,
):
    await _test_full_flow(
        hass,
        hass_client_no_auth,
        aioclient_mock,
        setup,
        entry_data,
        user_input,
        expected_result,
        mock_smartcar_auth,
        client_id_version,
        snapshot,
    )


@pytest.mark.parametrize("client_id_version", ["v3"])
@pytest.mark.usefixtures("current_request_with_host")
@pytest.mark.parametrize(
    ("setup", "entry_data", "user_input", "expected_result"),
    [
        (
            set(),
            {},
            {"use_webhooks": False},
            {
                "final_step": "webhooks",
                "errors": {
                    "base": "no_application_id",
                },
                "description_placeholders": {
                    "webhook_url": "webhooks-not-enabled",
                    "smartcar_url": "https://dashboard.smartcar.com/configuration",
                    "docs_url": "https://github.com/wbyoung/smartcar/#webhooks",
                },
            },
        ),
        (
            {"multi_user_app"},
            {},
            {
                CONF_APPLICATION_ID: "my-app-id",
                "use_webhooks": False,
            },
            {
                "form_type": FlowResultType.ABORT,
                "abort_reason": "not_single_user_app",
                "errors": {},
            },
        ),
        (
            {"empty_connections"},
            {},
            {
                CONF_APPLICATION_ID: "my-app-id",
                "use_webhooks": False,
            },
            {
                "form_type": FlowResultType.ABORT,
                "abort_reason": "no_vehicles",
                "errors": {},
            },
        ),
    ],
    ids=[
        "missing_application_id",
        "invalid_user_configuration",
        "empty_connections",
    ],
)
async def test_full_flow_v3_only(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    setup: set[str],
    entry_data: dict,
    user_input: dict,
    expected_result: dict,
    mock_smartcar_auth: AsyncMock,
    client_id_version: APIVersion,
    snapshot: SnapshotAssertion,
):
    await _test_full_flow(
        hass,
        hass_client_no_auth,
        aioclient_mock,
        setup,
        entry_data,
        user_input,
        expected_result,
        mock_smartcar_auth,
        client_id_version,
        snapshot,
    )


async def _test_full_flow(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    setup: set[str],
    entry_data: dict,
    user_input: dict,
    expected_result: dict,
    mock_smartcar_auth: AsyncMock,
    client_id_version: APIVersion,
    snapshot: SnapshotAssertion,
):
    """Test full flow."""

    continue_steps = True
    expected_result = deepcopy(expected_result)
    final_step = expected_result.pop("final_step", None)
    expected_errors = expected_result.pop("errors", None)
    expected_abort_reason = expected_result.pop("abort_reason", None)
    expected_placeholders = expected_result.pop("description_placeholders", None)
    expected_data = expected_result.pop("data", {})
    expected_form_type = expected_result.pop(
        "form_type",
        FlowResultType.FORM
        if expected_errors is not None
        else FlowResultType.CREATE_ENTRY,
    )
    expected_aioclient_mock_calls = 0

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    if continue_steps:
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "webhooks"
        assert not result["last_step"]

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input,
        )

        continue_steps = continue_steps and final_step != "webhooks"

    if continue_steps:
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "scopes"
        assert not result["last_step"]

        selected_scopes = ["read_odometer"]
        requested_scopes = REQUIRED_SCOPES + selected_scopes
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {k: k in selected_scopes for k in CONFIGURABLE_SCOPES},
        )

        continue_steps = continue_steps and final_step != "scopes"

    if continue_steps:
        state = config_entry_oauth2_flow._encode_jwt(
            hass,
            {
                "flow_id": result["flow_id"],
                "redirect_uri": REDIRECT_URL,
            },
        )
        if client_id_version == "v2":
            expected_authorize_client_id = "mock-id"
        else:
            assert client_id_version == "v3"
            expected_authorize_client_id = "my-app-id"

        assert result["type"] is FlowResultType.EXTERNAL_STEP
        assert result["step_id"] == "auth"
        assert result["url"] == (
            f"{OAUTH2_AUTHORIZE}?response_type=code&"
            f"client_id={expected_authorize_client_id}"
            f"&redirect_uri={REDIRECT_URL}"
            f"&state={state}"
            "&mode=live"
            f"&scope={'+'.join(requested_scopes)}"
        )

        client = await hass_client_no_auth()
        resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
        assert resp.status == 200
        assert resp.headers["content-type"] == "text/html; charset=utf-8"

        vehicle_id = "36ab27d0-fd9d-4455-823a-ce30af709ffc"
        vin = "5YJSA1CN5DFP00101" if "missing_vin" not in setup else None

        if client_id_version == "v2":
            server_access_token = {
                "refresh_token": "server-refresh-token",
                "access_token": "server-access-token",
                "type": "Bearer",
                "expires_in": 60,
                "scope": " ".join(requested_scopes),
            }
            aioclient_mock.post(
                OAUTH2_TOKEN_LEGACY,
                json=server_access_token,
            )
            aioclient_mock.get(
                f"{MOCK_API_ENDPOINT_LEGACY}/vehicles",
                json={"paging": {"count": 25, "offset": 0}, "vehicles": [vehicle_id]},
            )
            aioclient_mock.get(
                f"{MOCK_API_ENDPOINT_LEGACY}/vehicles/{vehicle_id}/vin",
                json={"vin": vin},
            )
            aioclient_mock.get(
                f"{MOCK_API_ENDPOINT_LEGACY}/vehicles/{vehicle_id}",
                json={
                    "id": vehicle_id,
                    "make": "TESLA",
                    "model": "Model S",
                    "year": "2014",
                },
            )
            expected_aioclient_mock_calls += 4  # oauth token & 3 for vehicles & info
        else:
            assert client_id_version == "v3"
            server_access_token = {
                "refresh_token": None,
                "access_token": "server-access-token",
                "token_type": "bearer",
                "expires_in": 3600,
            }
            aioclient_mock.post(
                OAUTH2_TOKEN,
                json=server_access_token,
            )
            connections_fixture = "list_connections"
            if "multi_user_app" in setup:
                connections_fixture = "list_connections_with_multiple_users"
            elif "empty_connections" in setup:
                connections_fixture = "list_connections_empty"
            aioclient_mock.get(
                f"{MOCK_API_ENDPOINT}/connections",
                json=load_json_object_fixture(
                    f"api/{connections_fixture}.json",
                    DOMAIN,
                ),
            )
            aioclient_mock.get(
                f"{MOCK_API_ENDPOINT}/vehicles/{vehicle_id}/signals/vehicleidentification-vin",
                json=load_json_object_fixture(
                    f"api/get_vin_signal{'_missing' if 'missing_vin' in setup else ''}.json",
                    DOMAIN,
                ),
            )
            expected_aioclient_mock_calls += (
                3  # oauth token & 2 for connections/signals
                - (
                    1  # the signals request is never made when the flow aborts
                    if setup & {"multi_user_app", "empty_connections"}
                    else 0
                )
            )

        with (
            patch(
                "custom_components.smartcar.async_setup_entry", return_value=True
            ) as mock_setup,
            patch(
                "homeassistant.components.webhook.async_generate_id",
                return_value="mock_webhook_id",
            ),
            patch(
                "homeassistant.components.cloud.async_active_subscription",
                return_value="cloud" in setup,
            ),
            patch(
                "homeassistant.components.cloud.async_get_or_create_cloudhook",
                return_value="cloud_url",
            )
            if "cloud_not_connected" not in setup
            else nullcontext(),
        ):
            result = await hass.config_entries.flow.async_configure(result["flow_id"])

            if expected_errors is None:
                assert len(mock_setup.mock_calls) == 1

    assert result["type"] is expected_form_type
    assert len(aioclient_mock.mock_calls) == expected_aioclient_mock_calls
    assert [tuple(mock_call) for mock_call in aioclient_mock.mock_calls] == snapshot

    if expected_errors is not None:
        assert result.get("errors", {}) == expected_errors
        assert result["description_placeholders"] == expected_placeholders

        if expected_abort_reason is not None:
            assert result["reason"] == expected_abort_reason
    else:
        entries = hass.config_entries.async_entries(DOMAIN)
        assert len(entries) == 1

        config_entry = entries[0]
        assert config_entry.title == DEFAULT_NAME
        assert config_entry.unique_id == vehicle_id

        data = dict(config_entry.data)
        expected_attrs = {
            "vin": vin,
            "make": "TESLA",
            "model": "Model S",
            "year": "2014",
        }
        if "missing_vin" in setup:
            expected_attrs.pop("vin")
        assert "token" in data
        del data["token"]["expires_at"]
        assert dict(config_entry.data) == {
            "application_id": "my-app-id",
            "auth_implementation": "smartcar",
            "token": dict(
                server_access_token,
                scopes=requested_scopes,
            ),
            "vehicles": {vehicle_id: expected_attrs},
            **(
                {
                    "user_id": "218eda3b-0656-49a8-8f3d-360cdad07334",
                }
                if client_id_version == "v3"
                else {}
            ),
            **expected_data,
        }

        assert result["title"] == DEFAULT_NAME
        assert result["result"].unique_id == vehicle_id

    await hass.async_block_till_done()


@pytest.mark.usefixtures("current_request_with_host")
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
async def test_duplicate_vins_disallowed(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    mock_smartcar_auth: AsyncMock,
    vehicle: AsyncMock,
) -> None:
    """Test flow fails if config entities share vehicles with the same VIN."""

    # setup the duplicate first with two vehicles
    duplicate_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="mock-vehicle-id-1 mock-vehicle-id-2",
        version=2,
        minor_version=0,
        data={
            "auth_implementation": DOMAIN,
            "token": {},
            "vehicles": {
                "mock-vehicle-id-1": {"vin": vehicle["vin"]},
                "mock-vehicle-id-2": {"vin": "mock-another-vin"},
            },
        },
    )

    # register it while skipping all of the entity config and whatnot
    with patch("custom_components.smartcar.async_setup_entry", return_value=True):
        await setup_integration(hass, duplicate_entry)
    assert duplicate_entry.state is ConfigEntryState.LOADED

    # now start the flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "webhooks"
    assert not result["last_step"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"use_webhooks": False},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scopes"

    selected_scopes = ["read_odometer"]
    requested_scopes = REQUIRED_SCOPES + selected_scopes
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {k: k in selected_scopes for k in CONFIGURABLE_SCOPES},
    )
    state = config_entry_oauth2_flow._encode_jwt(
        hass,
        {
            "flow_id": result["flow_id"],
            "redirect_uri": REDIRECT_URL,
        },
    )

    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["step_id"] == "auth"

    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200
    assert resp.headers["content-type"] == "text/html; charset=utf-8"

    server_access_token = {
        "refresh_token": "server-refresh-token",
        "access_token": "server-access-token",
        "type": "Bearer",
        "expires_in": 60,
        "scope": " ".join(requested_scopes),
    }

    aioclient_mock.post(
        OAUTH2_TOKEN_LEGACY,
        json=server_access_token,
    )
    aioclient_mock.get(
        f"{MOCK_API_ENDPOINT_LEGACY}/vehicles",
        json={"paging": {"count": 25, "offset": 0}, "vehicles": [vehicle["id"]]},
    )
    aioclient_mock.get(
        f"{MOCK_API_ENDPOINT_LEGACY}/vehicles/{vehicle['id']}/vin",
        json={"vin": vehicle["vin"]},
    )
    aioclient_mock.get(
        f"{MOCK_API_ENDPOINT_LEGACY}/vehicles/{vehicle['id']}",
        json={"id": vehicle["id"], "make": "TESLA", "model": "Model S", "year": "2014"},
    )

    result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "duplicate_vehicles"
    assert result["description_placeholders"] == {"vins": [vehicle["vin"]]}


@pytest.mark.usefixtures("current_request_with_host")
async def test_no_scopes_entered(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    mock_smartcar_auth: AsyncMock,
):
    """Test showing the scopes form again because no scopes were chosen."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "webhooks"
    assert not result["last_step"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"use_webhooks": False},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scopes"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict.fromkeys(CONFIGURABLE_SCOPES, False)
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scopes"
    assert result["errors"] == {"base": "no_scopes"}
    assert not result["last_step"]


@pytest.mark.parametrize(
    ("status_code", "error_reason"),
    [
        (HTTPStatus.UNAUTHORIZED, "oauth_unauthorized"),
        (HTTPStatus.INTERNAL_SERVER_ERROR, "oauth_failed"),
    ],
)
@pytest.mark.usefixtures("current_request_with_host")
async def test_token_error(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    mock_smartcar_auth: AsyncMock,
    status_code: HTTPStatus,
    error_reason: str,
):
    """Test flow with token error occurring."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "webhooks"
    assert not result["last_step"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"use_webhooks": False},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scopes"

    selected_scopes = ["read_odometer"]
    requested_scopes = REQUIRED_SCOPES + selected_scopes
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {k: k in selected_scopes for k in CONFIGURABLE_SCOPES},
    )
    state = config_entry_oauth2_flow._encode_jwt(
        hass,
        {
            "flow_id": result["flow_id"],
            "redirect_uri": REDIRECT_URL,
        },
    )

    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["step_id"] == "auth"
    assert result["url"] == (
        f"{OAUTH2_AUTHORIZE}?response_type=code&client_id=mock-id"
        f"&redirect_uri={REDIRECT_URL}"
        f"&state={state}"
        "&mode=live"
        f"&scope={'+'.join(requested_scopes)}"
    )

    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200
    assert resp.headers["content-type"] == "text/html; charset=utf-8"

    aioclient_mock.post(
        OAUTH2_TOKEN_LEGACY,
        status=status_code,
    )

    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == error_reason


@pytest.mark.parametrize(
    ("target_endpoint", "http_status", "json", "error_reason"),
    [
        params
        for endpoint in ["/vehicles", "/vehicles/{id}/vin", "/vehicles/{id}"]
        for params in [
            (endpoint, HTTPStatus.INTERNAL_SERVER_ERROR, None, "cannot_connect"),
            (endpoint, HTTPStatus.FORBIDDEN, None, "cannot_connect"),
            (
                endpoint,
                HTTPStatus.UNAUTHORIZED,
                {
                    "statusCode": 401,
                    "type": "AUTHENTICATION",
                    "code": None,
                    "description": "Mock description",
                    "docURL": "",
                    "resolution": {"type": None},
                    "suggestedUserMessage": "Mock suggestion",
                },
                "invalid_access_token",
            ),
        ]
    ]
    + [
        (
            "/vehicles",
            HTTPStatus.OK,
            {"vehicles": []},
            "no_vehicles",
        ),
    ],
)
@pytest.mark.usefixtures("current_request_with_host")
async def test_api_error(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    mock_smartcar_auth: AsyncMock,
    target_endpoint: str,
    http_status: HTTPStatus,
    json: Any,
    error_reason: str,
):
    """Test flow with API error occurring."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "webhooks"
    assert not result["last_step"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"use_webhooks": False},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scopes"

    selected_scopes = ["read_odometer"]
    requested_scopes = REQUIRED_SCOPES + selected_scopes
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {k: k in selected_scopes for k in CONFIGURABLE_SCOPES},
    )
    state = config_entry_oauth2_flow._encode_jwt(
        hass,
        {
            "flow_id": result["flow_id"],
            "redirect_uri": REDIRECT_URL,
        },
    )

    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["step_id"] == "auth"
    assert result["url"] == (
        f"{OAUTH2_AUTHORIZE}?response_type=code&client_id=mock-id"
        f"&redirect_uri={REDIRECT_URL}"
        f"&state={state}"
        "&mode=live"
        f"&scope={'+'.join(requested_scopes)}"
    )

    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200
    assert resp.headers["content-type"] == "text/html; charset=utf-8"

    vehicle_id = "36ab27d0-fd9d-4455-823a-ce30af709ffc"
    vin = "5YJSA1CN5DFP00101"
    server_access_token = {
        "refresh_token": "server-refresh-token",
        "access_token": "server-access-token",
        "type": "Bearer",
        "expires_in": 60,
        "scope": " ".join(requested_scopes),
    }

    override_vehicles = target_endpoint == "/vehicles"
    override_vin = target_endpoint == "/vehicles/{id}/vin"
    override_attributes = target_endpoint == "/vehicles/{id}"

    aioclient_mock.post(
        OAUTH2_TOKEN_LEGACY,
        json=server_access_token,
    )
    aioclient_mock.get(
        f"{MOCK_API_ENDPOINT_LEGACY}/vehicles",
        status=http_status if override_vehicles else 200,
        json=(
            json
            if override_vehicles
            else {"paging": {"count": 25, "offset": 0}, "vehicles": [vehicle_id]}
        ),
    )
    aioclient_mock.get(
        f"{MOCK_API_ENDPOINT_LEGACY}/vehicles/{vehicle_id}/vin",
        status=http_status if override_vin else 200,
        json=json if override_vin else {"vin": vin},
    )
    aioclient_mock.get(
        f"{MOCK_API_ENDPOINT_LEGACY}/vehicles/{vehicle_id}",
        status=http_status if override_attributes else 200,
        json=(
            json
            if override_attributes
            else {"id": vehicle_id, "make": "TESLA", "model": "Model S", "year": "2014"}
        ),
    )

    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == error_reason


@pytest.mark.usefixtures("current_request_with_host")
@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
@pytest.mark.parametrize(
    (
        "entry_data",
        "new_vehicle_id",
        "expected_result",
    ),
    [
        (
            {},
            "a1d50709-3502-4faa-ba43-a5c7565e6a09",
            {
                "abort_reason": "reauth_successful",
                "access_token": "updated-access-token",
                "setup_calls": 1,
            },
        ),
        (
            {
                CONF_WEBHOOK_ID: "original_webhook_id",
                CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt",
            },
            "a1d50709-3502-4faa-ba43-a5c7565e6a09",
            {
                "abort_reason": "reauth_successful",
                "access_token": "updated-access-token",
                "setup_calls": 1,
                "entry_data": {
                    CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt",
                    CONF_WEBHOOK_ID: "original_webhook_id",
                },
            },
        ),
        (
            {},
            "a-different-vehicle-id",
            {
                "abort_reason": "wrong_vehicles",
                "placeholders": {"vins": "VIWP1AB29P15LA85784N"},
                "access_token": "mock-access-token",
                "setup_calls": 0,
            },
        ),
    ],
    ids=["reauth_successful", "reauth_successful_unchanged_webhooks", "wrong_vehicles"],
)
async def test_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    vehicle_fixture: str,
    vehicle_attributes: dict,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    mock_smartcar_auth: AsyncMock,
    new_vehicle_id: str,
    entry_data: dict,
    expected_result: dict[str, Any],
) -> None:
    """Test the reauthentication flow."""
    expected_abort_reason = expected_result.get("abort_reason", "reauth_successful")
    expected_placeholders = expected_result.get("placeholders")
    expected_access_token = expected_result.get("access_token")
    expected_setup_calls = expected_result.get("setup_calls", 1)
    expected_entry_data = expected_result.get("entry_data", {})

    mock_config_entry.add_to_hass(hass)

    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, **entry_data},
    )

    result = await mock_config_entry.start_reauth_flow(hass)

    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scopes"

    selected_scopes = ["read_odometer"]
    requested_scopes = REQUIRED_SCOPES + selected_scopes
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {k: k in selected_scopes for k in CONFIGURABLE_SCOPES},
    )
    state = config_entry_oauth2_flow._encode_jwt(
        hass,
        {
            "flow_id": result["flow_id"],
            "redirect_uri": REDIRECT_URL,
        },
    )

    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["step_id"] == "auth"
    assert result["url"] == (
        f"{OAUTH2_AUTHORIZE}?response_type=code&client_id=mock-id"
        f"&redirect_uri={REDIRECT_URL}"
        f"&state={state}"
        "&mode=live"
        f"&scope={'+'.join(requested_scopes)}"
    )

    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200
    assert resp.headers["content-type"] == "text/html; charset=utf-8"

    vin = "5YJSA1CN5DFP00101"
    server_access_token = {
        "refresh_token": "mock-refresh-token",
        "access_token": "updated-access-token",
        "type": "Bearer",
        "expires_in": 60,
        "scope": " ".join(requested_scopes),
    }

    aioclient_mock.post(
        OAUTH2_TOKEN_LEGACY,
        json=server_access_token,
    )
    aioclient_mock.get(
        f"{MOCK_API_ENDPOINT_LEGACY}/vehicles",
        json={"paging": {"count": 25, "offset": 0}, "vehicles": [new_vehicle_id]},
    )
    aioclient_mock.get(
        f"{MOCK_API_ENDPOINT_LEGACY}/vehicles/{new_vehicle_id}/vin", json={"vin": vin}
    )
    aioclient_mock.get(
        f"{MOCK_API_ENDPOINT_LEGACY}/vehicles/{new_vehicle_id}",
        json={
            "id": new_vehicle_id,
            "make": "TESLA",
            "model": "Model S",
            "year": "2014",
        },
    )

    with patch(
        "custom_components.smartcar.async_setup_entry", return_value=True
    ) as mock_setup:
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert len(mock_setup.mock_calls) == expected_setup_calls
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == expected_abort_reason
    assert result["description_placeholders"] == expected_placeholders

    assert mock_config_entry.unique_id == vehicle_attributes["id"]
    assert "token" in mock_config_entry.data

    # limit scope of comparison for config entry data
    compare_entry_data = {**mock_config_entry.data}
    token = compare_entry_data.pop("token")
    compare_entry_data.pop("auth_implementation", None)
    compare_entry_data.pop("token", None)
    compare_entry_data.pop("vehicles", None)

    # verify access token is refreshed
    assert token["access_token"] == expected_access_token
    assert token["refresh_token"] == "mock-refresh-token"  # noqa: S105
    assert compare_entry_data == expected_entry_data


@pytest.mark.parametrize("vehicle_fixture", ["vw_id_4"])
@pytest.mark.parametrize(
    ("setup", "entry_data", "user_input", "expected_result"),
    [
        (set(), {}, {"use_webhooks": False}, {}),
        (
            set(),
            {},
            {"use_webhooks": True, CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt"},
            {
                "data": {
                    CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt",
                    CONF_CLOUDHOOK: False,
                    CONF_WEBHOOK_ID: "mock_webhook_id",
                }
            },
        ),
        (
            set(),
            {
                CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt",
                CONF_CLOUDHOOK: False,
                CONF_WEBHOOK_ID: "mock_webhook_id",
            },
            {"use_webhooks": False},
            {},
        ),
        (
            set(),
            {
                CONF_APPLICATION_MANAGEMENT_TOKEN: "old_mock_amt",
                CONF_CLOUDHOOK: False,
                CONF_WEBHOOK_ID: "old_mock_webhook_id",
            },
            {"use_webhooks": True, CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt"},
            {
                "data": {
                    CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt",
                    CONF_CLOUDHOOK: False,
                    CONF_WEBHOOK_ID: "old_mock_webhook_id",
                }
            },
        ),
        (
            {"cloud"},
            {},
            {"use_webhooks": True, CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt"},
            {
                "data": {
                    CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt",
                    CONF_CLOUDHOOK: True,
                    CONF_WEBHOOK_ID: "mock_webhook_id",
                }
            },
        ),
        (
            {"cloud", "cloud_not_connected"},
            {},
            {"use_webhooks": True, CONF_APPLICATION_MANAGEMENT_TOKEN: "mock_amt"},
            {
                "form_type": FlowResultType.ABORT,
                "errors": {},
            },
        ),
    ],
    ids=[
        "no_webhooks",
        "webhooks",
        "disable_webhooks",
        "reconfigure_webhooks",
        "cloud_webhooks",
        "cloud_not_connected",
    ],
)
async def test_options_flow(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    setup: set[str],
    entry_data: dict,
    user_input: dict,
    expected_result: dict,
    mock_smartcar_auth: AsyncMock,
    snapshot: SnapshotAssertion,
) -> None:
    """Test options flow."""
    mock_config_entry.add_to_hass(hass)

    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, **entry_data},
    )

    with (
        patch(
            "custom_components.smartcar.async_setup_entry",
            return_value=True,
        ) as mock_setup_entry,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert mock_setup_entry.called

    with (
        patch(
            "homeassistant.components.webhook.async_generate_id",
            return_value="mock_webhook_id",
        ),
        patch(
            "homeassistant.components.cloud.async_active_subscription",
            return_value="cloud" in setup,
        ),
        patch(
            "homeassistant.components.cloud.async_get_or_create_cloudhook",
            return_value="cloud_url",
        )
        if "cloud_not_connected" not in setup
        else nullcontext(),
    ):
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "webhooks"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input=user_input,
        )

        expected_errors = expected_result.pop("errors", None)
        expected_placeholders = expected_result.pop("description_placeholders", None)
        expected_data = expected_result.pop("data", {})
        expected_form_type = expected_result.pop(
            "form_type",
            FlowResultType.FORM if expected_errors else FlowResultType.CREATE_ENTRY,
        )

        # limit scope of comparison for config entry data
        compare_entry_data = {**mock_config_entry.data}
        compare_entry_data.pop("auth_implementation", None)
        compare_entry_data.pop("token", None)
        compare_entry_data.pop("vehicles", None)

        if expected_errors is not None:
            assert result["type"] is expected_form_type
            assert result.get("errors", {}) == expected_errors
            assert result["description_placeholders"] == expected_placeholders
        else:
            assert result["type"] is expected_form_type
            assert compare_entry_data == expected_data

        await hass.async_block_till_done()
