"""Opaque execution receipt chain for managed comparison lanes."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import weakref
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionProviderCall,
)
from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    GoldBlindEvidence,
    gold_blind_evidence_identity,
    validate_gold_blind_evidence,
)
from infinity_context_server.memory_comparison_gold_blind_contract import (
    JUDGE_RESULT_SCHEMA_VERSION,
    GoldBlindJudgeResult,
)
from infinity_context_server.memory_comparison_gold_blind_run_validation import (
    canonical_dispatch_json,
)
from infinity_context_server.memory_comparison_managed_provider_calls import (
    ManagedProviderCallOutcome,
    ManagedProviderLaneBinding,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderCallProvenance,
    ProviderChatCompletion,
    ProviderRouteAttestation,
)

_TOKEN = object()
_LOCK = threading.RLock()
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManagedExecutionReceiptError(RuntimeError):
    """Fixed-code receipt failure without evidence or provider text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedExecutionReceiptIssuer:
    """Opaque lane-scoped authority for one complete receipt chain."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedExecutionReceiptError("managed_receipt_issuer_forged")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedExecutionReceiptIssuer is final")

    def __repr__(self) -> str:
        return "ManagedExecutionReceiptIssuer(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedExecutionReceiptIssuer is nonserializable")


@final
class ManagedExecutionReceipt:
    """Opaque HMAC and object-identity receipt; all payload stays external."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedExecutionReceiptError("managed_execution_receipt_forged")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedExecutionReceipt is final")

    def __repr__(self) -> str:
        return "ManagedExecutionReceipt(<redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedExecutionReceipt is nonserializable")


@final
class ManagedSealedJudgeOutcome:
    """Opaque one-shot proof derived only while consuming a sealed receipt."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedExecutionReceiptError("managed_sealed_judge_outcome_forged")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedSealedJudgeOutcome is final")

    def __repr__(self) -> str:
        return "ManagedSealedJudgeOutcome(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedSealedJudgeOutcome is nonserializable")


@final
@dataclass(frozen=True, slots=True)
class ManagedRetrievalEvidenceView:
    """Fresh immutable evidence copies returned only to the answer binder."""

    evidence: tuple[GoldBlindEvidence, ...]
    retrieval_identity: str

    def __post_init__(self) -> None:
        validate_gold_blind_evidence(self.evidence)
        _digest(self.retrieval_identity)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedRetrievalEvidenceView is final")


@dataclass(frozen=True, slots=True)
class _LaneBindingSnapshot:
    comparison_commitment_sha256: str
    run_id: str
    profile_id: str
    public_case_alias: str
    backend_role: str
    stage: str
    model: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class _IssuerBindingSnapshot:
    answer: _LaneBindingSnapshot
    judge: _LaneBindingSnapshot
    target_identity_sha256: str


@dataclass(slots=True)
class _IssuerState:
    answer_binding: ManagedProviderLaneBinding
    judge_binding: ManagedProviderLaneBinding
    target_identity_sha256: str
    binding_snapshot: _IssuerBindingSnapshot
    secret: bytes
    phase: str
    current: ManagedExecutionReceipt | None


@dataclass(frozen=True, slots=True)
class _JudgeOutcomeSnapshot:
    case_alias: str
    backend_role: str
    verdict: str
    score: float
    judge_result_sha256: str


@dataclass(slots=True)
class _SealedJudgeOutcomeState:
    issuer: ManagedExecutionReceiptIssuer
    receipt_commitment: str
    snapshot: _JudgeOutcomeSnapshot
    comparison_commitment_sha256: str
    commitment: str
    phase: str


@dataclass(slots=True)
class _ReceiptState:
    issuer: ManagedExecutionReceiptIssuer
    stage: str
    predecessor_commitment: str
    evidence: tuple[GoldBlindEvidence, ...] | None
    evidence_snapshot: tuple[tuple[str, str, int, str | None], ...] | None
    retrieval_identity: str
    result_identity: str
    outcomes: tuple[ManagedProviderCallOutcome, ...]
    outcome_snapshots: tuple[str, ...]
    commitment: str
    phase: str
    judge_outcome: _JudgeOutcomeSnapshot | None = None


_ISSUERS: weakref.WeakKeyDictionary[ManagedExecutionReceiptIssuer, _IssuerState] = (
    weakref.WeakKeyDictionary()
)
_RECEIPTS: weakref.WeakKeyDictionary[ManagedExecutionReceipt, _ReceiptState] = (
    weakref.WeakKeyDictionary()
)
_SEALED_JUDGE_OUTCOMES: weakref.WeakKeyDictionary[
    ManagedSealedJudgeOutcome, _SealedJudgeOutcomeState
] = weakref.WeakKeyDictionary()


def create_managed_execution_receipt_issuer(
    *,
    answer_binding: ManagedProviderLaneBinding,
    judge_binding: ManagedProviderLaneBinding,
    target_identity_sha256: str,
) -> ManagedExecutionReceiptIssuer:
    """Bind one issuer to one adjacent answerer and judge provider lane pair."""

    answer, judge = _validate_binding_pair(answer_binding, judge_binding)
    target = _digest(target_identity_sha256)
    issuer = ManagedExecutionReceiptIssuer(_token=_TOKEN)
    with _LOCK:
        _ISSUERS[issuer] = _IssuerState(
            answer_binding=answer,
            judge_binding=judge,
            target_identity_sha256=target,
            binding_snapshot=_issuer_binding_snapshot(answer, judge, target),
            secret=secrets.token_bytes(32),
            phase="new",
            current=None,
        )
    return issuer


def issue_managed_retrieval_receipt(
    issuer: ManagedExecutionReceiptIssuer,
    *,
    evidence: tuple[GoldBlindEvidence, ...],
    retrieval_identity: str,
) -> ManagedExecutionReceipt:
    """Issue retrieved stage from exact frozen GoldBlindEvidence."""

    state = _issuer(issuer)
    snapshot = validate_gold_blind_evidence(evidence)
    _digest(retrieval_identity)
    if not hmac.compare_digest(gold_blind_evidence_identity(evidence), retrieval_identity):
        raise ManagedExecutionReceiptError("managed_retrieval_identity_mismatch")
    with _LOCK:
        if state.phase != "new" or state.current is not None:
            raise ManagedExecutionReceiptError("managed_receipt_transition_replay")
        state.phase = "retrieval-issuing"
    try:
        receipt = _new_receipt(
            issuer,
            state,
            stage="retrieved",
            predecessor_commitment="",
            evidence=evidence,
            evidence_snapshot=snapshot,
            retrieval_identity=retrieval_identity,
            result_identity="",
            outcomes=(),
            judge_outcome=None,
        )
    except BaseException:
        _terminal(state)
        raise
    with _LOCK:
        state.current = receipt
        state.phase = "retrieved"
    return receipt


def inspect_managed_retrieval_receipt_for_answer(
    issuer: ManagedExecutionReceiptIssuer,
    receipt: ManagedExecutionReceipt,
) -> ManagedRetrievalEvidenceView:
    """Revalidate and copy retrieval evidence for answer prompt binding."""

    state = _issuer(issuer)
    with _LOCK:
        current = _receipt(receipt)
        if (
            state.phase != "retrieved"
            or state.current is not receipt
            or current.issuer is not issuer
            or current.stage != "retrieved"
            or current.phase != "live"
        ):
            raise ManagedExecutionReceiptError("managed_receipt_predecessor_invalid")
        _validate_receipt(current, state)
        snapshot = current.evidence_snapshot
    if snapshot is None:
        raise ManagedExecutionReceiptError("managed_retrieval_evidence_missing")
    return ManagedRetrievalEvidenceView(
        tuple(GoldBlindEvidence(*item) for item in snapshot),
        current.retrieval_identity,
    )


def issue_managed_answer_receipt(
    issuer: ManagedExecutionReceiptIssuer,
    *,
    predecessor: ManagedExecutionReceipt,
    outcome: ManagedProviderCallOutcome,
    answer_result_identity: str,
) -> ManagedExecutionReceipt:
    """Bind answer completion/result to the exact retrieved predecessor."""

    return _advance(
        issuer,
        predecessor=predecessor,
        expected_phase="retrieved",
        next_stage="answer-bound",
        outcome=outcome,
        result_identity=answer_result_identity,
    )


def issue_managed_judge_receipt(
    issuer: ManagedExecutionReceiptIssuer,
    *,
    predecessor: ManagedExecutionReceipt,
    outcome: ManagedProviderCallOutcome,
    judge_result: GoldBlindJudgeResult,
    judge_result_sha256: str,
) -> ManagedExecutionReceipt:
    """Bind an exact canonical GoldBlind judge result to the answer receipt."""

    state = _issuer(issuer)
    snapshot = _judge_outcome_snapshot(
        state,
        judge_result=judge_result,
        judge_result_sha256=judge_result_sha256,
    )

    return _advance(
        issuer,
        predecessor=predecessor,
        expected_phase="answer-bound",
        next_stage="judge-bound",
        outcome=outcome,
        result_identity=judge_result_sha256,
        judge_outcome=snapshot,
    )


def seal_managed_execution_receipt(
    issuer: ManagedExecutionReceiptIssuer,
    *,
    predecessor: ManagedExecutionReceipt,
) -> ManagedExecutionReceipt:
    """Consume judge-bound predecessor and issue one sealed receipt."""

    state, previous = _begin(issuer, predecessor, "judge-bound", "sealing")
    try:
        receipt = _new_receipt(
            issuer,
            state,
            stage="sealed",
            predecessor_commitment=previous.commitment,
            evidence=None,
            evidence_snapshot=None,
            retrieval_identity=previous.retrieval_identity,
            result_identity=previous.result_identity,
            outcomes=previous.outcomes,
            judge_outcome=previous.judge_outcome,
        )
    except BaseException:
        _abort(state, previous)
        raise
    _finish(state, previous, receipt, "sealed")
    return receipt


def consume_sealed_managed_execution_receipt(
    issuer: ManagedExecutionReceiptIssuer,
    receipt: ManagedExecutionReceipt,
) -> tuple[
    tuple[FullExecutionProviderCall, FullExecutionProviderCall],
    ManagedSealedJudgeOutcome,
]:
    """Consume once, returning exact calls and an opaque judge-outcome proof."""

    state, sealed = _begin(issuer, receipt, "sealed", "consuming")
    try:
        calls = tuple(item.provider_call for item in sealed.outcomes)
        if len(calls) != 2 or calls[0].stage != "answerer" or calls[1].stage != "judge":
            raise ManagedExecutionReceiptError("managed_receipt_call_coverage_invalid")
        snapshot = _validated_judge_outcome_snapshot(sealed.judge_outcome, state)
        proof = ManagedSealedJudgeOutcome(_token=_TOKEN)
        comparison_commitment_sha256 = (
            state.binding_snapshot.answer.comparison_commitment_sha256
        )
        proof_state = _SealedJudgeOutcomeState(
            issuer=issuer,
            receipt_commitment=sealed.commitment,
            snapshot=snapshot,
            comparison_commitment_sha256=comparison_commitment_sha256,
            commitment=hmac.new(
                state.secret,
                _sealed_judge_outcome_material(
                    sealed.commitment,
                    snapshot,
                    comparison_commitment_sha256,
                ),
                hashlib.sha256,
            ).hexdigest(),
            phase="issued",
        )
    except BaseException:
        _abort(state, sealed)
        raise
    with _LOCK:
        sealed.phase = "consumed"
        state.phase = "consumed"
        state.current = None
        _SEALED_JUDGE_OUTCOMES[proof] = proof_state
    return calls, proof  # type: ignore[return-value]


def _advance(
    issuer: ManagedExecutionReceiptIssuer,
    *,
    predecessor: ManagedExecutionReceipt,
    expected_phase: str,
    next_stage: str,
    outcome: ManagedProviderCallOutcome,
    result_identity: str,
    judge_outcome: _JudgeOutcomeSnapshot | None = None,
) -> ManagedExecutionReceipt:
    state, previous = _begin(issuer, predecessor, expected_phase, f"{next_stage}-issuing")
    try:
        expected = (
            state.binding_snapshot.answer
            if next_stage == "answer-bound"
            else state.binding_snapshot.judge
        )
        _validate_outcome(outcome, expected)
        _digest(result_identity)
        if next_stage == "judge-bound":
            _validated_judge_outcome_snapshot(judge_outcome, state)
        elif judge_outcome is not None:
            raise ManagedExecutionReceiptError("managed_receipt_judge_outcome_invalid")
        receipt = _new_receipt(
            issuer,
            state,
            stage=next_stage,
            predecessor_commitment=previous.commitment,
            evidence=None,
            evidence_snapshot=None,
            retrieval_identity=previous.retrieval_identity,
            result_identity=result_identity,
            outcomes=(*previous.outcomes, outcome),
            judge_outcome=judge_outcome,
        )
    except BaseException:
        _abort(state, previous)
        raise
    _finish(state, previous, receipt, next_stage)
    return receipt


def _begin(
    issuer: ManagedExecutionReceiptIssuer,
    predecessor: ManagedExecutionReceipt,
    expected_phase: str,
    transient_phase: str,
) -> tuple[_IssuerState, _ReceiptState]:
    state = _issuer(issuer)
    with _LOCK:
        previous = _receipt(predecessor)
        if (
            state.phase != expected_phase
            or state.current is not predecessor
            or previous.issuer is not issuer
            or previous.stage != expected_phase
            or previous.phase != "live"
        ):
            raise ManagedExecutionReceiptError("managed_receipt_predecessor_invalid")
        _validate_receipt(previous, state)
        state.phase = transient_phase
        previous.phase = "consuming"
        return state, previous


def _finish(
    state: _IssuerState,
    previous: _ReceiptState,
    receipt: ManagedExecutionReceipt,
    phase: str,
) -> None:
    with _LOCK:
        if previous.phase != "consuming":
            _terminal(state)
            raise ManagedExecutionReceiptError("managed_receipt_concurrent_transition")
        previous.phase = "consumed"
        state.current = receipt
        state.phase = phase


def _abort(state: _IssuerState, previous: _ReceiptState) -> None:
    with _LOCK:
        previous.phase = "terminal"
        _terminal(state)


def _terminal(state: _IssuerState) -> None:
    state.phase = "terminal"
    state.current = None


def _new_receipt(
    issuer: ManagedExecutionReceiptIssuer,
    state: _IssuerState,
    *,
    stage: str,
    predecessor_commitment: str,
    evidence: tuple[GoldBlindEvidence, ...] | None,
    evidence_snapshot: tuple[tuple[str, str, int, str | None], ...] | None,
    retrieval_identity: str,
    result_identity: str,
    outcomes: tuple[ManagedProviderCallOutcome, ...],
    judge_outcome: _JudgeOutcomeSnapshot | None,
) -> ManagedExecutionReceipt:
    snapshots = tuple(_outcome_snapshot(item) for item in outcomes)
    material = _material(
        state,
        stage,
        predecessor_commitment,
        retrieval_identity,
        result_identity,
        snapshots,
        judge_outcome,
    )
    receipt = ManagedExecutionReceipt(_token=_TOKEN)
    record = _ReceiptState(
        issuer,
        stage,
        predecessor_commitment,
        evidence,
        evidence_snapshot,
        retrieval_identity,
        result_identity,
        outcomes,
        snapshots,
        hmac.new(state.secret, material, hashlib.sha256).hexdigest(),
        "live",
        judge_outcome,
    )
    with _LOCK:
        _RECEIPTS[receipt] = record
    return receipt


def _validate_receipt(receipt: _ReceiptState, issuer: _IssuerState) -> None:
    _validate_live_issuer_bindings(issuer)
    if receipt.evidence is not None:
        current_evidence = validate_gold_blind_evidence(receipt.evidence)
        if current_evidence != receipt.evidence_snapshot:
            raise ManagedExecutionReceiptError("managed_receipt_mutated")
    snapshots = tuple(_outcome_snapshot(item) for item in receipt.outcomes)
    if receipt.stage in {"judge-bound", "sealed"}:
        _validated_judge_outcome_snapshot(receipt.judge_outcome, issuer)
    elif receipt.judge_outcome is not None:
        raise ManagedExecutionReceiptError("managed_receipt_mutated")
    expected = hmac.new(
        issuer.secret,
        _material(
            issuer,
            receipt.stage,
            receipt.predecessor_commitment,
            receipt.retrieval_identity,
            receipt.result_identity,
            snapshots,
            receipt.judge_outcome,
        ),
        hashlib.sha256,
    ).hexdigest()
    if snapshots != receipt.outcome_snapshots or not hmac.compare_digest(
        expected, receipt.commitment
    ):
        raise ManagedExecutionReceiptError("managed_receipt_mutated")


def _validate_outcome(
    outcome: object, expected: _LaneBindingSnapshot
) -> ManagedProviderCallOutcome:
    if type(outcome) is not ManagedProviderCallOutcome:
        raise ManagedExecutionReceiptError("managed_receipt_outcome_invalid")
    outcome.__post_init__()
    call = outcome.provider_call
    if (
        _binding_snapshot(outcome.binding) != expected
        or call.comparison_commitment_sha256 != expected.comparison_commitment_sha256
        or call.run_id != expected.run_id
        or call.profile_id != expected.profile_id
        or call.case_id != expected.public_case_alias
        or call.backend_role != expected.backend_role
        or call.stage != expected.stage
        or call.provenance is not outcome.completion.provenance
    ):
        raise ManagedExecutionReceiptError("managed_receipt_outcome_binding_invalid")
    _outcome_snapshot(outcome)
    return outcome


def _outcome_snapshot(outcome: ManagedProviderCallOutcome) -> str:
    outcome.__post_init__()
    completion = outcome.completion
    call = outcome.provider_call
    provenance = call.provenance
    if (
        type(completion) is not ProviderChatCompletion
        or type(call) is not FullExecutionProviderCall
        or type(provenance) is not ProviderCallProvenance
        or type(provenance.route) is not ProviderRouteAttestation
        or completion.provenance is not provenance
    ):
        raise ManagedExecutionReceiptError("managed_receipt_outcome_invalid")
    call.__post_init__()
    route = provenance.route
    payload = {
        "binding": [
            outcome.binding.comparison_commitment_sha256,
            outcome.binding.run_id,
            outcome.binding.profile_id,
            outcome.binding.public_case_alias,
            outcome.binding.backend_role,
            outcome.binding.stage,
            outcome.binding.model,
            outcome.binding.ordinal,
        ],
        "completion": [
            completion.text,
            completion.prompt_tokens,
            completion.completion_tokens,
            completion.token_usage_source,
            completion.finish_reason,
            completion.finish_reason_source,
        ],
        "call": [
            call.comparison_commitment_sha256,
            call.run_id,
            call.profile_id,
            call.case_id,
            call.backend_role,
            call.stage,
            call.pending,
        ],
        "provenance": [
            route.trust,
            route.origin,
            route.endpoint_path,
            route.route_sha256,
            route.transport_evidence,
            route.credential_binding_id,
            route.request_method,
            route.response_status,
            provenance.requested_model,
            provenance.observed_model,
            provenance.response_id,
            provenance.system_fingerprint,
            provenance.request_sha256,
        ],
        "identities": [id(completion), id(provenance), id(call)],
    }
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _material(
    state: _IssuerState,
    stage: str,
    predecessor: str,
    retrieval_identity: str,
    result_identity: str,
    outcome_snapshots: tuple[str, ...],
    judge_outcome: _JudgeOutcomeSnapshot | None,
) -> bytes:
    bindings = state.binding_snapshot
    return _canonical(
        {
            "bindings": {
                "answer": _binding_material(bindings.answer),
                "judge": _binding_material(bindings.judge),
                "target_identity_sha256": bindings.target_identity_sha256,
            },
            "stage": stage,
            "predecessor": predecessor,
            "retrieval_identity": retrieval_identity,
            "result_identity": result_identity,
            "outcomes": list(outcome_snapshots),
            "judge_outcome": _judge_outcome_material(judge_outcome),
        }
    )


def _judge_outcome_snapshot(
    state: _IssuerState,
    *,
    judge_result: object,
    judge_result_sha256: object,
) -> _JudgeOutcomeSnapshot:
    if type(judge_result) is not GoldBlindJudgeResult:
        raise ManagedExecutionReceiptError("managed_receipt_judge_result_invalid")
    try:
        judge_result.__post_init__()
    except Exception:
        raise ManagedExecutionReceiptError("managed_receipt_judge_result_invalid") from None
    digest = _digest(judge_result_sha256)
    expected = _canonical_judge_result_sha256(judge_result)
    if not hmac.compare_digest(digest, expected):
        raise ManagedExecutionReceiptError("managed_receipt_judge_result_identity_invalid")
    binding = state.binding_snapshot.judge
    return _JudgeOutcomeSnapshot(
        case_alias=binding.public_case_alias,
        backend_role=binding.backend_role,
        verdict=judge_result.verdict,
        score=judge_result.score,
        judge_result_sha256=digest,
    )


def _validated_judge_outcome_snapshot(
    value: object,
    state: _IssuerState,
) -> _JudgeOutcomeSnapshot:
    if type(value) is not _JudgeOutcomeSnapshot:
        raise ManagedExecutionReceiptError("managed_receipt_judge_outcome_invalid")
    binding = state.binding_snapshot.judge
    if value.case_alias != binding.public_case_alias or value.backend_role != binding.backend_role:
        raise ManagedExecutionReceiptError("managed_receipt_judge_outcome_invalid")
    try:
        result = GoldBlindJudgeResult(value.verdict, value.score)
    except Exception:
        raise ManagedExecutionReceiptError("managed_receipt_judge_outcome_invalid") from None
    expected = _canonical_judge_result_sha256(result)
    if not hmac.compare_digest(value.judge_result_sha256, expected):
        raise ManagedExecutionReceiptError("managed_receipt_judge_outcome_invalid")
    return value


def _canonical_judge_result_sha256(result: GoldBlindJudgeResult) -> str:
    try:
        payload = canonical_dispatch_json(
            {
                "schema_version": JUDGE_RESULT_SCHEMA_VERSION,
                "score": result.score,
                "verdict": result.verdict,
            }
        )
    except Exception:
        raise ManagedExecutionReceiptError("managed_receipt_judge_result_invalid") from None
    return hashlib.sha256(payload).hexdigest()


def _judge_outcome_material(value: _JudgeOutcomeSnapshot | None) -> object:
    if value is None:
        return None
    return [
        value.case_alias,
        value.backend_role,
        value.verdict,
        value.score,
        value.judge_result_sha256,
    ]


def _sealed_judge_outcome_material(
    receipt_commitment: str,
    snapshot: _JudgeOutcomeSnapshot,
    comparison_commitment_sha256: str,
) -> bytes:
    return _canonical(
        {
            "receipt_commitment": receipt_commitment,
            "schema_version": "managed-sealed-judge-outcome.v1",
            "comparison_commitment_sha256": comparison_commitment_sha256,
            "judge_outcome": _judge_outcome_material(snapshot),
        }
    )


def consume_managed_sealed_judge_outcomes(
    proofs: object,
    *,
    binding_commitment_sha256: object,
    expected_lanes: object,
) -> tuple[_JudgeOutcomeSnapshot, ...]:
    """Consume exact receipt-issued proofs after manifest lane validation."""

    commitment = _digest(binding_commitment_sha256)
    if (
        type(proofs) is not tuple
        or type(expected_lanes) is not tuple
        or not expected_lanes
        or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not str
            for item in expected_lanes
        )
        or len(set(expected_lanes)) != len(expected_lanes)
    ):
        raise ManagedExecutionReceiptError("managed_sealed_judge_outcome_input_invalid")
    with _LOCK:
        states: list[_SealedJudgeOutcomeState] = []
        snapshots: list[_JudgeOutcomeSnapshot] = []
        for proof in proofs:
            proof_state = _sealed_judge_outcome(proof)
            issuer_state = _issuer(proof_state.issuer)
            snapshot = _validated_judge_outcome_snapshot(
                proof_state.snapshot,
                issuer_state,
            )
            expected = hmac.new(
                issuer_state.secret,
                _sealed_judge_outcome_material(
                    proof_state.receipt_commitment,
                    snapshot,
                    proof_state.comparison_commitment_sha256,
                ),
                hashlib.sha256,
            ).hexdigest()
            if (
                proof_state.phase != "issued"
                or not hmac.compare_digest(
                    proof_state.comparison_commitment_sha256,
                    commitment,
                )
                or not hmac.compare_digest(expected, proof_state.commitment)
            ):
                raise ManagedExecutionReceiptError("managed_sealed_judge_outcome_invalid")
            states.append(proof_state)
            snapshots.append(snapshot)
        observed = tuple((item.case_alias, item.backend_role) for item in snapshots)
        if len(observed) != len(expected_lanes) or set(observed) != set(expected_lanes):
            raise ManagedExecutionReceiptError("managed_sealed_judge_outcome_lane_invalid")
        if len(set(observed)) != len(observed):
            raise ManagedExecutionReceiptError("managed_sealed_judge_outcome_lane_invalid")
        for proof_state in states:
            proof_state.phase = "consumed"
    return tuple(snapshots)


def _validate_binding_pair(
    answer: object, judge: object
) -> tuple[ManagedProviderLaneBinding, ManagedProviderLaneBinding]:
    if (
        type(answer) is not ManagedProviderLaneBinding
        or type(judge) is not ManagedProviderLaneBinding
    ):
        raise ManagedExecutionReceiptError("managed_receipt_binding_invalid")
    answer.__post_init__()
    judge.__post_init__()
    if (
        answer.stage != "answerer"
        or judge.stage != "judge"
        or judge.ordinal != answer.ordinal + 1
        or (
            answer.comparison_commitment_sha256,
            answer.run_id,
            answer.profile_id,
            answer.public_case_alias,
            answer.backend_role,
        )
        != (
            judge.comparison_commitment_sha256,
            judge.run_id,
            judge.profile_id,
            judge.public_case_alias,
            judge.backend_role,
        )
    ):
        raise ManagedExecutionReceiptError("managed_receipt_binding_invalid")
    return answer, judge


def _binding_snapshot(value: object) -> _LaneBindingSnapshot:
    if type(value) is not ManagedProviderLaneBinding:
        raise ManagedExecutionReceiptError("managed_receipt_binding_invalid")
    try:
        value.__post_init__()
    except Exception:
        raise ManagedExecutionReceiptError("managed_receipt_binding_invalid") from None
    return _LaneBindingSnapshot(
        comparison_commitment_sha256=value.comparison_commitment_sha256,
        run_id=value.run_id,
        profile_id=value.profile_id,
        public_case_alias=value.public_case_alias,
        backend_role=value.backend_role,
        stage=value.stage,
        model=value.model,
        ordinal=value.ordinal,
    )


def _issuer_binding_snapshot(
    answer: ManagedProviderLaneBinding,
    judge: ManagedProviderLaneBinding,
    target_identity_sha256: str,
) -> _IssuerBindingSnapshot:
    return _IssuerBindingSnapshot(
        answer=_binding_snapshot(answer),
        judge=_binding_snapshot(judge),
        target_identity_sha256=target_identity_sha256,
    )


def _binding_material(value: _LaneBindingSnapshot) -> list[object]:
    return [
        value.comparison_commitment_sha256,
        value.run_id,
        value.profile_id,
        value.public_case_alias,
        value.backend_role,
        value.stage,
        value.model,
        value.ordinal,
    ]


def _validate_live_issuer_bindings(state: _IssuerState) -> None:
    try:
        answer, judge = _validate_binding_pair(
            state.answer_binding,
            state.judge_binding,
        )
        target = _digest(state.target_identity_sha256)
        current = _issuer_binding_snapshot(answer, judge, target)
    except Exception:
        raise ManagedExecutionReceiptError("managed_receipt_binding_mutated") from None
    if current != state.binding_snapshot:
        raise ManagedExecutionReceiptError("managed_receipt_binding_mutated")


def _issuer(value: object) -> _IssuerState:
    if type(value) is not ManagedExecutionReceiptIssuer:
        raise ManagedExecutionReceiptError("managed_receipt_issuer_invalid")
    with _LOCK:
        state = _ISSUERS.get(value)
    if state is None:
        raise ManagedExecutionReceiptError("managed_receipt_issuer_invalid")
    _validate_live_issuer_bindings(state)
    return state


def _receipt(value: object) -> _ReceiptState:
    if type(value) is not ManagedExecutionReceipt:
        raise ManagedExecutionReceiptError("managed_receipt_predecessor_invalid")
    with _LOCK:
        state = _RECEIPTS.get(value)
    if state is None:
        raise ManagedExecutionReceiptError("managed_receipt_predecessor_invalid")
    return state


def _sealed_judge_outcome(value: object) -> _SealedJudgeOutcomeState:
    if type(value) is not ManagedSealedJudgeOutcome:
        raise ManagedExecutionReceiptError("managed_sealed_judge_outcome_invalid")
    with _LOCK:
        state = _SEALED_JUDGE_OUTCOMES.get(value)
    if state is None:
        raise ManagedExecutionReceiptError("managed_sealed_judge_outcome_invalid")
    return state


def _digest(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedExecutionReceiptError("managed_receipt_digest_invalid")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


__all__ = (
    "ManagedExecutionReceipt",
    "ManagedExecutionReceiptError",
    "ManagedExecutionReceiptIssuer",
    "ManagedRetrievalEvidenceView",
    "ManagedSealedJudgeOutcome",
    "consume_managed_sealed_judge_outcomes",
    "consume_sealed_managed_execution_receipt",
    "create_managed_execution_receipt_issuer",
    "inspect_managed_retrieval_receipt_for_answer",
    "issue_managed_answer_receipt",
    "issue_managed_judge_receipt",
    "issue_managed_retrieval_receipt",
    "seal_managed_execution_receipt",
)
