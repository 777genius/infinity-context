"""Expand visible context through approved canonical context links."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.application.context_artifact_evidence import (
    context_items_from_media_manifest_payload,
    read_media_manifest_payload,
)
from infinity_context_core.application.context_hydration import ContextHydrator
from infinity_context_core.application.context_link_expansion_items import (
    _linked_anchor_context_item,
    _linked_asset_context_item,
    _linked_asset_manifest_extra_diagnostics,
    _linked_asset_manifest_extra_provenance,
    _linked_chunk_context_item,
    _linked_extraction_artifact_context_item,
    _linked_extraction_artifact_extra_diagnostics,
    _linked_extraction_artifact_extra_provenance,
    _linked_fact_context_item,
    _linked_item_score,
)
from infinity_context_core.application.context_policy import (
    is_context_anchor_visible,
    is_context_fact_visible,
)
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.domain.assets import AssetStatus, MemoryAsset, MemoryContextLink
from infinity_context_core.domain.entities import MemoryAnchor
from infinity_context_core.domain.extraction import (
    AssetExtractionJob,
    AssetExtractionStatus,
    ExtractionArtifact,
    ExtractionArtifactType,
)
from infinity_context_core.ports.assets import BlobStoragePort
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
        blob_storage: BlobStoragePort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._hydrator = hydrator
        self._clock = clock
        self._blob_storage = blob_storage

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

        visible_item_ids = _visible_link_endpoint_ids(items)
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
        existing_artifact_ids = {
            item.item_id for item in items if item.item_type == "extraction_artifact"
        }
        existing_anchor_ids = {item.item_id for item in items if item.item_type == "anchor"}
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
        anchor_items, stale_anchor_drop_count = await self._linked_anchor_items(
            links=deduped_links,
            existing_anchor_ids=existing_anchor_ids,
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        (
            asset_items,
            stale_asset_drop_count,
            asset_manifest_diagnostics,
        ) = await self._linked_asset_items(
            links=deduped_links,
            existing_asset_ids=existing_asset_ids,
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        (
            artifact_items,
            stale_artifact_drop_count,
            artifact_diagnostics,
        ) = await self._linked_extraction_artifact_items(
            links=deduped_links,
            existing_artifact_ids=existing_artifact_ids,
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        return ContextLinkExpansionResult(
            items=(*chunk_items, *fact_items, *anchor_items, *asset_items, *artifact_items),
            diagnostics={
                "approved_context_links_considered": len(deduped_links),
                "approved_context_links_used": (
                    len(chunk_items)
                    + len(fact_items)
                    + len(anchor_items)
                    + len(asset_items)
                    + len(artifact_items)
                ),
                "approved_context_linked_chunks_used": len(chunk_items),
                "approved_context_linked_facts_used": len(fact_items),
                "approved_context_linked_anchors_used": len(anchor_items),
                "approved_context_linked_assets_used": len(asset_items),
                "approved_context_linked_extraction_artifacts_used": len(artifact_items),
                "stale_context_linked_chunk_drop_count": stale_chunk_drop_count,
                "stale_context_linked_fact_drop_count": stale_fact_drop_count,
                "stale_context_linked_anchor_drop_count": stale_anchor_drop_count,
                "stale_context_linked_asset_drop_count": stale_asset_drop_count,
                "stale_context_linked_extraction_artifact_drop_count": (stale_artifact_drop_count),
                **asset_manifest_diagnostics,
                **artifact_diagnostics,
            },
        )

    async def _collect_links(
        self,
        *,
        visible_item_ids: set[tuple[str, str]],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> list[MemoryContextLink]:
        max_links = max(query.max_chunks, query.max_facts, query.max_evidence_items, 1) * 4
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
            items.append(_linked_chunk_context_item(chunk, link=link, query_text=query.query))
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
            items.append(_linked_fact_context_item(fact, link=link, query_text=query.query))
        return tuple(items), max(0, len(fact_ids) - len(items))

    async def _linked_anchor_items(
        self,
        *,
        links: tuple[MemoryContextLink, ...],
        existing_anchor_ids: set[str],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> tuple[tuple[ContextItem, ...], int]:
        if query.max_facts <= 0:
            return (), 0
        links_by_anchor_id = _best_links_by_target_id(
            links=links,
            target_type="anchor",
            existing_ids=existing_anchor_ids,
            limit=max(query.max_facts, 1),
        )
        anchor_ids = tuple(links_by_anchor_id)
        if not anchor_ids:
            return (), 0
        now = self._clock.now() if self._clock is not None else None
        anchors_by_id: dict[str, MemoryAnchor] = {}
        async with self._uow_factory() as uow:
            for anchor_id in anchor_ids:
                anchor = await uow.anchors.get_by_id(anchor_id)
                if anchor is not None and is_context_anchor_visible(
                    anchor,
                    query=query,
                    memory_scope_ids=memory_scope_ids,
                    now=now,
                ):
                    anchors_by_id[anchor_id] = anchor
        items: list[ContextItem] = []
        for anchor_id, link in links_by_anchor_id.items():
            anchor = anchors_by_id.get(anchor_id)
            if anchor is None:
                continue
            items.append(
                _linked_anchor_context_item(
                    anchor,
                    link=link,
                    query_text=query.query,
                    now=now,
                )
            )
        return tuple(items), max(0, len(anchor_ids) - len(items))

    async def _linked_asset_items(
        self,
        *,
        links: tuple[MemoryContextLink, ...],
        existing_asset_ids: set[str],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> tuple[tuple[ContextItem, ...], int, dict[str, object]]:
        diagnostics = _empty_asset_manifest_diagnostics()
        if query.max_evidence_items <= 0:
            return (), 0, diagnostics
        links_by_asset_id = _best_links_by_target_id(
            links=links,
            target_type="asset",
            existing_ids=existing_asset_ids,
            limit=max(query.max_evidence_items, 1),
        )
        asset_ids = tuple(links_by_asset_id)
        if not asset_ids:
            return (), 0, diagnostics
        async with self._uow_factory() as uow:
            assets_by_id = {}
            manifests_by_asset_id: dict[str, tuple[ExtractionArtifact, AssetExtractionJob]] = {}
            for asset_id in asset_ids:
                asset = await uow.assets.get_by_id(asset_id)
                if asset is not None:
                    assets_by_id[str(asset.id)] = asset
                    manifest = await _latest_asset_media_manifest(
                        uow,
                        asset_id=asset_id,
                        diagnostics=diagnostics,
                    )
                    if manifest is not None:
                        manifests_by_asset_id[asset_id] = manifest
        items: list[ContextItem] = []
        allowed_scope_ids = set(memory_scope_ids)
        visible_asset_count = 0
        for asset_id, link in links_by_asset_id.items():
            if len(items) >= query.max_evidence_items:
                break
            asset = assets_by_id.get(asset_id)
            if asset is None or not _asset_visible(
                asset,
                query=query,
                memory_scope_ids=allowed_scope_ids,
            ):
                continue
            visible_asset_count += 1
            manifest = manifests_by_asset_id.get(asset_id)
            if manifest is not None and self._blob_storage is not None:
                artifact, job = manifest
                payload = await read_media_manifest_payload(
                    blob_storage=self._blob_storage,
                    artifact=artifact,
                    diagnostics=diagnostics,
                    diagnostic_prefix="approved_context_linked_asset_manifest",
                )
                if payload is not None:
                    manifest_items = context_items_from_media_manifest_payload(
                        artifact=artifact,
                        job_id=str(job.id),
                        memory_scope_id=str(job.memory_scope_id),
                        payload=payload,
                        query=query,
                        diagnostics=diagnostics,
                        retrieval_source="approved_context_linked_asset_manifest_evidence",
                        ranking_reason=(
                            "approved context link connected visible memory to "
                            "linked asset extraction evidence"
                        ),
                        require_query_match=False,
                        extra_diagnostics=_linked_asset_manifest_extra_diagnostics(
                            artifact=artifact,
                            job=job,
                            asset=asset,
                            link=link,
                        ),
                        extra_provenance=_linked_asset_manifest_extra_provenance(
                            artifact=artifact,
                            job=job,
                            asset=asset,
                            link=link,
                        ),
                    )
                    selected_manifest_items = sorted(
                        manifest_items,
                        key=lambda item: (-item.score, item.item_id),
                    )[: max(0, query.max_evidence_items - len(items))]
                    diagnostics["approved_context_linked_asset_manifest_items_used"] = int(
                        diagnostics["approved_context_linked_asset_manifest_items_used"]
                    ) + len(selected_manifest_items)
                    items.extend(selected_manifest_items)
                    if len(items) >= query.max_evidence_items:
                        break
                    if selected_manifest_items:
                        continue
            elif manifest is not None:
                diagnostics[
                    "approved_context_linked_asset_manifest_blob_storage_disabled_count"
                ] = (
                    int(
                        diagnostics[
                            "approved_context_linked_asset_manifest_blob_storage_disabled_count"
                        ]
                    )
                    + 1
                )
            items.append(_linked_asset_context_item(asset, link=link))
            if len(items) >= query.max_evidence_items:
                break
        return (
            tuple(items),
            max(0, len(asset_ids) - visible_asset_count),
            _strip_generic_artifact_evidence_diagnostics(diagnostics),
        )

    async def _linked_extraction_artifact_items(
        self,
        *,
        links: tuple[MemoryContextLink, ...],
        existing_artifact_ids: set[str],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> tuple[tuple[ContextItem, ...], int, dict[str, object]]:
        diagnostics = _empty_extraction_artifact_diagnostics()
        if query.max_evidence_items <= 0:
            return (), 0, diagnostics
        links_by_artifact_id = _best_links_by_target_id(
            links=links,
            target_type="extraction_artifact",
            existing_ids=existing_artifact_ids,
            limit=max(query.max_evidence_items, 1),
        )
        artifact_ids = tuple(links_by_artifact_id)
        if not artifact_ids:
            return (), 0, diagnostics

        loaded: dict[str, tuple[ExtractionArtifact, AssetExtractionJob, MemoryAsset]] = {}
        async with self._uow_factory() as uow:
            for artifact_id in artifact_ids:
                artifact = await uow.asset_extractions.get_artifact_by_id(artifact_id)
                if artifact is None:
                    continue
                job = await uow.asset_extractions.get_by_id(str(artifact.job_id))
                asset = await uow.assets.get_by_id(str(artifact.asset_id))
                if (
                    job is None
                    or asset is None
                    or not _extraction_artifact_visible(
                        artifact=artifact,
                        job=job,
                        asset=asset,
                        query=query,
                        memory_scope_ids=set(memory_scope_ids),
                    )
                ):
                    continue
                loaded[artifact_id] = (artifact, job, asset)

        items: list[ContextItem] = []
        for artifact_id, link in links_by_artifact_id.items():
            loaded_item = loaded.get(artifact_id)
            if loaded_item is None:
                continue
            artifact, job, asset = loaded_item
            if (
                artifact.artifact_type == ExtractionArtifactType.MEDIA_MANIFEST
                and self._blob_storage is not None
            ):
                payload = await read_media_manifest_payload(
                    blob_storage=self._blob_storage,
                    artifact=artifact,
                    diagnostics=diagnostics,
                    diagnostic_prefix="approved_context_linked_extraction_artifact",
                )
                if payload is not None:
                    manifest_items = context_items_from_media_manifest_payload(
                        artifact=artifact,
                        job_id=str(job.id),
                        memory_scope_id=str(job.memory_scope_id),
                        payload=payload,
                        query=query,
                        diagnostics=diagnostics,
                        retrieval_source="approved_context_linked_extraction_artifacts",
                        ranking_reason=(
                            "approved context link connected visible memory to "
                            "multimodal extraction evidence"
                        ),
                        require_query_match=False,
                        extra_diagnostics=_linked_extraction_artifact_extra_diagnostics(
                            artifact=artifact,
                            job=job,
                            asset=asset,
                            link=link,
                        ),
                        extra_provenance=_linked_extraction_artifact_extra_provenance(
                            artifact=artifact,
                            job=job,
                            asset=asset,
                            link=link,
                        ),
                    )
                    manifest_items_key = (
                        "approved_context_linked_extraction_artifact_manifest_items_used"
                    )
                    diagnostics[manifest_items_key] = int(diagnostics[manifest_items_key]) + len(
                        manifest_items
                    )
                    items.extend(
                        sorted(manifest_items, key=lambda item: (-item.score, item.item_id))[
                            : max(0, query.max_evidence_items - len(items))
                        ]
                    )
                    if len(items) >= query.max_evidence_items:
                        break
                    continue
            elif artifact.artifact_type == ExtractionArtifactType.MEDIA_MANIFEST:
                diagnostics[
                    "approved_context_linked_extraction_artifact_blob_storage_disabled_count"
                ] = (
                    int(
                        diagnostics[
                            "approved_context_linked_extraction_artifact_blob_storage_disabled_count"
                        ]
                    )
                    + 1
                )
            items.append(
                _linked_extraction_artifact_context_item(
                    artifact,
                    job=job,
                    asset=asset,
                    link=link,
                )
            )
            if len(items) >= query.max_evidence_items:
                break
        return (
            tuple(items),
            max(0, len(artifact_ids) - len(loaded)),
            _strip_generic_artifact_evidence_diagnostics(diagnostics),
        )


def _empty_diagnostics() -> dict[str, object]:
    return {
        "approved_context_links_considered": 0,
        "approved_context_links_used": 0,
        "approved_context_linked_chunks_used": 0,
        "approved_context_linked_facts_used": 0,
        "approved_context_linked_anchors_used": 0,
        "approved_context_linked_assets_used": 0,
        "approved_context_linked_extraction_artifacts_used": 0,
        "stale_context_linked_chunk_drop_count": 0,
        "stale_context_linked_fact_drop_count": 0,
        "stale_context_linked_anchor_drop_count": 0,
        "stale_context_linked_asset_drop_count": 0,
        "stale_context_linked_extraction_artifact_drop_count": 0,
        **_empty_asset_manifest_diagnostics(),
        **_empty_extraction_artifact_diagnostics(),
    }


def _empty_asset_manifest_diagnostics() -> dict[str, object]:
    return {
        "approved_context_linked_asset_manifest_jobs_considered": 0,
        "approved_context_linked_asset_manifest_artifacts_considered": 0,
        "approved_context_linked_asset_manifest_items_used": 0,
        "approved_context_linked_asset_manifest_blob_storage_disabled_count": 0,
        "approved_context_linked_asset_manifest_too_large_count": 0,
        "approved_context_linked_asset_manifest_read_error_count": 0,
        "approved_context_linked_asset_manifest_parse_error_count": 0,
        "approved_context_linked_asset_manifest_schema_skip_count": 0,
    }


def _empty_extraction_artifact_diagnostics() -> dict[str, object]:
    return {
        "approved_context_linked_extraction_artifact_manifest_items_used": 0,
        "approved_context_linked_extraction_artifact_blob_storage_disabled_count": 0,
        "approved_context_linked_extraction_artifact_manifest_too_large_count": 0,
        "approved_context_linked_extraction_artifact_read_error_count": 0,
        "approved_context_linked_extraction_artifact_parse_error_count": 0,
        "approved_context_linked_extraction_artifact_schema_skip_count": 0,
    }


def _strip_generic_artifact_evidence_diagnostics(
    diagnostics: dict[str, object],
) -> dict[str, object]:
    return {
        key: value
        for key, value in diagnostics.items()
        if key != "artifact_evidence_status" and not key.startswith("artifact_evidence_")
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


def _visible_link_endpoint_ids(items: tuple[ContextItem, ...]) -> set[tuple[str, str]]:
    visible: set[tuple[str, str]] = set()
    for item in items:
        if item.item_type in {"anchor", "asset", "chunk", "fact"}:
            visible.add((item.item_type, item.item_id))
            continue
        if item.item_type != "extraction_artifact":
            continue
        visible.add((item.item_type, item.item_id))
        diagnostics = item.diagnostics if isinstance(item.diagnostics, dict) else {}
        artifact_id = diagnostics.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id.strip():
            visible.add(("extraction_artifact", artifact_id.strip()))
        for source_ref in item.source_refs:
            if source_ref.source_type == "extraction_artifact" and source_ref.source_id:
                visible.add(("extraction_artifact", source_ref.source_id))
    return visible


async def _latest_asset_media_manifest(
    uow: object,
    *,
    asset_id: str,
    diagnostics: dict[str, object],
) -> tuple[ExtractionArtifact, AssetExtractionJob] | None:
    jobs = await uow.asset_extractions.list_for_asset(
        asset_id=asset_id,
        status=AssetExtractionStatus.SUCCEEDED.value,
        limit=5,
    )
    diagnostics["approved_context_linked_asset_manifest_jobs_considered"] = int(
        diagnostics["approved_context_linked_asset_manifest_jobs_considered"]
    ) + len(jobs)
    for job in jobs:
        artifacts = await uow.asset_extractions.list_artifacts(job_id=str(job.id))
        diagnostics["approved_context_linked_asset_manifest_artifacts_considered"] = int(
            diagnostics["approved_context_linked_asset_manifest_artifacts_considered"]
        ) + len(artifacts)
        for artifact in artifacts:
            if artifact.artifact_type == ExtractionArtifactType.MEDIA_MANIFEST:
                return artifact, job
    return None














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


def _extraction_artifact_visible(
    *,
    artifact: ExtractionArtifact,
    job: AssetExtractionJob,
    asset: MemoryAsset,
    query: BuildContextQuery,
    memory_scope_ids: set[str],
) -> bool:
    if job.status != AssetExtractionStatus.SUCCEEDED:
        return False
    if str(job.id) != str(artifact.job_id) or str(job.asset_id) != str(artifact.asset_id):
        return False
    if str(asset.id) != str(artifact.asset_id):
        return False
    return _asset_visible(asset, query=query, memory_scope_ids=memory_scope_ids)









def _dedupe_context_links(links: tuple[MemoryContextLink, ...]) -> tuple[MemoryContextLink, ...]:
    by_id: dict[str, MemoryContextLink] = {}
    for link in links:
        by_id[str(link.id)] = link
    return tuple(by_id.values())
