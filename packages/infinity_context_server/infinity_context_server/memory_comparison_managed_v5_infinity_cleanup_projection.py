"""Exact provider-free projection of Infinity ingest cleanup sources."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import final

from infinity_context_core.application.document_fragments import fragment_document_text
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_infinity_operation_sha256,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    memory_scope_external_ref_sha256 as cleanup_v4_scope_external_ref_sha256,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    thread_external_ref_sha256 as cleanup_v4_thread_external_ref_sha256,
)

from infinity_context_server.memory_comparison_canonical_source_hash import (
    document_source_hash,
    memory_source_hash,
)
from infinity_context_server.memory_comparison_conversation_ingestion import (
    conversation_documents,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _reconstruct_managed_corpus_case,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    ManagedPublicRunProjection,
)
from infinity_context_server.memory_comparison_managed_v5_operation_material import (
    managed_v5_infinity_document_operation_material,
    managed_v5_infinity_fact_operation_material,
    managed_v5_infinity_fragment_descriptor,
)


class ManagedV5InfinityCleanupProjectionError(RuntimeError):
    pass


@final
@dataclass(frozen=True, slots=True)
class ManagedV5InfinitySourceDescriptor:
    lane: str
    source_id_sha256: str
    source_content_sha256: str
    expected_chunk_count: int
    operation_commitment_sha256: str

    def __post_init__(self) -> None:
        if (
            self.lane not in {"fact", "document"}
            or not _sha(self.source_id_sha256)
            or not _sha(self.source_content_sha256)
            or type(self.expected_chunk_count) is not int
            or self.expected_chunk_count < 0
            or (self.lane == "fact" and self.expected_chunk_count != 0)
            or (self.lane == "document" and self.expected_chunk_count < 1)
            or not _sha(self.operation_commitment_sha256)
        ):
            _fail("managed_v5_infinity_cleanup_source_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedV5InfinityCorpusCleanupProjection:
    corpus_id: str
    thread_external_ref: str
    scope_external_ref_sha256: str
    thread_external_ref_sha256: str
    cleanup_v4_scope_external_ref_sha256: str
    cleanup_v4_thread_external_ref_sha256: str
    sources: tuple[ManagedV5InfinitySourceDescriptor, ...]

    def __post_init__(self) -> None:
        document_contents = [
            item.source_content_sha256 for item in self.sources if item.lane == "document"
        ]
        if (
            type(self.corpus_id) is not str
            or not self.corpus_id
            or type(self.thread_external_ref) is not str
            or not self.thread_external_ref
            or self.scope_external_ref_sha256 != _text_sha(self.corpus_id)
            or self.thread_external_ref_sha256 != _text_sha(self.thread_external_ref)
            or self.cleanup_v4_scope_external_ref_sha256
            != cleanup_v4_scope_external_ref_sha256(self.corpus_id)
            or self.cleanup_v4_thread_external_ref_sha256
            != cleanup_v4_thread_external_ref_sha256(self.thread_external_ref)
            or type(self.sources) is not tuple
            or not self.sources
            or any(type(item) is not ManagedV5InfinitySourceDescriptor for item in self.sources)
            or len({item.source_id_sha256 for item in self.sources}) != len(self.sources)
            or len(set(document_contents)) != len(document_contents)
        ):
            _fail("managed_v5_infinity_cleanup_corpus_invalid")

    @property
    def expected_fact_count(self) -> int:
        return sum(item.lane == "fact" for item in self.sources)

    @property
    def expected_document_count(self) -> int:
        return sum(item.lane == "document" for item in self.sources)

    @property
    def expected_chunk_count(self) -> int:
        return sum(item.expected_chunk_count for item in self.sources)


@final
@dataclass(frozen=True, slots=True)
class ManagedV5InfinityCleanupProjection:
    corpora: tuple[ManagedV5InfinityCorpusCleanupProjection, ...]

    def __post_init__(self) -> None:
        source_ids = [
            source.source_id_sha256 for corpus in self.corpora for source in corpus.sources
        ]
        if (
            type(self.corpora) is not tuple
            or not self.corpora
            or any(
                type(item) is not ManagedV5InfinityCorpusCleanupProjection for item in self.corpora
            )
            or len({item.corpus_id for item in self.corpora}) != len(self.corpora)
            or len(set(source_ids)) != len(source_ids)
        ):
            _fail("managed_v5_infinity_cleanup_projection_invalid")

    @property
    def expected_source_count(self) -> int:
        return sum(len(item.sources) for item in self.corpora)

    @property
    def expected_fact_count(self) -> int:
        return sum(item.expected_fact_count for item in self.corpora)

    @property
    def expected_document_count(self) -> int:
        return sum(item.expected_document_count for item in self.corpora)

    @property
    def expected_chunk_count(self) -> int:
        return sum(
            source.expected_chunk_count for corpus in self.corpora for source in corpus.sources
        )


def project_managed_v5_infinity_cleanup(
    projection: ManagedPublicRunProjection,
) -> ManagedV5InfinityCleanupProjection:
    """Match exact fact/document operations used by the Infinity HTTP adapter."""

    if type(projection) is not ManagedPublicRunProjection:
        _fail("managed_v5_infinity_cleanup_projection_invalid")
    by_corpus: dict[str, tuple[str, str, tuple[ManagedV5InfinitySourceDescriptor, ...]]] = {}
    order: list[str] = []
    for case in projection.cases:
        try:
            rebuilt = _reconstruct_managed_corpus_case(
                case.record,
                case_id=case.case_id,
                question="managed-ingest-gold-blind-projection",
                temporal_context={},
            )
            if rebuilt.benchmark == "locomo":
                projected_facts: list[ManagedV5InfinitySourceDescriptor] = []
                for memory in rebuilt.memories:
                    identity = memory_source_hash(memory)
                    material = managed_v5_infinity_fact_operation_material(memory)
                    projected_facts.append(
                        ManagedV5InfinitySourceDescriptor(
                            "fact",
                            _text_sha(identity.source_id),
                            identity.source_sha256,
                            0,
                            managed_benchmark_infinity_operation_sha256(material),
                        )
                    )
                sources = tuple(projected_facts)
            else:
                documents = conversation_documents(rebuilt)
                projected_documents: list[ManagedV5InfinitySourceDescriptor] = []
                for document in documents:
                    identity = document_source_hash(document)
                    source_id_sha = _text_sha(identity.source_id)
                    fragments = fragment_document_text(document.text)
                    material = managed_v5_infinity_document_operation_material(
                        document, fragments=fragments
                    )
                    projected_documents.append(
                        ManagedV5InfinitySourceDescriptor(
                            "document",
                            source_id_sha,
                            identity.source_sha256,
                            len(fragments),
                            managed_benchmark_infinity_operation_sha256(material),
                        )
                    )
                sources = tuple(projected_documents)
        except ManagedV5InfinityCleanupProjectionError:
            raise
        except Exception:
            _fail("managed_v5_infinity_cleanup_projection_invalid")
        if not sources:
            _fail("managed_v5_infinity_cleanup_projection_empty")
        if rebuilt.memory_scope_external_ref != case.corpus_id:
            _fail("managed_v5_infinity_cleanup_scope_mismatch")
        thread_sha = _text_sha(rebuilt.thread_external_ref)
        current = (rebuilt.thread_external_ref, thread_sha, sources)
        existing = by_corpus.get(case.corpus_id)
        if existing is None:
            by_corpus[case.corpus_id] = current
            order.append(case.corpus_id)
        elif existing != current:
            _fail("managed_v5_infinity_cleanup_corpus_conflict")
    return ManagedV5InfinityCleanupProjection(
        tuple(
            ManagedV5InfinityCorpusCleanupProjection(
                corpus_id=key,
                thread_external_ref=by_corpus[key][0],
                scope_external_ref_sha256=_text_sha(key),
                thread_external_ref_sha256=by_corpus[key][1],
                cleanup_v4_scope_external_ref_sha256=(cleanup_v4_scope_external_ref_sha256(key)),
                cleanup_v4_thread_external_ref_sha256=(
                    cleanup_v4_thread_external_ref_sha256(by_corpus[key][0])
                ),
                sources=by_corpus[key][2],
            )
            for key in order
        )
    )


def _text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= set("0123456789abcdef")


def _fail(code: str) -> None:
    raise ManagedV5InfinityCleanupProjectionError(code)


__all__ = (
    "ManagedV5InfinityCleanupProjection",
    "ManagedV5InfinityCleanupProjectionError",
    "ManagedV5InfinityCorpusCleanupProjection",
    "ManagedV5InfinitySourceDescriptor",
    "managed_v5_infinity_document_operation_material",
    "managed_v5_infinity_fact_operation_material",
    "managed_v5_infinity_fragment_descriptor",
    "project_managed_v5_infinity_cleanup",
)
