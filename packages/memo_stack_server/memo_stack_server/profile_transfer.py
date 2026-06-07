"""Profile export/import lite.

This is a local portability tool, not a sync protocol. It reads and writes
canonical Postgres rows only and never serializes derived Qdrant/Graphiti state.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from memo_stack_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryFactRelationRow,
    MemoryFactRow,
    MemoryOutboxRow,
    MemoryProfileRow,
    MemorySourceRefRow,
    MemorySpaceRow,
)
from memo_stack_core.profile_snapshot_preview import (
    build_profile_snapshot_import_preview,
    import_counts,
    skipped_snapshot_ids,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from memo_stack_server.profile_transfer_conflicts import profile_snapshot_conflicts
from memo_stack_server.profile_transfer_relations import (
    relation_from_json,
    relation_to_json,
    remap_relation,
)

SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = {1, 2}
SUPPORTED_MERGE_STRATEGIES = {
    "fail_on_conflict",
    "skip_existing",
    "create_new_profile",
    "supersede_matching_facts",
}

async def export_profile(
    *,
    engine: AsyncEngine,
    space_slug: str,
    profile_external_ref: str,
    out_path: Path,
    redacted: bool,
) -> dict[str, object]:
    result = await export_profile_payload(
        engine=engine,
        space_slug=space_slug,
        profile_external_ref=profile_external_ref,
        redacted=redacted,
    )
    if result["status"] != "ok":
        return {"status": result["status"], "out": str(out_path)}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result["snapshot"], ensure_ascii=False, indent=2), "utf-8")
    counts = result["counts"]
    return {
        "status": "ok", "out": str(out_path), "facts": counts["facts"],
        "documents": counts["documents"], "chunks": counts["chunks"],
        "relations": counts["relations"], "redacted": redacted,
    }


async def export_profile_payload(
    *,
    engine: AsyncEngine,
    space_slug: str,
    profile_external_ref: str,
    redacted: bool,
) -> dict[str, object]:
    async with AsyncSession(engine) as session:
        scope = await _load_scope(
            session,
            space_slug=space_slug,
            profile_external_ref=profile_external_ref,
        )
        if scope is None:
            return {"status": "not_found"}
        space, profile = scope
        facts = list(
            (
                await session.execute(
                    select(MemoryFactRow)
                    .where(
                        MemoryFactRow.space_id == space.id,
                        MemoryFactRow.profile_id == profile.id,
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
                        MemoryDocumentRow.profile_id == profile.id,
                    )
                    .order_by(MemoryDocumentRow.created_at, MemoryDocumentRow.id)
                )
            ).scalars()
        )
        chunks = list(
            (
                await session.execute(
                    select(MemoryChunkRow)
                    .where(
                        MemoryChunkRow.space_id == space.id,
                        MemoryChunkRow.profile_id == profile.id,
                    )
                    .order_by(MemoryChunkRow.created_at, MemoryChunkRow.id)
                )
            ).scalars()
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
                            MemoryFactRelationRow.profile_id == profile.id,
                            MemoryFactRelationRow.source_fact_id.in_(fact_ids),
                            MemoryFactRelationRow.target_fact_id.in_(fact_ids),
                        )
                        .order_by(MemoryFactRelationRow.created_at, MemoryFactRelationRow.id)
                    )
                ).scalars()
            )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "space": {"slug": space.slug, "id": space.id},
        "profile": {"external_ref": profile.external_ref, "id": profile.id},
        "facts": [_fact_to_json(fact, redacted=redacted) for fact in facts],
        "documents": [_document_to_json(document) for document in documents],
        "chunks": [_chunk_to_json(chunk, redacted=redacted) for chunk in chunks],
        "relations": [relation_to_json(relation) for relation in relations],
        "source_refs": [_source_ref_to_json(ref, redacted=redacted) for ref in source_refs],
        "exported_at": datetime.now(UTC).isoformat(),
        "redacted": redacted,
    }
    return {
        "status": "ok",
        "snapshot": payload,
        "counts": {
            "facts": len(facts),
            "documents": len(documents),
            "chunks": len(chunks),
            "relations": len(relations),
            "source_refs": len(source_refs),
        },
        "redacted": redacted,
    }


async def import_profile(
    *,
    engine: AsyncEngine,
    now: datetime,
    space_id: str,
    profile_id: str,
    in_path: Path,
    dry_run: bool,
    merge_strategy: str,
) -> dict[str, object]:
    payload = json.loads(in_path.read_text(encoding="utf-8"))
    return await import_profile_payload(
        engine=engine,
        now=now,
        space_id=space_id,
        profile_id=profile_id,
        payload=payload,
        dry_run=dry_run,
        merge_strategy=merge_strategy,
        source_name=in_path.name,
    )


async def import_profile_payload(
    *,
    engine: AsyncEngine,
    now: datetime,
    space_id: str,
    profile_id: str,
    payload: dict[str, Any],
    dry_run: bool,
    merge_strategy: str,
    source_name: str = "profile-snapshot",
) -> dict[str, object]:
    if int(payload.get("schema_version", 0)) not in SUPPORTED_SCHEMA_VERSIONS:
        return {"status": "failed", "reason": "unsupported_schema_version"}
    if merge_strategy not in SUPPORTED_MERGE_STRATEGIES:
        return {"status": "failed", "reason": "unsupported_merge_strategy"}

    facts = list(payload.get("facts", []))
    documents = list(payload.get("documents", []))
    chunks = list(payload.get("chunks", []))
    relations = list(payload.get("relations", []))
    source_refs = list(payload.get("source_refs", []))
    if not dry_run and _contains_redacted_memory(payload, facts=facts, chunks=chunks):
        return {"status": "refused", "reason": "redacted_profile_export_cannot_be_imported"}

    async with AsyncSession(engine) as session:
        target_profile_id = profile_id
        created_profile: dict[str, str] | None = None
        import_batch_id = _stable_id("import", source_name, now.isoformat())
        fact_id_map: dict[str, str] = {}
        document_id_map: dict[str, str] = {}
        chunk_id_map: dict[str, str] = {}
        relation_id_map: dict[str, str] = {}

        if merge_strategy == "create_new_profile" and not dry_run:
            profile = await _create_import_profile(
                session,
                space_id=space_id,
                base_profile_id=profile_id,
                now=now,
            )
            target_profile_id = profile.id
            created_profile = {"id": profile.id, "external_ref": profile.external_ref}
            fact_id_map = _build_id_map("fact", facts, target_profile_id, import_batch_id)
            document_id_map = _build_id_map("doc", documents, target_profile_id, import_batch_id)
            chunk_id_map = _build_id_map("chunk", chunks, target_profile_id, import_batch_id)
            relation_id_map = _build_id_map(
                "relation", relations, target_profile_id, import_batch_id
            )

        conflict_ids = (
            []
            if merge_strategy == "create_new_profile"
            else await profile_snapshot_conflicts(
                session,
                space_id=space_id,
                profile_id=target_profile_id,
                facts=facts,
                documents=documents,
                chunks=chunks,
                relations=relations,
            )
        )
        conflict_id_set = set(conflict_ids)
        preview = build_profile_snapshot_import_preview(
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
                facts=facts,
                documents=documents,
                chunks=chunks,
                relations=relations,
            )
            result: dict[str, object] = {
                "status": "ok",
                "dry_run": True,
                "would_import": import_counts(
                    facts=facts,
                    documents=documents,
                    chunks=chunks,
                    relations=relations,
                    source_refs=source_refs,
                    skipped=skipped,
                ),
                "conflict_count": len(conflict_ids),
                "merge_strategy": merge_strategy,
                "preview": preview,
            }
            if merge_strategy == "create_new_profile":
                result["would_create_profile"] = True
                preview["would_create_profile"] = True
            return {
                **result,
            }

        skipped = skipped_snapshot_ids(
            merge_strategy=merge_strategy,
            conflict_ids=conflict_id_set,
            facts=facts,
            documents=documents,
            chunks=chunks,
            relations=relations,
        )
        if merge_strategy == "supersede_matching_facts":
            superseded_fact_ids = _fact_conflict_ids(
                facts=facts,
                conflict_ids=conflict_id_set,
            )
            fact_id_map = {
                fact_id: _stable_id("fact", target_profile_id, fact_id, import_batch_id)
                for fact_id in superseded_fact_ids
            }
            await _supersede_facts(session, fact_ids=superseded_fact_ids, now=now)
            for fact_id in superseded_fact_ids:
                session.add(
                    _outbox(
                        event_type="graph.delete_fact",
                        aggregate_type="fact",
                        aggregate_id=fact_id,
                        now=now,
                        payload={"fact_id": fact_id},
                    )
                )

        imported_fact_versions: dict[str, int] = {}
        for fact in facts:
            if str(fact["id"]) in skipped["facts"]:
                continue
            mapped = _remap_fact(fact, fact_id_map=fact_id_map)
            session.add(
                _fact_from_json(
                    mapped,
                    space_id=space_id,
                    profile_id=target_profile_id,
                    now=now,
                )
            )
            imported_fact_versions[str(mapped["id"])] = int(mapped.get("version", 1))
        for document in documents:
            if str(document["id"]) in skipped["documents"]:
                continue
            mapped = _remap_document(document, document_id_map=document_id_map)
            session.add(
                _document_from_json(
                    mapped,
                    space_id=space_id,
                    profile_id=target_profile_id,
                    now=now,
                )
            )
        for chunk in chunks:
            if str(chunk["id"]) in skipped["chunks"]:
                continue
            mapped = _remap_chunk(
                chunk,
                document_id_map=document_id_map,
                chunk_id_map=chunk_id_map,
            )
            session.add(
                _chunk_from_json(
                    mapped,
                    space_id=space_id,
                    profile_id=target_profile_id,
                    now=now,
                )
            )
            session.add(
                _outbox(
                    event_type="vector.upsert_chunk",
                    aggregate_type="chunk",
                    aggregate_id=str(mapped["id"]),
                    now=now,
                    payload={"chunk_id": str(mapped["id"])},
                )
            )
        imported_refs_by_fact: set[str] = set()
        for ref in source_refs:
            if str(ref["fact_id"]) in skipped["facts"]:
                continue
            if ref.get("chunk_id") is not None and str(ref["chunk_id"]) in skipped["chunks"]:
                continue
            mapped = _remap_source_ref(
                ref,
                fact_id_map=fact_id_map,
                chunk_id_map=chunk_id_map,
                skipped_chunk_ids=skipped["chunks"],
            )
            fact_id = str(mapped["fact_id"])
            if fact_id not in imported_fact_versions:
                continue
            session.add(_source_ref_from_json(mapped))
            imported_refs_by_fact.add(fact_id)
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
                    profile_id=target_profile_id,
                    now=now,
                )
            )
        for fact_id, fact_version in imported_fact_versions.items():
            if fact_id in imported_refs_by_fact:
                continue
            session.add(
                MemorySourceRefRow(
                    fact_id=fact_id,
                    fact_version=fact_version,
                    source_type="import",
                    source_id=_bounded_optional_text(f"profile-import:{source_name}", 160)
                    or "profile-import",
                    chunk_id=None,
                    char_start=None,
                    char_end=None,
                    quote_preview=None,
                )
            )
        for fact in facts:
            if str(fact["id"]) in skipped["facts"] or str(fact.get("status", "active")) != "active":
                continue
            mapped_fact_id = fact_id_map.get(str(fact["id"]), str(fact["id"]))
            session.add(
                _outbox(
                    event_type="graph.upsert_fact",
                    aggregate_type="fact",
                    aggregate_id=mapped_fact_id,
                    aggregate_version=int(fact.get("version", 1)),
                    now=now,
                    payload={"fact_id": mapped_fact_id},
                )
            )
        await session.commit()

    result = {
        "status": "ok",
        "dry_run": False,
        "merge_strategy": merge_strategy,
        "imported": import_counts(
            facts=facts,
            documents=documents,
            chunks=chunks,
            relations=relations,
            source_refs=source_refs,
            skipped=skipped,
        ),
        "preview": preview,
    }
    if created_profile is not None:
        result["created_profile"] = created_profile
    return result


async def _load_scope(
    session: AsyncSession,
    *,
    space_slug: str,
    profile_external_ref: str,
) -> tuple[MemorySpaceRow, MemoryProfileRow] | None:
    space = (
        await session.execute(
            select(MemorySpaceRow).where(
                MemorySpaceRow.slug == space_slug,
                MemorySpaceRow.status == "active",
            )
        )
    ).scalar_one_or_none()
    if space is None:
        return None
    profile = (
        await session.execute(
            select(MemoryProfileRow).where(
                MemoryProfileRow.space_id == space.id,
                MemoryProfileRow.external_ref == profile_external_ref,
                MemoryProfileRow.status == "active",
            )
        )
    ).scalar_one_or_none()
    if profile is None:
        return None
    return space, profile


def _contains_redacted_memory(
    payload: dict[str, Any],
    *,
    facts: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> bool:
    if payload.get("redacted") is True:
        return True
    if any(fact.get("text") is None for fact in facts):
        return True
    return any(
        chunk.get("text") is None or chunk.get("normalized_text") is None for chunk in chunks
    )


def _fact_conflict_ids(
    *,
    facts: list[dict[str, Any]],
    conflict_ids: set[str],
) -> set[str]:
    return {str(item["id"]) for item in facts if str(item["id"]) in conflict_ids}


async def _supersede_facts(
    session: AsyncSession,
    *,
    fact_ids: set[str],
    now: datetime,
) -> None:
    if not fact_ids:
        return
    rows = (
        await session.execute(
            select(MemoryFactRow)
            .where(MemoryFactRow.id.in_(fact_ids), MemoryFactRow.status == "active")
            .with_for_update()
        )
    ).scalars()
    for row in rows:
        row.status = "superseded"
        row.version += 1
        row.updated_at = now


async def _create_import_profile(
    session: AsyncSession,
    *,
    space_id: str,
    base_profile_id: str,
    now: datetime,
) -> MemoryProfileRow:
    base_profile = await session.get(MemoryProfileRow, base_profile_id)
    if base_profile is None:
        msg = "Base profile not found"
        raise ValueError(msg)
    external_ref = await _next_import_profile_ref(
        session,
        space_id=space_id,
        base_external_ref=base_profile.external_ref,
        now=now,
    )
    row = MemoryProfileRow(
        id=_stable_id("profile", space_id, external_ref),
        space_id=space_id,
        external_ref=external_ref,
        name=f"{base_profile.name} import",
        status="active",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def _next_import_profile_ref(
    session: AsyncSession,
    *,
    space_id: str,
    base_external_ref: str,
    now: datetime,
) -> str:
    base = _bounded_external_ref(
        f"{base_external_ref}-import-{now.strftime('%Y%m%d%H%M%S')}",
        suffix="",
    )
    candidate = base
    suffix = 2
    while await _profile_ref_exists(session, space_id=space_id, external_ref=candidate):
        candidate = _bounded_external_ref(base, suffix=f"-{suffix}")
        suffix += 1
    return candidate


async def _profile_ref_exists(
    session: AsyncSession,
    *,
    space_id: str,
    external_ref: str,
) -> bool:
    return (
        await session.scalar(
            select(MemoryProfileRow.id).where(
                MemoryProfileRow.space_id == space_id,
                MemoryProfileRow.external_ref == external_ref,
            )
        )
        is not None
    )


def _bounded_external_ref(value: str, *, suffix: str) -> str:
    limit = 200 - len(suffix)
    return f"{value[:limit].rstrip('-')}{suffix}"


def _build_id_map(
    prefix: str,
    items: list[dict[str, Any]],
    profile_id: str,
    import_batch_id: str,
) -> dict[str, str]:
    return {
        str(item["id"]): _stable_id(prefix, profile_id, str(item["id"]), import_batch_id)
        for item in items
    }


def _remap_fact(item: dict[str, Any], *, fact_id_map: dict[str, str]) -> dict[str, Any]:
    fact_id = str(item["id"])
    if fact_id not in fact_id_map:
        return item
    return {**item, "id": fact_id_map[fact_id]}


def _remap_document(
    item: dict[str, Any],
    *,
    document_id_map: dict[str, str],
) -> dict[str, Any]:
    document_id = str(item["id"])
    if document_id not in document_id_map:
        return item
    return {**item, "id": document_id_map[document_id]}


def _remap_chunk(
    item: dict[str, Any],
    *,
    document_id_map: dict[str, str],
    chunk_id_map: dict[str, str],
) -> dict[str, Any]:
    chunk_id = str(item["id"])
    document_id = item.get("document_id")
    return {
        **item,
        "id": chunk_id_map.get(chunk_id, chunk_id),
        "document_id": (
            document_id_map.get(str(document_id), str(document_id))
            if document_id is not None
            else None
        ),
    }


def _remap_source_ref(
    item: dict[str, Any],
    *,
    fact_id_map: dict[str, str],
    chunk_id_map: dict[str, str],
    skipped_chunk_ids: set[str],
) -> dict[str, Any]:
    chunk_id = item.get("chunk_id")
    mapped_chunk_id = None
    if chunk_id is not None and str(chunk_id) not in skipped_chunk_ids:
        mapped_chunk_id = chunk_id_map.get(str(chunk_id), str(chunk_id))
    return {
        **item,
        "fact_id": fact_id_map.get(str(item["fact_id"]), str(item["fact_id"])),
        "chunk_id": mapped_chunk_id,
    }


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\u241f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _fact_to_json(row: MemoryFactRow, *, redacted: bool) -> dict[str, Any]:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "kind": row.kind,
        "text": None if redacted else row.text,
        "status": row.status,
        "confidence": row.confidence,
        "trust_level": row.trust_level,
        "classification": row.classification,
        "category": row.category,
        "tags": list(row.tags_json or []),
        "ttl_policy": row.ttl_policy,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "version": row.version,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _document_to_json(row: MemoryDocumentRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "title": row.title,
        "source_type": row.source_type,
        "source_external_id": row.source_external_id,
        "content_hash": row.content_hash,
        "classification": row.classification,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _chunk_to_json(row: MemoryChunkRow, *, redacted: bool) -> dict[str, Any]:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "document_id": row.document_id,
        "episode_id": row.episode_id,
        "source_type": row.source_type,
        "source_external_id": row.source_external_id,
        "source_hash": row.source_hash,
        "kind": row.kind,
        "text": None if redacted else row.text,
        "normalized_text": None if redacted else row.normalized_text,
        "status": row.status,
        "sequence": row.sequence,
        "char_start": row.char_start,
        "char_end": row.char_end,
        "token_estimate": row.token_estimate,
        "classification": row.classification,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "metadata_json": row.metadata_json,
    }


def _source_ref_to_json(row: MemorySourceRefRow, *, redacted: bool) -> dict[str, Any]:
    return {
        "fact_id": row.fact_id,
        "fact_version": row.fact_version,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "chunk_id": row.chunk_id,
        "char_start": row.char_start,
        "char_end": row.char_end,
        "quote_preview": None if redacted else _bounded_optional_text(row.quote_preview, 240),
    }


def _fact_from_json(
    item: dict[str, Any],
    *,
    space_id: str,
    profile_id: str,
    now: datetime,
) -> MemoryFactRow:
    return MemoryFactRow(
        id=str(item["id"]),
        space_id=space_id,
        profile_id=profile_id,
        thread_id=None,
        kind=str(item.get("kind", "note")),
        text=str(item.get("text") or "[redacted]"),
        status=str(item.get("status", "active")),
        confidence=str(item.get("confidence", "medium")),
        trust_level=str(item.get("trust_level", "medium")),
        classification=str(item.get("classification", "internal")),
        category=_bounded_optional_text(item.get("category"), 80),
        tags_json=_bounded_tags(item.get("tags")),
        ttl_policy=_bounded_optional_text(item.get("ttl_policy"), 80),
        expires_at=_parse_optional_dt(item.get("expires_at")),
        version=int(item.get("version", 1)),
        created_at=_parse_dt(item.get("created_at"), now),
        updated_at=_parse_dt(item.get("updated_at"), now),
    )


def _document_from_json(
    item: dict[str, Any],
    *,
    space_id: str,
    profile_id: str,
    now: datetime,
) -> MemoryDocumentRow:
    return MemoryDocumentRow(
        id=str(item["id"]),
        space_id=space_id,
        profile_id=profile_id,
        thread_id=None,
        title=str(item.get("title") or "Imported document"),
        source_type=str(item.get("source_type", "import")),
        source_external_id=str(item.get("source_external_id", item["id"])),
        content_hash=str(item.get("content_hash", item["id"])),
        classification=str(item.get("classification", "unknown")),
        status=str(item.get("status", "active")),
        created_at=_parse_dt(item.get("created_at"), now),
        updated_at=_parse_dt(item.get("updated_at"), now),
    )


def _chunk_from_json(
    item: dict[str, Any],
    *,
    space_id: str,
    profile_id: str,
    now: datetime,
) -> MemoryChunkRow:
    text = str(item.get("text") or "[redacted]")
    return MemoryChunkRow(
        id=str(item["id"]),
        space_id=space_id,
        profile_id=profile_id,
        thread_id=None,
        document_id=item.get("document_id"),
        episode_id=None,
        source_type=str(item.get("source_type", "import")),
        source_external_id=str(item.get("source_external_id", item["id"])),
        source_hash=str(item.get("source_hash", item["id"])),
        kind=str(item.get("kind", "document_section")),
        text=text,
        normalized_text=str(item.get("normalized_text") or text),
        status=str(item.get("status", "active")),
        sequence=int(item.get("sequence", 0)),
        char_start=int(item.get("char_start", 0)),
        char_end=int(item.get("char_end", len(text))),
        token_estimate=int(item.get("token_estimate", max(1, len(text) // 4))),
        classification=str(item.get("classification", "unknown")),
        created_at=_parse_dt(item.get("created_at"), now),
        updated_at=_parse_dt(item.get("updated_at"), now),
        metadata_json=dict(item.get("metadata_json") or {}),
    )


def _source_ref_from_json(item: dict[str, Any]) -> MemorySourceRefRow:
    return MemorySourceRefRow(
        fact_id=str(item["fact_id"]),
        fact_version=int(item.get("fact_version", 1)),
        source_type=str(item.get("source_type", "import")),
        source_id=str(item.get("source_id", "import")),
        chunk_id=item.get("chunk_id"),
        char_start=item.get("char_start"),
        char_end=item.get("char_end"),
        quote_preview=_bounded_optional_text(item.get("quote_preview"), 240),
    )


def _outbox(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    now: datetime,
    payload: dict[str, object],
    aggregate_version: int | None = None,
) -> MemoryOutboxRow:
    return MemoryOutboxRow(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        workload_class="projection",
        fairness_key=f"{aggregate_type}:{aggregate_id}",
        payload_json=payload,
        status="pending",
        attempt_count=0,
        next_attempt_at=now,
        last_safe_error=None,
        created_at=now,
        updated_at=now,
    )


def _parse_dt(value: object, fallback: datetime) -> datetime:
    if not value:
        return fallback
    return datetime.fromisoformat(str(value))


def _parse_optional_dt(value: object) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value))


def _bounded_optional_text(value: object, limit: int) -> str | None:
    if value is None:
        return None
    return str(value)[:limit]


def _bounded_tags(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        tag = str(item).strip().lower()[:48]
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= 10:
            break
    return tags
