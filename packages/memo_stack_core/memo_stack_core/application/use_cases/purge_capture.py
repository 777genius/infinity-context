"""Privacy purge for canonical captures."""

from __future__ import annotations

from memo_stack_core.application.dto import CaptureResult, PurgeCaptureCommand
from memo_stack_core.domain.errors import MemoryNotFoundError
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class PurgeCaptureUseCase:
    _MAX_PENDING_SUGGESTIONS_PER_CAPTURE = 500

    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort, clock: ClockPort) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: PurgeCaptureCommand) -> CaptureResult:
        async with self._uow_factory() as uow:
            capture = await uow.captures.get_for_update(command.capture_id)
            if capture is None:
                raise MemoryNotFoundError("Capture not found")
            now = self._clock.now()
            saved = await uow.captures.save(capture.mark_purged(now=now, reason=command.reason))
            pending_suggestions = await uow.suggestions.list_pending_for_capture(
                capture_id=command.capture_id,
                limit=self._MAX_PENDING_SUGGESTIONS_PER_CAPTURE,
            )
            for suggestion in pending_suggestions:
                await uow.suggestions.save(
                    suggestion.expire(now=now, reason="capture_privacy_purged")
                )
            await uow.commit()
        return CaptureResult(capture=saved)
