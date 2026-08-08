"""Temporal governance response models split from the legacy MCP model registry."""

from pydantic import Field

from infinity_context_mcp.domain.models import (
    McpDataModel,
    McpToolResponse,
    MemoryRecordData,
)


class MemoryTemporalDecisionData(McpDataModel):
    id: str | None = None
    type: str | None = None
    source_fact_id: str | None = None
    source_fact_version: int | None = None
    target_fact_id: str | None = None
    target_fact_version: int | None = None
    effective_at: str | None = None
    applied_at: str | None = None
    actor_id: str | None = None
    policy_version: str | None = None
    reason_code: str | None = None
    compensates_decision_id: str | None = None
    outbox_message_ids: list[str] = Field(default_factory=list)


class MemorySupersessionRelationData(McpDataModel):
    id: str | None = None
    successor_fact_id: str | None = None
    successor_fact_version: int | None = None
    predecessor_fact_id: str | None = None
    predecessor_fact_version: int | None = None
    effective_at: str | None = None
    decision_id: str | None = None


class MemoryTemporalFactMutationData(McpDataModel):
    fact: MemoryRecordData | None = None
    successor: MemoryRecordData | None = None
    predecessor: MemoryRecordData | None = None
    challenger: MemoryRecordData | None = None
    challenged: MemoryRecordData | None = None
    reinstated_fact: MemoryRecordData | None = None
    rejected_successor: MemoryRecordData | None = None
    decision: MemoryTemporalDecisionData | None = None
    relation: MemorySupersessionRelationData | None = None
    replayed: bool | None = None
    outbox_message_ids: list[str] = Field(default_factory=list)


class MemoryTemporalFactMutationResponse(McpToolResponse):
    data: MemoryTemporalFactMutationData | None = None


__all__ = (
    "MemorySupersessionRelationData",
    "MemoryTemporalDecisionData",
    "MemoryTemporalFactMutationData",
    "MemoryTemporalFactMutationResponse",
)
