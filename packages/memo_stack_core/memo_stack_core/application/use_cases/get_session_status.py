"""Thread/session status query use case."""

from memo_stack_core.application.dto import GetSessionStatusQuery, SessionStatusResult
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class GetSessionStatusUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: GetSessionStatusQuery) -> SessionStatusResult:
        async with self._uow_factory() as uow:
            status = await uow.scope.thread_status(
                space_id=str(query.space_id),
                profile_id=str(query.profile_id),
                thread_id=str(query.thread_id),
            )
        return SessionStatusResult(
            chunks=status.chunks,
            facts=status.facts,
            jobs=status.jobs,
            pending_jobs=status.pending_jobs,
        )
