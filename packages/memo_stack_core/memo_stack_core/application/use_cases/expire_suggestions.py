"""Suggestion expiry cleanup."""

from __future__ import annotations

from dataclasses import dataclass

from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


@dataclass(frozen=True)
class ExpirePendingSuggestionsResult:
    expired: int
    suggestion_ids: tuple[str, ...]


class ExpirePendingSuggestionsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort, clock: ClockPort) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, *, limit: int = 100) -> ExpirePendingSuggestionsResult:
        now = self._clock.now()
        ids: list[str] = []
        async with self._uow_factory() as uow:
            suggestions = await uow.suggestions.list_expired_pending(
                now=now,
                limit=max(1, min(limit, 500)),
            )
            for suggestion in suggestions:
                saved = await uow.suggestions.save(
                    suggestion.expire(now=now, reason=suggestion.expiry_reason or "expired")
                )
                ids.append(str(saved.id))
            await uow.commit()
        return ExpirePendingSuggestionsResult(expired=len(ids), suggestion_ids=tuple(ids))
