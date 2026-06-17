import asyncio

from memo_stack_core.application.dto import (
    CreateSuggestionCommand,
    CreateSuggestionsBatchCommand,
    ReviewContextLinkSuggestionBatchItemCommand,
    ReviewContextLinkSuggestionsBatchCommand,
)
from memo_stack_core.application.use_cases.context_link_reviews import (
    ReviewContextLinkSuggestionsBatchUseCase,
)
from memo_stack_core.application.use_cases.suggestions import CreateSuggestionsBatchUseCase
from memo_stack_core.domain.entities import MemoryKind, MemoryScopeId, SourceRef, SpaceId
from memo_stack_core.domain.errors import MemoryValidationError


class _FailingUseCase:
    async def execute(self, _command):
        raise MemoryValidationError(
            "provider failed with Authorization: Bearer sk-proj-batch-secret-value"
        )


def test_create_suggestions_batch_redacts_item_error_messages() -> None:
    result = asyncio.run(_run_create_suggestions_batch_redaction_case())

    assert result.failed == 1
    assert "sk-proj-batch-secret-value" not in (result.results[0].error_message or "")
    assert "[redacted]" in (result.results[0].error_message or "")


async def _run_create_suggestions_batch_redaction_case():
    use_case = CreateSuggestionsBatchUseCase(create_suggestion=_FailingUseCase())

    return await use_case.execute(
        CreateSuggestionsBatchCommand(
            items=(
                CreateSuggestionCommand(
                    space_id=SpaceId("space_1"),
                    memory_scope_id=MemoryScopeId("scope_1"),
                    candidate_text="Batch redaction candidate",
                    kind=MemoryKind.NOTE,
                    source_refs=(SourceRef(source_type="manual", source_id="src_1"),),
                    safe_reason="unit redaction",
                ),
            ),
            continue_on_error=True,
        )
    )


def test_context_link_batch_redacts_item_error_messages() -> None:
    result = asyncio.run(_run_context_link_batch_redaction_case())

    assert result.failed == 1
    assert "sk-proj-batch-secret-value" not in (result.results[0].error_message or "")
    assert "[redacted]" in (result.results[0].error_message or "")


async def _run_context_link_batch_redaction_case():
    use_case = ReviewContextLinkSuggestionsBatchUseCase(
        review_context_link_suggestion=_FailingUseCase()
    )

    return await use_case.execute(
        ReviewContextLinkSuggestionsBatchCommand(
            items=(
                ReviewContextLinkSuggestionBatchItemCommand(
                    suggestion_id="ctxsug_1",
                    action="approve",
                ),
            ),
            continue_on_error=True,
        )
    )
