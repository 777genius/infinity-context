"""Mappers between HTTP contracts and context_building application DTOs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

import infinity_context_core.features.context_building.public as context_building
from infinity_context_contracts.features.context_building import (
    BuildContextRequestDto,
    BuildContextResultDto,
    ContextBudgetDto,
    ContextEvidenceDto,
    ContextItemDto,
)

DEFAULT_CONTEXT_TOKEN_BUDGET = 1800
DEFAULT_CANDIDATE_LIMIT = 20


def build_context_query_from_contract(
    request: BuildContextRequestDto,
) -> context_building.BuildContextQuery:
    """Map an HTTP contract into the feature application query boundary."""

    budget = _budget_from_contract(request.budget)
    return context_building.BuildContextQuery(
        query=context_building.ContextQuery(
            scope=context_building.ContextScope(
                space_id=_required_text(request.space_id, "space_id"),
                memory_scope_id=_required_text(
                    request.memory_scope_id,
                    "memory_scope_id",
                ),
                thread_id=_optional_text(request.thread_id),
            ),
            text=_required_text(request.query, "query"),
            tags=_string_tuple(request.tags),
        ),
        budget=context_building.ContextBudget(
            max_prompt_tokens=budget.max_context_tokens,
            reserved_response_tokens=budget.reserved_response_tokens,
        ),
        candidate_limit=budget.max_items or DEFAULT_CANDIDATE_LIMIT,
    )


def build_context_result_to_contract(
    result: context_building.BuildContextResult,
) -> BuildContextResultDto:
    """Map a feature application result into the public HTTP contract."""

    bundle = result.bundle
    budget = None
    if bundle.max_prompt_tokens is not None:
        budget = ContextBudgetDto(max_context_tokens=bundle.max_prompt_tokens)

    return BuildContextResultDto(
        items=tuple(_item_to_contract(item) for item in bundle.items),
        rendered_context=bundle.rendered_evidence,
        budget=budget,
        total_tokens=bundle.total_estimated_tokens,
        diagnostics={
            "feature_id": context_building.FEATURE_ID,
            "item_count": len(bundle.items),
            "dropped_items": [
                {
                    "id": item.item_id,
                    "reason": item.reason,
                    "estimated_tokens": item.estimated_tokens,
                }
                for item in bundle.dropped_items
            ],
        },
    )


def _budget_from_contract(
    budget: ContextBudgetDto | Mapping[str, object] | None,
) -> ContextBudgetDto:
    if budget is None:
        return ContextBudgetDto(max_context_tokens=DEFAULT_CONTEXT_TOKEN_BUDGET)
    if isinstance(budget, ContextBudgetDto):
        return budget

    return ContextBudgetDto(
        max_context_tokens=_positive_int(
            budget.get("max_context_tokens"),
            "budget.max_context_tokens",
        ),
        reserved_response_tokens=_non_negative_int(
            budget.get("reserved_response_tokens"),
            "budget.reserved_response_tokens",
        ),
        max_items=_optional_positive_int(budget.get("max_items"), "budget.max_items"),
        strategy=str(budget.get("strategy") or "balanced"),
    )


def _item_to_contract(item: context_building.ContextItem) -> ContextItemDto:
    return ContextItemDto(
        id=item.item_id,
        text=item.text,
        kind=item.kind,
        evidence=tuple(
            evidence
            for context_evidence in item.evidence
            for evidence in _evidence_to_contracts(context_evidence)
        ),
        score=item.score,
        token_count=item.token_cost,
        trust_level=item.evidence[0].trust_level,
        metadata={
            "role": item.role,
            "priority": item.priority,
            "tags": list(item.tags),
        },
    )


def _evidence_to_contracts(
    evidence: context_building.ContextEvidence,
) -> tuple[ContextEvidenceDto, ...]:
    return tuple(
        ContextEvidenceDto(
            source_type=source_ref.source_type,
            source_id=source_ref.source_id,
            fact_id=source_ref.fact_id,
            document_id=source_ref.document_id,
            chunk_id=source_ref.chunk_id,
            quote_preview=source_ref.quote_preview,
            score=evidence.relevance_score,
            trust_level=evidence.trust_level,
            metadata={
                "evidence_id": evidence.evidence_id,
                "confidence": evidence.confidence,
                "temporal_label": evidence.temporal_label,
                "char_start": source_ref.char_start,
                "char_end": source_ref.char_end,
                "occurred_at": _datetime_to_string(source_ref.occurred_at),
            },
        )
        for source_ref in evidence.source_refs
    )


def _required_text(value: str | None, field_name: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_text(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _string_tuple(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(text for value in values if (text := str(value).strip()))


def _positive_int(value: object, field_name: str) -> int:
    parsed = _int_value(value, field_name)
    if parsed < 1:
        raise ValueError(f"{field_name} must be positive")
    return parsed


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _non_negative_int(value: object, field_name: str) -> int:
    if value is None:
        return 0
    parsed = _int_value(value, field_name)
    if parsed < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return parsed


def _int_value(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _datetime_to_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


__all__ = (
    "DEFAULT_CANDIDATE_LIMIT",
    "DEFAULT_CONTEXT_TOKEN_BUDGET",
    "build_context_query_from_contract",
    "build_context_result_to_contract",
)
