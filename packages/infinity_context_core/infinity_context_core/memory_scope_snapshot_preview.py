"""Deterministic import preview for portable memory_scope snapshots."""

from __future__ import annotations

from typing import Any

_RECORD_TYPES = (
    "threads",
    "facts",
    "documents",
    "episodes",
    "chunks",
    "assets",
    "asset_extraction_jobs",
    "extraction_artifacts",
    "captures",
    "anchors",
    "context_links",
    "context_link_suggestions",
    "relations",
)
_COUNT_TYPES = (*_RECORD_TYPES, "asset_blobs", "extraction_artifact_blobs", "source_refs")
_ANCHOR_MIGRATION_DEFAULT_FIELDS = (
    ("confidence", "anchor_confidence", True),
    ("evidence_refs", "anchor_evidence_refs", True),
    ("observed_at", "anchor_observed_at", True),
    ("valid_from", "anchor_valid_from", False),
    ("valid_to", "anchor_valid_to", False),
)
_RELATION_MIGRATION_DEFAULT_FIELDS = (
    ("observed_at", "relation_observed_at", True),
    ("valid_from", "relation_valid_from", False),
    ("valid_to", "relation_valid_to", False),
)


def build_memory_scope_snapshot_import_preview(
    *,
    payload: dict[str, Any],
    merge_strategy: str,
    conflict_ids: set[str],
) -> dict[str, Any]:
    threads = _records(payload, "threads")
    facts = _records(payload, "facts")
    documents = _records(payload, "documents")
    episodes = _records(payload, "episodes")
    chunks = _records(payload, "chunks")
    assets = _records(payload, "assets")
    asset_blobs = _records(payload, "asset_blobs")
    asset_extraction_jobs = _records(payload, "asset_extraction_jobs")
    extraction_artifacts = _records(payload, "extraction_artifacts")
    extraction_artifact_blobs = _records(payload, "extraction_artifact_blobs")
    captures = _records(payload, "captures")
    anchors = _records(payload, "anchors")
    context_links = _records(payload, "context_links")
    context_link_suggestions = _records(payload, "context_link_suggestions")
    relations = _records(payload, "relations")
    source_refs = _records(payload, "source_refs")
    skipped = skipped_snapshot_ids(
        merge_strategy=merge_strategy,
        conflict_ids=conflict_ids,
        threads=threads,
        facts=facts,
        documents=documents,
        episodes=episodes,
        chunks=chunks,
        assets=assets,
        asset_blobs=asset_blobs,
        asset_extraction_jobs=asset_extraction_jobs,
        extraction_artifacts=extraction_artifacts,
        extraction_artifact_blobs=extraction_artifact_blobs,
        captures=captures,
        anchors=anchors,
        context_links=context_links,
        context_link_suggestions=context_link_suggestions,
        relations=relations,
        source_refs=source_refs,
    )
    conflicts = _conflicts_by_type(
        conflict_ids=conflict_ids,
        threads=threads,
        facts=facts,
        documents=documents,
        episodes=episodes,
        chunks=chunks,
        assets=assets,
        asset_extraction_jobs=asset_extraction_jobs,
        extraction_artifacts=extraction_artifacts,
        captures=captures,
        anchors=anchors,
        context_links=context_links,
        context_link_suggestions=context_link_suggestions,
        relations=relations,
    )
    superseded_fact_ids = (
        _record_ids(facts) & conflict_ids if merge_strategy == "supersede_matching_facts" else set()
    )
    migration_defaults_applied = _migration_defaults_applied(
        anchors=anchors,
        relations=relations,
    )
    return {
        "snapshot_counts": snapshot_counts(
            threads=threads,
            facts=facts,
            documents=documents,
            episodes=episodes,
            chunks=chunks,
            assets=assets,
            asset_blobs=asset_blobs,
            asset_extraction_jobs=asset_extraction_jobs,
            extraction_artifacts=extraction_artifacts,
            extraction_artifact_blobs=extraction_artifact_blobs,
            captures=captures,
            anchors=anchors,
            context_links=context_links,
            context_link_suggestions=context_link_suggestions,
            relations=relations,
            source_refs=source_refs,
        ),
        "conflict_count": len(conflict_ids),
        "conflicts": {key: sorted(value) for key, value in conflicts.items()},
        "would_import": import_counts(
            threads=threads,
            facts=facts,
            documents=documents,
            episodes=episodes,
            chunks=chunks,
            assets=assets,
            asset_extraction_jobs=asset_extraction_jobs,
            extraction_artifacts=extraction_artifacts,
            captures=captures,
            anchors=anchors,
            context_links=context_links,
            context_link_suggestions=context_link_suggestions,
            relations=relations,
            source_refs=source_refs,
            skipped=skipped,
        ),
        "would_skip": _skipped_counts(
            threads=threads,
            facts=facts,
            documents=documents,
            episodes=episodes,
            chunks=chunks,
            assets=assets,
            asset_extraction_jobs=asset_extraction_jobs,
            extraction_artifacts=extraction_artifacts,
            captures=captures,
            anchors=anchors,
            context_links=context_links,
            context_link_suggestions=context_link_suggestions,
            relations=relations,
            source_refs=source_refs,
            skipped=skipped,
        ),
        "would_supersede": {
            "facts": len(superseded_fact_ids),
            "fact_ids": sorted(superseded_fact_ids)[:20],
        },
        "diagnostics": _preview_diagnostics(
            migration_defaults_applied=migration_defaults_applied,
        ),
        "warnings": _preview_warnings(
            payload=payload,
            skipped=skipped,
            conflict_ids=conflict_ids,
            merge_strategy=merge_strategy,
            migration_defaults_applied=migration_defaults_applied,
        ),
    }


def snapshot_counts(
    *,
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    asset_blobs: list[dict[str, Any]],
    asset_extraction_jobs: list[dict[str, Any]],
    extraction_artifacts: list[dict[str, Any]],
    extraction_artifact_blobs: list[dict[str, Any]],
    captures: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    context_links: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
    threads: list[dict[str, Any]] | None = None,
    context_link_suggestions: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    threads = threads or []
    context_link_suggestions = context_link_suggestions or []
    return {
        "threads": len(threads),
        "facts": len(facts),
        "documents": len(documents),
        "episodes": len(episodes),
        "chunks": len(chunks),
        "assets": len(assets),
        "asset_blobs": len(asset_blobs),
        "asset_extraction_jobs": len(asset_extraction_jobs),
        "extraction_artifacts": len(extraction_artifacts),
        "extraction_artifact_blobs": len(extraction_artifact_blobs),
        "captures": len(captures),
        "anchors": len(anchors),
        "context_links": len(context_links),
        "context_link_suggestions": len(context_link_suggestions),
        "relations": len(relations),
        "source_refs": len(source_refs),
    }


def skipped_snapshot_ids(
    *,
    merge_strategy: str,
    conflict_ids: set[str],
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    asset_blobs: list[dict[str, Any]],
    asset_extraction_jobs: list[dict[str, Any]] | None = None,
    extraction_artifacts: list[dict[str, Any]] | None = None,
    extraction_artifact_blobs: list[dict[str, Any]] | None = None,
    captures: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    context_links: list[dict[str, Any]],
    threads: list[dict[str, Any]] | None = None,
    context_link_suggestions: list[dict[str, Any]] | None = None,
    relations: list[dict[str, Any]] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, set[str]]:
    relations = relations or []
    threads = threads or []
    context_link_suggestions = context_link_suggestions or []
    asset_extraction_jobs = asset_extraction_jobs or []
    extraction_artifacts = extraction_artifacts or []
    extraction_artifact_blobs = extraction_artifact_blobs or []
    source_refs = source_refs or []
    thread_ids = _record_ids(threads)
    fact_ids = _record_ids(facts)
    document_ids = _record_ids(documents)
    episode_ids = _record_ids(episodes)
    chunk_ids = _record_ids(chunks)
    asset_ids = _record_ids(assets)
    asset_blob_asset_ids = _asset_blob_asset_ids(asset_blobs)
    asset_extraction_job_ids = _record_ids(asset_extraction_jobs)
    extraction_artifact_ids = _record_ids(extraction_artifacts)
    extraction_artifact_blob_ids = _extraction_artifact_blob_ids(extraction_artifact_blobs)
    capture_ids = _record_ids(captures)
    anchor_ids = _record_ids(anchors)
    context_link_ids = _record_ids(context_links)
    context_link_suggestion_ids = _record_ids(context_link_suggestions)
    relation_ids = _record_ids(relations)
    skipped_threads = thread_ids & conflict_ids
    skipped_facts = fact_ids & conflict_ids if merge_strategy == "skip_existing" else set()
    skipped_documents = document_ids & conflict_ids
    skipped_episodes = episode_ids & conflict_ids
    skipped_chunks = chunk_ids & conflict_ids
    skipped_assets = asset_ids & conflict_ids
    skipped_asset_extraction_jobs = asset_extraction_job_ids & conflict_ids
    skipped_extraction_artifacts = extraction_artifact_ids & conflict_ids
    skipped_captures = capture_ids & conflict_ids
    skipped_anchors = anchor_ids & conflict_ids
    skipped_context_links = context_link_ids & conflict_ids
    skipped_context_link_suggestions = context_link_suggestion_ids & conflict_ids
    if thread_ids:
        skipped_facts.update(
            str(fact["id"])
            for fact in facts
            if _thread_ref_skipped(fact, thread_ids=thread_ids, skipped_threads=skipped_threads)
        )
        skipped_documents.update(
            str(document["id"])
            for document in documents
            if _thread_ref_skipped(
                document,
                thread_ids=thread_ids,
                skipped_threads=skipped_threads,
            )
        )
        skipped_episodes.update(
            str(episode["id"])
            for episode in episodes
            if _thread_ref_skipped(
                episode,
                thread_ids=thread_ids,
                skipped_threads=skipped_threads,
            )
        )
        skipped_chunks.update(
            str(chunk["id"])
            for chunk in chunks
            if _thread_ref_skipped(chunk, thread_ids=thread_ids, skipped_threads=skipped_threads)
        )
        skipped_assets.update(
            str(asset["id"])
            for asset in assets
            if _thread_ref_skipped(asset, thread_ids=thread_ids, skipped_threads=skipped_threads)
        )
        skipped_asset_extraction_jobs.update(
            str(job["id"])
            for job in asset_extraction_jobs
            if _thread_ref_skipped(job, thread_ids=thread_ids, skipped_threads=skipped_threads)
        )
        skipped_captures.update(
            str(capture["id"])
            for capture in captures
            if _thread_ref_skipped(
                capture,
                thread_ids=thread_ids,
                skipped_threads=skipped_threads,
            )
        )
    skipped_chunks.update(
        str(chunk["id"])
        for chunk in chunks
        if _chunk_parent_skipped(
            chunk,
            document_ids=document_ids,
            skipped_documents=skipped_documents,
            episode_ids=episode_ids,
            skipped_episodes=skipped_episodes,
        )
    )
    # A fact and its declared canonical evidence are one import unit. In
    # particular, skip_existing must never retain the fact after a local chunk
    # or direct document dependency has been skipped and later manufacture an
    # unrelated import citation for it.
    if merge_strategy == "skip_existing":
        skipped_facts.update(
            str(ref["fact_id"])
            for ref in source_refs
            if str(ref.get("fact_id")) in fact_ids
            and _canonical_source_ref_dependency_skipped(
                ref,
                document_ids=document_ids,
                skipped_documents=skipped_documents,
                chunk_ids=chunk_ids,
                skipped_chunks=skipped_chunks,
            )
        )
    skipped_assets.update(
        str(asset["id"])
        for asset in assets
        if _asset_requires_blob(asset) and str(asset["id"]) not in asset_blob_asset_ids
    )
    skipped_asset_extraction_jobs.update(
        str(job["id"])
        for job in asset_extraction_jobs
        if _extraction_job_asset_skipped(
            job,
            asset_ids=asset_ids,
            skipped_assets=skipped_assets,
        )
    )
    skipped_extraction_artifacts.update(
        str(artifact["id"])
        for artifact in extraction_artifacts
        if _extraction_artifact_parent_skipped(
            artifact,
            asset_ids=asset_ids,
            skipped_assets=skipped_assets,
            asset_extraction_job_ids=asset_extraction_job_ids,
            skipped_asset_extraction_jobs=skipped_asset_extraction_jobs,
        )
        or str(artifact["id"]) not in extraction_artifact_blob_ids
    )
    skipped_relations = relation_ids & conflict_ids
    skipped_context_links.update(
        str(context_link["id"])
        for context_link in context_links
        if _context_link_endpoint_skipped(
            context_link,
            fact_ids=fact_ids,
            thread_ids=thread_ids,
            document_ids=document_ids,
            episode_ids=episode_ids,
            chunk_ids=chunk_ids,
            asset_ids=asset_ids,
            asset_extraction_job_ids=asset_extraction_job_ids,
            extraction_artifact_ids=extraction_artifact_ids,
            capture_ids=capture_ids,
            anchor_ids=anchor_ids,
            skipped_facts=skipped_facts,
            skipped_threads=skipped_threads,
            skipped_documents=skipped_documents,
            skipped_episodes=skipped_episodes,
            skipped_chunks=skipped_chunks,
            skipped_assets=skipped_assets,
            skipped_asset_extraction_jobs=skipped_asset_extraction_jobs,
            skipped_extraction_artifacts=skipped_extraction_artifacts,
            skipped_captures=skipped_captures,
            skipped_anchors=skipped_anchors,
        )
    )
    skipped_context_link_suggestions.update(
        str(suggestion["id"])
        for suggestion in context_link_suggestions
        if _context_link_endpoint_skipped(
            suggestion,
            fact_ids=fact_ids,
            thread_ids=thread_ids,
            document_ids=document_ids,
            episode_ids=episode_ids,
            chunk_ids=chunk_ids,
            asset_ids=asset_ids,
            asset_extraction_job_ids=asset_extraction_job_ids,
            extraction_artifact_ids=extraction_artifact_ids,
            capture_ids=capture_ids,
            anchor_ids=anchor_ids,
            skipped_facts=skipped_facts,
            skipped_threads=skipped_threads,
            skipped_documents=skipped_documents,
            skipped_episodes=skipped_episodes,
            skipped_chunks=skipped_chunks,
            skipped_assets=skipped_assets,
            skipped_asset_extraction_jobs=skipped_asset_extraction_jobs,
            skipped_extraction_artifacts=skipped_extraction_artifacts,
            skipped_captures=skipped_captures,
            skipped_anchors=skipped_anchors,
        )
    )
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
        "threads": skipped_threads,
        "facts": skipped_facts,
        "documents": skipped_documents,
        "episodes": skipped_episodes,
        "chunks": skipped_chunks,
        "assets": skipped_assets,
        "asset_extraction_jobs": skipped_asset_extraction_jobs,
        "extraction_artifacts": skipped_extraction_artifacts,
        "captures": skipped_captures,
        "anchors": skipped_anchors,
        "context_links": skipped_context_links,
        "context_link_suggestions": skipped_context_link_suggestions,
        "relations": skipped_relations,
    }


def import_counts(
    *,
    threads: list[dict[str, Any]] | None = None,
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    asset_extraction_jobs: list[dict[str, Any]],
    extraction_artifacts: list[dict[str, Any]],
    captures: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    context_links: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
    skipped: dict[str, set[str]],
    relations: list[dict[str, Any]] | None = None,
    context_link_suggestions: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    skipped_source_refs = _skipped_source_ref_indexes(source_refs=source_refs, skipped=skipped)
    threads = threads or []
    relations = relations or []
    context_link_suggestions = context_link_suggestions or []
    return {
        "threads": len(threads) - _count_skipped(threads, skipped.get("threads", set())),
        "facts": len(facts) - _count_skipped(facts, skipped["facts"]),
        "documents": len(documents) - _count_skipped(documents, skipped["documents"]),
        "episodes": len(episodes) - _count_skipped(episodes, skipped["episodes"]),
        "chunks": len(chunks) - _count_skipped(chunks, skipped["chunks"]),
        "assets": len(assets) - _count_skipped(assets, skipped["assets"]),
        "asset_extraction_jobs": len(asset_extraction_jobs)
        - _count_skipped(asset_extraction_jobs, skipped["asset_extraction_jobs"]),
        "extraction_artifacts": len(extraction_artifacts)
        - _count_skipped(extraction_artifacts, skipped["extraction_artifacts"]),
        "captures": len(captures) - _count_skipped(captures, skipped["captures"]),
        "anchors": len(anchors) - _count_skipped(anchors, skipped["anchors"]),
        "context_links": len(context_links)
        - _count_skipped(context_links, skipped["context_links"]),
        "context_link_suggestions": len(context_link_suggestions)
        - _count_skipped(
            context_link_suggestions,
            skipped.get("context_link_suggestions", set()),
        ),
        "relations": len(relations) - _count_skipped(relations, skipped["relations"]),
        "source_refs": len(source_refs) - len(skipped_source_refs),
    }


def _skipped_counts(
    *,
    threads: list[dict[str, Any]] | None = None,
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    asset_extraction_jobs: list[dict[str, Any]],
    extraction_artifacts: list[dict[str, Any]],
    captures: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    context_links: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
    skipped: dict[str, set[str]],
    context_link_suggestions: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    skipped_source_refs = _skipped_source_ref_indexes(source_refs=source_refs, skipped=skipped)
    threads = threads or []
    context_link_suggestions = context_link_suggestions or []
    return {
        "threads": _count_skipped(threads, skipped.get("threads", set())),
        "facts": _count_skipped(facts, skipped["facts"]),
        "documents": _count_skipped(documents, skipped["documents"]),
        "episodes": _count_skipped(episodes, skipped["episodes"]),
        "chunks": _count_skipped(chunks, skipped["chunks"]),
        "assets": _count_skipped(assets, skipped["assets"]),
        "asset_extraction_jobs": _count_skipped(
            asset_extraction_jobs,
            skipped["asset_extraction_jobs"],
        ),
        "extraction_artifacts": _count_skipped(
            extraction_artifacts,
            skipped["extraction_artifacts"],
        ),
        "captures": _count_skipped(captures, skipped["captures"]),
        "anchors": _count_skipped(anchors, skipped["anchors"]),
        "context_links": _count_skipped(context_links, skipped["context_links"]),
        "context_link_suggestions": _count_skipped(
            context_link_suggestions,
            skipped.get("context_link_suggestions", set()),
        ),
        "relations": _count_skipped(relations, skipped["relations"]),
        "source_refs": len(skipped_source_refs),
    }


def _conflicts_by_type(
    *,
    conflict_ids: set[str],
    threads: list[dict[str, Any]] | None = None,
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    asset_extraction_jobs: list[dict[str, Any]],
    extraction_artifacts: list[dict[str, Any]],
    captures: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    context_links: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    context_link_suggestions: list[dict[str, Any]] | None = None,
) -> dict[str, set[str]]:
    threads = threads or []
    context_link_suggestions = context_link_suggestions or []
    conflicts = {
        "threads": _record_ids(threads) & conflict_ids,
        "facts": _record_ids(facts) & conflict_ids,
        "documents": _record_ids(documents) & conflict_ids,
        "episodes": _record_ids(episodes) & conflict_ids,
        "chunks": _record_ids(chunks) & conflict_ids,
        "assets": _record_ids(assets) & conflict_ids,
        "asset_extraction_jobs": _record_ids(asset_extraction_jobs) & conflict_ids,
        "extraction_artifacts": _record_ids(extraction_artifacts) & conflict_ids,
        "captures": _record_ids(captures) & conflict_ids,
        "anchors": _record_ids(anchors) & conflict_ids,
        "context_links": _record_ids(context_links) & conflict_ids,
        "context_link_suggestions": _record_ids(context_link_suggestions) & conflict_ids,
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
    migration_defaults_applied: dict[str, int],
) -> list[str]:
    warnings: list[str] = []
    if payload.get("redacted") is True:
        warnings.append("redacted_snapshot_cannot_be_applied")
    if skipped.get("threads"):
        warnings.append("some_threads_will_be_skipped")
    if skipped["chunks"]:
        warnings.append("some_chunks_will_be_skipped")
    if skipped["assets"]:
        warnings.append("some_assets_will_be_skipped")
    if skipped["asset_extraction_jobs"]:
        warnings.append("some_asset_extraction_jobs_will_be_skipped")
    if skipped["extraction_artifacts"]:
        warnings.append("some_extraction_artifacts_will_be_skipped")
    if skipped["relations"]:
        warnings.append("some_relations_will_be_skipped")
    if skipped["context_links"]:
        warnings.append("some_context_links_will_be_skipped")
    if skipped.get("context_link_suggestions"):
        warnings.append("some_context_link_suggestions_will_be_skipped")
    if conflict_ids and merge_strategy == "fail_on_conflict":
        warnings.append("conflicts_block_import")
    warnings.extend(
        f"migration_defaults_applied.{key}" for key in migration_defaults_applied
    )
    return warnings


def _preview_diagnostics(
    *,
    migration_defaults_applied: dict[str, int],
) -> dict[str, Any]:
    return {
        "migration_defaults_applied": migration_defaults_applied,
        "migration_defaults_applied_count": sum(migration_defaults_applied.values()),
    }


def _migration_defaults_applied(
    *,
    anchors: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> dict[str, int]:
    defaults: dict[str, int] = {}
    _record_default_counts(
        records=anchors,
        fields=_ANCHOR_MIGRATION_DEFAULT_FIELDS,
        defaults=defaults,
    )
    _record_default_counts(
        records=relations,
        fields=_RELATION_MIGRATION_DEFAULT_FIELDS,
        defaults=defaults,
    )
    return defaults


def _record_default_counts(
    *,
    records: list[dict[str, Any]],
    fields: tuple[tuple[str, str, bool], ...],
    defaults: dict[str, int],
) -> None:
    for field, diagnostic_key, none_defaults in fields:
        count = sum(1 for record in records if _field_will_default(record, field, none_defaults))
        if count:
            defaults[diagnostic_key] = count


def _field_will_default(record: dict[str, Any], field: str, none_defaults: bool) -> bool:
    return field not in record or (none_defaults and record.get(field) is None)


def _records(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _chunk_parent_skipped(
    chunk: dict[str, Any],
    *,
    document_ids: set[str],
    skipped_documents: set[str],
    episode_ids: set[str],
    skipped_episodes: set[str],
) -> bool:
    document_id = chunk.get("document_id")
    episode_id = chunk.get("episode_id")
    if document_id is not None:
        return str(document_id) not in document_ids or str(document_id) in skipped_documents
    if episode_id is not None:
        return str(episode_id) not in episode_ids or str(episode_id) in skipped_episodes
    return True


def _thread_ref_skipped(
    item: dict[str, Any],
    *,
    thread_ids: set[str],
    skipped_threads: set[str],
) -> bool:
    thread_id = item.get("thread_id")
    return thread_id is not None and (
        str(thread_id) not in thread_ids or str(thread_id) in skipped_threads
    )


def _context_link_endpoint_skipped(
    context_link: dict[str, Any],
    *,
    fact_ids: set[str],
    thread_ids: set[str],
    document_ids: set[str],
    episode_ids: set[str],
    chunk_ids: set[str],
    asset_ids: set[str],
    asset_extraction_job_ids: set[str],
    extraction_artifact_ids: set[str],
    capture_ids: set[str],
    anchor_ids: set[str],
    skipped_facts: set[str],
    skipped_threads: set[str],
    skipped_documents: set[str],
    skipped_episodes: set[str],
    skipped_chunks: set[str],
    skipped_assets: set[str],
    skipped_asset_extraction_jobs: set[str],
    skipped_extraction_artifacts: set[str],
    skipped_captures: set[str],
    skipped_anchors: set[str],
) -> bool:
    return _endpoint_skipped(
        source_type=context_link.get("source_type"),
        source_id=context_link.get("source_id"),
        fact_ids=fact_ids,
        thread_ids=thread_ids,
        document_ids=document_ids,
        episode_ids=episode_ids,
        chunk_ids=chunk_ids,
        asset_ids=asset_ids,
        asset_extraction_job_ids=asset_extraction_job_ids,
        extraction_artifact_ids=extraction_artifact_ids,
        capture_ids=capture_ids,
        anchor_ids=anchor_ids,
        skipped_facts=skipped_facts,
        skipped_threads=skipped_threads,
        skipped_documents=skipped_documents,
        skipped_episodes=skipped_episodes,
        skipped_chunks=skipped_chunks,
        skipped_assets=skipped_assets,
        skipped_asset_extraction_jobs=skipped_asset_extraction_jobs,
        skipped_extraction_artifacts=skipped_extraction_artifacts,
        skipped_captures=skipped_captures,
        skipped_anchors=skipped_anchors,
    ) or _endpoint_skipped(
        source_type=context_link.get("target_type"),
        source_id=context_link.get("target_id"),
        fact_ids=fact_ids,
        thread_ids=thread_ids,
        document_ids=document_ids,
        episode_ids=episode_ids,
        chunk_ids=chunk_ids,
        asset_ids=asset_ids,
        asset_extraction_job_ids=asset_extraction_job_ids,
        extraction_artifact_ids=extraction_artifact_ids,
        capture_ids=capture_ids,
        anchor_ids=anchor_ids,
        skipped_facts=skipped_facts,
        skipped_threads=skipped_threads,
        skipped_documents=skipped_documents,
        skipped_episodes=skipped_episodes,
        skipped_chunks=skipped_chunks,
        skipped_assets=skipped_assets,
        skipped_asset_extraction_jobs=skipped_asset_extraction_jobs,
        skipped_extraction_artifacts=skipped_extraction_artifacts,
        skipped_captures=skipped_captures,
        skipped_anchors=skipped_anchors,
    )


def _endpoint_skipped(
    *,
    source_type: object,
    source_id: object,
    fact_ids: set[str],
    thread_ids: set[str],
    document_ids: set[str],
    episode_ids: set[str],
    chunk_ids: set[str],
    asset_ids: set[str],
    asset_extraction_job_ids: set[str],
    extraction_artifact_ids: set[str],
    capture_ids: set[str],
    anchor_ids: set[str],
    skipped_facts: set[str],
    skipped_threads: set[str],
    skipped_documents: set[str],
    skipped_episodes: set[str],
    skipped_chunks: set[str],
    skipped_assets: set[str],
    skipped_asset_extraction_jobs: set[str],
    skipped_extraction_artifacts: set[str],
    skipped_captures: set[str],
    skipped_anchors: set[str],
) -> bool:
    if source_id is None:
        return True
    local_sets = {
        "fact": (fact_ids, skipped_facts),
        "thread": (thread_ids, skipped_threads),
        "document": (document_ids, skipped_documents),
        "episode": (episode_ids, skipped_episodes),
        "chunk": (chunk_ids, skipped_chunks),
        "asset": (asset_ids, skipped_assets),
        "asset_extraction": (asset_extraction_job_ids, skipped_asset_extraction_jobs),
        "extraction_artifact": (extraction_artifact_ids, skipped_extraction_artifacts),
        "capture": (capture_ids, skipped_captures),
        "anchor": (anchor_ids, skipped_anchors),
    }
    ids = local_sets.get(str(source_type))
    if ids is None:
        return True
    known_ids, skipped_ids = ids
    return str(source_id) not in known_ids or str(source_id) in skipped_ids


def _record_ids(items: list[dict[str, Any]]) -> set[str]:
    return {str(item["id"]) for item in items if item.get("id") is not None}


def _asset_blob_asset_ids(asset_blobs: list[dict[str, Any]]) -> set[str]:
    return {str(item["asset_id"]) for item in asset_blobs if item.get("asset_id") is not None}


def _extraction_artifact_blob_ids(artifact_blobs: list[dict[str, Any]]) -> set[str]:
    return {
        str(item["artifact_id"]) for item in artifact_blobs if item.get("artifact_id") is not None
    }


def _asset_requires_blob(asset: dict[str, Any]) -> bool:
    return str(asset.get("status", "stored")) == "stored"


def _extraction_job_asset_skipped(
    job: dict[str, Any],
    *,
    asset_ids: set[str],
    skipped_assets: set[str],
) -> bool:
    asset_id = job.get("asset_id")
    return asset_id is None or str(asset_id) not in asset_ids or str(asset_id) in skipped_assets


def _extraction_artifact_parent_skipped(
    artifact: dict[str, Any],
    *,
    asset_ids: set[str],
    skipped_assets: set[str],
    asset_extraction_job_ids: set[str],
    skipped_asset_extraction_jobs: set[str],
) -> bool:
    asset_id = artifact.get("asset_id")
    job_id = artifact.get("job_id")
    return (
        asset_id is None
        or str(asset_id) not in asset_ids
        or str(asset_id) in skipped_assets
        or job_id is None
        or str(job_id) not in asset_extraction_job_ids
        or str(job_id) in skipped_asset_extraction_jobs
    )


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


def _canonical_source_ref_dependency_skipped(
    ref: dict[str, Any],
    *,
    document_ids: set[str],
    skipped_documents: set[str],
    chunk_ids: set[str],
    skipped_chunks: set[str],
) -> bool:
    chunk_id = ref.get("chunk_id")
    if chunk_id is not None:
        normalized_chunk_id = str(chunk_id)
        return normalized_chunk_id in chunk_ids and normalized_chunk_id in skipped_chunks
    if str(ref.get("source_type") or "") != "document":
        return False
    source_id = str(ref.get("source_id") or "")
    return source_id in document_ids and source_id in skipped_documents


def _count_skipped(items: list[dict[str, Any]], skipped: set[str]) -> int:
    return sum(1 for item in items if str(item["id"]) in skipped)
