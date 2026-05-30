import asyncio
from collections.abc import Awaitable, Callable
from functools import reduce
import hashlib
import hmac
import logging
from typing import Any, cast, overload

from aiohttp import ClientConnectionError, ClientResponse

# Statuses that warrant an automatic retry with backoff. 429 is handled
# specially below: we only retry if Smartcar gave us a Retry-After hint.
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

# Connection-level errors that indicate a transient network problem worth
# retrying. We use the aiohttp base class ClientConnectionError to cover
# the whole subtree (ClientConnectorError, ServerDisconnectedError,
# ServerTimeoutError, ClientOSError, ...) without enumerating each one.
# TimeoutError covers asyncio.TimeoutError raised by aiohttp's own timeouts.
_TRANSIENT_NETWORK_ERRORS: tuple[type[BaseException], ...] = (
    ClientConnectionError,
    TimeoutError,
)


async def async_request_with_retry(
    request_fn: Callable[[], Awaitable[ClientResponse]],
    *,
    logger: logging.Logger,
    retry_statuses: frozenset[int] = _RETRYABLE_STATUSES,
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    context: str = "",
) -> ClientResponse:
    """Execute an async HTTP request with retry and exponential backoff.

    Retries on:
      * Transient network errors (DNS failures, dropped connections,
        socket-level read timeouts).
      * 5xx upstream errors (500, 502, 503, 504) using exponential
        backoff. If a ``Retry-After`` header is present its value is
        honoured (capped at ``max_delay``).
      * 429 rate-limit responses *only* when ``Retry-After`` is set;
        retrying without that guidance risks making rate limiting worse.

    The caller is responsible for calling ``raise_for_status()`` on the
    returned response and handling any remaining error status code.

    Returns:
        The response on success, or after retries are exhausted.

    Raises:
        ClientConnectionError, TimeoutError: If all retries fail with a
            transient network error.
        AssertionError: Should never be raised; satisfies the type checker.
    """
    for attempt in range(max_retries + 1):
        try:
            response = await request_fn()
        except _TRANSIENT_NETWORK_ERRORS as err:
            if attempt == max_retries:
                logger.warning(
                    "%s: %s after %s attempts, giving up",
                    context,
                    type(err).__name__,
                    attempt + 1,
                )
                raise
            delay = min(base_delay * 2**attempt, max_delay)
            logger.warning(
                "%s: %s, retrying in %.1fs (attempt %s/%s)",
                context,
                type(err).__name__,
                delay,
                attempt + 1,
                max_retries,
            )
            await asyncio.sleep(delay)
            continue

        if response.status not in retry_statuses or attempt == max_retries:
            return response

        # Parse Retry-After (seconds form; HTTP-date form not handled).
        retry_after_str = response.headers.get("Retry-After")
        retry_after: float | None = None
        if retry_after_str:
            try:
                retry_after = float(retry_after_str)
            except ValueError:
                retry_after = None

        # Smartcar rate-limited us without saying how long to wait; bail
        # rather than guess and risk worsening the situation.
        if response.status == 429 and retry_after is None:
            return response

        delay = (
            min(retry_after, max_delay)
            if retry_after is not None
            else min(base_delay * 2**attempt, max_delay)
        )

        logger.warning(
            "%s: HTTP %s, retrying in %.1fs (attempt %s/%s)",
            context,
            response.status,
            delay,
            attempt + 1,
            max_retries,
        )

        response.release()
        await asyncio.sleep(delay)

    # unreachable — the loop always returns — but satisfies the type checker
    raise AssertionError  # pragma: no cover


def unique_id_from_entry_data(data: dict) -> str:
    return " ".join(sorted(data["vehicles"].keys())).lower()


def vins_from_entry_data(data: dict) -> str:
    return " ".join(sorted([vehicle["vin"] for vehicle in data["vehicles"].values()]))


def hmac_sha256_hexdigest(key: str, msg: str) -> str:
    return hmac.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest()


def _key_path_traverse[KeyT: str, ValueT](
    dict_obj: dict[KeyT, ValueT],
    key_path: str,
    offset: int = 0,
    /,
    *,
    fill: bool = False,
) -> Any:  # noqa: ANN401
    assert offset <= 0
    try:
        return reduce(
            lambda v, key: (
                None if v is None else v.setdefault(key, {}) if fill else v[key]
            ),
            key_path.split(".")[: offset or None],
            cast("Any", dict_obj),
        )
    except KeyError as err:
        raise KeyError(key_path) from err


def key_path_get[KeyT: str, ValueT, EndValueT](
    dict_obj: dict[KeyT, ValueT], key_path: str, default: EndValueT | None = None, /
) -> EndValueT | None:
    try:
        return cast("EndValueT", _key_path_traverse(dict_obj, key_path))
    except KeyError:
        return default


@overload
def key_path_pop[KeyT: str, ValueT, EndValueT](
    dict_obj: dict[KeyT, ValueT], key_path: str, default: EndValueT | None = None, /
) -> EndValueT: ...


@overload
def key_path_pop[KeyT: str, ValueT](
    dict_obj: dict[KeyT, ValueT], key_path: str
) -> Any: ...  # noqa: ANN401


def key_path_pop(dict_obj, key_path, /, *args):
    try:
        dict_obj = _key_path_traverse(dict_obj, key_path, -1)
        return dict_obj.pop(key_path.split(".")[-1])
    except KeyError as err:
        has_default = len(args) > 0
        if has_default:
            return args[0]
        raise KeyError(key_path) from err


def key_path_update[KeyT: str, ValueT, EndValueT](
    dict_obj: dict[KeyT, ValueT], key_path: str, value: EndValueT
) -> None:
    sub_dict: Any = _key_path_traverse(dict_obj, key_path, -1, fill=True)
    sub_dict[key_path.rsplit(".", maxsplit=1)[-1]] = value


def key_path_transpose[KeyT: str, ValueT](
    dict_obj: dict[KeyT, ValueT],
    key_path_transpositions: dict[str, str],
    *,
    strict: bool = False,
) -> None:
    for from_key_path, to_key_path in key_path_transpositions.items():
        try:
            value: Any = key_path_pop(dict_obj, from_key_path)
            key_path_update(dict_obj, to_key_path, value)
        except KeyError as err:
            if strict:
                raise KeyError(from_key_path) from err
