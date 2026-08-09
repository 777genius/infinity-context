"""Pure canonical lineage checks for unsealed recovery inventory."""

from __future__ import annotations

from collections.abc import Sequence

from infinity_context_core.application.normalize import normalize_text, scoped_source_hash
from infinity_context_core.application.use_cases.ingest_document import (
    _source_refs_for_fragment,
)
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_document_fragment_descriptor,
    managed_benchmark_document_operation_material,
    managed_benchmark_fact_operation_material,
    managed_benchmark_fact_source_ref_descriptor,
    managed_benchmark_infinity_operation_sha256,
    managed_benchmark_text_sha256,
)
from infinity_context_core.ports.benchmark_unsealed_projection import (
    BenchmarkUnsealedProjectionScope,
)


def require_chunk_source_hashes(chunks: Sequence[object]) -> None:
    for row in chunks:
        if row.document_id is None or row.episode_id is not None:
            raise MemoryConflictError("Canonical managed chunk owner is invalid")
        expected = scoped_source_hash(
            row.space_id,
            row.memory_scope_id,
            row.document_id,
            row.sequence,
            normalize_text(row.text),
        )
        if row.source_hash != expected:
            raise MemoryConflictError("Canonical chunk source hash differs")


def require_managed_inventory_links(
    plan: dict[str, object],
    *,
    scopes: Sequence[object],
    threads: Sequence[object],
    episodes: Sequence[object],
    documents: Sequence[object],
    chunks: Sequence[object],
    facts: Sequence[object],
    fact_source_refs: Sequence[object],
) -> None:
    if episodes:
        _reject("episode lane")
    corpora = plan.get("corpora")
    if type(corpora) is not list or len(scopes) != len(corpora) or len(threads) != len(corpora):
        _reject("scope cardinality")
    scopes_by_sha = {managed_benchmark_text_sha256(row.external_ref): row for row in scopes}
    threads_by_scope: dict[str, list[object]] = {}
    for row in threads:
        threads_by_scope.setdefault(str(row.memory_scope_id), []).append(row)
    refs_by_fact: dict[tuple[str, int], list[object]] = {}
    for row in fact_source_refs:
        refs_by_fact.setdefault((str(row.fact_id), row.fact_version), []).append(row)
    documents_by_id = {str(row.id): row for row in documents}
    chunks_by_document: dict[str, list[object]] = {}
    for row in chunks:
        if row.document_id is None:
            _reject("chunk owner")
        chunks_by_document.setdefault(str(row.document_id), []).append(row)

    observed_fact_count = observed_document_count = observed_chunk_count = 0
    for corpus in corpora:
        scope = scopes_by_sha.get(corpus["memory_scope_external_ref_sha256"])
        if scope is None:
            _reject("scope external ref")
        scoped_threads = threads_by_scope.get(str(scope.id), [])
        if len(scoped_threads) != 1:
            _reject("thread cardinality")
        thread = scoped_threads[0]
        if (
            managed_benchmark_text_sha256(thread.external_ref)
            != corpus["thread_external_ref_sha256"]
        ):
            _reject("thread external ref")
        scoped_facts = [row for row in facts if str(row.memory_scope_id) == str(scope.id)]
        scoped_documents = [row for row in documents if str(row.memory_scope_id) == str(scope.id)]
        scoped_chunks = [row for row in chunks if str(row.memory_scope_id) == str(scope.id)]
        scoped_rows = (*scoped_facts, *scoped_documents, *scoped_chunks)
        if any(str(row.thread_id) != str(thread.id) for row in scoped_rows):
            _reject("thread lineage")
        if corpus["infinity_lane"] == "fact":
            if scoped_documents or scoped_chunks:
                _reject("foreign document lane")
            observed = _fact_operations(scoped_facts, refs_by_fact)
        else:
            if scoped_facts:
                _reject("foreign fact lane")
            observed = _document_operations(
                scoped_documents,
                chunks_by_document=chunks_by_document,
            )
        expected = {
            source: (content, operation)
            for source, content, operation in zip(
                corpus["ordered_infinity_source_external_id_sha256"],
                corpus["ordered_infinity_content_sha256"],
                corpus["ordered_infinity_operation_sha256"],
                strict=True,
            )
        }
        if observed != expected:
            _reject("operation commitment")
        if (
            len(scoped_facts) != corpus["expected_fact_count"]
            or len(scoped_documents) != corpus["expected_document_count"]
            or len(scoped_chunks) != corpus["expected_chunk_count"]
        ):
            _reject("lane cardinality")
        observed_fact_count += len(scoped_facts)
        observed_document_count += len(scoped_documents)
        observed_chunk_count += len(scoped_chunks)
    cardinality = plan["cardinality"]
    if (
        observed_fact_count != cardinality["expected_fact_count"]
        or observed_document_count != cardinality["expected_document_count"]
        or observed_chunk_count != cardinality["expected_chunk_count"]
        or set(documents_by_id) != set(chunks_by_document)
    ):
        _reject("global cardinality")


def _fact_operations(
    facts: Sequence[object], refs_by_fact: dict[tuple[str, int], list[object]]
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for fact in facts:
        refs = refs_by_fact.get((str(fact.id), fact.version), [])
        if len(refs) != 1:
            _reject("fact source reference")
        ref = refs[0]
        descriptors = [
            managed_benchmark_fact_source_ref_descriptor(
                source_type=ref.source_type,
                source_id=ref.source_id,
                chunk_id=ref.chunk_id,
                char_start=ref.char_start,
                char_end=ref.char_end,
                quote_preview=ref.quote_preview,
                page_number=ref.page_number,
                time_start_ms=ref.time_start_ms,
                time_end_ms=ref.time_end_ms,
                bbox=ref.bbox_json,
            )
        ]
        source_sha = managed_benchmark_text_sha256(ref.source_id)
        content_sha = managed_benchmark_text_sha256(fact.text)
        material = managed_benchmark_fact_operation_material(
            source_external_id_sha256=source_sha,
            content_sha256=content_sha,
            kind=fact.kind,
            classification=fact.classification,
            source_refs=descriptors,
        )
        if source_sha in result:
            _reject("duplicate fact source")
        result[source_sha] = (
            content_sha,
            managed_benchmark_infinity_operation_sha256(material),
        )
    return result


def _document_operations(
    documents: Sequence[object], *, chunks_by_document: dict[str, list[object]]
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for document in documents:
        document_chunks = sorted(
            chunks_by_document.get(str(document.id), []),
            key=lambda row: (row.sequence, str(row.id)),
        )
        if not document_chunks or [row.sequence for row in document_chunks] != list(
            range(len(document_chunks))
        ):
            _reject("document fragments")
        raw_refs = document_chunks[0].metadata_json.get("source_refs", [])
        if type(raw_refs) is not list or any(type(item) is not dict for item in raw_refs):
            _reject("document source references")
        for row in document_chunks:
            observed_refs = row.metadata_json.get("source_refs", [])
            if (
                type(observed_refs) is not list
                or any(type(item) is not dict for item in observed_refs)
                or observed_refs
                != _source_refs_for_fragment(
                    raw_refs,
                    char_start=row.char_start,
                    char_end=row.char_end,
                )
            ):
                _reject("document fragment source references")
        fragments = [
            managed_benchmark_document_fragment_descriptor(
                sequence=row.sequence,
                char_start=row.char_start,
                char_end=row.char_end,
                kind=row.kind,
                text=row.text,
                node_kind=row.metadata_json.get("node_kind"),
                heading=row.metadata_json.get("heading"),
                ordinal_in_heading=row.metadata_json.get("ordinal_in_heading"),
            )
            for row in document_chunks
        ]
        if any(
            row.source_external_id != document.source_external_id
            or row.source_type != document.source_type
            or str(row.memory_scope_id) != str(document.memory_scope_id)
            or str(row.thread_id) != str(document.thread_id)
            for row in document_chunks
        ):
            _reject("document chunk lineage")
        source_sha = managed_benchmark_text_sha256(document.source_external_id)
        material = managed_benchmark_document_operation_material(
            source_external_id_sha256=source_sha,
            content_sha256=document.content_hash,
            title_sha256=managed_benchmark_text_sha256(document.title),
            source_type=document.source_type,
            classification=document.classification,
            source_refs=raw_refs,
            fragments=fragments,
        )
        if source_sha in result:
            _reject("duplicate document source")
        result[source_sha] = (
            document.content_hash,
            managed_benchmark_infinity_operation_sha256(material),
        )
    return result


def projection_scopes(
    scopes: Sequence[object],
    threads: Sequence[object],
    chunks: Sequence[object],
    facts: Sequence[object],
) -> tuple[BenchmarkUnsealedProjectionScope, ...]:
    result = []
    for scope in scopes:
        scoped_threads = [row for row in threads if str(row.memory_scope_id) == str(scope.id)]
        for thread in scoped_threads:
            result.append(
                BenchmarkUnsealedProjectionScope(
                    memory_scope_id=str(scope.id),
                    thread_id=str(thread.id),
                    chunk_ids=tuple(
                        sorted(
                            str(row.id)
                            for row in chunks
                            if row.memory_scope_id == scope.id and row.thread_id == thread.id
                        )
                    ),
                    fact_ids=tuple(
                        sorted(
                            str(row.id)
                            for row in facts
                            if row.memory_scope_id == scope.id and row.thread_id == thread.id
                        )
                    ),
                )
            )
    return tuple(result)


def _reject(label: str) -> None:
    raise MemoryConflictError(f"Managed canonical {label} differs from cleanup plan")


__all__ = (
    "projection_scopes",
    "require_chunk_source_hashes",
    "require_managed_inventory_links",
)
