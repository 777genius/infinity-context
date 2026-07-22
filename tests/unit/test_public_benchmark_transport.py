from __future__ import annotations

import builtins
import importlib
import sys
from collections.abc import Callable

import httpx
import pytest
from infinity_context_server.public_benchmark_transport import HttpBenchmarkAdapter


class _DerivedConnectError(httpx.ConnectError):
    pass


def _post(adapter: HttpBenchmarkAdapter, path: str = "/v1/context") -> httpx.Response:
    return adapter.post(path, json_body={"query": "when"}, headers={"X-Test": "yes"})


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    timeout: httpx.Timeout | None = None,
) -> httpx.Client:
    return httpx.Client(
        base_url="https://benchmark.invalid",
        transport=httpx.MockTransport(handler),
        timeout=timeout or httpx.Timeout(9.0),
    )


@pytest.mark.parametrize(
    "error_type",
    [httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout],
)
def test_exact_pre_delivery_failure_is_retried_with_delay(
    error_type: type[httpx.HTTPError],
) -> None:
    calls: list[httpx.Request] = []
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise error_type("not delivered", request=request)
        return httpx.Response(200, json={"data": {}}, request=request)

    with _client(handler) as client:
        response = _post(HttpBenchmarkAdapter(client, sleep=delays.append))

    assert response.status_code == 200
    assert len(calls) == 2
    assert delays == [0.05]


@pytest.mark.parametrize(
    "failure",
    [
        httpx.HTTPError,
        httpx.RequestError,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.TimeoutException,
        httpx.ReadError,
        httpx.WriteError,
        httpx.NetworkError,
        httpx.RemoteProtocolError,
        httpx.ProtocolError,
        _DerivedConnectError,
    ],
)
def test_ambiguous_or_post_delivery_failure_is_never_retried(
    failure: type[httpx.HTTPError],
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure is httpx.HTTPError:
            raise failure("unsafe to replay")
        raise failure("unsafe to replay", request=request)

    with (
        _client(handler) as client,
        pytest.raises(failure, match="unsafe to replay"),
    ):
        _post(HttpBenchmarkAdapter(client, sleep=lambda _: pytest.fail("slept")))

    assert calls == 1


def test_attempts_are_bounded() -> None:
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=request)

    with _client(handler) as client:
        adapter = HttpBenchmarkAdapter(client, sleep=delays.append)
        with pytest.raises(httpx.ConnectError, match="offline"):
            _post(adapter)

    assert calls == 2
    assert delays == [0.05]


def test_mutation_route_is_never_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectTimeout("offline", request=request)

    with _client(handler) as client, pytest.raises(httpx.ConnectTimeout):
        _post(HttpBenchmarkAdapter(client), "/v1/facts")

    assert calls == 1


def test_caller_cannot_configure_mutation_route_retries() -> None:
    with (
        _client(lambda request: httpx.Response(200, request=request)) as client,
        pytest.raises(TypeError, match="retryable_paths"),
    ):
        HttpBenchmarkAdapter(client, retryable_paths={"/v1/facts"})  # type: ignore[call-arg]


def test_error_status_is_returned_without_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    with _client(handler) as client:
        response = _post(HttpBenchmarkAdapter(client))

    assert response.status_code == 503
    assert calls == 1


def test_custom_httpx_timeout_configuration_is_preserved() -> None:
    observed: list[dict[str, float]] = []
    timeout = httpx.Timeout(connect=1.25, read=8.5, write=3.75, pool=0.5)

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request.extensions["timeout"])
        return httpx.Response(200, request=request)

    with _client(handler, timeout=timeout) as client:
        _post(HttpBenchmarkAdapter(client))

    assert observed == [{"connect": 1.25, "read": 8.5, "write": 3.75, "pool": 0.5}]


def test_client_recovers_after_non_retried_protocol_failure() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.RemoteProtocolError("broken response", request=request)
        return httpx.Response(200, request=request)

    with _client(handler) as client:
        adapter = HttpBenchmarkAdapter(client)
        with pytest.raises(httpx.RemoteProtocolError):
            _post(adapter)
        assert _post(adapter).status_code == 200

    assert calls == 2


def test_models_import_does_not_import_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    module_name = "infinity_context_server.public_benchmark_models"
    sys.modules.pop(module_name, None)
    real_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "httpx" or name.startswith("httpx."):
            raise AssertionError("model import loaded httpx")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    models = importlib.import_module(module_name)

    assert "HttpBenchmarkAdapter" not in vars(models)
    assert models.PublicBenchmarkCase.__name__ == "PublicBenchmarkCase"


def test_legacy_model_adapter_export_is_lazy_and_compatible() -> None:
    from infinity_context_server.public_benchmark_models import HttpBenchmarkAdapter as legacy

    assert legacy is HttpBenchmarkAdapter
