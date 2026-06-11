from contextlib import nullcontext
import copy
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.smartcar.util import (
    async_request_with_retry,
    hmac_sha256_hexdigest,
    key_path_get,
    key_path_pop,
    key_path_transpose,
    key_path_update,
)


def test_hmac_sha256_hexdigest():
    assert (
        hmac_sha256_hexdigest("secret", "text")
        == "2f443685592900e619f2f3b2350c3c8a5738e2e7a26bc9a244d3393c3cd6abd6"
    )


@pytest.mark.parametrize(
    ("obj", "key_path", "default_args", "expected_result", "expected_exception"),
    [
        (
            {"person": {"name": "Veda", "age": 22}},
            "person.age",
            [],
            22,
            None,
        ),
        (
            {"person": "Veda"},
            "person.age",
            [],
            ...,
            TypeError,
        ),
        (
            {"person": {}},
            "person.age",
            [],
            None,
            None,
        ),
        (
            {"person": {}},
            "person.age",
            [21],
            21,
            None,
        ),
        (
            {"person": None},
            "person.age",
            [],
            None,
            None,
        ),
    ],
    ids=[
        "person.age",
        "person.age:TypeError",
        "person.age:standard-default",
        "person.age:default",
        "person.age:null-value",
    ],
)
def test_key_path_get(
    obj: dict[str, Any],
    key_path: str,
    default_args: list[Any],
    expected_result: Any,
    expected_exception: type[Exception] | None,
):
    with pytest.raises(expected_exception) if expected_exception else nullcontext():
        assert key_path_get(obj, key_path, *default_args) == expected_result


@pytest.mark.parametrize(
    (
        "obj",
        "key_path",
        "default_args",
        "expected_result",
        "expected_obj",
        "expected_exception",
    ),
    [
        (
            {"person": {"name": "Veda", "age": 22}},
            "person.age",
            [],
            22,
            {"person": {"name": "Veda"}},
            None,
        ),
        (
            {"person": {"name": "Veda"}},
            "person.age",
            [],
            None,
            {"person": {"name": "Veda"}},
            KeyError,
        ),
        (
            {"person": {"name": "Veda"}},
            "person.age",
            [21],
            21,
            {"person": {"name": "Veda"}},
            None,
        ),
    ],
    ids=["person.age", "person.age:KeyError", "person.age:default"],
)
def test_key_path_pop(
    obj: dict[str, Any],
    key_path: str,
    default_args: list[Any],
    expected_result: Any,
    expected_obj: Any,
    expected_exception: type[Exception] | None,
):
    obj = copy.deepcopy(obj)
    with pytest.raises(expected_exception) if expected_exception else nullcontext():
        result: Any = key_path_pop(obj, key_path, *default_args)
        assert result == expected_result
        assert obj == expected_obj


@pytest.mark.parametrize(
    ("obj", "key_path", "value", "expected_result", "expected_exception"),
    [
        (
            {"person": {"name": "Veda"}},
            "person.age",
            22,
            {"person": {"name": "Veda", "age": 22}},
            None,
        ),
        (
            {"person": "Veda"},
            "person.age",
            22,
            None,
            TypeError,
        ),
        (
            {},
            "person.age",
            22,
            {"person": {"age": 22}},
            None,
        ),
        (
            {},
            "",
            22,
            {"": 22},
            None,
        ),
    ],
    ids=["person.age", "person.age:TypeError", "person.age:default", "no_key"],
)
def test_key_path_update(
    obj: dict[str, Any],
    key_path: str,
    value: Any,
    expected_result: Any,
    expected_exception: type[Exception] | None,
):
    obj = copy.deepcopy(obj)

    with pytest.raises(expected_exception) if expected_exception else nullcontext():
        key_path_update(obj, key_path, value)
        assert obj == expected_result


@pytest.mark.parametrize(
    ("obj", "transpositions", "extra_kwargs", "expected_result", "expected_exception"),
    [
        (
            {"person": {"name": "Veda"}},
            {"person.name": "person.first_name"},
            {},
            {"person": {"first_name": "Veda"}},
            None,
        ),
        (
            {"person": {"name": "Veda"}},
            {"person.name": "person.details.name"},
            {},
            {"person": {"details": {"name": "Veda"}}},
            None,
        ),
        (
            {"person": {"details": {"name": "Veda"}}},
            {"person.details.name": "person.name"},
            {},
            {"person": {"name": "Veda", "details": {}}},
            None,
        ),
        (
            {"person": {"name": "Veda"}},
            {"person.first_name": "person.given_name"},
            {},
            {"person": {"name": "Veda"}},
            None,
        ),
        (
            {"person": {"name": "Veda"}},
            {"person.first_name": "person.given_name"},
            {"strict": True},
            {"person": {"name": "Veda"}},
            KeyError,
        ),
    ],
    ids=[
        "rename_attr",
        "nest_attr",
        "unnest_attr",
        "misnamed_key",
        "misnamed_key:strict",
    ],
)
def test_key_path_transpose(
    obj: dict[str, Any],
    transpositions: dict[str, str],
    extra_kwargs: dict[str, Any],
    expected_result: Any,
    expected_exception: type[Exception] | None,
):
    obj = copy.deepcopy(obj)

    with pytest.raises(expected_exception) if expected_exception else nullcontext():
        key_path_transpose(obj, transpositions, **extra_kwargs)
        assert obj == expected_result


def _mock_response(status: int, headers: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.headers = headers or {}
    resp.release = MagicMock()
    return resp


_logger = logging.getLogger(__name__)


async def test_retry_success_first_attempt():
    ok = _mock_response(200)
    request_fn = AsyncMock(return_value=ok)

    result = await async_request_with_retry(request_fn, logger=_logger, context="test")

    assert result is ok
    assert request_fn.call_count == 1


async def test_retry_500_then_success():
    error = _mock_response(500)
    ok = _mock_response(200)
    request_fn = AsyncMock(side_effect=[error, ok])

    result = await async_request_with_retry(
        request_fn, logger=_logger, context="test", base_delay=0.01
    )

    assert result is ok
    assert request_fn.call_count == 2
    error.release.assert_called_once()


async def test_retry_429_with_retry_after_then_success():
    rate_limited = _mock_response(429, headers={"Retry-After": "0.01"})
    ok = _mock_response(200)
    request_fn = AsyncMock(side_effect=[rate_limited, ok])

    result = await async_request_with_retry(request_fn, logger=_logger, context="test")

    assert result is ok
    assert request_fn.call_count == 2
    rate_limited.release.assert_called_once()


async def test_retry_429_without_retry_after_does_not_retry():
    rate_limited = _mock_response(429)
    request_fn = AsyncMock(return_value=rate_limited)

    result = await async_request_with_retry(request_fn, logger=_logger, context="test")

    assert result is rate_limited
    assert request_fn.call_count == 1


async def test_retry_429_with_invalid_retry_after_does_not_retry():
    rate_limited = _mock_response(429, headers={"Retry-After": "not-a-number"})
    request_fn = AsyncMock(return_value=rate_limited)

    result = await async_request_with_retry(request_fn, logger=_logger, context="test")

    assert result is rate_limited
    assert request_fn.call_count == 1


async def test_retry_caps_retry_after_at_max_delay():
    rate_limited = _mock_response(429, headers={"Retry-After": "999"})
    ok = _mock_response(200)
    request_fn = AsyncMock(side_effect=[rate_limited, ok])

    result = await async_request_with_retry(
        request_fn,
        logger=_logger,
        context="test",
        max_delay=0.01,
    )

    assert result is ok
    assert request_fn.call_count == 2


async def test_retry_exhausted_returns_failed_response():
    error = _mock_response(500)
    request_fn = AsyncMock(return_value=error)

    result = await async_request_with_retry(
        request_fn,
        logger=_logger,
        context="test",
        max_retries=2,
        base_delay=0.01,
    )

    assert result is error
    assert request_fn.call_count == 3  # 1 initial + 2 retries


async def test_retry_non_retryable_status_returns_immediately():
    forbidden = _mock_response(403)
    request_fn = AsyncMock(return_value=forbidden)

    result = await async_request_with_retry(request_fn, logger=_logger, context="test")

    assert result is forbidden
    assert request_fn.call_count == 1
