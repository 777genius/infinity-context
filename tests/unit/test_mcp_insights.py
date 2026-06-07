import asyncio
from typing import Any

from memo_stack_mcp.application.service import MemoryToolService
from memo_stack_mcp.config import MemoryMcpSettings
from memo_stack_mcp.server import create_mcp_server


class InsightsGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def build_insights(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("build_insights", kwargs))
        return {
            "data": {
                "insights_id": "ins_1",
                "health_score": 87.5,
                "metrics": {"suggestions": {"pending": 1}},
                "taxonomy": {"top_tags": [{"value": "memory", "count": 2}]},
                "action_items": [
                    {
                        "id": "mai_1",
                        "severity": "warning",
                        "action": "review_pending_suggestions",
                        "target_type": "suggestion_queue",
                        "target_id": None,
                        "profile_id": "profile_default",
                        "reason": "1 pending suggestions need review.",
                    }
                ],
                "recent_activity": [
                    {
                        "id": "act_1",
                        "occurred_at": "2026-06-07T10:00:00+00:00",
                        "event_type": "suggestion_created",
                        "entity_type": "suggestion",
                        "entity_id": "sug_1",
                        "profile_id": "profile_default",
                        "status": "pending",
                        "preview": "Review pending memory.",
                    }
                ],
                "consolidation_plan": [
                    {
                        "id": "mplan_1",
                        "plan_type": "similar_fact_review",
                        "profile_id": "profile_default",
                        "confidence": "medium",
                        "canonical_candidate_id": "fact_1",
                        "candidate_fact_ids": ["fact_2"],
                        "recommended_steps": ["Inspect both facts and source refs."],
                        "reason": "Two active facts look similar.",
                    }
                ],
                "diagnostics": {"evidence_only": True, "read_only": True},
            }
        }


def test_mcp_insights_structured_output_and_scope() -> None:
    async def run() -> None:
        gateway = InsightsGateway()
        server = create_mcp_server(
            service=MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())
        )

        result = await server.call_tool(
            "memory_insights",
            {
                "profile_external_refs": ["engineering", "product"],
                "max_suggestions": 25,
            },
        )

        assert result.structuredContent["ok"] is True
        assert result.structuredContent["data"]["insights_id"] == "ins_1"
        assert result.structuredContent["data"]["health_score"] == 87.5
        assert result.structuredContent["data"]["action_items"][0]["action"] == (
            "review_pending_suggestions"
        )
        assert result.structuredContent["data"]["recent_activity"][0]["event_type"] == (
            "suggestion_created"
        )
        assert result.structuredContent["data"]["consolidation_plan"][0]["plan_type"] == (
            "similar_fact_review"
        )
        assert gateway.calls[0][0] == "build_insights"
        assert gateway.calls[0][1]["max_suggestions"] == 25
        assert gateway.calls[0][1]["scope"].profile_external_refs == (
            "engineering",
            "product",
        )

    asyncio.run(run())
