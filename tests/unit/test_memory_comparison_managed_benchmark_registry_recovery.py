from __future__ import annotations

import json
import traceback
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from benchmark_cleanup_plan_fixtures import cleanup_plan_pair
from infinity_context_core.ports.benchmark_cleanup_plan import (
    ManagedBenchmarkCleanupPlan,
    validate_managed_benchmark_cleanup_plan,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
    ManagedBenchmarkRegistryHttpConfig,
    ManagedBenchmarkRegistryHttpError,
)
from memory_comparison_managed_benchmark_registry_test_support import (
    BASE_URL,
    BINDING,
    RUN,
    SPACE_SLUG,
    TOKEN,
    _cleanup,
    _close_with_cleanup_required,
    _config,
    _DeadlineAdvancingStream,
    _digest,
    _finalize,
    _lifecycle,
    _manifest,
    _MutableClock,
    _plan,
    _registration,
    _seal,
    _target,
    _TruncatedCommittedStream,
)


def _plan_for_base_url(base_url: str) -> ManagedBenchmarkCleanupPlan:
    target = _target(base_url)
    value, digest = cleanup_plan_pair(
        run_id=RUN,
        binding=BINDING,
        target=target,
        space_slug=SPACE_SLUG,
    )
    return validate_managed_benchmark_cleanup_plan(
        value,
        digest,
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=target,
        space_slug=SPACE_SLUG,
    )


def test_mismatched_registration_response_is_terminal_and_secret_free() -> None:
    adapter = ManagedBenchmarkRegistryHttpAdapter(
        _config(
            httpx.MockTransport(
                lambda request: httpx.Response(201, json=_registration(binding="c" * 64))
            )
        )
    )

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.register(
            cleanup_plan=_plan(),
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
        )

    assert caught.value.code == "managed_benchmark_registry_registration_response_invalid"
    assert TOKEN not in str(caught.value)
    assert adapter._client.is_closed is False
    _close_with_cleanup_required(adapter)


def test_expired_deadline_prevents_transport_call_and_closes_on_failure() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(201, json=_registration())

    adapter = ManagedBenchmarkRegistryHttpAdapter(
        _config(httpx.MockTransport(handler), expired=True)
    )
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.register(
            cleanup_plan=_plan(),
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
        )

    assert caught.value.code == "managed_benchmark_registry_deadline_expired"
    assert calls == 0
    assert adapter._client.is_closed is True


def test_transport_failure_is_sanitized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"transport leaked {TOKEN}")

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.register(
            cleanup_plan=_plan(),
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
        )

    assert caught.value.code == "managed_benchmark_registry_request_failed"
    assert TOKEN not in str(caught.value)
    formatted = "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert TOKEN not in formatted
    assert "transport leaked" not in formatted
    assert adapter._client.is_closed is False
    _close_with_cleanup_required(adapter)


def test_unknown_registration_replays_only_exact_attempt_then_allows_cleanup() -> None:
    methods: list[str] = []
    registration_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal registration_calls
        methods.append(request.method)
        if request.method == "POST":
            registration_calls += 1
            if registration_calls == 1:
                raise RuntimeError(f"committed registration leaked {TOKEN}")
            return httpx.Response(200, json=_registration(created=False))
        if request.method == "GET":
            return httpx.Response(200, json=_lifecycle())
        return httpx.Response(200, json=_cleanup(projection_cleanup="blocked"))

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.register(
            cleanup_plan=_plan(),
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
            idempotency_key="exact-registration-key",
        )
    assert caught.value.code == "managed_benchmark_registry_request_failed"
    assert adapter.cleanup_required is True

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as mismatch:
        adapter.register(
            cleanup_plan=_plan(),
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
            idempotency_key="different-registration-key",
        )
    assert mismatch.value.code == "managed_benchmark_registry_lifecycle_invalid"
    assert registration_calls == 1

    recovered = adapter.register(
        cleanup_plan=_plan(),
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
        idempotency_key="exact-registration-key",
    )
    assert recovered.created is False
    assert adapter.begin_cleanup().projection_cleanup == "blocked"
    assert methods == ["POST", "POST", "GET", "DELETE"]


def test_unknown_registration_recovery_uses_fresh_recovery_window() -> None:
    now = datetime(2026, 8, 2, tzinfo=UTC)
    clock = _MutableClock(now)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            clock.value = now + timedelta(minutes=2)
            raise RuntimeError("registration response lost")
        if request.method == "POST":
            return httpx.Response(200, json=_registration(created=False))
        if request.method == "GET":
            return httpx.Response(200, json=_lifecycle())
        return httpx.Response(200, json=_cleanup(projection_cleanup="blocked"))

    config = ManagedBenchmarkRegistryHttpConfig(
        base_url=BASE_URL,
        admin_bearer_token=TOKEN,
        target_identity_sha256=_target(),
        timeout_seconds=30,
        benchmark_deadline=now + timedelta(minutes=1),
        cleanup_recovery_timeout_seconds=300,
        transport=httpx.MockTransport(handler),
        clock=clock,
    )
    adapter = ManagedBenchmarkRegistryHttpAdapter(config)
    with pytest.raises(ManagedBenchmarkRegistryHttpError):
        adapter.register(
            cleanup_plan=_plan(),
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
        )

    adapter.register(
        cleanup_plan=_plan(),
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    adapter.begin_cleanup()
    assert calls == 4


def test_unknown_cleanup_replays_after_truncated_response_and_missed_window() -> None:
    delete_calls = 0
    clock = _MutableClock(datetime.now(UTC))

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal delete_calls
        if request.method == "POST":
            return httpx.Response(201, json=_registration())
        delete_calls += 1
        if delete_calls == 1:
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_TruncatedCommittedStream(),
            )
        return httpx.Response(200, json=_cleanup(replayed=True))

    adapter = ManagedBenchmarkRegistryHttpAdapter(
        _config(httpx.MockTransport(handler), clock=clock)
    )
    adapter.register(
        cleanup_plan=_plan(),
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.begin_cleanup(idempotency_key="exact-cleanup-key")
    assert caught.value.code == "managed_benchmark_registry_request_failed"
    assert adapter.cleanup_required is True

    with pytest.raises(ManagedBenchmarkRegistryHttpError, match="cleanup_required"):
        adapter.close()
    primary = RuntimeError("primary failure")
    with pytest.raises(RuntimeError) as preserved, adapter:
        raise primary
    assert preserved.value is primary
    assert primary.__notes__ == ["managed_benchmark_registry_cleanup_required"]
    assert adapter._client.is_closed is False
    clock.value += timedelta(days=1)

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as mismatch:
        adapter.begin_cleanup(idempotency_key="different-cleanup-key")
    assert mismatch.value.code == "managed_benchmark_registry_lifecycle_invalid"
    assert delete_calls == 1

    receipt = adapter.begin_cleanup(idempotency_key="exact-cleanup-key")
    assert receipt.replayed is True
    assert delete_calls == 2
    assert adapter._client.is_closed is False
    assert adapter.cleanup_required is True


def test_unknown_finalize_replays_only_exact_attempt_then_closes() -> None:
    manifest = _manifest()
    manifest_sha256 = _digest(manifest)
    finalize_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal finalize_calls
        if request.url.path.endswith("/cleanup/finalize"):
            finalize_calls += 1
            if finalize_calls == 1:
                return httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    stream=_TruncatedCommittedStream(),
                )
            return httpx.Response(200, json=_finalize(manifest_sha256, replayed=True))
        if request.method == "POST":
            return httpx.Response(201, json=_registration())
        if request.method == "PUT":
            return httpx.Response(200, json=_seal(manifest_sha256))
        return httpx.Response(200, json=_cleanup())

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    adapter.register(
        cleanup_plan=_plan(),
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    adapter.seal_projection_manifest(
        projection_manifest=manifest,
        projection_manifest_sha256=manifest_sha256,
    )
    initiation = adapter.begin_cleanup()

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.finalize_cleanup(
            cleanup_initiation_receipt_sha256=initiation.receipt_sha256,
            idempotency_key="exact-finalize-key",
        )
    assert caught.value.code == "managed_benchmark_registry_request_failed"
    assert adapter.cleanup_required is True
    assert adapter._client.is_closed is False

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as mismatch:
        adapter.finalize_cleanup(
            cleanup_initiation_receipt_sha256=initiation.receipt_sha256,
            idempotency_key="different-finalize-key",
        )
    assert mismatch.value.code == "managed_benchmark_registry_lifecycle_invalid"
    assert finalize_calls == 1

    completion = adapter.finalize_cleanup(
        cleanup_initiation_receipt_sha256=initiation.receipt_sha256,
        idempotency_key="exact-finalize-key",
    )
    assert completion.replayed is True
    assert finalize_calls == 2
    assert adapter.cleanup_required is False
    assert adapter._client.is_closed is True


def test_finalize_rejects_false_completion_digest_then_recovers_same_key() -> None:
    manifest = _manifest()
    manifest_sha256 = _digest(manifest)
    finalize_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal finalize_calls
        if request.url.path.endswith("/cleanup/finalize"):
            finalize_calls += 1
            response = _finalize(
                manifest_sha256,
                receipt_sha256="f" * 64 if finalize_calls == 1 else None,
                replayed=finalize_calls > 1,
            )
            return httpx.Response(200, json=response)
        if request.method == "POST":
            return httpx.Response(201, json=_registration())
        if request.method == "PUT":
            return httpx.Response(200, json=_seal(manifest_sha256))
        return httpx.Response(200, json=_cleanup())

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    adapter.register(
        cleanup_plan=_plan(),
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    adapter.seal_projection_manifest(
        projection_manifest=manifest,
        projection_manifest_sha256=manifest_sha256,
    )
    initiation = adapter.begin_cleanup()

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.finalize_cleanup(
            cleanup_initiation_receipt_sha256=initiation.receipt_sha256,
            idempotency_key="terminal-receipt-key",
        )
    assert caught.value.code == "managed_benchmark_registry_finalize_response_invalid"
    assert adapter.cleanup_required is True

    recovered = adapter.finalize_cleanup(
        cleanup_initiation_receipt_sha256=initiation.receipt_sha256,
        idempotency_key="terminal-receipt-key",
    )
    assert recovered.replayed is True
    assert adapter._client.is_closed is True


def test_unsealed_cleanup_cannot_claim_terminal_completion() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.method == "POST":
            return httpx.Response(201, json=_registration())
        return httpx.Response(200, json=_cleanup(projection_cleanup="blocked"))

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    adapter.register(
        cleanup_plan=_plan(),
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    initiation = adapter.begin_cleanup()

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.finalize_cleanup(cleanup_initiation_receipt_sha256=initiation.receipt_sha256)
    assert caught.value.code == "managed_benchmark_registry_lifecycle_invalid"
    assert calls == 2
    assert adapter.cleanup_required is True
    assert adapter._client.is_closed is False


def test_cleanup_uses_fresh_window_after_benchmark_deadline_expires() -> None:
    now = datetime(2026, 8, 2, tzinfo=UTC)
    clock = _MutableClock(now)
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(201, json=_registration())
        return httpx.Response(200, json=_cleanup(projection_cleanup="blocked"))

    config = ManagedBenchmarkRegistryHttpConfig(
        base_url=BASE_URL,
        admin_bearer_token=TOKEN,
        target_identity_sha256=_target(),
        timeout_seconds=30,
        benchmark_deadline=now + timedelta(minutes=1),
        cleanup_recovery_timeout_seconds=300,
        transport=httpx.MockTransport(handler),
        clock=clock,
    )
    adapter = ManagedBenchmarkRegistryHttpAdapter(config)
    adapter.register(
        cleanup_plan=_plan(),
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    clock.value = now + timedelta(minutes=2)

    assert adapter.begin_cleanup().projection_cleanup == "blocked"
    assert methods == ["POST", "DELETE"]


def test_cleanup_can_start_immediately_after_unsealed_registration() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(201, json=_registration())
        return httpx.Response(200, json=_cleanup(projection_cleanup="blocked"))

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    adapter.register(
        cleanup_plan=_plan(),
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )

    receipt = adapter.begin_cleanup()

    assert receipt.projection_cleanup == "blocked"
    assert methods == ["POST", "DELETE"]
    assert adapter._client.is_closed is False
    assert adapter.cleanup_required is True


def test_rejected_seal_keeps_client_usable_for_best_effort_cleanup() -> None:
    methods: list[str] = []
    manifest = _manifest()
    manifest_sha256 = _digest(manifest)

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(201, json=_registration())
        if request.method == "PUT":
            return httpx.Response(503, json={"data": {}})
        return httpx.Response(200, json=_cleanup(projection_cleanup="blocked"))

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    adapter.register(
        cleanup_plan=_plan(),
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.seal_projection_manifest(
            projection_manifest=manifest,
            projection_manifest_sha256=manifest_sha256,
        )

    assert caught.value.code == "managed_benchmark_registry_response_retryable"
    assert adapter._client.is_closed is False
    receipt = adapter.begin_cleanup()
    assert receipt.projection_cleanup == "blocked"
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as finalize_error:
        adapter.finalize_cleanup(cleanup_initiation_receipt_sha256=receipt.receipt_sha256)
    assert finalize_error.value.code == "managed_benchmark_registry_lifecycle_invalid"
    assert methods == ["POST", "PUT", "DELETE"]
    assert adapter.cleanup_required is True
    assert adapter._client.is_closed is False


def test_lost_seal_response_pending_cleanup_can_finalize_exact_attempt() -> None:
    methods: list[str] = []
    manifest = _manifest()
    manifest_sha256 = _digest(manifest)
    cleanup_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal cleanup_calls
        methods.append(request.method)
        if request.url.path.endswith("/cleanup/finalize"):
            return httpx.Response(200, json=_finalize(manifest_sha256))
        if request.method == "POST":
            return httpx.Response(201, json=_registration())
        if request.method == "PUT":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_TruncatedCommittedStream(),
            )
        cleanup_calls += 1
        if cleanup_calls == 1:
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_TruncatedCommittedStream(),
            )
        return httpx.Response(
            200,
            json=_cleanup(projection_cleanup="pending", replayed=True),
        )

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    adapter.register(
        cleanup_plan=_plan(),
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as seal_error:
        adapter.seal_projection_manifest(
            projection_manifest=manifest,
            projection_manifest_sha256=manifest_sha256,
        )
    assert seal_error.value.code == "managed_benchmark_registry_request_failed"

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as cleanup_error:
        adapter.begin_cleanup(idempotency_key="lost-seal-cleanup-key")
    assert cleanup_error.value.code == "managed_benchmark_registry_request_failed"
    initiation = adapter.begin_cleanup(idempotency_key="lost-seal-cleanup-key")
    assert initiation.projection_cleanup == "pending"
    assert initiation.replayed is True
    assert adapter.cleanup_required is True
    assert adapter._client.is_closed is False

    completion = adapter.finalize_cleanup(
        cleanup_initiation_receipt_sha256=initiation.receipt_sha256
    )
    assert completion.projection_manifest_sha256 == manifest_sha256
    assert completion.projection_cleanup == "complete"
    assert methods == ["POST", "PUT", "DELETE", "DELETE", "POST"]
    assert adapter.cleanup_required is False
    assert adapter._client.is_closed is True


def test_unknown_seal_outcome_keeps_client_usable_for_cleanup() -> None:
    methods: list[str] = []
    manifest = _manifest()

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(201, json=_registration())
        if request.method == "PUT":
            raise RuntimeError(f"unknown seal leaked {TOKEN}")
        return httpx.Response(200, json=_cleanup())

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    adapter.register(
        cleanup_plan=_plan(),
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.seal_projection_manifest(
            projection_manifest=manifest,
            projection_manifest_sha256=_digest(manifest),
        )

    assert caught.value.code == "managed_benchmark_registry_request_failed"
    assert adapter._client.is_closed is False
    formatted = "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert TOKEN not in formatted
    assert "unknown seal leaked" not in formatted
    adapter.begin_cleanup()
    assert methods == ["POST", "PUT", "DELETE"]


@pytest.mark.parametrize("base_url", (f"{BASE_URL}/api", f"{BASE_URL}/api/"))
def test_admitted_api_base_path_is_preserved_in_registry_url(base_url: str) -> None:
    seen_paths: list[str] = []
    cleanup_plan = _plan_for_base_url(base_url)

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        registration = _registration(target=_target(base_url))
        registration["data"]["cleanup_plan_sha256"] = cleanup_plan.sha256
        return httpx.Response(
            201,
            json=registration,
        )

    adapter = ManagedBenchmarkRegistryHttpAdapter(
        _config(httpx.MockTransport(handler), base_url=base_url)
    )
    adapter.register(
        cleanup_plan=cleanup_plan,
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )

    assert seen_paths == ["/api/v1/internal/memory-comparison/runs"]
    _close_with_cleanup_required(adapter)


def test_absolute_deadline_is_rechecked_while_response_streams() -> None:
    now = datetime(2026, 8, 2, tzinfo=UTC)
    clock = _MutableClock(now)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            201,
            headers={"content-type": "application/json"},
            stream=_DeadlineAdvancingStream(json.dumps(_registration()).encode(), clock),
        )
    )
    config = ManagedBenchmarkRegistryHttpConfig(
        base_url=BASE_URL,
        admin_bearer_token=TOKEN,
        target_identity_sha256=_target(),
        timeout_seconds=30,
        benchmark_deadline=now + timedelta(minutes=5),
        cleanup_recovery_timeout_seconds=600,
        transport=transport,
        clock=clock,
    )
    adapter = ManagedBenchmarkRegistryHttpAdapter(config)

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.register(
            cleanup_plan=_plan(),
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
        )

    assert caught.value.code == "managed_benchmark_registry_deadline_expired"
    assert adapter._client.is_closed is False
    _close_with_cleanup_required(adapter)


def test_adapter_owns_close_once_and_surfaces_secret_free_typed_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_calls = 0
    transport = httpx.MockTransport(lambda request: httpx.Response(201, json=_registration()))

    def fail_close() -> None:
        nonlocal close_calls
        close_calls += 1
        raise RuntimeError(f"close leaked {TOKEN}")

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(transport))
    monkeypatch.setattr(transport, "close", fail_close)

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.close()

    assert caught.value.code == "managed_benchmark_registry_close_failed"
    formatted = "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert TOKEN not in formatted
    assert "close leaked" not in formatted
    adapter.close()
    assert close_calls == 1


def test_successful_completion_receipt_is_returned_when_client_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    manifest_sha256 = _digest(manifest)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/cleanup/finalize"):
            return httpx.Response(200, json=_finalize(manifest_sha256))
        if request.method == "POST":
            return httpx.Response(201, json=_registration())
        if request.method == "PUT":
            return httpx.Response(200, json=_seal(manifest_sha256))
        return httpx.Response(200, json=_cleanup())

    transport = httpx.MockTransport(handler)
    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(transport))
    adapter.register(
        cleanup_plan=_plan(),
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    adapter.seal_projection_manifest(
        projection_manifest=manifest,
        projection_manifest_sha256=manifest_sha256,
    )
    initiation = adapter.begin_cleanup()

    def fail_close() -> None:
        raise RuntimeError(f"close leaked {TOKEN}")

    monkeypatch.setattr(transport, "close", fail_close)
    receipt = adapter.finalize_cleanup(cleanup_initiation_receipt_sha256=initiation.receipt_sha256)

    assert receipt.projection_cleanup == "complete"
    assert adapter.cleanup_required is False
    assert adapter.close_warning_code == "managed_benchmark_registry_close_failed"


def test_context_exit_rejects_silent_cleanup_abandonment_without_network_cleanup() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(201, json=_registration())

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught, adapter:
        adapter.register(
            cleanup_plan=_plan(),
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
        )

    assert caught.value.code == "managed_benchmark_registry_cleanup_required"
    assert adapter.cleanup_required is True
    assert adapter._client.is_closed is False
    assert methods == ["POST"]


@pytest.mark.parametrize(
    ("raised", "expected_type", "expected_code"),
    (
        (KeyboardInterrupt(f"interrupt leaked {TOKEN}"), KeyboardInterrupt, None),
        (SystemExit(f"exit leaked {TOKEN}"), SystemExit, 1),
    ),
)
def test_control_flow_base_exceptions_preserve_type_without_secret_traceback(
    raised: BaseException,
    expected_type: type[BaseException],
    expected_code: int | None,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise raised

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    with pytest.raises(expected_type) as caught:
        adapter.register(
            cleanup_plan=_plan(),
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
        )

    formatted = "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert TOKEN not in formatted
    if isinstance(caught.value, SystemExit):
        assert caught.value.code == expected_code
    _close_with_cleanup_required(adapter)


def test_cleanup_receipt_digest_and_outbox_counts_are_verified() -> None:
    manifest = _manifest()
    manifest_sha256 = _digest(manifest)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json=_registration())
        if request.method == "PUT":
            return httpx.Response(200, json=_seal(manifest_sha256))
        return httpx.Response(200, json=_cleanup(receipt_sha256="f" * 64))

    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(handler)))
    adapter.register(
        cleanup_plan=_plan(),
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
    )
    adapter.seal_projection_manifest(
        projection_manifest=manifest,
        projection_manifest_sha256=manifest_sha256,
    )

    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.begin_cleanup()

    assert caught.value.code == "managed_benchmark_registry_cleanup_response_invalid"
    assert adapter._client.is_closed is False
    _close_with_cleanup_required(adapter)
