from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from hashlib import sha256

from infinity_context_core.application.dto import RunAssetExtractionCommand
from infinity_context_core.application.use_cases.asset_extractions import RunAssetExtractionUseCase
from infinity_context_core.domain.assets import AssetStatus, MemoryAsset, MemoryAssetId
from infinity_context_core.domain.entities import MemoryScopeId, SpaceId, ThreadId
from infinity_context_core.domain.extraction import (
    AssetExtractionJob,
    AssetExtractionJobId,
    AssetExtractionStatus,
)
from infinity_context_core.ports.extraction import ExtractionLimits


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 6, 19, tzinfo=UTC)


class _Ids:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}_1"

    def projection_id(self, adapter: str, aggregate_type: str, aggregate_id: str) -> str:
        return f"{adapter}:{aggregate_type}:{aggregate_id}"


class _BlobStorage:
    def __init__(self, content: bytes = b"oversized content should not be read") -> None:
        self.content = content
        self.reads: list[str] = []

    async def read_bytes(self, *, storage_key: str) -> bytes:
        self.reads.append(storage_key)
        return self.content


class _Detector:
    def __init__(self) -> None:
        self.called = False

    async def detect(self, request: object) -> object:
        self.called = True
        raise AssertionError("detector must not be called for oversized assets")


class _Extractor:
    def __init__(self) -> None:
        self.called = False

    async def extract(self, request: object) -> object:
        self.called = True
        raise AssertionError("extractor must not be called for oversized assets")


class _Assets:
    def __init__(self, asset: MemoryAsset) -> None:
        self.asset = asset

    async def get_by_id(self, asset_id: str) -> MemoryAsset | None:
        assert asset_id == str(self.asset.id)
        return self.asset


class _AssetExtractions:
    def __init__(self, job: AssetExtractionJob) -> None:
        self.job = job
        self.saved: list[AssetExtractionJob] = []

    async def get_by_id(self, job_id: str) -> AssetExtractionJob | None:
        assert job_id == str(self.job.id)
        return self.job

    async def save(self, job: AssetExtractionJob) -> AssetExtractionJob:
        self.job = job
        self.saved.append(job)
        return job


class _Uow:
    def __init__(self, *, assets: _Assets, asset_extractions: _AssetExtractions) -> None:
        self.assets = assets
        self.asset_extractions = asset_extractions
        self.committed = False

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class _UowFactory:
    def __init__(self, *, asset: MemoryAsset, job: AssetExtractionJob) -> None:
        self.assets = _Assets(asset)
        self.asset_extractions = _AssetExtractions(job)
        self.instances: list[_Uow] = []

    def __call__(self) -> _Uow:
        uow = _Uow(assets=self.assets, asset_extractions=self.asset_extractions)
        self.instances.append(uow)
        return uow


def test_run_asset_extraction_rejects_oversized_asset_before_blob_read() -> None:
    asset = _asset(byte_size=11)
    job = _job(asset=asset)
    uow_factory = _UowFactory(asset=asset, job=job)
    blob_storage = _BlobStorage()
    detector = _Detector()
    extractor = _Extractor()
    use_case = RunAssetExtractionUseCase(
        uow_factory=uow_factory,
        blob_storage=blob_storage,
        detector=detector,
        extractor=extractor,
        ingest_document=object(),
        clock=_Clock(),
        ids=_Ids(),
        limits=ExtractionLimits(max_bytes=10, max_pages=0),
    )

    result = asyncio.run(use_case.execute(RunAssetExtractionCommand(job_id=str(job.id))))

    assert result.job.status == AssetExtractionStatus.UNSUPPORTED
    assert result.indexing_status == "unsupported"
    assert result.job.safe_error_code == "asset_extraction.file_too_large"
    assert result.job.safe_error_message == "Asset exceeds configured extraction size limit"
    assert result.job.metadata["extraction_asset_byte_size"] == 11
    assert result.job.metadata["extraction_max_bytes"] == 10
    assert result.job.metadata["extraction_resource_limit_exceeded"] == "max_bytes"
    assert result.job.metadata["extraction_limits_normalized"] is True
    assert "max_pages" in result.job.metadata["extraction_limits_clamped_fields"]
    assert blob_storage.reads == []
    assert detector.called is False
    assert extractor.called is False
    assert any(
        saved.status == AssetExtractionStatus.RUNNING
        for saved in uow_factory.asset_extractions.saved
    )


def test_run_asset_extraction_revalidates_upload_policy_before_detector() -> None:
    content = b"%PDF-1.7\nnot actually an image"
    asset = _asset(
        byte_size=len(content),
        content=content,
        filename="spoofed-screenshot.png",
        content_type="image/png",
    )
    job = _job(asset=asset)
    uow_factory = _UowFactory(asset=asset, job=job)
    blob_storage = _BlobStorage(content=content)
    detector = _Detector()
    extractor = _Extractor()
    use_case = RunAssetExtractionUseCase(
        uow_factory=uow_factory,
        blob_storage=blob_storage,
        detector=detector,
        extractor=extractor,
        ingest_document=object(),
        clock=_Clock(),
        ids=_Ids(),
        limits=ExtractionLimits(max_bytes=1_000_000, max_image_pixels=50_000_000),
    )

    result = asyncio.run(use_case.execute(RunAssetExtractionCommand(job_id=str(job.id))))

    assert result.job.status == AssetExtractionStatus.UNSUPPORTED
    assert result.indexing_status == "unsupported"
    assert result.job.safe_error_code == "asset_extraction.upload_policy_rejected"
    assert result.job.safe_error_message == "Asset violates upload security policy"
    assert result.job.parser_name == "upload_policy"
    assert result.job.metadata["extraction_upload_policy_revalidated"] is True
    assert result.job.metadata["extraction_upload_policy_status"] == "rejected"
    assert result.job.metadata["extraction_upload_magic_content_type"] == "application/pdf"
    assert "raw" not in result.job.metadata
    assert blob_storage.reads == ["assets/asset_1.bin"]
    assert detector.called is False
    assert extractor.called is False


def _asset(
    *,
    byte_size: int,
    content: bytes | None = None,
    filename: str = "large-recording.wav",
    content_type: str = "audio/wav",
) -> MemoryAsset:
    content = content if content is not None else b"x" * byte_size
    return MemoryAsset.create(
        asset_id=MemoryAssetId("asset_1"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("scope_1"),
        thread_id=ThreadId("thread_1"),
        filename=filename,
        content_type=content_type,
        byte_size=byte_size,
        sha256_hex=sha256(content).hexdigest(),
        storage_backend="local",
        storage_key="assets/asset_1.bin",
        now=datetime(2026, 6, 19, tzinfo=UTC),
    )


def _job(*, asset: MemoryAsset) -> AssetExtractionJob:
    assert asset.status == AssetStatus.STORED
    return AssetExtractionJob.create(
        job_id=AssetExtractionJobId("extract_1"),
        asset_id=asset.id,
        space_id=asset.space_id,
        memory_scope_id=asset.memory_scope_id,
        thread_id=asset.thread_id,
        parser_profile="standard_local",
        parser_config_hash="profile_hash",
        source_sha256_hex=asset.sha256_hex,
        now=datetime(2026, 6, 19, tzinfo=UTC),
    )
