"""Outbox process handlers for derived projection adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.domain.entities import (
    FactStatus,
    LifecycleStatus,
    MemoryChunk,
    SourceRef,
)
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
            "vector.upsert_locator_profile": self.handle_locator_profile_upsert,
            "vector.delete_locator_profile": self.handle_locator_profile_delete,
            "vector.replay_locator_profile_tombstones": self.handle_locator_profile_replay,
            "graph.upsert_fact": self.handle_graph_upsert,
            "graph.delete_fact": self.handle_graph_delete,
            "cognee.ingest_document": self.handle_cognee_document_ingest,
            "cognee.forget_document": self.handle_cognee_document_forget,
        }

    def non_fact_handlers(self) -> OutboxHandlerRegistry:
        return {
            event_type: handler
            for event_type, handler in self.handlers().items()
            if event_type not in {"graph.upsert_fact", "graph.delete_fact"}
        }

    def vector_handlers(self) -> OutboxHandlerRegistry:
        return {
            event_type: handler
            for event_type, handler in self.handlers().items()
            if event_type.startswith("vector.")
        }

    def document_handlers(self) -> OutboxHandlerRegistry:
        return {
            event_type: handler
            for event_type, handler in self.handlers().items()
            if event_type.startswith("cognee.")
        }

    async def handle_vector_upsert(self, job: ClaimedOutboxJob) -> None:
        if job.aggregate_type == "locator_chunk":
            return
        chunk_id = str(job.payload_json.get("chunk_id") or job.aggregate_id)
        async with self._container.uow_factory() as uow:
            chunk = await uow.chunks.get_by_id(chunk_id)
        if chunk is None or chunk.status != LifecycleStatus.ACTIVE:
            await self._delete_vector_chunk_from_canonical(chunk_id, chunk)
            return
        initial_space_id = str(chunk.space_id)
        async with self._container.projection_fence.hold(initial_space_id) as permit:
            if not permit.allow_upsert:
                await self._delete_vector_chunk_from_canonical(chunk_id, chunk)
                return
            async with self._container.uow_factory() as uow:
                chunk = await uow.chunks.get_by_id(chunk_id)
                document_token_estimate = 0
                if chunk is not None and chunk.document_id is not None:
                    document_chunks = await uow.documents.list_chunks(str(chunk.document_id))
                    document_token_estimate = sum(item.token_estimate for item in document_chunks)
            if chunk is None or chunk.status != LifecycleStatus.ACTIVE:
                await self._delete_vector_chunk_from_canonical(chunk_id, chunk)
                return
            _require_same_fenced_space(str(chunk.space_id), initial_space_id)
            if not _can_embed(chunk.classification):
                await self._delete_vector_chunk_from_canonical(chunk_id, chunk)
                return
            capabilities = await self._container.vector_index.capabilities()
            if _capability_is_disabled(capabilities):
                return
            if (
                not capabilities.enabled
                or not capabilities.healthy
                or not capabilities.supports_upsert
            ):
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
            _raise_if_degraded(
                embedding.status,
                "embeddings.embed_texts",
                embedding.diagnostics,
            )
            if not embedding.vectors:
                raise RuntimeError("Embedding adapter returned no vectors")

            canonical_version = _chunk_canonical_version(chunk)
            if canonical_version is None:
                raise RuntimeError("canonical vector version is unavailable")
            if "_canonical_retrieval_projection" not in chunk.metadata:
                retrieval_payload: dict[str, object] = {
                    "canonical_version": canonical_version,
                }
            else:
                raw_retrieval_payload = chunk.metadata["_canonical_retrieval_projection"]
                if not isinstance(raw_retrieval_payload, dict):
                    raise RuntimeError("canonical retrieval projection is malformed")
                retrieval_payload = _qdrant_safe_retrieval_payload(raw_retrieval_payload)
                if retrieval_payload.get("canonical_version") != canonical_version:
                    raise RuntimeError("canonical retrieval version is divergent")
            item = VectorUpsertItem(
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
                    **retrieval_payload,
                },
            )
            result = await self._container.vector_index.upsert_chunks((item,))
            _raise_if_degraded(result.status, "vector.upsert_chunks", result.diagnostics)
            # Canonical state may change while embedding or provider I/O is in
            # flight.  Reconcile the generation we just wrote before allowing
            # this event to complete; the exact delete cannot remove a newer
            # ABA/superseding point.
            async with self._container.uow_factory() as uow:
                current = await uow.chunks.get_by_id(chunk_id)
            current_version = _chunk_canonical_version(current)
            if (
                current is None
                or current.status != LifecycleStatus.ACTIVE
                or not _can_embed(current.classification)
                or current_version != canonical_version
            ):
                await self._delete_vector_chunks_if_version(
                    (chunk_id,),
                    canonical_version=canonical_version,
                )
                return
            _require_same_fenced_space(str(current.space_id), initial_space_id)

    async def handle_vector_delete_chunks(self, job: ClaimedOutboxJob) -> None:
        require_delete_completion = _benchmark_cleanup_requires_delete_completion(job.payload_json)
        for canonical_version, chunk_ids in _versioned_chunk_deletes(job):
            await self._delete_vector_chunks_if_version(
                chunk_ids,
                canonical_version=canonical_version,
                require_delete_completion=require_delete_completion,
            )

    async def handle_locator_profile_upsert(self, job: ClaimedOutboxJob) -> None:
        await self._container.retrieval_profile_outbox.upsert(job, now=self._container.clock.now())

    async def handle_locator_profile_delete(self, job: ClaimedOutboxJob) -> None:
        await self._container.retrieval_profile_outbox.delete(job, now=self._container.clock.now())

    async def handle_locator_profile_replay(self, job: ClaimedOutboxJob) -> None:
        await self._container.retrieval_profile_outbox.continue_tombstone_replay(
            job, now=self._container.clock.now()
        )

    async def _delete_vector_chunk_from_canonical(
        self, chunk_id: str, chunk: MemoryChunk | None
    ) -> None:
        canonical_version = _chunk_canonical_version(chunk)
        if canonical_version is None:
            # A missing/ineligible canonical row cannot prove which derived
            # version is safe to remove. Retire this cleanup branch fail closed.
            return
        await self._delete_vector_chunks_if_version(
            (chunk_id,), canonical_version=canonical_version
        )

    async def _delete_vector_chunks_if_version(
        self,
        chunk_ids: tuple[str, ...],
        *,
        canonical_version: int,
        require_delete_completion: bool = False,
    ) -> None:
        result = await self._container.vector_index.delete_chunks_if_version(
            chunk_ids,
            canonical_version=canonical_version,
        )
        _raise_if_degraded(
            result.status,
            "vector.delete_chunks",
            result.diagnostics,
            disabled_is_error=require_delete_completion,
        )

    async def handle_graph_upsert(self, job: ClaimedOutboxJob) -> None:
        async with self._container.uow_factory() as uow:
            fact = await uow.facts.get_by_id(job.aggregate_id)
        if fact is None or fact.status != FactStatus.ACTIVE:
            await self._delete_graph_fact(job.aggregate_id)
            return
        initial_space_id = str(fact.space_id)
        async with self._container.projection_fence.hold(initial_space_id) as permit:
            if not permit.allow_upsert:
                await self._delete_graph_fact(job.aggregate_id)
                return
            async with self._container.uow_factory() as uow:
                fact = await uow.facts.get_by_id(job.aggregate_id)
            if fact is None or fact.status != FactStatus.ACTIVE:
                await self._delete_graph_fact(job.aggregate_id)
                return
            _require_same_fenced_space(str(fact.space_id), initial_space_id)
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
        require_delete_completion = _benchmark_cleanup_requires_delete_completion(job.payload_json)
        await self._delete_graph_fact(
            fact_id,
            require_delete_completion=require_delete_completion,
        )

    async def _delete_graph_fact(
        self,
        fact_id: str,
        *,
        require_delete_completion: bool = False,
    ) -> None:
        result = await self._container.graph_index.delete_fact(fact_id)
        _raise_if_degraded(
            result.status,
            "graph.delete_fact",
            result.diagnostics,
            disabled_is_error=require_delete_completion,
        )

    async def handle_cognee_document_ingest(self, job: ClaimedOutboxJob) -> None:
        document_id = str(job.payload_json.get("document_id") or job.aggregate_id)
        async with self._container.uow_factory() as uow:
            document = await uow.documents.get_by_id(document_id)
        if document is None or document.status != LifecycleStatus.ACTIVE:
            await self._forget_cognee_document(document_id, reason="canonical_document_inactive")
            return
        initial_space_id = str(document.space_id)
        async with self._container.projection_fence.hold(initial_space_id) as permit:
            if not permit.allow_upsert:
                await self._forget_cognee_document(
                    document_id,
                    reason="benchmark_cleanup_pending",
                )
                return
            async with self._container.uow_factory() as uow:
                document = await uow.documents.get_by_id(document_id)
                chunks = (
                    await uow.documents.list_chunks(document_id) if document is not None else []
                )
            if document is None or document.status != LifecycleStatus.ACTIVE:
                await self._forget_cognee_document(
                    document_id,
                    reason="canonical_document_inactive",
                )
                return
            _require_same_fenced_space(str(document.space_id), initial_space_id)
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
        require_delete_completion = _benchmark_cleanup_requires_delete_completion(job.payload_json)
        await self._forget_cognee_document(
            document_id,
            reason="canonical_document_deleted",
            chunk_ids=chunk_ids,
            require_delete_completion=require_delete_completion,
        )

    async def _forget_cognee_document(
        self,
        document_id: str,
        *,
        reason: str,
        chunk_ids: tuple[str, ...] = (),
        require_delete_completion: bool = False,
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
            disabled_is_error=require_delete_completion,
        )


def _raise_if_degraded(
    status: PortStatus,
    operation: str,
    diagnostics: tuple[PortDiagnostic, ...] = (),
    *,
    disabled_is_error: bool = False,
) -> None:
    if _is_disabled_projection(diagnostics) and not disabled_is_error:
        return
    if status != PortStatus.OK:
        diagnostic_code = diagnostics[0].code if diagnostics else f"{operation}.degraded"
        raise OutboxProjectionError(operation, diagnostic_code)


def _raise_if_capability_degraded(
    status: CapabilityStatus,
    operation: str,
    diagnostics: tuple[CapabilityDiagnostic, ...] = (),
    *,
    disabled_is_error: bool = False,
) -> None:
    if status == CapabilityStatus.DISABLED and not disabled_is_error:
        return
    if status != CapabilityStatus.OK:
        default_suffix = "disabled" if status == CapabilityStatus.DISABLED else "degraded"
        diagnostic_code = diagnostics[0].code if diagnostics else f"{operation}.{default_suffix}"
        raise OutboxProjectionError(operation, diagnostic_code)


def _benchmark_cleanup_requires_delete_completion(payload_json: dict[str, object]) -> bool:
    if "cleanup_run_id_sha256" not in payload_json:
        return False
    cleanup_run_id_sha256 = payload_json["cleanup_run_id_sha256"]
    if (
        not isinstance(cleanup_run_id_sha256, str)
        or len(cleanup_run_id_sha256) != 64
        or any(character not in "0123456789abcdef" for character in cleanup_run_id_sha256)
    ):
        raise OutboxProjectionError(
            "benchmark.cleanup_projection",
            "benchmark.cleanup_run_id_sha256_invalid",
        )
    return True


def _versioned_chunk_deletes(
    job: ClaimedOutboxJob,
) -> tuple[tuple[int, tuple[str, ...]], ...]:
    raw_chunk_ids = job.payload_json.get("chunk_ids", [])
    if not isinstance(raw_chunk_ids, list) or any(
        not isinstance(value, str) or not value for value in raw_chunk_ids
    ):
        raise OutboxProjectionError("vector.delete_chunks", "vector.delete_chunk_ids_invalid")
    chunk_ids = tuple(raw_chunk_ids)
    if len(chunk_ids) != len(set(chunk_ids)):
        raise OutboxProjectionError("vector.delete_chunks", "vector.delete_chunk_ids_invalid")
    if not chunk_ids:
        return ()

    if job.aggregate_type == "locator_chunk":
        version = _required_canonical_version(job.aggregate_version)
        return ((version, chunk_ids),)

    raw_versions = job.payload_json.get("chunk_versions")
    if not isinstance(raw_versions, list):
        raise OutboxProjectionError(
            "vector.delete_chunks",
            "vector.delete_canonical_versions_rebuild_required",
        )
    versions_by_id: dict[str, int] = {}
    for item in raw_versions:
        if not isinstance(item, dict) or set(item) != {"chunk_id", "canonical_version"}:
            raise OutboxProjectionError(
                "vector.delete_chunks", "vector.delete_canonical_versions_invalid"
            )
        chunk_id = item["chunk_id"]
        if not isinstance(chunk_id, str) or not chunk_id or chunk_id in versions_by_id:
            raise OutboxProjectionError(
                "vector.delete_chunks", "vector.delete_canonical_versions_invalid"
            )
        versions_by_id[chunk_id] = _required_canonical_version(item["canonical_version"])
    if set(versions_by_id) != set(chunk_ids):
        raise OutboxProjectionError(
            "vector.delete_chunks", "vector.delete_canonical_versions_invalid"
        )
    grouped: dict[int, list[str]] = {}
    for chunk_id in chunk_ids:
        grouped.setdefault(versions_by_id[chunk_id], []).append(chunk_id)
    return tuple((version, tuple(ids)) for version, ids in sorted(grouped.items()))


def _required_canonical_version(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= 9_007_199_254_740_991
    ):
        raise OutboxProjectionError(
            "vector.delete_chunks", "vector.delete_canonical_version_invalid"
        )
    return value


def _chunk_canonical_version(chunk: MemoryChunk | None) -> int | None:
    if chunk is None:
        return None
    try:
        return _required_canonical_version(chunk.canonical_version)
    except OutboxProjectionError:
        return None


def _is_disabled_projection(diagnostics: tuple[PortDiagnostic, ...]) -> bool:
    return any(diagnostic.code.endswith(".disabled") for diagnostic in diagnostics)


def _capability_is_disabled(capabilities: AdapterCapabilities) -> bool:
    return not capabilities.enabled and capabilities.degraded_reason == "disabled"


def _require_same_fenced_space(authoritative_space_id: str, fenced_space_id: str) -> None:
    if authoritative_space_id != fenced_space_id:
        raise OutboxProjectionError(
            "projection.lifecycle_fence",
            "projection.space_changed_during_fence",
        )


def _qdrant_safe_retrieval_payload(payload: dict[str, object]) -> dict[str, object]:
    safe = dict(payload)
    for key in ("start_at", "end_at"):
        value = safe.get(key)
        if value is None:
            continue
        if not isinstance(value, datetime):
            raise RuntimeError("canonical retrieval absolute time is malformed")
        if value.utcoffset() is None:
            value = value.replace(tzinfo=UTC)
        safe[key] = value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return safe


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
