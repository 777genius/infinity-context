"""Expand visible context through approved canonical context links."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.application.context_hydration import ContextHydrator
from infinity_context_core.application.context_policy import is_context_fact_visible
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.application.source_refs import (
    chunk_source_refs,
    source_ref_location_summary,
)
from infinity_context_core.domain.assets import AssetStatus, MemoryAsset, MemoryContextLink
from infinity_context_core.domain.entities import MemoryChunk, MemoryFact, SourceRef
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort


@dataclass(frozen=True)
class ContextLinkExpansionResult:
    items: tuple[ContextItem, ...]
    diagnostics: dict[str, object]


class ApprovedContextLinkExpander:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        hydrator: ContextHydrator,
        clock: ClockPort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._hydrator = hydrator
        self._clock = clock

    async def collect(
        self,
        *,
        items: tuple[ContextItem, ...],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> ContextLinkExpansionResult:
        if not items or (
            query.max_chunks <= 0 and query.max_facts <= 0 and query.max_evidence_items <= 0
        ):
            return ContextLinkExpansionResult(items=(), diagnostics=_empty_diagnostics())

        visible_item_ids = {
            (item.item_type, item.item_id)
            for item in items
            if item.item_type in {"anchor", "chunk", "fact"}
        }
        if not visible_item_ids:
            return ContextLinkExpansionResult(items=(), diagnostics=_empty_diagnostics())

        links = await self._collect_links(
            visible_item_ids=visible_item_ids,
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        deduped_links = _dedupe_context_links(tuple(links))
        existing_chunk_ids = {item.item_id for item in items if item.item_type == "chunk"}
        existing_fact_ids = {item.item_id for item in items if item.item_type == "fact"}
        existing_asset_ids = {item.item_id for item in items if item.item_type == "asset"}
        chunk_items, stale_chunk_drop_count = await self._linked_chunk_items(
            links=deduped_links,
            existing_chunk_ids=existing_chunk_ids,
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        fact_items, stale_fact_drop_count = await self._linked_fact_items(
            links=deduped_links,
            existing_fact_ids=existing_fact_ids,
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        asset_items, stale_asset_drop_count = await self._linked_asset_items(
            links=deduped_links,
            existing_asset_ids=existing_asset_ids,
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        return ContextLinkExpansionResult(
            items=(*chunk_items, *fact_items, *asset_items),
            diagnostics={
                "approved_context_links_considered": len(deduped_links),
                "approved_context_links_used": (
                    len(chunk_items) + len(fact_items) + len(asset_items)
                ),
                "approved_context_linked_chunks_used": len(chunk_items),
                "approved_context_linked_facts_used": len(fact_items),
                "approved_context_linked_assets_used": len(asset_items),
                "stale_context_linked_chunk_drop_count": stale_chunk_drop_count,
                "stale_context_linked_fact_drop_count": stale_fact_drop_count,
                "stale_context_linked_asset_drop_count": stale_asset_drop_count,
            },
        )

    async def _collect_links(
        self,
        *,
        visible_item_ids: set[tuple[str, str]],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> list[MemoryContextLink]:
        max_links = max(query.max_chunks, query.max_facts, 1) * 4
        links: list[MemoryContextLink] = []
        async with self._uow_factory() as uow:
            for item_type, item_id in sorted(visible_item_ids):
                if len(links) >= max_links:
                    break
                for memory_scope_id in memory_scope_ids:
                    links.extend(
                        await uow.context_links.list_for_source(
                            space_id=str(query.space_id),
                            memory_scope_id=memory_scope_id,
                            source_type=item_type,
                            source_id=item_id,
                            status="active",
                            limit=10,
                        )
                    )
                    links.extend(
                        await uow.context_links.list_for_scope(
                            space_id=str(query.space_id),
                            memory_scope_id=memory_scope_id,
                            status="active",
                            limit=10,
                            target_type=item_type,
                            target_id=item_id,
                        )
                    )
        return links[:max_links]

    async def _linked_chunk_items(
        self,
        *,
        links: tuple[MemoryContextLink, ...],
        existing_chunk_ids: set[str],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> tuple[tuple[ContextItem, ...], int]:
        if query.max_chunks <= 0:
            return (), 0
        links_by_chunk_id = _best_links_by_target_id(
            links=links,
            target_type="chunk",
            existing_ids=existing_chunk_ids,
            limit=max(query.max_chunks, 1),
        )
        chunk_ids = tuple(links_by_chunk_id)
        chunks = await self._hydrator.hydrate_visible_chunks(
            chunk_ids=chunk_ids,
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        chunks_by_id = {str(chunk.id): chunk for chunk in chunks}
        items: list[ContextItem] = []
        for chunk_id, link in links_by_chunk_id.items():
            chunk = chunks_by_id.get(chunk_id)
            if chunk is None:
                continue
            items.append(_linked_chunk_context_item(chunk, link=link))
        return tuple(items), max(0, len(chunk_ids) - len(items))

    async def _linked_fact_items(
        self,
        *,
        links: tuple[MemoryContextLink, ...],
        existing_fact_ids: set[str],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> tuple[tuple[ContextItem, ...], int]:
        if query.max_facts <= 0:
            return (), 0
        links_by_fact_id = _best_links_by_target_id(
            links=links,
            target_type="fact",
            existing_ids=existing_fact_ids,
            limit=max(query.max_facts, 1),
        )
        fact_ids = tuple(links_by_fact_id)
        if not fact_ids:
            return (), 0
        now = self._clock.now() if self._clock is not None else None
        async with self._uow_factory() as uow:
            facts_by_id = {str(fact.id): fact for fact in await uow.facts.get_by_ids(fact_ids)}
        items: list[ContextItem] = []
        for fact_id, link in links_by_fact_id.items():
            fact = facts_by_id.get(fact_id)
            if fact is None or not is_context_fact_visible(
                fact,
                query=query,
                memory_scope_ids=memory_scope_ids,
                now=now,
            ):
                continue
            items.append(_linked_fact_context_item(fact, link=link))
        return tuple(items), max(0, len(fact_ids) - len(items))

    async def _linked_asset_items(
        self,
        *,
        links: tuple[MemoryContextLink, ...],
        existing_asset_ids: set[str],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> tuple[tuple[ContextItem, ...], int]:
        if query.max_evidence_items <= 0:
            return (), 0
        links_by_asset_id = _best_links_by_target_id(
            links=links,
            target_type="asset",
            existing_ids=existing_asset_ids,
            limit=max(query.max_evidence_items, 1),
        )
        asset_ids = tuple(links_by_asset_id)
        if not asset_ids:
            return (), 0
        async with self._uow_factory() as uow:
            assets_by_id = {}
            for asset_id in asset_ids:
                asset = await uow.assets.get_by_id(asset_id)
                if asset is not None:
                    assets_by_id[str(asset.id)] = asset
        items: list[ContextItem] = []
        allowed_scope_ids = set(memory_scope_ids)
        for asset_id, link in links_by_asset_id.items():
            asset = assets_by_id.get(asset_id)
            if asset is None or not _asset_visible(
                asset,
                query=query,
                memory_scope_ids=allowed_scope_ids,
            ):
                continue
            items.append(_linked_asset_context_item(asset, link=link))
        return tuple(items), max(0, len(asset_ids) - len(items))


def _empty_diagnostics() -> dict[str, object]:
    return {
        "approved_context_links_considered": 0,
        "approved_context_links_used": 0,
        "approved_context_linked_chunks_used": 0,
        "approved_context_linked_facts_used": 0,
        "approved_context_linked_assets_used": 0,
        "stale_context_linked_chunk_drop_count": 0,
        "stale_context_linked_fact_drop_count": 0,
        "stale_context_linked_asset_drop_count": 0,
    }


def _best_links_by_target_id(
    *,
    links: tuple[MemoryContextLink, ...],
    target_type: str,
    existing_ids: set[str],
    limit: int,
) -> dict[str, MemoryContextLink]:
    links_by_id: dict[str, MemoryContextLink] = {}
    for link in links:
        target_id = _linked_target_id(link, target_type=target_type)
        if not target_id or target_id in existing_ids:
            continue
        existing = links_by_id.get(target_id)
        if existing is None or _linked_item_score(link) > _linked_item_score(existing):
            links_by_id[target_id] = link
        if len(links_by_id) >= limit:
            break
    return links_by_id


def _linked_target_id(link: MemoryContextLink, *, target_type: str) -> str | None:
    if link.source_type == target_type:
        return link.source_id
    if link.target_type == target_type:
        return link.target_id
    return None


def _linked_chunk_context_item(chunk: MemoryChunk, *, link: MemoryContextLink) -> ContextItem:
    score = _linked_item_score(link)
    text = document_chunk_retrieval_text(text=chunk.text, metadata=chunk.metadata)
    source_refs = chunk_source_refs(chunk, text_preview=text[:200])
    return ContextItem(
        item_id=str(chunk.id),
        item_type="chunk",
        text=text,
        score=score,
        source_refs=source_refs,
        diagnostics=_linked_item_diagnostics(
            link=link,
            retrieval_source="approved_context_linked_chunks",
            memory_scope_id=str(chunk.memory_scope_id),
            score=score,
            source_ref_count=len(source_refs),
            extra_provenance={
                "source_type": chunk.source_type,
                "source_id": chunk.source_external_id,
                "chunk_id": str(chunk.id),
                "sequence": chunk.sequence,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                **source_ref_location_summary(source_refs),
            },
            extra_diagnostics={
                "source_type": chunk.source_type,
                "source_id": chunk.source_external_id,
                "chunk_sequence": chunk.sequence,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                **source_ref_location_summary(source_refs),
            },
        ),
    )


def _linked_fact_context_item(fact: MemoryFact, *, link: MemoryContextLink) -> ContextItem:
    score = min(0.93, round(_linked_item_score(link) + 0.015, 4))
    return ContextItem(
        item_id=str(fact.id),
        item_type="fact",
        text=fact.text,
        score=score,
        source_refs=fact.source_refs,
        diagnostics=_linked_item_diagnostics(
            link=link,
            retrieval_source="approved_context_linked_facts",
            memory_scope_id=str(fact.memory_scope_id),
            score=score,
            source_ref_count=len(fact.source_refs),
            extra_provenance={
                "fact_status": fact.status.value,
                "fact_version": fact.version,
            },
            extra_diagnostics={
                "confidence": fact.confidence.value,
                "trust_level": fact.trust_level.value,
                "updated_at": fact.updated_at.isoformat(),
            },
        ),
    )


def _linked_asset_context_item(asset: MemoryAsset, *, link: MemoryContextLink) -> ContextItem:
    score = min(0.9, round(_linked_item_score(link) + 0.005, 4))
    text = (
        f"Linked file {asset.filename} "
        f"({asset.content_type}, {asset.byte_size} bytes)"
    )
    source_refs = (
        SourceRef(
            source_type="asset",
            source_id=str(asset.id),
            quote_preview=asset.filename,
        ),
    )
    return ContextItem(
        item_id=str(asset.id),
        item_type="asset",
        text=text,
        score=score,
        source_refs=source_refs,
        diagnostics=_linked_item_diagnostics(
            link=link,
            retrieval_source="approved_context_linked_assets",
            memory_scope_id=str(asset.memory_scope_id),
            score=score,
            source_ref_count=len(source_refs),
            extra_provenance={
                "asset_id": str(asset.id),
                "asset_filename": asset.filename,
                "asset_content_type": asset.content_type,
                "asset_byte_size": asset.byte_size,
                "asset_status": asset.status.value,
            },
            extra_diagnostics={
                "asset_id": str(asset.id),
                "asset_filename": asset.filename,
                "asset_content_type": asset.content_type,
                "asset_byte_size": asset.byte_size,
                "asset_status": asset.status.value,
                **source_ref_location_summary(source_refs),
            },
        ),
    )


def _linked_item_diagnostics(
    *,
    link: MemoryContextLink,
    retrieval_source: str,
    memory_scope_id: str,
    score: float,
    source_ref_count: int,
    extra_provenance: dict[str, object],
    extra_diagnostics: dict[str, object],
) -> dict[str, object]:
    return {
        "memory_scope_id": memory_scope_id,
        "retrieval_source": retrieval_source,
        "retrieval_sources": [retrieval_source],
        "ranking_reason": "approved context link connected visible memory to related evidence",
        "context_link_id": str(link.id),
        "context_link_relation_type": link.relation_type,
        "context_link_confidence": link.confidence,
        "score_signals": {
            "base_score": 0.8,
            "final_score": score,
            "retrieval_channel": retrieval_source,
            "context_link_confidence_boost": round(score - 0.8, 4),
            "source_ref_count": source_ref_count,
        },
        "provenance": {
            "retrieval_sources": [retrieval_source],
            "source_ref_count": source_ref_count,
            "context_link_id": str(link.id),
            "context_link_relation_type": link.relation_type,
            "context_link_source_type": link.source_type,
            "context_link_source_id": link.source_id,
            "context_link_target_type": link.target_type,
            "context_link_target_id": link.target_id,
            **extra_provenance,
        },
        **extra_diagnostics,
    }


def _linked_item_score(link: MemoryContextLink) -> float:
    confidence_boost = {
        "high": 0.06,
        "medium": 0.035,
        "low": 0.015,
    }.get(link.confidence, 0.025)
    relation_boost = 0.015 if link.relation_type in {"evidence_of", "mentions"} else 0.0
    return min(0.91, round(0.8 + confidence_boost + relation_boost, 4))


def _asset_visible(
    asset: MemoryAsset,
    *,
    query: BuildContextQuery,
    memory_scope_ids: set[str],
) -> bool:
    if asset.status != AssetStatus.STORED:
        return False
    if str(asset.space_id) != str(query.space_id):
        return False
    if str(asset.memory_scope_id) not in memory_scope_ids:
        return False
    return query.thread_id is None or str(asset.thread_id) == str(query.thread_id)


def _dedupe_context_links(links: tuple[MemoryContextLink, ...]) -> tuple[MemoryContextLink, ...]:
    by_id: dict[str, MemoryContextLink] = {}
    for link in links:
        by_id[str(link.id)] = link
    return tuple(by_id.values())
