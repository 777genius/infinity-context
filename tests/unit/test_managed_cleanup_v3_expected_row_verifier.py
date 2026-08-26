from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_verifier import (
    verify_expected_row,
)
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_document_fragment_descriptor,
    managed_benchmark_document_operation_material,
    managed_benchmark_fact_operation_material,
    managed_benchmark_fact_source_ref_descriptor,
    managed_benchmark_infinity_operation_sha256,
    managed_benchmark_text_sha256,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    LOCOMO_PROFILE,
    ManagedCleanupV3Error,
    corpus_identity_sha256,
    fragment_commitments,
    memory_scope_external_ref_sha256,
    source_ref_commitments,
    thread_external_ref_sha256,
)
from test_managed_cleanup_v3_paged_authority import _context


class _Index:
    def __init__(self, operation, source_refs, fragments=()) -> None:
        self.operation = operation
        self.source_refs = source_refs
        self.fragments = fragments

    def lookup_source(self, source_identity_sha256):
        if source_identity_sha256 == self.operation.source_identity_sha256:
            return self.operation
        return None

    def has_corpus(self, corpus_identity_sha256):
        return corpus_identity_sha256 == self.operation.corpus_identity_sha256

    def lookup_source_ref_descriptors(self, sequence):
        return self.source_refs if sequence == self.operation.sequence else ()

    def lookup_fragment_descriptors(self, sequence):
        return self.fragments if sequence == self.operation.sequence else ()

    def lookup_fragment(self, *, sequence, ordinal, descriptor_sha256):
        if (
            sequence == self.operation.sequence
            and ordinal < len(self.fragments)
            and self.fragments[ordinal] == descriptor_sha256
        ):
            return self.operation, ordinal
        return None


def _identity(lane: str):
    scope_ref, thread_ref = "corpus-A", "thread-A"
    scope_sha = memory_scope_external_ref_sha256(scope_ref)
    thread_sha = thread_external_ref_sha256(thread_ref)
    corpus_sha = corpus_identity_sha256(
        lane=lane,
        memory_scope_external_ref_sha256=scope_sha,
        thread_external_ref_sha256=thread_sha,
    )
    return scope_ref, thread_ref, scope_sha, thread_sha, corpus_sha


def _base(context, *, row_id: str, scope_id: str = "scope-1", thread_id="thread-1"):
    return {
        "id": row_id,
        "space_id": context.space_id,
        "memory_scope_id": scope_id,
        "thread_id": thread_id,
        "status": "deleted",
    }


def _fact_fixture():
    context = _context(LOCOMO_PROFILE)
    scope_ref, thread_ref, scope_sha, thread_sha, corpus_sha = _identity("fact")
    fact = {
        **_base(context, row_id="fact-1"),
        "version": 2,
        "text": "remember exactly this",
        "kind": "semantic",
        "classification": "internal",
    }
    ref = {
        "id": 7,
        "fact_id": "fact-1",
        "fact_version": 2,
        "source_type": "manual",
        "source_id": "source-A",
        "chunk_id": None,
        "char_start": None,
        "char_end": None,
        "quote_preview": "remember exactly this",
        "page_number": None,
        "time_start_ms": None,
        "time_end_ms": None,
        "bbox_json": None,
    }
    descriptor = managed_benchmark_fact_source_ref_descriptor(
        source_type="manual",
        source_id="source-A",
        quote_preview="remember exactly this",
    )
    refs_sha, descriptors, refs_root = source_ref_commitments([descriptor])
    content_sha = managed_benchmark_text_sha256(fact["text"])
    material = managed_benchmark_fact_operation_material(
        source_external_id_sha256=managed_benchmark_text_sha256(ref["source_id"]),
        content_sha256=content_sha,
        kind=fact["kind"],
        classification=fact["classification"],
        source_refs=[descriptor],
    )
    operation = SimpleNamespace(
        sequence=11,
        lane="fact",
        corpus_identity_sha256=corpus_sha,
        memory_scope_external_ref_sha256=scope_sha,
        thread_external_ref_sha256=thread_sha,
        source_identity_sha256=managed_benchmark_text_sha256(ref["source_id"]),
        source_content_sha256=content_sha,
        operation_commitment_sha256=managed_benchmark_infinity_operation_sha256(material),
        source_refs_sha256=refs_sha,
        source_ref_root_sha256=refs_root,
    )
    evidence = {
        "memory_scope_external_ref": scope_ref,
        "thread_external_ref": thread_ref,
        "ordered_source_refs": [ref],
    }
    return context, _Index(operation, descriptors), fact, ref, evidence, corpus_sha


def _document_fixture():
    context = _context(LOCOMO_PROFILE)
    scope_ref, thread_ref, scope_sha, thread_sha, corpus_sha = _identity("document")
    text = "alpha beta gamma delta"
    document = {
        **_base(context, row_id="doc-1"),
        "source_external_id": "document-source-A",
        "content_hash": managed_benchmark_text_sha256(text),
        "title": "Document A",
        "source_type": "longmemeval",
        "classification": "internal",
    }
    raw_refs = [
        {"source_type": "longmemeval", "source_id_sha256": f"{index + 1:064x}"}
        for index in range(3)
    ]
    chunks = [
        {
            **_base(context, row_id=f"chunk-{sequence}"),
            "document_id": "doc-1",
            "source_external_id": "document-source-A",
            "sequence": sequence,
            "char_start": start,
            "char_end": end,
            "kind": "text",
            "text": text[start:end],
            "metadata_json": {
                "node_kind": "text",
                "heading": None,
                "ordinal_in_heading": None,
                "source_refs": raw_refs if sequence == 0 else [],
            },
        }
        for sequence, (start, end) in enumerate(((0, 10), (11, len(text))))
    ]
    fragments = [
        managed_benchmark_document_fragment_descriptor(
            sequence=row["sequence"],
            char_start=row["char_start"],
            char_end=row["char_end"],
            kind=row["kind"],
            text=row["text"],
            node_kind="text",
            heading=None,
            ordinal_in_heading=None,
        )
        for row in chunks
    ]
    refs_sha, ref_descriptors, refs_root = source_ref_commitments(raw_refs)
    fragments_sha, fragment_descriptors, fragment_root = fragment_commitments(fragments)
    material = managed_benchmark_document_operation_material(
        source_external_id_sha256=managed_benchmark_text_sha256(document["source_external_id"]),
        content_sha256=document["content_hash"],
        title_sha256=managed_benchmark_text_sha256(document["title"]),
        source_type=document["source_type"],
        classification=document["classification"],
        source_refs=raw_refs,
        fragments=fragments,
    )
    operation = SimpleNamespace(
        sequence=23,
        lane="document",
        corpus_identity_sha256=corpus_sha,
        memory_scope_external_ref_sha256=scope_sha,
        thread_external_ref_sha256=thread_sha,
        source_identity_sha256=managed_benchmark_text_sha256(document["source_external_id"]),
        source_content_sha256=document["content_hash"],
        operation_commitment_sha256=managed_benchmark_infinity_operation_sha256(material),
        source_refs_sha256=refs_sha,
        source_ref_root_sha256=refs_root,
        source_ref_count=3,
        fragments_sha256=fragments_sha,
        fragment_root_sha256=fragment_root,
    )
    index = _Index(operation, ref_descriptors, fragment_descriptors)
    evidence = {
        "memory_scope_external_ref": scope_ref,
        "thread_external_ref": thread_ref,
        "ordered_chunks": chunks,
    }
    return context, index, document, chunks, evidence


def test_scope_and_thread_claim_exact_corpus_identity() -> None:
    context, index, _fact, _ref, evidence, corpus_sha = _fact_fixture()
    scope_ref = evidence["memory_scope_external_ref"]
    thread_ref = evidence["thread_external_ref"]
    identity_evidence = {
        "memory_scope_external_ref": scope_ref,
        "thread_external_ref": thread_ref,
        "lane": "fact",
    }
    scope = {**_base(context, row_id="scope-1", thread_id=None), "external_ref": scope_ref}
    thread = {**_base(context, row_id="thread-1"), "external_ref": thread_ref}
    assert (
        verify_expected_row(
            index=index,
            context=context,
            kind="memory_scopes",
            locator_json={"id": "scope-1"},
            row_json={**scope, "__authority_evidence": identity_evidence},
        )[1]
        == corpus_sha
    )
    assert (
        verify_expected_row(
            index=index,
            context=context,
            kind="memory_threads",
            locator_json={"id": "thread-1"},
            row_json={**thread, "__authority_evidence": identity_evidence},
        )[1]
        == corpus_sha
    )


def test_fact_and_source_ref_verify_full_commitment() -> None:
    context, index, fact, ref, evidence, _corpus = _fact_fixture()
    fact_claim = verify_expected_row(
        index=index,
        context=context,
        kind="facts",
        locator_json={"id": "fact-1"},
        row_json={**fact, "__authority_evidence": evidence},
    )
    ref_evidence = {
        **evidence,
        "canonical_fact": fact,
        "source_ref_ordinal": 0,
    }
    ref_claim = verify_expected_row(
        index=index,
        context=context,
        kind="fact_source_refs",
        locator_json={"id": 7, "fact_id": "fact-1", "fact_version": 2},
        row_json={**ref, "__authority_evidence": ref_evidence},
    )
    assert fact_claim[1] == ref_claim[1] == 11


def test_document_and_chunk_verify_full_commitment() -> None:
    context, index, document, chunks, evidence = _document_fixture()
    assert (
        verify_expected_row(
            index=index,
            context=context,
            kind="documents",
            locator_json={"id": "doc-1"},
            row_json={**document, "__authority_evidence": evidence},
        )[1]
        == 23
    )
    chunk_evidence = {
        "document": document,
        "memory_scope_external_ref": evidence["memory_scope_external_ref"],
        "thread_external_ref": evidence["thread_external_ref"],
        "chunk_ordinal": 1,
    }
    assert (
        verify_expected_row(
            index=index,
            context=context,
            kind="chunks",
            locator_json={"id": "chunk-1"},
            row_json={**chunks[1], "__authority_evidence": chunk_evidence},
        )[1]
        == "23:1"
    )


def test_tampered_source_ref_and_fragment_are_rejected() -> None:
    context, index, fact, _ref, evidence, _corpus = _fact_fixture()
    bad_fact_evidence = deepcopy(evidence)
    bad_fact_evidence["ordered_source_refs"][0]["quote_preview"] = "tampered"
    with pytest.raises(ManagedCleanupV3Error, match="expected_row_fact_invalid"):
        verify_expected_row(
            index=index,
            context=context,
            kind="facts",
            locator_json={"id": "fact-1"},
            row_json={**fact, "__authority_evidence": bad_fact_evidence},
        )

    context, index, document, chunks, evidence = _document_fixture()
    bad_chunks = deepcopy(chunks)
    bad_chunks[1]["text"] = "tampered fragment"
    with pytest.raises(ManagedCleanupV3Error, match="expected_row_document_invalid"):
        verify_expected_row(
            index=index,
            context=context,
            kind="documents",
            locator_json={"id": "doc-1"},
            row_json={
                **document,
                "__authority_evidence": {**evidence, "ordered_chunks": bad_chunks},
            },
        )
