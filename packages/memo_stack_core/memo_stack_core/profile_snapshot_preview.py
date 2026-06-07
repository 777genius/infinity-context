"""Deterministic import preview for portable profile snapshots."""

from __future__ import annotations

from typing import Any

_RECORD_TYPES = ("facts", "documents", "chunks", "relations")
_COUNT_TYPES = (*_RECORD_TYPES, "source_refs")


def build_profile_snapshot_import_preview(
    *,
    payload: dict[str, Any],
    merge_strategy: str,
    conflict_ids: set[str],
) -> dict[str, Any]:
    facts = _records(payload, "facts")
    documents = _records(payload, "documents")
    chunks = _records(payload, "chunks")
    relations = _records(payload, "relations")
    source_refs = _records(payload, "source_refs")
    skipped = skipped_snapshot_ids(
        merge_strategy=merge_strategy,
        conflict_ids=conflict_ids,
        facts=facts,
        documents=documents,
        chunks=chunks,
        relations=relations,
    )
    conflicts = _conflicts_by_type(
        conflict_ids=conflict_ids,
        facts=facts,
        documents=documents,
        chunks=chunks,
        relations=relations,
    )
    superseded_fact_ids = (
        _record_ids(facts) & conflict_ids if merge_strategy == "supersede_matching_facts" else set()
    )
    return {
        "snapshot_counts": snapshot_counts(
            facts=facts,
            documents=documents,
            chunks=chunks,
            relations=relations,
            source_refs=source_refs,
        ),
        "conflict_count": len(conflict_ids),
        "conflicts": {key: sorted(value) for key, value in conflicts.items()},
        "would_import": import_counts(
            facts=facts,
            documents=documents,
            chunks=chunks,
            relations=relations,
            source_refs=source_refs,
            skipped=skipped,
        ),
        "would_skip": _skipped_counts(
            facts=facts,
            documents=documents,
            chunks=chunks,
            relations=relations,
            source_refs=source_refs,
            skipped=skipped,
        ),
        "would_supersede": {
            "facts": len(superseded_fact_ids),
            "fact_ids": sorted(superseded_fact_ids)[:20],
        },
        "warnings": _preview_warnings(
            payload=payload,
            skipped=skipped,
            conflict_ids=conflict_ids,
            merge_strategy=merge_strategy,
        ),
    }


def snapshot_counts(
    *,
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "facts": len(facts),
        "documents": len(documents),
        "chunks": len(chunks),
        "relations": len(relations),
        "source_refs": len(source_refs),
    }


def skipped_snapshot_ids(
    *,
    merge_strategy: str,
    conflict_ids: set[str],
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    relations: list[dict[str, Any]] | None = None,
) -> dict[str, set[str]]:
    relations = relations or []
    fact_ids = _record_ids(facts)
    document_ids = _record_ids(documents)
    chunk_ids = _record_ids(chunks)
    relation_ids = _record_ids(relations)
    skipped_facts = fact_ids & conflict_ids if merge_strategy == "skip_existing" else set()
    skipped_documents = document_ids & conflict_ids
    skipped_chunks = chunk_ids & conflict_ids
    skipped_chunks.update(
        str(chunk["id"])
        for chunk in chunks
        if chunk.get("document_id") is None
        or str(chunk["document_id"]) not in document_ids
        or str(chunk["document_id"]) in skipped_documents
    )
    skipped_relations = relation_ids & conflict_ids
    skipped_relations.update(
        str(relation["id"])
        for relation in relations
        if relation.get("source_fact_id") is None
        or relation.get("target_fact_id") is None
        or str(relation["source_fact_id"]) not in fact_ids
        or str(relation["target_fact_id"]) not in fact_ids
        or str(relation["source_fact_id"]) in skipped_facts
        or str(relation["target_fact_id"]) in skipped_facts
    )
    return {
        "facts": skipped_facts,
        "documents": skipped_documents,
        "chunks": skipped_chunks,
        "relations": skipped_relations,
    }


def import_counts(
    *,
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
    skipped: dict[str, set[str]],
    relations: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    skipped_source_refs = _skipped_source_ref_indexes(source_refs=source_refs, skipped=skipped)
    relations = relations or []
    return {
        "facts": len(facts) - _count_skipped(facts, skipped["facts"]),
        "documents": len(documents) - _count_skipped(documents, skipped["documents"]),
        "chunks": len(chunks) - _count_skipped(chunks, skipped["chunks"]),
        "relations": len(relations) - _count_skipped(relations, skipped["relations"]),
        "source_refs": len(source_refs) - len(skipped_source_refs),
    }


def _skipped_counts(
    *,
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
    skipped: dict[str, set[str]],
) -> dict[str, int]:
    skipped_source_refs = _skipped_source_ref_indexes(source_refs=source_refs, skipped=skipped)
    return {
        "facts": _count_skipped(facts, skipped["facts"]),
        "documents": _count_skipped(documents, skipped["documents"]),
        "chunks": _count_skipped(chunks, skipped["chunks"]),
        "relations": _count_skipped(relations, skipped["relations"]),
        "source_refs": len(skipped_source_refs),
    }


def _conflicts_by_type(
    *,
    conflict_ids: set[str],
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> dict[str, set[str]]:
    conflicts = {
        "facts": _record_ids(facts) & conflict_ids,
        "documents": _record_ids(documents) & conflict_ids,
        "chunks": _record_ids(chunks) & conflict_ids,
        "relations": _record_ids(relations) & conflict_ids,
    }
    known = set().union(*conflicts.values())
    conflicts["unknown"] = conflict_ids - known
    return conflicts


def _preview_warnings(
    *,
    payload: dict[str, Any],
    skipped: dict[str, set[str]],
    conflict_ids: set[str],
    merge_strategy: str,
) -> list[str]:
    warnings: list[str] = []
    if payload.get("redacted") is True:
        warnings.append("redacted_snapshot_cannot_be_applied")
    if skipped["chunks"]:
        warnings.append("some_chunks_will_be_skipped")
    if skipped["relations"]:
        warnings.append("some_relations_will_be_skipped")
    if conflict_ids and merge_strategy == "fail_on_conflict":
        warnings.append("conflicts_block_import")
    return warnings


def _records(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _record_ids(items: list[dict[str, Any]]) -> set[str]:
    return {str(item["id"]) for item in items if item.get("id") is not None}


def _skipped_source_ref_indexes(
    *,
    source_refs: list[dict[str, Any]],
    skipped: dict[str, set[str]],
) -> set[int]:
    return {
        index
        for index, ref in enumerate(source_refs)
        if str(ref.get("fact_id")) in skipped["facts"]
        or (ref.get("chunk_id") is not None and str(ref["chunk_id"]) in skipped["chunks"])
    }


def _count_skipped(items: list[dict[str, Any]], skipped: set[str]) -> int:
    return sum(1 for item in items if str(item["id"]) in skipped)
