"""Manifest and runtime contracts for the durable publishable journal."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import final

from infinity_context_server.publishable_checkpoint_journal.primitives import (
    CHECKPOINT_JOURNAL_SCHEMA_VERSION,
    PUBLISHABLE_ANSWER_CALL_COUNT,
    PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT,
    PUBLISHABLE_ANSWER_ORDINAL_START,
    PUBLISHABLE_CASE_COUNT,
    PUBLISHABLE_EXTRACTION_CALL_COUNT,
    PUBLISHABLE_JUDGE_CALL_COUNT,
    PUBLISHABLE_JUDGE_ORDINAL_START,
    PUBLISHABLE_MESSAGE_COUNT,
    PUBLISHABLE_TOTAL_CALL_COUNT,
    CallPhase,
    CallStage,
    CheckpointJournalError,
    LogicalCallIdentity,
    PublishableRunIdentity,
    RunPhase,
    _digest,
    _identifier,
    canonical_json,
    evaluation_stage_for_ordinal,
    sha256_commitment,
)


@final
@dataclass(frozen=True, slots=True)
class ManifestCaseAuthority:
    """One ordered case identity and its immutable external alias."""

    case_id: str
    case_alias: str

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case_id")
        _identifier(self.case_alias, "case_alias")

    def commitment_payload(self) -> dict[str, str]:
        return {"case_alias": self.case_alias, "case_id": self.case_id}

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManifestCaseAuthority is final")


@final
@dataclass(frozen=True, slots=True)
class BackendTargetAuthority:
    """One global backend lane and the exact target identity behind it."""

    backend_role: str
    backend_target_id: str
    backend_target_commitment_sha256: str

    def __post_init__(self) -> None:
        _identifier(self.backend_role, "backend_role")
        _identifier(self.backend_target_id, "backend_target_id")
        _digest(
            self.backend_target_commitment_sha256,
            "backend_target_commitment_sha256",
        )

    def commitment_payload(self) -> dict[str, str]:
        return {
            "backend_role": self.backend_role,
            "backend_target_commitment_sha256": (self.backend_target_commitment_sha256),
            "backend_target_id": self.backend_target_id,
        }

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("BackendTargetAuthority is final")


@final
@dataclass(frozen=True, slots=True)
class ManifestAuthority:
    """Exact ordered case and two-global-backend authority for one manifest."""

    ordered_cases: tuple[ManifestCaseAuthority, ...]
    backend_targets: tuple[BackendTargetAuthority, ...]
    case_manifest_sha256: str = field(init=False)
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.ordered_cases, tuple)
            or len(self.ordered_cases) != PUBLISHABLE_CASE_COUNT
            or any(not isinstance(case, ManifestCaseAuthority) for case in self.ordered_cases)
            or len({case.case_id for case in self.ordered_cases}) != PUBLISHABLE_CASE_COUNT
            or len({case.case_alias for case in self.ordered_cases}) != PUBLISHABLE_CASE_COUNT
        ):
            raise CheckpointJournalError("checkpoint_journal_case_authority_invalid")
        if (
            not isinstance(self.backend_targets, tuple)
            or len(self.backend_targets) != 2
            or any(
                not isinstance(target, BackendTargetAuthority) for target in self.backend_targets
            )
            or len({target.backend_role for target in self.backend_targets}) != 2
            or len({target.backend_target_id for target in self.backend_targets}) != 2
            or len({target.backend_target_commitment_sha256 for target in self.backend_targets})
            != 2
        ):
            raise CheckpointJournalError("checkpoint_journal_backend_authority_invalid")
        case_manifest_sha256 = sha256_commitment(
            {
                "ordered_cases": tuple(case.commitment_payload() for case in self.ordered_cases),
                "schema_version": CHECKPOINT_JOURNAL_SCHEMA_VERSION,
            }
        )
        commitment_sha256 = sha256_commitment(
            {
                "backend_targets": tuple(
                    target.commitment_payload() for target in self.backend_targets
                ),
                "case_manifest_sha256": case_manifest_sha256,
                "schema_version": CHECKPOINT_JOURNAL_SCHEMA_VERSION,
            }
        )
        object.__setattr__(self, "case_manifest_sha256", case_manifest_sha256)
        object.__setattr__(self, "commitment_sha256", commitment_sha256)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManifestAuthority is final")


@final
@dataclass(frozen=True, slots=True)
class EvaluationManifestVerification:
    """The bounded-stream proof of one exact persisted evaluation manifest."""

    run_id: str
    case_manifest_sha256: str
    manifest_authority_commitment_sha256: str
    commitment_sha256: str
    total_count: int
    answer_count: int
    judge_count: int

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        _digest(self.case_manifest_sha256, "case_manifest_sha256")
        _digest(
            self.manifest_authority_commitment_sha256,
            "manifest_authority_commitment_sha256",
        )
        _digest(self.commitment_sha256, "evaluation_manifest_commitment_sha256")
        expected = (
            (self.total_count, PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT),
            (self.answer_count, PUBLISHABLE_ANSWER_CALL_COUNT),
            (self.judge_count, PUBLISHABLE_JUDGE_CALL_COUNT),
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value != expected_value
            for value, expected_value in expected
        ):
            raise CheckpointJournalError("checkpoint_journal_evaluation_manifest_coverage_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("EvaluationManifestVerification is final")


@final
@dataclass(frozen=True, slots=True)
class PublishableEvaluationManifest:
    """The exact 6,160 provider slots bound to one frozen case manifest."""

    authority: ManifestAuthority
    calls: tuple[LogicalCallIdentity, ...]
    run_id: str = field(init=False)
    case_manifest_sha256: str = field(init=False)
    manifest_authority_commitment_sha256: str = field(init=False)
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.authority, ManifestAuthority)
            or not isinstance(self.calls, tuple)
            or len(self.calls) != PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT
            or any(not isinstance(call, LogicalCallIdentity) for call in self.calls)
        ):
            raise CheckpointJournalError("checkpoint_journal_evaluation_manifest_shape_invalid")
        verification = verify_evaluation_manifest_stream(
            self.calls,
            case_manifest_sha256=self.authority.case_manifest_sha256,
            manifest_authority_commitment_sha256=self.authority.commitment_sha256,
            authority=self.authority,
        )
        object.__setattr__(self, "run_id", verification.run_id)
        object.__setattr__(
            self,
            "case_manifest_sha256",
            verification.case_manifest_sha256,
        )
        object.__setattr__(
            self,
            "manifest_authority_commitment_sha256",
            verification.manifest_authority_commitment_sha256,
        )
        object.__setattr__(self, "commitment_sha256", verification.commitment_sha256)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("PublishableEvaluationManifest is final")


def verify_evaluation_manifest_stream(
    calls: Iterable[LogicalCallIdentity],
    *,
    case_manifest_sha256: str,
    manifest_authority_commitment_sha256: str,
    authority: ManifestAuthority | None = None,
) -> EvaluationManifestVerification:
    """Prove exact slot/lane/dependency coverage while consuming rows once."""

    _digest(case_manifest_sha256, "case_manifest_sha256")
    _digest(
        manifest_authority_commitment_sha256,
        "manifest_authority_commitment_sha256",
    )
    if authority is not None and (
        authority.case_manifest_sha256 != case_manifest_sha256
        or authority.commitment_sha256 != manifest_authority_commitment_sha256
    ):
        raise CheckpointJournalError("checkpoint_journal_manifest_authority_binding_invalid")
    digest = hashlib.sha256()
    digest.update(b'{"calls":[')
    expected_ordinal = 0
    run_id: str | None = None
    answer_lanes: dict[tuple[str, str, str], tuple[int, str]] = {}
    judge_lanes: set[tuple[str, str, str]] = set()
    case_backends: dict[str, set[str]] = {}
    answer_count = 0
    judge_count = 0
    for call in calls:
        if not isinstance(call, LogicalCallIdentity):
            raise CheckpointJournalError("checkpoint_journal_evaluation_manifest_call_invalid")
        if run_id is None:
            run_id = call.run_id
        if call.run_id != run_id or call.ordinal != expected_ordinal:
            raise CheckpointJournalError("checkpoint_journal_evaluation_manifest_ordinal_drift")
        expected_stage = evaluation_stage_for_ordinal(expected_ordinal)
        if call.stage is not expected_stage:
            raise CheckpointJournalError("checkpoint_journal_evaluation_manifest_stage_drift")
        base_ordinal = expected_ordinal % PUBLISHABLE_ANSWER_CALL_COUNT
        if authority is not None:
            expected_case = authority.ordered_cases[base_ordinal // 2]
            expected_target = authority.backend_targets[base_ordinal % 2]
            if (
                call.case_id != expected_case.case_id
                or call.case_alias != expected_case.case_alias
                or call.backend_role != expected_target.backend_role
                or call.backend_target_id != expected_target.backend_target_id
                or call.backend_target_commitment_sha256
                != expected_target.backend_target_commitment_sha256
            ):
                raise CheckpointJournalError(
                    "checkpoint_journal_evaluation_manifest_authority_drift"
                )
        lane = call.case_id, call.case_alias, call.backend_target_id
        case_backends.setdefault(call.case_id, set()).add(call.backend_target_id)
        if call.stage is CallStage.ANSWER:
            if lane in answer_lanes:
                raise CheckpointJournalError(
                    "checkpoint_journal_evaluation_manifest_lane_duplicate"
                )
            answer_lanes[lane] = (call.ordinal, call.logical_call_id)
            answer_count += 1
        else:
            answer = answer_lanes.get(lane)
            if (
                lane in judge_lanes
                or answer is None
                or call.depends_on_logical_call_id != answer[1]
                or call.ordinal != answer[0] + PUBLISHABLE_ANSWER_CALL_COUNT
            ):
                raise CheckpointJournalError(
                    "checkpoint_journal_evaluation_manifest_dependency_invalid"
                )
            judge_lanes.add(lane)
            judge_count += 1
        if expected_ordinal:
            digest.update(b",")
        digest.update(canonical_json(call.identity_payload()).encode("utf-8"))
        expected_ordinal += 1
    if (
        run_id is None
        or expected_ordinal != PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT
        or answer_count != PUBLISHABLE_ANSWER_CALL_COUNT
        or judge_count != PUBLISHABLE_JUDGE_CALL_COUNT
        or set(answer_lanes) != judge_lanes
        or len(case_backends) != PUBLISHABLE_CASE_COUNT
        or any(len(backends) != 2 for backends in case_backends.values())
    ):
        raise CheckpointJournalError("checkpoint_journal_evaluation_manifest_lane_coverage_invalid")
    digest.update(b'],"case_manifest_sha256":')
    digest.update(canonical_json(case_manifest_sha256).encode("utf-8"))
    digest.update(b',"manifest_authority_commitment_sha256":')
    digest.update(canonical_json(manifest_authority_commitment_sha256).encode("utf-8"))
    digest.update(b',"schema_version":')
    digest.update(canonical_json(CHECKPOINT_JOURNAL_SCHEMA_VERSION).encode("utf-8"))
    digest.update(b"}")
    return EvaluationManifestVerification(
        run_id=run_id,
        case_manifest_sha256=case_manifest_sha256,
        manifest_authority_commitment_sha256=(manifest_authority_commitment_sha256),
        commitment_sha256=digest.hexdigest(),
        total_count=expected_ordinal,
        answer_count=answer_count,
        judge_count=judge_count,
    )


@final
@dataclass(frozen=True, slots=True)
class RuntimeReceipt:
    """The compact, provider-neutral identity of one completed evaluation call."""

    run_id: str
    logical_call_id: str
    request_commitment_sha256: str
    provider_receipt_id: str
    result_commitment_sha256: str

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        _digest(self.logical_call_id, "logical_call_id")
        _digest(self.request_commitment_sha256, "request_commitment_sha256")
        _identifier(self.provider_receipt_id, "provider_receipt_id")
        _digest(self.result_commitment_sha256, "result_commitment_sha256")

    def identity_payload(self) -> dict[str, str]:
        return {
            "logical_call_id": self.logical_call_id,
            "provider_receipt_id": self.provider_receipt_id,
            "request_commitment_sha256": self.request_commitment_sha256,
            "result_commitment_sha256": self.result_commitment_sha256,
            "run_id": self.run_id,
        }

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("RuntimeReceipt is final")


@final
@dataclass(frozen=True, slots=True)
class VerifiedRuntimeReceipt:
    """A receipt accepted by the composition-owned runtime verifier."""

    receipt: RuntimeReceipt
    verifier_key_id: str
    verification_commitment_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, RuntimeReceipt):
            raise CheckpointJournalError("checkpoint_journal_receipt_type_invalid")
        _identifier(self.verifier_key_id, "verifier_key_id")
        _digest(self.verification_commitment_sha256, "verification_commitment_sha256")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("VerifiedRuntimeReceipt is final")


@final
@dataclass(frozen=True, slots=True)
class ProviderCallState:
    """Durable state of exactly one manifest-bound evaluation provider call."""

    identity: LogicalCallIdentity
    phase: CallPhase
    request_commitment_sha256: str | None = None
    receipt: RuntimeReceipt | None = None
    verifier_key_id: str | None = None
    verification_commitment_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, LogicalCallIdentity) or not isinstance(
            self.phase, CallPhase
        ):
            raise CheckpointJournalError("checkpoint_journal_call_state_invalid")
        committed = self.phase is CallPhase.COMMITTED
        if self.request_commitment_sha256 is not None:
            _digest(self.request_commitment_sha256, "request_commitment_sha256")
        if self.phase is not CallPhase.RESERVED and self.request_commitment_sha256 is None:
            raise CheckpointJournalError("checkpoint_journal_request_commitment_missing")
        receipt_values = (
            self.receipt,
            self.verifier_key_id,
            self.verification_commitment_sha256,
        )
        if committed:
            if not isinstance(self.receipt, RuntimeReceipt):
                raise CheckpointJournalError("checkpoint_journal_committed_receipt_missing")
            if self.receipt.run_id != self.identity.run_id:
                raise CheckpointJournalError("checkpoint_journal_receipt_run_mismatch")
            if self.receipt.logical_call_id != self.identity.logical_call_id:
                raise CheckpointJournalError("checkpoint_journal_receipt_call_mismatch")
            if self.receipt.request_commitment_sha256 != self.request_commitment_sha256:
                raise CheckpointJournalError("checkpoint_journal_receipt_request_mismatch")
            if not isinstance(self.verifier_key_id, str):
                raise CheckpointJournalError("checkpoint_journal_verifier_key_missing")
            _identifier(self.verifier_key_id, "verifier_key_id")
            if not isinstance(self.verification_commitment_sha256, str):
                raise CheckpointJournalError("checkpoint_journal_verification_commitment_missing")
            _digest(self.verification_commitment_sha256, "verification_commitment_sha256")
        elif any(value is not None for value in receipt_values):
            raise CheckpointJournalError("checkpoint_journal_uncommitted_receipt_present")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ProviderCallState is final")


@final
@dataclass(frozen=True, slots=True)
class JournalRunState:
    """The durable evaluation phase and authenticated event-chain head."""

    identity: PublishableRunIdentity
    phase: RunPhase = RunPhase.ACTIVE
    event_count: int = 0
    head_event_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, PublishableRunIdentity) or not isinstance(
            self.phase, RunPhase
        ):
            raise CheckpointJournalError("checkpoint_journal_run_state_invalid")
        if (
            not isinstance(self.event_count, int)
            or isinstance(self.event_count, bool)
            or self.event_count < 0
        ):
            raise CheckpointJournalError("checkpoint_journal_event_count_invalid")
        if self.event_count == 0 and self.head_event_sha256 is not None:
            raise CheckpointJournalError("checkpoint_journal_empty_chain_has_head")
        if self.event_count > 0:
            if not isinstance(self.head_event_sha256, str):
                raise CheckpointJournalError("checkpoint_journal_chain_head_missing")
            _digest(self.head_event_sha256, "head_event_sha256")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("JournalRunState is final")


@final
@dataclass(frozen=True, slots=True)
class JournalEvent:
    """One signed append-only record in a run-scoped predecessor chain."""

    run_id: str
    sequence: int
    event_type: str
    logical_call_id: str | None
    payload_json: str
    predecessor_event_sha256: str | None
    event_sha256: str
    signer_key_id: str
    signature: str

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence <= 0
        ):
            raise CheckpointJournalError("checkpoint_journal_event_sequence_invalid")
        _identifier(self.event_type, "event_type")
        if self.logical_call_id is not None:
            _digest(self.logical_call_id, "logical_call_id")
        if not isinstance(self.payload_json, str):
            raise CheckpointJournalError("checkpoint_journal_event_payload_invalid")
        try:
            parsed = json.loads(self.payload_json)
        except (TypeError, ValueError) as error:
            raise CheckpointJournalError("checkpoint_journal_event_payload_invalid") from error
        if canonical_json(parsed) != self.payload_json:
            raise CheckpointJournalError("checkpoint_journal_event_payload_not_canonical")
        if self.predecessor_event_sha256 is not None:
            _digest(self.predecessor_event_sha256, "predecessor_event_sha256")
        _digest(self.event_sha256, "event_sha256")
        _identifier(self.signer_key_id, "signer_key_id")
        if not isinstance(self.signature, str) or not self.signature or len(self.signature) > 512:
            raise CheckpointJournalError("checkpoint_journal_event_signature_invalid")

    def hash_payload(self) -> dict[str, object]:
        return {
            "event_type": self.event_type,
            "logical_call_id": self.logical_call_id,
            "payload_json": self.payload_json,
            "predecessor_event_sha256": self.predecessor_event_sha256,
            "run_id": self.run_id,
            "sequence": self.sequence,
        }

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("JournalEvent is final")


@final
@dataclass(frozen=True, slots=True)
class ResumeResult:
    run: JournalRunState
    outcome_unknown_count: int
    newly_outcome_unknown_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.run, JournalRunState):
            raise CheckpointJournalError("checkpoint_journal_resume_state_invalid")
        for value in (self.outcome_unknown_count, self.newly_outcome_unknown_count):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise CheckpointJournalError("checkpoint_journal_resume_count_invalid")
        if self.newly_outcome_unknown_count > self.outcome_unknown_count:
            raise CheckpointJournalError("checkpoint_journal_resume_count_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ResumeResult is final")


@final
@dataclass(frozen=True, slots=True)
class EvaluationCoverage:
    case_manifest_sha256: str | None
    manifest_authority_commitment_sha256: str | None
    evaluation_manifest_commitment_sha256: str | None
    authority_case_count: int
    authority_backend_target_count: int
    authority_mismatch_count: int
    manifest_total: int
    manifest_answer_count: int
    manifest_judge_count: int
    committed_total: int
    committed_answer_count: int
    committed_judge_count: int
    unresolved_count: int
    private_result_count: int
    signed_commit_event_count: int
    signed_commit_binding_count: int

    def __post_init__(self) -> None:
        for value in (
            self.authority_case_count,
            self.authority_backend_target_count,
            self.authority_mismatch_count,
            self.manifest_total,
            self.manifest_answer_count,
            self.manifest_judge_count,
            self.committed_total,
            self.committed_answer_count,
            self.committed_judge_count,
            self.unresolved_count,
            self.private_result_count,
            self.signed_commit_event_count,
            self.signed_commit_binding_count,
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise CheckpointJournalError("checkpoint_journal_coverage_invalid")
        for value, name in (
            (self.case_manifest_sha256, "case_manifest_sha256"),
            (
                self.manifest_authority_commitment_sha256,
                "manifest_authority_commitment_sha256",
            ),
            (
                self.evaluation_manifest_commitment_sha256,
                "evaluation_manifest_commitment_sha256",
            ),
        ):
            if value is not None:
                _digest(value, name)

    def manifest_is_exact_for(self, identity: PublishableRunIdentity) -> bool:
        return (
            self.case_manifest_sha256 == identity.case_manifest_sha256
            and self.manifest_authority_commitment_sha256
            == identity.manifest_authority_commitment_sha256
            and self.evaluation_manifest_commitment_sha256
            == identity.evaluation_manifest_commitment_sha256
            and self.authority_case_count == identity.expected_case_count
            and self.authority_backend_target_count == 2
            and self.authority_mismatch_count == 0
            and self.manifest_total == identity.expected_answer_judge_call_count
            and self.manifest_answer_count == PUBLISHABLE_ANSWER_CALL_COUNT
            and self.manifest_judge_count == PUBLISHABLE_JUDGE_CALL_COUNT
        )

    def is_complete_for(self, identity: PublishableRunIdentity) -> bool:
        return (
            self.manifest_is_exact_for(identity)
            and self.committed_total == identity.expected_answer_judge_call_count
            and self.committed_answer_count == PUBLISHABLE_ANSWER_CALL_COUNT
            and self.committed_judge_count == PUBLISHABLE_JUDGE_CALL_COUNT
            and self.unresolved_count == 0
            and self.private_result_count == identity.expected_answer_judge_call_count
            and self.signed_commit_event_count == identity.expected_answer_judge_call_count
            and self.signed_commit_binding_count == identity.expected_answer_judge_call_count
        )

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("EvaluationCoverage is final")


def create_journal_event(
    *,
    run_id: str,
    sequence: int,
    event_type: str,
    logical_call_id: str | None,
    payload: Mapping[str, object],
    predecessor_event_sha256: str | None,
    signer_key_id: str,
    sign: Callable[[bytes], str],
) -> JournalEvent:
    """Create a deterministic hash-chain entry signed by the injected key."""

    payload_json = canonical_json(payload)
    provisional = JournalEvent(
        run_id=run_id,
        sequence=sequence,
        event_type=event_type,
        logical_call_id=logical_call_id,
        payload_json=payload_json,
        predecessor_event_sha256=predecessor_event_sha256,
        event_sha256="0" * 64,
        signer_key_id=signer_key_id,
        signature="provisional",
    )
    event_sha256 = sha256_commitment(provisional.hash_payload())
    signature = sign(event_sha256.encode("ascii"))
    return JournalEvent(
        run_id=run_id,
        sequence=sequence,
        event_type=event_type,
        logical_call_id=logical_call_id,
        payload_json=payload_json,
        predecessor_event_sha256=predecessor_event_sha256,
        event_sha256=event_sha256,
        signer_key_id=signer_key_id,
        signature=signature,
    )


__all__ = (
    "CHECKPOINT_JOURNAL_SCHEMA_VERSION",
    "PUBLISHABLE_ANSWER_CALL_COUNT",
    "PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT",
    "PUBLISHABLE_ANSWER_ORDINAL_START",
    "PUBLISHABLE_CASE_COUNT",
    "PUBLISHABLE_EXTRACTION_CALL_COUNT",
    "PUBLISHABLE_JUDGE_CALL_COUNT",
    "PUBLISHABLE_JUDGE_ORDINAL_START",
    "PUBLISHABLE_MESSAGE_COUNT",
    "PUBLISHABLE_TOTAL_CALL_COUNT",
    "BackendTargetAuthority",
    "CallPhase",
    "CallStage",
    "CheckpointJournalError",
    "EvaluationCoverage",
    "EvaluationManifestVerification",
    "JournalEvent",
    "JournalRunState",
    "LogicalCallIdentity",
    "ManifestAuthority",
    "ManifestCaseAuthority",
    "ProviderCallState",
    "PublishableEvaluationManifest",
    "PublishableRunIdentity",
    "ResumeResult",
    "RunPhase",
    "RuntimeReceipt",
    "VerifiedRuntimeReceipt",
    "canonical_json",
    "create_journal_event",
    "evaluation_stage_for_ordinal",
    "sha256_commitment",
    "verify_evaluation_manifest_stream",
)
