import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Any

from memo_stack_core.application.dto import CreateAssetCommand
from memo_stack_core.application.use_cases.assets import CreateAssetUseCase
from memo_stack_core.domain.assets import MemoryAsset, MemoryAssetId
from memo_stack_core.domain.entities import MemoryScopeId, SpaceId, ThreadId
from memo_stack_core.domain.errors import MemoryConflictError
from memo_stack_core.ports.assets import StoredBlob

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

    async def write_bytes(self, *, storage_key: str, content: bytes) -> StoredBlob:
        self.writes.append((storage_key, content))
        return StoredBlob(storage_key=storage_key, byte_size=len(content))

    async def read_bytes(self, *, storage_key: str) -> bytes:
        raise AssertionError(f"unexpected read for {storage_key}")

    async def delete(self, *, storage_key: str) -> None:
        self.deletes.append(storage_key)


class FakeAssetRepository:
    def __init__(self) -> None:
        self.lookup_results: list[MemoryAsset | None] = []
        self.storage_refs: set[str] = set()
        self.created: list[MemoryAsset] = []
        self.fail_create = False

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

    async def has_stored_with_storage_key(
        self,
        *,
        storage_key: str,
        excluding_asset_id: str | None = None,
    ) -> bool:
        return storage_key in self.storage_refs

    async def create(self, asset: MemoryAsset) -> MemoryAsset:
        if self.fail_create:
            raise MemoryConflictError("asset conflict")
        self.created.append(asset)
        self.storage_refs.add(asset.storage_key)
        return asset


class FakeUnitOfWork:
    def __init__(self, assets: FakeAssetRepository) -> None:
        self.assets = assets
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

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(self.assets)


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
        assert result.asset == existing
        assert storage.writes[0][0] == expected_key
        assert storage.deletes == []

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


def _create_use_case(
    *,
    assets: FakeAssetRepository,
    storage: FakeBlobStorage,
) -> CreateAssetUseCase:
    return CreateAssetUseCase(
        uow_factory=FakeUnitOfWorkFactory(assets),
        clock=FakeClock(),
        ids=FakeIds(),
        blob_storage=storage,
    )


def _command(*, filename: str, content: bytes) -> CreateAssetCommand:
    return CreateAssetCommand(
        space_id=SPACE_ID,
        memory_scope_id=MEMORY_SCOPE_ID,
        thread_id=THREAD_ID,
        filename=filename,
        content_type="text/plain",
        content=content,
    )


def _asset(
    *,
    asset_id: str,
    filename: str,
    sha256_hex: str,
    storage_key: str,
) -> MemoryAsset:
    return MemoryAsset.create(
        asset_id=MemoryAssetId(asset_id),
        space_id=SPACE_ID,
        memory_scope_id=MEMORY_SCOPE_ID,
        thread_id=THREAD_ID,
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
