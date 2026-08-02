from __future__ import annotations

import httpx
import pytest
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
    ManagedBenchmarkRegistryHttpError,
)
from memory_comparison_managed_benchmark_registry_test_support import (
    BINDING,
    RUN,
    SPACE_SLUG,
    _cleanup,
    _config,
    _digest,
    _finalize,
    _lifecycle,
    _manifest,
    _persisted_cleanup,
    _persisted_completion,
    _registration,
    _seal,
)


def test_lost_delete_response_new_process_recovers_pending_and_finalizes() -> None:
    state = "new"
    manifest = _manifest()
    manifest_sha256 = _digest(manifest)
    initiation = _cleanup()["data"]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal state
        if request.url.path.endswith("/cleanup/finalize"):
            state = "cleanup_complete"
            return httpx.Response(200, json=_finalize(manifest_sha256))
        if request.method == "POST":
            created = state == "new"
            if created:
                state = "active"
            return httpx.Response(
                201 if created else 200,
                json=_registration(created=created, state=state),
            )
        if request.method == "PUT":
            state = "sealed"
            return httpx.Response(200, json=_seal(manifest_sha256))
        if request.method == "DELETE":
            state = "cleanup_pending"
            raise RuntimeError("committed cleanup response lost")
        assert request.method == "GET"
        return httpx.Response(
            200,
            json=_lifecycle(
                state="cleanup_pending",
                projection_cleanup_state="pending",
                projection_manifest_sha256=manifest_sha256,
                cleanup_receipt=_persisted_cleanup(),
            ),
        )

    process_a = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    process_a.register(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    process_a.seal_projection_manifest(
        projection_manifest=manifest,
        projection_manifest_sha256=manifest_sha256,
    )
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as lost:
        process_a.begin_cleanup()
    assert lost.value.code == "managed_benchmark_registry_request_failed"

    process_b = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    replay = process_b.register(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    assert replay.created is False
    assert replay.state == "cleanup_pending"
    assert process_b.lifecycle_state == "cleanup_pending"
    assert process_b.recovered_cleanup_receipt is not None
    assert process_b.recovered_cleanup_receipt.receipt_sha256 == initiation["receipt_sha256"]

    completion = process_b.finalize_cleanup(
        cleanup_initiation_receipt_sha256=process_b.recovered_cleanup_receipt.receipt_sha256
    )
    assert completion.projection_cleanup == "complete"
    assert process_b.lifecycle_state == "cleanup_complete"
    assert process_b.cleanup_required is False
    assert process_b._client.is_closed is True
    process_a._client.close()


def test_lost_finalize_response_new_process_recovers_terminal_and_closes() -> None:
    state = "new"
    manifest = _manifest()
    manifest_sha256 = _digest(manifest)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal state
        if request.url.path.endswith("/cleanup/finalize"):
            state = "cleanup_complete"
            raise RuntimeError("committed finalize response lost")
        if request.method == "POST":
            created = state == "new"
            if created:
                state = "active"
            return httpx.Response(
                201 if created else 200,
                json=_registration(created=created, state=state),
            )
        if request.method == "PUT":
            state = "sealed"
            return httpx.Response(200, json=_seal(manifest_sha256))
        if request.method == "DELETE":
            state = "cleanup_pending"
            return httpx.Response(200, json=_cleanup())
        assert request.method == "GET"
        return httpx.Response(
            200,
            json=_lifecycle(
                state="cleanup_complete",
                projection_cleanup_state="complete",
                projection_manifest_sha256=manifest_sha256,
                cleanup_receipt=_persisted_cleanup(),
                completion_receipt=_persisted_completion(manifest_sha256),
            ),
        )

    process_a = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    process_a.register(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    process_a.seal_projection_manifest(
        projection_manifest=manifest,
        projection_manifest_sha256=manifest_sha256,
    )
    initiation = process_a.begin_cleanup()
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as lost:
        process_a.finalize_cleanup(cleanup_initiation_receipt_sha256=initiation.receipt_sha256)
    assert lost.value.code == "managed_benchmark_registry_request_failed"

    process_b = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    replay = process_b.register(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    assert replay.state == "cleanup_complete"
    assert process_b.lifecycle_state == "cleanup_complete"
    assert process_b.recovered_completion_receipt is not None
    assert process_b.cleanup_required is False
    assert process_b._client.is_closed is True
    process_a._client.close()


def test_active_registration_replay_gets_sealed_snapshot_before_cleanup() -> None:
    manifest = _manifest()
    manifest_sha256 = _digest(manifest)
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(200, json=_registration(created=False))
        if request.method == "GET":
            assert request.content == b""
            assert "idempotency-key" not in request.headers
            return httpx.Response(
                200,
                json=_lifecycle(
                    projection_cleanup_state="sealed",
                    projection_manifest_sha256=manifest_sha256,
                ),
            )
        return httpx.Response(200, json=_cleanup())

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    adapter.register(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    initiation = adapter.begin_cleanup()

    assert initiation.projection_cleanup == "pending"
    assert methods == ["POST", "GET", "DELETE"]
    assert adapter.lifecycle_state == "cleanup_pending"
    adapter._client.close()


def test_cleanup_blocked_snapshot_cannot_finalize() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json=_lifecycle(
                state="cleanup_pending",
                projection_cleanup_state="blocked",
                cleanup_receipt=_persisted_cleanup(projection_cleanup="blocked"),
            ),
        )

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    snapshot = adapter.recover_lifecycle(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    assert snapshot.projection_cleanup_state == "blocked"
    assert adapter.recovered_cleanup_receipt is not None

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.finalize_cleanup(
            cleanup_initiation_receipt_sha256=adapter.recovered_cleanup_receipt.receipt_sha256
        )
    assert caught.value.code == "managed_benchmark_registry_lifecycle_invalid"
    assert calls == 1
    assert adapter.cleanup_required is True
    adapter._client.close()


def test_legacy_blocked_snapshot_preserves_pending_receipt_but_cannot_finalize() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json=_lifecycle(
                state="cleanup_pending",
                projection_cleanup_state="blocked",
                cleanup_receipt=_persisted_cleanup(projection_cleanup="pending"),
            ),
        )

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    snapshot = adapter.recover_lifecycle(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    assert snapshot.projection_cleanup_state == "blocked"
    assert snapshot.cleanup_receipt is not None
    assert snapshot.cleanup_receipt.projection_cleanup == "pending"
    assert adapter.lifecycle_state == "cleanup_pending"
    assert adapter.recovered_cleanup_receipt is snapshot.cleanup_receipt

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as finalize_error:
        adapter.finalize_cleanup(
            cleanup_initiation_receipt_sha256=snapshot.cleanup_receipt.receipt_sha256
        )
    assert finalize_error.value.code == "managed_benchmark_registry_lifecycle_invalid"
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as close_error:
        adapter.close()
    assert close_error.value.code == "managed_benchmark_registry_cleanup_required"
    assert calls == 1
    assert adapter.cleanup_required is True
    assert adapter._client.is_closed is False
    adapter._client.close()


@pytest.mark.parametrize("tamper", ("manifest", "completion", "inverse_mismatch"))
def test_legacy_blocked_snapshot_rejects_all_other_mismatches(tamper: str) -> None:
    manifest = "d" * 64

    def handler(request: httpx.Request) -> httpx.Response:
        response = _lifecycle(
            state="cleanup_pending",
            projection_cleanup_state="blocked",
            cleanup_receipt=_persisted_cleanup(projection_cleanup="pending"),
        )
        data = response["data"]
        if tamper == "manifest":
            data["projection_manifest_sha256"] = manifest
        elif tamper == "completion":
            data["completion_receipt"] = _persisted_completion(manifest)
        else:
            data["projection_cleanup_state"] = "pending"
            data["projection_manifest_sha256"] = manifest
            data["cleanup_receipt"] = _persisted_cleanup(projection_cleanup="blocked")
        return httpx.Response(200, json=response)

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.recover_lifecycle(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
        )
    assert caught.value.code == "managed_benchmark_registry_lifecycle_response_invalid"
    assert adapter.lifecycle_state == "unknown"
    assert adapter.cleanup_required is True
    adapter._client.close()


@pytest.mark.parametrize("mismatch", ("binding", "receipt"))
def test_lifecycle_snapshot_binding_and_receipt_mismatch_fail_closed(
    mismatch: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        cleanup = _persisted_cleanup(receipt_sha256="f" * 64 if mismatch == "receipt" else None)
        return httpx.Response(
            200,
            json=_lifecycle(
                state="cleanup_pending",
                projection_cleanup_state="pending",
                projection_manifest_sha256="d" * 64,
                cleanup_receipt=cleanup,
                binding="c" * 64 if mismatch == "binding" else BINDING,
            ),
        )

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.recover_lifecycle(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
        )
    assert caught.value.code == "managed_benchmark_registry_lifecycle_response_invalid"
    assert adapter.lifecycle_state == "unknown"
    assert adapter.cleanup_required is True
    adapter._client.close()


@pytest.mark.parametrize("mismatch", ("space", "state_regression"))
def test_registration_replay_rejects_snapshot_identity_or_state_regression(
    mismatch: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json=_registration(
                    created=False,
                    state="cleanup_pending" if mismatch == "state_regression" else "active",
                ),
            )
        snapshot = _lifecycle()
        if mismatch == "space":
            snapshot["data"]["space_id"] = "different-benchmark-space"
        return httpx.Response(200, json=snapshot)

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.register(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
        )
    assert caught.value.code == "managed_benchmark_registry_lifecycle_response_invalid"
    assert adapter.lifecycle_state == "unknown"
    assert adapter.cleanup_required is True
    adapter._client.close()


def test_unknown_get_recovery_retries_only_exact_binding() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("GET response lost")
        return httpx.Response(200, json=_lifecycle())

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as lost:
        adapter.recover_lifecycle(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
        )
    assert lost.value.code == "managed_benchmark_registry_request_failed"

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as mismatch:
        adapter.recover_lifecycle(
            run_id_sha256=RUN,
            binding_commitment_sha256="c" * 64,
            space_slug=SPACE_SLUG,
        )
    assert mismatch.value.code == "managed_benchmark_registry_lifecycle_invalid"
    assert calls == 1

    snapshot = adapter.recover_lifecycle(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    assert snapshot.state == "active"
    assert adapter.lifecycle_state == "active"
    assert calls == 2
    adapter._client.close()
