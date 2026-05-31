"""HTTP view that receives the Smartcar Connect redirect.

Smartcar's V3 Connect flow redirects the user's browser to a fixed callback
URL with these query parameters of interest:

  * ``state``    — opaque value we generated when launching the flow.
  * ``code``     — short-lived authorization code; ignored in V3.
  * ``user_id``  — the Smartcar user identifier (sometimes documented as
                   ``userId``; the live redirect uses snake_case).

We can't reuse Home Assistant's ``/auth/external/callback`` view because it
only forwards ``code`` and ``state`` to the flow. We need the user id too,
so we register our own view at a stable path. The user puts that path into
the Smartcar dashboard once.

Registration timing
-------------------
HA only calls a config-flow-only integration's ``async_setup`` after the
first config entry exists. During initial setup the view must be registered
*before* the user is sent to Connect, otherwise the redirect 404s. So this
module's :func:`async_register_view` is idempotent and is called both from
``async_setup`` (for subsequent restarts) and from the config flow itself
(for the very first run).

Security
--------
  * The ``state`` value is stored on the running config flow before the user
    is sent to Connect, and is treated as one-time-use: present, match, then
    discarded. A replayed callback URL with the same ``state`` won't find an
    active flow and will be rejected.
  * The view rejects unknown ``state`` values with a 400 so attackers can't
    use it as an oracle.
  * Authentication is intentionally not required — Smartcar can't authenticate
    to Home Assistant, but the ``state`` value plus the random flow id give
    sufficient protection against forgery.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Where the user registers this on the Smartcar dashboard:
#   https://<their-ha-external-url>/api/smartcar/callback
CALLBACK_PATH = "/api/smartcar/callback"

# Keys under hass.data:
#   * pending state → flow_id map, populated when launching a flow
#   * registration sentinel, set once the view is attached to the HTTP app
DATA_PENDING_FLOWS = "pending_oauth_flows"
DATA_VIEW_REGISTERED = "callback_view_registered"


def register_state(hass: HomeAssistant, state: str, flow_id: str) -> None:
    """Park a flow id under a state token so the callback can find it."""
    hass.data.setdefault(DOMAIN, {}).setdefault(DATA_PENDING_FLOWS, {})[state] = flow_id


def pop_state(hass: HomeAssistant, state: str) -> str | None:
    """Look up and remove a parked flow id by its state token.

    Returns:
        The flow id previously parked under ``state``, or ``None`` if no
        active flow matches (expired, replayed, or never registered).
    """
    pending = hass.data.get(DOMAIN, {}).get(DATA_PENDING_FLOWS, {})
    value = pending.pop(state, None)
    return value if isinstance(value, str) else None


class SmartcarConnectCallbackView(HomeAssistantView):
    """Handle GET ``/api/smartcar/callback``."""

    url = CALLBACK_PATH
    name = "smartcar:callback"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:  # noqa: PLR6301
        """Resume the config flow with the user id from the redirect URL.

        Returns:
            An HTTP response. Always 200 with a "you can close this window"
            page on the happy path; 400 if the state parameter is missing
            or no longer matches an active flow.
        """
        hass: HomeAssistant = request.app["hass"]

        state = request.query.get("state")
        # Smartcar's current redirects use `user_id` (snake_case). Older docs
        # show `userId`. Accept either to be safe.
        user_id = request.query.get("user_id") or request.query.get("userId")
        code = request.query.get("code")  # accepted but unused in V3
        error = request.query.get("error")

        if not state:
            _LOGGER.warning("Smartcar callback missing state")
            return web.Response(status=400, text="Missing state parameter")

        flow_id = pop_state(hass, state)
        if not flow_id:
            _LOGGER.warning(
                "Smartcar callback received with unknown state (possibly "
                "expired or replayed)"
            )
            return web.Response(
                status=400,
                text="Invalid or expired state. Restart the integration setup.",
            )

        if error:
            _LOGGER.warning("Smartcar callback signalled error: %s", error)
            user_input: dict[str, Any] = {"error": error}
        elif not user_id:
            _LOGGER.warning("Smartcar callback missing user_id; cannot proceed")
            user_input = {"error": "missing_user_id"}
        else:
            user_input = {"userId": user_id, "code": code}

        # We intentionally don't 500 the browser tab if async_configure raises.
        # The actual flow outcome (success, abort, etc.) is reflected in the
        # HA UI where the user can see it; the browser tab here is just a
        # courtesy "you can close this window" page. Returning 500 from the
        # callback hides successful setups behind a scary error page when the
        # exception was, for example, a benign duplicate-setup race.
        try:
            await hass.config_entries.flow.async_configure(
                flow_id, user_input=user_input
            )
        except Exception:
            _LOGGER.exception(
                "Error while resuming Smartcar config flow. Check "
                "Settings \u2192 Devices & Services to see whether the entry "
                "was created successfully despite this."
            )

        return web.Response(
            content_type="text/html",
            text=(
                "<!doctype html><html><head><title>Smartcar authorization</title>"
                '<meta charset="utf-8"></head><body style="font-family:sans-serif;'
                'padding:2rem;">'
                "<h2>Authorization complete</h2>"
                "<p>You can close this window and return to Home Assistant.</p>"
                "<script>setTimeout(function(){window.close();},1500);</script>"
                "</body></html>"
            ),
        )


def async_register_view(hass: HomeAssistant) -> None:
    """Register the callback view exactly once per HA process.

    Idempotent: safe to call from ``async_setup`` and from the config flow.
    The first caller registers the view; subsequent callers are no-ops.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(DATA_VIEW_REGISTERED):
        return
    hass.http.register_view(SmartcarConnectCallbackView())
    domain_data[DATA_VIEW_REGISTERED] = True
    _LOGGER.debug("Registered Smartcar OAuth callback view at %s", CALLBACK_PATH)
