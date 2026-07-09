import asyncio
from typing import Any

from infinity_context_mcp.application.service import MemoryToolService
from infinity_context_mcp.config import MemoryMcpSettings
from infinity_context_mcp.domain.models import MemoryGraphExportResponse


class GraphExportGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def export_graph(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "data": {
                "schema_version": "infinity_context.graph_export.v1",
                "scope": {"space_id": "space_1", "memory_scope_id": "memory_scope_1"},
                "nodes": [
                    {
                        "id": "anchor:anchor_1",
                        "type": "anchor",
                        "label": "Atlas",
                        "data": {
                            "aliases": ["Project Atlas", "Atlas"],
                            "metadata": {
                                "labels": ["canonical", "project"],
                                "confidence": 0.93,
                            },
                        },
                    }
                ],
                "edges": [
                    {
                        "id": "anchor:anchor_1->fact:fact_1",
                        "type": "supports",
                        "source": "anchor:anchor_1",
                        "target": "fact:fact_1",
                        "label": "supports",
                        "data": {"bbox": [1.0, 2.0, 30.0, 40.0]},
                    }
                ],
                "counts": {
                    "facts": 1,
                    "documents": 0,
                    "episodes": 0,
                    "chunks": 0,
                    "nodes": 1,
                    "edges": 0,
                },
                "truncated": False,
                "warnings": [],
            }
        }


def test_memory_export_graph_uses_default_scope_and_preserves_payload() -> None:
    gateway = GraphExportGateway()
    service = MemoryToolService(
        gateway=gateway,
        settings=MemoryMcpSettings(
            default_space_slug="client-app",
            default_memory_scope_external_ref="default",
        ),
    )

    response = asyncio.run(service.export_graph())

    parsed = MemoryGraphExportResponse.model_validate(response)
    assert parsed.ok is True
    assert parsed.data is not None
    assert parsed.data.schema_version == "infinity_context.graph_export.v1"
    assert parsed.data.counts["facts"] == 1
    assert parsed.data.nodes[0].data["aliases"] == ["Project Atlas", "Atlas"]
    assert parsed.data.nodes[0].data["metadata"] == {
        "labels": ["canonical", "project"],
        "confidence": 0.93,
    }
    assert parsed.data.edges[0].data["bbox"] == [1.0, 2.0, 30.0, 40.0]
    assert gateway.calls[0]["scope"].space_slug == "client-app"
    assert gateway.calls[0]["scope"].memory_scope_external_ref == "default"
    assert gateway.calls[0]["include_deleted"] is False
    assert gateway.calls[0]["include_restricted"] is False


def test_memory_export_graph_clamps_large_limits() -> None:
    gateway = GraphExportGateway()
    service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

    response = asyncio.run(
        service.export_graph(
            max_facts=9_999,
            max_documents=9_999,
            max_episodes=9_999,
            max_chunks=9_999,
        )
    )

    parsed = MemoryGraphExportResponse.model_validate(response)
    assert parsed.ok is True
    assert parsed.diagnostics.warnings == [
        "max_facts_clamped_to_max",
        "max_documents_clamped_to_max",
        "max_episodes_clamped_to_max",
        "max_chunks_clamped_to_max",
    ]
    assert gateway.calls[0]["max_facts"] == 1_000
    assert gateway.calls[0]["max_documents"] == 500
    assert gateway.calls[0]["max_episodes"] == 500
    assert gateway.calls[0]["max_chunks"] == 2_000
