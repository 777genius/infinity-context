"""Outbox process handlers for derived projection adapters."""

from __future__ import annotations

from datetime import UTC, datetime
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
            "vector.upsert_locator_profile": self.handle_locator_profile_upsert,
            "vector.delete_locator_profile": self.handle_locator_profile_delete,
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
        await self.reconcile_vector_tombstones()
        chunk_id = str(job.payload_json.get("chunk_id") or job.aggregate_id)
        async with self._container.uow_factory() as uow:
            chunk = await uow.chunks.get_by_id(chunk_id)
        if chunk is None or chunk.status != LifecycleStatus.ACTIVE:
            await self._delete_vector_chunks((chunk_id,))
            return
        initial_space_id = str(chunk.space_id)
        async with self._container.projection_fence.hold(initial_space_id) as permit:
            if not permit.allow_upsert:
                await self._delete_vector_chunks((chunk_id,))
                return
            async with self._container.uow_factory() as uow:
                chunk = await uow.chunks.get_by_id(chunk_id)
                document_token_estimate = 0
                if chunk is not None and chunk.document_id is not None:
                    document_chunks = await uow.documents.list_chunks(str(chunk.document_id))
                    document_token_estimate = sum(item.token_estimate for item in document_chunks)
            if chunk is None or chunk.status != LifecycleStatus.ACTIVE:
                await self._delete_vector_chunks((chunk_id,))
                return
            _require_same_fenced_space(str(chunk.space_id), initial_space_id)
            if not _can_embed(chunk.classification):
                await self._delete_vector_chunks((chunk_id,))
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

            if "_canonical_retrieval_projection" not in chunk.metadata:
                retrieval_payload: dict[str, object] = {}
                canonical_version = None
            else:
                raw_retrieval_payload = chunk.metadata["_canonical_retrieval_projection"]
                if not isinstance(raw_retrieval_payload, dict):
                    raise RuntimeError("canonical retrieval projection is malformed")
                retrieval_payload = _qdrant_safe_retrieval_payload(raw_retrieval_payload)
                canonical_version = retrieval_payload.get("canonical_version")
                if not isinstance(canonical_version, int) or isinstance(canonical_version, bool):
                    raise RuntimeError("canonical retrieval version is unavailable")
            legacy_item = VectorUpsertItem(
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
            result = await self._container.vector_index.upsert_chunks((legacy_item,))
            _raise_if_degraded(result.status, "vector.upsert_chunks", result.diagnostics)
            locator_index = getattr(self._container, "locator_vector_index", None)
            if (
                locator_index is not None
                and canonical_version is not None
                and getattr(locator_index, "locator_writes_enabled", True)
                and all(
                    retrieval_payload.get(key)
                    for key in ("locator", "source_key", "projection_generation")
                )
            ):
                locator_metadata = {
                    **retrieval_payload,
                    "kind": retrieval_payload.get("kind", chunk.kind.value),
                    "canonical_identity": str(chunk.id),
                    "canonical_version": canonical_version,
                    "document_key": str(chunk.document_id or ""),
                    "chunk_key": str(chunk.id),
                    "lifecycle_status": "active",
                }
                locator_result = await locator_index.upsert_chunks(
                    (
                        VectorUpsertItem(
                            chunk_id=legacy_item.chunk_id,
                            space_id=legacy_item.space_id,
                            memory_scope_id=legacy_item.memory_scope_id,
                            thread_id=legacy_item.thread_id,
                            text=legacy_item.text,
                            vector=legacy_item.vector,
                            projection_version="document-retrieval-projection.v1",
                            metadata=locator_metadata,
                        ),
                    )
                )
                _raise_if_degraded(
                    locator_result.status,
                    "locator_vector.upsert_chunks",
                    locator_result.diagnostics,
                )

    async def handle_vector_delete_chunks(self, job: ClaimedOutboxJob) -> None:
        chunk_ids = tuple(str(value) for value in job.payload_json.get("chunk_ids", []))
        require_delete_completion = _benchmark_cleanup_requires_delete_completion(job.payload_json)
        canonical_version = job.aggregate_version
        if canonical_version is not None:
            maintenance = getattr(self._container, "locator_projection_maintenance", None)
            authorize = getattr(maintenance, "current_delete_ids", None)
            if not callable(authorize):
                raise OutboxProjectionError(
                    "vector.delete_chunks",
                    "vector.delete_version_fence_unavailable",
                )
            chunk_ids = await authorize(
                chunk_ids,
                canonical_version=canonical_version,
            )
            if not chunk_ids:
                return
        await self._delete_vector_chunks(
            chunk_ids,
            require_delete_completion=require_delete_completion,
            canonical_version=canonical_version,
        )

    async def handle_locator_profile_upsert(self, job: ClaimedOutboxJob) -> None:
        coordinator = getattr(self._container, "retrieval_profile_outbox", None)
        if coordinator is None:
            raise OutboxProjectionError(
                "vector.upsert_locator_profile", "retrieval_profile_runtime_unavailable"
            )
        await coordinator.upsert(job, now=self._container.clock.now())

    async def handle_locator_profile_delete(self, job: ClaimedOutboxJob) -> None:
        coordinator = getattr(self._container, "retrieval_profile_outbox", None)
        if coordinator is None:
            raise OutboxProjectionError(
                "vector.delete_locator_profile", "retrieval_profile_runtime_unavailable"
            )
        await coordinator.delete(job, now=self._container.clock.now())

    async def reconcile_vector_tombstones(self, *, limit: int = 100) -> None:
        maintenance = getattr(self._container, "locator_projection_maintenance", None)
        if maintenance is None:
            return
        lanes = (
            ("legacy", self._container.vector_index),
            ("locator", getattr(self._container, "locator_vector_index", None)),
        )
        for lane, adapter in lanes:
            if adapter is None or not callable(getattr(adapter, "locator_points_absent", None)):
                continue
            pending_deletes = getattr(maintenance, "pending_deletes", None)
            if not callable(pending_deletes):
                continue
            candidates = await pending_deletes(lane, limit=limit)
            for chunk_id, canonical_version in candidates:
                chunk_ids = await maintenance.current_delete_ids(
                    (chunk_id,), canonical_version=canonical_version
                )
                if not chunk_ids:
                    continue
                await self._delete_projection_lane(
                    lane,
                    adapter,
                    chunk_ids,
                    suppress=True,
                    canonical_version=canonical_version,
                )

    async def _delete_vector_chunks(
        self,
        chunk_ids: tuple[str, ...],
        *,
        require_delete_completion: bool = False,
        canonical_version: int | None = None,
    ) -> None:
        failures: list[Exception] = []
        try:
            await self._delete_projection_lane(
                "legacy",
                self._container.vector_index,
                chunk_ids,
                disabled_is_error=require_delete_completion,
                canonical_version=canonical_version,
            )
        except Exception as exc:
            failures.append(exc)
        locator_index = getattr(self._container, "locator_vector_index", None)
        if locator_index is not None:
            try:
                await self._delete_projection_lane(
                    "locator",
                    locator_index,
                    chunk_ids,
                    disabled_is_error=require_delete_completion,
                    canonical_version=canonical_version,
                )
            except Exception as exc:
                failures.append(exc)
        if failures:
            raise failures[0]

    async def _delete_projection_lane(
        self,
        lane: str,
        adapter,
        chunk_ids: tuple[str, ...],
        *,
        disabled_is_error: bool = False,
        suppress: bool = False,
        canonical_version: int | None = None,
    ) -> None:
        try:
            maintenance = getattr(self._container, "locator_projection_maintenance", None)
            observe_absence = getattr(adapter, "locator_points_absent", None)
            if suppress:
                if not callable(observe_absence):
                    return
                absent = await observe_absence(chunk_ids)
                if absent is None:
                    return
                if absent:
                    if maintenance is not None:
                        await maintenance.mark_deleted(
                            lane,
                            chunk_ids,
                            completed_at=self._container.clock.now(),
                            canonical_version=canonical_version,
                        )
                    return
            try:
                if canonical_version is None:
                    result = await adapter.delete_chunks(chunk_ids)
                else:
                    delete_if_version = getattr(adapter, "delete_chunks_if_version", None)
                    if not callable(delete_if_version):
                        raise OutboxProjectionError(
                            "vector.delete_chunks",
                            "vector.delete_version_fence_unsupported",
                        )
                    result = await delete_if_version(chunk_ids, canonical_version=canonical_version)
            except Exception:
                if callable(observe_absence):
                    absent = await observe_absence(chunk_ids)
                    if absent:
                        if maintenance is not None:
                            await maintenance.mark_deleted(
                                lane,
                                chunk_ids,
                                completed_at=self._container.clock.now(),
                                canonical_version=canonical_version,
                            )
                        return
                    if (
                        maintenance is not None
                        and callable(getattr(maintenance, "tracks", None))
                        and await maintenance.tracks(chunk_ids)
                    ):
                        return
                raise
            operation = (
                "vector.delete_chunks" if lane == "legacy" else "locator_vector.delete_chunks"
            )
            disabled = _is_disabled_projection(result.diagnostics)
            try:
                _raise_if_degraded(
                    result.status,
                    operation,
                    result.diagnostics,
                    disabled_is_error=disabled_is_error,
                )
            except Exception:
                if callable(observe_absence):
                    absent = await observe_absence(chunk_ids)
                    if absent and maintenance is not None:
                        await maintenance.mark_deleted(
                            lane,
                            chunk_ids,
                            completed_at=self._container.clock.now(),
                            canonical_version=canonical_version,
                        )
                        return
                    if (
                        maintenance is not None
                        and callable(getattr(maintenance, "tracks", None))
                        and await maintenance.tracks(chunk_ids)
                    ):
                        return
                raise
            if disabled:
                return
            if maintenance is not None:
                await maintenance.mark_deleted(
                    lane,
                    chunk_ids,
                    completed_at=self._container.clock.now(),
                    canonical_version=canonical_version,
                )
        except Exception:
            if not suppress:
                raise

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
