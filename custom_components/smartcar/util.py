import asyncio
from collections.abc import Awaitable, Callable
from functools import reduce
import hashlib
import hmac
import logging
import re
from typing import Any, cast, overload

from aiohttp import ClientResponse

from .types import APIVersion

_RETRYABLE_STATUSES = frozenset({429, 500})


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

    Retries on 500 responses with exponential backoff. For 429
    responses, only retries when a Retry-After header is present.
    The caller is responsible for calling raise_for_status() and
    handling errors.

    Returns:
        The response on success or after retries are exhausted.

    Raises:
        AssertionError: Should never be raised; satisfies the type checker.
    """
    for attempt in range(max_retries + 1):
        response = await request_fn()

        if response.status not in retry_statuses or attempt == max_retries:
            return response

        if response.status == 429:
            retry_after = response.headers.get("Retry-After")
            if not retry_after:
                return response
            try:
                delay = min(float(retry_after), max_delay)
            except ValueError:
                return response
        else:
            delay = min(base_delay * 2**attempt, max_delay)

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


def api_version_for_client_id(client_id: str) -> APIVersion:
    if re.match(r"^client_", client_id):
        return "v3"
    return "v2"


def unique_id_from_entry_data(data: dict) -> str:
    return " ".join(sorted(data["vehicles"].keys())).lower()


def vins_from_entry_data(data: dict) -> str:
    return " ".join(
        sorted(
            [
                vehicle["vin"]
                for vehicle in data["vehicles"].values()
                if vehicle.get("vin")
            ]
        )
    )


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
