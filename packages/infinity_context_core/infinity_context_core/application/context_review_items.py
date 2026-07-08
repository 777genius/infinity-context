"""Context items for stale memory and pending review suggestions."""

from __future__ import annotations

from infinity_context_core.application.context_media_time import enrich_context_item_with_media_time
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    query_relevance_score_signals,
)
from infinity_context_core.application.context_snippets import (
    query_focused_snippet,
    query_snippet_diagnostics,
    query_snippet_score_signals,
    source_refs_with_query_snippet,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.application.review_payloads import review_payload_with_default_contract
from infinity_context_core.domain.entities import MemoryFact


def suggestion_conflict_fact_id(suggestion) -> str | None:
    payload = suggestion.review_payload or {}
    for key in ("conflicting_fact_id", "conflict_fact_id", "possible_conflict_fact_id"):
        value = payload.get(key)
        if value:
            return str(value)
    if suggestion.target_fact_id:
        return str(suggestion.target_fact_id)
    return None


def pending_review_suggestion_item(
    *,
    suggestion,
    target_fact_id: str,
    target_fact_text: str | None = None,
) -> ContextItem:
    review_kind = _suggestion_review_kind(suggestion)
    retrieval_source = _pending_suggestion_retrieval_source(review_kind)
    score = _pending_suggestion_score(review_kind)
    review_resolution = _suggestion_review_resolution_diagnostics(suggestion)
    review_match = _suggestion_review_match_diagnostics(suggestion)
    return ContextItem(
        item_id=str(suggestion.id),
        item_type="suggestion",
        text=_pending_suggestion_text(
            candidate_text=suggestion.candidate_text,
            operation=suggestion.operation.value,
            review_kind=review_kind,
            target_fact_id=target_fact_id,
            target_fact_text=target_fact_text,
        ),
        score=score,
        source_refs=suggestion.source_refs,
        diagnostics={
            "memory_scope_id": str(suggestion.memory_scope_id),
            "retrieval_source": retrieval_source,
            "retrieval_sources": [retrieval_source],
            "ranking_reason": _pending_suggestion_ranking_reason(review_kind),
            "review_kind": review_kind,
            "score_signals": {
                "base_score": score,
                "review_status_boost": 0.0,
                "canonical": False,
            },
            "provenance": {
                "retrieval_sources": [retrieval_source],
                "source_ref_count": len(suggestion.source_refs),
                "target_fact_id": target_fact_id,
                "review_kind": review_kind,
                "candidate_fingerprint": suggestion.candidate_fingerprint,
                **review_match,
            },
            "status": suggestion.status.value,
            "operation": suggestion.operation.value,
            "canonical": False,
            "target_fact_id": target_fact_id,
            "conflicting_fact_id": target_fact_id,
            **review_match,
            **review_resolution,
        },
    )


def stale_review_item(
    fact: MemoryFact,
    *,
    relevance: QueryRelevance,
    query_text: str,
) -> ContextItem:
    score = min(0.64, round(0.44 + relevance.score_boost, 4))
    status = fact.status.value
    retrieval_source = stale_review_retrieval_source(status)
    stale_reason = f"fact_status_{status}"
    snippet = query_focused_snippet(query=query_text, text=fact.text)
    source_refs = source_refs_with_query_snippet(fact.source_refs, snippet)
    return enrich_context_item_with_media_time(
        ContextItem(
            item_id=str(fact.id),
            item_type="fact",
            text=fact.text,
            score=score,
            source_refs=source_refs,
            diagnostics={
                "memory_scope_id": str(fact.memory_scope_id),
                "retrieval_source": retrieval_source,
                "retrieval_sources": [retrieval_source],
                "ranking_reason": stale_review_ranking_reason(status),
                "review_only": True,
                "stale_reason": stale_reason,
                "score_signals": {
                    "base_score": 0.44,
                    "final_score": score,
                    "retrieval_channel": retrieval_source,
                    "fact_status": fact.status.value,
                    **query_relevance_score_signals(relevance),
                    **query_snippet_score_signals(snippet),
                },
                "provenance": {
                    "retrieval_sources": [retrieval_source],
                    "source_ref_count": len(source_refs),
                    "fact_status": fact.status.value,
                    "fact_version": fact.version,
                    "visibility": "review_only",
                    **query_snippet_diagnostics(snippet),
                },
                "confidence": fact.confidence.value,
                "trust_level": fact.trust_level.value,
                "updated_at": fact.updated_at.isoformat(),
                **query_snippet_diagnostics(snippet),
            },
        ),
        query_text=query_text,
    )


def stale_review_retrieval_source(status: str) -> str:
    if status == "superseded":
        return "superseded_review"
    if status == "disputed":
        return "disputed_review"
    return "stale_review"


def stale_review_ranking_reason(status: str) -> str:
    if status == "superseded":
        return "included only for review because include_superseded is true"
    return f"included only for stale memory review because status is {status}"


def _conflict_suggestion_text(
    *,
    candidate_text: str,
    operation: str,
    conflict_fact_id: str,
    target_fact_text: str | None = None,
) -> str:
    target_text = f" current active fact: {target_fact_text}" if target_fact_text else ""
    return (
        f"Pending review {operation} suggestion for active fact {conflict_fact_id}: "
        f"{candidate_text}{target_text}"
    )


def _suggestion_review_kind(suggestion) -> str:
    payload = review_payload_with_default_contract(suggestion.review_payload or {})
    value = payload.get("review_kind")
    return str(value).strip() if value else "conflict_review"


def _suggestion_review_resolution_diagnostics(suggestion) -> dict[str, object]:
    payload = review_payload_with_default_contract(suggestion.review_payload or {})
    diagnostics: dict[str, object] = {}
    recommended_action = _bounded_metadata_text(payload.get("recommended_action"), limit=80)
    recommended_resolution_action = _bounded_metadata_text(
        payload.get("recommended_resolution_action"),
        limit=80,
    )
    default_resolution = _bounded_metadata_text(payload.get("default_resolution"), limit=80)
    review_risk = _bounded_metadata_text(payload.get("review_risk"), limit=40)
    recommendation_confidence = _bounded_metadata_text(
        payload.get("recommendation_confidence"),
        limit=40,
    )
    policy_version = _bounded_metadata_text(
        payload.get("duplicate_merge_policy_version"),
        limit=80,
    )
    if recommended_action:
        diagnostics["review_recommended_action"] = recommended_action
    if recommended_resolution_action:
        diagnostics["review_recommended_resolution_action"] = recommended_resolution_action
    if default_resolution:
        diagnostics["review_default_resolution"] = default_resolution
    if review_risk:
        diagnostics["review_risk"] = review_risk
    if recommendation_confidence:
        diagnostics["review_recommendation_confidence"] = recommendation_confidence
    if policy_version:
        diagnostics["review_policy_version"] = policy_version
    if isinstance(payload.get("requires_review"), bool):
        diagnostics["review_requires_review"] = payload["requires_review"]
    if isinstance(payload.get("auto_merge_eligible"), bool):
        diagnostics["review_auto_merge_eligible"] = payload["auto_merge_eligible"]
    reason_codes = _bounded_metadata_text_list(
        payload.get("recommendation_reason_codes"),
        limit=80,
        max_items=12,
    )
    if reason_codes:
        diagnostics["review_recommendation_reason_codes"] = reason_codes
    options = payload.get("resolution_options")
    if not isinstance(options, list):
        return diagnostics
    safe_options: list[dict[str, str]] = []
    for option in options[:8]:
        if not isinstance(option, dict):
            continue
        safe_option = {
            key: value
            for key, value in (
                ("id", _bounded_metadata_text(option.get("id"), limit=80)),
                ("review_action", _bounded_metadata_text(option.get("review_action"), limit=40)),
                ("effect", _bounded_metadata_text(option.get("effect"), limit=120)),
                ("availability", _bounded_metadata_text(option.get("availability"), limit=40)),
            )
            if value
        }
        if safe_option:
            safe_options.append(safe_option)
    if safe_options:
        diagnostics["review_resolution_options"] = safe_options
    return diagnostics


def _suggestion_review_match_diagnostics(suggestion) -> dict[str, object]:
    payload = review_payload_with_default_contract(suggestion.review_payload or {})
    diagnostics: dict[str, object] = {}
    for key in (
        "dedupe_match_type",
        "conflict_match_type",
        "duplicate_fact_id",
        "duplicate_fact_version",
        "target_fact_version",
    ):
        value = _bounded_metadata_text(payload.get(key), limit=120)
        if value:
            diagnostics[key] = value
    score = _optional_float(payload.get("dedupe_score") or payload.get("conflict_score"))
    if score is not None:
        diagnostics["review_match_score"] = score
    for key in (
        "dedupe_reason_codes",
        "dedupe_overlap_terms",
        "conflict_reason_codes",
        "conflict_overlap_terms",
    ):
        values = _bounded_metadata_text_list(payload.get(key), limit=80, max_items=12)
        if values:
            diagnostics[key] = values
    reason_codes = _bounded_metadata_text_list(
        payload.get("dedupe_reason_codes") or payload.get("conflict_reason_codes"),
        limit=80,
        max_items=12,
    )
    if reason_codes:
        diagnostics["review_reason_codes"] = reason_codes
    return diagnostics


def _bounded_metadata_text_list(
    value: object,
    *,
    limit: int,
    max_items: int,
) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    safe_values: list[str] = []
    for item in value[:max_items]:
        text = _bounded_metadata_text(item, limit=limit)
        if text:
            safe_values.append(text)
    return safe_values


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bounded_metadata_text(value: object, *, limit: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _pending_suggestion_retrieval_source(review_kind: str) -> str:
    if review_kind == "duplicate_fact_merge":
        return "pending_duplicate_merge_suggestion"
    return "pending_conflict_suggestion"


def _pending_suggestion_score(review_kind: str) -> float:
    if review_kind == "duplicate_fact_merge":
        return 0.93
    return 0.94


def _pending_suggestion_ranking_reason(review_kind: str) -> str:
    if review_kind == "duplicate_fact_merge":
        return "pending duplicate merge can update visible active fact without duplicating memory"
    return "pending suggestion contradicts visible active fact"


def _pending_suggestion_text(
    *,
    candidate_text: str,
    operation: str,
    review_kind: str,
    target_fact_id: str,
    target_fact_text: str | None = None,
) -> str:
    if review_kind == "duplicate_fact_merge":
        return (
            f"Pending duplicate merge {operation} suggestion for active fact "
            f"{target_fact_id}: {candidate_text}"
        )
    return _conflict_suggestion_text(
        candidate_text=candidate_text,
        operation=operation,
        conflict_fact_id=target_fact_id,
        target_fact_text=target_fact_text,
    )
