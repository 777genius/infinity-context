from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
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
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedComparisonHttpExecutionAdapter,
    ManagedHttpExecutionError,
    ManagedInfinityHttpConfig,
    ManagedMem0HttpConfig,
    managed_http_execution_implementation_sha256,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    INFINITY_TUNED_RETRIEVAL_POLICY,
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkMemoryInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)

_INFINITY_TARGET = managed_backend_target_identity_sha256(
    backend_role="infinity-context", base_url="https://infinity.test"
)
_MEM0_TARGET = managed_backend_target_identity_sha256(
    backend_role="mem0", base_url="https://mem0.test"
)
_PRIVATE_GOLD = "PRIVATE-GOLD-MUST-NOT-CROSS-HTTP"
_PRIVATE_SOURCE_QUESTION = "PRIVATE-SOURCE-QUESTION-MUST-NOT-INGEST"
_RUN_ID = "managed-http-run"


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 1, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def _source_case(*, conversation_count: int = 1) -> PublicBenchmarkCase:
    conversations = tuple(
        BenchmarkConversationInput(
            messages=(
                BenchmarkMessageInput(
                    role="user",
                    content=f"I moved to city {index}.",
                    source_external_id=f"message-{index}-1",
                ),
                BenchmarkMessageInput(
                    role="assistant",
                    content=f"City {index} noted.",
                    source_external_id=f"message-{index}-2",
                ),
            ),
            source_external_id=f"conversation-{index}",
            session_external_id=f"session-{index}",
        )
        for index in range(1, conversation_count + 1)
    )
    return PublicBenchmarkCase(
        benchmark="longmemeval",
        case_id="source-case",
        question=_PRIVATE_SOURCE_QUESTION,
        expected_terms=(_PRIVATE_GOLD,),
        forbidden_terms=("forbidden-private",),
        memory_scope_external_ref="source-corpus",
        thread_external_ref="source-thread",
        metadata={"_evaluator_ground_truth": {"answer": _PRIVATE_GOLD}},
        conversations=conversations,
    )


def _managed_material(*, conversation_count: int = 1) -> tuple[ManagedRunCase, ManagedAnswerCase]:
    source = _source_case(conversation_count=conversation_count)
    corpus_id, _ = _managed_corpus_identity(source)
    case_id = "longmemeval-case-" + "3" * 64
    case = ManagedRunCase(
        case_id=case_id,
        corpus_id=corpus_id,
        record=_managed_corpus_record(source),
    )
    query = ManagedAnswerCase(
        case_id=case_id,
        question="Where did the user move?",
        temporal_context={},
    )
    return case, query


def _locomo_managed_case() -> ManagedRunCase:
    source = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="sample:qa:1",
        question="Where did they go?",
        expected_terms=(_PRIVATE_GOLD,),
        memories=(
            BenchmarkMemoryInput(
                text="The user went to Kyiv.",
                source_external_id="locomo:sample:session_1:D1:1:turn",
                metadata={
                    "role": "user",
                    "speaker": "Alice",
                    "session_key": "session_1",
                    "session_date": "1:00 pm on 1 January, 2024",
                    "timestamp": 1_704_114_000,
                },
            ),
            BenchmarkMemoryInput(
                text="The trip to Kyiv was noted.",
                source_external_id="locomo:sample:session_1:D1:2:turn",
                metadata={
                    "role": "assistant",
                    "speaker": "Bob",
                    "session_key": "session_1",
                    "session_date": "1:00 pm on 1 January, 2024",
                    "timestamp": 1_704_114_000,
                },
            ),
        ),
        memory_scope_external_ref="sample",
        thread_external_ref="sample-thread",
        metadata={
            "_evaluator_ground_truth": {"answer": _PRIVATE_GOLD},
            "locomo_ingest_mode": "official-turns",
            "reference_date": "2 January 2024",
        },
    )
    corpus_id, _ = _managed_corpus_identity(source)
    return ManagedRunCase(
        case_id="locomo-case-" + "4" * 64,
        corpus_id=corpus_id,
        record=_managed_corpus_record(source),
    )


def _targets() -> tuple[FullComparisonBackendTarget, ...]:
    return (
        FullComparisonBackendTarget("infinity-context", _INFINITY_TARGET),
        FullComparisonBackendTarget("mem0", _MEM0_TARGET),
    )


def _profile(profile_id: str = PROFILE_LONGMEMEVAL_TOP_50):
    profile = resolve_full_comparison_profile(profile_id)
    assert profile is not None
    return profile


def _adapter(
    *,
    clock: _Clock,
    infinity_handler,
    mem0_handler,
    infinity_timeout: float = 20.0,
    mem0_timeout: float = 20.0,
    mem0_send_timestamps: bool = False,
    deadline_delta: timedelta = timedelta(seconds=10),
    profile_id: str = PROFILE_LONGMEMEVAL_TOP_50,
    retrieval_policy=NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
) -> ManagedComparisonHttpExecutionAdapter:
    return ManagedComparisonHttpExecutionAdapter(
        admitted_targets=_targets(),
        run_id=_RUN_ID,
        profile=_profile(profile_id),
        deadline=clock.value + deadline_delta,
        infinity=ManagedInfinityHttpConfig(
            target_identity_sha256=_INFINITY_TARGET,
            base_url="https://infinity.test",
            auth_token="test-token",
            timeout_seconds=infinity_timeout,
            transport=httpx.MockTransport(infinity_handler),
        ),
        mem0=ManagedMem0HttpConfig(
            target_identity_sha256=_MEM0_TARGET,
            base_url="https://mem0.test",
            timeout_seconds=mem0_timeout,
            send_timestamps=mem0_send_timestamps,
            transport=httpx.MockTransport(mem0_handler),
        ),
        retrieval_policy=retrieval_policy,
        clock=clock,
    )


def _unused(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected HTTP request: {request.method} {request.url}")


def test_neutral_infinity_retrieval_is_one_exact_query_without_harness_postprocessing() -> None:
    clock = _Clock()
    requests: list[httpx.Request] = []

    def infinity_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [
                        {"item_id": "memory-1", "text": "The user moved to city 1."},
                        {"item_id": "memory-2", "text": "Unrelated evidence."},
                    ]
                }
            },
        )

    adapter = _adapter(
        clock=clock,
        infinity_handler=infinity_handler,
        mem0_handler=_unused,
    )
    case, query = _managed_material()
    try:
        result = adapter.retrieve(
            run_id=_RUN_ID,
            backend_role="infinity-context",
            target_identity_sha256=_INFINITY_TARGET,
            case=case,
            query=query,
        )
    finally:
        adapter.close()

    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert payload["query"] == query.question
    assert payload["max_facts"] == payload["max_chunks"] == 200
    assert _PRIVATE_GOLD not in requests[0].content.decode()
    assert _PRIVATE_SOURCE_QUESTION not in requests[0].content.decode()
    assert tuple((item.item_id, item.rank) for item in result.evidence) == (
        ("memory-1", 1),
        ("memory-2", 2),
    )
    backend = result.metadata["backend"]
    assert backend["retrieval_policy"]["policy_id"] == "neutral-retrieval-v1"
    assert backend["query_decomposition"]["applied"] is False
    assert backend["multi_query_merge"]["applied"] is False
    assert backend["temporal_rerank"]["applied"] is False
    assert backend["benchmark_rerank"]["applied"] is False
    assert result.metadata["retrieval_top_k"] == 200
    assert result.metadata["answer_cutoff"] == 50


def test_ingest_reconstructs_projection_without_question_or_gold_for_both_targets() -> None:
    clock = _Clock()
    infinity_payloads: list[dict[str, object]] = []
    mem0_payloads: list[dict[str, object]] = []

    def infinity_handler(request: httpx.Request) -> httpx.Response:
        infinity_payloads.append(json.loads(request.content))
        return httpx.Response(201, json={"data": {"id": "document-1"}})

    def mem0_handler(request: httpx.Request) -> httpx.Response:
        mem0_payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [{"id": "memory-1"}]})

    adapter = _adapter(
        clock=clock,
        infinity_handler=infinity_handler,
        mem0_handler=mem0_handler,
    )
    case, _ = _managed_material()
    try:
        infinity = adapter.ingest(
            run_id=_RUN_ID,
            backend_role="infinity-context",
            target_identity_sha256=_INFINITY_TARGET,
            case=case,
        )
        mem0 = adapter.ingest(
            run_id=_RUN_ID,
            backend_role="mem0",
            target_identity_sha256=_MEM0_TARGET,
            case=case,
        )
    finally:
        adapter.close()

    wire = json.dumps([infinity_payloads, mem0_payloads], sort_keys=True)
    assert _PRIVATE_SOURCE_QUESTION not in wire
    assert _PRIVATE_GOLD not in wire
    assert "forbidden-private" not in wire
    assert all("question" not in payload for payload in infinity_payloads + mem0_payloads)
    assert infinity.metadata["managed_http_execution"] == {
        "adapter_id": "managed-comparison-http-neutral-v1",
        "composition_blockers": ["credential_authority_not_bound"],
        "credential_continuity_proven": False,
        "question_forwarded": False,
        "gold_fields_forwarded": False,
        "retries": 0,
    }
    assert mem0.metadata["managed_http_execution"]["gold_fields_forwarded"] is False


def test_each_io_timeout_is_minimum_of_configured_and_remaining_deadline() -> None:
    clock = _Clock()
    observed_timeouts: list[float] = []

    def infinity_handler(request: httpx.Request) -> httpx.Response:
        observed_timeouts.append(request.extensions["timeout"]["read"])
        clock.value += timedelta(seconds=2)
        return httpx.Response(201, json={"data": {"id": "document"}})

    adapter = _adapter(
        clock=clock,
        infinity_handler=infinity_handler,
        mem0_handler=_unused,
        infinity_timeout=4.0,
        deadline_delta=timedelta(seconds=5),
    )
    case, _ = _managed_material(conversation_count=2)
    try:
        adapter.ingest(
            run_id=_RUN_ID,
            backend_role="infinity-context",
            target_identity_sha256=_INFINITY_TARGET,
            case=case,
        )
    finally:
        adapter.close()

    assert observed_timeouts == [4.0, 3.0]


def test_invalid_expired_or_gold_tainted_inputs_fail_before_http() -> None:
    clock = _Clock()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": {"items": []}})

    adapter = _adapter(clock=clock, infinity_handler=handler, mem0_handler=handler)
    case, query = _managed_material()
    try:
        with pytest.raises(ManagedHttpExecutionError, match="exactly admitted"):
            adapter.retrieve(
                run_id=_RUN_ID,
                backend_role="infinity-context",
                target_identity_sha256=_MEM0_TARGET,
                case=case,
                query=query,
            )
        with pytest.raises(ManagedHttpExecutionError, match="differs from exact admission"):
            adapter.retrieve(
                run_id="different-managed-run",
                backend_role="infinity-context",
                target_identity_sha256=_INFINITY_TARGET,
                case=case,
                query=query,
            )
        record = dict(case.record)
        record["gold"] = _PRIVATE_GOLD
        tainted = ManagedRunCase(
            case_id=case.case_id,
            corpus_id=case.corpus_id,
            record=record,
        )
        with pytest.raises(ManagedRunError, match="fields are not exact"):
            adapter.ingest(
                run_id=_RUN_ID,
                backend_role="infinity-context",
                target_identity_sha256=_INFINITY_TARGET,
                case=tainted,
            )
        assert calls == 0
        clock.value += timedelta(seconds=10)
        with pytest.raises(ManagedHttpExecutionError, match="expired"):
            adapter.retrieve(
                run_id=_RUN_ID,
                backend_role="infinity-context",
                target_identity_sha256=_INFINITY_TARGET,
                case=case,
                query=query,
            )
    finally:
        adapter.close()
    assert calls == 0


def test_http_failure_is_not_retried_and_close_is_terminal_exactly_once() -> None:
    clock = _Clock()
    calls = 0

    def infinity_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"error": "unavailable"})

    adapter = _adapter(
        clock=clock,
        infinity_handler=infinity_handler,
        mem0_handler=_unused,
    )
    case, query = _managed_material()
    with pytest.raises(httpx.HTTPStatusError):
        adapter.retrieve(
            run_id=_RUN_ID,
            backend_role="infinity-context",
            target_identity_sha256=_INFINITY_TARGET,
            case=case,
            query=query,
        )
    assert calls == 1
    assert not hasattr(adapter, "terminal_delete")
    adapter.close()
    with pytest.raises(ManagedHttpExecutionError, match="already closed"):
        adapter.close()


def test_managed_adapter_rejects_tuned_or_equal_but_reconstructed_policy() -> None:
    clock = _Clock()
    with pytest.raises(ManagedHttpExecutionError, match="neutral-retrieval-v1"):
        _adapter(
            clock=clock,
            infinity_handler=_unused,
            mem0_handler=_unused,
            retrieval_policy=INFINITY_TUNED_RETRIEVAL_POLICY,
        )
    copied = replace(NEUTRAL_COMPARISON_RETRIEVAL_POLICY)
    assert copied == NEUTRAL_COMPARISON_RETRIEVAL_POLICY
    assert copied is not NEUTRAL_COMPARISON_RETRIEVAL_POLICY
    with pytest.raises(ManagedHttpExecutionError, match="neutral-retrieval-v1"):
        _adapter(
            clock=clock,
            infinity_handler=_unused,
            mem0_handler=_unused,
            retrieval_policy=copied,
        )


def test_mem0_locomo_transport_authority_is_exported_with_exact_run_binding() -> None:
    clock = _Clock()
    requests: list[httpx.Request] = []

    def mem0_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"results": [{"id": "memory-1"}]})

    adapter = _adapter(
        clock=clock,
        infinity_handler=_unused,
        mem0_handler=mem0_handler,
        mem0_send_timestamps=True,
        profile_id=PROFILE_LOCOMO_TOP_50,
    )
    try:
        adapter.ingest(
            run_id=_RUN_ID,
            backend_role="mem0",
            target_identity_sha256=_MEM0_TARGET,
            case=_locomo_managed_case(),
        )
        verifier = adapter.locomo_timestamp_transport_verifier(
            run_id=_RUN_ID,
            target_identity_sha256=_MEM0_TARGET,
        )
        evidence = adapter.locomo_timestamp_transport_evidence(
            run_id=_RUN_ID,
            target_identity_sha256=_MEM0_TARGET,
        )
        assert type(verifier) is RunScopedLocomoTransportEvidenceKey
        assert evidence
        assert all(type(item) is LocomoTimestampTransportEvidence for item in evidence)
        calls = len(requests)
        with pytest.raises(ManagedHttpExecutionError, match="exactly admitted"):
            adapter.locomo_timestamp_transport_evidence(
                run_id=_RUN_ID,
                target_identity_sha256=_INFINITY_TARGET,
            )
        assert len(requests) == calls
    finally:
        adapter.close()


def test_http_config_binds_target_identity_to_normalized_base_url() -> None:
    with pytest.raises(ManagedHttpExecutionError, match="differs from base URL"):
        ManagedInfinityHttpConfig(
            target_identity_sha256=_INFINITY_TARGET,
            base_url="https://different-infinity.test",
            auth_token="redacted-test-token",
            timeout_seconds=1.0,
        )


def test_mutated_neutral_policy_singleton_fails_before_http() -> None:
    clock = _Clock()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": {"items": []}})

    adapter = _adapter(clock=clock, infinity_handler=handler, mem0_handler=handler)
    case, query = _managed_material()
    object.__setattr__(NEUTRAL_COMPARISON_RETRIEVAL_POLICY, "apply_candidate_fusion", True)
    try:
        with pytest.raises(ManagedHttpExecutionError, match="neutral-retrieval-v1"):
            adapter.retrieve(
                run_id=_RUN_ID,
                backend_role="infinity-context",
                target_identity_sha256=_INFINITY_TARGET,
                case=case,
                query=query,
            )
    finally:
        object.__setattr__(NEUTRAL_COMPARISON_RETRIEVAL_POLICY, "apply_candidate_fusion", False)
        adapter.close()
    assert calls == 0


def test_adapter_implementation_identity_is_stable_sha256() -> None:
    identity = managed_http_execution_implementation_sha256()
    assert len(identity) == 64
    assert identity == managed_http_execution_implementation_sha256()
