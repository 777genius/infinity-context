from __future__ import annotations

import json
import pickle
import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from infinity_context_server import (
    memory_comparison_managed_http_lifecycle_evidence as evidence_module,
)
from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    PROFILE_LONGMEMEVAL_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_locomo_transport import (
    LocomoTimestampTransportEvidence,
    RunScopedLocomoTransportEvidenceKey,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _managed_corpus_identity,
    _managed_corpus_record,
    _reconstruct_managed_corpus_case,
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedComparisonHttpExecutionAdapter,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    ManagedComparisonHttpLifecycleAdapter,
    ManagedHttpIngestReceipt,
    ManagedHttpLifecycleError,
    consume_managed_http_execution_evidence,
    consume_managed_http_ingest_receipts,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    MANAGED_PREFLIGHT_PROVIDER_SUBSCRIPTION_RUNTIME,
    ManagedDatasetMetadata,
    ManagedPreflightRequest,
    ManagedPreflightTimeouts,
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_runtime_credentials import (
    issue_managed_runtime_credential_authority,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkMemoryInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)

_RUN = "managed-lifecycle-run"
_BINDING = "b" * 64
_INFINITY_URL = "https://infinity.private.test"
_MEM0_URL = "https://mem0.private.test"
_INFINITY_TARGET = managed_backend_target_identity_sha256(
    backend_role="infinity-context",
    base_url=_INFINITY_URL,
)
_MEM0_TARGET = managed_backend_target_identity_sha256(
    backend_role="mem0",
    base_url=_MEM0_URL,
)
_INFINITY_TOKEN = "infinity-private-token"
_MEM0_TOKEN = "mem0-private-token"
_PRIVATE_GOLD = "PRIVATE-GOLD-MUST-NOT-CROSS-HTTP"
_PRIVATE_QUESTION = "PRIVATE-QUESTION-MUST-NOT-CROSS-INGEST"


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 1, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def _targets() -> tuple[FullComparisonBackendTarget, ...]:
    return (
        FullComparisonBackendTarget("infinity-context", _INFINITY_TARGET),
        FullComparisonBackendTarget("mem0", _MEM0_TARGET),
    )


def _longmem_case(*, case_id: str = "longmemeval-case-" + "3" * 64) -> ManagedRunCase:
    source = PublicBenchmarkCase(
        benchmark="longmemeval",
        case_id="private-source-case",
        question=_PRIVATE_QUESTION,
        expected_terms=(_PRIVATE_GOLD,),
        forbidden_terms=("private-forbidden",),
        memory_scope_external_ref="private-corpus",
        thread_external_ref="private-thread",
        metadata={"_evaluator_ground_truth": {"answer": _PRIVATE_GOLD}},
        conversations=(
            BenchmarkConversationInput(
                messages=(
                    BenchmarkMessageInput(role="user", content="I moved to Kyiv."),
                    BenchmarkMessageInput(role="assistant", content="Noted."),
                ),
                source_external_id="private-conversation",
                session_external_id="private-session",
            ),
        ),
    )
    corpus_id, _ = _managed_corpus_identity(source)
    return ManagedRunCase(case_id, corpus_id, _managed_corpus_record(source))


def _locomo_case() -> ManagedRunCase:
    source = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="private-locomo-source",
        question=_PRIVATE_QUESTION,
        expected_terms=(_PRIVATE_GOLD,),
        forbidden_terms=("private-forbidden",),
        memory_scope_external_ref="private-locomo-corpus",
        thread_external_ref="private-locomo-thread",
        metadata={
            "locomo_ingest_mode": "official-turns",
            "_evaluator_ground_truth": {"answer": _PRIVATE_GOLD},
        },
        memories=(
            BenchmarkMemoryInput(
                text="Alice arrived in Kyiv.",
                kind="dialogue_turn",
                source_external_id="private-source-turn",
                metadata={
                    "role": "user",
                    "timestamp": 1_735_689_600,
                    "session_key": "session_1",
                    "session_date": "12:00 am on 1 January, 2025",
                    "dia_id": "D1:1",
                    "speaker": "Alice",
                },
            ),
        ),
    )
    corpus_id, _ = _managed_corpus_identity(source)
    return ManagedRunCase("locomo-case-" + "4" * 64, corpus_id, _managed_corpus_record(source))


def _thaw(value: object) -> object:
    if isinstance(value, dict) or type(value).__name__ == "mappingproxy":
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _profile(name: str):
    profile = resolve_full_comparison_profile(name)
    assert profile is not None
    return profile


def _build(
    *,
    case: ManagedRunCase,
    infinity_handler,
    mem0_handler,
    clock: _Clock,
    send_timestamps: bool = False,
    deadline_delta: timedelta = timedelta(seconds=10),
    lifecycle_credential_action: str | None = None,
) -> tuple[ManagedComparisonHttpLifecycleAdapter, ManagedComparisonHttpExecutionAdapter]:
    profile = _profile(
        PROFILE_LOCOMO_TOP_50
        if case.record["benchmark"] == "locomo"
        else PROFILE_LONGMEMEVAL_TOP_50
    )
    deadline = clock.value + deadline_delta
    authority = issue_managed_runtime_credential_authority(
        run_id=_RUN,
        infinity_origin=_INFINITY_URL,
        infinity_auth_token=_INFINITY_TOKEN,
        mem0_origin=_MEM0_URL,
        mem0_api_key=_MEM0_TOKEN,
        mem0_probe_token="mem0-private-probe-token",
        subscription_origin="http://127.0.0.1:8890",
        subscription_bearer_token="subscription-private-token",
        request_timeout_seconds=20,
        issued_at=clock.value,
        deadline=deadline,
    )
    preflight_material = authority.preflight_material()
    preflight_request = ManagedPreflightRequest(
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset=ManagedDatasetMetadata(
            profile.profile_id,
            profile.benchmark,
            profile.expected_dataset_hash,
            profile.expected_case_count,
            dict(profile.expected_distribution),
            profile.expected_corpus_count,
        ),
        provider_route=preflight_material.provider_route,
        answerer_model="gpt-5.6-sol",
        judge_model="gpt-5.6-sol",
        openai_credential=preflight_material.provider_credential,
        backend_endpoints=preflight_material.backend_endpoints,
        timeouts=ManagedPreflightTimeouts(1, 20, 120),
        scope="canary",
        provider_kind=MANAGED_PREFLIGHT_PROVIDER_SUBSCRIPTION_RUNTIME,
    )
    authority.bind_preflight_request(
        preflight_request,
        run_id=_RUN,
        deadline=deadline,
    )
    credential_material = authority.issue_backend_credential_material(
        expected_request=preflight_request,
        run_id=_RUN,
        infinity_origin=_INFINITY_URL,
        mem0_origin=_MEM0_URL,
        deadline=deadline,
        now=clock.value,
        infinity_transport=httpx.MockTransport(infinity_handler),
        mem0_transport=httpx.MockTransport(mem0_handler),
        mem0_send_timestamps=send_timestamps,
    )
    execution = ManagedComparisonHttpExecutionAdapter(
        preflight_request=preflight_request,
        run_id=_RUN,
        deadline=deadline,
        credential_material=credential_material,
        retrieval_policy=NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
        clock=clock,
    )
    if lifecycle_credential_action == "replay":
        credential_material.consume_for_http_lifecycle(
            expected_request=preflight_request,
            run_id=_RUN,
            deadline=deadline,
        )
    elif lifecycle_credential_action == "wrong-run":
        with pytest.raises(ValueError, match="continuity failed"):
            credential_material.consume_for_http_lifecycle(
                expected_request=preflight_request,
                run_id="wrong-managed-run",
                deadline=deadline,
            )
    elif lifecycle_credential_action == "tamper":
        object.__setattr__(preflight_request, "answerer_model", "gpt-5.6-sol-tampered")
        object.__setattr__(preflight_request, "judge_model", "gpt-5.6-sol-tampered")
    lifecycle = ManagedComparisonHttpLifecycleAdapter(
        run_id=_RUN,
        binding_commitment_sha256=_BINDING,
        admitted_targets=_targets(),
        cases=(case,),
        deadline=deadline,
        execution=execution,
        preflight_request=preflight_request,
        credential_material=credential_material,
        infinity_reset_transport=httpx.MockTransport(infinity_handler),
        mem0_reset_transport=httpx.MockTransport(mem0_handler),
        clock=clock,
    )
    return lifecycle, execution


@pytest.mark.parametrize(
    "action",
    ("replay", "wrong-run", "tamper"),
)
def test_lifecycle_credential_lane_fails_before_backend_io(action: str) -> None:
    calls = 0

    def unexpected(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    with pytest.raises(
        ManagedHttpLifecycleError,
        match="managed_http_lifecycle_credential_continuity_failed",
    ):
        _build(
            case=_longmem_case(),
            infinity_handler=unexpected,
            mem0_handler=unexpected,
            clock=_Clock(),
            lifecycle_credential_action=action,
        )
    assert calls == 0


def _reset(adapter: ManagedComparisonHttpLifecycleAdapter) -> None:
    adapter.reset(
        run_id=_RUN,
        binding_commitment_sha256=_BINDING,
        backend_targets=tuple(
            (item.backend_role, item.target_identity_sha256) for item in _targets()
        ),
    )


def _ingest(
    adapter: ManagedComparisonHttpLifecycleAdapter,
    case: ManagedRunCase,
    role: str,
) -> ManagedHttpIngestReceipt:
    target = _INFINITY_TARGET if role == "infinity-context" else _MEM0_TARGET
    return adapter.ingest(
        run_id=_RUN,
        backend_role=role,
        target_identity_sha256=target,
        record=_thaw(case.record),
    )


def test_exact_reset_ingest_order_clean_proofs_and_opaque_receipt_consumption() -> None:
    case = _longmem_case()
    clock = _Clock()
    events: list[str] = []
    wire: list[str] = []

    def infinity_handler(request: httpx.Request) -> httpx.Response:
        wire.append(request.content.decode())
        assert request.headers["Authorization"] == f"Bearer {_INFINITY_TOKEN}"
        if request.url.path == "/v1/spaces":
            events.append("infinity.reset")
            payload = json.loads(request.content)
            assert payload == {
                "slug": "memory-comparison-managed-lifecycle-run",
                "name": "memory-comparison-managed-lifecycle-run",
            }
            return httpx.Response(201, json={"data": {"slug": payload["slug"]}})
        events.append("infinity.ingest")
        return httpx.Response(201, json={"data": {"id": "document-1"}})

    def mem0_handler(request: httpx.Request) -> httpx.Response:
        wire.append(request.content.decode())
        assert request.headers["X-API-Key"] == _MEM0_TOKEN
        if request.method == "DELETE":
            events.append("mem0.delete-readback")
            assert request.url.params["run_id"] == _RUN
            assert request.url.params["user_id"].startswith("memo-stack-comparison-")
            return httpx.Response(200, json={"deleted": True, "verified_absent": True})
        events.append("mem0.ingest")
        return httpx.Response(200, json={"results": [{"id": "memory-1"}]})

    adapter, execution = _build(
        case=case,
        infinity_handler=infinity_handler,
        mem0_handler=mem0_handler,
        clock=clock,
    )
    try:
        _reset(adapter)
        receipts = (_ingest(adapter, case, "infinity-context"), _ingest(adapter, case, "mem0"))
        execution_view = consume_managed_http_execution_evidence(
            adapter.execution_evidence_capability(),
            run_id=_RUN,
            binding_commitment_sha256=_BINDING,
            backend_targets=_targets(),
            cases=(case,),
        )
        views = consume_managed_http_ingest_receipts(
            receipts,
            run_id=_RUN,
            binding_commitment_sha256=_BINDING,
            backend_targets=_targets(),
            cases=(case,),
        )
    finally:
        execution.close()

    assert events == [
        "infinity.reset",
        "mem0.delete-readback",
        "infinity.ingest",
        "mem0.ingest",
    ]
    assert execution_view.validation.eligible is True
    assert tuple(scope.backend_role for scope in execution_view.scopes) == (
        "infinity-context",
        "mem0",
    )
    assert execution_view.provenance["infinity_namespace_http_observation_count"] == 1
    assert execution_view.provenance["infinity_derived_corpus_proof_count"] == 0
    assert len(execution_view.attestation_key) == 32
    assert tuple(view.backend_role for view in views) == ("infinity-context", "mem0")
    assert all(view.clean_state_validation.eligible for view in views)
    serialized_wire = "".join(wire)
    assert _PRIVATE_GOLD not in serialized_wire
    assert _PRIVATE_QUESTION not in serialized_wire
    assert "private-forbidden" not in serialized_wire
    assert repr(receipts[0]) == "ManagedHttpIngestReceipt(<opaque>)"
    with pytest.raises(TypeError, match="nonserializable"):
        pickle.dumps(receipts[0])
    with pytest.raises(ManagedHttpLifecycleError, match="binding_invalid"):
        consume_managed_http_ingest_receipts(
            receipts,
            run_id=_RUN,
            binding_commitment_sha256=_BINDING,
            backend_targets=_targets(),
            cases=(case,),
        )


def test_locomo_receipt_preserves_exact_transport_verifier_and_timestamp_evidence() -> None:
    case = _locomo_case()
    clock = _Clock()
    observed_mem0: list[dict[str, object]] = []

    def infinity_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/spaces":
            slug = json.loads(request.content)["slug"]
            return httpx.Response(201, json={"data": {"slug": slug}})
        return httpx.Response(201, json={"data": {"id": "fact-1"}})

    def mem0_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200, json={"deleted": True, "verified_absent": True})
        payload = json.loads(request.content)
        observed_mem0.append(payload)
        return httpx.Response(200, json={"results": [{"id": "memory-1"}]})

    adapter, execution = _build(
        case=case,
        infinity_handler=infinity_handler,
        mem0_handler=mem0_handler,
        clock=clock,
        send_timestamps=True,
    )
    try:
        _reset(adapter)
        receipts = (_ingest(adapter, case, "infinity-context"), _ingest(adapter, case, "mem0"))
        execution_view = consume_managed_http_execution_evidence(
            adapter.execution_evidence_capability(),
            run_id=_RUN,
            binding_commitment_sha256=_BINDING,
            backend_targets=_targets(),
            cases=(case,),
        )
        views = consume_managed_http_ingest_receipts(
            receipts,
            run_id=_RUN,
            binding_commitment_sha256=_BINDING,
            backend_targets=_targets(),
            cases=(case,),
        )
    finally:
        execution.close()

    mem0_view = views[1]
    assert execution_view.locomo_timestamp_verifier is mem0_view.locomo_timestamp_verifier
    assert execution_view.locomo_timestamp_evidence == mem0_view.locomo_timestamp_evidence
    assert type(mem0_view.locomo_timestamp_verifier) is RunScopedLocomoTransportEvidenceKey
    assert len(mem0_view.locomo_timestamp_evidence) == 1
    assert type(mem0_view.locomo_timestamp_evidence[0]) is LocomoTimestampTransportEvidence
    assert observed_mem0[0]["timestamp"] == 1_735_689_600
    rebuilt = _reconstruct_managed_corpus_case(
        case.record,
        case_id=case.case_id,
        question="managed-ingest-gold-blind-projection",
        temporal_context={},
    )
    assert observed_mem0[0]["metadata"]["case_id"] == rebuilt.case_id
    assert _PRIVATE_QUESTION not in json.dumps(observed_mem0)
    assert _PRIVATE_GOLD not in json.dumps(observed_mem0)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ({"run_id": "wrong-run"}, "reset_binding_mismatch"),
        ({"binding_commitment_sha256": "c" * 64}, "reset_binding_mismatch"),
        ({"backend_targets": (("mem0", _MEM0_TARGET),)}, "reset_binding_mismatch"),
    ],
)
def test_wrong_reset_binding_is_terminal_before_http(
    mutation: dict[str, object], code: str
) -> None:
    case = _longmem_case()
    clock = _Clock()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError(request)

    adapter, execution = _build(
        case=case, infinity_handler=handler, mem0_handler=handler, clock=clock
    )
    kwargs: dict[str, object] = {
        "run_id": _RUN,
        "binding_commitment_sha256": _BINDING,
        "backend_targets": tuple(
            (item.backend_role, item.target_identity_sha256) for item in _targets()
        ),
    }
    kwargs.update(mutation)
    try:
        with pytest.raises(ManagedHttpLifecycleError, match=code):
            adapter.reset(**kwargs)
        with pytest.raises(ManagedHttpLifecycleError, match="reset_replay"):
            _reset(adapter)
    finally:
        execution.close()
    assert calls == 0


def test_wrong_ingest_order_record_target_and_run_fail_closed() -> None:
    variants = (
        ("mem0", _MEM0_TARGET, _RUN, None),
        ("infinity-context", _MEM0_TARGET, _RUN, None),
        ("infinity-context", _INFINITY_TARGET, "wrong-run", None),
        ("infinity-context", _INFINITY_TARGET, _RUN, {"gold": _PRIVATE_GOLD}),
    )
    for role, target, run_id, extra in variants:
        case = _longmem_case()
        clock = _Clock()
        ingest_calls = 0

        def infinity_handler(request: httpx.Request) -> httpx.Response:
            nonlocal ingest_calls
            if request.url.path == "/v1/spaces":
                slug = json.loads(request.content)["slug"]
                return httpx.Response(201, json={"data": {"slug": slug}})
            ingest_calls += 1
            return httpx.Response(201, json={"data": {"id": "unexpected"}})

        def mem0_handler(request: httpx.Request) -> httpx.Response:
            nonlocal ingest_calls
            if request.method == "DELETE":
                return httpx.Response(200, json={"deleted": True, "verified_absent": True})
            ingest_calls += 1
            return httpx.Response(200, json={"results": []})

        adapter, execution = _build(
            case=case,
            infinity_handler=infinity_handler,
            mem0_handler=mem0_handler,
            clock=clock,
        )
        try:
            _reset(adapter)
            record = _thaw(case.record)
            assert isinstance(record, dict)
            if extra:
                record.update(extra)
            with pytest.raises(ManagedHttpLifecycleError, match="ingest_binding_mismatch"):
                adapter.ingest(
                    run_id=run_id,
                    backend_role=role,
                    target_identity_sha256=target,
                    record=record,
                )
            with pytest.raises(ManagedHttpLifecycleError, match="phase_invalid"):
                _ingest(adapter, case, "infinity-context")
        finally:
            execution.close()
        assert ingest_calls == 0


def test_deadline_and_provider_failure_are_terminal_and_never_retried() -> None:
    case = _longmem_case()
    for expire in (True, False):
        clock = _Clock()
        infinity_ingests = 0

        def infinity_handler(request: httpx.Request) -> httpx.Response:
            nonlocal infinity_ingests
            if request.url.path == "/v1/spaces":
                slug = json.loads(request.content)["slug"]
                return httpx.Response(201, json={"data": {"slug": slug}})
            infinity_ingests += 1
            return httpx.Response(503, json={"error": f"secret-{_INFINITY_TOKEN}"})

        def mem0_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"deleted": True, "verified_absent": True})

        adapter, execution = _build(
            case=case,
            infinity_handler=infinity_handler,
            mem0_handler=mem0_handler,
            clock=clock,
        )
        try:
            _reset(adapter)
            if expire:
                clock.value += timedelta(seconds=10)
            code = "deadline_expired" if expire else "ingest_result_invalid"
            with pytest.raises(ManagedHttpLifecycleError, match=code) as raised:
                _ingest(adapter, case, "infinity-context")
            assert _INFINITY_TOKEN not in str(raised.value)
            assert "infinity.private.test" not in str(raised.value)
            with pytest.raises(ManagedHttpLifecycleError, match="phase_invalid"):
                _ingest(adapter, case, "infinity-context")
        finally:
            execution.close()
        assert infinity_ingests == (0 if expire else 1)


def test_concurrent_ingest_rejects_both_calls_and_terminalizes_receipts() -> None:
    case = _longmem_case()
    clock = _Clock()
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def infinity_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/spaces":
            slug = json.loads(request.content)["slug"]
            return httpx.Response(201, json={"data": {"slug": slug}})
        entered.set()
        assert release.wait(timeout=3)
        return httpx.Response(201, json={"data": {"id": "document-1"}})

    def mem0_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"deleted": True, "verified_absent": True})

    adapter, execution = _build(
        case=case,
        infinity_handler=infinity_handler,
        mem0_handler=mem0_handler,
        clock=clock,
    )
    _reset(adapter)

    def first() -> None:
        try:
            _ingest(adapter, case, "infinity-context")
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=first)
    thread.start()
    assert entered.wait(timeout=3)
    try:
        with pytest.raises(ManagedHttpLifecycleError, match="ingest_concurrent"):
            _ingest(adapter, case, "infinity-context")
    finally:
        release.set()
        thread.join(timeout=3)
        execution.close()
    assert len(errors) == 1
    assert isinstance(errors[0], ManagedHttpLifecycleError)
    assert errors[0].code == "managed_http_lifecycle_ingest_concurrent"
    assert not hasattr(adapter, "terminal_delete")
    assert "private" not in repr(adapter)


def test_failed_execution_evidence_consume_does_not_burn_policy_receipts() -> None:
    case = _longmem_case()
    clock = _Clock()

    def infinity_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/spaces":
            slug = json.loads(request.content)["slug"]
            return httpx.Response(201, json={"data": {"slug": slug}})
        return httpx.Response(201, json={"data": {"id": "document-1"}})

    def mem0_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200, json={"deleted": True, "verified_absent": True})
        return httpx.Response(200, json={"results": [{"id": "memory-1"}]})

    adapter, execution = _build(
        case=case,
        infinity_handler=infinity_handler,
        mem0_handler=mem0_handler,
        clock=clock,
    )
    try:
        _reset(adapter)
        receipts = (_ingest(adapter, case, "infinity-context"), _ingest(adapter, case, "mem0"))
        capability = adapter.execution_evidence_capability()
        with pytest.raises(RuntimeError, match="evidence_binding_invalid"):
            consume_managed_http_execution_evidence(
                capability,
                run_id=_RUN,
                binding_commitment_sha256="c" * 64,
                backend_targets=_targets(),
                cases=(case,),
            )
        policy_views = consume_managed_http_ingest_receipts(
            receipts,
            run_id=_RUN,
            binding_commitment_sha256=_BINDING,
            backend_targets=_targets(),
            cases=(case,),
        )
    finally:
        execution.close()

    assert tuple(view.backend_role for view in policy_views) == (
        "infinity-context",
        "mem0",
    )


def test_execution_evidence_capability_allows_exactly_one_concurrent_consumer() -> None:
    case = _longmem_case()
    clock = _Clock()

    def infinity_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/spaces":
            slug = json.loads(request.content)["slug"]
            return httpx.Response(201, json={"data": {"slug": slug}})
        return httpx.Response(201, json={"data": {"id": "document-1"}})

    def mem0_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200, json={"deleted": True, "verified_absent": True})
        return httpx.Response(200, json={"results": [{"id": "memory-1"}]})

    adapter, execution = _build(
        case=case,
        infinity_handler=infinity_handler,
        mem0_handler=mem0_handler,
        clock=clock,
    )
    results: list[object] = []
    barrier = threading.Barrier(3)
    try:
        _reset(adapter)
        _ingest(adapter, case, "infinity-context")
        _ingest(adapter, case, "mem0")
        capability = adapter.execution_evidence_capability()

        def consume() -> None:
            barrier.wait(timeout=3)
            try:
                results.append(
                    consume_managed_http_execution_evidence(
                        capability,
                        run_id=_RUN,
                        binding_commitment_sha256=_BINDING,
                        backend_targets=_targets(),
                        cases=(case,),
                    )
                )
            except BaseException as exc:
                results.append(exc)

        threads = [threading.Thread(target=consume) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=3)
        for thread in threads:
            thread.join(timeout=3)
    finally:
        execution.close()

    successes = [item for item in results if not isinstance(item, BaseException)]
    failures = [item for item in results if isinstance(item, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert str(failures[0]) == "managed_http_execution_evidence_binding_invalid"


def test_execution_evidence_capability_rejects_direct_state_tamper() -> None:
    case = _longmem_case()
    clock = _Clock()

    def infinity_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/spaces":
            slug = json.loads(request.content)["slug"]
            return httpx.Response(201, json={"data": {"slug": slug}})
        return httpx.Response(201, json={"data": {"id": "document-1"}})

    def mem0_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200, json={"deleted": True, "verified_absent": True})
        return httpx.Response(200, json={"results": [{"id": "memory-1"}]})

    adapter, execution = _build(
        case=case,
        infinity_handler=infinity_handler,
        mem0_handler=mem0_handler,
        clock=clock,
    )
    try:
        _reset(adapter)
        _ingest(adapter, case, "infinity-context")
        _ingest(adapter, case, "mem0")
        capability = adapter.execution_evidence_capability()
        evidence_module._STATES[capability].completed_ingest_count += 1
        with pytest.raises(RuntimeError, match="evidence_binding_invalid"):
            consume_managed_http_execution_evidence(
                capability,
                run_id=_RUN,
                binding_commitment_sha256=_BINDING,
                backend_targets=_targets(),
                cases=(case,),
            )
        with pytest.raises(RuntimeError, match="evidence_binding_invalid"):
            consume_managed_http_execution_evidence(
                capability,
                run_id=_RUN,
                binding_commitment_sha256=_BINDING,
                backend_targets=_targets(),
                cases=(case,),
            )
    finally:
        execution.close()
