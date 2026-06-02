# Smartcar V3 Integration — FAQ

Common issues and how to diagnose them. Many of these are platform-side issues that aren't really integration bugs but need to be understood to get data flowing.

## Pre-flight check

Before deep-diving, sanity-check the obvious:

- [Smartcar Status](https://status.smartcar.com/) — platform-wide outages.
- [Smartcar Brand Reliability](https://brandreliability.smartcar.com/) — known issues per OEM.
- [Brand Data Frequency](https://smartcar.com/docs/help/frequencies) — how often each brand actually sends data.
- [Vehicle Compatibility](https://smartcar.com/product/compatible-vehicles) — confirm your vehicle and country are supported.

## Setup-time problems

### "Invalid parameter client_id" during Connect

Smartcar Connect rejected the value HA sent as `client_id` in the redirect URL. This is the most common setup error: the **Application ID** field in the HA form needs the *Application ID* from your Smartcar dashboard, **not** the V3 Client ID.

The two are different:

- **Application ID** — shown on your Smartcar application's overview page. Used by Connect.
- **V3 Client ID** — shown under *API Credentials* on the same application page. Format: `client_xxx...`. Used by IAM to mint access tokens.

They often look superficially similar (both can be `client_xxx` format depending on when the application was created), so it's easy to swap them. The error message includes the rejected value — if it matches your V3 Client ID, that's the swap.

### "Failed to resume setup flow" / 404 on `/api/smartcar/callback`

Either:

1. **You restarted HA in the middle of the flow.** Start the flow over.
2. **The callback view didn't register.** This used to happen with older versions of the integration — `async_setup` runs only after a config entry exists, but during the first setup there's no entry yet. The current integration registers the view from the config flow as well, so this shouldn't happen anymore. If it does, restart HA and try again; if that fails, there's a real bug.

### "Failed to setup" after a successful setup, with "Config entry … has already been setup!" errors in the log

This was a bug in earlier V3 builds where a failure after `async_forward_entry_setups` triggered a retry loop. The platforms were registered on the first attempt, and the retry's forward call collided with them.

Fix: delete the broken config entry from Settings → Devices & Services, restart HA, set up again with the current integration version. The current version moves all fallible operations before the forward call and makes the first data refresh fire-and-forget, so failures in the data path don't trigger setup retries.

### Setup completes but I can't see where to register the callback URL on Smartcar

It's not the webhook callback — that's separate. The integration setup needs an **OAuth redirect URI** registered on your Smartcar *application* (the same place where the Application ID and API Credentials live). Look for a field labelled *Allowed Redirect URIs*, *Redirect URLs*, or similar. Paste the URL exactly as HA displayed it during setup.

## Runtime problems

### All entities are "Unavailable" even though setup succeeded

The most common cause. Almost always means: **vehicle isn't subscribed to your webhook** on Smartcar's side.

In V3, signal data only flows for subscribed vehicles. This is true for both webhook delivery and the polling `/signals` endpoint — Smartcar returns `404 Not Found` on `/vehicles/{id}/signals` for unsubscribed vehicles, not an empty list.

Fix:

1. Smartcar dashboard → *Integrations* → open your webhook.
2. Enable **"Automatically subscribe all vehicles"**.
3. Save.
4. Wait. OEM polling cadence varies — you'll see *some* data within an hour for most brands, but full signal coverage can take longer. Refer to [Brand Data Frequency](https://smartcar.com/docs/help/frequencies) for your make.

If you'd rather subscribe vehicles selectively, do it from Smartcar dashboard → *Vehicles* → your car → *Webhook Subscriptions* → *Subscribe*.

### Smartcar dashboard log shows 404 on `/vehicles/:id/signals`

Same root cause as above: vehicle isn't subscribed. The integration is calling the right endpoint with the right auth; Smartcar is saying "this vehicle has no signals subscription so there's nothing to return". Enable auto-enrollment.

### Webhook delivery works but `last_webhook_received` shows a stale time

Webhooks fire when signals change, *and* on Smartcar's internal cadence — they're not continuous. If your vehicle is parked and unchanged, webhooks won't fire. Take it for a short drive to force odometer / battery / location changes and confirm webhooks resume.

The `sensor.<make_model>_last_webhook_received` entity exposes `response_status` and `response_data` attributes — if Smartcar is sending but HA is rejecting (e.g. HMAC verification failure), those will show non-200 status codes.

### Some entities show data, others stay unavailable

Two likely reasons:

1. **The signal isn't enabled in your webhook config.** Smartcar's webhooks deliver a subset of signals configured in the dashboard. Unselected signals don't reach HA. Open your webhook in the dashboard and confirm the signals matching your unavailable entities are enabled.
2. **The signal isn't included in your Smartcar plan.** Some signals are only available on paid plans. The free tier currently exposes about 9 trigger signals and 9 data signals (subject to change). Check your [Smartcar billing page](https://dashboard.smartcar.com/team/billing) and compare against the [pricing page](https://smartcar.com/pricing#pricing).
3. **Your vehicle doesn't support the signal.** Even with the right plan, signal support varies by make/model/year. The [compatibility table](https://smartcar.com/product/compatible-vehicles) shows what's available.

### `error for signal X: VEHICLE_STATE:...` in the log

This is normal, not a problem. Smartcar uses `VEHICLE_STATE` errors to say "this signal can't be read because the vehicle isn't in the relevant state right now". The most common one is `VEHICLE_STATE:NOT_CHARGING` for the `ChargeRate` signal: every time you unplug, the next webhook reports that this datapoint has no value. The integration handles it by setting the corresponding entity to unavailable, which is the right behaviour.

The integration logs these at DEBUG rather than ERROR (since v2.0.x), so they don't appear in your error log unless debug logging is on. If you see them at error level, you're on an older build — pull the latest.

Errors with other `type` values (`PERMISSION`, `UPSTREAM`, `INTEGRATION`, etc.) are *not* demoted — those still log at error level because they're things you can act on.

### Repeated `REAUTHENTICATE` errors

Known issue on Smartcar's side, often associated with the `VehicleUserAccount` signal group. Workaround: disable both the `VehicleUserAccount` triggers and data signals in your webhook configuration. Reference: [original integration issue #51](https://github.com/wbyoung/smartcar/issues/51).

### Tokens expire mid-session, integration goes unavailable

This shouldn't happen — the token manager fetches a fresh token on demand. If it does, check the HA log for entries from `custom_components.smartcar.auth_impl` around the time it went unavailable. The most likely cause is your V3 Client ID or Secret being revoked or rotated on the Smartcar dashboard.

### Polling fetches return empty data but webhooks work

If webhooks are enabled and arriving, polling is disabled — the integration treats the management-token-configured case as "webhooks are the source of truth" and doesn't poll in parallel. If you've disabled webhooks and rely on polling, the default cadence is 6 hours idle / 15 minutes while charging; both are configurable from *Settings → Devices & Services → Smartcar → Configure* with a 5-minute minimum.

## Diagnostics

### Enable debug logging

Settings → Devices & Services → Smartcar → ⋯ → *Enable debug logging*. Then reproduce the issue. The logs will include:

- `custom_components.smartcar.coordinator` — what the polling code is fetching and getting back.
- `custom_components.smartcar.webhooks` — incoming webhook payloads (raw JSON).
- `custom_components.smartcar.auth_impl` — token mint requests and refreshes.
- `custom_components.smartcar.views` — the OAuth callback view.

Disable debug logging when done — you'll be prompted to download the log file.

### Check Smartcar's side of the conversation

The Smartcar dashboard has its own log of every request it received and webhook it sent:

- Application page → *Logs* or *Activity* tab — API requests received from your integration.
- Webhook config → *Logs* — webhook deliveries attempted, including HTTP status responses from your HA.

If you suspect a request is malformed, the dashboard often shows more context than HA does — paths, status codes, sometimes response bodies.

## When all else fails

A clean reset:

1. Settings → Devices & Services → Smartcar → ⋯ → *Delete*.
2. Smartcar dashboard → *Vehicles* → disconnect the vehicle.
3. Smartcar dashboard → *Integrations* → delete the webhook.
4. Restart HA.
5. Set up from scratch following the [README setup steps](README.md#setup).

This wipes any half-baked state on both sides.

## Privacy and what's shared with Smartcar

Worth knowing if you care about this:

- **Your HA URL is registered with Smartcar.** Either your Nabu Casa Cloud URL or your own external URL ends up in their dashboard as both the OAuth redirect URI and the webhook callback URI.
- **Webhook payloads transit Smartcar's infrastructure.** Encrypted end-to-end at the TLS layer, but routed through their servers.
- **Smartcar logs requests** in their dashboard. Bearer tokens and headers are typically masked but URLs and timestamps aren't.
- **Webhook payloads contain vehicle identifiers, location coordinates, and signal values.** If posting log excerpts publicly for help, redact lat/long and vehicle IDs.

## Reporting bugs

Before opening an issue:

1. Work through the relevant sections above.
2. Enable debug logging, reproduce, and grab the log file.
3. Download the integration diagnostics file (Settings → Devices & Services → Smartcar → ⋯ → *Download diagnostics*) — it's redacted automatically.

Attach the diagnostics and relevant log excerpts (the section around the issue, not the full multi-MB file). If posting raw webhook JSON, beautify it and wrap in a `<details>` block so the issue stays readable.
