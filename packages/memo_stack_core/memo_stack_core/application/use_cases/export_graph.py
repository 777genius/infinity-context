"""Export canonical memory as a portable graph."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar

from memo_stack_core.application.dto import (
    ExportGraphQuery,
    GraphExportEdge,
    GraphExportNode,
    GraphExportResult,
)
from memo_stack_core.domain.entities import (
    DataClassification,
    FactStatus,
    LifecycleStatus,
    MemoryChunk,
    MemoryDocument,
    MemoryFact,
    MemoryFactRelation,
    SourceRef,
)
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort

_SCHEMA_VERSION = "memo_stack.graph_export.v1"
_PREVIEW_CHARS = 180
_T = TypeVar("_T")


class ExportGraphUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: ExportGraphQuery) -> GraphExportResult:
        fact_status = None if query.include_deleted else FactStatus.ACTIVE.value
        document_status = None if query.include_deleted else LifecycleStatus.ACTIVE.value
        warnings: list[str] = []
        async with self._uow_factory() as uow:
            facts = await uow.facts.list_for_scope(
                space_id=str(query.space_id),
                profile_id=str(query.profile_id),
                thread_id=str(query.thread_id) if query.thread_id else None,
                status=fact_status,
                limit=query.max_facts + 1,
            )
            documents = await uow.documents.list_for_scope(
                space_id=str(query.space_id),
                profile_id=str(query.profile_id),
                thread_id=str(query.thread_id) if query.thread_id else None,
                status=document_status,
                limit=query.max_documents + 1,
            )
            facts, facts_truncated = _bounded(
                _visible_facts(facts, include_restricted=query.include_restricted),
                query.max_facts,
            )
            documents, documents_truncated = _bounded(
                _visible_documents(documents, include_restricted=query.include_restricted),
                query.max_documents,
            )
            chunks, chunks_truncated = await _load_document_chunks(
                documents=documents,
                max_chunks=query.max_chunks,
                include_restricted=query.include_restricted,
                list_chunks=uow.documents.list_chunks,
            )
            relations = await _load_fact_relations(
                facts=facts,
                status=None if query.include_deleted else LifecycleStatus.ACTIVE.value,
                list_relations=uow.fact_relations.list_for_fact,
            )

        if facts_truncated:
            warnings.append("facts_truncated")
        if documents_truncated:
            warnings.append("documents_truncated")
        if chunks_truncated:
            warnings.append("chunks_truncated")

        nodes = _build_nodes(
            space_id=str(query.space_id),
            profile_id=str(query.profile_id),
            thread_id=str(query.thread_id) if query.thread_id else None,
            facts=facts,
            documents=documents,
            chunks=chunks,
        )
        edges = _build_edges(facts=facts, documents=documents, chunks=chunks, relations=relations)
        return GraphExportResult(
            schema_version=_SCHEMA_VERSION,
            scope={
                "space_id": str(query.space_id),
                "profile_id": str(query.profile_id),
                "thread_id": str(query.thread_id) if query.thread_id else None,
            },
            nodes=tuple(nodes),
            edges=tuple(edges),
            counts={
                "facts": len(facts),
                "documents": len(documents),
                "chunks": len(chunks),
                "relations": len(relations),
                "nodes": len(nodes),
                "edges": len(edges),
            },
            truncated=bool(facts_truncated or documents_truncated or chunks_truncated),
            warnings=tuple(warnings),
        )


def _visible_facts(
    facts: Iterable[MemoryFact],
    *,
    include_restricted: bool,
) -> list[MemoryFact]:
    if include_restricted:
        return list(facts)
    return [
        fact
        for fact in facts
        if fact.classification != DataClassification.RESTRICTED.value
    ]


def _visible_documents(
    documents: Iterable[MemoryDocument],
    *,
    include_restricted: bool,
) -> list[MemoryDocument]:
    if include_restricted:
        return list(documents)
    return [
        document
        for document in documents
        if document.classification != DataClassification.RESTRICTED.value
    ]


async def _load_document_chunks(
    *,
    documents: list[MemoryDocument],
    max_chunks: int,
    include_restricted: bool,
    list_chunks: Callable[..., Awaitable[list[MemoryChunk]]],
) -> tuple[list[MemoryChunk], bool]:
    chunks: list[MemoryChunk] = []
    truncated = False
    for document in documents:
        remaining = max_chunks - len(chunks)
        if remaining <= 0:
            truncated = True
            break
        document_chunks = await list_chunks(str(document.id), limit=remaining + 1)
        visible_chunks = [
            chunk
            for chunk in document_chunks
            if include_restricted
            or chunk.classification != DataClassification.RESTRICTED.value
        ]
        if len(visible_chunks) > remaining:
            truncated = True
        chunks.extend(visible_chunks[:remaining])
    return chunks, truncated


async def _load_fact_relations(
    *,
    facts: list[MemoryFact],
    status: str | None,
    list_relations: Callable[..., Awaitable[list[MemoryFactRelation]]],
) -> list[MemoryFactRelation]:
    visible_fact_ids = {str(fact.id) for fact in facts}
    by_id: dict[str, MemoryFactRelation] = {}
    for fact_id in sorted(visible_fact_ids):
        for relation in await list_relations(fact_id=fact_id, status=status, limit=200):
            if (
                str(relation.source_fact_id) in visible_fact_ids
                and str(relation.target_fact_id) in visible_fact_ids
            ):
                by_id[str(relation.id)] = relation
    return sorted(by_id.values(), key=lambda relation: str(relation.id))


def _bounded(items: Iterable[_T], limit: int) -> tuple[list[_T], bool]:
    values = list(items)
    return values[:limit], len(values) > limit


def _build_nodes(
    *,
    space_id: str,
    profile_id: str,
    thread_id: str | None,
    facts: list[MemoryFact],
    documents: list[MemoryDocument],
    chunks: list[MemoryChunk],
) -> list[GraphExportNode]:
    nodes = [
        GraphExportNode(
            id=f"profile:{profile_id}",
            type="profile",
            label=profile_id,
            data={"space_id": space_id, "profile_id": profile_id, "thread_id": thread_id},
        )
    ]
    nodes.extend(_fact_node(fact) for fact in facts)
    nodes.extend(_document_node(document) for document in documents)
    nodes.extend(_chunk_node(chunk) for chunk in chunks)
    return nodes


def _fact_node(fact: MemoryFact) -> GraphExportNode:
    return GraphExportNode(
        id=f"fact:{fact.id}",
        type="fact",
        label=_preview(fact.text),
        data={
            "id": str(fact.id),
            "kind": fact.kind.value,
            "status": fact.status.value,
            "version": fact.version,
            "classification": fact.classification,
            "category": fact.category,
            "tags": ",".join(fact.tags),
            "ttl_policy": fact.ttl_policy,
            "expires_at": fact.expires_at.isoformat() if fact.expires_at else None,
            "text": fact.text,
            "created_at": fact.created_at.isoformat(),
            "updated_at": fact.updated_at.isoformat(),
        },
    )


def _document_node(document: MemoryDocument) -> GraphExportNode:
    return GraphExportNode(
        id=f"document:{document.id}",
        type="document",
        label=document.title,
        data={
            "id": str(document.id),
            "title": document.title,
            "source_type": document.source_type,
            "source_external_id": document.source_external_id,
            "status": document.status.value,
            "classification": document.classification,
            "created_at": document.created_at.isoformat(),
            "updated_at": document.updated_at.isoformat(),
        },
    )


def _chunk_node(chunk: MemoryChunk) -> GraphExportNode:
    return GraphExportNode(
        id=f"chunk:{chunk.id}",
        type="chunk",
        label=_preview(chunk.text),
        data={
            "id": str(chunk.id),
            "document_id": str(chunk.document_id) if chunk.document_id else None,
            "kind": chunk.kind.value,
            "node_kind": chunk.metadata.get("node_kind"),
            "heading": chunk.metadata.get("heading"),
            "sequence": chunk.sequence,
            "classification": chunk.classification,
            "text_preview": _preview(chunk.text),
        },
    )


def _build_edges(
    *,
    facts: list[MemoryFact],
    documents: list[MemoryDocument],
    chunks: list[MemoryChunk],
    relations: list[MemoryFactRelation],
) -> list[GraphExportEdge]:
    edges: list[GraphExportEdge] = []
    profile_id = str(facts[0].profile_id if facts else documents[0].profile_id) if (
        facts or documents
    ) else None
    if profile_id:
        edges.extend(_scope_edges(profile_id=profile_id, facts=facts, documents=documents))
    edges.extend(_document_chunk_edges(chunks))
    edges.extend(_fact_evidence_edges(facts=facts, documents=documents, chunks=chunks))
    edges.extend(_fact_relation_edges(relations))
    return edges


def _fact_relation_edges(relations: list[MemoryFactRelation]) -> list[GraphExportEdge]:
    return [
        GraphExportEdge(
            id=f"relation:{relation.id}",
            type=relation.relation_type.value,
            source=f"fact:{relation.source_fact_id}",
            target=f"fact:{relation.target_fact_id}",
            label=relation.relation_type.value,
            data={
                "id": str(relation.id),
                "reason": relation.reason,
                "status": relation.status.value,
                "created_at": relation.created_at.isoformat(),
                "updated_at": relation.updated_at.isoformat(),
            },
        )
        for relation in relations
    ]


def _scope_edges(
    *,
    profile_id: str,
    facts: list[MemoryFact],
    documents: list[MemoryDocument],
) -> list[GraphExportEdge]:
    edges = [
        _edge(
            edge_id=f"profile:{profile_id}->fact:{fact.id}",
            edge_type="contains_fact",
            source=f"profile:{profile_id}",
            target=f"fact:{fact.id}",
            label="contains fact",
        )
        for fact in facts
    ]
    edges.extend(
        _edge(
            edge_id=f"profile:{profile_id}->document:{document.id}",
            edge_type="contains_document",
            source=f"profile:{profile_id}",
            target=f"document:{document.id}",
            label="contains document",
        )
        for document in documents
    )
    return edges


def _document_chunk_edges(chunks: list[MemoryChunk]) -> list[GraphExportEdge]:
    return [
        _edge(
            edge_id=f"document:{chunk.document_id}->chunk:{chunk.id}",
            edge_type="has_chunk",
            source=f"document:{chunk.document_id}",
            target=f"chunk:{chunk.id}",
            label="has chunk",
            data={"sequence": chunk.sequence},
        )
        for chunk in chunks
        if chunk.document_id is not None
    ]


def _fact_evidence_edges(
    *,
    facts: list[MemoryFact],
    documents: list[MemoryDocument],
    chunks: list[MemoryChunk],
) -> list[GraphExportEdge]:
    chunk_ids = {str(chunk.id) for chunk in chunks}
    document_by_source = {
        (document.source_type, document.source_external_id): str(document.id)
        for document in documents
    }
    document_ids = {str(document.id) for document in documents}
    edges: list[GraphExportEdge] = []
    for fact in facts:
        for index, ref in enumerate(fact.source_refs):
            if ref.chunk_id and ref.chunk_id in chunk_ids:
                edges.append(
                    _edge(
                        edge_id=f"fact:{fact.id}->chunk:{ref.chunk_id}:{index}",
                        edge_type="evidenced_by_chunk",
                        source=f"fact:{fact.id}",
                        target=f"chunk:{ref.chunk_id}",
                        label="evidenced by chunk",
                        data=_source_ref_data(ref),
                    )
                )
                continue
            document_id = document_by_source.get((ref.source_type, ref.source_id))
            if ref.source_id in document_ids:
                document_id = ref.source_id
            if document_id:
                edges.append(
                    _edge(
                        edge_id=f"fact:{fact.id}->document:{document_id}:{index}",
                        edge_type="evidenced_by_document",
                        source=f"fact:{fact.id}",
                        target=f"document:{document_id}",
                        label="evidenced by document",
                        data=_source_ref_data(ref),
                    )
                )
    return edges


def _edge(
    *,
    edge_id: str,
    edge_type: str,
    source: str,
    target: str,
    label: str,
    data: dict[str, object] | None = None,
) -> GraphExportEdge:
    return GraphExportEdge(
        id=edge_id,
        type=edge_type,
        source=source,
        target=target,
        label=label,
        data=data or {},
    )


def _source_ref_data(ref: SourceRef) -> dict[str, object]:
    return {
        "source_type": ref.source_type,
        "source_id": ref.source_id,
        "char_start": ref.char_start,
        "char_end": ref.char_end,
        "quote_preview": ref.quote_preview,
    }


def _preview(value: str) -> str:
    stripped = " ".join(value.split())
    if len(stripped) <= _PREVIEW_CHARS:
        return stripped
    return f"{stripped[: _PREVIEW_CHARS - 1]}..."
