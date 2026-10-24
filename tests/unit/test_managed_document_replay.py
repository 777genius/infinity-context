"""Exact managed replay through real canonical storage and fresh admission."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from benchmark_cleanup_plan_fixtures import cleanup_plan_pair
from infinity_context_adapters.noop import UuidIdGenerator
from infinity_context_adapters.postgres.benchmark_run_repositories import _json_sha256
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryIdempotencyRecordRow,
    MemoryOutboxRow,
)
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWorkFactory,
    build_async_engine,
    build_session_factory,
    create_schema,
)
from infinity_context_core.application.document_fragments import fragment_document_text
from infinity_context_core.application.document_ingestion_replay import validate_document_replay
from infinity_context_core.application.normalize import content_hash
from infinity_context_core.application.use_cases import ingest_document as ingestion
from infinity_context_core.application.use_cases.benchmark_runs import RegisterBenchmarkRunUseCase
from infinity_context_core.domain.entities import MemoryScopeId, SpaceId
from infinity_context_core.domain.errors import MemoryConflictError, MemoryInvariantError
from infinity_context_core.features.document_ingestion.public import (
    document_content_digest,
    legacy_document_content_digest,
)
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_document_fragment_descriptor,
    managed_benchmark_document_operation_material,
    managed_benchmark_infinity_operation_sha256,
    managed_benchmark_text_sha256,
)
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_postgres_managed_document_admission import (
    BINDING,
    RUN,
    SLUG,
    TARGET,
    FixedClock,
    _ingest_command,
    _registration,
    _seed_scope_thread,
)


@asynccontextmanager
async def _fixture(tmp_path):
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'managed-replay.db'}")
    try:
        await create_schema(engine)
        factory = PostgresUnitOfWorkFactory(
            session_factory=build_session_factory(engine), clock=FixedClock()
        )
        command = replace(
            _ingest_command(f"benchmark-space-{RUN[:48]}", "source-1"),
            text="\n".join(
                f"Line {index}: Keep UserID and two  spaces in the exact source."
                for index in range(90)
            ),
            chunk_metadata={
                "source_refs": [
                    {"source_type": "longmemeval", "source_id_sha256": "3" * 64, "page_number": 1},
                    {"source_type": "longmemeval", "source_id_sha256": "4" * 64, "page_number": 2},
                ]
            },
        )
        pieces = fragment_document_text(command.text)
        assert len(pieces) > 1
        fragments = tuple(
            managed_benchmark_document_fragment_descriptor(
                sequence=piece.sequence,
                char_start=piece.char_start,
                char_end=piece.char_end,
                kind=piece.kind.value,
                text=piece.text,
                node_kind=piece.node_kind,
                heading=piece.heading,
                ordinal_in_heading=piece.ordinal_in_heading,
            )
            for piece in pieces
        )
        material = managed_benchmark_document_operation_material(
            source_external_id_sha256=managed_benchmark_text_sha256(command.source_external_id),
            content_sha256=content_hash(command.text),
            title_sha256=managed_benchmark_text_sha256(command.title),
            source_type=command.source_type,
            classification=command.classification,
            source_refs=command.chunk_metadata["source_refs"],
            fragments=fragments,
        )
        plan, _ = cleanup_plan_pair(run_id=RUN, binding=BINDING, target=TARGET, space_slug=SLUG)
        plan["corpora"][0].update(
            memory_scope_external_ref_sha256=managed_benchmark_text_sha256("corpus-1"),
            thread_external_ref_sha256=managed_benchmark_text_sha256("thread-1"),
            infinity_lane="document",
            ordered_infinity_operation_sha256=[
                managed_benchmark_infinity_operation_sha256(material)
            ],
            ordered_infinity_source_external_id_sha256=[material["source_external_id_sha256"]],
            ordered_infinity_content_sha256=[material["content_sha256"]],
            ordered_document_fragment_count=[len(fragments)],
            expected_fact_count=0,
            expected_document_count=1,
            expected_chunk_count=len(fragments),
        )
        plan["cardinality"].update(
            expected_fact_count=0, expected_document_count=1, expected_chunk_count=len(fragments)
        )
        registered = await RegisterBenchmarkRunUseCase(
            uow_factory=factory, clock=FixedClock()
        ).execute(
            replace(_registration(), cleanup_plan_json=plan, cleanup_plan_sha256=_json_sha256(plan))
        )
        await _seed_scope_thread(engine, registered.record.space_id, scope_external_ref="corpus-1")
        yield SimpleNamespace(
            engine=engine,
            factory=factory,
            command=command,
            ingest=ingestion.IngestDocumentUseCase(
                uow_factory=factory, clock=FixedClock(), ids=UuidIdGenerator()
            ),
        )
    finally:
        await engine.dispose()


async def _counts(engine):
    async with AsyncSession(engine) as session:
        return tuple(
            [
                await session.scalar(select(func.count()).select_from(model))
                for model in (
                    MemoryDocumentRow,
                    MemoryChunkRow,
                    MemoryOutboxRow,
                    MemoryIdempotencyRecordRow,
                )
            ]
        )


class _HiddenReads:
    def __init__(self, delegate, *, hide_document: bool):
        self.delegate = delegate
        self.hide_document = hide_document

    async def find(self, **_kwargs):
        return None

    async def find_active_by_content_hash(self, **kwargs):
        if self.hide_document:
            return None
        return await self.delegate.find_active_by_content_hash(**kwargs)

    def __getattr__(self, name):
        return getattr(self.delegate, name)


class _ReadRoutingUow:
    def __init__(self, delegate, *, hide_document: bool):
        self.delegate = delegate
        self.hide_document = hide_document

    async def __aenter__(self):
        await self.delegate.__aenter__()
        self.idempotency = _HiddenReads(self.delegate.idempotency, hide_document=False)
        self.documents = _HiddenReads(self.delegate.documents, hide_document=self.hide_document)
        return self

    async def __aexit__(self, *args):
        return await self.delegate.__aexit__(*args)

    def __getattr__(self, name):
        return getattr(self.delegate, name)


class _ReadRoutingFactory:
    """Force real uniqueness conflicts; all writes and admission remain real."""

    def __init__(self, delegate, *, nested: bool):
        self.delegate = delegate
        self.nested = nested
        self.opened = 0

    def __call__(self):
        self.opened += 1
        uow = self.delegate()
        if self.opened == 1:
            return _ReadRoutingUow(uow, hide_document=True)
        if self.opened == 2 and self.nested:
            return _ReadRoutingUow(uow, hide_document=False)
        return uow


@pytest.mark.parametrize("route", ("receipt", "duplicate", "flush_conflict", "nested_conflict"))
def test_admitted_long_document_replays_preserve_canonical_identity(tmp_path, monkeypatch, route):
    async def run():
        async with _fixture(tmp_path) as fixture:
            first = await fixture.ingest.execute(fixture.command)
            original_counts = await _counts(fixture.engine)
            assert first.document.content_hash == legacy_document_content_digest(
                fixture.command.text
            )
            original_admission = ingestion.require_managed_document_admission
            admissions = []

            async def admit(**kwargs):
                key = await original_admission(**kwargs)
                admissions.append((kwargs["uow"], key))
                assert key is not None
                return key

            monkeypatch.setattr(ingestion, "require_managed_document_admission", admit)
            if route == "duplicate":
                async with AsyncSession(fixture.engine) as session:
                    await session.execute(delete(MemoryIdempotencyRecordRow))
                    await session.commit()
            factory = fixture.factory
            if route in {"flush_conflict", "nested_conflict"}:
                factory = _ReadRoutingFactory(factory, nested=route == "nested_conflict")
            ingest = ingestion.IngestDocumentUseCase(
                uow_factory=factory, clock=FixedClock(), ids=UuidIdGenerator()
            )
            replay = await ingest.execute(fixture.command)
            assert replay.indexing_status == "already_indexed_or_pending"
            assert replay.document.id == first.document.id
            assert tuple(chunk.id for chunk in replay.chunks) == tuple(
                chunk.id for chunk in first.chunks
            )
            assert await _counts(fixture.engine) == original_counts
            assert (
                len(admissions)
                == {"receipt": 1, "duplicate": 1, "flush_conflict": 2, "nested_conflict": 3}[route]
            )
            assert len({id(uow) for uow, _ in admissions}) == len(admissions)
            # A subsequent steady-state receipt replay must be entirely read-only.
            steady = await fixture.ingest.execute(fixture.command)
            assert steady.document.id == first.document.id
            assert await _counts(fixture.engine) == original_counts

    asyncio.run(run())


@pytest.mark.parametrize("change", ("deny", "new_key"))
def test_nested_receipt_conflict_requires_its_own_fresh_admission(tmp_path, monkeypatch, change):
    async def run():
        async with _fixture(tmp_path) as fixture:
            await fixture.ingest.execute(fixture.command)
            counts = await _counts(fixture.engine)
            original_admission = ingestion.require_managed_document_admission
            admissions = []

            async def admit(**kwargs):
                key = await original_admission(**kwargs)
                admissions.append(kwargs["uow"])
                if len(admissions) == 3:
                    if change == "deny":
                        raise MemoryConflictError("Fresh managed admission denied")
                    return key + "-newly-admitted-key"
                return key

            monkeypatch.setattr(ingestion, "require_managed_document_admission", admit)
            ingest = ingestion.IngestDocumentUseCase(
                uow_factory=_ReadRoutingFactory(fixture.factory, nested=True),
                clock=FixedClock(),
                ids=UuidIdGenerator(),
            )
            with pytest.raises(MemoryConflictError):
                await ingest.execute(fixture.command)
            assert len(admissions) == 3
            assert await _counts(fixture.engine) == counts

    asyncio.run(run())


def test_managed_namespace_does_not_replace_successful_admission(tmp_path, monkeypatch):
    async def run():
        async with _fixture(tmp_path) as fixture:
            await fixture.ingest.execute(fixture.command)
            counts = await _counts(fixture.engine)
            original_admission = ingestion.require_managed_document_admission

            async def no_managed_admission(**kwargs):
                await original_admission(**kwargs)
                return None

            monkeypatch.setattr(
                ingestion, "require_managed_document_admission", no_managed_admission
            )
            with pytest.raises(
                MemoryConflictError, match="^Document content differs from the stored request$"
            ):
                await fixture.ingest.execute(fixture.command)
            assert await _counts(fixture.engine) == counts

    asyncio.run(run())


def test_managed_receipt_rejects_a_different_digest_format(tmp_path):
    async def run():
        async with _fixture(tmp_path) as fixture:
            await fixture.ingest.execute(fixture.command)
            async with AsyncSession(fixture.engine) as session:
                row = (await session.execute(select(MemoryIdempotencyRecordRow))).scalar_one()
                row.fingerprint = document_content_digest(fixture.command.text)
                await session.commit()
            counts = await _counts(fixture.engine)
            with pytest.raises(MemoryConflictError, match="Idempotency key was used"):
                await fixture.ingest.execute(fixture.command)
            assert await _counts(fixture.engine) == counts

    asyncio.run(run())


@pytest.mark.parametrize("change", ("case", "whitespace", "source", "thread", "references"))
def test_managed_replay_rejects_changed_command_before_returning_evidence(tmp_path, change):
    async def run():
        async with _fixture(tmp_path) as fixture:
            await fixture.ingest.execute(fixture.command)
            counts = await _counts(fixture.engine)
            command = fixture.command
            if change == "case":
                changed = replace(command, text=command.text.lower())
            elif change == "whitespace":
                changed = replace(command, text=command.text.replace("  ", " "))
            elif change == "source":
                changed = replace(command, source_external_id="unadmitted-source")
            elif change == "thread":
                changed = replace(command, thread_id=None)
            else:
                changed = replace(command, chunk_metadata={"source_refs": []})
            if change in {"case", "whitespace"}:
                assert content_hash(command.text) == content_hash(changed.text)
            with pytest.raises(MemoryConflictError, match="is not admitted"):
                await fixture.ingest.execute(changed)
            assert await _counts(fixture.engine) == counts

    asyncio.run(run())


@pytest.mark.parametrize(
    "corruption",
    (
        "missing",
        "extra",
        "sequence",
        "span",
        "kind",
        "text",
        "title",
        "source",
        "scope",
        "classification",
        "metadata_missing",
        "metadata_extra_empty",
        "metadata_null_missing",
        "metadata_order",
        "metadata_bool",
        "metadata_number",
    ),
)
def test_managed_projection_rejects_incomplete_or_changed_canonical_evidence(tmp_path, corruption):
    async def run():
        async with _fixture(tmp_path) as fixture:
            first = await fixture.ingest.execute(fixture.command)
            document = first.document
            chunks = list(first.chunks)
            if corruption == "missing":
                chunks.pop()
            elif corruption == "extra":
                chunks.append(chunks[-1])
            elif corruption == "sequence":
                chunks[1] = replace(chunks[1], sequence=chunks[0].sequence)
            elif corruption == "span":
                chunks[0] = replace(chunks[0], char_start=chunks[0].char_start + 1)
            elif corruption == "kind":
                chunks[0] = replace(chunks[0], kind="unexpected")
            elif corruption == "text":
                chunks[0] = replace(chunks[0], text=chunks[0].text.lower())
            elif corruption == "title":
                document = replace(document, title="Different title")
            elif corruption == "source":
                document = replace(document, source_external_id="different-source")
                chunks = [replace(chunk, source_external_id="different-source") for chunk in chunks]
            elif corruption == "scope":
                document = replace(document, memory_scope_id=MemoryScopeId("other-scope"))
                chunks = [
                    replace(chunk, memory_scope_id=document.memory_scope_id) for chunk in chunks
                ]
            elif corruption == "classification":
                document = replace(document, classification="public")
                chunks = [replace(chunk, classification="public") for chunk in chunks]
            else:
                index = -1 if corruption == "metadata_extra_empty" else 0
                metadata = dict(chunks[index].metadata)
                if corruption == "metadata_missing":
                    metadata.pop("source_refs")
                elif corruption == "metadata_extra_empty":
                    assert "source_refs" not in metadata
                    metadata["source_refs"] = []
                elif corruption == "metadata_null_missing":
                    assert metadata.pop("heading") is None
                elif corruption == "metadata_order":
                    metadata["source_refs"] = list(reversed(metadata["source_refs"]))
                elif corruption == "metadata_bool":
                    refs = [dict(ref) for ref in metadata["source_refs"]]
                    assert refs[0]["page_number"] == 1
                    refs[0]["page_number"] = True
                    metadata["source_refs"] = refs
                elif corruption == "metadata_number":
                    metadata["source_ref_count"] = float(metadata["source_ref_count"])
                chunks[index] = replace(chunks[index], metadata=metadata)
            expected_error = (
                MemoryConflictError
                if corruption == "text"
                else (MemoryConflictError, MemoryInvariantError)
            )
            with pytest.raises(expected_error):
                validate_document_replay(
                    fixture.command, document, chunks, modern=False, managed=True
                )

    asyncio.run(run())


@pytest.mark.parametrize("corruption", ("ownership", "impossible_span"))
def test_managed_replay_keeps_structural_invariant_errors(tmp_path, corruption):
    async def run():
        async with _fixture(tmp_path) as fixture:
            first = await fixture.ingest.execute(fixture.command)
            chunks = list(first.chunks)
            if corruption == "ownership":
                chunks[0] = replace(chunks[0], document_id="unrelated-document")
            else:
                chunks[0] = replace(chunks[0], char_end=chunks[0].char_start - 1)
            with pytest.raises(
                MemoryInvariantError, match="^Document chunk ownership is incomplete or unrelated$"
            ):
                validate_document_replay(
                    fixture.command, first.document, chunks, modern=False, managed=True
                )

    asyncio.run(run())


def test_managed_projection_conflict_recovers_with_fresh_admission_without_writes(
    tmp_path, monkeypatch
):
    async def run():
        async with _fixture(tmp_path) as fixture:
            first = await fixture.ingest.execute(fixture.command)
            chunk_id = str(first.chunks[0].id)
            async with AsyncSession(fixture.engine) as session:
                row = await session.get(MemoryChunkRow, chunk_id)
                corrupted_text = row.text.lower()
                assert corrupted_text != row.text
                row.text = corrupted_text
                await session.commit()
            counts = await _counts(fixture.engine)
            original_admission = ingestion.require_managed_document_admission
            admissions = []

            async def admit(**kwargs):
                key = await original_admission(**kwargs)
                assert key is not None
                admissions.append(kwargs["uow"])
                return key

            monkeypatch.setattr(ingestion, "require_managed_document_admission", admit)
            with pytest.raises(
                MemoryConflictError,
                match="^Managed document chunk projection is incomplete or divergent$",
            ):
                await fixture.ingest.execute(fixture.command)
            assert len(admissions) == 2
            assert len({id(uow) for uow in admissions}) == 2
            assert await _counts(fixture.engine) == counts
            async with AsyncSession(fixture.engine) as session:
                assert (await session.get(MemoryChunkRow, chunk_id)).text == corrupted_text

    asyncio.run(run())


def test_managed_projection_allows_fetch_order_but_not_ordinary_legacy_expansion(tmp_path):
    async def run():
        async with _fixture(tmp_path) as fixture:
            first = await fixture.ingest.execute(fixture.command)
            replay = validate_document_replay(
                fixture.command,
                first.document,
                list(reversed(first.chunks)),
                modern=False,
                managed=True,
            )
            assert replay.chunks == first.chunks
            ordinary = replace(fixture.command, space_id=SpaceId("ordinary-space"))
            document = replace(first.document, space_id=ordinary.space_id)
            chunks = [replace(chunk, space_id=ordinary.space_id) for chunk in first.chunks]
            with pytest.raises(MemoryConflictError, match="Legacy document source"):
                validate_document_replay(ordinary, document, chunks, modern=False)

    asyncio.run(run())
