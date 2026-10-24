"""Compensation preserves a blob write failure even when cleanup also fails."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from itertools import count
from types import SimpleNamespace

import pytest
from infinity_context_core.application.use_cases.asset_extractions import RunAssetExtractionUseCase
from infinity_context_core.domain.assets import MemoryAsset, MemoryAssetId
from infinity_context_core.domain.entities import MemoryScopeId, SpaceId
from infinity_context_core.domain.extraction import AssetExtractionJob, AssetExtractionJobId
from infinity_context_core.ports.assets import StoredBlob
from infinity_context_core.ports.extraction import ExtractionLimits, ExtractionResult


class _SecondWriteFailureStorage:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self.events = events
        self.successful_keys: list[str] = []
        self.write_error = RuntimeError("second blob write failed")

    async def write_bytes(self, *, storage_key: str, content: bytes) -> StoredBlob:
        self.events.append(("write", storage_key))
        if self.successful_keys:
            raise self.write_error
        self.successful_keys.append(storage_key)
        return StoredBlob(storage_key=storage_key, byte_size=len(content))

    async def delete(self, *, storage_key: str) -> None:
        self.events.append(("delete", storage_key))
        raise RuntimeError("cleanup also failed")


class _ForbiddenMetadataUow:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self.events = events

    def __call__(self):
        self.events.append(("uow", "unexpected"))
        raise AssertionError("Metadata persistence must start only after all blob writes")


def test_second_blob_write_failure_cleans_only_successful_write_and_keeps_original_error() -> None:
    events: list[tuple[str, str]] = []
    storage = _SecondWriteFailureStorage(events)
    now = datetime(2026, 6, 18, tzinfo=UTC)
    sequence = count(1)
    asset = MemoryAsset.create(
        asset_id=MemoryAssetId("asset_1"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("scope_1"),
        filename="capture.txt",
        content_type="text/plain",
        byte_size=5,
        sha256_hex=sha256(b"asset").hexdigest(),
        storage_backend="local",
        storage_key="assets/asset_1.bin",
        now=now,
    )
    job = AssetExtractionJob.create(
        job_id=AssetExtractionJobId("extract_1"),
        asset_id=asset.id,
        space_id=asset.space_id,
        memory_scope_id=asset.memory_scope_id,
        parser_profile="standard_local",
        parser_config_hash="profile_hash",
        source_sha256_hex=asset.sha256_hex,
        now=now,
    )
    use_case = RunAssetExtractionUseCase(
        uow_factory=_ForbiddenMetadataUow(events),
        blob_storage=storage,
        detector=object(),
        extractor=object(),
        ingest_document=object(),
        clock=SimpleNamespace(now=lambda: now),
        ids=SimpleNamespace(new_id=lambda prefix: f"{prefix}_{next(sequence)}"),
        limits=ExtractionLimits(max_bytes=1_000_000),
    )

    with pytest.raises(RuntimeError, match="second blob write failed") as raised:
        asyncio.run(
            use_case._store_artifacts(  # noqa: SLF001 - blob compensation boundary.
                asset=asset,
                job=job,
                result=ExtractionResult(
                    status="succeeded",
                    normalized_content_type="text/plain",
                    title="capture.txt",
                    markdown="searchable evidence",
                    parser_name="test_parser",
                ),
                markdown="searchable evidence",
            )
        )

    assert raised.value is storage.write_error
    assert len(storage.successful_keys) == 1
    assert [operation for operation, _key in events] == ["write", "write", "delete"]
    assert events[0][1] == events[2][1] == storage.successful_keys[0]
    assert events[1][1] != events[2][1]
