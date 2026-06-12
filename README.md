# Smartcar Integration for Home Assistant — V3

Connect your compatible vehicle to Home Assistant using the [Smartcar API](https://smartcar.com/).

This integration provides sensors and controls for vehicles linked through the Smartcar platform — battery state, range, lock control, charge control, location, tire pressure, and more — depending on what your vehicle and Smartcar plan support.

This is a rewrite of the original [`wbyoung/smartcar`](https://github.com/wbyoung/smartcar) integration for the **Smartcar V3 API**. V3 changed the authentication model substantially: per-user OAuth tokens with refresh are gone, replaced by a single application-level access token minted via the `client_credentials` grant, with a `sc-user-id` header identifying which user a request is on behalf of. If you're coming from the V2 version, the setup flow looks different and the credentials you need from Smartcar are different — see [Setup](#setup) below.

> **Status:** This is a personal V3 rebuild. It works for the maintainer's vehicles but hasn't been broadly tested. If you try it, expect rough edges and check the [FAQ](FAQ.md) before opening issues.

## Prerequisites

1. **Compatible vehicle.** Check [Smartcar's compatibility list](https://smartcar.com/product/compatible-vehicles) and [regional availability](https://smartcar.com/global).
2. **Smartcar developer account** at [dashboard.smartcar.com](https://dashboard.smartcar.com/).
3. **Smartcar application set up for V3.** From the Smartcar dashboard you need three values from your application:
   - **Application ID** — used by Smartcar Connect to identify your app during the user-consent step.
   - **V3 Client ID** — used by the integration's backend to mint access tokens at `iam.smartcar.com`. Format: `client_xxx...`. Found under *API Credentials* on your application page.
   - **V3 Client Secret** — paired with the V3 Client ID.

   These are **three distinct values**, even though both "Application ID" and "V3 Client ID" can look similar at a glance. Mixing them up is the most common setup error.
4. **A publicly reachable HTTPS URL for Home Assistant.** Smartcar Connect redirects through your HA instance during setup, so HA needs to be accessible from the public internet. Either:
   - Home Assistant Cloud (Nabu Casa) — works automatically; the integration picks up your cloud URL.
   - Your own external URL — set under *Settings → System → Network → Home Assistant URL*. Must be HTTPS with a valid certificate.

## Installation

### HACS (recommended)

If this fork is registered as a custom HACS repository:

1. HACS → Integrations → ⋯ → Custom repositories → add this repo as type *Integration*.
2. Search for *Smartcar*, download the latest release.
3. Restart Home Assistant.

### Manual

1. Download the release zip.
2. Unpack and copy `custom_components/smartcar` into your Home Assistant `config/custom_components/` directory.
3. Restart Home Assistant.

## Setup

### Step 1 — Register the redirect URI on Smartcar

Before starting the HA setup, register Home Assistant's Connect callback URL with Smartcar.

- If you use Nabu Casa Cloud, the URL is `https://<your-id>.ui.nabu.casa/api/smartcar/callback`.
- If you have your own external URL, it's `https://<your-domain>/api/smartcar/callback`.

In the Smartcar dashboard, open your application's settings and add this URL under *Allowed Redirect URIs* (or whatever the equivalent is labelled — Smartcar's UI changes occasionally).

### Step 2 — Start the integration setup in HA

Settings → Devices & Services → *+ Add Integration* → search for *Smartcar*.

### Step 3 — Enter credentials

You'll be asked for the three values from your Smartcar dashboard. Pay attention to which field is which:

| Field | What it is | What it looks like |
|---|---|---|
| Application ID | The OAuth client ID Smartcar Connect uses | UUID or `client_xxx` (depends on when the app was created) |
| V3 Client ID | The API Credentials client ID | `client_xxx...` (under *API Credentials*) |
| V3 Client Secret | The API Credentials secret | opaque string (under *API Credentials*) |

The integration verifies the V3 Client ID + Secret immediately by minting a token at `iam.smartcar.com`. If they're wrong you get an error here rather than failing later.

### Step 4 — Webhook setup (optional but strongly recommended)

You'll be asked whether you want to use webhooks. If yes, paste your **Application Management Token** from the Smartcar dashboard (under *Configuration → API Keys*). The integration uses this to verify HMAC signatures on incoming webhook payloads.

You don't need to register the webhook URL yet — that happens after setup completes.

### Step 5 — Select permissions

Pick the scopes you want HA to request. You can tighten this later by removing connections in the Smartcar dashboard, but it's easier to grant broadly now.

### Step 6 — Connect

You'll be redirected to Smartcar Connect. Log in with the credentials for your **vehicle's connected services account** (e.g. your VW ID, FordPass, MyHyundai — **not** your Smartcar developer account), grant the requested permissions, and you'll be redirected back to HA.

### Step 7 — Webhook URL registration (if you enabled webhooks)

After setup completes, HA shows you a webhook URL like:

```
https://<your-ha-host>/api/webhook/<long-random-id>
```

This is the URL Smartcar pushes data to. You need to register it on the Smartcar dashboard:

1. Smartcar dashboard → *Integrations* → *Create integration* → *Webhook*.
2. Configure the signals you want delivered.
3. **Set the callback URI to the URL HA showed you.**
4. **Enable "Automatically subscribe all vehicles"** — see the [auto-enrollment](#auto-enrollment-required-for-data) section below.
5. Save.

### Auto-enrollment (required for data)

This is **critical** and the most common reason "everything looks set up but all entities are unavailable":

In V3, vehicles do not start producing signal data until they are **subscribed** to a webhook on Smartcar's side. Just registering the callback URL is not enough.

The simplest fix: on the Smartcar dashboard webhook configuration, enable the **"Automatically subscribe all vehicles"** option. This subscribes every vehicle connected to your application — both ones already connected and ones that connect in the future. Without this, both:

- Webhook events won't be delivered (Smartcar has nothing to deliver), and
- Polling via the `/v3/vehicles/{id}/signals` endpoint returns **404 Not Found** instead of data.

The 404 is correct per Smartcar's design: if there's no subscription, there's no data, and they return 404 rather than an empty list. The integration handles this gracefully (the entry sets up cleanly; entities just show as unavailable) but you won't get any data until you enable subscription.

If you don't want to auto-subscribe all vehicles, you can subscribe individual vehicles from the dashboard's *Vehicles* section, or use Smartcar's [Subscribe API](https://smartcar.com/docs/api-reference/webhooks/subscribe-webhook) directly.

## Entities

Entities created per vehicle, subject to vehicle compatibility, granted permissions, and webhook signal subscription. The list and behaviour is unchanged from the V2 version — refer to the [original README's entity reference](https://github.com/wbyoung/smartcar#entities) for the complete list and per-entity notes. The headline entities:

- `device_tracker.<make_model>_location` — GPS location.
- `sensor.<make_model>_battery` — state of charge percentage (EV/PHEV).
- `sensor.<make_model>_range` — estimated remaining range.
- `sensor.<make_model>_odometer` — total distance.
- `sensor.<make_model>_charging_status` — charging state.
- `sensor.<make_model>_fuel`, `_fuel_percent`, `_fuel_range` — fuel level (ICE/PHEV).
- `binary_sensor.<make_model>_*` — door/window/lock states, charging cable plugged, etc.
- `lock.<make_model>_door_lock` — lock/unlock control.
- `switch.<make_model>_charging` — start/stop charging.
- `number.<make_model>_charge_limit` — set target charge.
- `sensor.<make_model>_last_webhook_received` — diagnostic; updates every time a webhook arrives.

Each entity exposes `age` and `fetched_at` attributes when Smartcar provides them.

## Rate limits and polling

- **With webhooks subscribed** the integration relies on push delivery by default. Polling is off out of the box because each polled signal is one call against your Smartcar quota and webhooks are supposed to keep state fresh for free. If webhook delivery turns out to be unreliable on your setup (Smartcar's dashboard logs don't always surface dropped sends), enable the *Use polling as backup* checkbox in setup — or later under *Settings → Devices & Services → Smartcar → Configure* — to also poll the API hourly as a safety net. While the vehicle is charging the faster 15-minute cadence applies; outside of charging it's hourly.
- **Without webhooks** polling is the only data source. The cadence is the same: 1 hour idle, 15 minutes charging. The values are hard-coded — under Smartcar's free-tier ~500 calls/vehicle/month budget that's about right for typical driving patterns.
- Each vehicle exposes a diagnostic *Last Polled* sensor (under *Diagnostic* in the device view). It only ticks when an actual HTTP poll succeeds, so it's a clean indicator of whether the polling pipeline is healthy — independent of the webhook pipeline. In webhooks-only mode it'll sit at `unknown`, which is the correct signal that no polls are happening.
- You can also disable polling entirely from *Settings → Devices & Services → Smartcar → ⋯ → System Options → Enable polling for changes*, and trigger refreshes from automations via `homeassistant.update_entity`. The V3 `/signals` endpoint returns all signals in one call, so a single `update_entity` refreshes everything at once — there's no per-entity batching to worry about as there was in V2.

## What's different from V2

If you used the V2 version of this integration, things that changed:

- **Three credentials instead of one client_id/client_secret pair.** V3 split the OAuth identity into Application ID (for Connect) and Client ID/Secret (for IAM).
- **No more `my.home-assistant.io` intermediary in the OAuth flow.** Smartcar redirects directly to `<your-ha>/api/smartcar/callback`. You register that URL on Smartcar's dashboard. This also avoided some Safari/ITP issues with the older flow.
- **No more `application_credentials` integration dependency.** Credentials live in the config entry itself.
- **VIN endpoint is gone.** V3 has no `/vehicles/{id}/vin` endpoint. The integration uses Smartcar's `vehicle_id` (a UUID) as the unique identifier internally, in place of the VIN, so existing device_id-based references in automations may need updating after setup.
- **Auto-enrollment requirement.** See [above](#auto-enrollment-required-for-data) — V2 didn't have this concept; V3 vehicles don't push data until subscribed.

## Troubleshooting

See [FAQ.md](FAQ.md) for common issues:

- All entities unavailable → check auto-enrollment.
- Setup fails at Connect with "Invalid parameter client_id" → wrong value in the Application ID field.
- "Failed to setup" with "already been setup" errors → check FAQ.
- General Smartcar platform issues (brand reliability, signal availability, plan limits).

## License

Apache 2.0 — same as the original wbyoung/smartcar integration. See [LICENSE.md](LICENSE.md).

## Credits

This is a V3 rewrite of [wbyoung/smartcar](https://github.com/wbyoung/smartcar), maintained by [@wbyoung](https://github.com/wbyoung) and [@tube0013](https://github.com/tube0013). The entity model, naming conventions, and the bulk of the platform code (`sensor.py`, `binary_sensor.py`, etc.) come from the original. The auth, config flow, coordinator, and webhook layers are reworked for V3.
[hacs]: https://hacs.xyz/
[hacs-repo]: https://github.com/hacs/integration
[hacs-badge]: https://my.home-assistant.io/badges/hacs_repository.svg
[hacs-open]: https://my.home-assistant.io/redirect/hacs_repository/?owner=wbyoung&repository=smartcar&category=integration
[releases]: https://github.com/wbyoung/smartcar/releases
[config-flow-start]: https://my.home-assistant.io/redirect/config_flow_start/?domain=smartcar
[smartcar-dashboard]: https://dashboard.smartcar.com/team/applications
[ha-remote-access]: https://www.home-assistant.io/docs/configuration/remote/
[gh-sponsors]: https://github.com/sponsors/wbyoung
