"""Compatibility response helpers for the legacy graph export API."""

from __future__ import annotations

from typing import Any, Protocol


class GraphExportNodeResponseSource(Protocol):
    id: str
    type: str
    label: str
    data: dict[str, object]


class GraphExportEdgeResponseSource(Protocol):
    id: str
    type: str
    source: str
    target: str
    label: str
    data: dict[str, object]


class GraphExportResponseSource(Protocol):
    schema_version: str
    scope: dict[str, object]
    nodes: tuple[GraphExportNodeResponseSource, ...]
    edges: tuple[GraphExportEdgeResponseSource, ...]
    counts: dict[str, int]
    truncated: bool
    warnings: tuple[str, ...]


def graph_export_to_response(graph: GraphExportResponseSource) -> dict[str, Any]:
    """Map a graph export use-case result to the legacy response payload."""

    return {
        "schema_version": graph.schema_version,
        "scope": graph.scope,
        "nodes": [
            {
                "id": node.id,
                "type": node.type,
                "label": node.label,
                "data": node.data,
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "id": edge.id,
                "type": edge.type,
                "source": edge.source,
                "target": edge.target,
                "label": edge.label,
                "data": edge.data,
            }
            for edge in graph.edges
        ],
        "counts": graph.counts,
        "truncated": graph.truncated,
        "warnings": list(graph.warnings),
    }


def graph_export_scope_not_found_response() -> dict[str, Any]:
    """Return the legacy graph export payload for an unresolved memory scope."""

    return {
        "schema_version": "infinity_context.graph_export.v1",
        "scope": {"scope_not_found": True},
        "nodes": [],
        "edges": [],
        "counts": {
            "facts": 0,
            "documents": 0,
            "episodes": 0,
            "chunks": 0,
            "anchors": 0,
            "nodes": 0,
            "edges": 0,
            "relations": 0,
            "anchor_relations": 0,
        },
        "truncated": False,
        "warnings": ["scope_not_found"],
    }


__all__ = (
    "graph_export_scope_not_found_response",
    "graph_export_to_response",
)
