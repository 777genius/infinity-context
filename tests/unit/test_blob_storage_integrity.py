import asyncio
import hashlib
from datetime import UTC, datetime

import pytest
from infinity_context_core.application.use_cases.blob_storage_integrity import (
    BlobStorageIntegrityAuditCommand,
    RunBlobStorageIntegrityAuditUseCase,
)
from infinity_context_core.domain.errors import MemoryNotFoundError, MemoryValidationError
from infinity_context_core.ports.assets import StoredBlob, StoredBlobObject, StoredBlobReference

NOW = datetime(2026, 6, 19, tzinfo=UTC)


class _BlobStorage:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = dict(blobs)
        self.stat_sizes: dict[str, int] = {}
        self.stat_errors: set[str] = set()
        self.read_errors: set[str] = set()
        self.reads: list[str] = []

    async def write_bytes(self, *, storage_key: str, content: bytes) -> StoredBlob:
        raise AssertionError("not used")

    async def read_bytes(self, *, storage_key: str) -> bytes:
        self.reads.append(storage_key)
        if storage_key in self.read_errors:
            raise RuntimeError("read outage")
        content = self.blobs.get(storage_key)
        if content is None:
            raise MemoryNotFoundError("missing")
        return content

    async def delete(self, *, storage_key: str) -> None:
        raise AssertionError("not used")

    async def stat_object(self, *, storage_key: str) -> StoredBlobObject:
        if storage_key in self.stat_errors:
            raise RuntimeError("stat outage")
        content = self.blobs.get(storage_key)
        if content is None:
            raise MemoryNotFoundError("missing")
        return StoredBlobObject(
            storage_key=storage_key,
            byte_size=self.stat_sizes.get(storage_key, len(content)),
            updated_at=NOW,
        )


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Assets:
    def __init__(self, refs: tuple[StoredBlobReference, ...]) -> None:
        self.refs = refs
        self.calls: list[tuple[str, str, int]] = []

    async def list_stored_blob_references(
        self,
        *,
        storage_backend: str,
        prefix: str,
        limit: int,
    ) -> list[StoredBlobReference]:
        self.calls.append((storage_backend, prefix, limit))
        return _filter_refs(self.refs, prefix=prefix)[:limit]


class _AssetExtractions:
    def __init__(self, refs: tuple[StoredBlobReference, ...]) -> None:
        self.refs = refs
        self.calls: list[tuple[str, str, int]] = []

    async def list_retained_artifact_blob_references(
        self,
        *,
        storage_backend: str,
        prefix: str,
        limit: int,
    ) -> list[StoredBlobReference]:
        self.calls.append((storage_backend, prefix, limit))
        return _filter_refs(self.refs, prefix=prefix)[:limit]


class _Uow:
    def __init__(self, assets: _Assets, asset_extractions: _AssetExtractions) -> None:
        self.assets = assets
        self.asset_extractions = asset_extractions

    async def __aenter__(self) -> "_Uow":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _UowFactory:
    def __init__(self, assets: _Assets, asset_extractions: _AssetExtractions) -> None:
        self.assets = assets
        self.asset_extractions = asset_extractions

    def __call__(self) -> _Uow:
        return _Uow(self.assets, self.asset_extractions)


def test_blob_storage_integrity_audit_detects_missing_and_corrupt_blobs() -> None:
    async def run() -> None:
        storage = _BlobStorage(
            {
                "space/scope/ok.txt": b"ok",
                "space/scope/size.txt": b"size",
                "space/scope/checksum.txt": b"altered!",
                "space/scope/large.bin": b"0123456789",
                "space/scope/read-error.txt": b"err",
                "space/scope/stat-error.txt": b"stat-error",
            }
        )
        storage.stat_sizes["space/scope/size.txt"] = 99
        storage.read_errors.add("space/scope/read-error.txt")
        storage.stat_errors.add("space/scope/stat-error.txt")
        refs = (
            _ref("asset", "asset_ok", "space/scope/ok.txt", b"ok"),
            _ref("asset", "asset_missing", "space/scope/missing.txt", b"missing"),
            _ref("asset", "asset_size", "space/scope/size.txt", b"size"),
            _ref("asset", "asset_checksum", "space/scope/checksum.txt", b"original"),
            _ref("asset", "asset_large", "space/scope/large.bin", b"0123456789"),
            _ref("asset", "asset_read", "space/scope/read-error.txt", b"err"),
            _ref("asset", "asset_stat", "space/scope/stat-error.txt", b"stat-error"),
        )

        result = await _use_case(storage=storage, asset_refs=refs).execute(
                BlobStorageIntegrityAuditCommand(
                    storage_backend="local",
                    prefix="space/scope",
                    max_blob_read_bytes=8,
                )
        )

        assert result.status == "degraded"
        assert result.scanned_count == 7
        assert result.ok_count == 1
        assert result.missing_count == 1
        assert result.byte_size_mismatch_count == 1
        assert result.checksum_mismatch_count == 1
        assert result.checksum_skipped_count == 1
        assert result.read_error_count == 1
        assert result.stat_error_count == 1
        assert {issue.reason for issue in result.issues} == {
            "missing_blob",
            "byte_size_mismatch",
            "checksum_mismatch",
            "checksum_skipped_too_large",
            "read_error",
            "stat_error",
        }
        assert "space/scope/ok.txt" in storage.reads
        assert "space/scope/large.bin" not in storage.reads
        assert all(not hasattr(issue, "storage_key") for issue in result.issues)
        assert {issue.checked_at for issue in result.issues} == {NOW}
        assert result.diagnostics["storage_keys_are_redacted"] is True

    asyncio.run(run())


def test_blob_storage_integrity_audit_respects_source_filters_and_budget() -> None:
    async def run() -> None:
        storage = _BlobStorage(
            {
                "space/scope/a.txt": b"a",
                "space/scope/artifact.md": b"artifact",
            }
        )
        assets = (_ref("asset", "asset_1", "space/scope/a.txt", b"a"),)
        artifacts = (
            _ref(
                "extraction_artifact",
                "artifact_1",
                "space/scope/artifact.md",
                b"artifact",
            ),
        )
        use_case = _use_case(storage=storage, asset_refs=assets, artifact_refs=artifacts)

        result = await use_case.execute(
            BlobStorageIntegrityAuditCommand(
                storage_backend="local",
                prefix="space/scope",
                include_assets=False,
                include_artifacts=True,
                max_references=1,
            )
        )

        assert result.status == "ok"
        assert result.scanned_count == 1
        assert use_case._uow_factory.assets.calls == []  # noqa: SLF001
        assert use_case._uow_factory.asset_extractions.calls == [("local", "space/scope", 1)]  # noqa: SLF001

    asyncio.run(run())


def test_blob_storage_integrity_audit_balances_asset_and_artifact_budget() -> None:
    async def run() -> None:
        storage = _BlobStorage(
            {
                "space/scope/a.txt": b"a",
                "space/scope/b.txt": b"b",
                "space/scope/artifact.md": b"artifact",
            }
        )
        assets = (
            _ref("asset", "asset_1", "space/scope/a.txt", b"a"),
            _ref("asset", "asset_2", "space/scope/b.txt", b"b"),
        )
        artifacts = (
            _ref(
                "extraction_artifact",
                "artifact_1",
                "space/scope/artifact.md",
                b"artifact",
            ),
        )
        use_case = _use_case(storage=storage, asset_refs=assets, artifact_refs=artifacts)

        result = await use_case.execute(
            BlobStorageIntegrityAuditCommand(
                storage_backend="local",
                prefix="space/scope",
                max_references=2,
            )
        )

        assert result.status == "ok"
        assert result.scanned_count == 2
        assert use_case._uow_factory.assets.calls == [("local", "space/scope", 1)]  # noqa: SLF001
        assert use_case._uow_factory.asset_extractions.calls == [("local", "space/scope", 1)]  # noqa: SLF001

    asyncio.run(run())


def test_blob_storage_integrity_audit_requires_at_least_one_source_type() -> None:
    async def run() -> None:
        with pytest.raises(MemoryValidationError):
            await _use_case(storage=_BlobStorage({}), asset_refs=()).execute(
                BlobStorageIntegrityAuditCommand(
                    storage_backend="local",
                    include_assets=False,
                    include_artifacts=False,
                )
            )

    asyncio.run(run())


def _use_case(
    *,
    storage: _BlobStorage,
    asset_refs: tuple[StoredBlobReference, ...],
    artifact_refs: tuple[StoredBlobReference, ...] = (),
) -> RunBlobStorageIntegrityAuditUseCase:
    return RunBlobStorageIntegrityAuditUseCase(
        uow_factory=_UowFactory(_Assets(asset_refs), _AssetExtractions(artifact_refs)),
        blob_storage=storage,
        clock=_Clock(),
    )


def _ref(
    source_type: str,
    source_id: str,
    storage_key: str,
    content: bytes,
) -> StoredBlobReference:
    return StoredBlobReference(
        source_type=source_type,
        source_id=source_id,
        storage_backend="local",
        storage_key=storage_key,
        sha256_hex=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
        created_at=NOW,
    )


def _filter_refs(
    refs: tuple[StoredBlobReference, ...],
    *,
    prefix: str,
) -> list[StoredBlobReference]:
    return [
        ref
        for ref in refs
        if not prefix or ref.storage_key == prefix or ref.storage_key.startswith(f"{prefix}/")
    ]
