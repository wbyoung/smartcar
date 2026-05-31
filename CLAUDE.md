# CLAUDE.md

Guidance for Claude (and other AI assistants) working in this repository. This isn't a primer on Home Assistant integrations or the Smartcar API — those are findable elsewhere. This document captures the **non-obvious decisions and gotchas** specific to this V3 rebuild, the kind of thing that would make you waste a debugging round if you didn't know it going in.

## TL;DR

This is a Home Assistant custom integration for Smartcar's **V3 API**. It's a rewrite of [`wbyoung/smartcar`](https://github.com/wbyoung/smartcar), which targeted V2. V3 changed authentication, endpoints, and the data delivery model substantially. Most of the platform code (`sensor.py`, `binary_sensor.py`, etc.) is from the original V2 integration and is still correct because the entity model is unchanged. The auth, config flow, coordinator, and webhook layers were rewritten.

## Architecture

### Two distinct credential sets, two endpoints

The most important V3 quirk: **Smartcar Connect and Smartcar IAM are different services with different identifiers and different endpoints**.

| Concern | Endpoint | What it does | Auth |
|---|---|---|---|
| User consent | `https://connect.smartcar.com/oauth/authorize` | The user-facing OAuth flow where they grant permission to read their vehicle | `client_id=<Application ID>` in URL params |
| Token mint | `https://iam.smartcar.com/oauth2/token` | App-level access token via `client_credentials` grant | HTTP Basic Auth with V3 Client ID + Secret |
| Vehicle data | `https://vehicle.api.smartcar.com/v3/...` | All vehicle reads and commands | `Authorization: Bearer <iam token>` + `sc-user-id: <user_id>` headers |

The **Application ID** (Connect's `client_id`) and the **V3 Client ID** (IAM's `client_id` in Basic Auth) are **different values**, both stored on the same Smartcar application in the dashboard. Confusing them was the #1 source of debugging time during the rebuild. The user-facing error from Connect when you swap them is `400: Invalid parameter client_id: <value>`.

If you see code or docs that talk about the V2 token endpoint at `auth.smartcar.com/oauth/token`, that's legacy and rejects V3 credentials with 401.

### No per-user tokens, no refresh

V2 used the authorization code grant: the user logs in via Connect, Smartcar returns an auth code, the app exchanges it for a per-user access token + refresh token, and refreshes as needed. V3 dropped this entirely.

V3 model:
- One application-level token per app, minted via `client_credentials` at IAM. Valid 1 hour, no refresh token, re-minted on demand.
- User identification via `sc-user-id` header on every vehicle API request.
- The auth code Smartcar still returns from Connect is **ignored** — it's a vestigial parameter.

This means HA's `AbstractOAuth2FlowHandler` and `OAuth2Session` framework don't fit V3 at all. The integration uses a plain `ConfigFlow` and a custom `ClientCredentialsTokenManager` instead.

### user_id captured from the Connect callback

Smartcar Connect redirects to the configured callback URL with these query parameters:

```
?code=<ignored>&user_id=<sc_user_id>&state=<our state token>
```

Note the **snake_case** `user_id`. The docs sometimes show `userId` (camelCase); the live redirect uses snake_case. The view accepts both as a safety net.

`user_id` is the only value we actually need from the callback. It's persisted in the config entry as `sc_user_id` and sent as the `sc-user-id` header on every subsequent vehicle API request.

### Auto-enrollment is required for any data to flow

In V3, vehicles don't produce signal data until they're **subscribed** to a webhook. This applies to both webhook delivery AND on-demand `GET /signals` polling — Smartcar returns `404 Not Found` for unsubscribed vehicles, not an empty signal list.

This is the most common "all entities unavailable despite successful setup" scenario. The fix is on Smartcar's side, not the integration's: enable *"Automatically subscribe all vehicles"* in the dashboard's webhook configuration, or manually subscribe each vehicle.

The integration currently does *not* call Smartcar's `/v3/webhooks/{id}/subscribe` API to subscribe vehicles programmatically. If we ever want to, we'd need to capture the Smartcar-side webhook ID (different from HA's webhook ID) during setup. For now, auto-enrollment via the dashboard is the recommended path and we just document it.

## File-by-file map

```
custom_components/smartcar/
├── __init__.py            # async_setup_entry, populate_entry_data (called from config flow)
├── auth.py                # AbstractAuth: builds requests, injects auth headers
├── auth_impl.py           # ClientCredentialsTokenManager + concrete auth implementations
├── config_flow.py         # The 5-step config flow (credentials → webhooks → scopes → Connect → finish)
├── const.py               # All URLs, conf keys, scope definitions
├── coordinator.py         # SmartcarVehicleCoordinator: polls /signals, parses responses
├── entity.py              # Base SmartcarEntity class with shared availability/value logic
├── views.py               # SmartcarConnectCallbackView at /api/smartcar/callback
├── webhooks.py            # Handler for incoming webhook events from Smartcar
├── util.py                # async_request_with_retry, HMAC helpers, key path utilities
├── errors.py              # InvalidAuthError, EmptyVehicleListError, MissingVINError
├── types.py               # SmartcarData dataclass for runtime_data
├── services.py            # smartcar.lock_doors / smartcar.unlock_doors services
├── sensor.py, switch.py,  # Platform implementations — mostly unchanged from V2
├── lock.py, number.py,    
├── binary_sensor.py,      
├── device_tracker.py      
├── diagnostics.py         # Redacted diagnostics dump
├── manifest.json          # Note: dependencies are ["http", "webhook"]; no application_credentials
└── translations/en.json
```

## HA framework gotchas hit during the rebuild

These took multiple debugging rounds. Don't repeat them.

### 1. `async_setup` doesn't run until a config entry exists

For config-flow-only integrations, HA only calls the integration's `async_setup` (component-level) after the first config entry is created. During the very first setup flow there's no entry yet, so `async_setup` hasn't run.

Consequence: anything registered in `async_setup` (services, HTTP views) isn't available during the first config flow. The OAuth callback view (`SmartcarConnectCallbackView`) **must** be registered from the config flow too — specifically in `async_step_authorize` before launching `async_external_step`. Registration is idempotent (guarded by a sentinel in `hass.data[DOMAIN]`), so calling it from both `async_setup` and the config flow is safe.

### 2. `async_forward_entry_setups` is a commit point

Once `hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)` succeeds, the entry is considered set up. If anything in `async_setup_entry` raises **after** this call, HA marks the entry as `SETUP_RETRY` and calls `async_setup_entry` again — but does **not** unload the platforms. The retry's forward call then hits HA's tracking and raises:

```
ValueError: Config entry X (...) for Y has already been setup!
```

This cascades into a "Failed to setup" state that persists across restarts because the `SETUP_RETRY` flag is on disk.

Fix: structure `async_setup_entry` so that *everything that can fail* runs before the forward call, and *nothing after the forward call raises*. In particular:

- The first coordinator refresh is now a fire-and-forget background task (`hass.async_create_task(coordinator.async_refresh())`) — not awaited. If the API isn't ready (e.g. auto-enrollment isn't enabled), entities stay unavailable until the next refresh, but setup completes.
- Webhook registration happens before the forward call, wrapped in try/except so transient cloudhook failures don't propagate.

### 3. External step resume must use `async_external_step_done`

When the OAuth callback view calls `flow.async_configure(flow_id, user_input=...)` to resume the flow, the `async_step_authorize` handler runs again with the user input.

Wrong:
```python
async def async_step_authorize(self, user_input=None):
    if user_input is not None:
        self._user_id = user_input["userId"]
        return await self.async_step_finish()   # ← directly invokes next step
```

This returns a `CreateEntry` result inside an external-step-resume handler, which can cause HA's framework to double-dispatch — invoking `async_setup_entry` twice and triggering the "already been setup" cascade above.

Right:
```python
async def async_step_authorize(self, user_input=None):
    if user_input is not None:
        self._user_id = user_input["userId"]
        return self.async_external_step_done(next_step_id="finish")
```

The framework then dispatches `async_step_finish` itself.

### 4. The OAuth callback view should never 500 the browser

The view receives the redirect from Smartcar Connect and resumes the config flow. The flow result (success, abort) is reflected in HA's UI separately — the browser tab is just a courtesy "you can close this window" page.

Returning 500 from the callback hides successful setups behind a scary error page when the exception was benign. Log the exception, return a 200 success page anyway, and let the user verify outcome in HA UI.

### 5. URL detection: use `get_url`, not `hass.config.external_url`

Nabu Casa Cloud users have an external URL but it's not in `hass.config.external_url` (that's only populated from `configuration.yaml` or the network settings). The cloud URL is exposed via `cloud.async_remote_ui_url()` separately.

`homeassistant.helpers.network.get_url(hass, allow_cloud=True, require_ssl=True, ...)` knows about both and returns whichever is available, preferring a user-configured external URL over the cloud URL.

## V3 endpoint reference

All paths under `https://vehicle.api.smartcar.com/v3/`. All require `Authorization: Bearer <iam-token>`. Vehicle endpoints additionally require `sc-user-id: <user_id>`.

| Path | Method | Used by | Notes |
|---|---|---|---|
| `/connections` | GET | `populate_entry_data` (setup) | JSON:API response. Vehicle ID at `data[i].relationships.vehicle.data.id`. Filter with `filter[userId]={user_id}`. Paginated via `page[number]` / `page[size]`. |
| `/vehicles/{id}` | GET | not used | Returns make/model/year/powertrain. We get these from `/connections` instead to save a call. |
| `/vehicles/{id}/signals` | GET | `coordinator._async_update_data` | All signals in one response. JSON:API format. Returns 404 for unsubscribed vehicles. |
| `/vehicles/{id}/signals/{code}` | GET | not used in current code; was used for VIN | Single signal. We dropped VIN fetching entirely — we use `vehicle_id` as the unique identifier instead. |
| `/vehicles/{id}/commands/{type}/{action}` | POST | `entity.async_send_command` (locks/charging/limit) | E.g. `commands/security/lock`, `commands/charge/start`, `commands/charge/limit`. |

The IAM token endpoint is **not** under `vehicle.api.smartcar.com` — it's at `https://iam.smartcar.com/oauth2/token`. Confusing these (especially `auth.smartcar.com` from the V2 era) wastes time.

## Webhook architecture

Two webhooks are involved, with different IDs:

1. **HA's webhook ID** — generated by `webhook.async_generate_id()`, used as the URL Smartcar pushes to. Stored in `entry.data[CONF_WEBHOOK_ID]`. The URL is `<external>/api/webhook/<webhook_id>` or a Nabu Casa cloudhook.

2. **Smartcar's webhook ID** — assigned by Smartcar when you create a webhook on the dashboard. The integration doesn't capture this currently, so we can't call `/v3/webhooks/{id}/subscribe` programmatically. Auto-enrollment from the dashboard sidesteps this.

The integration verifies incoming webhook payloads using HMAC-SHA256 with the **Application Management Token** (a third Smartcar credential, separate from the V3 Client ID/Secret). Captured during setup if webhooks are enabled. Logic is in `webhooks.py`.

## Testing changes

The integration has a partial V3 test suite. The split:

**Active V3 tests** (51 tests, all passing locally):

- `tests/test_util.py` — 26 pure utility tests for HTTP retry, HMAC, key-path helpers. Unchanged from the V2 suite (`util.py` is V3-clean).
- `tests/test_auth_impl.py` — 8 tests for `ClientCredentialsTokenManager`, `AsyncConfigEntryAuth`, `ClientCredentialsAuthImpl`. Covers token caching, expiry refresh, 401/403 handling, malformed responses, invalidation, and the bootstrap auth's `with_user_id()` rebinding.
- `tests/test_config_flow.py` — 6 tests covering: the happy path (credentials → webhooks → scopes → Connect external step → callback resume → finish), IAM-rejecting-credentials at the user step, network failure at the user step, missing-external-URL abort at the authorize step, missing-user-id from the callback (deferred abort via `_oauth_error`), and the webhooks step rejecting an enable-without-token.
- `tests/test_binary_sensor.py` — 3 tests built from a real VW ID.7 webhook payload. Verifies that populated signals surface on their entities (charging cable plugged in), that closure signals absent from the payload render as `unavailable`, and that meta signals (online, asleep, etc.) render as `unavailable` when no data is present.
- `tests/test_sensor.py` — 3 tests against the same fixture. Verifies battery (80%), range (472 km), odometer (16342 km), charging_status (`FULLY_CHARGED`), charging_power (0 W) and time_to_complete (0). Separately checks that signals arriving with `status: ERROR` (`charge-chargerate` here, with error code `NOT_CHARGING`) render as `unavailable`, and that signals not present in the payload (engine oil, fuel, tire pressure) likewise render as `unavailable`.
- `tests/test_switch.py` — 3 tests for the charging switch. Initial state (`off`, derived from `charge-ischarging: false`), `turn_on` dispatches `commands/charge/start`, `turn_off` dispatches `commands/charge/stop`.
- `tests/test_diagnostics.py` — 2 tests. Verifies that the diagnostics dump redacts the VIN and never includes the application management token or cloudhook secret, and that the coordinator data is present in the dump.

**Stubbed pending V3 fixture work** (5 modules, module-level `pytest.skip`):

- `test_device_tracker.py`, `test_init.py`, `test_lock.py`, `test_number.py`, `test_services.py`

These need additional fixture data — typically locations (`location-preciselocation`) for device_tracker, lock state (`closure-islocked`) for lock and door entities, and service-call routing for services. The VW ID.7 fixture has `location-preciselocation: null` and `closure-islocked: null`, so they can't be re-enabled with what's on hand. As new payloads with those signals become available, they can be added under `tests/fixtures/coordinator_data/` and the stubs unstubbed.

**Fixture data on hand**:

- `tests/fixtures/webhooks/vw_id7_vehicle_state.json` — full V3 webhook payload for a VW ID.7 (sanitised; vehicle id and user id replaced with stable test UUIDs, VIN already redacted upstream).
- `tests/fixtures/coordinator_data/vw_id7.json` — the same vehicle's signal state after the integration's webhook handler has processed it (the shape that sits in `coordinator.data`). This is the simpler artefact to inject in tests via the `setup_with_data` fixture, which patches `_async_update_data` and runs the integration's `async_setup_entry`.
- `tests/fixtures/vehicles/vw_id7.json` — vehicle metadata as it appears in the config entry's `vehicles` dict.

**Quirks worth knowing:**

- `tests/conftest.py` includes a session-scoped `_aiohttp_thread_warmup` fixture that creates and discards an aiohttp `ClientSession` before any test runs. This is to pre-spawn aiohttp's `_run_safe_shutdown_loop` daemon thread, which the pytest-HA leak detector would otherwise flag as a leak the first time a test creates a session.
- An autouse `expected_lingering_timers` fixture returns `True` to neutralise pytest-HA's lingering-timer detector. HA-core's legacy `device_tracker` schedules a 5-second `async_update_stale` timer inside `LegacyDeviceTracker` that doesn't reliably cancel at test teardown; it's not an integration concern.
- `mock_smartcar_auth` patches the `async_get_access_token` *method* on the three auth classes (`ClientCredentialsTokenManager`, `AsyncConfigEntryAuth`, `ClientCredentialsAuthImpl`) rather than replacing the classes themselves. Earlier versions of this fixture used `patch(...)` with `autospec=True` to swap the class, and that broke a later test in the suite: pytest-HA can reimport the integration between tests, and `config_flow.py`'s `from .auth_impl import ClientCredentialsTokenManager` then rebinds to the active MagicMock. The MagicMock binding survives the patch unwinding in `sys.modules` because Python's module cache persists, and subsequent tests trying to use the real class get the leftover MagicMock. Patching the method keeps class identity stable.
- `setup_with_data` patches `_async_update_data` on the coordinator and runs the integration's full `async_setup_entry`. Tests get real entities backed by canned data without paying for HTTP mocking. Use it whenever you'd otherwise need to construct a `/signals` JSON:API fixture.
- `mock_config_entry` carries the V3 data shape and accepts a `vehicle_data` override fixture. Per-test overrides (e.g. the VW ID.7 fixture) work by redefining `vehicle_data` at module level.

To run locally:

```bash
pip install pytest pytest-homeassistant-custom-component freezegun
pytest tests/ --no-cov
```

## Common requests and how to handle them

**"Add a new sensor type."** Almost always means: add a key to `DATAPOINT_ENTITY_KEY_MAP` in `const.py`, add a description in the relevant platform file (`sensor.py`, `binary_sensor.py`, etc.), make sure the Smartcar signal code matches what's in their schema. The coordinator already fetches all signals in one call so there's no API plumbing to add.

**"It returns 404 / no data."** First question: is auto-enrollment on? Second question: is the signal in the user's Smartcar plan? Both are platform-side, not integration bugs.

**"Setup fails at Connect."** Almost always credential confusion — Application ID vs V3 Client ID in the wrong fields. Compare formats and the exact value in the error message.

**"Tokens expire mid-session."** Shouldn't happen; the token manager refreshes on demand with a 5-minute expiry buffer. If it does, check `auth_impl.py` for changes, or the user's V3 credentials may have been rotated.

**"How do I add a new command?"** New entry in the relevant platform's command mapping, then make sure the V3 endpoint path matches (e.g. `commands/security/lock`, `commands/charge/start`). Permissions are enforced server-side; we don't pre-check.

## Style notes

- The code uses Google-style docstrings (per `pyproject.toml` ruff config).
- Type annotations everywhere; the project targets Python 3.13+ matching HA's requirement.
- Module-level docstrings on every file explain *why* the file exists, not just what's in it.
- Errors are raised, not returned as None or sentinels, unless the calling pattern explicitly handles None (e.g. `pop_state` returning None for unknown state tokens).
- HTTP retries go through `util.async_request_with_retry`, not bespoke loops.

## Out-of-scope / known limitations

- **No subscription management API integration.** As above — would require capturing the Smartcar-side webhook ID.
- **Platform tests partially rebuilt.** 5 of 9 stubbed test modules (`test_device_tracker.py`, `test_init.py`, `test_lock.py`, `test_number.py`, `test_services.py`) remain stubbed with module-level `pytest.skip` because the VW ID.7 reference payload doesn't include the relevant signals (`location-preciselocation`, `closure-islocked`, charge-limit setters, service-call payloads). The other 4 — binary_sensor, sensor, switch, diagnostics — are rebuilt and active.
- **Single-language translations.** `translations/en.json` and `translations/nl.json` only.
- **VIN handling is degenerate.** We use `vehicle_id` (UUID) as the unique identifier in place of VIN. This is fine for the integration but means device identifiers in the registry are UUIDs, not actual VINs. If you want true VIN, fetch it via the `vehicleidentification-vin` signal (single-signal endpoint) and store separately — but be ready to handle the case where the signal returns `status: ERROR`.
- **No `manifest.json` `version` bump strategy documented.** Currently at `2.0.0` to signal the V3 break. Future versions should follow semver against this baseline.
