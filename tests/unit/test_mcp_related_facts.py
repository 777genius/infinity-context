import asyncio
from typing import Any

from memo_stack_mcp.application.service import MemoryToolService
from memo_stack_mcp.config import MemoryMcpSettings


class RelatedGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_related_facts(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_related_facts", kwargs))
        return {
            "data": {
                "target": {"id": kwargs["fact_id"], "text": "target"},
                "items": [
                    {
                        "id": "fact_related",
                        "text": "related",
                        "score": 108.0,
                        "relation_reasons": ["shared_source_chunk", "same_category"],
                    }
                ],
                "diagnostics": {"include_other_threads": kwargs["include_other_threads"]},
            }
        }


def test_mcp_related_facts_is_read_only_and_explainable() -> None:
    async def run() -> None:
        gateway = RelatedGateway()
        service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

        result = await service.get_related_facts(
            fact_id="fact_1",
            limit=500,
            include_other_threads=True,
        )

        assert result["ok"] is True
        assert result["diagnostics"]["side_effects"] == []
        assert result["diagnostics"]["warnings"] == ["limit_clamped_to_max"]
        assert result["data"]["items"][0]["relation_reasons"] == [
            "shared_source_chunk",
            "same_category",
        ]
        assert gateway.calls == [
            (
                "get_related_facts",
                {
                    "fact_id": "fact_1",
                    "limit": 50,
                    "include_other_threads": True,
                },
            )
        ]

    asyncio.run(run())
