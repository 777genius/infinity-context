"""MemoryScope export/import for canonical Postgres rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from infinity_context_adapters.postgres.models import (
    MemoryAnchorRow,
    MemoryAssetExtractionArtifactRow,
    MemoryAssetExtractionJobRow,
    MemoryAssetRow,
    MemoryCaptureRow,
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryEpisodeRow,
    MemoryFactRelationRow,
    MemoryFactRow,
    MemorySourceRefRow,
)
from infinity_context_core.memory_scope_snapshot_preview import (
    build_memory_scope_snapshot_import_preview,
    import_counts,
    skipped_snapshot_ids,
)
from infinity_context_core.ports.assets import BlobStoragePort
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from infinity_context_server import memory_scope_transfer_assets as _assets
from infinity_context_server import memory_scope_transfer_context as _context
from infinity_context_server import memory_scope_transfer_extractions as _extractions
from infinity_context_server import memory_scope_transfer_fact_coordination as _fact_coordination
from infinity_context_server import memory_scope_transfer_facts as _facts
from infinity_context_server import memory_scope_transfer_lifecycle as _lifecycle
from infinity_context_server import memory_scope_transfer_records as _records
from infinity_context_server import memory_scope_transfer_remap as _remap
from infinity_context_server import memory_scope_transfer_scope as _scope
from infinity_context_server import memory_scope_transfer_support as _support
from infinity_context_server.memory_scope_transfer_conflicts import memory_scope_snapshot_conflicts
from infinity_context_server.memory_scope_transfer_relations import (
    relation_from_json,
    relation_to_json,
    remap_relation,
)

SCHEMA_VERSION = 9
SUPPORTED_SCHEMA_VERSIONS = set(range(1, SCHEMA_VERSION + 1))
SUPPORTED_MERGE_STRATEGIES = _support.SUPPORTED_MERGE_STRATEGIES


async def export_memory_scope(
    *,
    engine: AsyncEngine,
    space_slug: str,
    memory_scope_external_ref: str,
    out_path: Path,
    redacted: bool,
    blob_storage: BlobStoragePort | None = None,
) -> dict[str, object]:
    result = await export_memory_scope_payload(
        engine=engine,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        redacted=redacted,
        blob_storage=blob_storage,
    )
    if result["status"] != "ok":
        return {"status": result["status"], "out": str(out_path)}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result["snapshot"], ensure_ascii=False, indent=2), "utf-8")
    counts = result["counts"]
    return {
        "status": "ok",
        "out": str(out_path),
        "threads": counts["threads"],
        "facts": counts["facts"],
        "documents": counts["documents"],
        "episodes": counts["episodes"],
        "chunks": counts["chunks"],
        "assets": counts["assets"],
        "asset_blobs": counts["asset_blobs"],
        "asset_extraction_jobs": counts["asset_extraction_jobs"],
        "extraction_artifacts": counts["extraction_artifacts"],
        "extraction_artifact_blobs": counts["extraction_artifact_blobs"],
        "captures": counts["captures"],
        "anchors": counts["anchors"],
        "context_links": counts["context_links"],
        "context_link_suggestions": counts["context_link_suggestions"],
        "relations": counts["relations"],
        "redacted": redacted,
    }


async def export_memory_scope_payload(
    *,
    engine: AsyncEngine,
    space_slug: str,
    memory_scope_external_ref: str,
    redacted: bool,
    blob_storage: BlobStoragePort | None = None,
) -> dict[str, object]:
    async with AsyncSession(engine) as session:
        scope = await _scope.load_scope(
            session,
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
        )
        if scope is None:
            return {"status": "not_found"}
        space, memory_scope = scope
        threads = await _scope.load_threads(
            session,
            space_id=space.id,
            memory_scope_id=memory_scope.id,
        )
        facts = list(
            (
                await session.execute(
                    select(MemoryFactRow)
                    .where(
                        MemoryFactRow.space_id == space.id,
                        MemoryFactRow.memory_scope_id == memory_scope.id,
                    )
                    .order_by(MemoryFactRow.created_at, MemoryFactRow.id)
                )
            ).scalars()
        )
        documents = list(
            (
                await session.execute(
                    select(MemoryDocumentRow)
                    .where(
                        MemoryDocumentRow.space_id == space.id,
                        MemoryDocumentRow.memory_scope_id == memory_scope.id,
                    )
                    .order_by(MemoryDocumentRow.created_at, MemoryDocumentRow.id)
                )
            ).scalars()
        )
        episodes = list(
            (
                await session.execute(
                    select(MemoryEpisodeRow)
                    .where(
                        MemoryEpisodeRow.space_id == space.id,
                        MemoryEpisodeRow.memory_scope_id == memory_scope.id,
                    )
                    .order_by(MemoryEpisodeRow.occurred_at, MemoryEpisodeRow.id)
                )
            ).scalars()
        )
        chunks = list(
            (
                await session.execute(
                    select(MemoryChunkRow)
                    .where(
                        MemoryChunkRow.space_id == space.id,
                        MemoryChunkRow.memory_scope_id == memory_scope.id,
                    )
                    .order_by(MemoryChunkRow.created_at, MemoryChunkRow.id)
                )
            ).scalars()
        )
        assets = list(
            (
                await session.execute(
                    select(MemoryAssetRow)
                    .where(
                        MemoryAssetRow.space_id == space.id,
                        MemoryAssetRow.memory_scope_id == memory_scope.id,
                    )
                    .order_by(MemoryAssetRow.created_at, MemoryAssetRow.id)
                )
            ).scalars()
        )
        asset_extraction_jobs = list(
            (
                await session.execute(
                    select(MemoryAssetExtractionJobRow)
                    .where(
                        MemoryAssetExtractionJobRow.space_id == space.id,
                        MemoryAssetExtractionJobRow.memory_scope_id == memory_scope.id,
                    )
                    .order_by(
                        MemoryAssetExtractionJobRow.created_at,
                        MemoryAssetExtractionJobRow.id,
                    )
                )
            ).scalars()
        )
        extraction_artifacts = []
        asset_extraction_job_ids = [job.id for job in asset_extraction_jobs]
        if asset_extraction_job_ids:
            extraction_artifacts = list(
                (
                    await session.execute(
                        select(MemoryAssetExtractionArtifactRow)
                        .where(
                            MemoryAssetExtractionArtifactRow.job_id.in_(asset_extraction_job_ids)
                        )
                        .order_by(
                            MemoryAssetExtractionArtifactRow.created_at,
                            MemoryAssetExtractionArtifactRow.id,
                        )
                    )
                ).scalars()
            )
        captures = list(
            (
                await session.execute(
                    select(MemoryCaptureRow)
                    .where(
                        MemoryCaptureRow.space_id == space.id,
                        MemoryCaptureRow.memory_scope_id == memory_scope.id,
                    )
                    .order_by(MemoryCaptureRow.created_at, MemoryCaptureRow.id)
                )
            ).scalars()
        )
        anchors = list(
            (
                await session.execute(
                    select(MemoryAnchorRow)
                    .where(
                        MemoryAnchorRow.space_id == space.id,
                        MemoryAnchorRow.memory_scope_id == memory_scope.id,
                    )
                    .order_by(MemoryAnchorRow.created_at, MemoryAnchorRow.id)
                )
            ).scalars()
        )
        context_links, context_link_suggestions = await _context.load_context_records(
            session,
            space_id=space.id,
            memory_scope_id=memory_scope.id,
        )
        fact_ids = [fact.id for fact in facts]
        source_refs = []
        relations = []
        if fact_ids:
            source_refs = list(
                (
                    await session.execute(
                        select(MemorySourceRefRow)
                        .where(MemorySourceRefRow.fact_id.in_(fact_ids))
                        .order_by(MemorySourceRefRow.fact_id, MemorySourceRefRow.id)
                    )
                ).scalars()
            )
            relations = list(
                (
                    await session.execute(
                        select(MemoryFactRelationRow)
                        .where(
                            MemoryFactRelationRow.space_id == space.id,
                            MemoryFactRelationRow.memory_scope_id == memory_scope.id,
                            MemoryFactRelationRow.source_fact_id.in_(fact_ids),
                            MemoryFactRelationRow.target_fact_id.in_(fact_ids),
                        )
                        .order_by(MemoryFactRelationRow.created_at, MemoryFactRelationRow.id)
                    )
                ).scalars()
            )

    try:
        asset_blobs = await _assets.asset_blobs_to_json(
            assets=assets,
            blob_storage=blob_storage,
            redacted=redacted,
        )
    except _assets.MemoryScopeAssetBlobError as exc:
        return {"status": "failed", "reason": exc.reason, "asset_id": exc.asset_id}
    try:
        extraction_artifact_blobs = await _extractions.extraction_artifact_blobs_to_json(
            artifacts=extraction_artifacts,
            blob_storage=blob_storage,
            redacted=redacted,
        )
    except _extractions.MemoryScopeExtractionArtifactBlobError as exc:
        return {"status": "failed", "reason": exc.reason, "artifact_id": exc.artifact_id}

    payload = {
        "schema_version": SCHEMA_VERSION,
        "space": {"slug": space.slug, "id": space.id},
        "memory_scope": {"external_ref": memory_scope.external_ref, "id": memory_scope.id},
        "threads": [_scope.thread_to_json(thread) for thread in threads],
        "facts": [_records.fact_to_json(fact, redacted=redacted) for fact in facts],
        "documents": [_records.document_to_json(document) for document in documents],
        "episodes": [_records.episode_to_json(episode, redacted=redacted) for episode in episodes],
        "chunks": [_records.chunk_to_json(chunk, redacted=redacted) for chunk in chunks],
        "assets": [_assets.asset_to_json(asset) for asset in assets],
        "asset_blobs": asset_blobs,
        "asset_extraction_jobs": [
            _extractions.extraction_job_to_json(job) for job in asset_extraction_jobs
        ],
        "extraction_artifacts": [
            _extractions.extraction_artifact_to_json(artifact) for artifact in extraction_artifacts
        ],
        "extraction_artifact_blobs": extraction_artifact_blobs,
        "captures": [_records.capture_to_json(capture, redacted=redacted) for capture in captures],
        "anchors": [_records.anchor_to_json(anchor) for anchor in anchors],
        "context_links": [_context.context_link_to_json(link) for link in context_links],
        "context_link_suggestions": [
            _context.context_link_suggestion_to_json(suggestion)
            for suggestion in context_link_suggestions
        ],
        "relations": [relation_to_json(relation) for relation in relations],
        "source_refs": [_records.source_ref_to_json(ref, redacted=redacted) for ref in source_refs],
        "exported_at": datetime.now(UTC).isoformat(),
        "redacted": redacted,
    }
    return {
        "status": "ok",
        "snapshot": payload,
        "counts": {
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
        },
        "redacted": redacted,
    }


async def import_memory_scope(
    *,
    engine: AsyncEngine,
    now: datetime,
    space_id: str,
    memory_scope_id: str,
    in_path: Path,
    dry_run: bool,
    merge_strategy: str,
    blob_storage: BlobStoragePort | None = None,
) -> dict[str, object]:
    payload = json.loads(in_path.read_text(encoding="utf-8"))
    return await import_memory_scope_payload(
        engine=engine,
        now=now,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        payload=payload,
        dry_run=dry_run,
        merge_strategy=merge_strategy,
        source_name=in_path.name,
        blob_storage=blob_storage,
    )


async def import_memory_scope_payload(
    *,
    engine: AsyncEngine,
    now: datetime,
    space_id: str,
    memory_scope_id: str,
    payload: dict[str, Any],
    dry_run: bool,
    merge_strategy: str,
    source_name: str = "memory_scope-snapshot",
    blob_storage: BlobStoragePort | None = None,
) -> dict[str, object]:
    if int(payload.get("schema_version", 0)) not in SUPPORTED_SCHEMA_VERSIONS:
        return {"status": "failed", "reason": "unsupported_schema_version"}
    if merge_strategy not in _support.SUPPORTED_MERGE_STRATEGIES:
        return {"status": "failed", "reason": "unsupported_merge_strategy"}

    threads = list(payload.get("threads", []))
    facts = list(payload.get("facts", []))
    documents = list(payload.get("documents", []))
    episodes = list(payload.get("episodes", []))
    chunks = list(payload.get("chunks", []))
    assets = list(payload.get("assets", []))
    asset_blobs = list(payload.get("asset_blobs", []))
    asset_blob_map = _assets.asset_blob_by_id(asset_blobs)
    asset_extraction_jobs = list(payload.get("asset_extraction_jobs", []))
    extraction_artifacts = list(payload.get("extraction_artifacts", []))
    extraction_artifact_blobs = list(payload.get("extraction_artifact_blobs", []))
    extraction_artifact_blob_map = _extractions.extraction_artifact_blob_by_id(
        extraction_artifact_blobs
    )
    captures = list(payload.get("captures", []))
    anchors = list(payload.get("anchors", []))
    context_links = list(payload.get("context_links", []))
    context_link_suggestions = list(payload.get("context_link_suggestions", []))
    relations = list(payload.get("relations", []))
    source_refs = list(payload.get("source_refs", []))
    declared_thread_ids = _lifecycle.referenced_thread_ids(
        facts=facts,
        documents=documents,
        episodes=episodes,
        chunks=chunks,
        assets=assets,
        asset_extraction_jobs=asset_extraction_jobs,
        captures=captures,
    )
    if not dry_run and _records.contains_redacted_memory(
        payload,
        facts=facts,
        episodes=episodes,
        chunks=chunks,
        captures=captures,
    ):
        return {"status": "refused", "reason": "redacted_memory_scope_export_cannot_be_imported"}
    if (
        not dry_run
        and payload.get("redacted") is True
        and (assets or asset_extraction_jobs or extraction_artifacts)
    ):
        return {"status": "refused", "reason": "redacted_memory_scope_export_cannot_be_imported"}

    async with AsyncSession(engine) as session:
        target_memory_scope_id = memory_scope_id
        created_memory_scope: dict[str, str] | None = None
        import_batch_id = _support.stable_id("import", source_name, now.isoformat())
        fact_id_map: dict[str, str] = {}
        document_id_map: dict[str, str] = {}
        episode_id_map: dict[str, str] = {}
        chunk_id_map: dict[str, str] = {}
        asset_id_map: dict[str, str] = {}
        extraction_job_id_map: dict[str, str] = {}
        extraction_artifact_id_map: dict[str, str] = {}
        capture_id_map: dict[str, str] = {}
        anchor_id_map: dict[str, str] = {}
        context_link_id_map: dict[str, str] = {}
        context_link_suggestion_id_map: dict[str, str] = {}
        relation_id_map: dict[str, str] = {}
        thread_id_map: dict[str, str] = {}
        if threads and not dry_run:
            thread_id_map = {str(thread["id"]): str(thread["id"]) for thread in threads}

        if merge_strategy == "create_new_memory_scope" and not dry_run:
            memory_scope = await _scope.create_import_memory_scope(
                session,
                space_id=space_id,
                base_memory_scope_id=memory_scope_id,
                now=now,
            )
            target_memory_scope_id = memory_scope.id
            created_memory_scope = {
                "id": memory_scope.id,
                "external_ref": memory_scope.external_ref,
            }
            fact_id_map = _support.build_id_map(
                "fact",
                facts,
                target_memory_scope_id,
                import_batch_id,
            )
            document_id_map = _support.build_id_map(
                "doc", documents, target_memory_scope_id, import_batch_id
            )
            episode_id_map = _support.build_id_map(
                "episode", episodes, target_memory_scope_id, import_batch_id
            )
            chunk_id_map = _support.build_id_map(
                "chunk",
                chunks,
                target_memory_scope_id,
                import_batch_id,
            )
            asset_id_map = _support.build_id_map(
                "asset",
                assets,
                target_memory_scope_id,
                import_batch_id,
            )
            extraction_job_id_map = _support.build_id_map(
                "extract",
                asset_extraction_jobs,
                target_memory_scope_id,
                import_batch_id,
            )
            extraction_artifact_id_map = _support.build_id_map(
                "artifact",
                extraction_artifacts,
                target_memory_scope_id,
                import_batch_id,
            )
            capture_id_map = _support.build_id_map(
                "capture", captures, target_memory_scope_id, import_batch_id
            )
            anchor_id_map = _support.build_id_map(
                "anchor", anchors, target_memory_scope_id, import_batch_id
            )
            context_link_id_map = _support.build_id_map(
                "context_link", context_links, target_memory_scope_id, import_batch_id
            )
            context_link_suggestion_id_map = _support.build_id_map(
                "context_link_suggestion",
                context_link_suggestions,
                target_memory_scope_id,
                import_batch_id,
            )
            relation_id_map = _support.build_id_map(
                "relation", relations, target_memory_scope_id, import_batch_id
            )
            thread_id_map = _support.build_thread_id_map(
                threads=threads,
                episodes=episodes,
                memory_scope_id=target_memory_scope_id,
                import_batch_id=import_batch_id,
                referenced_thread_ids=declared_thread_ids,
            )
        if episodes and not dry_run and not thread_id_map:
            thread_id_map = _support.build_thread_id_map(
                episodes=episodes,
                memory_scope_id=target_memory_scope_id,
                import_batch_id=import_batch_id,
            )

        conflict_ids = (
            []
            if merge_strategy == "create_new_memory_scope"
            else await memory_scope_snapshot_conflicts(
                session,
                space_id=space_id,
                memory_scope_id=target_memory_scope_id,
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
        )
        conflict_id_set = set(conflict_ids)
        preview = build_memory_scope_snapshot_import_preview(
            payload=payload,
            merge_strategy=merge_strategy,
            conflict_ids=conflict_id_set,
        )
        if conflict_ids and merge_strategy == "fail_on_conflict":
            return {
                "status": "conflict",
                "conflict_count": len(conflict_ids),
                "conflict_ids": conflict_ids[:20],
                "dry_run": dry_run,
                "preview": preview,
            }
        if dry_run:
            skipped = skipped_snapshot_ids(
                merge_strategy=merge_strategy,
                conflict_ids=conflict_id_set,
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
            result: dict[str, object] = {
                "status": "ok",
                "dry_run": True,
                "would_import": import_counts(
                    facts=facts,
                    threads=threads,
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
                "conflict_count": len(conflict_ids),
                "merge_strategy": merge_strategy,
                "preview": preview,
            }
            if merge_strategy == "create_new_memory_scope":
                result["would_create_memory_scope"] = True
                preview["would_create_memory_scope"] = True
            return result

        skipped = skipped_snapshot_ids(
            merge_strategy=merge_strategy,
            conflict_ids=conflict_id_set,
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
        superseded_fact_ids: set[str] = set()
        if merge_strategy == "supersede_matching_facts":
            superseded_fact_ids = _facts.fact_conflict_ids(
                facts=facts,
                conflict_ids=conflict_id_set,
            )
            fact_id_map = {
                fact_id: _support.stable_id(
                    "fact",
                    target_memory_scope_id,
                    fact_id,
                    import_batch_id,
                )
                for fact_id in superseded_fact_ids
            }

        (
            target_thread_ids,
            creatable_thread_ids,
            referenced_thread_id_map,
        ) = _lifecycle.plan_snapshot_thread_fences(
            threads=threads,
            facts=facts,
            documents=documents,
            episodes=episodes,
            chunks=chunks,
            assets=assets,
            asset_extraction_jobs=asset_extraction_jobs,
            captures=captures,
            skipped=skipped,
            thread_id_map=thread_id_map,
            create_new_memory_scope=merge_strategy == "create_new_memory_scope",
        )
        await _lifecycle.fence_snapshot_import_threads(
            session,
            space_id=space_id,
            memory_scope_id=target_memory_scope_id,
            thread_ids=target_thread_ids,
            creatable_thread_ids=creatable_thread_ids,
        )

        imported_fact_versions: dict[str, int] = {}
        mapped_facts: list[dict[str, Any]] = []
        for fact in facts:
            if str(fact["id"]) in skipped["facts"]:
                continue
            mapped = _remap.remap_fact(fact, fact_id_map=fact_id_map, thread_id_map=thread_id_map)
            mapped_facts.append(mapped)
            imported_fact_versions[str(mapped["id"])] = int(mapped.get("version", 1))
        for document in documents:
            if str(document["id"]) in skipped["documents"]:
                continue
            mapped = _remap.remap_document(
                document,
                document_id_map=document_id_map,
                extraction_job_id_map=extraction_job_id_map,
                thread_id_map=thread_id_map,
            )
            session.add(
                _records.document_from_json(
                    mapped,
                    space_id=space_id,
                    memory_scope_id=target_memory_scope_id,
                    now=now,
                )
            )
        await _scope.ensure_import_threads(
            session,
            threads=threads,
            skipped_thread_ids=skipped["threads"],
            episodes=episodes,
            skipped_episode_ids=skipped["episodes"],
            thread_id_map=thread_id_map,
            space_id=space_id,
            memory_scope_id=target_memory_scope_id,
            now=now,
            referenced_thread_id_map=referenced_thread_id_map,
        )
        # Document-backed chunks are guarded by a database trigger that resolves
        # their canonical parent at INSERT time. Flush threads and documents
        # first instead of relying on SQLAlchemy table ordering for unrelated
        # mapped rows.
        await session.flush()
        for episode in episodes:
            if str(episode["id"]) in skipped["episodes"]:
                continue
            mapped = _remap.remap_episode(
                episode,
                episode_id_map=episode_id_map,
                thread_id_map=thread_id_map,
            )
            session.add(
                _records.episode_from_json(
                    mapped,
                    space_id=space_id,
                    memory_scope_id=target_memory_scope_id,
                    now=now,
                )
            )
        for chunk in chunks:
            if str(chunk["id"]) in skipped["chunks"]:
                continue
            mapped = _remap.remap_chunk(
                chunk,
                document_id_map=document_id_map,
                episode_id_map=episode_id_map,
                chunk_id_map=chunk_id_map,
                thread_id_map=thread_id_map,
                asset_id_map=asset_id_map,
                extraction_job_id_map=extraction_job_id_map,
            )
            session.add(
                _records.chunk_from_json(
                    mapped,
                    space_id=space_id,
                    memory_scope_id=target_memory_scope_id,
                    now=now,
                )
            )
            session.add(
                _support.outbox(
                    event_type="vector.upsert_chunk",
                    aggregate_type="chunk",
                    aggregate_id=str(mapped["id"]),
                    now=now,
                    payload={"chunk_id": str(mapped["id"])},
                )
            )
        # Canonical evidence must exist before it can be validated and locked, while
        # fact rows must not be staged until the complete batch is coordinated.
        await session.flush()
        mapped_source_ref_rows = await _fact_coordination.coordinate_and_stage_imported_facts(
            session,
            space_id=space_id,
            memory_scope_id=target_memory_scope_id,
            now=now,
            mapped_facts=mapped_facts,
            imported_fact_versions=imported_fact_versions,
            source_refs=source_refs,
            skipped_fact_ids=skipped["facts"],
            skipped_chunk_ids=skipped["chunks"],
            fact_id_map=fact_id_map,
            chunk_id_map=chunk_id_map,
            document_id_map=document_id_map,
            extraction_job_id_map=extraction_job_id_map,
            superseded_fact_ids=superseded_fact_ids,
        )
        for asset in assets:
            if str(asset["id"]) in skipped["assets"]:
                continue
            mapped = _assets.remap_asset(
                asset,
                asset_id_map=asset_id_map,
                thread_id_map=thread_id_map,
                space_id=space_id,
                memory_scope_id=target_memory_scope_id,
            )
            if str(mapped.get("status", "stored")) == "stored":
                if blob_storage is None:
                    return {"status": "failed", "reason": "asset_blob_storage_unavailable"}
                blob = asset_blob_map.get(str(asset["id"]))
                if blob is None:
                    return {
                        "status": "failed",
                        "reason": "asset_blob_missing",
                        "asset_id": str(asset["id"]),
                    }
                try:
                    await _assets.write_imported_asset_blob(
                        asset=mapped,
                        blob=blob,
                        blob_storage=blob_storage,
                    )
                except _assets.MemoryScopeAssetBlobError as exc:
                    return {"status": "failed", "reason": exc.reason, "asset_id": exc.asset_id}
            session.add(
                _assets.asset_from_json(
                    mapped,
                    space_id=space_id,
                    memory_scope_id=target_memory_scope_id,
                    now=now,
                )
            )
        extraction_import_error = await _extractions.import_extraction_rows(
            session,
            jobs=asset_extraction_jobs,
            artifacts=extraction_artifacts,
            artifact_blob_map=extraction_artifact_blob_map,
            skipped=skipped,
            extraction_job_id_map=extraction_job_id_map,
            extraction_artifact_id_map=extraction_artifact_id_map,
            asset_id_map=asset_id_map,
            document_id_map=document_id_map,
            thread_id_map=thread_id_map,
            space_id=space_id,
            memory_scope_id=target_memory_scope_id,
            now=now,
            blob_storage=blob_storage,
        )
        if extraction_import_error is not None:
            return extraction_import_error
        for capture in captures:
            if str(capture["id"]) in skipped["captures"]:
                continue
            mapped = _remap.remap_capture(
                capture,
                fact_id_map=fact_id_map,
                document_id_map=document_id_map,
                episode_id_map=episode_id_map,
                chunk_id_map=chunk_id_map,
                capture_id_map=capture_id_map,
                asset_id_map=asset_id_map,
                anchor_id_map=anchor_id_map,
                extraction_job_id_map=extraction_job_id_map,
                extraction_artifact_id_map=extraction_artifact_id_map,
                thread_id_map=thread_id_map,
            )
            session.add(
                _records.capture_from_json(
                    mapped,
                    space_id=space_id,
                    memory_scope_id=target_memory_scope_id,
                    now=now,
                )
            )
        for anchor in anchors:
            if str(anchor["id"]) in skipped["anchors"]:
                continue
            mapped = _remap.remap_anchor(anchor, anchor_id_map=anchor_id_map)
            session.add(
                _records.anchor_from_json(
                    mapped,
                    space_id=space_id,
                    memory_scope_id=target_memory_scope_id,
                    now=now,
                )
            )
        _context.import_context_records(
            session,
            context_links=context_links,
            context_link_suggestions=context_link_suggestions,
            skipped=skipped,
            context_link_id_map=context_link_id_map,
            context_link_suggestion_id_map=context_link_suggestion_id_map,
            fact_id_map=fact_id_map,
            document_id_map=document_id_map,
            episode_id_map=episode_id_map,
            chunk_id_map=chunk_id_map,
            capture_id_map=capture_id_map,
            asset_id_map=asset_id_map,
            anchor_id_map=anchor_id_map,
            thread_id_map=thread_id_map,
            extraction_job_id_map=extraction_job_id_map,
            extraction_artifact_id_map=extraction_artifact_id_map,
            space_id=space_id,
            memory_scope_id=target_memory_scope_id,
            now=now,
        )
        imported_refs_by_fact = {row.fact_id for row in mapped_source_ref_rows}
        declared_refs_by_fact = {
            fact_id_map.get(str(ref["fact_id"]), str(ref["fact_id"]))
            for ref in source_refs
            if str(ref.get("fact_id")) not in skipped["facts"]
        }
        session.add_all(mapped_source_ref_rows)
        for relation in relations:
            if str(relation["id"]) in skipped["relations"]:
                continue
            if str(relation["source_fact_id"]) in skipped["facts"]:
                continue
            if str(relation["target_fact_id"]) in skipped["facts"]:
                continue
            mapped = remap_relation(
                relation,
                fact_id_map=fact_id_map,
                relation_id_map=relation_id_map,
            )
            session.add(
                relation_from_json(
                    mapped,
                    space_id=space_id,
                    memory_scope_id=target_memory_scope_id,
                    now=now,
                )
            )
        for fact_id, fact_version in imported_fact_versions.items():
            if fact_id in imported_refs_by_fact or fact_id in declared_refs_by_fact:
                continue
            session.add(
                MemorySourceRefRow(
                    fact_id=fact_id,
                    fact_version=fact_version,
                    source_type="import",
                    source_id=_records.bounded_optional_text(
                        f"memory_scope-import:{source_name}",
                        160,
                    )
                    or "memory_scope-import",
                    chunk_id=None,
                    char_start=None,
                    char_end=None,
                    quote_preview=None,
                )
            )
        _facts.enqueue_fact_graph_upserts(
            session,
            facts=facts,
            skipped_fact_ids=skipped["facts"],
            fact_id_map=fact_id_map,
            now=now,
        )
        await session.commit()

    result = {
        "status": "ok",
        "dry_run": False,
        "merge_strategy": merge_strategy,
        "imported": import_counts(
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
        "preview": preview,
    }
    if created_memory_scope is not None:
        result["created_memory_scope"] = created_memory_scope
    return result
