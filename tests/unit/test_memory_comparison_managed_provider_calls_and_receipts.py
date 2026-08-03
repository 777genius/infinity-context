from __future__ import annotations

import hashlib
import pickle
import threading
from collections.abc import Mapping

import pytest
from infinity_context_server import memory_comparison_managed_execution_receipts as receipts
from infinity_context_server.memory_comparison_bounded_provider import (
    BoundedProviderBudget,
    BoundedProviderChatCompletions,
)
from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    GoldBlindEvidence,
    gold_blind_evidence_identity,
)
from infinity_context_server.memory_comparison_gold_blind_contract import (
    JUDGE_RESULT_SCHEMA_VERSION,
    GoldBlindJudgeResult,
)
from infinity_context_server.memory_comparison_gold_blind_run_validation import (
    canonical_dispatch_json,
)
from infinity_context_server.memory_comparison_managed_execution_receipts import (
    ManagedExecutionReceipt,
    ManagedExecutionReceiptError,
    ManagedSealedJudgeOutcome,
    consume_sealed_managed_execution_receipt,
    create_managed_execution_receipt_issuer,
    inspect_managed_retrieval_receipt_for_answer,
    issue_managed_answer_receipt,
    issue_managed_judge_receipt,
    issue_managed_retrieval_receipt,
    seal_managed_execution_receipt,
)
from infinity_context_server.memory_comparison_managed_provider_calls import (
    ManagedProviderCallError,
    ManagedProviderCallOutcome,
    ManagedProviderLaneBinding,
    create_managed_provider_call_collector,
    managed_provider_lane_bindings,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderCallProvenance,
    ProviderChatCompletion,
    ProviderRouteAttestation,
)

_COMMITMENT = "a" * 64
_TARGET = "b" * 64
_ROUTE = ProviderRouteAttestation(
    trust="official",
    origin="https://provider.example",
    endpoint_path="/v1/chat/completions",
    route_sha256="c" * 64,
    transport_evidence="direct_https",
    credential_binding_id="sha256:" + "d" * 64,
    request_method="POST",
    response_status=200,
)


class _Delegate:
    def __init__(self) -> None:
        self.calls = 0
        self.block = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.omit_provenance = False

    def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        temperature: float | None = None,
        response_format: Mapping[str, object] | None = None,
    ) -> ProviderChatCompletion:
        del system_prompt, user_prompt, max_output_tokens, temperature, response_format
        self.calls += 1
        ordinal = self.calls
        self.entered.set()
        if self.block:
            assert self.release.wait(timeout=2)
        provenance = None
        if not self.omit_provenance:
            provenance = ProviderCallProvenance(
                _ROUTE,
                model,
                model,
                f"response-{ordinal}",
                f"fingerprint-{ordinal}",
                f"{ordinal:064x}",
            )
        return ProviderChatCompletion(
            text=f"result-{ordinal}",
            prompt_tokens=1,
            completion_tokens=1,
            token_usage_source="provider_observed",
            provenance=provenance,
        )

    def close(self) -> None:
        pass


class _MaliciousBoundedProvider(BoundedProviderChatCompletions):
    pass


def test_collector_owns_exact_four_per_case_order_and_direct_provenance() -> None:
    delegate = _Delegate()
    provider = _provider(delegate, max_calls=8)
    bindings = _bindings(("case-0001", "case-0002"))
    collector = create_managed_provider_call_collector(
        provider=provider,
        bindings=bindings,
        deadline_monotonic=100.0,
        monotonic_clock=lambda: 1.0,
    )
    outcomes = tuple(_complete(collector, binding) for binding in bindings)

    calls = collector.seal()

    assert len(calls) == 8 == 4 * 2
    assert tuple((item.case_id, item.backend_role, item.stage) for item in calls) == tuple(
        (item.public_case_alias, item.backend_role, item.stage) for item in bindings
    )
    assert all(
        outcome.completion.provenance is outcome.provider_call.provenance for outcome in outcomes
    )
    assert delegate.calls == 8
    with pytest.raises(ManagedProviderCallError, match="collector_terminal"):
        collector.seal()


def test_wrong_order_retries_and_deadline_fail_before_provider() -> None:
    bindings = _bindings(("case-0001",))
    wrong_delegate = _Delegate()
    wrong = _collector(wrong_delegate, bindings)
    with pytest.raises(ManagedProviderCallError, match="lane_order_invalid"):
        wrong.issue_lane(bindings[1])
    assert wrong_delegate.calls == 0

    retry_delegate = _Delegate()
    retry = _collector(retry_delegate, bindings)
    lane = retry.issue_lane(bindings[0])
    with pytest.raises(ManagedProviderCallError, match="retries_forbidden"):
        _complete_lane(lane, retries=1)
    with pytest.raises(ManagedProviderCallError, match="lane_terminal"):
        _complete_lane(lane)
    assert retry_delegate.calls == 0

    deadline_delegate = _Delegate()
    deadline = create_managed_provider_call_collector(
        provider=_provider(deadline_delegate),
        bindings=bindings,
        deadline_monotonic=10.0,
        monotonic_clock=lambda: 10.0,
    )
    with pytest.raises(ManagedProviderCallError, match="managed_provider_deadline"):
        _complete_lane(deadline.issue_lane(bindings[0]))
    assert deadline_delegate.calls == 0


def test_one_shot_lane_rejects_concurrent_second_attempt() -> None:
    delegate = _Delegate()
    delegate.block = True
    collector = _collector(delegate, _bindings(("case-0001",)))
    lane = collector.issue_lane(_bindings(("case-0001",))[0])
    results: list[object] = []

    def call() -> None:
        try:
            results.append(_complete_lane(lane))
        except Exception as exc:
            results.append(exc)

    first = threading.Thread(target=call)
    first.start()
    assert delegate.entered.wait(timeout=2)
    second = threading.Thread(target=call)
    second.start()
    second.join(timeout=2)
    delegate.release.set()
    first.join(timeout=2)

    assert delegate.calls == 1
    assert len(results) == 2
    assert sum(type(item) is ManagedProviderCallOutcome for item in results) == 1
    assert sum(type(item) is ManagedProviderCallError for item in results) == 1


def test_missing_typed_provenance_is_terminal_and_not_reconstructed() -> None:
    delegate = _Delegate()
    delegate.omit_provenance = True
    bindings = _bindings(("case-0001",))
    collector = _collector(delegate, bindings)
    lane = collector.issue_lane(bindings[0])

    with pytest.raises(ManagedProviderCallError, match="provenance_invalid"):
        _complete_lane(lane)
    with pytest.raises(ManagedProviderCallError, match="collector_terminal"):
        collector.issue_lane(bindings[0])
    assert delegate.calls == 1


def test_receipt_chain_binds_frozen_evidence_completions_and_exact_calls() -> None:
    answer, judge = _first_lane_outcomes()
    issuer = create_managed_execution_receipt_issuer(
        answer_binding=answer.binding,
        judge_binding=judge.binding,
        target_identity_sha256=_TARGET,
    )
    evidence = _evidence()
    identity = gold_blind_evidence_identity(evidence)
    retrieved = issue_managed_retrieval_receipt(
        issuer,
        evidence=evidence,
        retrieval_identity=identity,
    )

    view = inspect_managed_retrieval_receipt_for_answer(issuer, retrieved)
    answered = issue_managed_answer_receipt(
        issuer,
        predecessor=retrieved,
        outcome=answer,
        answer_result_identity="e" * 64,
    )
    judge_result = _judge_result("partial", 0.4)
    judged = issue_managed_judge_receipt(
        issuer,
        predecessor=answered,
        outcome=judge,
        judge_result=judge_result,
        judge_result_sha256=_judge_result_sha256(judge_result),
    )
    sealed = seal_managed_execution_receipt(issuer, predecessor=judged)
    calls, proof = consume_sealed_managed_execution_receipt(issuer, sealed)

    assert view.evidence == evidence
    assert view.evidence is not evidence
    assert view.retrieval_identity == identity
    assert calls == (answer.provider_call, judge.provider_call)
    assert repr(sealed) == "ManagedExecutionReceipt(<redacted>)"
    assert repr(proof) == "ManagedSealedJudgeOutcome(<opaque>)"
    with pytest.raises(TypeError, match="nonserializable"):
        pickle.dumps(proof)
    with pytest.raises(ManagedExecutionReceiptError, match="predecessor_invalid"):
        consume_sealed_managed_execution_receipt(issuer, sealed)


def test_receipts_reject_forgery_serialization_wrong_predecessor_and_replay() -> None:
    answer, judge = _first_lane_outcomes()
    first = create_managed_execution_receipt_issuer(
        answer_binding=answer.binding,
        judge_binding=judge.binding,
        target_identity_sha256=_TARGET,
    )
    second = create_managed_execution_receipt_issuer(
        answer_binding=answer.binding,
        judge_binding=judge.binding,
        target_identity_sha256=_TARGET,
    )
    evidence = _evidence()
    retrieved = issue_managed_retrieval_receipt(
        first,
        evidence=evidence,
        retrieval_identity=gold_blind_evidence_identity(evidence),
    )
    second_retrieved = issue_managed_retrieval_receipt(
        second,
        evidence=evidence,
        retrieval_identity=gold_blind_evidence_identity(evidence),
    )

    with pytest.raises(ManagedExecutionReceiptError, match="forged"):
        ManagedExecutionReceipt(_token=object())
    with pytest.raises(TypeError, match="nonserializable"):
        pickle.dumps(retrieved)
    with pytest.raises(ManagedExecutionReceiptError, match="predecessor_invalid"):
        issue_managed_answer_receipt(
            first,
            predecessor=second_retrieved,
            outcome=answer,
            answer_result_identity="e" * 64,
        )

    answered = issue_managed_answer_receipt(
        first,
        predecessor=retrieved,
        outcome=answer,
        answer_result_identity="e" * 64,
    )
    with pytest.raises(ManagedExecutionReceiptError, match="predecessor_invalid"):
        issue_managed_answer_receipt(
            first,
            predecessor=retrieved,
            outcome=answer,
            answer_result_identity="e" * 64,
        )
    assert type(answered) is ManagedExecutionReceipt


def test_receipt_detects_evidence_and_provider_completion_mutation() -> None:
    answer, judge = _first_lane_outcomes()
    issuer = create_managed_execution_receipt_issuer(
        answer_binding=answer.binding,
        judge_binding=judge.binding,
        target_identity_sha256=_TARGET,
    )
    evidence = _evidence()
    retrieved = issue_managed_retrieval_receipt(
        issuer,
        evidence=evidence,
        retrieval_identity=gold_blind_evidence_identity(evidence),
    )
    object.__setattr__(evidence[0], "text", "mutated")
    with pytest.raises(ManagedExecutionReceiptError, match="mutated"):
        inspect_managed_retrieval_receipt_for_answer(issuer, retrieved)

    issuer = create_managed_execution_receipt_issuer(
        answer_binding=answer.binding,
        judge_binding=judge.binding,
        target_identity_sha256=_TARGET,
    )
    clean = _evidence()
    retrieved = issue_managed_retrieval_receipt(
        issuer,
        evidence=clean,
        retrieval_identity=gold_blind_evidence_identity(clean),
    )
    answered = issue_managed_answer_receipt(
        issuer,
        predecessor=retrieved,
        outcome=answer,
        answer_result_identity="e" * 64,
    )
    object.__setattr__(answer.completion, "text", "mutated")
    with pytest.raises(ManagedExecutionReceiptError, match="mutated"):
        issue_managed_judge_receipt(
            issuer,
            predecessor=answered,
            outcome=judge,
            judge_result=_judge_result("correct", 1.0),
            judge_result_sha256=_judge_result_sha256(_judge_result("correct", 1.0)),
        )


def test_issuer_rejects_post_issue_binding_and_target_mutation() -> None:
    answer, judge = _first_lane_outcomes()
    issuer = create_managed_execution_receipt_issuer(
        answer_binding=answer.binding,
        judge_binding=judge.binding,
        target_identity_sha256=_TARGET,
    )
    object.__setattr__(answer.binding, "model", "tampered-model")
    with pytest.raises(ManagedExecutionReceiptError, match="binding_mutated"):
        issue_managed_retrieval_receipt(
            issuer,
            evidence=_evidence(),
            retrieval_identity=gold_blind_evidence_identity(_evidence()),
        )

    answer, judge = _first_lane_outcomes()
    issuer = create_managed_execution_receipt_issuer(
        answer_binding=answer.binding,
        judge_binding=judge.binding,
        target_identity_sha256=_TARGET,
    )
    object.__setattr__(receipts._ISSUERS[issuer], "target_identity_sha256", "f" * 64)
    with pytest.raises(ManagedExecutionReceiptError, match="binding_mutated"):
        issue_managed_retrieval_receipt(
            issuer,
            evidence=_evidence(),
            retrieval_identity=gold_blind_evidence_identity(_evidence()),
        )


def test_judge_result_receipt_and_proof_reject_tampering_and_forgery() -> None:
    answer, judge = _first_lane_outcomes()
    issuer = create_managed_execution_receipt_issuer(
        answer_binding=answer.binding,
        judge_binding=judge.binding,
        target_identity_sha256=_TARGET,
    )
    evidence = _evidence()
    retrieved = issue_managed_retrieval_receipt(
        issuer,
        evidence=evidence,
        retrieval_identity=gold_blind_evidence_identity(evidence),
    )
    answered = issue_managed_answer_receipt(
        issuer,
        predecessor=retrieved,
        outcome=answer,
        answer_result_identity="e" * 64,
    )
    result = _judge_result("correct", 0.6)
    judged = issue_managed_judge_receipt(
        issuer,
        predecessor=answered,
        outcome=judge,
        judge_result=result,
        judge_result_sha256=_judge_result_sha256(result),
    )
    state = receipts._RECEIPTS[judged]
    assert state.judge_outcome is not None
    object.__setattr__(state.judge_outcome, "score", 0.2)
    changed = _judge_result("correct", 0.2)
    object.__setattr__(
        state.judge_outcome,
        "judge_result_sha256",
        _judge_result_sha256(changed),
    )
    with pytest.raises(ManagedExecutionReceiptError, match="mutated"):
        seal_managed_execution_receipt(issuer, predecessor=judged)
    with pytest.raises(ManagedExecutionReceiptError, match="forged"):
        ManagedSealedJudgeOutcome(_token=object())


def test_judge_receipt_rejects_noncanonical_result_hash() -> None:
    answer, judge = _first_lane_outcomes()
    issuer = create_managed_execution_receipt_issuer(
        answer_binding=answer.binding,
        judge_binding=judge.binding,
        target_identity_sha256=_TARGET,
    )
    evidence = _evidence()
    retrieved = issue_managed_retrieval_receipt(
        issuer,
        evidence=evidence,
        retrieval_identity=gold_blind_evidence_identity(evidence),
    )
    answered = issue_managed_answer_receipt(
        issuer,
        predecessor=retrieved,
        outcome=answer,
        answer_result_identity="e" * 64,
    )
    with pytest.raises(ManagedExecutionReceiptError, match="identity_invalid"):
        issue_managed_judge_receipt(
            issuer,
            predecessor=answered,
            outcome=judge,
            judge_result=_judge_result("abstain", 0.3),
            judge_result_sha256="f" * 64,
        )


def test_collector_rejects_subclass_deadline_crossing_and_plan_tamper() -> None:
    bindings = _bindings(("case-0001",))
    delegate = _Delegate()
    safe = _provider(delegate)
    malicious = _MaliciousBoundedProvider(
        delegate=delegate,
        budget=BoundedProviderBudget(
            max_total_tokens=100,
            max_calls=4,
            max_output_tokens_per_call=4,
            deadline_monotonic=100.0,
        ),
        input_token_estimator=lambda _text: 1,
        monotonic_clock=lambda: 1.0,
    )
    with pytest.raises(ManagedProviderCallError, match="transport_invalid"):
        create_managed_provider_call_collector(
            provider=malicious,
            bindings=bindings,
            deadline_monotonic=100.0,
            monotonic_clock=lambda: 1.0,
        )

    clock_values = iter((1.0, 11.0))
    crossing = create_managed_provider_call_collector(
        provider=safe,
        bindings=bindings,
        deadline_monotonic=10.0,
        monotonic_clock=lambda: next(clock_values),
    )
    with pytest.raises(ManagedProviderCallError, match="managed_provider_deadline"):
        _complete_lane(crossing.issue_lane(bindings[0]))
    assert delegate.calls == 1

    fresh_bindings = _bindings(("case-0001",))
    protected = _collector(_Delegate(), fresh_bindings)
    object.__setattr__(fresh_bindings[0], "model", "tampered-model")
    with pytest.raises(ManagedProviderCallError, match="lane_order_invalid"):
        protected.issue_lane(fresh_bindings[0])
    assert protected.issue_lane(_bindings(("case-0001",))[0]).binding.model == "answer-model"

    internal = _collector(_Delegate(), _bindings(("case-0001",)))
    object.__setattr__(internal._expected[0], "model", "tampered-model")
    with pytest.raises(ManagedProviderCallError, match="plan_mutated"):
        internal.issue_lane(_bindings(("case-0001",))[0])


def test_receipt_transition_has_one_concurrent_winner() -> None:
    answer, judge = _first_lane_outcomes()
    issuer = create_managed_execution_receipt_issuer(
        answer_binding=answer.binding,
        judge_binding=judge.binding,
        target_identity_sha256=_TARGET,
    )
    evidence = _evidence()
    retrieved = issue_managed_retrieval_receipt(
        issuer,
        evidence=evidence,
        retrieval_identity=gold_blind_evidence_identity(evidence),
    )
    barrier = threading.Barrier(2)
    results: list[object] = []
    result_lock = threading.Lock()

    def bind() -> None:
        barrier.wait(timeout=2)
        try:
            result: object = issue_managed_answer_receipt(
                issuer,
                predecessor=retrieved,
                outcome=answer,
                answer_result_identity="e" * 64,
            )
        except Exception as exc:
            result = exc
        with result_lock:
            results.append(result)

    threads = (threading.Thread(target=bind), threading.Thread(target=bind))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert sum(type(item) is ManagedExecutionReceipt for item in results) == 1
    assert sum(type(item) is ManagedExecutionReceiptError for item in results) == 1


def _first_lane_outcomes() -> tuple[ManagedProviderCallOutcome, ManagedProviderCallOutcome]:
    delegate = _Delegate()
    bindings = _bindings(("case-0001",))
    collector = _collector(delegate, bindings)
    return _complete(collector, bindings[0]), _complete(collector, bindings[1])


def _bindings(aliases: tuple[str, ...]) -> tuple[ManagedProviderLaneBinding, ...]:
    return managed_provider_lane_bindings(
        comparison_commitment_sha256=_COMMITMENT,
        run_id="run-1",
        profile_id="profile-1",
        public_case_aliases=aliases,
        backend_roles=("infinity-context", "mem0"),
        answerer_model="answer-model",
        judge_model="judge-model",
    )


def _provider(delegate: _Delegate, *, max_calls: int = 4) -> BoundedProviderChatCompletions:
    return BoundedProviderChatCompletions(
        delegate=delegate,
        budget=BoundedProviderBudget(
            max_total_tokens=100,
            max_calls=max_calls,
            max_output_tokens_per_call=4,
            deadline_monotonic=100.0,
        ),
        input_token_estimator=lambda _text: 1,
        monotonic_clock=lambda: 1.0,
    )


def _collector(
    delegate: _Delegate,
    bindings: tuple[ManagedProviderLaneBinding, ...],
):
    return create_managed_provider_call_collector(
        provider=_provider(delegate, max_calls=len(bindings)),
        bindings=bindings,
        deadline_monotonic=100.0,
        monotonic_clock=lambda: 1.0,
    )


def _complete(collector, binding: ManagedProviderLaneBinding) -> ManagedProviderCallOutcome:
    return _complete_lane(collector.issue_lane(binding))


def _complete_lane(lane, *, retries: int = 0) -> ManagedProviderCallOutcome:
    return lane.complete(
        system_prompt="system",
        user_prompt="user",
        max_output_tokens=2,
        retries=retries,
    )


def _evidence() -> tuple[GoldBlindEvidence, ...]:
    return (GoldBlindEvidence("memory-1", "retrieved evidence", 1, None),)


def _judge_result(verdict: str, score: float) -> GoldBlindJudgeResult:
    return GoldBlindJudgeResult(verdict=verdict, score=score)


def _judge_result_sha256(result: GoldBlindJudgeResult) -> str:
    return hashlib.sha256(
        canonical_dispatch_json(
            {
                "schema_version": JUDGE_RESULT_SCHEMA_VERSION,
                "score": result.score,
                "verdict": result.verdict,
            }
        )
    ).hexdigest()
