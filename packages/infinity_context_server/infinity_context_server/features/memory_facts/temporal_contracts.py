"""HTTP contracts for audited temporal fact decisions."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from infinity_context_server.features.memory_facts.contracts import (
    MemoryFactSourceRefHttpRequest,
)


class TemporalEvidenceRefHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: MemoryFactSourceRefHttpRequest
    evidence_id: str | None = Field(default=None, min_length=1, max_length=160)


class TemporalDecisionHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    evidence_refs: list[TemporalEvidenceRefHttpRequest] = Field(min_length=1, max_length=20)
    actor_id: str | None = Field(default=None, min_length=1, max_length=160)


class ConfirmFactHttpRequest(TemporalDecisionHttpRequest):
    expected_version: int = Field(ge=1)
    confirmed_at: AwareDatetime
    confirmation_basis: str = Field(min_length=1, max_length=120)


class EndFactValidityHttpRequest(TemporalDecisionHttpRequest):
    expected_version: int = Field(ge=1)
    effective_at: AwareDatetime
    reason_code: str = Field(min_length=1, max_length=120)


class SupersedeFactHttpRequest(TemporalDecisionHttpRequest):
    successor_fact_id: str = Field(min_length=1, max_length=80)
    expected_successor_version: int = Field(ge=1)
    expected_predecessor_version: int = Field(ge=1)
    effective_at: AwareDatetime
    reason_code: str = Field(min_length=1, max_length=120)


class DisputeFactHttpRequest(TemporalDecisionHttpRequest):
    challenger_fact_id: str = Field(min_length=1, max_length=80)
    expected_challenger_version: int = Field(ge=1)
    expected_challenged_version: int = Field(ge=1)
    reason_code: str = Field(min_length=1, max_length=120)


class ReinstateSupersessionHttpRequest(TemporalDecisionHttpRequest):
    supersession_decision_id: str = Field(min_length=1, max_length=80)
    expected_rejected_successor_version: int = Field(ge=1)
    expected_original_predecessor_version: int = Field(ge=1)
    reason_code: str = Field(min_length=1, max_length=120)


__all__ = (
    "ConfirmFactHttpRequest",
    "DisputeFactHttpRequest",
    "EndFactValidityHttpRequest",
    "ReinstateSupersessionHttpRequest",
    "SupersedeFactHttpRequest",
    "TemporalDecisionHttpRequest",
    "TemporalEvidenceRefHttpRequest",
)
