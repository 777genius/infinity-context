from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkCleanupCompletionReceipt,
    ManagedBenchmarkRunRegistration,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
    ManagedBenchmarkRegistryHttpConfig,
    ManagedBenchmarkRegistryHttpError,
    managed_benchmark_registry_idempotency_key,
)
from memory_comparison_managed_benchmark_registry_test_support import (
    BASE_URL,
    BINDING,
    RUN,
    SPACE_ID,
    SPACE_SLUG,
    TOKEN,
    _cleanup,
    _close_with_cleanup_required,
    _config,
    _digest,
    _finalize,
    _lifecycle,
    _manifest,
    _registration,
    _seal,
    _target,
)


def test_exact_lifecycle_sends_bound_requests_and_returns_typed_receipts() -> None:
    requests: list[httpx.Request] = []
    manifest = _manifest()
    manifest_sha256 = _digest(manifest)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/cleanup/finalize"):
            return httpx.Response(
                200,
                json=_finalize(
                    manifest_sha256,
                    completed_at="2026-08-02T04:05:06.000000Z",
                ),
            )
        if request.method == "POST":
            return httpx.Response(201, json=_registration())
        if request.method == "PUT":
            return httpx.Response(200, json=_seal(manifest_sha256))
        return httpx.Response(200, json=_cleanup())

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    registration = adapter.register(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    seal = adapter.seal_projection_manifest(
        projection_manifest=manifest,
        projection_manifest_sha256=manifest_sha256,
    )
    cleanup = adapter.begin_cleanup()
    assert adapter._client.is_closed is False
    assert adapter.cleanup_required is True
    completion = adapter.finalize_cleanup(cleanup_initiation_receipt_sha256=cleanup.receipt_sha256)

    assert type(registration) is ManagedBenchmarkRunRegistration
    assert registration.schema_version == "memory-comparison-run-registration-response.v1"
    assert registration.authority == "infinity_canonical"
    assert registration.state == "active"
    assert registration.space_id == SPACE_ID
    assert registration.created is True
    assert seal.projection_manifest_sha256 == manifest_sha256
    assert cleanup.counts.vector_delete_jobs == 1
    assert cleanup.vector_delete_outbox_ids == (101,)
    assert cleanup.receipt_sha256 == _cleanup()["data"]["receipt_sha256"]
    assert type(completion) is ManagedBenchmarkCleanupCompletionReceipt
    assert completion.state == "cleanup_complete"
    assert completion.projection_cleanup == "complete"
    assert completion.cleanup_initiation_receipt_sha256 == cleanup.receipt_sha256
    assert completion.projection_manifest_sha256 == manifest_sha256
    assert completion.completed_at == "2026-08-02T04:05:06.000000Z"
    assert adapter.retries == 0
    assert adapter._client.is_closed is True
    assert adapter.cleanup_required is False
    assert [request.method for request in requests] == ["POST", "PUT", "DELETE", "POST"]
    assert [request.url.path for request in requests] == [
        "/v1/internal/memory-comparison/runs",
        f"/v1/internal/memory-comparison/runs/{RUN}/projection-manifest",
        f"/v1/internal/memory-comparison/runs/{RUN}",
        f"/v1/internal/memory-comparison/runs/{RUN}/cleanup/finalize",
    ]
    assert all(request.headers["authorization"] == f"Bearer {TOKEN}" for request in requests)
    assert "idempotency-key" in requests[0].headers
    assert "idempotency-key" not in requests[1].headers
    assert "idempotency-key" in requests[2].headers
    assert "idempotency-key" in requests[3].headers
    assert (
        len(
            {
                requests[0].headers["idempotency-key"],
                requests[2].headers["idempotency-key"],
                requests[3].headers["idempotency-key"],
            }
        )
        == 3
    )
    assert json.loads(requests[0].content) == {
        "schema_version": "memory-comparison-run-registration.v1",
        "run_id_sha256": RUN,
        "binding_commitment_sha256": BINDING,
        "infinity_target_identity_sha256": _target(),
        "space_slug": SPACE_SLUG,
    }
    assert json.loads(requests[3].content) == {
        "schema_version": "memory-comparison-run-cleanup-finalize.v1",
        "receipt_sha256": cleanup.receipt_sha256,
    }
    assert TOKEN not in repr(adapter)
    assert TOKEN not in repr(adapter._config)


def test_caller_supplied_idempotency_keys_are_forwarded_exactly() -> None:
    keys: list[str] = []
    manifest = _manifest()
    manifest_sha256 = _digest(manifest)

    def handler(request: httpx.Request) -> httpx.Response:
        if "idempotency-key" in request.headers:
            keys.append(request.headers["idempotency-key"])
        if request.url.path.endswith("/cleanup/finalize"):
            return httpx.Response(200, json=_finalize(manifest_sha256))
        if request.method == "POST":
            return httpx.Response(201, json=_registration())
        if request.method == "PUT":
            return httpx.Response(200, json=_seal(manifest_sha256))
        return httpx.Response(200, json=_cleanup())

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    adapter.register(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
        idempotency_key="caller-register-key",
    )
    adapter.seal_projection_manifest(
        projection_manifest=manifest,
        projection_manifest_sha256=manifest_sha256,
    )
    cleanup = adapter.begin_cleanup(idempotency_key="caller-cleanup-key")
    adapter.finalize_cleanup(
        cleanup_initiation_receipt_sha256=cleanup.receipt_sha256,
        idempotency_key="caller-finalize-key",
    )

    assert keys == [
        "caller-register-key",
        "caller-cleanup-key",
        "caller-finalize-key",
    ]


def test_deterministic_idempotency_helper_binds_operation_and_target() -> None:
    register = managed_benchmark_registry_idempotency_key(
        "register",
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        target_identity_sha256=_target(),
    )
    cleanup = managed_benchmark_registry_idempotency_key(
        "begin-cleanup",
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        target_identity_sha256=_target(),
    )

    assert register == managed_benchmark_registry_idempotency_key(
        "register",
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        target_identity_sha256=_target(),
    )
    finalize = managed_benchmark_registry_idempotency_key(
        "finalize-cleanup",
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        target_identity_sha256=_target(),
    )

    assert len({register, cleanup, finalize}) == 3
    assert 8 <= len(register) <= 240
    assert RUN not in register
    assert BINDING not in register


def test_registration_replay_requires_http_200_and_created_false() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=(_lifecycle() if request.method == "GET" else _registration(created=False)),
        )
    )
    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(transport))

    result = adapter.register(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )

    assert result.created is False
    assert adapter.lifecycle_state == "active"
    _close_with_cleanup_required(adapter)


def test_lifecycle_rejects_out_of_order_and_repeated_operations_without_io() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(201, json=_registration())

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as seal_error:
        adapter.seal_projection_manifest(
            projection_manifest=_manifest(),
            projection_manifest_sha256=_digest(_manifest()),
        )
    assert seal_error.value.code == "managed_benchmark_registry_lifecycle_invalid"
    adapter.register(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as repeat_error:
        adapter.register(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
        )
    assert repeat_error.value.code == "managed_benchmark_registry_lifecycle_invalid"
    assert calls == 1
    _close_with_cleanup_required(adapter)


def test_manifest_digest_and_registry_binding_are_validated_before_http() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(201, json=_registration())

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    adapter.register(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    manifest = _manifest()
    manifest["binding_commitment_sha256"] = "f" * 64

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.seal_projection_manifest(
            projection_manifest=manifest,
            projection_manifest_sha256=_digest(manifest),
        )

    assert caught.value.code == "managed_benchmark_registry_manifest_invalid"
    assert calls == 1
    _close_with_cleanup_required(adapter)


@pytest.mark.parametrize(
    ("response", "expected_code"),
    (
        (
            httpx.Response(302, headers={"location": "/elsewhere"}),
            "managed_benchmark_registry_response_rejected",
        ),
        (
            httpx.Response(
                201,
                text=json.dumps(_registration()),
                headers={"content-type": "text/plain"},
            ),
            "managed_benchmark_registry_response_invalid",
        ),
        (
            httpx.Response(
                201,
                content=b'{"data":{},"data":{}}',
                headers={"content-type": "application/json"},
            ),
            "managed_benchmark_registry_response_invalid",
        ),
        (
            httpx.Response(
                201,
                content=b"{}",
                headers={
                    "content-type": "application/json",
                    "content-length": "2000001",
                },
            ),
            "managed_benchmark_registry_response_too_large",
        ),
    ),
)
def test_response_status_type_shape_and_size_are_fail_closed(
    response: httpx.Response,
    expected_code: str,
) -> None:
    adapter = ManagedBenchmarkRegistryHttpAdapter(
        _config(httpx.MockTransport(lambda request: response))
    )

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.register(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
        )

    assert caught.value.code == expected_code
    assert str(caught.value) == expected_code
    assert TOKEN not in str(caught.value)
    assert adapter._client.is_closed is False
    _close_with_cleanup_required(adapter)


def test_config_rejects_target_mismatch_and_non_mock_injection() -> None:
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as target_error:
        ManagedBenchmarkRegistryHttpConfig(
            base_url=BASE_URL,
            admin_bearer_token=TOKEN,
            target_identity_sha256="f" * 64,
            timeout_seconds=30,
            benchmark_deadline=datetime.now(UTC) + timedelta(minutes=1),
            cleanup_recovery_timeout_seconds=120,
        )
    assert target_error.value.code == "managed_benchmark_registry_config_invalid"

    now = datetime.now(UTC)
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as deadline_error:
        ManagedBenchmarkRegistryHttpConfig(
            base_url=BASE_URL,
            admin_bearer_token=TOKEN,
            target_identity_sha256=_target(),
            timeout_seconds=30,
            benchmark_deadline=now + timedelta(minutes=2),
            cleanup_recovery_timeout_seconds=0,
        )
    assert deadline_error.value.code == "managed_benchmark_registry_config_invalid"

    transport = httpx.HTTPTransport(retries=0)
    try:
        with pytest.raises(ManagedBenchmarkRegistryHttpError) as transport_error:
            ManagedBenchmarkRegistryHttpConfig(
                base_url=BASE_URL,
                admin_bearer_token=TOKEN,
                target_identity_sha256=_target(),
                timeout_seconds=30,
                benchmark_deadline=datetime.now(UTC) + timedelta(minutes=1),
                cleanup_recovery_timeout_seconds=120,
                transport=transport,  # type: ignore[arg-type]
            )
        assert transport_error.value.code == "managed_benchmark_registry_config_invalid"
    finally:
        transport.close()
