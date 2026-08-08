from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import httpx
import pytest
from infinity_context_server import memory_comparison_managed_http_execution as legacy_execution
from infinity_context_server import memory_comparison_managed_http_lifecycle as legacy_lifecycle
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_production_execution_evidence as production_evidence,
)
from infinity_context_server.memory_comparison_backend_target import FullComparisonBackendTarget
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    gold_blind_evidence_identity,
)
from infinity_context_server.memory_comparison_managed_infinity_clean_state_source import (
    ManagedInfinityCleanStateSourceError,
    consume_managed_infinity_clean_state_evidence_source,
    create_managed_infinity_clean_state_evidence_channel,
)
from infinity_context_server.memory_comparison_managed_infinity_http_execution import (
    ManagedInfinityHttpExecutionAdapter,
    ManagedInfinityHttpRuntimeConfig,
)
from infinity_context_server.memory_comparison_managed_infinity_http_lifecycle import (
    ManagedInfinityHttpIngestReceipt,
    ManagedInfinityHttpLifecycleAdapter,
    managed_infinity_http_lifecycle_implementation_sha256,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
    ManagedMem0V5PairedRuntimeBundle,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_ingest_receipts import (
    ManagedMem0V5CorpusIngestReceipt,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_pending_receipts import (
    ManagedMem0V5PendingReceiptError,
    ManagedMem0V5PendingReceiptSet,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_lifecycle import (
    ManagedMem0V5IngestSnapshot,
    ManagedMem0V5ProductionLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_ports import (
    ManagedV5CutoverProductionPortError,
    create_managed_v5_cutover_lifecycle_ports,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_runner_adapter import (
    ManagedMem0V5RetrievalAdapter,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_managed_retrieval_port import (
    ManagedRetrievalResult,
    _issue_managed_retrieval_authority,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedRunCase,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_managed_v5_retrieval_factory import (
    ManagedV5RetrievalFactoryError,
    create_managed_v5_target_aware_retrieval,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)
from test_memory_comparison_managed_mem0_v5_runner_foundation import _authority_and_case


def _cases() -> tuple[ManagedRunCase, ManagedRunCase]:
    _authority, first = _authority_and_case()
    second_corpus = f"locomo-corpus-{'d' * 64}"
    second_record = dict(first.record)
    second_record["corpus_id"] = second_corpus
    second_record["thread_id"] = f"locomo-thread-{'e' * 64}"
    second = ManagedRunCase("case-2", second_corpus, second_record)
    return first, second


def _binding(*, infinity_target: str = "a" * 64) -> ManagedRunnerCompositionBinding:
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    return ManagedRunnerCompositionBinding(
        run_id="v5-cutover-components",
        profile=profile,
        binding_commitment_sha256="c" * 64,
        deadline=datetime(2027, 1, 1, tzinfo=UTC),
        backend_targets=(
            FullComparisonBackendTarget("infinity-context", infinity_target),
            FullComparisonBackendTarget("mem0", "b" * 64),
        ),
        retrieval_top_k=200,
        answer_cutoff=50,
    )


def test_real_infinity_reset_and_two_ingests_fulfill_deferred_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def legacy_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("legacy or Mem0 component was constructed")

    monkeypatch.setattr(
        legacy_execution.ManagedComparisonHttpExecutionAdapter, "__init__", legacy_forbidden
    )
    monkeypatch.setattr(legacy_execution.Mem0HttpComparisonBackend, "__init__", legacy_forbidden)
    monkeypatch.setattr(legacy_lifecycle.Mem0CleanStateSession, "__init__", legacy_forbidden)
    base_url = "http://127.0.0.1:8080"
    target = managed_backend_target_identity_sha256(
        backend_role="infinity-context", base_url=base_url
    )
    binding = _binding(infinity_target=target)
    cases = _cases()
    events: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/spaces":
            events.append("reset")
            return httpx.Response(
                201, json={"data": {"slug": "memory-comparison-v5-cutover-components"}}
            )
        events.append("ingest")
        return httpx.Response(201, json={"data": {}})

    config = ManagedInfinityHttpRuntimeConfig(
        target_identity_sha256=target,
        base_url=base_url,
        auth_token="test-token",
        transport=httpx.MockTransport(handler),
    )
    execution = ManagedInfinityHttpExecutionAdapter(
        composition_binding=binding,
        config=config,
        clock=lambda: datetime(2026, 8, 8, tzinfo=UTC),
    )
    publisher, source = create_managed_infinity_clean_state_evidence_channel(
        composition_binding=binding,
        corpus_ids=tuple(item.corpus_id for item in cases),
        producer_implementation_sha256=managed_infinity_http_lifecycle_implementation_sha256(),
    )
    lifecycle = ManagedInfinityHttpLifecycleAdapter(
        composition_binding=binding,
        cases=cases,
        execution=execution,
        config=config,
        clean_state_publisher=publisher,
        clock=lambda: datetime(2026, 8, 8, tzinfo=UTC),
    )
    lifecycle.reset(
        run_id=binding.run_id,
        binding_commitment_sha256=binding.binding_commitment_sha256,
        backend_targets=tuple(
            (item.backend_role, item.target_identity_sha256) for item in binding.backend_targets
        ),
    )
    with pytest.raises(ManagedInfinityCleanStateSourceError, match="not_ready"):
        consume_managed_infinity_clean_state_evidence_source(
            source,
            composition_binding=binding,
            corpus_ids=tuple(item.corpus_id for item in cases),
            producer_implementation_sha256=lifecycle.implementation_sha256,
        )
    for case in cases:
        lifecycle.ingest(
            run_id=binding.run_id,
            backend_role="infinity-context",
            target_identity_sha256=target,
            record=dict(case.record),
        )
    evidence = consume_managed_infinity_clean_state_evidence_source(
        source,
        composition_binding=binding,
        corpus_ids=tuple(item.corpus_id for item in cases),
        producer_implementation_sha256=lifecycle.implementation_sha256,
    )
    assert evidence is not None
    assert events == ["reset", "ingest", "ingest"]


def _hollow_components(monkeypatch: pytest.MonkeyPatch):
    binding = _binding()
    cases = _cases()
    infinity = object.__new__(ManagedInfinityHttpLifecycleAdapter)
    mem0 = object.__new__(ManagedMem0V5ProductionLifecycleAdapter)
    bundle = object.__new__(ManagedMem0V5PairedRuntimeBundle)
    calls = {"dispatch": 0, "coverage": 0}

    monkeypatch.setattr(
        ManagedInfinityHttpLifecycleAdapter,
        "composition_binding",
        property(lambda _self: binding),
    )
    monkeypatch.setattr(
        ManagedMem0V5ProductionLifecycleAdapter,
        "composition_binding",
        property(lambda _self: binding),
    )
    monkeypatch.setattr(ManagedInfinityHttpLifecycleAdapter, "reset", lambda *_a, **_k: None)
    monkeypatch.setattr(
        ManagedInfinityHttpLifecycleAdapter,
        "ingest",
        lambda *_a, **_k: object.__new__(ManagedInfinityHttpIngestReceipt),
    )
    monkeypatch.setattr(
        ManagedMem0V5ProductionLifecycleAdapter, "admit_or_restore", lambda *_a, **_k: object()
    )

    def dispatch(*_args: object, **_kwargs: object) -> object:
        calls["dispatch"] += 1
        return object()

    monkeypatch.setattr(ManagedMem0V5ProductionLifecycleAdapter, "dispatch_once", dispatch)
    monkeypatch.setattr(
        ManagedMem0V5PairedRuntimeBundle,
        "issue_transport_coverage",
        lambda *_a, **_k: calls.__setitem__("coverage", calls["coverage"] + 1) or object(),
    )
    monkeypatch.setattr(
        ManagedMem0V5ProductionLifecycleAdapter,
        "consume_transport_coverage",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(
        ManagedMem0V5ProductionLifecycleAdapter,
        "issue_corpus_receipt",
        lambda *_a, **_k: object.__new__(ManagedMem0V5CorpusIngestReceipt),
    )
    monkeypatch.setattr(
        ManagedMem0V5ProductionLifecycleAdapter,
        "authenticate_exact_receipts",
        lambda *_a, **_k: ManagedMem0V5IngestSnapshot(
            tuple(hashlib.sha256(item.corpus_id.encode()).hexdigest() for item in cases),
            ("1" * 64, "2" * 64),
            len(cases),
            "3" * 64,
        ),
    )
    ports = create_managed_v5_cutover_lifecycle_ports(
        composition_binding=binding,
        cases=cases,
        infinity_lifecycle=infinity,
        mem0_lifecycle=mem0,
        paired_runtime_bundle=bundle,
    )
    ports.reset.reset(
        run_id=binding.run_id,
        binding_commitment_sha256=binding.binding_commitment_sha256,
        backend_targets=tuple(
            (item.backend_role, item.target_identity_sha256) for item in binding.backend_targets
        ),
    )
    return binding, cases, ports, calls


def _ingest(
    ports: object, binding: ManagedRunnerCompositionBinding, case: ManagedRunCase, role: str
) -> object:
    target = next(
        item.target_identity_sha256 for item in binding.backend_targets if item.backend_role == role
    )
    return ports.ingest.ingest(
        run_id=binding.run_id,
        backend_role=role,
        target_identity_sha256=target,
        record=dict(case.record),
    )


def test_second_mem0_record_mismatch_dispatches_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    binding, cases, ports, calls = _hollow_components(monkeypatch)
    for case in cases:
        _ingest(ports, binding, case, "infinity-context")
    _ingest(ports, binding, cases[0], "mem0")
    with pytest.raises(ManagedV5CutoverProductionPortError, match="binding_invalid"):
        _ingest(ports, binding, cases[0], "mem0")
    assert calls == {"dispatch": 0, "coverage": 0}


def test_non_json_ingest_record_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    binding, cases, ports, calls = _hollow_components(monkeypatch)
    record = dict(cases[0].record)
    record["non_json"] = {"value"}
    target = next(
        item.target_identity_sha256
        for item in binding.backend_targets
        if item.backend_role == "infinity-context"
    )

    with pytest.raises(
        ManagedV5CutoverProductionPortError,
        match="managed_v5_cutover_ingest_binding_invalid",
    ):
        ports.ingest.ingest(
            run_id=binding.run_id,
            backend_role="infinity-context",
            target_identity_sha256=target,
            record=record,
        )

    assert calls == {"dispatch": 0, "coverage": 0}


def test_non_json_duplicate_corpus_fails_closed_during_composition() -> None:
    binding = _binding()
    first = _cases()[0]
    duplicate = ManagedRunCase("case-duplicate", first.corpus_id, dict(first.record))
    object.__setattr__(duplicate, "record", {"non_json": {"value"}})

    with pytest.raises(
        ManagedV5CutoverProductionPortError,
        match="managed_v5_cutover_cases_invalid",
    ):
        create_managed_v5_cutover_lifecycle_ports(
            composition_binding=binding,
            cases=(first, duplicate),
            infinity_lifecycle=object(),  # type: ignore[arg-type]
            mem0_lifecycle=object(),  # type: ignore[arg-type]
            paired_runtime_bundle=object(),  # type: ignore[arg-type]
        )


def test_final_record_dispatches_once_and_ambiguous_path_never_redispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, cases, ports, calls = _hollow_components(monkeypatch)
    for case in cases:
        _ingest(ports, binding, case, "infinity-context")
    first = _ingest(ports, binding, cases[0], "mem0")
    second = _ingest(ports, binding, cases[1], "mem0")
    assert calls == {"dispatch": 1, "coverage": 1}
    assert ports.ingest.consume_exact_mem0_receipts((first, second))

    binding, cases, ports, calls = _hollow_components(monkeypatch)
    monkeypatch.setattr(
        ManagedMem0V5ProductionLifecycleAdapter,
        "dispatch_once",
        lambda *_a, **_k: (
            calls.__setitem__("dispatch", calls["dispatch"] + 1)
            or (_ for _ in ()).throw(RuntimeError())
        ),
    )
    for case in cases:
        _ingest(ports, binding, case, "infinity-context")
    _ingest(ports, binding, cases[0], "mem0")
    with pytest.raises(ManagedV5CutoverProductionPortError, match="dispatch_ambiguous"):
        _ingest(ports, binding, cases[1], "mem0")
    with pytest.raises(ManagedV5CutoverProductionPortError, match="phase_invalid"):
        _ingest(ports, binding, cases[1], "mem0")
    assert calls["dispatch"] == 1


def test_pending_handles_and_receipts_reject_swapped_missing_and_foreign(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus_ids = ("corpus-a", "corpus-b")
    lifecycle = object.__new__(ManagedMem0V5ProductionLifecycleAdapter)
    owned = tuple(object.__new__(ManagedMem0V5CorpusIngestReceipt) for _ in corpus_ids)
    foreign = tuple(object.__new__(ManagedMem0V5CorpusIngestReceipt) for _ in corpus_ids)

    def authenticate(_self: object, receipts: object) -> ManagedMem0V5IngestSnapshot:
        if (
            type(receipts) is not tuple
            or len(receipts) != len(owned)
            or any(actual is not expected for actual, expected in zip(receipts, owned, strict=True))
        ):
            raise RuntimeError("foreign receipt")
        return ManagedMem0V5IngestSnapshot(
            tuple(hashlib.sha256(item.encode()).hexdigest() for item in corpus_ids),
            ("1" * 64, "2" * 64),
            len(corpus_ids),
            "3" * 64,
        )

    monkeypatch.setattr(
        ManagedMem0V5ProductionLifecycleAdapter,
        "authenticate_exact_receipts",
        authenticate,
    )
    first = ManagedMem0V5PendingReceiptSet(
        corpus_ids=corpus_ids,
        production_lifecycle=lifecycle,
    )
    handles = tuple(first.reserve(corpus_id=item) for item in corpus_ids)
    with pytest.raises(ManagedMem0V5PendingReceiptError, match="bind_invalid"):
        first.bind_exact_ordered(handles=handles[::-1], receipts=owned)

    missing = ManagedMem0V5PendingReceiptSet(
        corpus_ids=corpus_ids,
        production_lifecycle=lifecycle,
    )
    missing_handles = tuple(missing.reserve(corpus_id=item) for item in corpus_ids)
    with pytest.raises(ManagedMem0V5PendingReceiptError, match="bind_invalid"):
        missing.bind_exact_ordered(handles=missing_handles, receipts=owned[:1])

    owner = ManagedMem0V5PendingReceiptSet(
        corpus_ids=corpus_ids,
        production_lifecycle=lifecycle,
    )
    owner_handles = tuple(owner.reserve(corpus_id=item) for item in corpus_ids)
    with pytest.raises(ManagedMem0V5PendingReceiptError, match="bind_invalid"):
        owner.bind_exact_ordered(handles=owner_handles, receipts=owned[::-1])

    foreign_owner = ManagedMem0V5PendingReceiptSet(
        corpus_ids=corpus_ids,
        production_lifecycle=lifecycle,
    )
    foreign_handles = tuple(foreign_owner.reserve(corpus_id=item) for item in corpus_ids)
    with pytest.raises(ManagedMem0V5PendingReceiptError, match="bind_invalid"):
        foreign_owner.bind_exact_ordered(handles=foreign_handles, receipts=foreign)


def test_retrieval_factory_rejects_hollow_or_crosswired_delegates() -> None:
    binding = _binding()
    infinity = object.__new__(ManagedInfinityHttpExecutionAdapter)
    mem0 = object.__new__(ManagedMem0V5RetrievalAdapter)
    with pytest.raises(ManagedV5RetrievalFactoryError, match="composition_invalid"):
        create_managed_v5_target_aware_retrieval(
            composition_binding=binding,
            infinity=infinity,
            mem0=mem0,
        )


def test_retrieval_factory_routes_exactly_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    infinity = object.__new__(ManagedInfinityHttpExecutionAdapter)
    mem0 = object.__new__(ManagedMem0V5RetrievalAdapter)
    calls = {"infinity-context": 0, "mem0": 0}

    monkeypatch.setattr(
        ManagedInfinityHttpExecutionAdapter,
        "composition_binding",
        property(lambda _self: binding),
    )
    monkeypatch.setattr(
        ManagedMem0V5RetrievalAdapter,
        "composition_binding",
        property(lambda _self: binding),
    )
    monkeypatch.setattr(
        ManagedInfinityHttpExecutionAdapter,
        "adapter_id",
        property(lambda _self: "infinity-test-v1"),
    )
    monkeypatch.setattr(
        ManagedInfinityHttpExecutionAdapter,
        "implementation_sha256",
        property(lambda _self: "1" * 64),
    )
    monkeypatch.setattr(
        ManagedMem0V5RetrievalAdapter,
        "adapter_id",
        property(lambda _self: "mem0-test-v1"),
    )
    monkeypatch.setattr(
        ManagedMem0V5RetrievalAdapter,
        "implementation_sha256",
        property(lambda _self: "2" * 64),
    )

    def authority_for(_self: object, *, backend_role: str, target_identity_sha256: str):
        return _issue_managed_retrieval_authority(
            binding,
            backend_role=backend_role,
            target_identity_sha256=target_identity_sha256,
        )

    def retrieve(_self: object, *, authority: object, case: object, query: object):
        del case, query
        role = authority.backend_role
        calls[role] += 1
        return ManagedRetrievalResult(
            evidence=(),
            retrieval_identity=gold_blind_evidence_identity(()),
            metadata={
                "adapter_id": "infinity-test-v1" if role == "infinity-context" else "mem0-test-v1",
                "implementation_sha256": "1" * 64 if role == "infinity-context" else "2" * 64,
                "backend_role": role,
                "target_identity_sha256": authority.target_identity_sha256,
                "retrieval_policy": NEUTRAL_COMPARISON_RETRIEVAL_POLICY.telemetry(),
                "gold_fields_forwarded": False,
                "retries": 0,
            },
        )

    monkeypatch.setattr(ManagedInfinityHttpExecutionAdapter, "authority_for", authority_for)
    monkeypatch.setattr(ManagedMem0V5RetrievalAdapter, "authority_for", authority_for)
    monkeypatch.setattr(ManagedInfinityHttpExecutionAdapter, "retrieve", retrieve)
    monkeypatch.setattr(ManagedMem0V5RetrievalAdapter, "retrieve", retrieve)
    router = create_managed_v5_target_aware_retrieval(
        composition_binding=binding,
        infinity=infinity,
        mem0=mem0,
    )
    case = _cases()[0]
    query = ManagedAnswerCase(case.case_id, "What does Alice like?", {})
    for target in binding.backend_targets:
        authority = router.authority_for(
            backend_role=target.backend_role,
            target_identity_sha256=target.target_identity_sha256,
        )
        router.retrieve(authority=authority, case=case, query=query)
    assert calls == {"infinity-context": 1, "mem0": 1}


def test_execution_evidence_facade_uses_only_foundation_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    lifecycle = object.__new__(ManagedMem0V5ProductionLifecycleAdapter)
    calls: list[str] = []
    monkeypatch.setattr(
        ManagedMem0V5ProductionLifecycleAdapter,
        "composition_binding",
        property(lambda _self: binding),
    )
    monkeypatch.setattr(
        ManagedMem0V5ProductionLifecycleAdapter,
        "consume_ready_execution_evidence",
        lambda *_a, **_k: calls.append("consume"),
    )
    monkeypatch.setattr(
        ManagedMem0V5ProductionLifecycleAdapter,
        "seal_execution_validation",
        lambda *_a, **_k: calls.append("seal") or object(),
    )
    facade = production_evidence.ManagedMem0V5ProductionExecutionEvidenceFacade(
        composition_binding=binding,
        lifecycle=lifecycle,
    )
    facade.consume_ready_evidence(
        composition_binding=binding,
        bindings=object(),
        cases=_cases(),
    )
    facade.seal_execution_validation(
        composition_binding=binding,
        bindings=object(),
        benchmark="locomo",
        case_manifest=(),
        required_model="model",
        required_route=object(),
        provider_calls=(),
        session_verifier=object(),
        session_evidence=(),
    )
    assert calls == ["consume", "seal"]
