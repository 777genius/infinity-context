"""FastMCP tools for audited temporal fact governance."""

from __future__ import annotations

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import AwareDatetime, Field

from infinity_context_mcp.application.service import MemoryToolService
from infinity_context_mcp.domain.temporal_models import MemoryTemporalFactMutationResponse
from infinity_context_mcp.server_request_mapping import SourceType
from infinity_context_mcp.server_response import tool_response as _tool_response

_MUTATION_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def register_memory_temporal_fact_tools(
    mcp: FastMCP,
    tool_service: MemoryToolService,
) -> None:
    @mcp.tool(
        name="memory_confirm_fact",
        title="Confirm Fact",
        description=(
            "Record an evidence-backed confirmation of the current fact revision. This updates "
            "freshness but never infers truth from age or updated_at."
        ),
        annotations=_MUTATION_ANNOTATIONS,
        structured_output=True,
    )
    async def memory_confirm_fact(
        fact_id: Annotated[str, Field(min_length=1, max_length=160)],
        expected_version: Annotated[int, Field(ge=1)],
        confirmed_at: AwareDatetime,
        confirmation_basis: Annotated[str, Field(min_length=1, max_length=120)],
        space_slug: Annotated[str | None, Field(default=None, max_length=160)] = None,
        memory_scope_external_ref: Annotated[
            str | None, Field(default=None, max_length=200)
        ] = None,
        thread_external_ref: Annotated[str | None, Field(default=None, max_length=200)] = None,
        source_type: Annotated[SourceType | None, Field(default=None)] = None,
        source_id: Annotated[str | None, Field(default=None, max_length=240)] = None,
        quote_preview: Annotated[str | None, Field(default=None, max_length=240)] = None,
        idempotency_key: Annotated[str | None, Field(default=None, max_length=240)] = None,
    ) -> Annotated[CallToolResult, MemoryTemporalFactMutationResponse]:
        return _tool_response(
            await tool_service.confirm_fact(
                fact_id=fact_id,
                expected_version=expected_version,
                confirmed_at=confirmed_at,
                confirmation_basis=confirmation_basis,
                **_common(
                    space_slug,
                    memory_scope_external_ref,
                    thread_external_ref,
                    source_type,
                    source_id,
                    quote_preview,
                    idempotency_key,
                ),
            ),
            MemoryTemporalFactMutationResponse,
        )

    @mcp.tool(
        name="memory_end_fact_validity",
        title="End Fact Validity",
        description=(
            "Close a currently valid state fact at an observed boundary without inventing a "
            "replacement. Future scheduling is intentionally unsupported."
        ),
        annotations=_MUTATION_ANNOTATIONS,
        structured_output=True,
    )
    async def memory_end_fact_validity(
        fact_id: Annotated[str, Field(min_length=1, max_length=160)],
        expected_version: Annotated[int, Field(ge=1)],
        effective_at: AwareDatetime,
        reason_code: Annotated[str, Field(min_length=1, max_length=120)],
        space_slug: Annotated[str | None, Field(default=None, max_length=160)] = None,
        memory_scope_external_ref: Annotated[
            str | None, Field(default=None, max_length=200)
        ] = None,
        thread_external_ref: Annotated[str | None, Field(default=None, max_length=200)] = None,
        source_type: Annotated[SourceType | None, Field(default=None)] = None,
        source_id: Annotated[str | None, Field(default=None, max_length=240)] = None,
        quote_preview: Annotated[str | None, Field(default=None, max_length=240)] = None,
        idempotency_key: Annotated[str | None, Field(default=None, max_length=240)] = None,
    ) -> Annotated[CallToolResult, MemoryTemporalFactMutationResponse]:
        return _tool_response(
            await tool_service.end_fact_validity(
                fact_id=fact_id,
                expected_version=expected_version,
                effective_at=effective_at,
                reason_code=reason_code,
                **_common(
                    space_slug,
                    memory_scope_external_ref,
                    thread_external_ref,
                    source_type,
                    source_id,
                    quote_preview,
                    idempotency_key,
                ),
            ),
            MemoryTemporalFactMutationResponse,
        )

    @mcp.tool(
        name="memory_supersede_fact",
        title="Supersede Fact",
        description=(
            "Atomically replace one current state fact with an already-created successor. "
            "Requires exact versions and evidence; do not use generic memory_link_facts."
        ),
        annotations=_MUTATION_ANNOTATIONS,
        structured_output=True,
    )
    async def memory_supersede_fact(
        predecessor_fact_id: Annotated[str, Field(min_length=1, max_length=160)],
        successor_fact_id: Annotated[str, Field(min_length=1, max_length=160)],
        expected_predecessor_version: Annotated[int, Field(ge=1)],
        expected_successor_version: Annotated[int, Field(ge=1)],
        effective_at: AwareDatetime,
        reason_code: Annotated[str, Field(min_length=1, max_length=120)],
        space_slug: Annotated[str | None, Field(default=None, max_length=160)] = None,
        memory_scope_external_ref: Annotated[
            str | None, Field(default=None, max_length=200)
        ] = None,
        thread_external_ref: Annotated[str | None, Field(default=None, max_length=200)] = None,
        source_type: Annotated[SourceType | None, Field(default=None)] = None,
        source_id: Annotated[str | None, Field(default=None, max_length=240)] = None,
        quote_preview: Annotated[str | None, Field(default=None, max_length=240)] = None,
        idempotency_key: Annotated[str | None, Field(default=None, max_length=240)] = None,
    ) -> Annotated[CallToolResult, MemoryTemporalFactMutationResponse]:
        return _tool_response(
            await tool_service.supersede_fact(
                predecessor_fact_id=predecessor_fact_id,
                successor_fact_id=successor_fact_id,
                expected_predecessor_version=expected_predecessor_version,
                expected_successor_version=expected_successor_version,
                effective_at=effective_at,
                reason_code=reason_code,
                **_common(
                    space_slug,
                    memory_scope_external_ref,
                    thread_external_ref,
                    source_type,
                    source_id,
                    quote_preview,
                    idempotency_key,
                ),
            ),
            MemoryTemporalFactMutationResponse,
        )

    @mcp.tool(
        name="memory_dispute_facts",
        title="Dispute Facts",
        description=(
            "Atomically move two comparable, currently valid claims out of normal context while "
            "their conflict is reviewed."
        ),
        annotations=_MUTATION_ANNOTATIONS,
        structured_output=True,
    )
    async def memory_dispute_facts(
        challenged_fact_id: Annotated[str, Field(min_length=1, max_length=160)],
        challenger_fact_id: Annotated[str, Field(min_length=1, max_length=160)],
        expected_challenged_version: Annotated[int, Field(ge=1)],
        expected_challenger_version: Annotated[int, Field(ge=1)],
        reason_code: Annotated[str, Field(min_length=1, max_length=120)],
        space_slug: Annotated[str | None, Field(default=None, max_length=160)] = None,
        memory_scope_external_ref: Annotated[
            str | None, Field(default=None, max_length=200)
        ] = None,
        thread_external_ref: Annotated[str | None, Field(default=None, max_length=200)] = None,
        source_type: Annotated[SourceType | None, Field(default=None)] = None,
        source_id: Annotated[str | None, Field(default=None, max_length=240)] = None,
        quote_preview: Annotated[str | None, Field(default=None, max_length=240)] = None,
        idempotency_key: Annotated[str | None, Field(default=None, max_length=240)] = None,
    ) -> Annotated[CallToolResult, MemoryTemporalFactMutationResponse]:
        return _tool_response(
            await tool_service.dispute_facts(
                challenged_fact_id=challenged_fact_id,
                challenger_fact_id=challenger_fact_id,
                expected_challenged_version=expected_challenged_version,
                expected_challenger_version=expected_challenger_version,
                reason_code=reason_code,
                **_common(
                    space_slug,
                    memory_scope_external_ref,
                    thread_external_ref,
                    source_type,
                    source_id,
                    quote_preview,
                    idempotency_key,
                ),
            ),
            MemoryTemporalFactMutationResponse,
        )

    @mcp.tool(
        name="memory_reinstate_supersession",
        title="Reinstate Superseded Fact",
        description="Compensate one audited supersession decision without rewriting history.",
        annotations=_MUTATION_ANNOTATIONS,
        structured_output=True,
    )
    async def memory_reinstate_supersession(
        supersession_decision_id: Annotated[str, Field(min_length=1, max_length=160)],
        expected_rejected_successor_version: Annotated[int, Field(ge=1)],
        expected_original_predecessor_version: Annotated[int, Field(ge=1)],
        reason_code: Annotated[str, Field(min_length=1, max_length=120)],
        space_slug: Annotated[str | None, Field(default=None, max_length=160)] = None,
        memory_scope_external_ref: Annotated[
            str | None, Field(default=None, max_length=200)
        ] = None,
        thread_external_ref: Annotated[str | None, Field(default=None, max_length=200)] = None,
        source_type: Annotated[SourceType | None, Field(default=None)] = None,
        source_id: Annotated[str | None, Field(default=None, max_length=240)] = None,
        quote_preview: Annotated[str | None, Field(default=None, max_length=240)] = None,
        idempotency_key: Annotated[str | None, Field(default=None, max_length=240)] = None,
    ) -> Annotated[CallToolResult, MemoryTemporalFactMutationResponse]:
        return _tool_response(
            await tool_service.reinstate_supersession(
                supersession_decision_id=supersession_decision_id,
                expected_rejected_successor_version=expected_rejected_successor_version,
                expected_original_predecessor_version=expected_original_predecessor_version,
                reason_code=reason_code,
                **_common(
                    space_slug,
                    memory_scope_external_ref,
                    thread_external_ref,
                    source_type,
                    source_id,
                    quote_preview,
                    idempotency_key,
                ),
            ),
            MemoryTemporalFactMutationResponse,
        )


def _common(
    space_slug: str | None,
    memory_scope_external_ref: str | None,
    thread_external_ref: str | None,
    source_type: str | None,
    source_id: str | None,
    quote_preview: str | None,
    idempotency_key: str | None,
) -> dict[str, object]:
    return {
        "space_slug": space_slug,
        "memory_scope_external_ref": memory_scope_external_ref,
        "thread_external_ref": thread_external_ref,
        "source_type": source_type,
        "source_id": source_id,
        "quote_preview": quote_preview,
        "idempotency_key": idempotency_key,
    }


__all__ = ("register_memory_temporal_fact_tools",)
