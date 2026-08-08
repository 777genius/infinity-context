"""Receive canonical auto-memory captures."""

from __future__ import annotations

from datetime import UTC, datetime

from infinity_context_core.application.capture_policy import (
    CaptureAdmissionService,
    capture_idempotency_key,
    capture_payload_hash,
)
from infinity_context_core.application.dto import CaptureResult, ReceiveCaptureCommand
from infinity_context_core.domain.capture import (
    CanonicalCapture,
    CaptureActorRole,
    CaptureSensitivity,
    CaptureSourceKind,
    CaptureStatus,
    ConsolidationStatus,
    MemoryCaptureId,
    SourceAuthority,
)
from infinity_context_core.domain.entities import DataClassification, TrustLevel
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryIngressLimitError,
    MemoryValidationError,
)
from infinity_context_core.domain.events import OutboxEvent
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_MAX_METADATA_VALUE_CHARS = 500
_SENSITIVE_METADATA_KEY_MARKERS = ("token", "secret", "key", "password", "authorization")


class ReceiveCaptureUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
        admission: CaptureAdmissionService | None = None,
        max_pending_captures_per_memory_scope: int = 5_000,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._admission = admission or CaptureAdmissionService()
        self._max_pending_captures_per_memory_scope = max(1, max_pending_captures_per_memory_scope)

    async def execute(self, command: ReceiveCaptureCommand) -> CaptureResult:
        now = self._clock.now()
        admitted = self._admission.admit(command.text)
        if not admitted.accepted:
            raise MemoryValidationError(f"Capture rejected: {admitted.reason}")
        idempotency_key = command.idempotency_key or capture_idempotency_key(
            source_agent=command.source_agent,
            source_kind=command.source_kind,
            event_type=command.event_type,
            source_event_id=command.source_event_id,
            client_instance_id=command.client_instance_id,
            text=admitted.text,
        )
        safe_metadata = _safe_metadata(command.metadata)
        request_fingerprint = _capture_request_fingerprint(
            command,
            admitted_text=admitted.text,
            safe_metadata=safe_metadata,
        )
        async with self._uow_factory() as uow:
            existing = await uow.captures.get_by_idempotency_key(
                space_id=str(command.space_id),
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                _require_exact_capture_replay(existing, request_fingerprint)
                return CaptureResult(capture=existing, duplicate=True)

            pending_count = await uow.captures.count_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                status=CaptureStatus.ACCEPTED.value,
                consolidation_statuses=(
                    ConsolidationStatus.PENDING.value,
                    ConsolidationStatus.RUNNING.value,
                    ConsolidationStatus.RETRY_PENDING.value,
                ),
            )
            if pending_count >= self._max_pending_captures_per_memory_scope:
                raise MemoryIngressLimitError("Pending capture limit reached")

            capture = CanonicalCapture.create(
                capture_id=MemoryCaptureId(self._ids.new_id("cap")),
                space_id=command.space_id,
                memory_scope_id=command.memory_scope_id,
                thread_id=command.thread_id,
                source_agent=command.source_agent,
                source_kind=_source_kind(command.source_kind),
                event_type=command.event_type,
                actor_role=_actor_role(command.actor_role),
                text=admitted.text,
                evidence_refs=command.evidence_refs,
                payload_hash=request_fingerprint,
                idempotency_key=idempotency_key,
                trust_level=_trust_level(command.trust_level),
                source_authority=_source_authority(command.source_authority),
                sensitivity=_sensitivity(command.sensitivity, redacted=admitted.redacted),
                data_classification=_data_classification(command.data_classification),
                occurred_at=_safe_occurred_at(command.occurred_at, now),
                now=now,
                metadata={
                    **safe_metadata,
                    "admission_reason": admitted.reason,
                    "client_minimization_version": str(
                        safe_metadata.get("client_minimization_version", "")
                    ),
                },
                consolidation_status=(
                    ConsolidationStatus.PENDING
                    if command.consolidate
                    else ConsolidationStatus.NOT_REQUIRED
                ),
                source_event_id=command.source_event_id,
                source_actor_external_ref=command.source_actor_external_ref,
                client_instance_id=command.client_instance_id,
                agent_session_external_ref=command.agent_session_external_ref,
                turn_external_ref=command.turn_external_ref,
                parent_capture_id=MemoryCaptureId(command.parent_capture_id)
                if command.parent_capture_id
                else None,
                sequence_index=command.sequence_index,
                trace_id=command.trace_id,
            )
            saved = await uow.captures.create(capture)
            if command.consolidate:
                await uow.outbox.enqueue(
                    OutboxEvent(
                        event_type="capture.consolidate",
                        aggregate_type="capture",
                        aggregate_id=str(saved.id),
                        workload_class="auto_memory",
                        fairness_key=str(saved.memory_scope_id),
                        payload={
                            "schema_version": 1,
                            "capture_id": str(saved.id),
                            "space_id": str(saved.space_id),
                            "memory_scope_id": str(saved.memory_scope_id),
                            "trace_id": saved.trace_id,
                        },
                    )
                )
            try:
                await uow.commit()
            except MemoryConflictError:
                existing = await uow.captures.get_by_idempotency_key(
                    space_id=str(command.space_id),
                    idempotency_key=idempotency_key,
                )
                if existing is None:
                    raise
                _require_exact_capture_replay(existing, request_fingerprint)
                return CaptureResult(capture=existing, duplicate=True)
        return CaptureResult(capture=saved)


def _source_kind(value: str) -> CaptureSourceKind:
    try:
        return CaptureSourceKind(value)
    except ValueError as exc:
        raise MemoryValidationError("Unknown capture source_kind") from exc


def _actor_role(value: str) -> CaptureActorRole:
    try:
        return CaptureActorRole(value)
    except ValueError as exc:
        raise MemoryValidationError("Unknown capture actor_role") from exc


def _trust_level(value: str) -> TrustLevel:
    try:
        return TrustLevel(value)
    except ValueError as exc:
        raise MemoryValidationError("Unknown capture trust_level") from exc


def _source_authority(value: str) -> SourceAuthority:
    try:
        return SourceAuthority(value)
    except ValueError as exc:
        raise MemoryValidationError("Unknown capture source_authority") from exc


def _sensitivity(value: str, *, redacted: bool) -> CaptureSensitivity:
    if redacted:
        return CaptureSensitivity.HIGH
    try:
        return CaptureSensitivity(value)
    except ValueError as exc:
        raise MemoryValidationError("Unknown capture sensitivity") from exc


def _data_classification(value: str) -> DataClassification:
    try:
        return DataClassification(value)
    except ValueError as exc:
        raise MemoryValidationError("Unknown capture data_classification") from exc


def _safe_occurred_at(value: datetime | None, now: datetime) -> datetime:
    if value is None:
        return now
    if _as_utc(value) > _as_utc(now):
        return now
    return value


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _safe_metadata(metadata: dict[str, object] | None) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in dict(metadata or {}).items():
        key_text = str(key)[:80]
        lowered = key_text.lower()
        if any(marker in lowered for marker in _SENSITIVE_METADATA_KEY_MARKERS):
            continue
        if isinstance(value, str):
            safe[key_text] = value[:_MAX_METADATA_VALUE_CHARS]
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[key_text] = value
    return safe


def _capture_request_fingerprint(
    command: ReceiveCaptureCommand,
    *,
    admitted_text: str,
    safe_metadata: dict[str, object],
) -> str:
    return capture_payload_hash(
        str(command.space_id),
        str(command.memory_scope_id),
        str(command.thread_id) if command.thread_id else None,
        command.source_agent,
        command.source_kind,
        command.event_type,
        command.actor_role,
        admitted_text,
        tuple(command.evidence_refs),
        command.trust_level,
        command.source_authority,
        command.sensitivity,
        command.data_classification,
        command.occurred_at.isoformat() if command.occurred_at else None,
        tuple(sorted(safe_metadata.items())),
        command.source_event_id,
        command.source_actor_external_ref,
        command.client_instance_id,
        command.agent_session_external_ref,
        command.turn_external_ref,
        command.parent_capture_id,
        command.sequence_index,
        command.trace_id,
        command.consolidate,
    )


def _require_exact_capture_replay(
    existing: CanonicalCapture,
    request_fingerprint: str,
) -> None:
    if existing.payload_hash != request_fingerprint:
        raise MemoryConflictError("Capture idempotency key was reused for a different request")
