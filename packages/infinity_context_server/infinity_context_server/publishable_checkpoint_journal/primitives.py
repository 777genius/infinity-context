"""Immutable contracts for the durable publishable evaluation journal.

Extraction remains a separately attested 5,882-operation run commitment.
This boundary owns only the 6,160 provider answer/judge evaluation slots.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import final

CHECKPOINT_JOURNAL_SCHEMA_VERSION = "3"
PUBLISHABLE_CASE_COUNT = 1540
PUBLISHABLE_MESSAGE_COUNT = 5882
PUBLISHABLE_EXTRACTION_CALL_COUNT = 5882
PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT = 6160
PUBLISHABLE_ANSWER_CALL_COUNT = PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT // 2
PUBLISHABLE_JUDGE_CALL_COUNT = PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT // 2
PUBLISHABLE_TOTAL_CALL_COUNT = (
    PUBLISHABLE_EXTRACTION_CALL_COUNT + PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT
)
PUBLISHABLE_ANSWER_ORDINAL_START = 0
PUBLISHABLE_JUDGE_ORDINAL_START = PUBLISHABLE_ANSWER_CALL_COUNT

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CheckpointJournalError(RuntimeError):
    """Raised when a checkpoint invariant cannot be proven."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RunPhase(StrEnum):
    ACTIVE = "active"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    EVALUATION_SEALED = "evaluation_sealed"


class CallPhase(StrEnum):
    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    COMMITTED = "committed"
    OUTCOME_UNKNOWN = "outcome_unknown"


class CallStage(StrEnum):
    ANSWER = "answer"
    JUDGE = "judge"


def canonical_json(value: object) -> str:
    """Return the single JSON representation allowed in durable commitments."""

    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise CheckpointJournalError("checkpoint_journal_payload_not_canonical") from error


def sha256_commitment(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def evaluation_stage_for_ordinal(ordinal: int) -> CallStage:
    """Return the exact provider stage assigned to a global evaluation ordinal."""

    if not isinstance(ordinal, int) or isinstance(ordinal, bool):
        raise CheckpointJournalError("checkpoint_journal_call_ordinal_invalid")
    if PUBLISHABLE_ANSWER_ORDINAL_START <= ordinal < PUBLISHABLE_JUDGE_ORDINAL_START:
        return CallStage.ANSWER
    if PUBLISHABLE_JUDGE_ORDINAL_START <= ordinal < PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT:
        return CallStage.JUDGE
    raise CheckpointJournalError("checkpoint_journal_call_ordinal_out_of_range")


@final
@dataclass(frozen=True, slots=True)
class PublishableRunIdentity:
    """Every authority input frozen before the evaluation journal is opened."""

    run_id: str
    profile_id: str
    profile_commitment_sha256: str
    dataset_commitment_sha256: str
    methodology_commitment_sha256: str
    source_commit_sha256: str
    runtime_pin_sha256: str
    case_manifest_sha256: str
    manifest_authority_commitment_sha256: str
    evaluation_manifest_commitment_sha256: str
    signer_key_id: str
    journal_schema_version: str = CHECKPOINT_JOURNAL_SCHEMA_VERSION
    expected_case_count: int = PUBLISHABLE_CASE_COUNT
    expected_message_count: int = PUBLISHABLE_MESSAGE_COUNT
    expected_extraction_call_count: int = PUBLISHABLE_EXTRACTION_CALL_COUNT
    expected_answer_judge_call_count: int = PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        _identifier(self.profile_id, "profile_id")
        _identifier(self.signer_key_id, "signer_key_id")
        for value, name in (
            (self.profile_commitment_sha256, "profile_commitment_sha256"),
            (self.dataset_commitment_sha256, "dataset_commitment_sha256"),
            (self.methodology_commitment_sha256, "methodology_commitment_sha256"),
            (self.source_commit_sha256, "source_commit_sha256"),
            (self.runtime_pin_sha256, "runtime_pin_sha256"),
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
            _digest(value, name)
        if self.journal_schema_version != CHECKPOINT_JOURNAL_SCHEMA_VERSION:
            raise CheckpointJournalError("checkpoint_journal_schema_version_drift")
        expected = (
            (self.expected_case_count, PUBLISHABLE_CASE_COUNT),
            (self.expected_message_count, PUBLISHABLE_MESSAGE_COUNT),
            (self.expected_extraction_call_count, PUBLISHABLE_EXTRACTION_CALL_COUNT),
            (
                self.expected_answer_judge_call_count,
                PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT,
            ),
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value != commitment
            for value, commitment in expected
        ):
            raise CheckpointJournalError("checkpoint_journal_publishable_commitment_drift")

    @property
    def expected_total_call_count(self) -> int:
        return self.expected_extraction_call_count + self.expected_answer_judge_call_count

    def commitment_payload(self) -> dict[str, object]:
        return {
            "case_manifest_sha256": self.case_manifest_sha256,
            "dataset_commitment_sha256": self.dataset_commitment_sha256,
            "evaluation_manifest_commitment_sha256": (self.evaluation_manifest_commitment_sha256),
            "expected_answer_judge_call_count": self.expected_answer_judge_call_count,
            "expected_case_count": self.expected_case_count,
            "expected_extraction_call_count": self.expected_extraction_call_count,
            "expected_message_count": self.expected_message_count,
            "journal_schema_version": self.journal_schema_version,
            "manifest_authority_commitment_sha256": (self.manifest_authority_commitment_sha256),
            "methodology_commitment_sha256": self.methodology_commitment_sha256,
            "profile_commitment_sha256": self.profile_commitment_sha256,
            "profile_id": self.profile_id,
            "run_id": self.run_id,
            "runtime_pin_sha256": self.runtime_pin_sha256,
            "signer_key_id": self.signer_key_id,
            "source_commit_sha256": self.source_commit_sha256,
        }

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("PublishableRunIdentity is final")


@final
@dataclass(frozen=True, slots=True)
class LogicalCallIdentity:
    """One immutable provider answer/judge slot with a global ordinal."""

    run_id: str
    case_id: str
    case_alias: str
    backend_role: str
    backend_target_id: str
    backend_target_commitment_sha256: str
    stage: CallStage
    ordinal: int
    depends_on_logical_call_id: str | None = None
    logical_call_id: str = field(init=False)
    replay_key: str = field(init=False)
    case_lane_id: str = field(init=False)

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        _identifier(self.case_id, "case_id")
        _identifier(self.case_alias, "case_alias")
        _identifier(self.backend_role, "backend_role")
        _identifier(self.backend_target_id, "backend_target_id")
        _digest(
            self.backend_target_commitment_sha256,
            "backend_target_commitment_sha256",
        )
        if not isinstance(self.stage, CallStage):
            raise CheckpointJournalError("checkpoint_journal_call_stage_invalid")
        expected_stage = evaluation_stage_for_ordinal(self.ordinal)
        if self.stage is not expected_stage:
            raise CheckpointJournalError("checkpoint_journal_call_stage_ordinal_invalid")
        if self.stage is CallStage.JUDGE:
            if self.depends_on_logical_call_id is None:
                raise CheckpointJournalError("checkpoint_journal_judge_dependency_missing")
            _digest(self.depends_on_logical_call_id, "depends_on_logical_call_id")
        elif self.depends_on_logical_call_id is not None:
            raise CheckpointJournalError("checkpoint_journal_unexpected_call_dependency")
        identity_payload = self.identity_payload()
        replay_payload = {
            "backend_role": self.backend_role,
            "backend_target_id": self.backend_target_id,
            "backend_target_commitment_sha256": (self.backend_target_commitment_sha256),
            "case_alias": self.case_alias,
            "case_id": self.case_id,
            "ordinal": self.ordinal,
            "run_id": self.run_id,
            "stage": self.stage.value,
        }
        lane_payload = {
            "backend_role": self.backend_role,
            "backend_target_id": self.backend_target_id,
            "backend_target_commitment_sha256": (self.backend_target_commitment_sha256),
            "case_alias": self.case_alias,
            "case_id": self.case_id,
            "run_id": self.run_id,
        }
        object.__setattr__(self, "logical_call_id", sha256_commitment(identity_payload))
        object.__setattr__(self, "replay_key", sha256_commitment(replay_payload))
        object.__setattr__(self, "case_lane_id", sha256_commitment(lane_payload))

    def identity_payload(self) -> dict[str, object]:
        return {
            "backend_role": self.backend_role,
            "backend_target_commitment_sha256": (self.backend_target_commitment_sha256),
            "backend_target_id": self.backend_target_id,
            "case_alias": self.case_alias,
            "case_id": self.case_id,
            "depends_on_logical_call_id": self.depends_on_logical_call_id,
            "ordinal": self.ordinal,
            "run_id": self.run_id,
            "stage": self.stage.value,
        }

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("LogicalCallIdentity is final")


def _identifier(value: object, name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise CheckpointJournalError(f"checkpoint_journal_{name}_invalid")


def _digest(value: object, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise CheckpointJournalError(f"checkpoint_journal_{name}_invalid")


__all__ = (
    "CHECKPOINT_JOURNAL_SCHEMA_VERSION",
    "CallPhase",
    "CallStage",
    "CheckpointJournalError",
    "LogicalCallIdentity",
    "PUBLISHABLE_ANSWER_CALL_COUNT",
    "PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT",
    "PUBLISHABLE_ANSWER_ORDINAL_START",
    "PUBLISHABLE_CASE_COUNT",
    "PUBLISHABLE_EXTRACTION_CALL_COUNT",
    "PUBLISHABLE_JUDGE_CALL_COUNT",
    "PUBLISHABLE_JUDGE_ORDINAL_START",
    "PUBLISHABLE_MESSAGE_COUNT",
    "PUBLISHABLE_TOTAL_CALL_COUNT",
    "PublishableRunIdentity",
    "RunPhase",
    "canonical_json",
    "evaluation_stage_for_ordinal",
    "sha256_commitment",
)
