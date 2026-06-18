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
    MemoryEpisode,
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
        lifecycle_status = None if query.include_deleted else LifecycleStatus.ACTIVE.value
        warnings: list[str] = []
        async with self._uow_factory() as uow:
            facts = await uow.facts.list_for_scope(
                space_id=str(query.space_id),
                memory_scope_id=str(query.memory_scope_id),
                thread_id=str(query.thread_id) if query.thread_id else None,
                status=fact_status,
                limit=query.max_facts + 1,
            )
            documents = await uow.documents.list_for_scope(
                space_id=str(query.space_id),
                memory_scope_id=str(query.memory_scope_id),
                thread_id=str(query.thread_id) if query.thread_id else None,
                status=lifecycle_status,
                limit=query.max_documents + 1,
            )
            episodes = await uow.episodes.list_for_scope(
                space_id=str(query.space_id),
                memory_scope_id=str(query.memory_scope_id),
                thread_id=str(query.thread_id) if query.thread_id else None,
                status=lifecycle_status,
                limit=query.max_episodes + 1,
            )
            facts, facts_truncated = _bounded(
                _visible_facts(facts, include_restricted=query.include_restricted),
                query.max_facts,
            )
            documents, documents_truncated = _bounded(
                _visible_documents(documents, include_restricted=query.include_restricted),
                query.max_documents,
            )
            episodes, episodes_truncated = _bounded(episodes, query.max_episodes)
            chunks, chunks_truncated = await _load_parent_chunks(
                documents=documents,
                episodes=episodes,
                max_chunks=query.max_chunks,
                include_restricted=query.include_restricted,
                list_document_chunks=uow.documents.list_chunks,
                list_episode_chunks=uow.chunks.list_for_episode,
            )
            relations = await _load_fact_relations(
                facts=facts,
                status=lifecycle_status,
                list_relations=uow.fact_relations.list_for_fact,
            )

        if facts_truncated:
            warnings.append("facts_truncated")
        if documents_truncated:
            warnings.append("documents_truncated")
        if episodes_truncated:
            warnings.append("episodes_truncated")
        if chunks_truncated:
            warnings.append("chunks_truncated")

        nodes = _build_nodes(
            space_id=str(query.space_id),
            memory_scope_id=str(query.memory_scope_id),
            thread_id=str(query.thread_id) if query.thread_id else None,
            facts=facts,
            documents=documents,
            episodes=episodes,
            chunks=chunks,
        )
        edges = _build_edges(
            facts=facts,
            documents=documents,
            episodes=episodes,
            chunks=chunks,
            relations=relations,
        )
        return GraphExportResult(
            schema_version=_SCHEMA_VERSION,
            scope={
                "space_id": str(query.space_id),
                "memory_scope_id": str(query.memory_scope_id),
                "thread_id": str(query.thread_id) if query.thread_id else None,
            },
            nodes=tuple(nodes),
            edges=tuple(edges),
            counts={
                "facts": len(facts),
                "documents": len(documents),
                "episodes": len(episodes),
                "chunks": len(chunks),
                "relations": len(relations),
                "nodes": len(nodes),
                "edges": len(edges),
            },
            truncated=bool(
                facts_truncated or documents_truncated or episodes_truncated or chunks_truncated
            ),
            warnings=tuple(warnings),
        )


def _visible_facts(
    facts: Iterable[MemoryFact],
    *,
    include_restricted: bool,
) -> list[MemoryFact]:
    if include_restricted:
        return list(facts)
    return [fact for fact in facts if fact.classification != DataClassification.RESTRICTED.value]


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


async def _load_parent_chunks(
    *,
    documents: list[MemoryDocument],
    episodes: list[MemoryEpisode],
    max_chunks: int,
    include_restricted: bool,
    list_document_chunks: Callable[..., Awaitable[list[MemoryChunk]]],
    list_episode_chunks: Callable[..., Awaitable[list[MemoryChunk]]],
) -> tuple[list[MemoryChunk], bool]:
    chunks: list[MemoryChunk] = []
    truncated = False
    for document in documents:
        parent_chunks, parent_truncated = await _load_visible_parent_chunks(
            parent_id=str(document.id),
            max_chunks=max_chunks,
            loaded_chunks=chunks,
            include_restricted=include_restricted,
            list_chunks=list_document_chunks,
        )
        chunks.extend(parent_chunks)
        truncated = truncated or parent_truncated
    for episode in episodes:
        parent_chunks, parent_truncated = await _load_visible_parent_chunks(
            parent_id=str(episode.id),
            max_chunks=max_chunks,
            loaded_chunks=chunks,
            include_restricted=include_restricted,
            list_chunks=list_episode_chunks,
        )
        chunks.extend(parent_chunks)
        truncated = truncated or parent_truncated
    return chunks, truncated


async def _load_visible_parent_chunks(
    *,
    parent_id: str,
    max_chunks: int,
    loaded_chunks: list[MemoryChunk],
    include_restricted: bool,
    list_chunks: Callable[..., Awaitable[list[MemoryChunk]]],
) -> tuple[list[MemoryChunk], bool]:
    remaining = max_chunks - len(loaded_chunks)
    if remaining <= 0:
        return [], True
    parent_chunks = await list_chunks(parent_id, limit=remaining + 1)
    visible_chunks = [
        chunk
        for chunk in parent_chunks
        if include_restricted or chunk.classification != DataClassification.RESTRICTED.value
    ]
    return visible_chunks[:remaining], len(visible_chunks) > remaining


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
    memory_scope_id: str,
    thread_id: str | None,
    facts: list[MemoryFact],
    documents: list[MemoryDocument],
    episodes: list[MemoryEpisode],
    chunks: list[MemoryChunk],
) -> list[GraphExportNode]:
    nodes = [
        GraphExportNode(
            id=f"memory_scope:{memory_scope_id}",
            type="memory_scope",
            label=memory_scope_id,
            data={"space_id": space_id, "memory_scope_id": memory_scope_id, "thread_id": thread_id},
        )
    ]
    nodes.extend(_fact_node(fact) for fact in facts)
    nodes.extend(_document_node(document) for document in documents)
    nodes.extend(_episode_node(episode) for episode in episodes)
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


def _episode_node(episode: MemoryEpisode) -> GraphExportNode:
    return GraphExportNode(
        id=f"episode:{episode.id}",
        type="episode",
        label=_preview(episode.text),
        data={
            "id": str(episode.id),
            "thread_id": str(episode.thread_id),
            "source_type": episode.source_type,
            "source_external_id": episode.source_external_id,
            "speaker": episode.speaker.value,
            "trust_level": episode.trust_level.value,
            "status": episode.status.value,
            "occurred_at": episode.occurred_at.isoformat(),
            "created_at": episode.created_at.isoformat(),
            "text_preview": _preview(episode.text),
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
            "episode_id": str(chunk.episode_id) if chunk.episode_id else None,
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
    episodes: list[MemoryEpisode],
    chunks: list[MemoryChunk],
    relations: list[MemoryFactRelation],
) -> list[GraphExportEdge]:
    edges: list[GraphExportEdge] = []
    memory_scope_id = _memory_scope_id_for_edges(
        facts=facts,
        documents=documents,
        episodes=episodes,
        chunks=chunks,
    )
    if memory_scope_id:
        edges.extend(
            _scope_edges(
                memory_scope_id=memory_scope_id,
                facts=facts,
                documents=documents,
                episodes=episodes,
            )
        )
    edges.extend(_parent_chunk_edges(chunks))
    edges.extend(
        _fact_evidence_edges(facts=facts, documents=documents, episodes=episodes, chunks=chunks)
    )
    edges.extend(_fact_relation_edges(relations))
    return edges


def _memory_scope_id_for_edges(
    *,
    facts: list[MemoryFact],
    documents: list[MemoryDocument],
    episodes: list[MemoryEpisode],
    chunks: list[MemoryChunk],
) -> str | None:
    if facts:
        return str(facts[0].memory_scope_id)
    if documents:
        return str(documents[0].memory_scope_id)
    if episodes:
        return str(episodes[0].memory_scope_id)
    if chunks:
        return str(chunks[0].memory_scope_id)
    return None


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
    memory_scope_id: str,
    facts: list[MemoryFact],
    documents: list[MemoryDocument],
    episodes: list[MemoryEpisode],
) -> list[GraphExportEdge]:
    edges = [
        _edge(
            edge_id=f"memory_scope:{memory_scope_id}->fact:{fact.id}",
            edge_type="contains_fact",
            source=f"memory_scope:{memory_scope_id}",
            target=f"fact:{fact.id}",
            label="contains fact",
        )
        for fact in facts
    ]
    edges.extend(
        _edge(
            edge_id=f"memory_scope:{memory_scope_id}->document:{document.id}",
            edge_type="contains_document",
            source=f"memory_scope:{memory_scope_id}",
            target=f"document:{document.id}",
            label="contains document",
        )
        for document in documents
    )
    edges.extend(
        _edge(
            edge_id=f"memory_scope:{memory_scope_id}->episode:{episode.id}",
            edge_type="contains_episode",
            source=f"memory_scope:{memory_scope_id}",
            target=f"episode:{episode.id}",
            label="contains episode",
        )
        for episode in episodes
    )
    return edges


def _parent_chunk_edges(chunks: list[MemoryChunk]) -> list[GraphExportEdge]:
    edges: list[GraphExportEdge] = []
    for chunk in chunks:
        if chunk.document_id is not None:
            source = f"document:{chunk.document_id}"
        elif chunk.episode_id is not None:
            source = f"episode:{chunk.episode_id}"
        else:
            continue
        edges.append(
            _edge(
                edge_id=f"{source}->chunk:{chunk.id}",
                edge_type="has_chunk",
                source=source,
                target=f"chunk:{chunk.id}",
                label="has chunk",
                data={"sequence": chunk.sequence},
            )
        )
    return edges


def _fact_evidence_edges(
    *,
    facts: list[MemoryFact],
    documents: list[MemoryDocument],
    episodes: list[MemoryEpisode],
    chunks: list[MemoryChunk],
) -> list[GraphExportEdge]:
    chunk_ids = {str(chunk.id) for chunk in chunks}
    document_by_source = {
        (document.source_type, document.source_external_id): str(document.id)
        for document in documents
    }
    episode_by_source = {
        (episode.source_type, episode.source_external_id): str(episode.id) for episode in episodes
    }
    document_ids = {str(document.id) for document in documents}
    episode_ids = {str(episode.id) for episode in episodes}
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
                continue
            episode_id = episode_by_source.get((ref.source_type, ref.source_id))
            if ref.source_id in episode_ids:
                episode_id = ref.source_id
            if episode_id:
                edges.append(
                    _edge(
                        edge_id=f"fact:{fact.id}->episode:{episode_id}:{index}",
                        edge_type="evidenced_by_episode",
                        source=f"fact:{fact.id}",
                        target=f"episode:{episode_id}",
                        label="evidenced by episode",
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
        "page_number": ref.page_number,
        "time_start_ms": ref.time_start_ms,
        "time_end_ms": ref.time_end_ms,
        "bbox": list(ref.bbox) if ref.bbox is not None else None,
    }


def _preview(value: str) -> str:
    stripped = " ".join(value.split())
    if len(stripped) <= _PREVIEW_CHARS:
        return stripped
    return f"{stripped[: _PREVIEW_CHARS - 1]}..."
