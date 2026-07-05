"""Outbox process handlers for derived projection adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.domain.entities import FactStatus, LifecycleStatus, SourceRef
from infinity_context_core.ports.adapters import (
    AdapterCapabilities,
    PortDiagnostic,
    PortStatus,
    VectorUpsertItem,
)
from infinity_context_core.ports.capabilities import (
    CapabilityDiagnostic,
    CapabilityStatus,
    DocumentMemoryWrite,
    ProjectionForgetRequest,
)

from infinity_context_server.processes.outbox import ClaimedOutboxJob, OutboxHandlerRegistry

if TYPE_CHECKING:
    from infinity_context_server.composition import Container


class OutboxProjectionError(RuntimeError):
    def __init__(self, operation: str, diagnostic_code: str) -> None:
        super().__init__(operation)
        self.diagnostic_code = diagnostic_code


class ProjectionOutboxProcess:
    def __init__(self, container: Container) -> None:
        self._container = container

    def handlers(self) -> OutboxHandlerRegistry:
        return {
            "vector.upsert_chunk": self.handle_vector_upsert,
            "vector.upsert_chunks": self.handle_vector_upsert,
            "vector.delete_chunks": self.handle_vector_delete_chunks,
            "graph.upsert_fact": self.handle_graph_upsert,
            "graph.delete_fact": self.handle_graph_delete,
            "cognee.ingest_document": self.handle_cognee_document_ingest,
            "cognee.forget_document": self.handle_cognee_document_forget,
        }

    async def handle_vector_upsert(self, job: ClaimedOutboxJob) -> None:
        chunk_id = str(job.payload_json.get("chunk_id") or job.aggregate_id)
        async with self._container.uow_factory() as uow:
            chunk = await uow.chunks.get_by_id(chunk_id)
            document_token_estimate = 0
            if chunk is not None and chunk.document_id is not None:
                document_chunks = await uow.documents.list_chunks(str(chunk.document_id))
                document_token_estimate = sum(item.token_estimate for item in document_chunks)
        if chunk is None or chunk.status != LifecycleStatus.ACTIVE:
            await self._container.vector_index.delete_chunks((chunk_id,))
            return
        if not _can_embed(chunk.classification):
            return
        capabilities = await self._container.vector_index.capabilities()
        if _capability_is_disabled(capabilities):
            return
        if not capabilities.enabled or not capabilities.healthy or not capabilities.supports_upsert:
            raise RuntimeError("vector adapter unavailable")
        if _document_embedding_budget_exceeded(
            self._container.settings.max_embedding_tokens_per_document,
            document_token_estimate,
        ):
            raise OutboxProjectionError(
                "embeddings.embed_texts",
                "embeddings.document_budget_exceeded",
            )

        projection_text = document_chunk_retrieval_text(
            text=chunk.text,
            metadata=chunk.metadata,
        )
        embedding = await self._container.embedder.embed_texts((projection_text,))
        if _is_disabled_projection(embedding.diagnostics):
            return
        _raise_if_degraded(embedding.status, "embeddings.embed_texts", embedding.diagnostics)
        if not embedding.vectors:
            raise RuntimeError("Embedding adapter returned no vectors")

        result = await self._container.vector_index.upsert_chunks(
            (
                VectorUpsertItem(
                    chunk_id=str(chunk.id),
                    space_id=str(chunk.space_id),
                    memory_scope_id=str(chunk.memory_scope_id),
                    thread_id=str(chunk.thread_id) if chunk.thread_id else None,
                    text=projection_text,
                    vector=embedding.vectors[0],
                    projection_version="v1",
                    metadata={
                        "source_type": chunk.source_type,
                        "kind": chunk.kind.value,
                        "classification": chunk.classification,
                    },
                ),
            )
        )
        _raise_if_degraded(result.status, "vector.upsert_chunks", result.diagnostics)

    async def handle_vector_delete_chunks(self, job: ClaimedOutboxJob) -> None:
        chunk_ids = tuple(str(value) for value in job.payload_json.get("chunk_ids", []))
        result = await self._container.vector_index.delete_chunks(chunk_ids)
        _raise_if_degraded(result.status, "vector.delete_chunks", result.diagnostics)

    async def handle_graph_upsert(self, job: ClaimedOutboxJob) -> None:
        async with self._container.uow_factory() as uow:
            fact = await uow.facts.get_by_id(job.aggregate_id)
        if fact is None or fact.status != FactStatus.ACTIVE:
            await self._container.graph_index.delete_fact(job.aggregate_id)
            return
        if job.aggregate_version and fact.version != job.aggregate_version:
            return
        result = await self._container.graph_index.upsert_fact(
            str(fact.id),
            fact.text,
            {
                "space_id": str(fact.space_id),
                "memory_scope_id": str(fact.memory_scope_id),
                "updated_at": fact.updated_at.isoformat(),
            },
        )
        _raise_if_degraded(result.status, "graph.upsert_fact", result.diagnostics)

    async def handle_graph_delete(self, job: ClaimedOutboxJob) -> None:
        fact_id = str(job.payload_json.get("fact_id") or job.aggregate_id)
        result = await self._container.graph_index.delete_fact(fact_id)
        _raise_if_degraded(result.status, "graph.delete_fact", result.diagnostics)

    async def handle_cognee_document_ingest(self, job: ClaimedOutboxJob) -> None:
        document_id = str(job.payload_json.get("document_id") or job.aggregate_id)
        async with self._container.uow_factory() as uow:
            document = await uow.documents.get_by_id(document_id)
            chunks = await uow.documents.list_chunks(document_id) if document is not None else []
        if document is None or document.status != LifecycleStatus.ACTIVE:
            await self._forget_cognee_document(document_id, reason="canonical_document_inactive")
            return
        if not _can_send_to_external_memory(document.classification):
            return
        safe_chunks = tuple(
            chunk for chunk in chunks if _can_send_to_external_memory(chunk.classification)
        )
        if not safe_chunks:
            return
        result = await self._container.cognee_memory.ingest_document(
            DocumentMemoryWrite(
                document_id=str(document.id),
                space_id=str(document.space_id),
                memory_scope_id=str(document.memory_scope_id),
                title=document.title,
                text="\n\n".join(chunk.text for chunk in safe_chunks),
                source_refs=tuple(_chunk_source_ref(chunk) for chunk in safe_chunks),
                chunk_ids=tuple(str(chunk.id) for chunk in safe_chunks),
                metadata={
                    "classification": document.classification,
                    "source_type": document.source_type,
                },
            )
        )
        _raise_if_capability_degraded(
            result.status,
            "cognee.ingest_document",
            result.diagnostics,
        )

    async def handle_cognee_document_forget(self, job: ClaimedOutboxJob) -> None:
        document_id = str(job.payload_json.get("document_id") or job.aggregate_id)
        chunk_ids = tuple(str(value) for value in job.payload_json.get("chunk_ids", []))
        await self._forget_cognee_document(
            document_id,
            reason="canonical_document_deleted",
            chunk_ids=chunk_ids,
        )

    async def _forget_cognee_document(
        self,
        document_id: str,
        *,
        reason: str,
        chunk_ids: tuple[str, ...] = (),
    ) -> None:
        result = await self._container.cognee_memory.forget_document(
            ProjectionForgetRequest(
                canonical_ids=(document_id, *chunk_ids),
                reason=reason,
            )
        )
        _raise_if_capability_degraded(
            result.status,
            "cognee.forget_document",
            result.diagnostics,
        )


def _raise_if_degraded(
    status: PortStatus,
    operation: str,
    diagnostics: tuple[PortDiagnostic, ...] = (),
) -> None:
    if _is_disabled_projection(diagnostics):
        return
    if status != PortStatus.OK:
        diagnostic_code = diagnostics[0].code if diagnostics else f"{operation}.degraded"
        raise OutboxProjectionError(operation, diagnostic_code)


def _raise_if_capability_degraded(
    status: CapabilityStatus,
    operation: str,
    diagnostics: tuple[CapabilityDiagnostic, ...] = (),
) -> None:
    if status == CapabilityStatus.DISABLED:
        return
    if status != CapabilityStatus.OK:
        diagnostic_code = diagnostics[0].code if diagnostics else f"{operation}.degraded"
        raise OutboxProjectionError(operation, diagnostic_code)


def _is_disabled_projection(diagnostics: tuple[PortDiagnostic, ...]) -> bool:
    return any(diagnostic.code.endswith(".disabled") for diagnostic in diagnostics)


def _capability_is_disabled(capabilities: AdapterCapabilities) -> bool:
    return not capabilities.enabled and capabilities.degraded_reason == "disabled"


def _can_embed(classification: str) -> bool:
    return classification in {"public", "internal"}


def _can_send_to_external_memory(classification: str) -> bool:
    return classification in {"public", "internal"}


def _document_embedding_budget_exceeded(limit: int, token_estimate: int) -> bool:
    return limit > 0 and token_estimate > limit


def _chunk_source_ref(chunk) -> SourceRef:
    return SourceRef(
        source_type=chunk.source_type,
        source_id=chunk.source_external_id,
        chunk_id=str(chunk.id),
        char_start=chunk.char_start,
        char_end=chunk.char_end,
    )
