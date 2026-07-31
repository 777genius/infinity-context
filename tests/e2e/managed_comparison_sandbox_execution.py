"""Real gold-blind and complete-execution evidence for the managed sandbox."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace

from infinity_context_server.memory_comparison_benchmark_identity import (
    mem0_benchmark_user_id,
)
from infinity_context_server.memory_comparison_full_execution_validation import (
    FullExecutionCaseManifestEntry,
    FullExecutionProviderCall,
    issue_full_execution_validation_session,
    seal_full_execution_validation,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_gold_blind import build_gold_blind_contract
from infinity_context_server.memory_comparison_gold_blind_contract import (
    GoldBlindEvidence,
    GoldBlindExpectedDispatchCase,
    GoldBlindJudgeResult,
    JudgeRunKey,
    create_gold_blind_run_dispatch_ledger,
    create_trusted_gold_blind_evaluator,
    dispatch_answer,
    dispatch_judge,
    dispatch_retrieval,
    issue_gold_blind_judge_dispatch_binding,
    verify_gold_blind_execution,
)
from infinity_context_server.memory_comparison_locomo_expected_turn import (
    ExpectedOfficialLocomoTurn,
)
from infinity_context_server.memory_comparison_locomo_transport import (
    LocomoOfficialTurnsTransportRequest,
    RunScopedLocomoTransportEvidenceKey,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedCaseExecution,
    ManagedExecutionArtifacts,
    ManagedRunCase,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderCallProvenance,
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_session_identity_contract import (
    RunScopedSessionHmacKey,
    SessionIdentityMapping,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from managed_comparison_sandbox_adapters import (
    REQUIRED_MODEL,
    SandboxBackendState,
    SandboxTrace,
    implementation_sha256,
)


class _GoldRetriever:
    def __init__(self, state: SandboxBackendState, backend_role: str, corpus_id: str) -> None:
        self._source = state.source(backend_role, corpus_id)

    def search(
        self,
        request: Mapping[str, object],
        *,
        run_id: str,
        top_k: int,
    ) -> tuple[GoldBlindEvidence, ...]:
        del request
        assert run_id and top_k == 5
        return (
            GoldBlindEvidence(
                item_id="official-turn-1",
                text=self._source.text,
                rank=1,
                created_at="2023-05-08T13:56:00Z",
            ),
        )


class _GoldAnswerer:
    def __init__(
        self,
        state: SandboxBackendState,
        backend_role: str,
        corpus_id: str,
        answer_text: str,
    ) -> None:
        self._source = state.source(backend_role, corpus_id)
        self._answer_text = answer_text

    def answer(self, request: Mapping[str, object]) -> object:
        assert "question" in request
        assert self._source.text in repr(request)
        return {"answer": self._answer_text}


def _correct_judge(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    assert candidate_answer["answer"] == "green tea"  # type: ignore[index]
    assert ground_truth == "green tea"
    assert "green tea" in expected_terms
    assert not forbidden_terms
    return GoldBlindJudgeResult(verdict="correct", score=1.0)


class SandboxExecutionPort:
    def __init__(
        self,
        trace: SandboxTrace,
        *,
        state: SandboxBackendState,
        public_case: PublicBenchmarkCase,
        case_manifest: tuple[FullExecutionCaseManifestEntry, ...],
        provider_route: ProviderRouteAttestation,
        answer_text: str = "green tea",
    ) -> None:
        self.adapter_id = "managed-locomo-sandbox-execution"
        self.implementation_sha256 = implementation_sha256("execution")
        self.trace = trace
        self._state = state
        self._case = public_case
        self._manifest = case_manifest
        self._route = provider_route
        self._answer_text = answer_text
        self._bindings: FullComparisonRunBindings | None = None
        self._ledger = None
        self._contracts: dict[str, tuple[object, JudgeRunKey]] = {}
        self._provider_calls: list[FullExecutionProviderCall] = []
        self._answers: dict[str, object] = {}
        self.case_manifest: tuple[FullExecutionCaseManifestEntry, ...] | None = None
        self.gold_validation: object | None = None

    @property
    def provider_calls(self) -> tuple[FullExecutionProviderCall, ...]:
        return tuple(self._provider_calls)

    def _lane_id(self, backend_role: str, case_id: str) -> str:
        return f"{case_id}:{backend_role}"

    def _ensure_gold(self, bindings: FullComparisonRunBindings) -> None:
        if self._bindings is not None:
            assert self._bindings is bindings
            return
        self._bindings = bindings
        expected = tuple(
            GoldBlindExpectedDispatchCase(
                case_id=self._lane_id(target.backend_role, item.case_id),
                retrieval_backend_id=f"{target.backend_role}-retrieval",
                answer_backend_id=f"{target.backend_role}-answerer",
                judge_backend_id=f"{target.backend_role}-judge",
            )
            for item in self._manifest
            for target in bindings.backend_targets
        )
        self._ledger = create_gold_blind_run_dispatch_ledger(
            run_id=bindings.run_id,
            comparison_binding_commitment_sha256=bindings.binding_commitment_sha256,
            expected_cases=expected,
        )
        for lane in expected:
            key = JudgeRunKey.issue(run_id=bindings.run_id, case_id=lane.case_id)
            gold_case = replace(
                self._case,
                case_id=lane.case_id,
                metadata={
                    "_evaluator_ground_truth": "green tea",
                    "reference_date": "8 May 2023",
                },
            )
            contract = build_gold_blind_contract(
                gold_case,
                run_id=bindings.run_id,
                judge_key=key,
                dispatch_ledger=self._ledger,
            )
            self._contracts[lane.case_id] = (contract, key)

    def retrieve(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        case: ManagedRunCase,
    ) -> object:
        assert len(target_identity_sha256) == 64
        self._ensure_gold(bindings)
        lane = self._lane_id(backend_role, case.case_id)
        contract, _key = self._contracts[lane]
        result = dispatch_retrieval(
            _GoldRetriever(self._state, backend_role, case.corpus_id),
            contract.retrieval_request,
            backend_id=f"{backend_role}-retrieval",
            dispatch_ledger=self._ledger,
            run_id=bindings.run_id,
            top_k=5,
        )
        self.trace.add(f"retrieve:{backend_role}:{case.case_id}")
        return result

    def answer(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        case: ManagedRunCase,
        retrieval_receipt: object,
    ) -> object:
        assert len(target_identity_sha256) == 64 and type(retrieval_receipt) is tuple
        lane = self._lane_id(backend_role, case.case_id)
        contract, _key = self._contracts[lane]
        answer = dispatch_answer(
            _GoldAnswerer(
                self._state,
                backend_role,
                case.corpus_id,
                self._answer_text,
            ),
            contract.answer_request(retrieval_receipt),
            backend_id=f"{backend_role}-answerer",
            dispatch_ledger=self._ledger,
            run_id=bindings.run_id,
            case_id=lane,
        )
        self._answers[lane] = answer
        self._provider_call(bindings, case.case_id, backend_role, "answerer")
        self.trace.add(f"answer:{backend_role}:{case.case_id}")
        return answer

    def judge(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        case: ManagedRunCase,
        answer_receipt: object,
    ) -> object:
        assert len(target_identity_sha256) == 64
        lane = self._lane_id(backend_role, case.case_id)
        assert self._answers[lane] is answer_receipt
        contract, key = self._contracts[lane]
        result = dispatch_judge(
            create_trusted_gold_blind_evaluator(_correct_judge),
            contract.judge_channel,
            backend_id=f"{backend_role}-judge",
            dispatch_ledger=self._ledger,
            answer_binding=issue_gold_blind_judge_dispatch_binding(
                self._ledger,
                run_id=bindings.run_id,
                case_id=lane,
                backend_id=f"{backend_role}-judge",
            ),
            key=key,
            run_id=bindings.run_id,
            case_id=lane,
        )
        self._provider_call(bindings, case.case_id, backend_role, "judge")
        self.trace.add(f"judge:{backend_role}:{case.case_id}")
        return result

    def _provider_call(
        self,
        bindings: FullComparisonRunBindings,
        case_id: str,
        backend_role: str,
        stage: str,
    ) -> None:
        response_id = f"resp-{backend_role}-{stage}"
        self._provider_calls.append(
            FullExecutionProviderCall(
                bindings.binding_commitment_sha256,
                bindings.run_id,
                bindings.profile_id,
                case_id,
                backend_role,
                stage,
                False,
                ProviderCallProvenance(
                    self._route,
                    REQUIRED_MODEL,
                    REQUIRED_MODEL,
                    response_id,
                    f"fp-{backend_role}-{stage}",
                    hashlib.sha256(response_id.encode()).hexdigest(),
                ),
            )
        )

    def seal_execution(
        self,
        *,
        bindings: FullComparisonRunBindings,
        executions: tuple[ManagedCaseExecution, ...],
        case_manifest: tuple[FullExecutionCaseManifestEntry, ...],
        case_manifest_sha256: str,
    ) -> ManagedExecutionArtifacts:
        assert self._bindings is bindings
        assert len(executions) == 2 * len(self._manifest)
        assert case_manifest is self._manifest
        assert case_manifest[0].case_id == self._case.case_id
        assert len(self._provider_calls) == 4 * len(self._manifest)
        self.case_manifest = case_manifest
        execution = _execution_validation(
            bindings,
            case_manifest,
            tuple(self._provider_calls),
            self._route,
            self._state,
        )
        gold = verify_gold_blind_execution(self._ledger)
        self.gold_validation = gold
        self.trace.add("execution.seal")
        return ManagedExecutionArtifacts(gold, execution, case_manifest_sha256)


def _execution_validation(
    bindings: FullComparisonRunBindings,
    manifest: tuple[FullExecutionCaseManifestEntry, ...],
    calls: tuple[FullExecutionProviderCall, ...],
    route: ProviderRouteAttestation,
    state: SandboxBackendState,
) -> object:
    session_key = RunScopedSessionHmacKey.generate(run_id=bindings.run_id)
    mappings = tuple(
        SessionIdentityMapping(
            item.corpus_id,
            item.thread_id,
            item.case_id,
            role,
            alias,
        )
        for item in manifest
        for role, alias in zip(item.session_roles, item.session_aliases, strict=True)
    )
    transport_key = RunScopedLocomoTransportEvidenceKey.generate(run_id=bindings.run_id)
    source = "locomo:sandbox-locomo-1:session_1:D1:1:turn"
    metadata = {
        "benchmark": "locomo",
        "case_id": manifest[0].case_id,
        "corpus_key": manifest[0].corpus_id,
        "source_external_id": source,
        "source_id": source,
        "session_key": "session_1",
        "session_date": "1:56 pm on 8 May, 2023",
        "dia_id": "D1:1",
        "role": "user",
        "speaker": "Alice",
        "locomo_evidence_ref": "D1:1",
    }
    request = LocomoOfficialTurnsTransportRequest.create(
        messages=[{"role": "user", "content": "Alice bought green tea after work."}],
        user_id=mem0_benchmark_user_id(bindings.run_id),
        run_id=bindings.run_id,
        metadata=metadata,
        timestamp=1_683_554_160,
        idempotency_key=source,
    )
    turn = ExpectedOfficialLocomoTurn.create(
        run_id=bindings.run_id,
        corpus_key=manifest[0].corpus_id,
        source_external_id=source,
        source_id=source,
        session_key="session_1",
        speaker="Alice",
        session_date=metadata["session_date"],
        trigger_case_id=manifest[0].case_id,
        dia_id="D1:1",
        role="user",
        content="Alice bought green tea after work.",
        timestamp=1_683_554_160,
    )
    clean = state.clean_state
    assert clean is not None
    session = issue_full_execution_validation_session(
        bindings=bindings,
        benchmark="locomo",
        case_manifest=manifest,
        required_model=REQUIRED_MODEL,
        required_route=route,
        provider_calls=calls,
        session_verifier=session_key,
        session_evidence=tuple(session_key.issue(item) for item in mappings),
        transport_verifier=transport_key,
        transport_evidence=(transport_key.issue(request, expected_turn=turn),),
        clean_validation=clean.validation,
        clean_scopes=clean.scopes,
        clean_attestation_key=clean.attestation_key,
    )
    return seal_full_execution_validation(session)


__all__ = ("SandboxExecutionPort",)
