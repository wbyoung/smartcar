"""Smartcar V3 integration setup.

The OAuth2 framework dependency has been removed. We now run an explicit
token manager that fetches application-level tokens via the V3 IAM endpoint
on demand, and read the captured ``sc_user_id`` directly from the entry data.
"""

from __future__ import annotations

from functools import partial
from http import HTTPStatus
import logging
from typing import Any

from aiohttp import ClientResponseError
from homeassistant.components import cloud, webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .auth import AbstractAuth
from .auth_impl import AsyncConfigEntryAuth, ClientCredentialsTokenManager
from .const import (
    API_HOST,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_CLOUDHOOK,
    CONF_SC_USER_ID,
    CONF_SCOPES,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import SmartcarVehicleCoordinator
from .errors import EmptyVehicleListError, InvalidAuthError
from .services import async_setup_services
from .types import SmartcarData
from .util import async_request_with_retry
from .views import async_register_view
from .webhooks import handle_webhook, webhook_url_from_id

_LOGGER = logging.getLogger(__name__)


async def async_setup(  # noqa: RUF029
    hass: HomeAssistant,
    config: ConfigType,  # noqa: ARG001
) -> bool:
    """Component-level setup. Runs once at HA startup.

    Registers services and the OAuth callback view. The view is shared across
    all Smartcar config entries (only one is needed for the whole component).
    """
    async_setup_services(hass)
    async_register_view(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Smartcar config entry."""
    websession = async_get_clientsession(hass)

    # One token manager per entry — caches the IAM access token between calls
    # and re-mints when it expires.
    token_manager = ClientCredentialsTokenManager(
        websession,
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET],
    )

    auth = AsyncConfigEntryAuth(
        websession,
        token_manager,
        API_HOST,
        entry.data.get(CONF_SC_USER_ID),
    )

    coordinators: dict[str, SmartcarVehicleCoordinator] = {}
    meta_coordinator = DataUpdateCoordinator(
        hass, _LOGGER, name=f"{DOMAIN}_meta", config_entry=entry
    )
    meta_coordinator.async_set_updated_data({})

    entry.runtime_data = SmartcarData(
        auth=auth,
        coordinators=coordinators,
        meta_coordinator=meta_coordinator,
    )

    device_registry = dr.async_get(hass)
    other_vins = vehicle_vins_in_use(hass, entry)

    for vehicle_id, details in entry.data.get("vehicles", {}).items():
        vin = details["vin"]
        make = details.get("make")
        model = details.get("model")
        year = details.get("year")

        if vin in other_vins:
            msg = f"Cannot setup multiple config entries with VIN {vin}"
            raise ConfigEntryError(msg)

        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, vin)},
            manufacturer=make,
            model=f"{model} ({year})" if model and year else model,
            name=f"{make} {model}" if make and model else f"Smartcar {vin[-4:]}",
        )

        coordinator = SmartcarVehicleCoordinator(hass, auth, vehicle_id, vin, entry)
        coordinators[vin] = coordinator

    # Webhook registration BEFORE forward. If it fails (e.g., Nabu Casa
    # transient outage), we want HA to retry the whole setup cleanly — at
    # this point no platforms have been registered yet, so a retry won't
    # hit the "already been setup" guard.
    if CONF_WEBHOOK_ID in entry.data:
        try:
            _LOGGER.info(
                "Registering webhook at: %s",
                (await webhook_url_from_id(hass, entry.data[CONF_WEBHOOK_ID]))[0],
            )
            webhook.async_register(
                hass,
                DOMAIN,
                entry.title,
                entry.data[CONF_WEBHOOK_ID],
                partial(handle_webhook, config_entry=entry),
            )
        except Exception:
            _LOGGER.exception(
                "Failed to register webhook; webhooks won't work until reload"
            )

    # async_forward_entry_setups is the "commit point" of setup. After this
    # succeeds the entry is fully registered with HA. Critically, anything
    # that raises *after* this call will trigger HA to mark the entry as
    # SETUP_RETRY and call async_setup_entry again — and that second call
    # will hit `Config entry has already been setup!` because the platforms
    # we just registered are still in HA's bookkeeping. So everything that
    # can fail must come before this line, and nothing that can fail may
    # come after.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # First refresh as fire-and-forget. We don't await it because if it
    # raised, async_setup_entry would re-trigger the retry loop described
    # above. Failures here just mean entities are temporarily unavailable
    # until the next periodic poll or webhook arrives — the coordinator
    # handles its own auth/retry logic and will surface ConfigEntryAuthFailed
    # via async_start_reauth without going through async_setup_entry.
    for coordinator in coordinators.values():
        hass.async_create_task(
            coordinator.async_refresh(),
            f"{DOMAIN}-first-refresh-{coordinator.vin}",
        )

    _LOGGER.info(
        "Smartcar entry %s loaded with %d vehicles, scopes=%s",
        entry.entry_id,
        len(coordinators),
        entry.data.get(CONF_SCOPES),
    )

    entry.async_on_unload(
        entry.add_update_listener(
            partial(async_update_listener, initial_data=entry.data)
        )
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if CONF_WEBHOOK_ID in entry.data:
        webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])
    return bool(await hass.config_entries.async_unload_platforms(entry, PLATFORMS))


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up cloudhook on removal."""
    if CONF_WEBHOOK_ID in entry.data and (
        cloud.async_active_subscription(hass) or entry.data.get(CONF_CLOUDHOOK, False)
    ):
        try:
            await cloud.async_delete_cloudhook(hass, entry.data[CONF_WEBHOOK_ID])
        except cloud.CloudNotAvailable:
            pass


async def async_update_listener(
    hass: HomeAssistant,
    entry: ConfigEntry,
    initial_data: dict[str, Any],
) -> None:
    """Reload the entry when meaningful data changes."""
    # We strip transient fields before comparing so token refreshes etc don't
    # trigger a reload.
    transient = {CONF_SC_USER_ID, CONF_SCOPES}
    a = {k: v for k, v in entry.data.items() if k not in transient}
    b = {k: v for k, v in initial_data.items() if k not in transient}
    if a != b:
        await hass.config_entries.async_reload(entry.entry_id)


def vehicle_vins_in_use(
    hass: HomeAssistant, config_entry: ConfigEntry = None
) -> set[str]:
    """Return all VINs in use across other Smartcar config entries."""
    return {
        vehicle["vin"]
        for other_entry in hass.config_entries.async_entries(DOMAIN)
        for vehicle in other_entry.data.get("vehicles", {}).values()
        if not config_entry or other_entry.unique_id != config_entry.unique_id
    }


async def populate_entry_data(data: dict, auth: AbstractAuth) -> None:
    """Populate ``vehicles`` and ``CONF_SCOPES`` via ``/v3/connections``.

    The ``CONF_SC_USER_ID`` is already set by the time we reach here (it came
    from the Smartcar Connect callback). We use it to filter the
    ``/connections`` response to vehicles belonging to this user.

    Vehicle identifiers: V3 removed the dedicated ``/vin`` endpoint, and the
    ``GET /vehicles/{id}`` response doesn't include VIN either. The VIN is
    now a signal whose code isn't consistently documented across pages, so
    rather than make a fragile extra API call during setup we use Smartcar's
    own ``vehicle_id`` (a UUID) as the unique identifier. The field is still
    called ``vin`` in storage for backwards compatibility with the rest of
    the integration's code paths.
    """
    user_id = data.get(CONF_SC_USER_ID)
    if not user_id:
        raise InvalidAuthError("Missing sc_user_id; the Connect callback didn't return userId")

    connections = await _fetch_connections(auth, user_id)
    if not connections:
        raise EmptyVehicleListError

    granted: set[str] = set()
    vehicles: dict[str, dict[str, Any]] = {}
    for connection in connections:
        attrs = connection.get("attributes", {})
        vehicle_id = _vehicle_id_from_connection(connection)
        if not vehicle_id:
            continue
        vehicle_attrs = attrs.get("vehicle") or {}
        vehicles[vehicle_id] = {
            "make": vehicle_attrs.get("make"),
            "model": vehicle_attrs.get("model"),
            "year": vehicle_attrs.get("year"),
            # Identifier reused as "vin" so the rest of the code paths
            # (device registry, coordinator keying, webhook routing) work
            # without touching them.
            "vin": vehicle_id,
        }
        granted.update(attrs.get("permissions") or [])

    data[CONF_SCOPES] = sorted(granted)
    data["vehicles"] = vehicles


async def _fetch_connections(
    auth: AbstractAuth, user_id: str
) -> list[dict[str, Any]]:
    """Return all connections for the given user, with retry on transient errors."""
    all_connections: list[dict[str, Any]] = []
    page = 1
    while True:
        try:
            resp = await async_request_with_retry(
                lambda p=page: auth.request(
                    "get",
                    f"connections?filter[userId]={user_id}&page[number]={p}&page[size]=50",
                ),
                logger=_LOGGER,
                context=f"Setup: /connections page {page}",
            )
        except ClientResponseError as err:
            if err.status == HTTPStatus.UNAUTHORIZED:
                msg = f"Auth error fetching connections: {err.status}"
                raise InvalidAuthError(msg) from err
            raise

        if resp.status == HTTPStatus.UNAUTHORIZED:
            resp.release()
            raise InvalidAuthError("Auth error fetching connections")
        resp.raise_for_status()
        payload = await resp.json()
        all_connections.extend(payload.get("data") or [])
        links = payload.get("links") or {}
        if not links.get("next"):
            break
        page += 1
        if page > 20:  # runaway-page safety net
            break

    return all_connections


def _vehicle_id_from_connection(connection: dict[str, Any]) -> str | None:
    return (
        connection.get("relationships", {})
        .get("vehicle", {})
        .get("data", {})
        .get("id")
    )


