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
