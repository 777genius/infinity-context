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
    MemoryFactRow,
    MemoryOutboxRow,
    MemoryProfileRow,
    MemorySourceRefRow,
    MemorySpaceRow,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

SCHEMA_VERSION = 1
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
    async with AsyncSession(engine) as session:
        scope = await _load_scope(
            session,
            space_slug=space_slug,
            profile_external_ref=profile_external_ref,
        )
        if scope is None:
            return {"status": "not_found", "out": str(out_path)}
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

    payload = {
        "schema_version": SCHEMA_VERSION,
        "space": {"slug": space.slug, "id": space.id},
        "profile": {"external_ref": profile.external_ref, "id": profile.id},
        "facts": [_fact_to_json(fact, redacted=redacted) for fact in facts],
        "documents": [_document_to_json(document) for document in documents],
        "chunks": [_chunk_to_json(chunk, redacted=redacted) for chunk in chunks],
        "source_refs": [_source_ref_to_json(ref, redacted=redacted) for ref in source_refs],
        "exported_at": datetime.now(UTC).isoformat(),
        "redacted": redacted,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "ok",
        "out": str(out_path),
        "facts": len(facts),
        "documents": len(documents),
        "chunks": len(chunks),
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
    if int(payload.get("schema_version", 0)) != SCHEMA_VERSION:
        return {"status": "failed", "reason": "unsupported_schema_version"}
    if merge_strategy not in SUPPORTED_MERGE_STRATEGIES:
        return {"status": "failed", "reason": "unsupported_merge_strategy"}

    facts = list(payload.get("facts", []))
    documents = list(payload.get("documents", []))
    chunks = list(payload.get("chunks", []))
    source_refs = list(payload.get("source_refs", []))
    if not dry_run and _contains_redacted_memory(payload, facts=facts, chunks=chunks):
        return {"status": "refused", "reason": "redacted_profile_export_cannot_be_imported"}

    async with AsyncSession(engine) as session:
        target_profile_id = profile_id
        created_profile: dict[str, str] | None = None
        import_batch_id = _stable_id("import", str(in_path), now.isoformat())
        fact_id_map: dict[str, str] = {}
        document_id_map: dict[str, str] = {}
        chunk_id_map: dict[str, str] = {}

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

        conflict_ids = (
            []
            if merge_strategy == "create_new_profile"
            else await _conflicts(
                session,
                space_id=space_id,
                profile_id=target_profile_id,
                facts=facts,
                documents=documents,
                chunks=chunks,
            )
        )
        if conflict_ids and merge_strategy == "fail_on_conflict":
            return {
                "status": "conflict",
                "conflict_count": len(conflict_ids),
                "conflict_ids": conflict_ids[:20],
                "dry_run": dry_run,
            }
        if dry_run:
            skipped = _skipped_ids(
                merge_strategy=merge_strategy,
                conflict_ids=set(conflict_ids),
                facts=facts,
                documents=documents,
                chunks=chunks,
            )
            result: dict[str, object] = {
                "status": "ok",
                "dry_run": True,
                "would_import": _import_counts(
                    facts=facts,
                    documents=documents,
                    chunks=chunks,
                    source_refs=source_refs,
                    skipped=skipped,
                ),
                "conflict_count": len(conflict_ids),
                "merge_strategy": merge_strategy,
            }
            if merge_strategy == "create_new_profile":
                result["would_create_profile"] = True
            return {
                **result,
            }

        skipped = _skipped_ids(
            merge_strategy=merge_strategy,
            conflict_ids=set(conflict_ids),
            facts=facts,
            documents=documents,
            chunks=chunks,
        )
        if merge_strategy == "supersede_matching_facts":
            superseded_fact_ids = _fact_conflict_ids(facts=facts, conflict_ids=set(conflict_ids))
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
        for fact_id, fact_version in imported_fact_versions.items():
            if fact_id in imported_refs_by_fact:
                continue
            session.add(
                MemorySourceRefRow(
                    fact_id=fact_id,
                    fact_version=fact_version,
                    source_type="import",
                    source_id=_bounded_optional_text(f"profile-import:{in_path.name}", 160)
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
        "imported": _import_counts(
            facts=facts,
            documents=documents,
            chunks=chunks,
            source_refs=source_refs,
            skipped=skipped,
        ),
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


async def _conflicts(
    session: AsyncSession,
    *,
    space_id: str,
    profile_id: str,
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[str]:
    conflicts: list[str] = []
    fact_ids = [str(item["id"]) for item in facts]
    document_ids = [str(item["id"]) for item in documents]
    chunk_ids = [str(item["id"]) for item in chunks]
    for model, ids in (
        (MemoryFactRow, fact_ids),
        (MemoryDocumentRow, document_ids),
        (MemoryChunkRow, chunk_ids),
    ):
        if not ids:
            continue
        result = await session.execute(select(model.id).where(model.id.in_(ids)))
        conflicts.extend(str(row_id) for row_id in result.scalars())
    conflicts.extend(
        await _document_hash_conflicts(
            session,
            space_id=space_id,
            profile_id=profile_id,
            documents=documents,
        )
    )
    conflicts.extend(
        await _chunk_hash_conflicts(
            session,
            space_id=space_id,
            profile_id=profile_id,
            chunks=chunks,
        )
    )
    return sorted(set(conflicts))


async def _document_hash_conflicts(
    session: AsyncSession,
    *,
    space_id: str,
    profile_id: str,
    documents: list[dict[str, Any]],
) -> list[str]:
    by_hash = {
        str(item.get("content_hash")): str(item["id"])
        for item in documents
        if item.get("content_hash")
    }
    if not by_hash:
        return []
    rows = (
        await session.execute(
            select(MemoryDocumentRow.id, MemoryDocumentRow.content_hash).where(
                MemoryDocumentRow.space_id == space_id,
                MemoryDocumentRow.profile_id == profile_id,
                MemoryDocumentRow.status != "deleted",
                MemoryDocumentRow.content_hash.in_(by_hash),
            )
        )
    ).all()
    return [
        by_hash[str(content_hash)]
        for row_id, content_hash in rows
        if str(row_id) != by_hash[str(content_hash)]
    ]


async def _chunk_hash_conflicts(
    session: AsyncSession,
    *,
    space_id: str,
    profile_id: str,
    chunks: list[dict[str, Any]],
) -> list[str]:
    by_hash = {
        str(item.get("source_hash")): str(item["id"]) for item in chunks if item.get("source_hash")
    }
    if not by_hash:
        return []
    rows = (
        await session.execute(
            select(MemoryChunkRow.id, MemoryChunkRow.source_hash).where(
                MemoryChunkRow.space_id == space_id,
                MemoryChunkRow.profile_id == profile_id,
                MemoryChunkRow.status != "deleted",
                MemoryChunkRow.source_hash.in_(by_hash),
            )
        )
    ).all()
    return [
        by_hash[str(source_hash)]
        for row_id, source_hash in rows
        if str(row_id) != by_hash[str(source_hash)]
    ]


def _skipped_ids(
    *,
    merge_strategy: str,
    conflict_ids: set[str],
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> dict[str, set[str]]:
    fact_ids = {str(item["id"]) for item in facts}
    document_ids = {str(item["id"]) for item in documents}
    chunk_ids = {str(item["id"]) for item in chunks}
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
    return {
        "facts": skipped_facts,
        "documents": skipped_documents,
        "chunks": skipped_chunks,
    }


def _import_counts(
    *,
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
    skipped: dict[str, set[str]],
) -> dict[str, int]:
    skipped_source_refs = {
        index
        for index, ref in enumerate(source_refs)
        if str(ref.get("fact_id")) in skipped["facts"]
        or (ref.get("chunk_id") is not None and str(ref["chunk_id"]) in skipped["chunks"])
    }
    return {
        "facts": len(facts) - _count_skipped(facts, skipped["facts"]),
        "documents": len(documents) - _count_skipped(documents, skipped["documents"]),
        "chunks": len(chunks) - _count_skipped(chunks, skipped["chunks"]),
        "source_refs": len(source_refs) - len(skipped_source_refs),
    }


def _count_skipped(items: list[dict[str, Any]], skipped: set[str]) -> int:
    return sum(1 for item in items if str(item["id"]) in skipped)


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


def _bounded_optional_text(value: object, limit: int) -> str | None:
    if value is None:
        return None
    return str(value)[:limit]
