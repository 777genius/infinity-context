"""Consolidate captures into review-gated suggestions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from hashlib import sha256

from infinity_context_core.application.auto_apply import AutoApplySafePolicy
from infinity_context_core.application.auto_memory import MemoryAdmissionService
from infinity_context_core.application.dto import CaptureResult, ConsolidateCaptureCommand
from infinity_context_core.application.extractor import (
    RuleBasedMemoryExtractor,
    validate_extractor_candidates,
)
from infinity_context_core.application.review_payloads import (
    conflict_review_contract,
    duplicate_fact_merge_review_contract,
)
from infinity_context_core.application.semantic_dedupe import (
    describe_conflicting_fact_match,
    describe_duplicate_fact_match,
    looks_conflicting_fact,
    looks_equivalent_fact,
    normalize_memory_text,
    recommend_duplicate_fact_merge_review,
)
from infinity_context_core.application.sensitive_text import redact_sensitive_text
from infinity_context_core.domain.capture import (
    CaptureActorRole,
    ConsolidationStatus,
    SourceAuthority,
)
from infinity_context_core.domain.entities import (
    FactStatus,
    MemoryFact,
    MemoryFactId,
    MemorySuggestion,
    MemorySuggestionId,
    SuggestionOperation,
    TrustLevel,
)
from infinity_context_core.domain.errors import (
    MemoryInfrastructureError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from infinity_context_core.domain.events import OutboxEvent
from infinity_context_core.domain.taxonomy import DefaultTaxonomyPolicy, TaxonomyPolicyPort
from infinity_context_core.ports.auto_memory import (
    CandidateOperation,
    MemoryExtractorPort,
    SourceProvenance,
)
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

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
        max_pending_suggestions_per_memory_scope: int = 500,
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
        self._max_pending_suggestions_per_memory_scope = max(
            1, max_pending_suggestions_per_memory_scope
        )

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
            trust_level=_effective_capture_trust(running),
            actor_role=running.actor_role.value,
            source_authority=running.source_authority.value,
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
                message=_safe_consolidation_error_message(exc),
            )
        except MemoryValidationError as exc:
            return await self._mark_dead(
                capture_id=command.capture_id,
                code="extractor_invalid_output",
                message=_safe_consolidation_error_message(exc),
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
                memory_scope_id=str(current.memory_scope_id),
                status="pending",
            )
            seen_fingerprints: set[str] = set()
            touched_targets: set[str] = set()
            for candidate in validation.candidates:
                if candidate.operation_hint == CandidateOperation.NOOP:
                    resolver_rejected_codes.append("noop_candidate")
                    continue
                (
                    candidate,
                    target_resolution,
                    resolution_rejection,
                ) = await _resolve_candidate_target(
                    uow,
                    capture=current,
                    candidate=candidate,
                )
                if resolution_rejection is not None:
                    resolver_rejected_codes.append(resolution_rejection)
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
                        or target_fact.memory_scope_id != current.memory_scope_id
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
                    memory_scope_id=str(current.memory_scope_id),
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
                    active_duplicate = await _find_active_duplicate(
                        uow,
                        space_id=str(current.space_id),
                        memory_scope_id=str(current.memory_scope_id),
                        thread_id=str(current.thread_id) if current.thread_id else None,
                        text=candidate.text,
                        kind=candidate.kind.value,
                    )
                if active_duplicate is not None:
                    resolver_rejected_codes.append("duplicate_active_fact")
                    duplicate_match = describe_duplicate_fact_match(
                        candidate.text,
                        active_duplicate.text,
                    )
                    if duplicate_match is None:
                        continue
                    duplicate_candidate = replace(
                        candidate,
                        operation_hint=CandidateOperation.REVIEW,
                        target_fact_id=str(active_duplicate.id),
                        target_fact_version=active_duplicate.version,
                        ttl_policy="review",
                        tags=_dedupe_review_tags(taxonomy.tags),
                    )
                    duplicate_taxonomy = self._taxonomy.normalize(duplicate_candidate)
                    duplicate_fingerprint = _candidate_fingerprint(
                        space_id=str(current.space_id),
                        memory_scope_id=str(current.memory_scope_id),
                        text=candidate.text,
                        operation=CandidateOperation.REVIEW.value,
                        target_fact_id=str(active_duplicate.id),
                        category=duplicate_taxonomy.category,
                    )
                    duplicate_pending = await uow.suggestions.find_pending_duplicate(
                        space_id=str(current.space_id),
                        memory_scope_id=str(current.memory_scope_id),
                        candidate_fingerprint=duplicate_fingerprint,
                        operation=SuggestionOperation.REVIEW.value,
                        target_fact_id=str(active_duplicate.id),
                    )
                    if duplicate_pending is not None:
                        resolver_rejected_codes.append("duplicate_pending_suggestion")
                        continue
                    if pending_suggestion_count + len(created_ids) >= (
                        self._max_pending_suggestions_per_memory_scope
                    ):
                        resolver_rejected_codes.append("pending_suggestion_limit_reached")
                        continue
                    duplicate_expires_at = _expires_at(now, duplicate_taxonomy.ttl_policy.duration)
                    duplicate_recommendation = recommend_duplicate_fact_merge_review(
                        duplicate_match
                    )
                    suggestion = MemorySuggestion.create(
                        suggestion_id=MemorySuggestionId(self._ids.new_id("sug")),
                        space_id=current.space_id,
                        memory_scope_id=current.memory_scope_id,
                        candidate_text=candidate.text,
                        kind=candidate.kind,
                        source_refs=candidate.source_refs,
                        safe_reason=(
                            "Candidate matches an active memory fact and needs merge review."
                        ),
                        confidence=decision.confidence,
                        trust_level=decision.trust_level,
                        target_fact_id=MemoryFactId(str(active_duplicate.id)),
                        target_fact_version=active_duplicate.version,
                        operation=SuggestionOperation.REVIEW,
                        category=duplicate_taxonomy.category,
                        tags=duplicate_taxonomy.tags,
                        ttl_policy=duplicate_taxonomy.ttl_policy.name,
                        expires_at=duplicate_expires_at,
                        expiry_reason="ttl_policy" if duplicate_expires_at else None,
                        created_from_capture_id=str(current.id),
                        candidate_fingerprint=duplicate_fingerprint,
                        review_payload={
                            **duplicate_fact_merge_review_contract(),
                            **duplicate_recommendation.to_review_payload(),
                            "operation": SuggestionOperation.REVIEW.value,
                            "category": duplicate_taxonomy.category,
                            "tags": list(duplicate_taxonomy.tags),
                            "ttl_policy": duplicate_taxonomy.ttl_policy.name,
                            "source_authority": current.source_authority.value,
                            "target_fact_id": str(active_duplicate.id),
                            "target_fact_version": active_duplicate.version,
                            "duplicate_fact_id": str(active_duplicate.id),
                            "duplicate_fact_version": active_duplicate.version,
                            "dedupe_match_type": duplicate_match.match_type,
                            "dedupe_score": duplicate_match.score,
                            "dedupe_reason_codes": list(duplicate_match.reason_codes),
                            "dedupe_overlap_terms": list(duplicate_match.overlap_terms),
                            "rejected_extractor_codes": list(validation.rejected_codes),
                            "rejected_resolver_codes": list(resolver_rejected_codes),
                            "unknown_taxonomy_labels": list(duplicate_taxonomy.unknown_labels),
                        },
                        now=now,
                    )
                    saved_suggestion = await uow.suggestions.create(suggestion)
                    created_ids.append(str(saved_suggestion.id))
                    continue
                active_conflict = None
                if candidate.operation_hint == CandidateOperation.ADD:
                    active_conflict = await _find_active_conflict(
                        uow,
                        space_id=str(current.space_id),
                        memory_scope_id=str(current.memory_scope_id),
                        thread_id=str(current.thread_id) if current.thread_id else None,
                        text=candidate.text,
                        kind=candidate.kind.value,
                    )
                active_conflict_match = (
                    describe_conflicting_fact_match(candidate.text, active_conflict.text)
                    if active_conflict is not None
                    else None
                )
                duplicate = await uow.suggestions.find_pending_duplicate(
                    space_id=str(current.space_id),
                    memory_scope_id=str(current.memory_scope_id),
                    candidate_fingerprint=fingerprint,
                    operation=_suggestion_operation(candidate.operation_hint).value,
                    target_fact_id=candidate.target_fact_id,
                )
                if duplicate is not None:
                    resolver_rejected_codes.append("duplicate_pending_suggestion")
                    continue
                expires_at = _expires_at(now, taxonomy.ttl_policy.duration)
                source_refs = candidate.source_refs
                auto_apply = self._auto_apply_policy.decide(
                    enabled=self._auto_apply_safe_enabled,
                    capture=current,
                    candidate=candidate,
                    ttl_policy=taxonomy.ttl_policy.name,
                    has_active_duplicate=False,
                    has_active_conflict=active_conflict is not None,
                    has_pending_duplicate=False,
                )
                if auto_apply.allowed:
                    fact = MemoryFact.create(
                        fact_id=MemoryFactId(self._ids.new_id("fact")),
                        space_id=current.space_id,
                        memory_scope_id=current.memory_scope_id,
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
                    self._max_pending_suggestions_per_memory_scope
                ):
                    resolver_rejected_codes.append("pending_suggestion_limit_reached")
                    continue
                suggestion = MemorySuggestion.create(
                    suggestion_id=MemorySuggestionId(self._ids.new_id("sug")),
                    space_id=current.space_id,
                    memory_scope_id=current.memory_scope_id,
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
                        **(
                            conflict_review_contract(
                                approve_effect="create_new_fact_keep_conflicting_fact"
                            )
                            if active_conflict is not None
                            else {}
                        ),
                        "operation": _suggestion_operation(candidate.operation_hint).value,
                        "category": taxonomy.category,
                        "tags": list(taxonomy.tags),
                        "ttl_policy": taxonomy.ttl_policy.name,
                        "source_authority": current.source_authority.value,
                        "target_fact_id": candidate.target_fact_id,
                        "target_fact_version": candidate.target_fact_version,
                        "target_hint": candidate.target_hint,
                        "target_resolution": target_resolution,
                        "conflicting_fact_id": str(active_conflict.id)
                        if active_conflict is not None
                        else None,
                        "conflicting_fact_version": active_conflict.version
                        if active_conflict is not None
                        else None,
                        "conflict_match_type": active_conflict_match.match_type
                        if active_conflict_match is not None
                        else None,
                        "conflict_score": active_conflict_match.score
                        if active_conflict_match is not None
                        else None,
                        "conflict_reason_codes": list(active_conflict_match.reason_codes)
                        if active_conflict_match is not None
                        else [],
                        "conflict_overlap_terms": list(active_conflict_match.overlap_terms)
                        if active_conflict_match is not None
                        else [],
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
                capture.mark_dead(
                    now=self._clock.now(),
                    code=code,
                    message=_safe_consolidation_error_message(message),
                )
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
                capture.mark_retry_pending(
                    now=self._clock.now(),
                    code=code,
                    message=_safe_consolidation_error_message(message),
                )
            )
            await uow.commit()
        return CaptureResult(capture=saved)


async def _resolve_candidate_target(
    uow,
    *,
    capture,
    candidate,
) -> tuple[object, dict[str, object], str | None]:
    if candidate.operation_hint not in {CandidateOperation.UPDATE, CandidateOperation.DELETE}:
        return candidate, {"status": "not_required"}, None
    if candidate.target_fact_id:
        return (
            candidate,
            {
                "status": "provided",
                "target_fact_id": candidate.target_fact_id,
                "target_fact_version": candidate.target_fact_version,
            },
            None,
        )

    target_hint = _normalize_target_hint(candidate.target_hint or candidate.text)
    if not target_hint:
        return candidate, {"status": "missing_target_hint"}, "target_fact_or_hint_required"

    candidates = await uow.facts.find_active(
        space_id=str(capture.space_id),
        memory_scope_ids=(str(capture.memory_scope_id),),
        thread_id=str(capture.thread_id) if capture.thread_id else None,
        query=target_hint,
        limit=5,
    )
    ranked = _rank_target_matches(candidates, target_hint)
    if not ranked:
        return (
            candidate,
            {"status": "not_found", "target_hint": _target_hint_preview(target_hint)},
            "target_fact_not_found",
        )
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return (
            candidate,
            {
                "status": "ambiguous",
                "target_hint": _target_hint_preview(target_hint),
                "candidate_count": len(ranked),
            },
            "target_fact_ambiguous",
        )

    score, fact = ranked[0]
    resolved = replace(
        candidate,
        target_fact_id=str(fact.id),
        target_fact_version=fact.version,
    )
    return (
        resolved,
        {
            "status": "resolved",
            "target_hint": _target_hint_preview(target_hint),
            "target_fact_id": str(fact.id),
            "target_fact_version": fact.version,
            "score": score,
        },
        None,
    )


def _suggestion_operation(operation: CandidateOperation) -> SuggestionOperation:
    if operation == CandidateOperation.DELETE:
        return SuggestionOperation.DELETE
    if operation == CandidateOperation.UPDATE:
        return SuggestionOperation.UPDATE
    if operation == CandidateOperation.REVIEW:
        return SuggestionOperation.REVIEW
    return SuggestionOperation.ADD


def _effective_capture_trust(capture) -> TrustLevel:
    if (
        capture.actor_role == CaptureActorRole.ASSISTANT
        or capture.source_authority == SourceAuthority.ASSISTANT_INFERENCE
    ):
        return TrustLevel.LOW
    return capture.trust_level


def _candidate_fingerprint(
    *,
    space_id: str,
    memory_scope_id: str,
    text: str,
    operation: str,
    target_fact_id: str | None,
    category: str,
) -> str:
    raw = f"{space_id}:{memory_scope_id}:{operation}:{target_fact_id or ''}:{category}:{text}"
    return sha256(raw.encode("utf-8")).hexdigest()


def _dedupe_review_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    ordered = [tag for tag in tags if tag != "dedupe"]
    ordered.insert(0, "dedupe")
    return tuple(ordered[:10])


def _expires_at(now: datetime, duration) -> datetime | None:
    if duration is None:
        return None
    return now + duration


def _safe_consolidation_error_message(value: object) -> str:
    text = str(value).strip() or value.__class__.__name__
    return redact_sensitive_text(text)[:400]


async def _find_active_duplicate(
    uow,
    *,
    space_id: str,
    memory_scope_id: str,
    thread_id: str | None,
    text: str,
    kind: str,
):
    normalized = normalize_memory_text(text)
    candidates = await _active_duplicate_candidates(
        uow,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        text=text,
    )
    seen_ids: set[str] = set()
    for fact in candidates:
        seen_ids.add(str(fact.id))
        if fact.kind.value != kind:
            continue
        if normalize_memory_text(fact.text) == normalized or looks_equivalent_fact(
            text,
            fact.text,
        ):
            return fact
    fallback_candidates = await uow.facts.find_active(
        space_id=space_id,
        memory_scope_ids=(memory_scope_id,),
        thread_id=thread_id,
        query="",
        limit=50,
    )
    for fact in fallback_candidates:
        if str(fact.id) in seen_ids or fact.kind.value != kind:
            continue
        if normalize_memory_text(fact.text) == normalized or looks_equivalent_fact(
            text,
            fact.text,
        ):
            return fact
    return None


async def _find_active_conflict(
    uow,
    *,
    space_id: str,
    memory_scope_id: str,
    thread_id: str | None,
    text: str,
    kind: str,
):
    candidates = await uow.facts.find_active(
        space_id=space_id,
        memory_scope_ids=(memory_scope_id,),
        thread_id=thread_id,
        query=text,
        limit=50,
    )
    for fact in candidates:
        if fact.kind.value == kind and looks_conflicting_fact(text, fact.text):
            return fact
    fallback_candidates = await uow.facts.find_active(
        space_id=space_id,
        memory_scope_ids=(memory_scope_id,),
        thread_id=thread_id,
        query="",
        limit=50,
    )
    seen_ids = {str(fact.id) for fact in candidates}
    for fact in fallback_candidates:
        if str(fact.id) in seen_ids or fact.kind.value != kind:
            continue
        if looks_conflicting_fact(text, fact.text):
            return fact
    return None


async def _active_duplicate_candidates(
    uow,
    *,
    space_id: str,
    memory_scope_id: str,
    thread_id: str | None,
    text: str,
):
    return await uow.facts.find_active(
        space_id=space_id,
        memory_scope_ids=(memory_scope_id,),
        thread_id=thread_id,
        query=text,
        limit=10,
    )


def _normalize_fact_text(value: str) -> str:
    return normalize_memory_text(value)


def _normalize_target_hint(value: str) -> str:
    return " ".join(value.strip().split())


def _target_hint_preview(value: str) -> str:
    return value[:160]


def _rank_target_matches(candidates, target_hint: str):
    ranked = [
        (score, fact)
        for fact in candidates
        if (score := _target_match_score(fact.text, target_hint)) > 0
    ]
    ranked.sort(key=lambda item: (item[0], str(item[1].updated_at), str(item[1].id)), reverse=True)
    return ranked


def _target_match_score(fact_text: str, target_hint: str) -> int:
    normalized_fact = _normalize_fact_text(fact_text)
    normalized_hint = _normalize_fact_text(target_hint)
    terms = {term for term in normalized_hint.split() if len(term) >= 3}
    if not terms:
        return 0
    score = len(terms.intersection(normalized_fact.split()))
    if normalized_hint in normalized_fact:
        score += len(terms) + 1
    return score


def _diff_preview(target_fact, candidate_text: str) -> dict[str, str] | None:
    if target_fact is None:
        return None
    return {
        "before": target_fact.text[:240],
        "after": candidate_text[:240],
    }
