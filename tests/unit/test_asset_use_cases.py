import asyncio
import hashlib
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from infinity_context_core.application.dto import CreateAssetCommand
from infinity_context_core.application.use_cases.assets import CreateAssetUseCase
from infinity_context_core.domain.assets import (
    MemoryAsset,
    MemoryAssetId,
    MemoryContextLinkSuggestion,
)
from infinity_context_core.domain.entities import MemoryScopeId, SpaceId, ThreadId
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryIngressLimitError,
    MemoryQuotaExceededError,
)
from infinity_context_core.ports.assets import StoredBlob

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SPACE_ID = SpaceId("space_asset_tests")
MEMORY_SCOPE_ID = MemoryScopeId("scope_asset_tests")
THREAD_ID = ThreadId("thread_asset_tests")


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeIds:
    def __init__(self) -> None:
        self._count = 0

    def new_id(self, prefix: str) -> str:
        self._count += 1
        return f"{prefix}_{self._count}"


class FakeBlobStorage:
    def __init__(self) -> None:
        self.writes: list[tuple[str, bytes]] = []
        self.deletes: list[str] = []
        self.fail_delete = False

    async def write_bytes(self, *, storage_key: str, content: bytes) -> StoredBlob:
        self.writes.append((storage_key, content))
        return StoredBlob(storage_key=storage_key, byte_size=len(content))

    async def read_bytes(self, *, storage_key: str) -> bytes:
        raise AssertionError(f"unexpected read for {storage_key}")

    async def delete(self, *, storage_key: str) -> None:
        self.deletes.append(storage_key)
        if self.fail_delete:
            raise RuntimeError("blob delete failed")


class FakeAssetRepository:
    def __init__(self) -> None:
        self.lookup_results: list[MemoryAsset | None] = []
        self.scope_lookup_results: list[MemoryAsset | None] = []
        self.scope_lookup_calls = 0
        self.scope_lookup_storage_backends: list[str] = []
        self.storage_refs: set[str] = set()
        self.stored_blob_bytes = 0
        self.storage_usage_calls = 0
        self.created: list[MemoryAsset] = []
        self.fail_create = False
        self.create_error: Exception | None = None

    async def find_stored_by_sha256(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        sha256_hex: str,
    ) -> MemoryAsset | None:
        if self.lookup_results:
            return self.lookup_results.pop(0)
        return None

    async def find_any_stored_by_sha256(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        storage_backend: str,
        sha256_hex: str,
    ) -> MemoryAsset | None:
        self.scope_lookup_calls += 1
        self.scope_lookup_storage_backends.append(storage_backend)
        if self.scope_lookup_results:
            return self.scope_lookup_results.pop(0)
        return None

    async def has_stored_with_storage_key(
        self,
        *,
        storage_key: str,
        excluding_asset_id: str | None = None,
    ) -> bool:
        return storage_key in self.storage_refs

    async def create(self, asset: MemoryAsset) -> MemoryAsset:
        if self.create_error is not None:
            raise self.create_error
        if self.fail_create:
            raise MemoryConflictError("asset conflict")
        self.created.append(asset)
        self.storage_refs.add(asset.storage_key)
        self.stored_blob_bytes += asset.byte_size
        return asset

    async def sum_stored_blob_bytes(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        storage_backend: str,
    ) -> int:
        self.storage_usage_calls += 1
        return self.stored_blob_bytes


class FakeContextLinksRepository:
    def __init__(self) -> None:
        self.active_links: dict[tuple[str, str, str, str, str], object] = {}
        self.find_active_calls: list[tuple[str, str, str, str, str]] = []

    async def find_active(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        relation_type: str,
    ) -> object | None:
        key = (source_type, source_id, target_type, target_id, relation_type)
        self.find_active_calls.append(key)
        return self.active_links.get(key)


class FakeContextLinkSuggestionsRepository:
    def __init__(self) -> None:
        self.latest: dict[tuple[str, str, str, str, str], MemoryContextLinkSuggestion] = {}
        self.created: list[MemoryContextLinkSuggestion] = []

    async def find_latest_for_pair(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        relation_type: str,
    ) -> MemoryContextLinkSuggestion | None:
        return self.latest.get((source_type, source_id, target_type, target_id, relation_type))

    async def create(
        self,
        suggestion: MemoryContextLinkSuggestion,
    ) -> MemoryContextLinkSuggestion:
        self.created.append(suggestion)
        return suggestion


class FakeUnitOfWork:
    def __init__(
        self,
        assets: FakeAssetRepository,
        context_links: FakeContextLinksRepository,
        context_link_suggestions: FakeContextLinkSuggestionsRepository,
    ) -> None:
        self.assets = assets
        self.context_links = context_links
        self.context_link_suggestions = context_link_suggestions
        self.commits = 0

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


class FakeUnitOfWorkFactory:
    def __init__(self, assets: FakeAssetRepository) -> None:
        self.assets = assets
        self.context_links = FakeContextLinksRepository()
        self.context_link_suggestions = FakeContextLinkSuggestionsRepository()

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(
            self.assets,
            self.context_links,
            self.context_link_suggestions,
        )


def test_create_asset_cleans_unreferenced_blob_on_late_duplicate() -> None:
    async def run() -> None:
        content = b"same content"
        digest = hashlib.sha256(content).hexdigest()
        existing = _asset(
            asset_id="asset_existing",
            filename="existing.txt",
            sha256_hex=digest,
            storage_key="space_asset_tests/scope_asset_tests/existing.txt",
        )
        assets = FakeAssetRepository()
        assets.lookup_results = [None, existing]
        assets.storage_refs.add(existing.storage_key)
        storage = FakeBlobStorage()

        result = await _create_use_case(assets=assets, storage=storage).execute(
            _command(filename="new-name.txt", content=content)
        )

        written_key = storage.writes[0][0]
        assert result.duplicate is True
        assert result.deduplication is not None
        assert result.deduplication.status == "late_exact_asset_match"
        assert result.deduplication.reason_code == "asset_dedup.late_exact_asset_match"
        assert result.deduplication.scope == "thread"
        assert result.deduplication.duplicate_of_asset_id == str(existing.id)
        assert result.deduplication.blob_written is True
        assert result.deduplication.temporary_blob_cleaned_up is True
        assert result.asset == existing
        assert assets.created == []
        assert storage.deletes == [written_key]

    asyncio.run(run())


def test_create_asset_keeps_late_duplicate_blob_when_storage_key_is_referenced() -> None:
    async def run() -> None:
        content = b"same content"
        digest = hashlib.sha256(content).hexdigest()
        existing = _asset(
            asset_id="asset_existing",
            filename="existing.txt",
            sha256_hex=digest,
            storage_key="space_asset_tests/scope_asset_tests/existing.txt",
        )
        assets = FakeAssetRepository()
        assets.lookup_results = [None, existing]
        storage = FakeBlobStorage()

        use_case = _create_use_case(assets=assets, storage=storage)
        command = _command(filename="shared-name.txt", content=content)
        expected_key = _expected_storage_key(filename=command.filename, content=content)
        assets.storage_refs.update({existing.storage_key, expected_key})

        result = await use_case.execute(command)

        assert result.duplicate is True
        assert result.deduplication is not None
        assert result.deduplication.status == "late_exact_asset_match"
        assert result.deduplication.temporary_blob_cleaned_up is False
        assert result.asset == existing
        assert storage.writes[0][0] == expected_key
        assert storage.deletes == []

    asyncio.run(run())


def test_create_asset_reuses_scope_blob_for_different_thread_duplicate() -> None:
    async def run() -> None:
        content = b"same content in another thread"
        digest = hashlib.sha256(content).hexdigest()
        reusable = _asset(
            asset_id="asset_reusable",
            filename="original.txt",
            sha256_hex=digest,
            storage_key="space_asset_tests/scope_asset_tests/original.txt",
            thread_id=ThreadId("thread_original"),
        )
        assets = FakeAssetRepository()
        assets.scope_lookup_results = [reusable]
        assets.storage_refs.add(reusable.storage_key)
        storage = FakeBlobStorage()

        result = await _create_use_case(assets=assets, storage=storage).execute(
            _command(filename="copy.txt", content=content)
        )

        assert result.duplicate is True
        assert result.deduplication is not None
        assert result.deduplication.status == "scope_blob_reused"
        assert result.deduplication.reason_code == "asset_dedup.scope_blob_reused"
        assert result.deduplication.scope == "memory_scope"
        assert result.deduplication.duplicate_of_asset_id == str(reusable.id)
        assert result.deduplication.suggestion_id == "ctxlinksug_2"
        assert result.deduplication.suggestion_status == "pending"
        assert result.deduplication.storage_key_reused is True
        assert result.deduplication.blob_written is False
        assert result.asset.id != reusable.id
        assert result.asset.thread_id == THREAD_ID
        assert result.asset.storage_key == reusable.storage_key
        assert result.asset.metadata["asset_blob_deduplicated"] is True
        assert result.asset.metadata["asset_blob_duplicate_of_asset_id"] == str(reusable.id)
        assert result.asset.metadata["asset_blob_dedupe_scope"] == "memory_scope"
        assert assets.scope_lookup_storage_backends == ["local"]
        assert assets.created == [result.asset]
        assert storage.writes == []
        assert storage.deletes == []

    asyncio.run(run())


def test_create_asset_same_thread_duplicate_returns_existing_without_scope_lookup() -> None:
    async def run() -> None:
        content = b"already uploaded here"
        digest = hashlib.sha256(content).hexdigest()
        existing = _asset(
            asset_id="asset_existing",
            filename="existing.txt",
            sha256_hex=digest,
            storage_key="space_asset_tests/scope_asset_tests/existing.txt",
        )
        assets = FakeAssetRepository()
        assets.lookup_results = [existing]
        storage = FakeBlobStorage()

        result = await _create_use_case(assets=assets, storage=storage).execute(
            _command(filename="same-thread.txt", content=content)
        )

        assert result.duplicate is True
        assert result.deduplication is not None
        assert result.deduplication.status == "exact_asset_match"
        assert result.deduplication.reason_code == "asset_dedup.exact_asset_match"
        assert result.deduplication.scope == "thread"
        assert result.deduplication.duplicate_of_asset_id == str(existing.id)
        assert result.deduplication.blob_written is False
        assert result.asset == existing
        assert assets.scope_lookup_calls == 0
        assert assets.created == []
        assert storage.writes == []

    asyncio.run(run())


def test_create_asset_rejects_scope_storage_quota_before_blob_write() -> None:
    async def run() -> None:
        assets = FakeAssetRepository()
        assets.stored_blob_bytes = 8
        storage = FakeBlobStorage()

        try:
            await _create_use_case(
                assets=assets,
                storage=storage,
                max_storage_bytes_per_memory_scope=10,
            ).execute(_command(filename="over-quota.txt", content=b"123"))
        except MemoryQuotaExceededError as exc:
            assert "storage quota" in str(exc)
        else:
            raise AssertionError("expected MemoryQuotaExceededError")

        assert assets.storage_usage_calls == 1
        assert storage.writes == []
        assert assets.created == []

    asyncio.run(run())


def test_create_asset_storage_quota_allows_scope_blob_reuse() -> None:
    async def run() -> None:
        content = b"reuse does not consume new physical bytes"
        digest = hashlib.sha256(content).hexdigest()
        reusable = _asset(
            asset_id="asset_reusable",
            filename="original.txt",
            sha256_hex=digest,
            storage_key="space_asset_tests/scope_asset_tests/original.txt",
            thread_id=ThreadId("thread_original"),
        )
        assets = FakeAssetRepository()
        assets.stored_blob_bytes = 10
        assets.scope_lookup_results = [reusable]
        assets.storage_refs.add(reusable.storage_key)
        storage = FakeBlobStorage()

        result = await _create_use_case(
            assets=assets,
            storage=storage,
            max_storage_bytes_per_memory_scope=10,
        ).execute(_command(filename="copy.txt", content=content))

        assert result.deduplication is not None
        assert result.deduplication.status == "scope_blob_reused"
        assert assets.storage_usage_calls == 0
        assert storage.writes == []

    asyncio.run(run())


def test_create_asset_storage_quota_allows_same_thread_duplicate() -> None:
    async def run() -> None:
        content = b"same content"
        digest = hashlib.sha256(content).hexdigest()
        existing = _asset(
            asset_id="asset_existing",
            filename="existing.txt",
            sha256_hex=digest,
            storage_key="space_asset_tests/scope_asset_tests/existing.txt",
        )
        assets = FakeAssetRepository()
        assets.stored_blob_bytes = 10
        assets.lookup_results = [existing]
        storage = FakeBlobStorage()

        result = await _create_use_case(
            assets=assets,
            storage=storage,
            max_storage_bytes_per_memory_scope=10,
        ).execute(_command(filename="existing.txt", content=content))

        assert result.deduplication is not None
        assert result.deduplication.status == "exact_asset_match"
        assert assets.storage_usage_calls == 0
        assert storage.writes == []

    asyncio.run(run())


def test_create_asset_conflict_cleanup_keeps_referenced_storage_key() -> None:
    async def run() -> None:
        content = b"conflicting content"
        command = _command(filename="shared-conflict.txt", content=content)
        expected_key = _expected_storage_key(filename=command.filename, content=content)
        assets = FakeAssetRepository()
        assets.lookup_results = [None, None]
        assets.storage_refs.add(expected_key)
        assets.fail_create = True
        storage = FakeBlobStorage()

        try:
            await _create_use_case(assets=assets, storage=storage).execute(command)
        except MemoryConflictError:
            pass
        else:
            raise AssertionError("expected MemoryConflictError")

        assert storage.writes[0][0] == expected_key
        assert storage.deletes == []

    asyncio.run(run())


def test_create_asset_unexpected_failure_cleans_unreferenced_blob() -> None:
    async def run() -> None:
        content = b"database outage after blob write"
        command = _command(filename="late-failure.txt", content=content)
        expected_key = _expected_storage_key(filename=command.filename, content=content)
        assets = FakeAssetRepository()
        assets.lookup_results = [None, None]
        assets.create_error = RuntimeError("database create failed")
        storage = FakeBlobStorage()

        try:
            await _create_use_case(assets=assets, storage=storage).execute(command)
        except RuntimeError as exc:
            assert str(exc) == "database create failed"
        else:
            raise AssertionError("expected RuntimeError")

        assert storage.writes[0][0] == expected_key
        assert storage.deletes == [expected_key]

    asyncio.run(run())


def test_create_asset_cleanup_failure_preserves_original_error() -> None:
    async def run() -> None:
        content = b"cleanup can fail but must not hide root cause"
        command = _command(filename="cleanup-failure.txt", content=content)
        expected_key = _expected_storage_key(filename=command.filename, content=content)
        assets = FakeAssetRepository()
        assets.lookup_results = [None, None]
        assets.create_error = RuntimeError("database create failed")
        storage = FakeBlobStorage()
        storage.fail_delete = True

        try:
            await _create_use_case(assets=assets, storage=storage).execute(command)
        except RuntimeError as exc:
            assert str(exc) == "database create failed"
        else:
            raise AssertionError("expected RuntimeError")

        assert storage.writes[0][0] == expected_key
        assert storage.deletes == [expected_key]

    asyncio.run(run())


def test_create_asset_sanitizes_user_metadata_and_preserves_upload_policy() -> None:
    async def run() -> None:
        assets = FakeAssetRepository()
        storage = FakeBlobStorage()

        result = await _create_use_case(assets=assets, storage=storage).execute(
            _command(
                filename="note.txt",
                content=b"plain text",
                metadata={
                    "secret_token": "should not persist",
                    "nested": {"api_key": "nope", "safe": "ok"},
                    "upload_policy_version": "user override",
                    "huge": "x" * 800,
                },
            )
        )

        assert result.duplicate is False
        assert result.deduplication is not None
        assert result.deduplication.status == "new_blob_stored"
        assert result.deduplication.reason_code == "asset_dedup.new_blob_stored"
        assert result.deduplication.storage_key_reused is False
        assert result.deduplication.blob_written is True
        metadata = assets.created[0].metadata
        assert "secret_token" not in metadata
        assert metadata["nested"] == {"safe": "ok"}
        assert metadata["huge"] == "x" * 500
        assert metadata["upload_policy_version"] == "asset-upload-policy-v1"
        assert metadata["upload_magic_content_type"] == "text/plain"

    asyncio.run(run())


def test_create_asset_rejects_archive_bomb_before_blob_write() -> None:
    async def run() -> None:
        assets = FakeAssetRepository()
        storage = FakeBlobStorage()

        try:
            await _create_use_case(assets=assets, storage=storage).execute(
                _command(
                    filename="payload.zip",
                    content=_zip_bytes({"huge.txt": b"0" * (2 * 1024 * 1024)}),
                )
            )
        except MemoryIngressLimitError as exc:
            assert "compression ratio" in str(exc)
        else:
            raise AssertionError("expected MemoryIngressLimitError")

        assert storage.writes == []
        assert assets.created == []

    asyncio.run(run())


def test_create_asset_rejects_archive_single_large_member_before_blob_write() -> None:
    async def run() -> None:
        assets = FakeAssetRepository()
        storage = FakeBlobStorage()

        try:
            await _create_use_case(
                assets=assets,
                storage=storage,
                max_archive_single_entry_bytes=512,
                max_archive_uncompressed_bytes=10_000,
                max_archive_compression_ratio=10_000,
            ).execute(
                _command(
                    filename="payload.zip",
                    content=_zip_bytes(
                        {
                            "large.bin": b"0" * 900,
                            "small.bin": b"1",
                        }
                    ),
                )
            )
        except MemoryIngressLimitError as exc:
            assert "entry exceeds configured size limit" in str(exc)
        else:
            raise AssertionError("expected MemoryIngressLimitError")

        assert storage.writes == []
        assert assets.created == []

    asyncio.run(run())


def test_create_asset_rejects_image_pixel_bomb_before_blob_write() -> None:
    async def run() -> None:
        assets = FakeAssetRepository()
        storage = FakeBlobStorage()

        try:
            await _create_use_case(assets=assets, storage=storage).execute(
                _command(
                    filename="huge-screenshot.png",
                    content_type="image/png",
                    content=_png_bytes(width=100_000, height=100_000),
                )
            )
        except MemoryIngressLimitError as exc:
            assert "pixel count" in str(exc)
        else:
            raise AssertionError("expected MemoryIngressLimitError")

        assert storage.writes == []
        assert assets.created == []

    asyncio.run(run())


def _create_use_case(
    *,
    assets: FakeAssetRepository,
    storage: FakeBlobStorage,
    max_archive_single_entry_bytes: int = 100 * 1024 * 1024,
    max_archive_uncompressed_bytes: int = 250 * 1024 * 1024,
    max_archive_compression_ratio: int = 100,
    max_storage_bytes_per_memory_scope: int = 0,
) -> CreateAssetUseCase:
    return CreateAssetUseCase(
        uow_factory=FakeUnitOfWorkFactory(assets),
        clock=FakeClock(),
        ids=FakeIds(),
        blob_storage=storage,
        max_archive_single_entry_bytes=max_archive_single_entry_bytes,
        max_archive_uncompressed_bytes=max_archive_uncompressed_bytes,
        max_archive_compression_ratio=max_archive_compression_ratio,
        max_storage_bytes_per_memory_scope=max_storage_bytes_per_memory_scope,
    )


def _command(
    *,
    filename: str,
    content: bytes,
    content_type: str = "text/plain",
    metadata: dict[str, object] | None = None,
) -> CreateAssetCommand:
    return CreateAssetCommand(
        space_id=SPACE_ID,
        memory_scope_id=MEMORY_SCOPE_ID,
        thread_id=THREAD_ID,
        filename=filename,
        content_type=content_type,
        content=content,
        metadata=metadata,
    )


def _asset(
    *,
    asset_id: str,
    filename: str,
    sha256_hex: str,
    storage_key: str,
    thread_id: ThreadId | None = THREAD_ID,
) -> MemoryAsset:
    return MemoryAsset.create(
        asset_id=MemoryAssetId(asset_id),
        space_id=SPACE_ID,
        memory_scope_id=MEMORY_SCOPE_ID,
        thread_id=thread_id,
        filename=filename,
        content_type="text/plain",
        byte_size=12,
        sha256_hex=sha256_hex,
        storage_backend="local",
        storage_key=storage_key,
        now=NOW,
    )


def _expected_storage_key(*, filename: str, content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    return f"{SPACE_ID}/{MEMORY_SCOPE_ID}/{digest[:2]}/{digest}/{filename}"


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _png_bytes(*, width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\r"
        b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
