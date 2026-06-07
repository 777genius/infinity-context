import asyncio
from typing import Any

from memo_stack_mcp.application.service import MemoryToolService
from memo_stack_mcp.config import MemoryMcpSettings
from memo_stack_mcp.domain.policy import MemoryMcpDeleteMode


class RelationGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def link_facts(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("link_facts", kwargs))
        return {
            "data": {
                "id": "relation_1",
                "source_fact_id": kwargs["source_fact_id"],
                "target_fact_id": kwargs["target_fact_id"],
                "relation_type": kwargs["relation_type"],
                "reason": kwargs["reason"],
                "status": "active",
            }
        }

    async def list_fact_relations(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list_fact_relations", kwargs))
        return {
            "data": {
                "target": {"id": kwargs["fact_id"]},
                "items": [
                    {
                        "relation": {"id": "relation_1", "relation_type": "supports"},
                        "related_fact": {"id": "fact_2", "text": "target"},
                        "direction": "outgoing",
                    }
                ],
            }
        }

    async def unlink_fact_relation(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("unlink_fact_relation", kwargs))
        return {"data": {"id": kwargs["relation_id"], "status": "deleted"}}


def test_mcp_fact_relations_link_list_and_unlink_policy() -> None:
    async def run() -> None:
        gateway = RelationGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(delete_mode=MemoryMcpDeleteMode.EXPLICIT),
        )

        linked = await service.link_facts(
            source_fact_id="fact_1",
            target_fact_id="fact_2",
            relation_type="supports",
            reason="fact_2 supports fact_1",
        )
        listed = await service.list_fact_relations(fact_id="fact_1", status="active", limit=500)
        unlinked = await service.unlink_fact_relation(relation_id="relation_1")

        assert linked["ok"] is True
        assert linked["diagnostics"]["side_effects"] == ["linked_facts"]
        assert listed["ok"] is True
        assert listed["diagnostics"]["warnings"] == ["limit_clamped_to_max"]
        assert listed["data"]["items"][0]["direction"] == "outgoing"
        assert unlinked["ok"] is True
        assert unlinked["diagnostics"]["side_effects"] == ["unlinked_fact_relation"]
        assert gateway.calls == [
            (
                "link_facts",
                {
                    "source_fact_id": "fact_1",
                    "target_fact_id": "fact_2",
                    "relation_type": "supports",
                    "reason": "fact_2 supports fact_1",
                },
            ),
            ("list_fact_relations", {"fact_id": "fact_1", "status": "active", "limit": 100}),
            ("unlink_fact_relation", {"relation_id": "relation_1"}),
        ]

    asyncio.run(run())


def test_mcp_unlink_fact_relation_respects_delete_mode_off() -> None:
    async def run() -> None:
        result = await MemoryToolService(
            gateway=RelationGateway(),
            settings=MemoryMcpSettings(),
        ).unlink_fact_relation(relation_id="relation_1")

        assert result["ok"] is False
        assert result["error"]["code"] == "memo_stack_mcp.policy.delete_mode_off"

    asyncio.run(run())
