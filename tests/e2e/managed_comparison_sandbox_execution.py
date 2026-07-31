"""Gold-blind complete-execution evidence for managed sandbox scenarios."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
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
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _managed_corpus_record,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    managed_execution_case_material_sha256,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
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
    SandboxScenario,
    SandboxTrace,
    implementation_sha256,
)

AnswerFromSource = Callable[[str, str], str]
BindCaseTransform = Callable[[PublicBenchmarkCase], PublicBenchmarkCase]


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
                item_id=f"evidence-{self._source.source_sha256}",
                text=self._source.text,
                rank=1,
                created_at="2023-05-08T13:56:00Z",
            ),
        )


class _GoldAnswerer:
    def __init__(self, answer_from_source: AnswerFromSource) -> None:
        self._answer_from_source = answer_from_source

    def answer(self, request: Mapping[str, object]) -> object:
        question = request.get("question")
        evidence = request.get("evidence")
        assert type(question) is str and type(evidence) is list
        evidence_text = "\n".join(
            str(item["text"])
            for item in evidence
            if type(item) is dict and type(item.get("text")) is str
        )
        assert evidence_text
        return {"answer": self._answer_from_source(question, evidence_text)}


def _correct_judge(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    assert isinstance(candidate_answer, Mapping)
    answer = candidate_answer.get("answer")
    assert answer == ground_truth
    assert str(answer) in expected_terms
    assert not forbidden_terms
    return GoldBlindJudgeResult(verdict="correct", score=1.0)


def locomo_answer_from_source(question: str, source_text: str) -> str:
    assert "what did alice buy" in question.casefold()
    match = re.search(r"\bbought ([^.]+)", source_text, flags=re.IGNORECASE)
    if match is None:
        raise AssertionError("LoCoMo sandbox source has no answer phrase")
    answer = match.group(1).strip()
    return answer.removesuffix(" after work")


class SandboxExecutionPort:
    def __init__(
        self,
        trace: SandboxTrace,
        *,
        candidate_channel: _CandidateGoldBlindChannel,
    ) -> None:
        scenario = candidate_channel.scenario
        self.adapter_id = f"{scenario.scenario_id}-execution"
        self.implementation_sha256 = implementation_sha256(
            "execution",
            scenario_id=scenario.scenario_id,
        )
        self.trace = trace
        self._candidate_channel = candidate_channel
        self._observed_queries: list[ManagedAnswerCase] = []

    @property
    def provider_calls(self) -> tuple[FullExecutionProviderCall, ...]:
        return self._candidate_channel.provider_calls

    @property
    def retrieval_item_ids(self) -> tuple[str, ...]:
        return self._candidate_channel.retrieval_item_ids

    @property
    def observed_queries(self) -> tuple[ManagedAnswerCase, ...]:
        return tuple(self._observed_queries)

    def retrieve(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
    ) -> object:
        assert len(target_identity_sha256) == 64
        self._observed_queries.append(query)
        result = self._candidate_channel.retrieve(
            bindings=bindings,
            backend_role=backend_role,
            case=case,
            query=query,
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
        query: ManagedAnswerCase,
        retrieval_receipt: object,
    ) -> object:
        assert len(target_identity_sha256) == 64 and type(retrieval_receipt) is tuple
        answer = self._candidate_channel.answer(
            bindings=bindings,
            backend_role=backend_role,
            case=case,
            query=query,
            retrieval_receipt=retrieval_receipt,
        )
        self.trace.add(f"answer:{backend_role}:{case.case_id}")
        return answer


class _CandidateGoldBlindChannel:
    def __init__(self, owner: SandboxJudgePort) -> None:
        self.__owner = owner

    @property
    def scenario(self) -> SandboxScenario:
        return self.__owner.scenario

    @property
    def provider_calls(self) -> tuple[FullExecutionProviderCall, ...]:
        return self.__owner.provider_calls

    @property
    def retrieval_item_ids(self) -> tuple[str, ...]:
        return self.__owner.retrieval_item_ids

    def retrieve(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
    ) -> object:
        return self.__owner._candidate_retrieve(bindings, backend_role, case, query)

    def answer(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
        retrieval_receipt: object,
    ) -> object:
        return self.__owner._candidate_answer(
            bindings,
            backend_role,
            case,
            query,
            retrieval_receipt,
        )


class SandboxJudgePort:
    def __init__(
        self,
        trace: SandboxTrace,
        *,
        state: SandboxBackendState,
        provider_route: ProviderRouteAttestation,
        answer_from_source: AnswerFromSource = locomo_answer_from_source,
        bind_case_transform: BindCaseTransform | None = None,
    ) -> None:
        scenario = state.scenario
        self.adapter_id = f"{scenario.scenario_id}-judge"
        self.implementation_sha256 = implementation_sha256(
            "judge",
            scenario_id=scenario.scenario_id,
        )
        self.trace = trace
        self.scenario = scenario
        self._state = state
        self._route = provider_route
        self._answer_from_source = answer_from_source
        self._bind_case_transform = bind_case_transform
        self._bindings: FullComparisonRunBindings | None = None
        self._cases: dict[str, PublicBenchmarkCase] = {}
        self._case_aliases: tuple[str, ...] = ()
        self._case_material_sha256: tuple[tuple[str, str], ...] = ()
        self._ledger = None
        self._contracts: dict[str, tuple[object, JudgeRunKey, object]] = {}
        self._provider_calls: list[FullExecutionProviderCall] = []
        self._answers: dict[str, object] = {}
        self._retrieval_item_ids: list[str] = []
        self.case_manifest: tuple[FullExecutionCaseManifestEntry, ...] | None = None
        self.gold_validation: object | None = None
        self.execution_validation: object | None = None
        self.candidate_channel = _CandidateGoldBlindChannel(self)

    @property
    def provider_calls(self) -> tuple[FullExecutionProviderCall, ...]:
        return tuple(self._provider_calls)

    @property
    def retrieval_item_ids(self) -> tuple[str, ...]:
        return tuple(self._retrieval_item_ids)

    def bind_cases(
        self,
        *,
        bindings: FullComparisonRunBindings,
        cases: tuple[PublicBenchmarkCase, ...],
        case_aliases: tuple[str, ...],
    ) -> tuple[tuple[str, str], ...]:
        assert type(cases) is tuple and cases
        assert type(case_aliases) is tuple and len(case_aliases) == len(cases)
        assert len(set(case_aliases)) == len(case_aliases)
        transform = self._bind_case_transform
        bound_cases = tuple(transform(case) for case in cases) if transform else cases
        if any(type(case) is not PublicBenchmarkCase for case in bound_cases):
            raise AssertionError("sandbox judge bind produced an invalid case")
        commitments = tuple(
            (alias, managed_execution_case_material_sha256(case, case_alias=alias))
            for alias, case in zip(case_aliases, bound_cases, strict=True)
        )
        self._bindings = bindings
        self._cases = dict(zip(case_aliases, bound_cases, strict=True))
        self._case_aliases = case_aliases
        self._case_material_sha256 = commitments
        self._initialize_gold(bindings)
        return commitments

    def _lane_id(self, backend_role: str, case_id: str) -> str:
        return f"{case_id}:{backend_role}"

    def _initialize_gold(self, bindings: FullComparisonRunBindings) -> None:
        assert self._ledger is None and self._bindings is bindings
        expected = tuple(
            GoldBlindExpectedDispatchCase(
                case_id=self._lane_id(target.backend_role, case_alias),
                retrieval_backend_id=f"{target.backend_role}-retrieval",
                answer_backend_id=f"{target.backend_role}-answerer",
                judge_backend_id=f"{target.backend_role}-judge",
            )
            for case_alias in self._case_aliases
            for target in bindings.backend_targets
        )
        self._ledger = create_gold_blind_run_dispatch_ledger(
            run_id=bindings.run_id,
            comparison_binding_commitment_sha256=bindings.binding_commitment_sha256,
            expected_cases=expected,
        )
        for lane in expected:
            case_id, _backend = lane.case_id.rsplit(":", 1)
            public_case = self._cases[case_id]
            expected_answer = public_case.metadata["_evaluator_ground_truth"]
            key = JudgeRunKey.issue(run_id=bindings.run_id, case_id=lane.case_id)
            gold_case = replace(
                public_case,
                case_id=lane.case_id,
                metadata={
                    "_evaluator_ground_truth": expected_answer,
                    "reference_date": public_case.metadata.get("reference_date"),
                },
            )
            contract = build_gold_blind_contract(
                gold_case,
                run_id=bindings.run_id,
                judge_key=key,
                dispatch_ledger=self._ledger,
            )
            self._contracts[lane.case_id] = (contract, key, expected_answer)

    def _require_query(self, case: ManagedRunCase, query: ManagedAnswerCase) -> None:
        public_case = self._cases[case.case_id]
        assert query.case_id == case.case_id
        assert query.question == public_case.question

    def _candidate_retrieve(
        self,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
    ) -> object:
        assert self._bindings is bindings
        self._require_query(case, query)
        lane = self._lane_id(backend_role, case.case_id)
        contract, _key, _expected = self._contracts[lane]
        result = dispatch_retrieval(
            _GoldRetriever(self._state, backend_role, case.corpus_id),
            contract.retrieval_request,
            backend_id=f"{backend_role}-retrieval",
            dispatch_ledger=self._ledger,
            run_id=bindings.run_id,
            top_k=5,
        )
        self._retrieval_item_ids.extend(item.item_id for item in result)
        return result

    def _candidate_answer(
        self,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
        retrieval_receipt: object,
    ) -> object:
        assert self._bindings is bindings
        self._require_query(case, query)
        lane = self._lane_id(backend_role, case.case_id)
        contract, _key, _expected = self._contracts[lane]
        answer = dispatch_answer(
            _GoldAnswerer(self._answer_from_source),
            contract.answer_request(retrieval_receipt),
            backend_id=f"{backend_role}-answerer",
            dispatch_ledger=self._ledger,
            run_id=bindings.run_id,
            case_id=lane,
        )
        self._answers[lane] = answer
        self._provider_call(bindings, case.case_id, backend_role, "answerer")
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
        contract, key, _expected_answer = self._contracts[lane]
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
        response_id = f"resp-{case_id}-{backend_role}-{stage}"
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
                    f"fp-{case_id}-{backend_role}-{stage}",
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
        case_material_sha256: tuple[tuple[str, str], ...],
    ) -> ManagedExecutionArtifacts:
        assert self._bindings is bindings
        assert len(executions) == 2 * len(self._case_aliases)
        assert tuple(item.case_id for item in case_manifest) == self._case_aliases
        assert case_material_sha256 == self._case_material_sha256
        assert len(self._provider_calls) == 4 * len(self._case_aliases)
        assert {item.case_id for item in case_manifest} == set(self._cases)
        self.case_manifest = case_manifest
        execution = _execution_validation(
            bindings,
            case_manifest,
            tuple(self._provider_calls),
            self._route,
            self._state,
            self.scenario,
            self._cases,
        )
        gold = verify_gold_blind_execution(self._ledger)
        self.gold_validation = gold
        self.execution_validation = execution
        self.trace.add("execution.seal")
        return ManagedExecutionArtifacts(
            gold,
            execution,
            case_manifest_sha256,
            case_material_sha256,
        )


def _execution_validation(
    bindings: FullComparisonRunBindings,
    manifest: tuple[FullExecutionCaseManifestEntry, ...],
    calls: tuple[FullExecutionProviderCall, ...],
    route: ProviderRouteAttestation,
    state: SandboxBackendState,
    scenario: SandboxScenario,
    cases: Mapping[str, PublicBenchmarkCase],
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
    clean = state.clean_state
    assert clean is not None
    transport_verifier, transport_evidence = _transport(
        bindings,
        manifest,
        state,
        scenario,
        cases,
    )
    session = issue_full_execution_validation_session(
        bindings=bindings,
        benchmark=scenario.benchmark,
        case_manifest=manifest,
        required_model=REQUIRED_MODEL,
        required_route=route,
        provider_calls=calls,
        session_verifier=session_key,
        session_evidence=tuple(session_key.issue(item) for item in mappings),
        transport_verifier=transport_verifier,
        transport_evidence=transport_evidence,
        clean_validation=clean.validation,
        clean_scopes=clean.scopes,
        clean_attestation_key=clean.attestation_key,
    )
    return seal_full_execution_validation(session)


def _transport(
    bindings: FullComparisonRunBindings,
    manifest: tuple[FullExecutionCaseManifestEntry, ...],
    state: SandboxBackendState,
    scenario: SandboxScenario,
    cases: Mapping[str, PublicBenchmarkCase],
) -> tuple[RunScopedLocomoTransportEvidenceKey | None, tuple[object, ...]]:
    if scenario.benchmark == "longmemeval":
        return None, ()
    transport_key = RunScopedLocomoTransportEvidenceKey.generate(run_id=bindings.run_id)
    evidence: list[object] = []
    observed_corpora: set[str] = set()
    for item in manifest:
        if item.corpus_id in observed_corpora:
            continue
        observed_corpora.add(item.corpus_id)
        public_case = cases[item.case_id]
        projected_memories = _managed_corpus_record(public_case)["memories"]
        assert isinstance(projected_memories, list)
        assert len(public_case.memories) == len(projected_memories) == item.official_turn_count
        assert state.source("infinity-context", item.corpus_id).text
        for memory, projected in zip(
            public_case.memories,
            projected_memories,
            strict=True,
        ):
            assert isinstance(projected, Mapping) and type(projected.get("text")) is str
            source_text = projected["text"]
            memory_metadata = memory.metadata
            source = memory.source_external_id
            assert type(source) is str
            session_key = memory_metadata["session_key"]
            session_date = memory_metadata["session_date"]
            dia_id = memory_metadata["dia_id"]
            role = memory_metadata["role"]
            speaker = memory_metadata["speaker"]
            timestamp = memory_metadata["timestamp"]
            assert all(
                type(value) is str for value in (session_key, session_date, dia_id, role, speaker)
            )
            assert type(timestamp) is int
            metadata = {
                "benchmark": "locomo",
                "case_id": public_case.case_id,
                "corpus_key": item.corpus_id,
                "source_external_id": source,
                "source_id": source,
                "session_key": session_key,
                "session_date": session_date,
                "dia_id": dia_id,
                "role": role,
                "speaker": speaker,
                "locomo_evidence_ref": dia_id,
            }
            request = LocomoOfficialTurnsTransportRequest.create(
                messages=[{"role": role, "content": source_text}],
                user_id=mem0_benchmark_user_id(bindings.run_id),
                run_id=bindings.run_id,
                metadata=metadata,
                timestamp=timestamp,
                idempotency_key=source,
            )
            turn = ExpectedOfficialLocomoTurn.create(
                run_id=bindings.run_id,
                corpus_key=item.corpus_id,
                source_external_id=source,
                source_id=source,
                session_key=session_key,
                speaker=speaker,
                session_date=session_date,
                trigger_case_id=public_case.case_id,
                dia_id=dia_id,
                role=role,
                content=source_text,
                timestamp=timestamp,
            )
            evidence.append(
                transport_key.issue(
                    request,
                    expected_turn=turn,
                    public_trigger_case_id=item.case_id,
                )
            )
    return transport_key, tuple(evidence)


__all__ = (
    "AnswerFromSource",
    "SandboxExecutionPort",
    "SandboxJudgePort",
    "locomo_answer_from_source",
)
