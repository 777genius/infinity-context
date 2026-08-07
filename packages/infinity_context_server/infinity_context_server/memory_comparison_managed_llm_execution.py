"""Production managed answer and stateful gold-blind judge execution authority.

The pinned Mem0 prompt text is reused with an admitted subscription model. This
is a non-publishable production canary, not proof of identical published Mem0
methodology.
"""

from __future__ import annotations

import hashlib
import math
import threading
from dataclasses import dataclass, replace
from typing import final

from infinity_context_server.memory_comparison_bounded_provider import (
    BoundedProviderChatCompletions,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCaseManifestEntry,
    execution_case_manifest_sha256,
)
from infinity_context_server.memory_comparison_full_profiles import (
    REQUIRED_FULL_COMPARISON_BACKENDS,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
    validate_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_gold_blind import build_gold_blind_contract
from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    gold_blind_evidence_identity,
)
from infinity_context_server.memory_comparison_gold_blind_contract import (
    GoldBlindExpectedDispatchCase,
    JudgeRunKey,
    create_gold_blind_run_dispatch_ledger,
    dispatch_answer,
    dispatch_judge,
    dispatch_retrieval,
    issue_gold_blind_judge_dispatch_binding,
    verify_gold_blind_execution,
)
from infinity_context_server.memory_comparison_gold_blind_judge_capability import (
    _issue_trusted_gold_blind_judge_capability,
)
from infinity_context_server.memory_comparison_gold_blind_run_validation import (
    canonical_dispatch_json,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _managed_corpus_identity,
    _managed_corpus_record,
)
from infinity_context_server.memory_comparison_managed_execution_evidence_port import (
    ManagedExecutionEvidencePort,
)
from infinity_context_server.memory_comparison_managed_execution_receipts import (
    ManagedExecutionReceipt,
    ManagedExecutionReceiptIssuer,
    ManagedSealedJudgeOutcome,
    consume_sealed_managed_execution_receipt,
    create_managed_execution_receipt_issuer,
    inspect_managed_retrieval_receipt_for_answer,
    issue_managed_answer_receipt,
    issue_managed_judge_receipt,
    issue_managed_retrieval_receipt,
    seal_managed_execution_receipt,
)
from infinity_context_server.memory_comparison_managed_live_composition import (
    ManagedLiveExecutionLimits,
)
from infinity_context_server.memory_comparison_managed_llm_execution_dispatch import (
    ManagedAnswerDispatchPort,
    ManagedLlmExecutionError,
    ManagedRetrievalDispatchPort,
    ManagedStatefulJudge,
    invoke_managed_stateful_judge,
)
from infinity_context_server.memory_comparison_managed_llm_execution_ports import (
    MANAGED_PRODUCTION_EXECUTION_PUBLISHABLE,
    MANAGED_PRODUCTION_METHODOLOGY_STATUS,
    ManagedComparisonCandidateExecutionPort,
    ManagedComparisonExecutionPorts,
    ManagedComparisonJudgeExecutionPort,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    managed_execution_case_material_sha256,
)
from infinity_context_server.memory_comparison_managed_provider_calls import (
    ManagedProviderCallCollector,
    ManagedProviderCallOutcome,
    ManagedProviderLaneBinding,
    create_managed_provider_call_collector,
    managed_provider_lane_bindings,
)
from infinity_context_server.memory_comparison_managed_retrieval_port import (
    ManagedRetrievalPort,
    ManagedRetrievalResult,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedCaseExecution,
    ManagedExecutionArtifacts,
    ManagedRunCase,
    _thaw_json,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)
from infinity_context_server.memory_comparison_session_identity_contract import (
    RunScopedSessionHmacKey,
    SessionIdentityMapping,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

MANAGED_SUBSCRIPTION_EXECUTION_MODEL = "gpt-5.6-sol"
MANAGED_RETRIEVAL_PROOF_STATUS = "bound_internal_no_full_execution_artifact_slot"


@dataclass(frozen=True, slots=True)
class _BoundCase:
    public_case: PublicBenchmarkCase
    managed_case: ManagedRunCase
    query: ManagedAnswerCase


@dataclass(slots=True)
class _Lane:
    lane_id: str
    backend_role: str
    target_identity_sha256: str
    contract: object
    judge_key: JudgeRunKey
    answer_binding: ManagedProviderLaneBinding
    judge_binding: ManagedProviderLaneBinding
    receipt_issuer: ManagedExecutionReceiptIssuer
    retrieval_implementation_sha256: str
    retrieval_receipt: ManagedExecutionReceipt | None = None
    answer_receipt: ManagedExecutionReceipt | None = None
    judge_receipt: ManagedExecutionReceipt | None = None
    retrieval_result: ManagedRetrievalResult | None = None
    retrieval_metadata_sha256: str | None = None


@final
class _ManagedExecutionCoordinator:
    def __init__(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        retrieval: ManagedRetrievalPort,
        execution_evidence: ManagedExecutionEvidencePort,
        retrieval_adapter_id: str,
        retrieval_implementation_sha256: str,
        provider: BoundedProviderChatCompletions,
        limits: ManagedLiveExecutionLimits,
        provider_route: ProviderRouteAttestation,
    ) -> None:
        try:
            neutral_composition_valid = (
                type(composition_binding) is ManagedRunnerCompositionBinding
                and retrieval.composition_binding is composition_binding
                and execution_evidence.composition_binding is composition_binding
            )
        except Exception:
            neutral_composition_valid = False
        if (
            not neutral_composition_valid
            or type(provider) is not BoundedProviderChatCompletions
            or type(limits) is not ManagedLiveExecutionLimits
            or type(provider_route) is not ProviderRouteAttestation
            or type(retrieval_adapter_id) is not str
            or not retrieval_adapter_id
            or type(retrieval_implementation_sha256) is not str
            or len(retrieval_implementation_sha256) != 64
            or any(item not in "0123456789abcdef" for item in retrieval_implementation_sha256)
            or limits.answerer_model != MANAGED_SUBSCRIPTION_EXECUTION_MODEL
            or limits.judge_model != MANAGED_SUBSCRIPTION_EXECUTION_MODEL
            or composition_binding.deadline is not limits.deadline
        ):
            raise ManagedLlmExecutionError("managed_execution_composition_invalid")
        budget = getattr(provider, "_budget", None)
        deadline = getattr(budget, "deadline_monotonic", None)
        if (
            isinstance(deadline, bool)
            or not isinstance(deadline, int | float)
            or not math.isfinite(deadline)
            or deadline <= 0
        ):
            raise ManagedLlmExecutionError("managed_execution_deadline_invalid")
        self._binding = composition_binding
        self._retrieval = retrieval
        self._execution_evidence = execution_evidence
        self._retrieval_adapter_id = retrieval_adapter_id
        self._retrieval_implementation_sha256 = retrieval_implementation_sha256
        self._provider = provider
        self._limits = limits
        self._route = provider_route
        self._execution_evidence_ready = False
        self._bound_managed_cases: tuple[ManagedRunCase, ...] = ()
        self._deadline_monotonic = float(deadline)
        self._lock = threading.RLock()
        self._phase = "new"
        self._active = False
        self._bindings: FullComparisonRunBindings | None = None
        self._cases: dict[str, _BoundCase] = {}
        self._aliases: tuple[str, ...] = ()
        self._case_material: tuple[tuple[str, str], ...] = ()
        self._lanes: dict[tuple[str, str], _Lane] = {}
        self._operation_order: tuple[tuple[str, str, str], ...] = ()
        self._operation_index = 0
        self._ledger = None
        self._collector: ManagedProviderCallCollector | None = None

    def bind_cases(
        self,
        bindings: FullComparisonRunBindings,
        cases: tuple[PublicBenchmarkCase, ...],
        aliases: tuple[str, ...],
    ) -> tuple[tuple[str, str], ...]:
        try:
            with self._lock:
                if self._phase != "new":
                    raise ManagedLlmExecutionError("managed_execution_bind_replay")
                self._phase = "binding"
            trusted = validate_full_comparison_run_bindings(bindings)
            if (
                type(cases) is not tuple
                or not cases
                or any(type(item) is not PublicBenchmarkCase for item in cases)
                or type(aliases) is not tuple
                or len(aliases) != len(cases)
                or len(set(aliases)) != len(aliases)
                or len(cases) > self._limits.max_cases
            ):
                raise ManagedLlmExecutionError("managed_execution_cases_invalid")
            profile = resolve_full_comparison_profile(trusted.profile_id)
            if (
                profile is None
                or self._binding.profile_id != trusted.profile_id
                or self._binding.run_id != trusted.run_id
                or self._binding.binding_commitment_sha256
                != trusted.binding_commitment_sha256
                or self._binding.retrieval_top_k != profile.retrieval_top_k
                or self._binding.answer_cutoff != profile.answer_cutoff
            ):
                raise ManagedLlmExecutionError("managed_execution_profile_invalid")
            backend_roles = tuple(item.backend_role for item in trusted.backend_targets)
            if (
                backend_roles != REQUIRED_FULL_COMPARISON_BACKENDS
                or self._binding.backend_targets != trusted.backend_targets
            ):
                raise ManagedLlmExecutionError("managed_execution_backends_invalid")
            provider_plan = managed_provider_lane_bindings(
                comparison_commitment_sha256=trusted.binding_commitment_sha256,
                run_id=trusted.run_id,
                profile_id=trusted.profile_id,
                public_case_aliases=aliases,
                backend_roles=backend_roles,
                answerer_model=self._limits.answerer_model,
                judge_model=self._limits.judge_model,
            )
            if len(provider_plan) > self._limits.benchmark_max_provider_calls:
                raise ManagedLlmExecutionError("managed_execution_provider_budget_invalid")
            collector = create_managed_provider_call_collector(
                provider=self._provider,
                bindings=provider_plan,
                deadline_monotonic=self._deadline_monotonic,
            )
            expected = tuple(
                GoldBlindExpectedDispatchCase(
                    case_id=_lane_id(alias, target.backend_role),
                    retrieval_backend_id=f"{target.backend_role}-retrieval",
                    answer_backend_id=f"{target.backend_role}-answerer",
                    judge_backend_id=f"{target.backend_role}-judge",
                )
                for alias in aliases
                for target in trusted.backend_targets
            )
            ledger = create_gold_blind_run_dispatch_ledger(
                run_id=trusted.run_id,
                comparison_binding_commitment_sha256=trusted.binding_commitment_sha256,
                expected_cases=expected,
            )
            material: list[tuple[str, str]] = []
            bound_cases: dict[str, _BoundCase] = {}
            lanes: dict[tuple[str, str], _Lane] = {}
            plan_by_key = {
                (item.public_case_alias, item.backend_role, item.stage): item
                for item in provider_plan
            }
            for source, alias in zip(cases, aliases, strict=True):
                material.append(
                    (
                        alias,
                        managed_execution_case_material_sha256(source, case_alias=alias),
                    )
                )
                corpus_id, _thread_id = _managed_corpus_identity(source)
                managed_case = ManagedRunCase(alias, corpus_id, _managed_corpus_record(source))
                query = _answer_case(source, alias)
                bound_cases[alias] = _BoundCase(
                    _gold_free_prompt_case(source, alias), managed_case, query
                )
                for target in trusted.backend_targets:
                    lane_id = _lane_id(alias, target.backend_role)
                    key = JudgeRunKey.issue(run_id=trusted.run_id, case_id=lane_id)
                    contract = build_gold_blind_contract(
                        replace(source, case_id=lane_id),
                        run_id=trusted.run_id,
                        judge_key=key,
                        dispatch_ledger=ledger,
                    )
                    answer_binding = plan_by_key[(alias, target.backend_role, "answerer")]
                    judge_binding = plan_by_key[(alias, target.backend_role, "judge")]
                    issuer = create_managed_execution_receipt_issuer(
                        answer_binding=answer_binding,
                        judge_binding=judge_binding,
                        target_identity_sha256=target.target_identity_sha256,
                    )
                    lanes[(alias, target.backend_role)] = _Lane(
                        lane_id,
                        target.backend_role,
                        target.target_identity_sha256,
                        contract,
                        key,
                        answer_binding,
                        judge_binding,
                        issuer,
                        self._retrieval_implementation_sha256,
                    )
            with self._lock:
                self._bindings = bindings
                self._cases = bound_cases
                self._aliases = aliases
                self._case_material = tuple(material)
                self._bound_managed_cases = tuple(
                    bound_cases[alias].managed_case for alias in aliases
                )
                self._lanes = lanes
                self._ledger = ledger
                self._collector = collector
                self._operation_order = tuple(
                    (stage, alias, target.backend_role)
                    for alias in aliases
                    for target in trusted.backend_targets
                    for stage in ("retrieve", "answer", "judge")
                )
                self._phase = "bound"
            return self._case_material
        except BaseException as exc:
            self._terminal()
            _raise_fixed(exc, "managed_execution_bind_failed")

    def retrieve(
        self,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
    ) -> ManagedExecutionReceipt:
        lane = self._begin_operation("retrieve", bindings, backend_role, target, case, query)
        try:
            self._ensure_execution_evidence(bindings)
            authority = self._retrieval.authority_for(
                backend_role=backend_role,
                target_identity_sha256=target,
            )
            retrieval_port = ManagedRetrievalDispatchPort(
                composition_binding=self._binding,
                retrieval=self._retrieval,
                authority=authority,
                run_id=bindings.run_id,
                backend_role=backend_role,
                case=case,
                query=query,
                expected_case_id=lane.lane_id,
            )
            evidence = dispatch_retrieval(
                retrieval_port,
                lane.contract.retrieval_request,
                backend_id=f"{backend_role}-retrieval",
                dispatch_ledger=self._ledger,
                run_id=bindings.run_id,
                top_k=self._binding.retrieval_top_k,
            )
            if type(evidence) is not tuple:
                raise ManagedLlmExecutionError("managed_retrieval_result_invalid")
            result = retrieval_port.take_result()
            if result.evidence is not evidence:
                raise ManagedLlmExecutionError("managed_retrieval_result_invalid")
            lane.retrieval_result = result
            lane.retrieval_metadata_sha256 = _retrieval_semantic_identity(
                result,
                lane,
                adapter_id=self._retrieval_adapter_id,
                implementation_sha256=self._retrieval_implementation_sha256,
            )
            receipt = issue_managed_retrieval_receipt(
                lane.receipt_issuer,
                evidence=evidence,
                retrieval_identity=gold_blind_evidence_identity(evidence),
            )
            lane.retrieval_receipt = receipt
        except BaseException as exc:
            self._operation_failed()
            _raise_fixed(exc, "managed_execution_retrieval_failed")
        self._operation_succeeded()
        return receipt

    def answer(
        self,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
        retrieval_receipt: object,
    ) -> ManagedExecutionReceipt:
        lane = self._begin_operation("answer", bindings, backend_role, target, case, query)
        try:
            if retrieval_receipt is not lane.retrieval_receipt:
                raise ManagedLlmExecutionError("managed_answer_receipt_invalid")
            view = inspect_managed_retrieval_receipt_for_answer(
                lane.receipt_issuer, retrieval_receipt
            )
            answer_port = ManagedAnswerDispatchPort(
                case=self._cases[case.case_id].public_case,
                evidence=view.evidence,
                lane=self._collector_required().issue_lane(lane.answer_binding),
            )
            result = dispatch_answer(
                answer_port,
                lane.contract.answer_request(view.evidence),
                backend_id=f"{backend_role}-answerer",
                dispatch_ledger=self._ledger,
                run_id=bindings.run_id,
                case_id=lane.lane_id,
            )
            outcome = answer_port.take_outcome()
            self._validate_route(outcome)
            receipt = issue_managed_answer_receipt(
                lane.receipt_issuer,
                predecessor=retrieval_receipt,
                outcome=outcome,
                answer_result_identity=hashlib.sha256(canonical_dispatch_json(result)).hexdigest(),
            )
            lane.answer_receipt = receipt
        except BaseException as exc:
            self._operation_failed()
            _raise_fixed(exc, "managed_execution_answer_failed")
        self._operation_succeeded()
        return receipt

    def judge(
        self,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target: str,
        case: ManagedRunCase,
        answer_receipt: object,
    ) -> ManagedExecutionReceipt:
        lane = self._begin_operation("judge", bindings, backend_role, target, case, None)
        try:
            if answer_receipt is not lane.answer_receipt:
                raise ManagedLlmExecutionError("managed_judge_receipt_invalid")
            state = ManagedStatefulJudge(
                case=self._cases[case.case_id].public_case,
                lane=self._collector_required().issue_lane(lane.judge_binding),
            )
            capability = _issue_trusted_gold_blind_judge_capability(
                dispatcher=dispatch_judge,
                invoker=invoke_managed_stateful_judge,
                state=state,
                run_id=bindings.run_id,
                case_id=lane.lane_id,
                backend_id=f"{backend_role}-judge",
            )
            result = dispatch_judge(
                capability,
                lane.contract.judge_channel,
                backend_id=f"{backend_role}-judge",
                dispatch_ledger=self._ledger,
                answer_binding=issue_gold_blind_judge_dispatch_binding(
                    self._ledger,
                    run_id=bindings.run_id,
                    case_id=lane.lane_id,
                    backend_id=f"{backend_role}-judge",
                ),
                key=lane.judge_key,
                run_id=bindings.run_id,
                case_id=lane.lane_id,
            )
            outcome, judge_result = state.take()
            self._validate_route(outcome)
            if (
                type(result) is not dict
                or result.get("verdict") != judge_result.verdict
                or result.get("score") != judge_result.score
            ):
                raise ManagedLlmExecutionError("managed_judge_result_invalid")
            judge_result_sha256 = hashlib.sha256(canonical_dispatch_json(result)).hexdigest()
            receipt = issue_managed_judge_receipt(
                lane.receipt_issuer,
                predecessor=answer_receipt,
                outcome=outcome,
                judge_result=judge_result,
                judge_result_sha256=judge_result_sha256,
            )
            lane.judge_receipt = receipt
        except BaseException as exc:
            self._operation_failed()
            _raise_fixed(exc, "managed_execution_judge_failed")
        self._operation_succeeded()
        return receipt

    def seal_execution(
        self,
        bindings: FullComparisonRunBindings,
        manifest: tuple[FullExecutionCaseManifestEntry, ...],
        executions: tuple[ManagedCaseExecution, ...],
        manifest_sha256: str,
        material: tuple[tuple[str, str], ...],
    ) -> ManagedExecutionArtifacts:
        try:
            with self._lock:
                if (
                    self._phase != "bound"
                    or self._active
                    or self._operation_index != len(self._operation_order)
                ):
                    raise ManagedLlmExecutionError("managed_execution_coverage_incomplete")
                self._active = True
            self._require_bindings(bindings)
            if (
                type(manifest) is not tuple
                or tuple(item.case_id for item in manifest) != self._aliases
                or execution_case_manifest_sha256(manifest) != manifest_sha256
                or material != self._case_material
                or type(executions) is not tuple
                or len(executions) != len(self._lanes)
            ):
                raise ManagedLlmExecutionError("managed_execution_seal_inputs_invalid")
            expected_lanes = tuple(
                (alias, target.backend_role)
                for alias in self._aliases
                for target in bindings.backend_targets
            )
            calls = []
            quality_outcomes: list[ManagedSealedJudgeOutcome] = []
            for execution, key in zip(executions, expected_lanes, strict=True):
                lane = self._lanes[key]
                if (
                    type(execution) is not ManagedCaseExecution
                    or (
                        execution.case_id,
                        execution.backend_role,
                        execution.target_identity_sha256,
                    )
                    != (key[0], key[1], lane.target_identity_sha256)
                    or execution.retrieval_receipt is not lane.retrieval_receipt
                    or execution.answer_receipt is not lane.answer_receipt
                    or execution.judge_receipt is not lane.judge_receipt
                    or lane.retrieval_result is None
                    or lane.retrieval_metadata_sha256
                    != _retrieval_semantic_identity(
                        lane.retrieval_result,
                        lane,
                        adapter_id=self._retrieval_adapter_id,
                        implementation_sha256=self._retrieval_implementation_sha256,
                    )
                ):
                    raise ManagedLlmExecutionError("managed_execution_lane_coverage_invalid")
                sealed = seal_managed_execution_receipt(
                    lane.receipt_issuer,
                    predecessor=execution.judge_receipt,
                )
                lane_calls, proof = consume_sealed_managed_execution_receipt(
                    lane.receipt_issuer,
                    sealed,
                )
                calls.extend(lane_calls)
                quality_outcomes.append(proof)
            collected = self._collector_required().seal()
            if len(calls) != 4 * len(self._aliases) or any(
                observed is not expected
                for observed, expected in zip(calls, collected, strict=True)
            ):
                raise ManagedLlmExecutionError("managed_execution_provider_coverage_invalid")
            gold = verify_gold_blind_execution(self._ledger)
            if not self._execution_evidence_ready:
                raise ManagedLlmExecutionError("managed_execution_evidence_invalid")
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
                for role, alias in zip(
                    item.session_roles,
                    item.session_aliases,
                    strict=True,
                )
            )
            full_validation = self._execution_evidence.seal_execution_validation(
                composition_binding=self._binding,
                bindings=bindings,
                benchmark=self._cases[self._aliases[0]].public_case.benchmark,
                case_manifest=manifest,
                required_model=self._limits.answerer_model,
                required_route=self._route,
                provider_calls=collected,
                session_verifier=session_key,
                session_evidence=tuple(session_key.issue(item) for item in mappings),
            )
            artifacts = ManagedExecutionArtifacts(
                gold,
                full_validation,
                manifest_sha256,
                material,
                tuple(quality_outcomes),
            )
            with self._lock:
                self._phase = "sealed"
                self._active = False
            return artifacts
        except BaseException as exc:
            self._terminal()
            _raise_fixed(exc, "managed_execution_seal_failed")

    def _begin_operation(
        self,
        stage: str,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase | None,
    ) -> _Lane:
        try:
            with self._lock:
                if self._phase != "bound" or self._active:
                    raise ManagedLlmExecutionError("managed_execution_concurrent_or_terminal")
                self._require_bindings(bindings)
                if type(case) is not ManagedRunCase:
                    raise ManagedLlmExecutionError("managed_execution_case_invalid")
                key = (case.case_id, backend_role)
                lane = self._lanes.get(key)
                bound = self._cases.get(case.case_id)
                expected = (
                    self._operation_order[self._operation_index]
                    if self._operation_index < len(self._operation_order)
                    else None
                )
                if (
                    lane is None
                    or bound is None
                    or target != lane.target_identity_sha256
                    or case != bound.managed_case
                    or (stage != "judge" and query != bound.query)
                    or expected != (stage, case.case_id, backend_role)
                ):
                    raise ManagedLlmExecutionError("managed_execution_order_or_binding_invalid")
                self._active = True
                return lane
        except BaseException as exc:
            self._terminal()
            _raise_fixed(exc, "managed_execution_operation_rejected")

    def _operation_succeeded(self) -> None:
        with self._lock:
            if not self._active or self._phase != "bound":
                self._phase = "terminal"
                raise ManagedLlmExecutionError("managed_execution_state_invalid")
            self._operation_index += 1
            self._active = False

    def _operation_failed(self) -> None:
        self._terminal()

    def _terminal(self) -> None:
        with self._lock:
            self._phase = "terminal"
            self._active = False

    def _require_bindings(self, bindings: FullComparisonRunBindings) -> None:
        trusted = validate_full_comparison_run_bindings(bindings)
        if trusted is not self._bindings:
            raise ManagedLlmExecutionError("managed_execution_bindings_invalid")

    def _ensure_execution_evidence(
        self,
        bindings: FullComparisonRunBindings,
    ) -> None:
        if self._execution_evidence_ready:
            return
        self._execution_evidence.consume_ready_evidence(
            composition_binding=self._binding,
            bindings=bindings,
            cases=self._bound_managed_cases,
        )
        self._execution_evidence_ready = True

    def _collector_required(self) -> ManagedProviderCallCollector:
        collector = self._collector
        if type(collector) is not ManagedProviderCallCollector:
            raise ManagedLlmExecutionError("managed_execution_collector_missing")
        return collector

    def _validate_route(self, outcome: ManagedProviderCallOutcome) -> None:
        provenance = outcome.completion.provenance
        if provenance is None or provenance.route != self._route:
            raise ManagedLlmExecutionError("managed_execution_provider_route_invalid")


def create_managed_comparison_execution_ports(
    *,
    composition_binding: ManagedRunnerCompositionBinding,
    retrieval: ManagedRetrievalPort,
    execution_evidence: ManagedExecutionEvidencePort,
    retrieval_adapter_id: str,
    retrieval_implementation_sha256: str,
    provider: BoundedProviderChatCompletions,
    limits: ManagedLiveExecutionLimits,
    provider_route: ProviderRouteAttestation,
) -> ManagedComparisonExecutionPorts:
    """Create distinct runner ports backed by one exact serial authority."""

    coordinator = _ManagedExecutionCoordinator(
        composition_binding=composition_binding,
        retrieval=retrieval,
        execution_evidence=execution_evidence,
        retrieval_adapter_id=retrieval_adapter_id,
        retrieval_implementation_sha256=retrieval_implementation_sha256,
        provider=provider,
        limits=limits,
        provider_route=provider_route,
    )
    return ManagedComparisonExecutionPorts(
        ManagedComparisonCandidateExecutionPort(coordinator),
        ManagedComparisonJudgeExecutionPort(coordinator),
    )


def _answer_case(source: PublicBenchmarkCase, alias: str) -> ManagedAnswerCase:
    temporal = {
        key: value
        for key in ("question_type", "question_date", "reference_date")
        if (value := source.metadata.get(key)) is not None and type(value) in {str, int, float}
    }
    return ManagedAnswerCase(alias, source.question, temporal)


def _gold_free_prompt_case(source: PublicBenchmarkCase, alias: str) -> PublicBenchmarkCase:
    metadata = {
        key: value
        for key in (
            "category",
            "locomo_category",
            "question_type",
            "question_date",
            "reference_date",
            "reference_date_human",
        )
        if (value := source.metadata.get(key)) is not None
    }
    return PublicBenchmarkCase(
        benchmark=source.benchmark,
        case_id=alias,
        question=source.question,
        expected_terms=(),
        forbidden_terms=(),
        metadata=metadata,
    )


def _lane_id(alias: str, backend_role: str) -> str:
    return f"{alias}:{backend_role}"


def _retrieval_semantic_identity(
    result: ManagedRetrievalResult,
    lane: _Lane,
    *,
    adapter_id: str,
    implementation_sha256: str,
) -> str:
    if type(result) is not ManagedRetrievalResult:
        raise ManagedLlmExecutionError("managed_retrieval_semantics_invalid")
    evidence_identity = gold_blind_evidence_identity(result.evidence)
    if result.retrieval_identity != evidence_identity:
        raise ManagedLlmExecutionError("managed_retrieval_semantics_invalid")
    metadata = _thaw_json(result.metadata)
    if (
        type(metadata) is not dict
        or metadata.get("adapter_id") != adapter_id
        or metadata.get("backend_role") != lane.backend_role
        or metadata.get("target_identity_sha256") != lane.target_identity_sha256
        or metadata.get("retrieval_policy") != NEUTRAL_COMPARISON_RETRIEVAL_POLICY.telemetry()
        or metadata.get("gold_fields_forwarded") is not False
        or metadata.get("retries") != 0
        or lane.retrieval_implementation_sha256 != implementation_sha256
    ):
        raise ManagedLlmExecutionError("managed_retrieval_semantics_invalid")
    return hashlib.sha256(
        canonical_dispatch_json(
            {
                "adapter_implementation_sha256": lane.retrieval_implementation_sha256,
                "metadata": metadata,
            }
        )
    ).hexdigest()


def _raise_fixed(exc: BaseException, code: str) -> None:
    if isinstance(exc, Exception):
        raise ManagedLlmExecutionError(code) from None
    raise exc


__all__ = (
    "MANAGED_PRODUCTION_EXECUTION_PUBLISHABLE",
    "MANAGED_PRODUCTION_METHODOLOGY_STATUS",
    "MANAGED_RETRIEVAL_PROOF_STATUS",
    "MANAGED_SUBSCRIPTION_EXECUTION_MODEL",
    "ManagedComparisonCandidateExecutionPort",
    "ManagedComparisonExecutionPorts",
    "ManagedComparisonJudgeExecutionPort",
    "ManagedLlmExecutionError",
    "create_managed_comparison_execution_ports",
)
