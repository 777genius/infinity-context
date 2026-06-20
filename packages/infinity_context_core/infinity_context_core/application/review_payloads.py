"""Shared review payload contracts for memory suggestions."""

from __future__ import annotations

from typing import Any

CONFLICT_REVIEW_KIND = "conflict_review"
DUPLICATE_FACT_MERGE_REVIEW_KIND = "duplicate_fact_merge"


def conflict_review_contract(*, approve_effect: str) -> dict[str, Any]:
    return {
        "review_kind": CONFLICT_REVIEW_KIND,
        "recommended_action": "manual_conflict_review",
        "default_resolution": "reject_or_edit_before_approve",
        "resolution_options": [
            {
                "id": "reject_candidate",
                "review_action": "reject",
                "effect": "keep_existing_fact",
                "availability": "available",
                "resolution_action": "reject_candidate",
            },
            {
                "id": "approve_candidate",
                "review_action": "approve",
                "effect": approve_effect,
                "availability": "available",
                "resolution_action": "approve_candidate",
            },
            {
                "id": "expire_candidate",
                "review_action": "expire",
                "effect": "hide_pending_suggestion",
                "availability": "available",
                "resolution_action": "expire_candidate",
            },
            {
                "id": "replace_existing_fact",
                "review_action": "resolve_conflict",
                "effect": "update_conflicting_fact_with_candidate",
                "availability": "available",
                "resolution_action": "replace_existing_fact",
            },
            {
                "id": "mark_existing_disputed",
                "review_action": "resolve_conflict",
                "effect": "mark_existing_fact_disputed_keep_candidate_as_evidence",
                "availability": "available",
                "resolution_action": "mark_existing_disputed",
            },
        ],
    }


def duplicate_fact_merge_review_contract() -> dict[str, Any]:
    return {
        "review_kind": DUPLICATE_FACT_MERGE_REVIEW_KIND,
        "recommended_action": "merge_source_refs_into_existing_fact",
        "recommended_resolution_action": "merge_source_refs",
        "default_resolution": "merge_or_keep_separate_after_review",
        "duplicate_merge_policy_version": "duplicate-merge-review-v1",
        "review_risk": "medium",
        "recommendation_confidence": "medium",
        "requires_review": True,
        "auto_merge_eligible": False,
        "recommendation_reason_codes": ["human_review_required", "legacy_payload"],
        "resolution_options": [
            {
                "id": "merge_source_refs",
                "review_action": "resolve_duplicate",
                "effect": "merge_source_refs_into_existing_fact",
                "availability": "available",
                "resolution_action": "merge_source_refs",
            },
            {
                "id": "keep_separate_fact",
                "review_action": "resolve_duplicate",
                "effect": "create_new_fact_keep_existing_fact",
                "availability": "available",
                "resolution_action": "keep_separate_fact",
            },
            {
                "id": "reject_duplicate_candidate",
                "review_action": "reject",
                "effect": "keep_existing_fact_without_candidate_source_refs",
                "availability": "available",
                "resolution_action": "reject_candidate",
            },
            {
                "id": "expire_duplicate_candidate",
                "review_action": "expire",
                "effect": "hide_pending_duplicate_merge_review",
                "availability": "available",
                "resolution_action": "expire_candidate",
            },
        ],
    }


def review_payload_with_default_contract(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("review_kind") == DUPLICATE_FACT_MERGE_REVIEW_KIND:
        return {**duplicate_fact_merge_review_contract(), **payload}
    return dict(payload)
