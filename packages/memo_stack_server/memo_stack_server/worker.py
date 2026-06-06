"""Outbox worker for derived adapter side effects."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import timedelta

from memo_stack_adapters.postgres import create_schema
from memo_stack_adapters.postgres.models import MemoryOutboxRow
from memo_stack_core.application import ConsolidateCaptureCommand
from memo_stack_core.application.document_text import document_chunk_retrieval_text
from memo_stack_core.domain.entities import FactStatus, LifecycleStatus, SourceRef
from memo_stack_core.ports.adapters import (
    AdapterCapabilities,
    PortDiagnostic,
    PortStatus,
    VectorUpsertItem,
)
from memo_stack_core.ports.capabilities import (
    CapabilityDiagnostic,
    CapabilityStatus,
    DocumentMemoryWrite,
    ProjectionForgetRequest,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memo_stack_server.composition import Container, build_container
from memo_stack_server.config import Settings

MAX_ATTEMPTS = 5
RUNNING_LEASE_TIMEOUT = timedelta(minutes=5)


@dataclass(frozen=True)
class ClaimedOutboxJob:
    id: int
    event_type: str
    aggregate_id: str
    aggregate_version: int | None
    attempt_count: int
    workload_class: str
    fairness_key: str | None
    payload_json: dict[str, object]


class OutboxProjectionError(RuntimeError):
    def __init__(self, operation: str, diagnostic_code: str) -> None:
        super().__init__(operation)
        self.diagnostic_code = diagnostic_code


class OutboxWorker:
    def __init__(self, container: Container) -> None:
        self._container = container

    async def run_once(self, *, limit: int = 25) -> int:
        await self._container.expire_pending_suggestions.execute(limit=limit)
        jobs = await self._claim_pending(limit=limit)
        for job in jobs:
            try:
                await self._handle(job)
            except Exception as exc:
                await self._mark_retry_or_dead(job.id, exc)
            else:
                await self._mark_done(job.id)
        return len(jobs)

    async def _claim_pending(self, *, limit: int) -> list[ClaimedOutboxJob]:
        now = self._container.clock.now()
        async with AsyncSession(self._container.engine) as session:
            await self._recover_expired_running_jobs(session, now=now, limit=limit)
            rows = list(
                (
                    await session.execute(
                        select(MemoryOutboxRow)
                        .where(
                            MemoryOutboxRow.status.in_(("pending", "retry_pending")),
                            MemoryOutboxRow.next_attempt_at <= now,
                        )
                        .order_by(MemoryOutboxRow.created_at)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).scalars()
            )
            claimed = [
                ClaimedOutboxJob(
                    id=row.id,
                    event_type=row.event_type,
                    aggregate_id=row.aggregate_id,
                    aggregate_version=row.aggregate_version,
                    attempt_count=row.attempt_count,
                    workload_class=row.workload_class,
                    fairness_key=row.fairness_key,
                    payload_json=dict(row.payload_json),
                )
                for row in rows
            ]
            for row in rows:
                row.status = "running"
                row.updated_at = now
            await session.commit()
            return claimed

    async def _recover_expired_running_jobs(
        self,
        session: AsyncSession,
        *,
        now,
        limit: int,
    ) -> None:
        lease_cutoff = now - RUNNING_LEASE_TIMEOUT
        rows = list(
            (
                await session.execute(
                    select(MemoryOutboxRow)
                    .where(
                        MemoryOutboxRow.status == "running",
                        MemoryOutboxRow.updated_at <= lease_cutoff,
                    )
                    .order_by(MemoryOutboxRow.updated_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for row in rows:
            row.attempt_count += 1
            row.last_safe_error = "Worker lease expired"
            row.last_safe_diagnostic_code = "worker.lease_expired"
            row.updated_at = now
            if row.attempt_count >= MAX_ATTEMPTS:
                row.status = "dead"
            else:
                row.status = "retry_pending"
                row.next_attempt_at = now

    async def _handle(self, job: ClaimedOutboxJob) -> None:
        if job.event_type in {"vector.upsert_chunk", "vector.upsert_chunks"}:
            await self._handle_vector_upsert(job)
        elif job.event_type == "vector.delete_chunks":
            chunk_ids = tuple(str(value) for value in job.payload_json.get("chunk_ids", []))
            result = await self._container.vector_index.delete_chunks(chunk_ids)
            _raise_if_degraded(result.status, "vector.delete_chunks", result.diagnostics)
        elif job.event_type == "graph.upsert_fact":
            await self._handle_graph_upsert(job)
        elif job.event_type == "graph.delete_fact":
            fact_id = str(job.payload_json.get("fact_id") or job.aggregate_id)
            result = await self._container.graph_index.delete_fact(fact_id)
            _raise_if_degraded(result.status, "graph.delete_fact", result.diagnostics)
        elif job.event_type == "cognee.ingest_document":
            await self._handle_cognee_document_ingest(job)
        elif job.event_type == "cognee.forget_document":
            await self._handle_cognee_document_forget(job)
        elif job.event_type == "capture.consolidate":
            await self._container.consolidate_capture.execute(
                ConsolidateCaptureCommand(
                    capture_id=str(job.payload_json.get("capture_id") or job.aggregate_id),
                    force=job.attempt_count > 0,
                )
            )
        else:
            raise ValueError(f"Unknown outbox event type: {job.event_type}")

    async def _handle_vector_upsert(self, job: ClaimedOutboxJob) -> None:
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
                    profile_id=str(chunk.profile_id),
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

    async def _handle_graph_upsert(self, job: ClaimedOutboxJob) -> None:
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
                "profile_id": str(fact.profile_id),
                "updated_at": fact.updated_at.isoformat(),
            },
        )
        _raise_if_degraded(result.status, "graph.upsert_fact", result.diagnostics)

    async def _handle_cognee_document_ingest(self, job: ClaimedOutboxJob) -> None:
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
                profile_id=str(document.profile_id),
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

    async def _handle_cognee_document_forget(self, job: ClaimedOutboxJob) -> None:
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

    async def _mark_done(self, job_id: int) -> None:
        now = self._container.clock.now()
        async with AsyncSession(self._container.engine) as session:
            row = await session.get(MemoryOutboxRow, job_id)
            if row:
                row.status = "done"
                row.last_safe_error = None
                row.last_safe_diagnostic_code = None
                row.updated_at = now
            await session.commit()

    async def _mark_retry_or_dead(self, job_id: int, exc: Exception) -> None:
        now = self._container.clock.now()
        async with AsyncSession(self._container.engine) as session:
            row = await session.get(MemoryOutboxRow, job_id)
            if row:
                row.attempt_count += 1
                row.last_safe_error = _safe_error(exc)[:400]
                row.last_safe_diagnostic_code = _safe_diagnostic_code(exc)[:120]
                row.updated_at = now
                if row.attempt_count >= MAX_ATTEMPTS:
                    row.status = "dead"
                else:
                    row.status = "retry_pending"
                    row.next_attempt_at = now + timedelta(seconds=2**row.attempt_count)
            await session.commit()


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


def _safe_error(exc: Exception) -> str:
    return exc.__class__.__name__[:400]


def _safe_diagnostic_code(exc: Exception) -> str:
    code = getattr(exc, "diagnostic_code", None)
    if isinstance(code, str) and code.strip():
        return code
    return exc.__class__.__name__


async def _run(args: argparse.Namespace) -> None:
    container = build_container(Settings())
    if container.settings.auto_create_schema:
        await create_schema(container.engine)
    worker = OutboxWorker(container)
    try:
        while True:
            count = await worker.run_once(limit=args.limit)
            print({"processed": count})
            if args.once:
                return
            await asyncio.sleep(args.sleep_seconds)
    finally:
        await container.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Memo Stack outbox worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--sleep-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if not args.once and not args.loop:
        args.once = True
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
