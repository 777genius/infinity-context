"""Legacy /v1 insights API response shaping for the context_building seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class SafePublicMetadata(Protocol):
    def __call__(self, metadata: Any, *, max_items: int = 120) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class LegacyMemoryInsightsApiResponseMapper:
    """Build compatibility response payloads for legacy insights routes."""

    safe_public_metadata: SafePublicMetadata

    def insights_response_from_result(
        self,
        insights: object,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        return {
            "meta": {"request_id": request_id},
            "data": self.insights_to_response(insights),
        }

    def insights_to_response(self, insights: object) -> dict[str, Any]:
        return {
            "insights_id": insights.insights_id,
            "generated_at": insights.generated_at.isoformat(),
            "scope": insights.scope,
            "health_score": insights.health_score,
            "metrics": insights.metrics,
            "taxonomy": insights.taxonomy,
            "action_items": [
                self.action_item_to_response(item) for item in insights.action_items
            ],
            "recent_activity": [
                self.activity_item_to_response(item) for item in insights.recent_activity
            ],
            "consolidation_plan": [
                self.consolidation_plan_item_to_response(item)
                for item in insights.consolidation_plan
            ],
            "diagnostics": insights.diagnostics,
        }

    def empty_insights_response(
        self,
        *,
        request_id: str,
        policy_mode: str,
        scope_not_found: bool = False,
    ) -> dict[str, Any]:
        diagnostics: dict[str, object] = {
            "policy_mode": policy_mode,
            "retrieval_disabled": True,
            "evidence_only": True,
            "read_only": True,
        }
        if scope_not_found:
            diagnostics = {
                "policy_mode": policy_mode,
                "scope_not_found": True,
                "retrieval_disabled": False,
                "evidence_only": True,
                "read_only": True,
            }
        return {
            "meta": {"request_id": request_id},
            "data": {
                "insights_id": "ins_scope_not_found"
                if scope_not_found
                else "ins_disabled",
                "generated_at": None,
                "scope": {},
                "health_score": 0.0,
                "metrics": {},
                "taxonomy": {},
                "action_items": [],
                "recent_activity": [],
                "consolidation_plan": [],
                "diagnostics": diagnostics,
            },
        }

    def action_item_to_response(self, item: object) -> dict[str, Any]:
        return {
            "id": item.id,
            "severity": item.severity,
            "action": item.action,
            "target_type": item.target_type,
            "target_id": item.target_id,
            "memory_scope_id": item.memory_scope_id,
            "reason": item.reason,
            "preview": item.preview,
            "metadata": self.safe_public_metadata(item.metadata),
        }

    def activity_item_to_response(self, item: object) -> dict[str, Any]:
        return {
            "id": item.id,
            "occurred_at": item.occurred_at.isoformat(),
            "event_type": item.event_type,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "memory_scope_id": item.memory_scope_id,
            "thread_id": item.thread_id,
            "status": item.status,
            "preview": item.preview,
            "metadata": self.safe_public_metadata(item.metadata),
        }

    def consolidation_plan_item_to_response(self, item: object) -> dict[str, Any]:
        return {
            "id": item.id,
            "plan_type": item.plan_type,
            "memory_scope_id": item.memory_scope_id,
            "confidence": item.confidence,
            "canonical_candidate_id": item.canonical_candidate_id,
            "candidate_fact_ids": list(item.candidate_fact_ids),
            "recommended_steps": list(item.recommended_steps),
            "reason": item.reason,
            "preview": item.preview,
            "metadata": self.safe_public_metadata(item.metadata),
        }


__all__ = ("LegacyMemoryInsightsApiResponseMapper",)
