"""Consolidate captures into review-gated suggestions."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from memo_stack_core.application.auto_apply import AutoApplySafePolicy
from memo_stack_core.application.auto_memory import MemoryAdmissionService
from memo_stack_core.application.dto import CaptureResult, ConsolidateCaptureCommand
from memo_stack_core.application.extractor import (
    RuleBasedMemoryExtractor,
    validate_extractor_candidates,
)
from memo_stack_core.domain.capture import ConsolidationStatus
from memo_stack_core.domain.entities import (
    FactStatus,
    MemoryFact,
    MemoryFactId,
    MemorySuggestion,
    MemorySuggestionId,
    SourceRef,
    SuggestionOperation,
)
from memo_stack_core.domain.errors import (
    MemoryInfrastructureError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from memo_stack_core.domain.events import OutboxEvent
from memo_stack_core.domain.taxonomy import DefaultTaxonomyPolicy, TaxonomyPolicyPort
from memo_stack_core.ports.auto_memory import (
    CandidateOperation,
    MemoryExtractorPort,
    SourceProvenance,
)
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort

RESOLVER_VERSION = "capture-resolver-v1"


class ConsolidateCaptureUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
        extractor: MemoryExtractorPort | None = None,
        admission: MemoryAdmissionService | None = None,
        auto_apply_policy: AutoApplySafePolicy | None = None,
        taxonomy: TaxonomyPolicyPort | None = None,
        external_ai_enabled: bool = False,
        auto_apply_safe_enabled: bool = False,
        capture_consolidation_enabled: bool = True,
        max_pending_suggestions_per_profile: int = 500,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._extractor = extractor or RuleBasedMemoryExtractor()
        self._admission = admission or MemoryAdmissionService()
        self._auto_apply_policy = auto_apply_policy or AutoApplySafePolicy()
        self._taxonomy = taxonomy or DefaultTaxonomyPolicy()
        self._external_ai_enabled = external_ai_enabled
        self._auto_apply_safe_enabled = auto_apply_safe_enabled
        self._capture_consolidation_enabled = capture_consolidation_enabled
        self._max_pending_suggestions_per_profile = max(1, max_pending_suggestions_per_profile)

    async def execute(self, command: ConsolidateCaptureCommand) -> CaptureResult:
        now = self._clock.now()
        running = await self._claim_capture(command=command, now=now)
        if running.consolidation_status != ConsolidationStatus.RUNNING:
            return CaptureResult(capture=running)
        if not self._capture_consolidation_enabled:
            return await self._mark_skipped(
                capture_id=command.capture_id,
                reason="capture_policy_disabled",
            )

        provenance = SourceProvenance(
            source_type=f"capture:{running.source_kind.value}",
            source_id=str(running.id),
            trust_level=running.trust_level,
        )
        if self._extractor.requires_external_ai and not self._external_ai_enabled:
            return await self._mark_skipped(
                capture_id=command.capture_id,
                reason="external_ai_disabled",
            )

        try:
            raw_candidates = await self._extractor.extract_facts(
                text=running.text,
                source=provenance,
            )
            validation = validate_extractor_candidates(
                candidates=raw_candidates,
                source_text=running.text,
            )
        except MemoryInfrastructureError as exc:
            return await self._mark_retry_pending(
                capture_id=command.capture_id,
                code="extractor_infrastructure_unavailable",
                message=str(exc),
            )
        except MemoryValidationError as exc:
            return await self._mark_dead(
                capture_id=command.capture_id,
                code="extractor_invalid_output",
                message=str(exc),
            )

        if not validation.candidates:
            reason = "no_candidates" if not validation.rejected_codes else "no_valid_candidates"
            return await self._mark_skipped(capture_id=command.capture_id, reason=reason)

        now = self._clock.now()
        async with self._uow_factory() as uow:
            current = await uow.captures.get_for_update(command.capture_id)
            if current is None:
                raise MemoryNotFoundError("Capture not found")
            if current.consolidation_status != ConsolidationStatus.RUNNING and not command.force:
                return CaptureResult(capture=current)

            created_ids: list[str] = []
            auto_applied_ids: list[str] = []
            resolver_rejected_codes: list[str] = []
            pending_suggestion_count = await uow.suggestions.count_for_scope(
                space_id=str(current.space_id),
                profile_id=str(current.profile_id),
                status="pending",
            )
            seen_fingerprints: set[str] = set()
            touched_targets: set[str] = set()
            for candidate in validation.candidates:
                if candidate.operation_hint == CandidateOperation.NOOP:
                    resolver_rejected_codes.append("noop_candidate")
                    continue
                target_fact = None
                if candidate.operation_hint in {
                    CandidateOperation.UPDATE,
                    CandidateOperation.DELETE,
                }:
                    target_fact = await uow.facts.get_by_id(str(candidate.target_fact_id))
                    if target_fact is None:
                        resolver_rejected_codes.append("target_fact_not_found")
                        continue
                    if (
                        target_fact.space_id != current.space_id
                        or target_fact.profile_id != current.profile_id
                    ):
                        resolver_rejected_codes.append("target_fact_scope_mismatch")
                        continue
                    if target_fact.status != FactStatus.ACTIVE:
                        resolver_rejected_codes.append("target_fact_not_active")
                        continue
                    if (
                        candidate.target_fact_version is not None
                        and target_fact.version != candidate.target_fact_version
                    ):
                        resolver_rejected_codes.append("target_fact_stale_version")
                        continue
                    target_key = str(target_fact.id)
                    if target_key in touched_targets:
                        resolver_rejected_codes.append("target_fact_already_touched")
                        continue
                    touched_targets.add(target_key)
                decision = self._admission.decide(
                    source=provenance,
                    candidate=candidate,
                    allow_auto_promote=False,
                )
                if decision.outcome != "create_suggestion":
                    resolver_rejected_codes.append(f"admission_{decision.outcome}")
                    continue
                taxonomy = self._taxonomy.normalize(candidate)
                fingerprint = _candidate_fingerprint(
                    space_id=str(current.space_id),
                    profile_id=str(current.profile_id),
                    text=candidate.text,
                    operation=candidate.operation_hint.value,
                    target_fact_id=candidate.target_fact_id,
                    category=taxonomy.category,
                )
                if fingerprint in seen_fingerprints:
                    resolver_rejected_codes.append("duplicate_candidate_in_capture")
                    continue
                seen_fingerprints.add(fingerprint)
                active_duplicate = None
                if candidate.operation_hint in {CandidateOperation.ADD, CandidateOperation.UPDATE}:
                    active_duplicate = await _find_exact_active_duplicate(
                        uow,
                        space_id=str(current.space_id),
                        profile_id=str(current.profile_id),
                        thread_id=str(current.thread_id) if current.thread_id else None,
                        text=candidate.text,
                        kind=candidate.kind.value,
                    )
                if active_duplicate is not None:
                    resolver_rejected_codes.append("duplicate_active_fact")
                    continue
                duplicate = await uow.suggestions.find_pending_duplicate(
                    space_id=str(current.space_id),
                    profile_id=str(current.profile_id),
                    candidate_fingerprint=fingerprint,
                    operation=_suggestion_operation(candidate.operation_hint).value,
                    target_fact_id=candidate.target_fact_id,
                )
                if duplicate is not None:
                    resolver_rejected_codes.append("duplicate_pending_suggestion")
                    continue
                expires_at = _expires_at(now, taxonomy.ttl_policy.duration)
                source_refs = candidate.source_refs or (
                    SourceRef(
                        source_type=f"capture:{current.source_kind.value}",
                        source_id=str(current.id),
                        quote_preview=current.text[:240],
                    ),
                )
                auto_apply = self._auto_apply_policy.decide(
                    enabled=self._auto_apply_safe_enabled,
                    capture=current,
                    candidate=candidate,
                    ttl_policy=taxonomy.ttl_policy.name,
                    has_active_duplicate=False,
                    has_pending_duplicate=False,
                )
                if auto_apply.allowed:
                    fact = MemoryFact.create(
                        fact_id=MemoryFactId(self._ids.new_id("fact")),
                        space_id=current.space_id,
                        profile_id=current.profile_id,
                        thread_id=current.thread_id,
                        text=candidate.text,
                        kind=candidate.kind,
                        source_refs=source_refs,
                        confidence=decision.confidence,
                        trust_level=decision.trust_level,
                        now=now,
                    )
                    saved_fact = await uow.facts.create(fact)
                    await uow.outbox.enqueue(
                        OutboxEvent(
                            event_type="graph.upsert_fact",
                            aggregate_type="fact",
                            aggregate_id=str(saved_fact.id),
                            aggregate_version=saved_fact.version,
                            payload={"fact_id": str(saved_fact.id), "version": saved_fact.version},
                        )
                    )
                    auto_applied_ids.append(str(saved_fact.id))
                    continue
                resolver_rejected_codes.append(auto_apply.reason)
                if pending_suggestion_count + len(created_ids) >= (
                    self._max_pending_suggestions_per_profile
                ):
                    resolver_rejected_codes.append("pending_suggestion_limit_reached")
                    continue
                suggestion = MemorySuggestion.create(
                    suggestion_id=MemorySuggestionId(self._ids.new_id("sug")),
                    space_id=current.space_id,
                    profile_id=current.profile_id,
                    candidate_text=candidate.text,
                    kind=candidate.kind,
                    source_refs=source_refs,
                    safe_reason=decision.reason,
                    confidence=decision.confidence,
                    trust_level=decision.trust_level,
                    target_fact_id=MemoryFactId(candidate.target_fact_id)
                    if candidate.target_fact_id
                    else None,
                    target_fact_version=candidate.target_fact_version,
                    operation=_suggestion_operation(candidate.operation_hint),
                    category=taxonomy.category,
                    tags=taxonomy.tags,
                    ttl_policy=taxonomy.ttl_policy.name,
                    expires_at=expires_at,
                    expiry_reason="ttl_policy" if expires_at else None,
                    created_from_capture_id=str(current.id),
                    candidate_fingerprint=fingerprint,
                    review_payload={
                        "operation": _suggestion_operation(candidate.operation_hint).value,
                        "category": taxonomy.category,
                        "tags": list(taxonomy.tags),
                        "ttl_policy": taxonomy.ttl_policy.name,
                        "source_authority": current.source_authority.value,
                        "target_fact_id": candidate.target_fact_id,
                        "target_fact_version": candidate.target_fact_version,
                        "diff_preview": _diff_preview(target_fact, candidate.text),
                        "valid_from": candidate.valid_from.isoformat()
                        if candidate.valid_from
                        else None,
                        "valid_until": candidate.valid_until.isoformat()
                        if candidate.valid_until
                        else None,
                        "rejected_extractor_codes": list(validation.rejected_codes),
                        "rejected_resolver_codes": list(resolver_rejected_codes),
                        "unknown_taxonomy_labels": list(taxonomy.unknown_labels),
                    },
                    now=now,
                )
                saved_suggestion = await uow.suggestions.create(suggestion)
                created_ids.append(str(saved_suggestion.id))

            saved_capture = await uow.captures.save(
                current.mark_consolidated(
                    now=now,
                    extractor_version=self._extractor.version,
                    extractor_prompt_version=self._extractor.prompt_version,
                    resolver_version=RESOLVER_VERSION,
                )
            )
            await uow.commit()
        return CaptureResult(
            capture=saved_capture,
            created_suggestions=len(created_ids),
            suggestion_ids=tuple(created_ids),
            auto_applied_facts=len(auto_applied_ids),
            auto_applied_fact_ids=tuple(auto_applied_ids),
        )

    async def _claim_capture(
        self,
        *,
        command: ConsolidateCaptureCommand,
        now: datetime,
    ):
        async with self._uow_factory() as uow:
            capture = await uow.captures.get_for_update(command.capture_id)
            if capture is None:
                raise MemoryNotFoundError("Capture not found")
            if (
                capture.consolidation_status
                not in {ConsolidationStatus.PENDING, ConsolidationStatus.RETRY_PENDING}
                and not command.force
            ):
                return capture
            running = capture.mark_running(now=now)
            saved = await uow.captures.save(running)
            await uow.commit()
        return saved

    async def _mark_skipped(self, *, capture_id: str, reason: str) -> CaptureResult:
        async with self._uow_factory() as uow:
            capture = await uow.captures.get_for_update(capture_id)
            if capture is None:
                raise MemoryNotFoundError("Capture not found")
            saved = await uow.captures.save(
                capture.mark_skipped(now=self._clock.now(), reason=reason)
            )
            await uow.commit()
        return CaptureResult(capture=saved)

    async def _mark_dead(self, *, capture_id: str, code: str, message: str) -> CaptureResult:
        async with self._uow_factory() as uow:
            capture = await uow.captures.get_for_update(capture_id)
            if capture is None:
                raise MemoryNotFoundError("Capture not found")
            saved = await uow.captures.save(
                capture.mark_dead(now=self._clock.now(), code=code, message=message)
            )
            await uow.commit()
        return CaptureResult(capture=saved)

    async def _mark_retry_pending(
        self,
        *,
        capture_id: str,
        code: str,
        message: str,
    ) -> CaptureResult:
        async with self._uow_factory() as uow:
            capture = await uow.captures.get_for_update(capture_id)
            if capture is None:
                raise MemoryNotFoundError("Capture not found")
            saved = await uow.captures.save(
                capture.mark_retry_pending(now=self._clock.now(), code=code, message=message)
            )
            await uow.commit()
        return CaptureResult(capture=saved)


def _suggestion_operation(operation: CandidateOperation) -> SuggestionOperation:
    if operation == CandidateOperation.DELETE:
        return SuggestionOperation.DELETE
    if operation == CandidateOperation.UPDATE:
        return SuggestionOperation.UPDATE
    if operation == CandidateOperation.REVIEW:
        return SuggestionOperation.REVIEW
    return SuggestionOperation.ADD


def _candidate_fingerprint(
    *,
    space_id: str,
    profile_id: str,
    text: str,
    operation: str,
    target_fact_id: str | None,
    category: str,
) -> str:
    raw = f"{space_id}:{profile_id}:{operation}:{target_fact_id or ''}:{category}:{text}"
    return sha256(raw.encode("utf-8")).hexdigest()


def _expires_at(now: datetime, duration) -> datetime | None:
    if duration is None:
        return None
    return now + duration


async def _find_exact_active_duplicate(
    uow,
    *,
    space_id: str,
    profile_id: str,
    thread_id: str | None,
    text: str,
    kind: str,
):
    normalized = _normalize_fact_text(text)
    candidates = await uow.facts.find_active(
        space_id=space_id,
        profile_ids=(profile_id,),
        thread_id=thread_id,
        query=text,
        limit=10,
    )
    for fact in candidates:
        if fact.kind.value == kind and _normalize_fact_text(fact.text) == normalized:
            return fact
    return None


def _normalize_fact_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _diff_preview(target_fact, candidate_text: str) -> dict[str, str] | None:
    if target_fact is None:
        return None
    return {
        "before": target_fact.text[:240],
        "after": candidate_text[:240],
    }
