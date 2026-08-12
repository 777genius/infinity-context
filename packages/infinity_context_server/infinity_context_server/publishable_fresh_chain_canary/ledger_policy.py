"""Pure ordered-transition policy for fresh-chain ledger events."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import final

from .ledger_models import (
    FRESH_CHAIN_STAGES,
    CleanupBinding,
    FreshChainFailureDisposition,
    FreshChainPlan,
    FreshChainStage,
    FreshChainStageRecord,
    RetrievalHandoff,
    TerminalOutcome,
    TokenUsage,
    canonical_sha256,
    failure_commitment_keys,
    fresh_chain_call_failure_sha256,
    fresh_chain_dispatch_started_sha256,
    fresh_chain_failed_terminal_outcome_sha256,
    normalize_commitments,
    provider_disposition_sha256,
    require_failure_disposition,
    require_identifier,
    require_sha256,
    require_stage,
)

_MAX_ABSENCE_PROOFS = 32
_EXTRACTION_RESULT_KEYS = {
    "admission_commitment_sha256",
    "operation_id_sha256",
    "output_text_sha256",
    "request_body_sha256",
    "run_identity_commitment_sha256",
    "runtime_binding_commitment_sha256",
    "scope_sha256",
    "source_projection_commitment_sha256",
    "unit_identity_sha256",
    "unit_sha256",
}
_EVALUATION_RESULT_KEYS = {
    "bridge_intent_sha256",
    "encrypted_output_sha256",
    "output_text_sha256",
    "request_body_sha256",
    "response_body_sha256",
}
_HANDOFF_KEYS = {
    "extraction_intent_sha256",
    "handoff_sha256",
    "memory_count_sha256",
    "retrieval_material_sha256",
    "source_commitment_sha256",
    "source_projection_commitment_sha256",
}


@dataclass(slots=True)
class FreshChainProjection:
    stages: list[FreshChainStageRecord]
    source_projection_commitment_sha256: str | None = None
    retrieval_handoff: RetrievalHandoff | None = None
    abort_reason_sha256: str | None = None
    cleanup: CleanupBinding | None = None
    terminal_outcome: TerminalOutcome | None = None

    @classmethod
    def initial(cls) -> FreshChainProjection:
        return cls([FreshChainStageRecord(stage=stage) for stage in FRESH_CHAIN_STAGES])

    def copy(self) -> FreshChainProjection:
        return FreshChainProjection(
            list(self.stages),
            self.source_projection_commitment_sha256,
            self.retrieval_handoff,
            self.abort_reason_sha256,
            self.cleanup,
            self.terminal_outcome,
        )


@final
class FreshChainLedgerPolicy:
    """Fail-closed state machine independent of SQLite and provider adapters."""

    __slots__ = ("_plan",)

    def __init__(self, plan: FreshChainPlan) -> None:
        self._plan = plan

    def apply_event(
        self,
        projection: FreshChainProjection,
        event_kind: object,
        stage_value: object,
        payload: object,
    ) -> None:
        if type(payload) is not dict or type(event_kind) is not str:
            _fail("fresh_chain_event_malformed")
        if event_kind == "source_projection_bound":
            self._apply_source_projection_bound(projection, stage_value, payload)
        elif event_kind == "intent":
            self._apply_intent(projection, stage_value, payload)
        elif event_kind == "authenticated_pre_call_absence":
            self._apply_absence(projection, stage_value, payload)
        elif event_kind == "dispatch_started":
            self._apply_dispatch_started(projection, stage_value, payload)
        elif event_kind == "ambiguous_outcome":
            self._apply_ambiguity(projection, stage_value, payload)
        elif event_kind in {"success", "failure"}:
            self._apply_result(projection, event_kind, stage_value, payload)
        elif event_kind == "retrieval_handoff":
            self._apply_handoff(projection, stage_value, payload)
        elif event_kind == "local_abort":
            self._apply_local_abort(projection, stage_value, payload)
        elif event_kind == "cleanup":
            self._apply_cleanup(projection, stage_value, payload)
        elif event_kind == "terminal_outcome":
            self._apply_terminal(projection, stage_value, payload)
        else:
            _fail("fresh_chain_event_unknown")

    def _apply_source_projection_bound(
        self,
        projection: FreshChainProjection,
        stage_value: object,
        payload: dict[str, object],
    ) -> None:
        _exact_keys(
            payload,
            {
                "namespace_commitment_sha256",
                "source_commitment_sha256",
                "source_projection_commitment_sha256",
                "publishable",
            },
        )
        if stage_value is not None or payload["publishable"] is not False:
            _fail("fresh_chain_event_malformed")
        namespace = require_sha256(payload["namespace_commitment_sha256"])
        source = require_sha256(payload["source_commitment_sha256"])
        source_projection = require_sha256(payload["source_projection_commitment_sha256"])
        existing = projection.source_projection_commitment_sha256
        if existing is not None:
            if (
                existing == source_projection
                and namespace == self._plan.namespace_commitment_sha256
                and source == self._plan.source_commitment_sha256
            ):
                _fail("fresh_chain_source_projection_duplicate")
            _fail("fresh_chain_source_projection_conflict")
        if (
            namespace != self._plan.namespace_commitment_sha256
            or source != self._plan.source_commitment_sha256
        ):
            _fail("fresh_chain_source_projection_conflict")
        if (
            projection.retrieval_handoff is not None
            or projection.cleanup is not None
            or projection.terminal_outcome is not None
            or any(record.status != "not_started" for record in projection.stages)
        ):
            _fail("fresh_chain_source_projection_out_of_order")
        projection.source_projection_commitment_sha256 = source_projection

    def _apply_intent(
        self,
        projection: FreshChainProjection,
        stage_value: object,
        payload: dict[str, object],
    ) -> None:
        _exact_keys(
            payload,
            {
                "stage",
                "intent_sha256",
                "request_sha256",
                "input_authority_sha256",
                "commitments",
                "publishable",
            },
        )
        stage = require_stage(stage_value)
        if payload["stage"] != stage or payload["publishable"] is not False:
            _fail("fresh_chain_event_malformed")
        intent = require_sha256(payload["intent_sha256"])
        request = require_sha256(payload["request_sha256"])
        input_authority = require_sha256(payload["input_authority_sha256"])
        commitments = normalize_commitments(payload["commitments"])
        if projection.terminal_outcome is not None or projection.cleanup is not None:
            _fail("fresh_chain_ledger_terminal")
        if projection.source_projection_commitment_sha256 is None:
            _fail("fresh_chain_source_projection_missing")
        existing = next((record for record in projection.stages if record.stage == stage), None)
        if existing is not None and existing.intent_sha256 is not None:
            if (
                existing.intent_sha256 == intent
                and existing.request_sha256 == request
                and existing.input_authority_sha256 == input_authority
                and existing.intent_commitments == commitments
            ):
                _fail("fresh_chain_call_duplicate")
            _fail("fresh_chain_intent_replay_conflict")
        if any(record.status == "pending" for record in projection.stages):
            _fail("fresh_chain_call_out_of_order")
        if any(record.status == "failed" for record in projection.stages):
            _fail("fresh_chain_ledger_failed")
        current_index = next(
            (
                index
                for index, record in enumerate(projection.stages)
                if record.status == "not_started"
            ),
            None,
        )
        if current_index is None or projection.stages[current_index].stage != stage:
            _fail("fresh_chain_call_out_of_order")
        if any(record.intent_sha256 == intent for record in projection.stages):
            _fail("fresh_chain_call_duplicate")
        if (
            stage == "mem0_extraction"
            and input_authority != projection.source_projection_commitment_sha256
        ):
            _fail("fresh_chain_extraction_source_conflict")
        if stage == "infinity_answer":
            if projection.retrieval_handoff is None:
                _fail("fresh_chain_retrieval_handoff_missing")
            if input_authority != self._plan.source_commitment_sha256:
                _fail("fresh_chain_infinity_source_conflict")
        if stage == "mem0_answer" and (
            projection.retrieval_handoff is None
            or input_authority != projection.retrieval_handoff.retrieval_authority_sha256
        ):
            _fail("fresh_chain_mem0_retrieval_conflict")
        if stage in {"infinity_judge", "mem0_judge"}:
            answer = projection.stages[current_index - 1]
            if answer.status != "succeeded" or input_authority != answer.result_sha256:
                _fail("fresh_chain_judge_answer_conflict")
        expected_commitments = {
            "namespace_commitment_sha256": self._plan.namespace_commitment_sha256,
            "source_commitment_sha256": self._plan.source_commitment_sha256,
            "source_projection_commitment_sha256": (projection.source_projection_commitment_sha256),
        }
        if stage == "mem0_answer":
            assert projection.retrieval_handoff is not None
            handoff_commitments = dict(projection.retrieval_handoff.commitments)
            expected_commitments["retrieval_handoff_sha256"] = handoff_commitments.get(
                "handoff_sha256", ""
            )
        if dict(commitments) != expected_commitments:
            _fail("fresh_chain_intent_commitments_invalid")
        projection.stages[current_index] = replace(
            projection.stages[current_index],
            status="pending",
            intent_sha256=intent,
            request_sha256=request,
            input_authority_sha256=input_authority,
            intent_commitments=commitments,
        )

    def _apply_absence(
        self,
        projection: FreshChainProjection,
        stage_value: object,
        payload: dict[str, object],
    ) -> None:
        _exact_keys(payload, {"stage", "intent_sha256", "absence_sha256"})
        _stage, record, index = self._pending(projection, stage_value, payload)
        absence = require_sha256(payload["absence_sha256"])
        if record.dispatch_started_sha256 is not None:
            _fail("fresh_chain_authenticated_absence_out_of_order")
        if any(absence in other.authenticated_absence_sha256 for other in projection.stages):
            _fail("fresh_chain_authenticated_absence_duplicate")
        if len(record.authenticated_absence_sha256) >= _MAX_ABSENCE_PROOFS:
            _fail("fresh_chain_authenticated_absence_limit")
        projection.stages[index] = replace(
            record,
            authenticated_absence_sha256=record.authenticated_absence_sha256 + (absence,),
        )

    def _apply_dispatch_started(
        self,
        projection: FreshChainProjection,
        stage_value: object,
        payload: dict[str, object],
    ) -> None:
        _exact_keys(
            payload,
            {
                "stage",
                "intent_sha256",
                "authenticated_absence_sha256",
                "dispatch_started_sha256",
            },
        )
        stage, record, index = self._pending(projection, stage_value, payload)
        intent = require_sha256(payload["intent_sha256"])
        absence = require_sha256(payload["authenticated_absence_sha256"])
        dispatch_started = require_sha256(payload["dispatch_started_sha256"])
        expected = fresh_chain_dispatch_started_sha256(
            stage=stage,
            intent_sha256=intent,
            authenticated_absence_sha256=absence,
        )
        if record.dispatch_started_sha256 is not None:
            if record.dispatch_started_sha256 == dispatch_started:
                _fail("fresh_chain_dispatch_started_duplicate")
            _fail("fresh_chain_dispatch_started_conflict")
        if record.ambiguity_sha256 is not None:
            _fail("fresh_chain_dispatch_started_after_ambiguity")
        if absence not in record.authenticated_absence_sha256:
            _fail("fresh_chain_dispatch_started_absence_missing")
        if dispatch_started != expected or any(
            other.dispatch_started_sha256 == dispatch_started
            for other in projection.stages
            if other is not record
        ):
            _fail("fresh_chain_dispatch_started_conflict")
        projection.stages[index] = replace(
            record,
            dispatch_started_sha256=dispatch_started,
        )

    def _apply_ambiguity(
        self,
        projection: FreshChainProjection,
        stage_value: object,
        payload: dict[str, object],
    ) -> None:
        _exact_keys(payload, {"stage", "intent_sha256", "ambiguity_sha256"})
        _stage, record, index = self._pending(projection, stage_value, payload)
        ambiguity = require_sha256(payload["ambiguity_sha256"])
        if record.ambiguity_sha256 is not None:
            if record.ambiguity_sha256 == ambiguity:
                _fail("fresh_chain_ambiguous_outcome_duplicate")
            _fail("fresh_chain_ambiguous_outcome_conflict")
        projection.stages[index] = replace(record, ambiguity_sha256=ambiguity)

    def _apply_result(
        self,
        projection: FreshChainProjection,
        event_kind: str,
        stage_value: object,
        payload: dict[str, object],
    ) -> None:
        result_field = "result_sha256" if event_kind == "success" else "failure_sha256"
        expected_payload_keys = {
            "stage",
            "intent_sha256",
            result_field,
            "receipt_id",
            "receipt_sha256",
            "token_usage",
            "commitments",
            "result_publishable",
            "receipt_publishable",
        }
        if event_kind == "failure":
            expected_payload_keys.add("provider_disposition")
        _exact_keys(
            payload,
            expected_payload_keys,
        )
        stage = require_stage(stage_value)
        usage = _token_usage(payload.get("token_usage"))
        commitments = normalize_commitments(payload.get("commitments"))
        provider_disposition = (
            require_failure_disposition(payload.get("provider_disposition"))
            if event_kind == "failure"
            else None
        )
        existing = next((record for record in projection.stages if record.stage == stage), None)
        if existing is not None and existing.terminal:
            same = (
                payload.get("stage") == stage
                and payload.get("intent_sha256") == existing.intent_sha256
                and payload.get(result_field)
                == (existing.result_sha256 if event_kind == "success" else existing.failure_sha256)
                and provider_disposition == existing.provider_disposition
                and payload.get("receipt_id") == existing.receipt_id
                and payload.get("receipt_sha256") == existing.receipt_sha256
                and usage == existing.token_usage
                and commitments == existing.result_commitments
                and payload.get("result_publishable") is False
                and payload.get("receipt_publishable") is False
                and (event_kind == "success") == (existing.status == "succeeded")
            )
            if same:
                _fail("fresh_chain_call_duplicate")
            _fail("fresh_chain_result_replay_conflict")
        _stage, record, index = self._pending(projection, stage_value, payload)
        if not record.authenticated_absence_sha256:
            _fail("fresh_chain_authenticated_absence_missing")
        if record.dispatch_started_sha256 is None:
            _fail("fresh_chain_dispatch_started_missing")
        if (
            payload["result_publishable"] is not False
            or payload["receipt_publishable"] is not False
        ):
            _fail("fresh_chain_publishable_forbidden")
        outcome_sha256 = require_sha256(payload[result_field])
        receipt_id = require_identifier(payload["receipt_id"])
        receipt = require_sha256(payload["receipt_sha256"])
        if any(
            other.receipt_id == receipt_id or other.receipt_sha256 == receipt
            for other in projection.stages
            if other.receipt_id is not None
        ):
            _fail("fresh_chain_receipt_duplicate")
        if event_kind == "success":
            expected_keys = (
                _EXTRACTION_RESULT_KEYS if stage == "mem0_extraction" else _EVALUATION_RESULT_KEYS
            )
            result_commitments = dict(commitments)
            if (
                set(result_commitments) != expected_keys
                or result_commitments.get("request_body_sha256") != record.request_sha256
                or (
                    stage == "mem0_extraction"
                    and result_commitments.get("source_projection_commitment_sha256")
                    != projection.source_projection_commitment_sha256
                )
            ):
                _fail("fresh_chain_result_commitments_invalid")
        else:
            assert type(provider_disposition) is FreshChainFailureDisposition
            failure_commitments = dict(commitments)
            if (
                set(failure_commitments) != failure_commitment_keys(stage)
                or failure_commitments.get("request_body_sha256") != record.request_sha256
                or failure_commitments.get("provider_disposition_sha256")
                != provider_disposition_sha256(provider_disposition)
                or (
                    stage == "mem0_extraction"
                    and failure_commitments.get("source_projection_commitment_sha256")
                    != projection.source_projection_commitment_sha256
                )
            ):
                _fail("fresh_chain_failure_commitments_invalid")
            expected_failure = fresh_chain_call_failure_sha256(
                stage=stage,
                intent_sha256=record.intent_sha256,
                provider_disposition=provider_disposition,
                receipt_id=receipt_id,
                physical_receipt_sha256=receipt,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                commitments=commitments,
            )
            if outcome_sha256 != expected_failure:
                _fail("fresh_chain_failure_binding_invalid")
        projection.stages[index] = replace(
            record,
            status="succeeded" if event_kind == "success" else "failed",
            result_sha256=outcome_sha256 if event_kind == "success" else None,
            failure_sha256=outcome_sha256 if event_kind == "failure" else None,
            provider_disposition=provider_disposition,
            receipt_id=receipt_id,
            receipt_sha256=receipt,
            token_usage=usage,
            result_commitments=commitments,
        )

    def _apply_handoff(
        self,
        projection: FreshChainProjection,
        stage_value: object,
        payload: dict[str, object],
    ) -> None:
        _exact_keys(
            payload,
            {
                "extraction_result_sha256",
                "extraction_receipt_sha256",
                "namespace_commitment_sha256",
                "memory_authority_sha256",
                "retrieval_authority_sha256",
                "memory_count",
                "commitments",
                "publishable",
            },
        )
        if stage_value is not None or payload["publishable"] is not False:
            _fail("fresh_chain_event_malformed")
        extraction = projection.stages[0]
        commitments = normalize_commitments(payload["commitments"])
        handoff_commitments = dict(commitments)
        if (
            set(handoff_commitments) != _HANDOFF_KEYS
            or handoff_commitments.get("extraction_intent_sha256") != extraction.intent_sha256
            or handoff_commitments.get("source_commitment_sha256")
            != self._plan.source_commitment_sha256
            or handoff_commitments.get("source_projection_commitment_sha256")
            != projection.source_projection_commitment_sha256
        ):
            _fail("fresh_chain_retrieval_handoff_commitments_invalid")
        candidate = RetrievalHandoff(
            extraction_result_sha256=require_sha256(payload["extraction_result_sha256"]),
            extraction_receipt_sha256=require_sha256(payload["extraction_receipt_sha256"]),
            namespace_commitment_sha256=require_sha256(payload["namespace_commitment_sha256"]),
            memory_authority_sha256=require_sha256(payload["memory_authority_sha256"]),
            retrieval_authority_sha256=require_sha256(payload["retrieval_authority_sha256"]),
            memory_count=payload["memory_count"],  # type: ignore[arg-type]
            commitments=commitments,
        )
        if projection.retrieval_handoff is not None:
            if projection.retrieval_handoff == candidate:
                _fail("fresh_chain_retrieval_handoff_duplicate")
            _fail("fresh_chain_retrieval_handoff_conflict")
        if (
            projection.terminal_outcome is not None
            or extraction.status != "succeeded"
            or any(record.status != "not_started" for record in projection.stages[1:])
        ):
            _fail("fresh_chain_retrieval_handoff_out_of_order")
        if (
            candidate.extraction_result_sha256 != extraction.result_sha256
            or candidate.extraction_receipt_sha256 != extraction.receipt_sha256
            or candidate.namespace_commitment_sha256 != self._plan.namespace_commitment_sha256
        ):
            _fail("fresh_chain_retrieval_handoff_conflict")
        projection.retrieval_handoff = candidate

    def _apply_cleanup(
        self,
        projection: FreshChainProjection,
        stage_value: object,
        payload: dict[str, object],
    ) -> None:
        _exact_keys(
            payload,
            {
                "namespace_commitment_sha256",
                "cleanup_authority_sha256",
                "receipt_id",
                "receipt_sha256",
                "outcome_sha256",
                "deleted",
                "operation_count",
                "residual_count",
                "publishable",
            },
        )
        if stage_value is not None or payload["publishable"] is not False:
            _fail("fresh_chain_event_malformed")
        candidate = CleanupBinding(
            namespace_commitment_sha256=require_sha256(payload["namespace_commitment_sha256"]),
            cleanup_authority_sha256=require_sha256(payload["cleanup_authority_sha256"]),
            receipt_id=require_identifier(payload["receipt_id"]),
            receipt_sha256=require_sha256(payload["receipt_sha256"]),
            outcome_sha256=require_sha256(payload["outcome_sha256"]),
            deleted=payload["deleted"],  # type: ignore[arg-type]
            operation_count=payload["operation_count"],  # type: ignore[arg-type]
            residual_count=payload["residual_count"],  # type: ignore[arg-type]
        )
        if projection.cleanup is not None:
            if projection.cleanup == candidate:
                _fail("fresh_chain_cleanup_duplicate")
            _fail("fresh_chain_cleanup_conflict")
        if projection.terminal_outcome is not None or not (
            all(record.status == "succeeded" for record in projection.stages)
            or any(record.status == "failed" for record in projection.stages)
            or projection.abort_reason_sha256 is not None
        ):
            _fail("fresh_chain_cleanup_out_of_order")
        if candidate.namespace_commitment_sha256 != self._plan.namespace_commitment_sha256:
            _fail("fresh_chain_cleanup_namespace_conflict")
        if any(
            record.receipt_id == candidate.receipt_id
            or record.receipt_sha256 == candidate.receipt_sha256
            for record in projection.stages
        ):
            _fail("fresh_chain_receipt_duplicate")
        projection.cleanup = candidate

    def _apply_local_abort(
        self,
        projection: FreshChainProjection,
        stage_value: object,
        payload: dict[str, object],
    ) -> None:
        _exact_keys(payload, {"reason_sha256", "publishable"})
        reason = require_sha256(payload["reason_sha256"])
        extraction = projection.stages[0]
        authenticated_extraction_boundary = extraction.status == "succeeded" or (
            extraction.status == "pending"
            and extraction.dispatch_started_sha256 is not None
            and all(record.status == "not_started" for record in projection.stages[1:])
        )
        if (
            stage_value is not None
            or payload["publishable"] is not False
            or projection.abort_reason_sha256 is not None
            or projection.cleanup is not None
            or projection.terminal_outcome is not None
            or projection.source_projection_commitment_sha256 is None
            or not authenticated_extraction_boundary
        ):
            _fail("fresh_chain_local_abort_invalid")
        projection.abort_reason_sha256 = reason

    def _apply_terminal(
        self,
        projection: FreshChainProjection,
        stage_value: object,
        payload: dict[str, object],
    ) -> None:
        _exact_keys(
            payload,
            {"status", "outcome_sha256", "activation_evidence_only", "publishable"},
        )
        outcome = TerminalOutcome(
            status=payload.get("status"),  # type: ignore[arg-type]
            outcome_sha256=require_sha256(payload.get("outcome_sha256")),
        )
        if projection.terminal_outcome is not None:
            if projection.terminal_outcome == outcome:
                _fail("fresh_chain_terminal_outcome_duplicate")
            _fail("fresh_chain_terminal_outcome_conflict")
        if (
            stage_value is not None
            or projection.cleanup is None
            or payload["activation_evidence_only"] is not True
            or payload["publishable"] is not False
            or payload["status"] not in {"succeeded", "failed"}
        ):
            _fail("fresh_chain_terminal_outcome_invalid")
        status = payload["status"]
        if status == "succeeded" and not all(
            record.status == "succeeded" for record in projection.stages
        ):
            _fail("fresh_chain_terminal_outcome_invalid")
        if status == "failed" and not (
            any(record.status == "failed" for record in projection.stages)
            or projection.abort_reason_sha256 is not None
        ):
            _fail("fresh_chain_terminal_outcome_invalid")
        if status == "succeeded":
            expected_outcome = canonical_sha256(
                {
                    "activation_evidence_only": True,
                    "cleanup": projection.cleanup.material(),
                    "ordered_receipt_ids": [record.receipt_id for record in projection.stages],
                    "plan_commitment_sha256": self._plan.commitment_sha256,
                    "publishable": False,
                    "retrieval_handoff": projection.retrieval_handoff.material()
                    if projection.retrieval_handoff is not None
                    else None,
                    "source_projection_commitment_sha256": (
                        projection.source_projection_commitment_sha256
                    ),
                }
            )
            if outcome.outcome_sha256 != expected_outcome:
                _fail("fresh_chain_terminal_outcome_conflict")
        else:
            assert projection.cleanup is not None
            expected_outcome = fresh_chain_failed_terminal_outcome_sha256(
                plan=self._plan,
                source_projection_commitment_sha256=require_sha256(
                    projection.source_projection_commitment_sha256
                ),
                stages=tuple(projection.stages),
                retrieval_handoff=projection.retrieval_handoff,
                abort_reason_sha256=projection.abort_reason_sha256,
                cleanup=projection.cleanup,
            )
            if outcome.outcome_sha256 != expected_outcome:
                _fail("fresh_chain_terminal_outcome_conflict")
        projection.terminal_outcome = outcome

    def _pending(
        self,
        projection: FreshChainProjection,
        stage_value: object,
        payload: dict[str, object],
    ) -> tuple[FreshChainStage, FreshChainStageRecord, int]:
        stage = require_stage(stage_value)
        if payload.get("stage") != stage:
            _fail("fresh_chain_event_malformed")
        record = next((record for record in projection.stages if record.stage == stage), None)
        if record is None or record.status != "pending":
            _fail("fresh_chain_call_missing_or_duplicate")
        if payload.get("intent_sha256") != record.intent_sha256:
            _fail("fresh_chain_intent_replay_conflict")
        return stage, record, projection.stages.index(record)


def _token_usage(value: object) -> TokenUsage:
    _exact_keys(value, {"input_tokens", "output_tokens", "total_tokens"})
    try:
        return TokenUsage(
            input_tokens=value["input_tokens"],  # type: ignore[index]
            output_tokens=value["output_tokens"],  # type: ignore[index]
            total_tokens=value["total_tokens"],  # type: ignore[index]
        )
    except (KeyError, TypeError, ValueError):
        _fail("fresh_chain_token_usage_invalid")


def _exact_keys(value: object, expected: set[str]) -> None:
    if type(value) is not dict or set(value) != expected:
        _fail("fresh_chain_event_malformed")


def _fail(code: str) -> None:
    from .ledger_models import FreshChainLedgerError

    raise FreshChainLedgerError(code) from None


__all__ = ("FreshChainLedgerPolicy", "FreshChainProjection")
