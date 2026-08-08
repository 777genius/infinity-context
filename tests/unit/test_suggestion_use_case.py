import asyncio
from datetime import UTC, datetime

from infinity_context_core.application import CreateSuggestionCommand, CreateSuggestionUseCase
from infinity_context_core.application.suggestion_fact_resolution import reviewed_fact_decision
from infinity_context_core.domain.entities import (
    MAX_SOURCE_REFS_PER_ITEM,
    MAX_SUGGESTION_REVIEW_EVENTS,
    Confidence,
    MemoryKind,
    MemoryScopeId,
    MemorySuggestion,
    MemorySuggestionId,
    SourceRef,
    SpaceId,
    TrustLevel,
)
from infinity_context_core.domain.errors import MemoryConflictError


def test_create_suggestion_recovers_existing_pending_after_commit_conflict() -> None:
    asyncio.run(_run_commit_conflict_recovery())


def test_suggestion_source_refs_are_deduplicated_and_capped() -> None:
    suggestion = MemorySuggestion.create(
        suggestion_id=MemorySuggestionId("sug_many_refs"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("memory_scope_1"),
        candidate_text="Suggestion keeps bounded source refs.",
        kind=MemoryKind.NOTE,
        source_refs=(
            SourceRef(source_type="manual", source_id="source_0"),
            *tuple(
                SourceRef(source_type="manual", source_id=f"source_{index}")
                for index in range(MAX_SOURCE_REFS_PER_ITEM + 5)
            ),
        ),
        confidence=Confidence.MEDIUM,
        trust_level=TrustLevel.MEDIUM,
        safe_reason="review",
        now=_NOW,
    )

    assert len(suggestion.source_refs) == MAX_SOURCE_REFS_PER_ITEM
    assert suggestion.source_refs[0].source_id == "source_0"
    assert suggestion.source_refs[-1].source_id == f"source_{MAX_SOURCE_REFS_PER_ITEM - 1}"


def test_suggestion_review_audit_events_are_capped() -> None:
    suggestion = MemorySuggestion.create(
        suggestion_id=MemorySuggestionId("sug_review_cap"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("memory_scope_1"),
        candidate_text="Suggestion review audit stays bounded.",
        kind=MemoryKind.NOTE,
        source_refs=(SourceRef(source_type="manual", source_id="source_1"),),
        confidence=Confidence.MEDIUM,
        trust_level=TrustLevel.MEDIUM,
        safe_reason="review",
        review_payload={
            "review_events": [
                {"event_type": "memory_suggestion_reviewed", "suggestion_id": f"sug_{index}"}
                for index in range(MAX_SUGGESTION_REVIEW_EVENTS + 5)
            ]
        },
        now=_NOW,
    )

    rejected = suggestion.reject(now=_NOW, reason="not useful")
    events = rejected.review_payload["review_events"] if rejected.review_payload else []

    assert len(events) == MAX_SUGGESTION_REVIEW_EVENTS
    assert events[0]["suggestion_id"] == "sug_6"
    assert events[-1]["suggestion_id"] == "sug_review_cap"
    assert events[-1]["action"] == "reject"


def test_reviewed_candidate_preserves_extracted_temporal_window() -> None:
    suggestion = MemorySuggestion.create(
        suggestion_id=MemorySuggestionId("sug_temporal"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("memory_scope_1"),
        candidate_text="MySQL was used from January through June.",
        kind=MemoryKind.NOTE,
        source_refs=(SourceRef(source_type="manual", source_id="source_1"),),
        confidence=Confidence.MEDIUM,
        trust_level=TrustLevel.MEDIUM,
        safe_reason="review",
        review_payload={
            "valid_from": "2026-01-01T00:00:00+00:00",
            "valid_until": "2026-07-01T00:00:00+00:00",
        },
        now=_NOW,
    )

    decision = reviewed_fact_decision(
        suggestion,
        actor_id="reviewer-1",
        reason="approved temporal evidence",
        now=_NOW,
        allow_weaker=False,
    )

    assert decision.candidate.temporal_extent is not None
    assert decision.candidate.temporal_extent.observed_at == _NOW
    assert decision.candidate.temporal_extent.valid_from == datetime(2026, 1, 1, tzinfo=UTC)
    assert decision.candidate.temporal_extent.valid_to == datetime(2026, 7, 1, tzinfo=UTC)


async def _run_commit_conflict_recovery() -> None:
    duplicate = MemorySuggestion.create(
        suggestion_id=MemorySuggestionId("sug_existing"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("memory_scope_1"),
        candidate_text="Race-safe suggestion dedupe marker.",
        kind=MemoryKind.NOTE,
        source_refs=(SourceRef(source_type="manual", source_id="existing"),),
        confidence=Confidence.MEDIUM,
        trust_level=TrustLevel.MEDIUM,
        safe_reason="review",
        candidate_fingerprint="existing-fingerprint",
        now=_NOW,
    )
    uow_factory = _ConflictThenDuplicateUowFactory(duplicate=duplicate)
    use_case = CreateSuggestionUseCase(
        uow_factory=uow_factory,
        clock=_Clock(),
        ids=_Ids(),
    )

    result = await use_case.execute(
        CreateSuggestionCommand(
            space_id=SpaceId("space_1"),
            memory_scope_id=MemoryScopeId("memory_scope_1"),
            candidate_text="Race-safe suggestion dedupe marker.",
            kind=MemoryKind.NOTE,
            source_refs=(SourceRef(source_type="manual", source_id="new"),),
            safe_reason="review",
            candidate_fingerprint="existing-fingerprint",
        )
    )

    assert result.created is False
    assert result.suggestion.id == duplicate.id
    assert uow_factory.open_count == 2


_NOW = datetime(2026, 5, 25, 10, 0, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return _NOW


class _Ids:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}_new"


class _ConflictThenDuplicateUowFactory:
    def __init__(self, *, duplicate: MemorySuggestion) -> None:
        self._duplicate = duplicate
        self.open_count = 0

    def __call__(self):
        self.open_count += 1
        return _Uow(
            duplicate=None if self.open_count == 1 else self._duplicate,
            conflict_on_commit=self.open_count == 1,
        )


class _Uow:
    def __init__(
        self,
        *,
        duplicate: MemorySuggestion | None,
        conflict_on_commit: bool,
    ) -> None:
        self.suggestions = _Suggestions(duplicate=duplicate)
        self._conflict_on_commit = conflict_on_commit

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def commit(self) -> None:
        if self._conflict_on_commit:
            raise MemoryConflictError("Unique pending suggestion fingerprint conflict")


class _Suggestions:
    def __init__(self, *, duplicate: MemorySuggestion | None) -> None:
        self._duplicate = duplicate

    async def find_pending_duplicate(self, **_kwargs):
        return self._duplicate

    async def create(self, suggestion: MemorySuggestion) -> MemorySuggestion:
        return suggestion
