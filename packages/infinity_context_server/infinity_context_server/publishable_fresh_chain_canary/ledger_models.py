"""Immutable provider-neutral models for the fresh-chain durable ledger."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Literal, TypeAlias, final

FRESH_CHAIN_CANARY_KIND: Final = "fresh-chain canary"
FRESH_CHAIN_RUNTIME_TRANSPORT: Final = "subscription-runtime-worker-authenticated"
FRESH_CHAIN_LEDGER_AUTHENTICATION: Final = "operator-local HMAC"
FRESH_CHAIN_CASE_ID: Final = "conv-26:qa:1"
FRESH_CHAIN_STAGES: Final = (
    "mem0_extraction",
    "infinity_answer",
    "infinity_judge",
    "mem0_answer",
    "mem0_judge",
)
FRESH_CHAIN_EXPECTED_PHYSICAL_CALL_COUNT: Final = 5
FRESH_CHAIN_PLAN_SCHEMA_VERSION: Final = "infinity-context-fresh-chain-plan.v1"
FRESH_CHAIN_SNAPSHOT_SCHEMA_VERSION: Final = "infinity-context-fresh-chain-ledger-snapshot.v1"
FRESH_CHAIN_DISPATCH_STARTED_SCHEMA_VERSION: Final = (
    "infinity-context-fresh-chain-dispatch-started.v1"
)
FRESH_CHAIN_CALL_FAILURE_SCHEMA_VERSION: Final = "infinity-context-fresh-chain-call-failure.v1"
FRESH_CHAIN_FAILED_TERMINAL_SCHEMA_VERSION: Final = (
    "infinity-context-fresh-chain-failed-terminal.v1"
)
FRESH_CHAIN_EXTRACTION_FAILURE_COMMITMENT_KEYS: Final = frozenset(
    {
        "admission_commitment_sha256",
        "operation_id_sha256",
        "output_text_sha256",
        "provider_disposition_sha256",
        "request_body_sha256",
        "run_identity_commitment_sha256",
        "runtime_binding_commitment_sha256",
        "scope_sha256",
        "source_projection_commitment_sha256",
        "unit_identity_sha256",
        "unit_sha256",
    }
)
FRESH_CHAIN_EVALUATION_FAILURE_COMMITMENT_KEYS: Final = frozenset(
    {
        "bridge_intent_sha256",
        "provider_disposition_sha256",
        "request_body_sha256",
        "response_body_sha256",
    }
)

FreshChainStage: TypeAlias = Literal[
    "mem0_extraction",
    "infinity_answer",
    "infinity_judge",
    "mem0_answer",
    "mem0_judge",
]
StageStatus: TypeAlias = Literal["not_started", "pending", "succeeded", "failed"]
TerminalStatus: TypeAlias = Literal["succeeded", "failed"]
CommitmentItems: TypeAlias = tuple[tuple[str, str], ...]


class FreshChainFailureDisposition(StrEnum):
    """Authenticated terminal failure dispositions exposed by provider seams."""

    PROVIDER_FAILED = "provider_failed"
    REJECTED = "rejected"


class FreshChainLedgerError(RuntimeError):
    """Fail-closed rejection of malformed, divergent, or unauthenticated state."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@final
@dataclass(frozen=True, slots=True)
class FreshChainPlan:
    """Immutable authority for one fresh namespace and the fixed official case."""

    run_id: str
    namespace_id: str
    namespace_commitment_sha256: str
    source_commitment_sha256: str
    common_condition_policy_sha256: str
    commitments: CommitmentItems | Mapping[str, str] = field(default_factory=tuple)
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not _identifier(self.run_id) or not _identifier(self.namespace_id):
            _fail("fresh_chain_plan_invalid")
        if not all(
            _is_sha256(value)
            for value in (
                self.namespace_commitment_sha256,
                self.source_commitment_sha256,
                self.common_condition_policy_sha256,
            )
        ):
            _fail("fresh_chain_plan_invalid")
        normalized = normalize_commitments(self.commitments)
        object.__setattr__(self, "commitments", normalized)
        object.__setattr__(self, "commitment_sha256", canonical_sha256(self.material()))

    def material(self) -> dict[str, object]:
        return {
            "schema_version": FRESH_CHAIN_PLAN_SCHEMA_VERSION,
            "canary_kind": FRESH_CHAIN_CANARY_KIND,
            "runtime_transport": FRESH_CHAIN_RUNTIME_TRANSPORT,
            "ledger_authentication": FRESH_CHAIN_LEDGER_AUTHENTICATION,
            "run_id": self.run_id,
            "case_id": FRESH_CHAIN_CASE_ID,
            "fresh_namespace": True,
            "namespace_id": self.namespace_id,
            "namespace_commitment_sha256": self.namespace_commitment_sha256,
            "source_commitment_sha256": self.source_commitment_sha256,
            "common_condition_policy_sha256": self.common_condition_policy_sha256,
            "ordered_stages": list(FRESH_CHAIN_STAGES),
            "expected_physical_call_count": FRESH_CHAIN_EXPECTED_PHYSICAL_CALL_COUNT,
            "commitments": {key: value for key, value in self.commitments},
            "publishable": False,
        }


@final
@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        if (
            any(type(value) is not int or value < 0 for value in self.as_tuple())
            or self.total_tokens != self.input_tokens + self.output_tokens
        ):
            _fail("fresh_chain_token_usage_invalid")

    def as_tuple(self) -> tuple[int, int, int]:
        return self.input_tokens, self.output_tokens, self.total_tokens

    def material(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@final
@dataclass(frozen=True, slots=True)
class FreshChainStageRecord:
    stage: FreshChainStage
    status: StageStatus = "not_started"
    intent_sha256: str | None = None
    request_sha256: str | None = None
    input_authority_sha256: str | None = None
    intent_commitments: CommitmentItems = ()
    ambiguity_sha256: str | None = None
    authenticated_absence_sha256: tuple[str, ...] = ()
    dispatch_started_sha256: str | None = None
    result_sha256: str | None = None
    failure_sha256: str | None = None
    provider_disposition: FreshChainFailureDisposition | None = None
    receipt_id: str | None = None
    receipt_sha256: str | None = None
    token_usage: TokenUsage | None = None
    result_commitments: CommitmentItems = ()

    @property
    def terminal(self) -> bool:
        return self.status in {"succeeded", "failed"}

    def material(self) -> dict[str, object]:
        result = None
        if self.result_sha256 is not None:
            result = {
                "sha256": self.result_sha256,
                "commitments": dict(self.result_commitments),
                "publishable": False,
            }
        failure = None
        if self.failure_sha256 is not None:
            failure = {
                "sha256": self.failure_sha256,
                "provider_disposition": self.provider_disposition,
                "commitments": dict(self.result_commitments),
                "publishable": False,
            }
        receipt = None
        if self.receipt_sha256 is not None:
            receipt = {
                "receipt_id": self.receipt_id,
                "sha256": self.receipt_sha256,
                "token_usage": None if self.token_usage is None else self.token_usage.material(),
                "publishable": False,
            }
        material = {
            "stage": self.stage,
            "status": self.status,
            "intent_sha256": self.intent_sha256,
            "request_sha256": self.request_sha256,
            "input_authority_sha256": self.input_authority_sha256,
            "intent_commitments": dict(self.intent_commitments),
            "ambiguity_sha256": self.ambiguity_sha256,
            "authenticated_absence_sha256": list(self.authenticated_absence_sha256),
            "dispatch_started_sha256": self.dispatch_started_sha256,
            "result": result,
            "receipt": receipt,
            "publishable": False,
        }
        if failure is not None:
            material["failure"] = failure
        return material


@final
@dataclass(frozen=True, slots=True)
class RetrievalHandoff:
    extraction_result_sha256: str
    extraction_receipt_sha256: str
    namespace_commitment_sha256: str
    memory_authority_sha256: str
    retrieval_authority_sha256: str
    memory_count: int
    commitments: CommitmentItems = ()

    def __post_init__(self) -> None:
        commitments = dict(self.commitments)
        if (
            type(self.memory_count) is not int
            or self.memory_count < 1
            or commitments.get("memory_count_sha256")
            != canonical_sha256({"memory_count": self.memory_count})
            or commitments.get("handoff_sha256")
            != canonical_sha256(
                {
                    "extraction_intent_sha256": commitments.get("extraction_intent_sha256"),
                    "extraction_receipt_sha256": self.extraction_receipt_sha256,
                    "extraction_result_sha256": self.extraction_result_sha256,
                    "memory_authority_sha256": self.memory_authority_sha256,
                    "memory_count": self.memory_count,
                    "namespace_commitment_sha256": self.namespace_commitment_sha256,
                    "retrieval_authority_sha256": self.retrieval_authority_sha256,
                    "retrieval_material_sha256": commitments.get("retrieval_material_sha256"),
                    "source_commitment_sha256": commitments.get("source_commitment_sha256"),
                    "source_projection_commitment_sha256": commitments.get(
                        "source_projection_commitment_sha256"
                    ),
                }
            )
        ):
            _fail("fresh_chain_retrieval_handoff_invalid")

    def material(self) -> dict[str, object]:
        return {
            "extraction_result_sha256": self.extraction_result_sha256,
            "extraction_receipt_sha256": self.extraction_receipt_sha256,
            "namespace_commitment_sha256": self.namespace_commitment_sha256,
            "memory_authority_sha256": self.memory_authority_sha256,
            "memory_count": self.memory_count,
            "retrieval_authority_sha256": self.retrieval_authority_sha256,
            "commitments": dict(self.commitments),
            "publishable": False,
        }


@final
@dataclass(frozen=True, slots=True)
class CleanupBinding:
    namespace_commitment_sha256: str
    cleanup_authority_sha256: str
    receipt_id: str
    receipt_sha256: str
    outcome_sha256: str
    deleted: bool
    operation_count: int
    residual_count: int

    def __post_init__(self) -> None:
        if (
            not all(
                _is_sha256(value)
                for value in (
                    self.namespace_commitment_sha256,
                    self.cleanup_authority_sha256,
                    self.receipt_sha256,
                    self.outcome_sha256,
                )
            )
            or not _identifier(self.receipt_id)
            or self.deleted is not True
            or type(self.operation_count) is not int
            or self.operation_count != 1
            or type(self.residual_count) is not int
            or self.residual_count != 0
        ):
            _fail("fresh_chain_cleanup_invalid")

    def material(self) -> dict[str, object]:
        return {
            "namespace_commitment_sha256": self.namespace_commitment_sha256,
            "cleanup_authority_sha256": self.cleanup_authority_sha256,
            "deleted": self.deleted,
            "operation_count": self.operation_count,
            "receipt": {
                "receipt_id": self.receipt_id,
                "sha256": self.receipt_sha256,
                "publishable": False,
            },
            "residual_count": self.residual_count,
            "outcome_sha256": self.outcome_sha256,
            "publishable": False,
        }


@final
@dataclass(frozen=True, slots=True)
class TerminalOutcome:
    status: TerminalStatus
    outcome_sha256: str

    def material(self) -> dict[str, object]:
        return {
            "status": self.status,
            "outcome_sha256": self.outcome_sha256,
            "activation_evidence_only": True,
            "publishable": False,
        }


@final
@dataclass(frozen=True, slots=True)
class FreshChainSnapshot:
    plan: FreshChainPlan
    source_projection_commitment_sha256: str | None
    stages: tuple[FreshChainStageRecord, ...]
    retrieval_handoff: RetrievalHandoff | None
    cleanup: CleanupBinding | None
    terminal_outcome: TerminalOutcome | None
    event_count: int
    event_head_hmac: str
    abort_reason_sha256: str | None = None

    @property
    def pending_intent(self) -> FreshChainStageRecord | None:
        return next((stage for stage in self.stages if stage.status == "pending"), None)

    @property
    def recovery_required(self) -> bool:
        return self.pending_intent is not None

    @property
    def completed(self) -> bool:
        return self.terminal_outcome is not None

    @property
    def succeeded(self) -> bool:
        return self.terminal_outcome is not None and self.terminal_outcome.status == "succeeded"

    @property
    def intent_count(self) -> int:
        return sum(stage.intent_sha256 is not None for stage in self.stages)

    @property
    def result_count(self) -> int:
        return sum(stage.terminal for stage in self.stages)

    @property
    def physical_attempt_count(self) -> int:
        return sum(stage.receipt_sha256 is not None for stage in self.stages)

    @property
    def ordered_completed_stages(self) -> tuple[FreshChainStage, ...]:
        return tuple(stage.stage for stage in self.stages if stage.status == "succeeded")

    @property
    def ordered_receipt_ids(self) -> tuple[str, ...]:
        return tuple(stage.receipt_id for stage in self.stages if stage.receipt_id is not None)

    @property
    def token_usage(self) -> TokenUsage:
        usages = tuple(stage.token_usage for stage in self.stages if stage.token_usage is not None)
        input_tokens = sum(usage.input_tokens for usage in usages)
        output_tokens = sum(usage.output_tokens for usage in usages)
        return TokenUsage(input_tokens, output_tokens, input_tokens + output_tokens)

    @property
    def next_stage(self) -> FreshChainStage | None:
        if (
            self.source_projection_commitment_sha256 is None
            or self.completed
            or self.pending_intent is not None
            or any(stage.status == "failed" for stage in self.stages)
        ):
            return None
        next_record = next((stage for stage in self.stages if stage.status == "not_started"), None)
        if next_record is None:
            return None
        if next_record.stage == "infinity_answer" and self.retrieval_handoff is None:
            return None
        return next_record.stage

    def material(self) -> dict[str, object]:
        return {
            "schema_version": FRESH_CHAIN_SNAPSHOT_SCHEMA_VERSION,
            "canary_kind": FRESH_CHAIN_CANARY_KIND,
            "runtime_transport": FRESH_CHAIN_RUNTIME_TRANSPORT,
            "ledger_authentication": FRESH_CHAIN_LEDGER_AUTHENTICATION,
            "plan": self.plan.material(),
            "plan_commitment_sha256": self.plan.commitment_sha256,
            "source_projection_commitment_sha256": (self.source_projection_commitment_sha256),
            "stages": [stage.material() for stage in self.stages],
            "next_stage": self.next_stage,
            "pending_stage": (None if self.pending_intent is None else self.pending_intent.stage),
            "recovery_required": self.recovery_required,
            "intent_count": self.intent_count,
            "result_count": self.result_count,
            "physical_attempt_count": self.physical_attempt_count,
            "expected_physical_call_count": FRESH_CHAIN_EXPECTED_PHYSICAL_CALL_COUNT,
            "ordered_completed_stages": list(self.ordered_completed_stages),
            "ordered_receipt_ids": list(self.ordered_receipt_ids),
            "token_usage": self.token_usage.material(),
            "retrieval_handoff": (
                None if self.retrieval_handoff is None else self.retrieval_handoff.material()
            ),
            "abort_reason_sha256": self.abort_reason_sha256,
            "cleanup": None if self.cleanup is None else self.cleanup.material(),
            "terminal_outcome": (
                None if self.terminal_outcome is None else self.terminal_outcome.material()
            ),
            "event_count": self.event_count,
            "event_head_hmac": self.event_head_hmac,
            "activation_evidence_only": True,
            "publishable": False,
        }


def canonical_json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError):
        _fail("fresh_chain_material_invalid")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def failure_commitment_keys(stage: FreshChainStage | str) -> frozenset[str]:
    selected = require_stage(stage)
    if selected == "mem0_extraction":
        return FRESH_CHAIN_EXTRACTION_FAILURE_COMMITMENT_KEYS
    return FRESH_CHAIN_EVALUATION_FAILURE_COMMITMENT_KEYS


def provider_disposition_sha256(
    value: FreshChainFailureDisposition | str,
) -> str:
    disposition = require_failure_disposition(value)
    return canonical_sha256({"provider_disposition": disposition.value})


def fresh_chain_call_failure_sha256(
    *,
    stage: FreshChainStage | str,
    intent_sha256: str,
    provider_disposition: FreshChainFailureDisposition | str,
    receipt_id: str,
    physical_receipt_sha256: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    commitments: CommitmentItems | Mapping[str, str],
) -> str:
    """Bind one authenticated known failure independently of dispatch/readback mode."""

    selected = require_stage(stage)
    disposition = require_failure_disposition(provider_disposition)
    usage = TokenUsage(input_tokens, output_tokens, total_tokens)
    normalized = normalize_commitments(commitments)
    if set(dict(normalized)) != failure_commitment_keys(selected):
        _fail("fresh_chain_failure_commitments_invalid")
    if dict(normalized).get("provider_disposition_sha256") != (
        provider_disposition_sha256(disposition)
    ):
        _fail("fresh_chain_failure_commitments_invalid")
    return canonical_sha256(
        {
            "schema_version": FRESH_CHAIN_CALL_FAILURE_SCHEMA_VERSION,
            "stage": selected,
            "ordinal": FRESH_CHAIN_STAGES.index(selected),
            "intent_sha256": require_sha256(intent_sha256),
            "provider_disposition": disposition.value,
            "physical_receipt_sha256": require_sha256(physical_receipt_sha256),
            "receipt_id": require_identifier(receipt_id),
            "token_usage": usage.material(),
            "commitments": dict(normalized),
            "publishable": False,
        }
    )


def fresh_chain_failed_terminal_outcome_sha256(
    *,
    plan: FreshChainPlan,
    source_projection_commitment_sha256: str,
    stages: tuple[FreshChainStageRecord, ...],
    retrieval_handoff: RetrievalHandoff | None,
    abort_reason_sha256: str | None = None,
    cleanup: CleanupBinding,
) -> str:
    """Derive the terminal digest for a known-call failure or local abort."""

    if (
        type(plan) is not FreshChainPlan
        or not _is_sha256(source_projection_commitment_sha256)
        or type(stages) is not tuple
        or len(stages) != len(FRESH_CHAIN_STAGES)
        or tuple(record.stage for record in stages) != FRESH_CHAIN_STAGES
        or type(cleanup) is not CleanupBinding
        or (abort_reason_sha256 is not None and not _is_sha256(abort_reason_sha256))
        or (retrieval_handoff is not None and type(retrieval_handoff) is not RetrievalHandoff)
    ):
        _fail("fresh_chain_failed_terminal_invalid")
    failed_indexes = tuple(
        index for index, record in enumerate(stages) if record.status == "failed"
    )
    if (abort_reason_sha256 is None) == (len(failed_indexes) != 1):
        _fail("fresh_chain_failed_terminal_invalid")
    if abort_reason_sha256 is not None:
        if (
            not stages[0].terminal
            or stages[0].status != "succeeded"
            or cleanup.namespace_commitment_sha256 != plan.namespace_commitment_sha256
        ):
            _fail("fresh_chain_failed_terminal_invalid")
        return canonical_sha256(
            {
                "schema_version": FRESH_CHAIN_FAILED_TERMINAL_SCHEMA_VERSION,
                "abort_reason_sha256": abort_reason_sha256,
                "activation_evidence_only": True,
                "cleanup": cleanup.material(),
                "ordered_receipt_ids": [record.receipt_id for record in stages if record.terminal],
                "plan_commitment_sha256": plan.commitment_sha256,
                "publishable": False,
                "source_projection_commitment_sha256": source_projection_commitment_sha256,
                "retrieval_handoff": (
                    None if retrieval_handoff is None else retrieval_handoff.material()
                ),
                "terminal_stages": [record.material() for record in stages if record.terminal],
            }
        )
    failed_index = failed_indexes[0]
    failed = stages[failed_index]
    if (
        any(record.status != "succeeded" for record in stages[:failed_index])
        or any(record.status != "not_started" for record in stages[failed_index + 1 :])
        or (failed_index == 0) != (retrieval_handoff is None)
        or cleanup.namespace_commitment_sha256 != plan.namespace_commitment_sha256
        or failed.result_sha256 is not None
        or failed.failure_sha256 is None
        or type(failed.provider_disposition) is not FreshChainFailureDisposition
        or failed.receipt_id is None
        or failed.receipt_sha256 is None
        or failed.token_usage is None
        or set(dict(failed.result_commitments)) != failure_commitment_keys(failed.stage)
    ):
        _fail("fresh_chain_failed_terminal_invalid")
    expected_failure = fresh_chain_call_failure_sha256(
        stage=failed.stage,
        intent_sha256=failed.intent_sha256,
        provider_disposition=failed.provider_disposition,
        receipt_id=failed.receipt_id,
        physical_receipt_sha256=failed.receipt_sha256,
        input_tokens=failed.token_usage.input_tokens,
        output_tokens=failed.token_usage.output_tokens,
        total_tokens=failed.token_usage.total_tokens,
        commitments=failed.result_commitments,
    )
    if failed.failure_sha256 != expected_failure:
        _fail("fresh_chain_failed_terminal_invalid")
    return canonical_sha256(
        {
            "schema_version": FRESH_CHAIN_FAILED_TERMINAL_SCHEMA_VERSION,
            "activation_evidence_only": True,
            "cleanup": cleanup.material(),
            "ordered_receipt_ids": [record.receipt_id for record in stages if record.terminal],
            "plan_commitment_sha256": plan.commitment_sha256,
            "publishable": False,
            "source_projection_commitment_sha256": (source_projection_commitment_sha256),
            "retrieval_handoff": (
                None if retrieval_handoff is None else retrieval_handoff.material()
            ),
            "terminal_stages": [record.material() for record in stages if record.terminal],
        }
    )


def fresh_chain_dispatch_started_sha256(
    *,
    stage: FreshChainStage | str,
    intent_sha256: str,
    authenticated_absence_sha256: str,
) -> str:
    """Commit the exact authenticated absence that authorizes one dispatch start."""

    selected_stage = require_stage(stage)
    return canonical_sha256(
        {
            "schema_version": FRESH_CHAIN_DISPATCH_STARTED_SCHEMA_VERSION,
            "stage": selected_stage,
            "intent_sha256": require_sha256(intent_sha256),
            "authenticated_absence_sha256": require_sha256(authenticated_absence_sha256),
        }
    )


def normalize_commitments(value: object) -> CommitmentItems:
    if isinstance(value, Mapping):
        items = tuple(value.items())
    elif type(value) is tuple:
        items = value
    else:
        _fail("fresh_chain_commitments_invalid")
    if any(
        type(item) is not tuple
        or len(item) != 2
        or not _commitment_name(item[0])
        or not _is_sha256(item[1])
        for item in items
    ):
        _fail("fresh_chain_commitments_invalid")
    normalized = tuple(sorted(items))
    if len({name for name, _ in normalized}) != len(normalized):
        _fail("fresh_chain_commitments_invalid")
    return normalized


def require_sha256(value: object, code: str = "fresh_chain_digest_invalid") -> str:
    if not _is_sha256(value):
        _fail(code)
    return value


def require_identifier(value: object, code: str = "fresh_chain_identifier_invalid") -> str:
    if not _identifier(value):
        _fail(code)
    return value


def require_stage(value: object) -> FreshChainStage:
    if type(value) is not str or value not in FRESH_CHAIN_STAGES:
        _fail("fresh_chain_stage_unknown")
    return value  # type: ignore[return-value]


def require_failure_disposition(value: object) -> FreshChainFailureDisposition:
    if type(value) is FreshChainFailureDisposition:
        return value
    if type(value) is str:
        try:
            return FreshChainFailureDisposition(value)
        except ValueError:
            pass
    _fail("fresh_chain_failure_disposition_invalid")


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _identifier(value: object) -> bool:
    return (
        type(value) is str and bool(value.strip()) and value == value.strip() and len(value) <= 512
    )


def _commitment_name(value: object) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= 128
        and value[0].isalnum()
        and all(character.isalnum() or character in "_.-" for character in value)
    )


def _fail(code: str) -> None:
    raise FreshChainLedgerError(code) from None


__all__ = (
    "CleanupBinding",
    "FRESH_CHAIN_CANARY_KIND",
    "FRESH_CHAIN_CALL_FAILURE_SCHEMA_VERSION",
    "FRESH_CHAIN_CASE_ID",
    "FRESH_CHAIN_DISPATCH_STARTED_SCHEMA_VERSION",
    "FRESH_CHAIN_EVALUATION_FAILURE_COMMITMENT_KEYS",
    "FRESH_CHAIN_EXPECTED_PHYSICAL_CALL_COUNT",
    "FRESH_CHAIN_EXTRACTION_FAILURE_COMMITMENT_KEYS",
    "FRESH_CHAIN_FAILED_TERMINAL_SCHEMA_VERSION",
    "FRESH_CHAIN_LEDGER_AUTHENTICATION",
    "FRESH_CHAIN_RUNTIME_TRANSPORT",
    "FRESH_CHAIN_STAGES",
    "FreshChainFailureDisposition",
    "FreshChainLedgerError",
    "FreshChainPlan",
    "FreshChainSnapshot",
    "FreshChainStage",
    "FreshChainStageRecord",
    "RetrievalHandoff",
    "TerminalOutcome",
    "TokenUsage",
    "failure_commitment_keys",
    "fresh_chain_call_failure_sha256",
    "fresh_chain_dispatch_started_sha256",
    "fresh_chain_failed_terminal_outcome_sha256",
    "provider_disposition_sha256",
)
