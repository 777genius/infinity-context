import asyncio
import json
from datetime import UTC, datetime

from infinity_context_core.application import BuildContextQuery, ContextItem
from infinity_context_core.application.context_link_expansion import (
    ApprovedContextLinkExpander,
    _linked_fact_context_item,
)
from infinity_context_core.domain.assets import (
    MemoryAsset,
    MemoryAssetId,
    MemoryContextLink,
    MemoryContextLinkId,
)
from infinity_context_core.domain.entities import (
    Confidence,
    MemoryAnchor,
    MemoryAnchorId,
    MemoryAnchorKind,
    MemoryFact,
    MemoryFactId,
    MemoryKind,
    MemoryScopeId,
    SourceRef,
    SpaceId,
)
from infinity_context_core.domain.extraction import (
    AssetExtractionJob,
    AssetExtractionJobId,
    ExtractionArtifact,
    ExtractionArtifactId,
)


def test_approved_link_expands_media_manifest_artifact_evidence() -> None:
    now = datetime(2026, 6, 19, tzinfo=UTC)
    link = MemoryContextLink.create(
        link_id=MemoryContextLinkId("context_link_anchor_artifact"),
        space_id=SpaceId("space_client_app"),
        memory_scope_id=MemoryScopeId("memory_scope_default"),
        source_type="anchor",
        source_id="anchor_event_alex",
        target_type="extraction_artifact",
        target_id="artifact_manifest_1",
        relation_type="evidence_of",
        confidence="high",
        reason="event anchor points to exact transcript evidence",
        now=now,
    )
    uow = _LinkedArtifactUnitOfWork(now=now, link=link)
    expander = ApprovedContextLinkExpander(
        uow_factory=lambda: uow,
        hydrator=object(),
        blob_storage=_BlobStorage(
            {
                "artifact/manifest.json": json.dumps(
                    {
                        "schema_version": "infinity_context.multimodal_manifest.v1",
                        "evidence_items": [
                            {
                                "id": "segment_1",
                                "kind": "transcript_segment",
                                "modality": "video",
                                "text_preview": (
                                    "Atlas billing cutoff was confirmed by Alex in the "
                                    "uploaded call."
                                ),
                                "confidence": 0.91,
                                "time_range": {"start_ms": 1200, "end_ms": 6400},
                                "bbox": [0, 0, 320, 180],
                            }
                        ],
                    }
                ).encode("utf-8")
            }
        ),
    )

    result = asyncio.run(
        expander.collect(
            items=(
                ContextItem(
                    item_id="anchor_event_alex",
                    item_type="anchor",
                    text="event: Sprint review. with: Alex",
                    score=0.86,
                    source_refs=(),
                    diagnostics={"memory_scope_id": "memory_scope_default"},
                ),
            ),
            query=BuildContextQuery(
                space_id=SpaceId("space_client_app"),
                memory_scope_ids=(MemoryScopeId("memory_scope_default"),),
                query="Alex last week",
                max_facts=0,
                max_chunks=0,
                max_evidence_items=4,
            ),
            memory_scope_ids=("memory_scope_default",),
        )
    )

    assert result.diagnostics["approved_context_linked_extraction_artifacts_used"] == 1
    assert (
        result.diagnostics["approved_context_linked_extraction_artifact_manifest_items_used"] == 1
    )
    assert result.diagnostics["stale_context_linked_extraction_artifact_drop_count"] == 0
    item = result.items[0]
    assert item.item_type == "extraction_artifact"
    assert item.diagnostics["retrieval_source"] == ("approved_context_linked_extraction_artifacts")
    assert item.diagnostics["context_link_relation_type"] == "evidence_of"
    assert "Atlas billing cutoff" in item.text
    assert item.source_refs[0].time_start_ms == 1200
    assert item.source_refs[0].time_end_ms == 6400
    assert item.source_refs[0].bbox == (0.0, 0.0, 320.0, 180.0)


def test_approved_asset_link_expands_latest_media_manifest_evidence() -> None:
    now = datetime(2026, 6, 19, tzinfo=UTC)
    link = MemoryContextLink.create(
        link_id=MemoryContextLinkId("context_link_anchor_asset"),
        space_id=SpaceId("space_client_app"),
        memory_scope_id=MemoryScopeId("memory_scope_default"),
        source_type="anchor",
        source_id="anchor_event_alex",
        target_type="asset",
        target_id="asset_video_1",
        relation_type="evidence_of",
        confidence="high",
        reason="event anchor points to the uploaded call asset",
        now=now,
    )
    uow = _LinkedArtifactUnitOfWork(now=now, link=link)
    expander = ApprovedContextLinkExpander(
        uow_factory=lambda: uow,
        hydrator=object(),
        blob_storage=_BlobStorage(
            {
                "artifact/manifest.json": json.dumps(
                    {
                        "schema_version": "infinity_context.multimodal_manifest.v1",
                        "evidence_items": [
                            {
                                "id": "segment_1",
                                "kind": "transcript_segment",
                                "modality": "video",
                                "text_preview": (
                                    "Alex confirmed the Atlas billing cutoff in the "
                                    "uploaded customer call."
                                ),
                                "confidence": 0.92,
                                "time_range": {"start_ms": 2200, "end_ms": 7800},
                                "bbox": [12, 24, 420, 260],
                            }
                        ],
                    }
                ).encode("utf-8")
            }
        ),
    )

    result = asyncio.run(
        expander.collect(
            items=(
                ContextItem(
                    item_id="anchor_event_alex",
                    item_type="anchor",
                    text="event: Customer call. with: Alex",
                    score=0.86,
                    source_refs=(),
                    diagnostics={"memory_scope_id": "memory_scope_default"},
                ),
            ),
            query=BuildContextQuery(
                space_id=SpaceId("space_client_app"),
                memory_scope_ids=(MemoryScopeId("memory_scope_default"),),
                query="Alex billing cutoff",
                max_facts=0,
                max_chunks=0,
                max_evidence_items=4,
            ),
            memory_scope_ids=("memory_scope_default",),
        )
    )

    assert result.diagnostics["approved_context_linked_assets_used"] == 1
    assert result.diagnostics["approved_context_linked_asset_manifest_jobs_considered"] == 1
    assert result.diagnostics["approved_context_linked_asset_manifest_artifacts_considered"] == 1
    assert result.diagnostics["approved_context_linked_asset_manifest_items_used"] == 1
    assert result.diagnostics["stale_context_linked_asset_drop_count"] == 0
    item = result.items[0]
    assert item.item_type == "extraction_artifact"
    assert item.item_id == "artifact_manifest_1:segment_1"
    assert item.diagnostics["retrieval_source"] == (
        "approved_context_linked_asset_manifest_evidence"
    )
    assert item.diagnostics["context_link_relation_type"] == "evidence_of"
    assert item.diagnostics["asset_id"] == "asset_video_1"
    assert item.diagnostics["asset_filename"] == "alex-call.mp4"
    assert "Atlas billing cutoff" in item.text
    assert item.source_refs[0].time_start_ms == 2200
    assert item.source_refs[0].time_end_ms == 7800
    assert item.source_refs[0].bbox == (12.0, 24.0, 420.0, 260.0)


def test_linked_fact_context_item_uses_query_focused_source_quote() -> None:
    now = datetime(2026, 6, 19, tzinfo=UTC)
    fact = MemoryFact.create(
        fact_id=MemoryFactId("fact_linked_launch"),
        space_id=SpaceId("space_client_app"),
        memory_scope_id=MemoryScopeId("memory_scope_default"),
        text=(
            "Intro context. " * 10
            + "Atlas launch decision was approved by Alex after the review. "
            + "Trailing context. " * 10
        ),
        kind=MemoryKind.NOTE,
        source_refs=(
            SourceRef(
                source_type="manual",
                source_id="linked-launch-note",
                quote_preview="old broad quote",
            ),
        ),
        now=now,
    )
    link = MemoryContextLink.create(
        link_id=MemoryContextLinkId("context_link_anchor_fact"),
        space_id=SpaceId("space_client_app"),
        memory_scope_id=MemoryScopeId("memory_scope_default"),
        source_type="anchor",
        source_id="anchor_event_alex",
        target_type="fact",
        target_id=str(fact.id),
        relation_type="references",
        confidence="high",
        reason="event anchor references launch decision",
        now=now,
    )

    item = _linked_fact_context_item(
        fact,
        link=link,
        query_text="Atlas launch decision Alex",
    )

    diagnostics = item.diagnostics or {}
    snippet = diagnostics["query_snippet"]
    assert "Atlas launch decision was approved by Alex" in snippet
    assert item.source_refs[0].quote_preview == snippet
    assert diagnostics["retrieval_source"] == "approved_context_linked_facts"
    assert diagnostics["context_link_relation_type"] == "references"
    assert diagnostics["score_signals"]["query_snippet_unique_term_hits"] == 4


def test_visible_manifest_evidence_expands_reverse_link_to_anchor() -> None:
    now = datetime(2026, 6, 19, tzinfo=UTC)
    anchor = _anchor(now=now)
    link = MemoryContextLink.create(
        link_id=MemoryContextLinkId("context_link_artifact_anchor"),
        space_id=SpaceId("space_client_app"),
        memory_scope_id=MemoryScopeId("memory_scope_default"),
        source_type="extraction_artifact",
        source_id="artifact_manifest_1",
        target_type="anchor",
        target_id=str(anchor.id),
        relation_type="evidence_of",
        confidence="high",
        reason="exact transcript evidence resolves to canonical Alex event",
        now=now,
    )
    uow = _LinkedArtifactUnitOfWork(now=now, link=link, anchor=anchor)
    expander = ApprovedContextLinkExpander(
        uow_factory=lambda: uow,
        hydrator=object(),
    )

    result = asyncio.run(
        expander.collect(
            items=(
                ContextItem(
                    item_id="artifact_manifest_1:segment_1",
                    item_type="extraction_artifact",
                    text="Alex confirmed the Atlas cutoff in this transcript segment.",
                    score=0.9,
                    source_refs=(
                        SourceRef(
                            source_type="extraction_artifact",
                            source_id="artifact_manifest_1",
                            chunk_id="segment_1",
                        ),
                    ),
                    diagnostics={
                        "memory_scope_id": "memory_scope_default",
                        "artifact_id": "artifact_manifest_1",
                    },
                ),
            ),
            query=BuildContextQuery(
                space_id=SpaceId("space_client_app"),
                memory_scope_ids=(MemoryScopeId("memory_scope_default"),),
                query="TRANSCRIPT_ONLY_MARKER",
                max_facts=3,
                max_chunks=0,
                max_evidence_items=0,
            ),
            memory_scope_ids=("memory_scope_default",),
        )
    )

    assert result.diagnostics["approved_context_links_considered"] == 1
    assert result.diagnostics["approved_context_linked_anchors_used"] == 1
    assert result.diagnostics["stale_context_linked_anchor_drop_count"] == 0
    item = result.items[0]
    assert item.item_type == "anchor"
    assert item.text.startswith("event: Alex review")
    assert item.diagnostics["retrieval_source"] == "approved_context_linked_anchors"
    assert item.diagnostics["context_link_relation_type"] == "evidence_of"
    assert item.diagnostics["provenance"]["context_link_source_type"] == "extraction_artifact"
    assert item.diagnostics["score_signals"]["anchor_query_unique_term_hits"] == 0


class _LinkedArtifactUnitOfWork:
    def __init__(
        self,
        *,
        now: datetime,
        link: MemoryContextLink,
        anchor: MemoryAnchor | None = None,
    ) -> None:
        self.context_links = _ContextLinksRepository(link)
        self.assets = _AssetsRepository(_asset(now=now))
        self.anchors = _AnchorsRepository(anchor or _anchor(now=now))
        self.asset_extractions = _AssetExtractionsRepository(
            artifact=_artifact(now=now),
            job=_job(now=now),
        )

    async def __aenter__(self) -> "_LinkedArtifactUnitOfWork":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _ContextLinksRepository:
    def __init__(self, link: MemoryContextLink) -> None:
        self._link = link

    async def list_for_source(self, **kwargs: object) -> list[MemoryContextLink]:
        if (
            kwargs.get("source_type") == self._link.source_type
            and kwargs.get("source_id") == self._link.source_id
        ):
            return [self._link]
        return []

    async def list_for_scope(self, **kwargs: object) -> list[MemoryContextLink]:
        if (
            kwargs.get("target_type") == self._link.source_type
            and kwargs.get("target_id") == self._link.source_id
        ):
            return [self._link]
        return []


class _AssetsRepository:
    def __init__(self, asset: MemoryAsset) -> None:
        self._asset = asset

    async def get_by_id(self, asset_id: str) -> MemoryAsset | None:
        return self._asset if asset_id == str(self._asset.id) else None


class _AnchorsRepository:
    def __init__(self, anchor: MemoryAnchor) -> None:
        self._anchor = anchor

    async def get_by_id(self, anchor_id: str) -> MemoryAnchor | None:
        return self._anchor if anchor_id == str(self._anchor.id) else None


class _AssetExtractionsRepository:
    def __init__(self, *, artifact: ExtractionArtifact, job: AssetExtractionJob) -> None:
        self._artifact = artifact
        self._job = job

    async def get_artifact_by_id(self, artifact_id: str) -> ExtractionArtifact | None:
        return self._artifact if artifact_id == str(self._artifact.id) else None

    async def get_by_id(self, job_id: str) -> AssetExtractionJob | None:
        return self._job if job_id == str(self._job.id) else None

    async def list_for_asset(
        self,
        *,
        asset_id: str,
        status: str | None,
        limit: int,
        cursor_created_at: datetime | None = None,
        cursor_id: str | None = None,
    ) -> list[AssetExtractionJob]:
        if asset_id != str(self._job.asset_id):
            return []
        if status is not None and status != self._job.status.value:
            return []
        return [self._job][:limit]

    async def list_artifacts(self, *, job_id: str) -> list[ExtractionArtifact]:
        return [self._artifact] if job_id == str(self._job.id) else []


class _BlobStorage:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    async def read_bytes(self, *, storage_key: str) -> bytes:
        return self._blobs[storage_key]


def _asset(*, now: datetime) -> MemoryAsset:
    return MemoryAsset.create(
        asset_id=MemoryAssetId("asset_video_1"),
        space_id=SpaceId("space_client_app"),
        memory_scope_id=MemoryScopeId("memory_scope_default"),
        filename="alex-call.mp4",
        content_type="video/mp4",
        byte_size=4096,
        sha256_hex="a" * 64,
        storage_backend="local",
        storage_key="assets/alex-call.mp4",
        now=now,
    )


def _anchor(*, now: datetime) -> MemoryAnchor:
    return MemoryAnchor.create(
        anchor_id=MemoryAnchorId("anchor_event_alex"),
        space_id=SpaceId("space_client_app"),
        memory_scope_id=MemoryScopeId("memory_scope_default"),
        kind=MemoryAnchorKind.EVENT,
        normalized_key="alex review",
        label="Alex review",
        confidence=Confidence.HIGH,
        metadata={
            "anchor_family": "event",
            "event_participant_label": "Alex",
            "event_participant_canonical_key": "alex",
            "event_project_label": "Atlas",
            "event_project_canonical_key": "atlas",
        },
        now=now,
    )


def _job(*, now: datetime) -> AssetExtractionJob:
    return (
        AssetExtractionJob.create(
            job_id=AssetExtractionJobId("extract_video_1"),
            asset_id=MemoryAssetId("asset_video_1"),
            space_id=SpaceId("space_client_app"),
            memory_scope_id=MemoryScopeId("memory_scope_default"),
            parser_profile="standard_local",
            parser_config_hash="profile_hash",
            source_sha256_hex="a" * 64,
            now=now,
        )
        .mark_running(now=now)
        .mark_succeeded(
            now=now,
            result_document_ids=("doc_video_1",),
            parser_name="video_pipeline",
            parser_version="v1",
            model_version=None,
        )
    )


def _artifact(*, now: datetime) -> ExtractionArtifact:
    return ExtractionArtifact.create(
        artifact_id=ExtractionArtifactId("artifact_manifest_1"),
        job_id=AssetExtractionJobId("extract_video_1"),
        asset_id=MemoryAssetId("asset_video_1"),
        artifact_type="media_manifest",
        storage_backend="local",
        storage_key="artifact/manifest.json",
        sha256_hex="b" * 64,
        byte_size=1024,
        now=now,
        metadata={
            "filename": "alex-call.manifest.json",
            "content_type": "application/json",
        },
    )
