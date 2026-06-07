import asyncio
from datetime import UTC, datetime

from memo_stack_core.application import CreateSuggestionCommand, CreateSuggestionUseCase
from memo_stack_core.domain.entities import (
    Confidence,
    MemoryKind,
    MemorySuggestion,
    MemorySuggestionId,
    ProfileId,
    SourceRef,
    SpaceId,
    TrustLevel,
)
from memo_stack_core.domain.errors import MemoryConflictError


def test_create_suggestion_recovers_existing_pending_after_commit_conflict() -> None:
    asyncio.run(_run_commit_conflict_recovery())


async def _run_commit_conflict_recovery() -> None:
    duplicate = MemorySuggestion.create(
        suggestion_id=MemorySuggestionId("sug_existing"),
        space_id=SpaceId("space_1"),
        profile_id=ProfileId("profile_1"),
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
            profile_id=ProfileId("profile_1"),
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
