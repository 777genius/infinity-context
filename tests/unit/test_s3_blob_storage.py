import asyncio
from datetime import UTC, datetime

import pytest
from infinity_context_adapters.s3_blob import S3BlobStorage
from infinity_context_core.domain.errors import MemoryNotFoundError, MemoryValidationError
from infinity_context_server import composition
from infinity_context_server.config import DeployProfile, Settings


class _FakeBody:
    def __init__(self, content: bytes) -> None:
        self._content = content
        self.closed = False

    def read(self) -> bytes:
        return self._content

    def close(self) -> None:
        self.closed = True


class _FakeS3NotFound(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.last_modified: dict[tuple[str, str], datetime] = {}
        self.deleted: list[tuple[str, str]] = []
        self.list_requests: list[dict[str, object]] = []

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        self.objects[(Bucket, Key)] = Body
        self.last_modified[(Bucket, Key)] = datetime(2026, 6, 19, tzinfo=UTC)

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        content = self.objects.get((Bucket, Key))
        if content is None:
            raise _FakeS3NotFound
        return {"Body": _FakeBody(content)}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        content = self.objects.get((Bucket, Key))
        if content is None:
            raise _FakeS3NotFound
        return {
            "ContentLength": len(content),
            "LastModified": self.last_modified[(Bucket, Key)],
        }

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.deleted.append((Bucket, Key))
        self.objects.pop((Bucket, Key), None)
        self.last_modified.pop((Bucket, Key), None)

    def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
        self.list_requests.append(dict(kwargs))
        bucket = str(kwargs["Bucket"])
        prefix = str(kwargs.get("Prefix") or "")
        max_keys = int(kwargs.get("MaxKeys") or 1000)
        continuation_token = kwargs.get("ContinuationToken")
        keys = sorted(key for item_bucket, key in self.objects if item_bucket == bucket)
        if prefix:
            keys = [key for key in keys if key.startswith(prefix)]
        if continuation_token:
            keys = [key for key in keys if key > str(continuation_token)]
        page_keys = keys[:max_keys]
        contents = [
            {
                "Key": key,
                "Size": len(self.objects[(bucket, key)]),
                "LastModified": self.last_modified[(bucket, key)],
            }
            for key in page_keys
        ]
        return {
            "Contents": contents,
            "NextContinuationToken": page_keys[-1] if len(keys) > len(page_keys) else None,
        }


def test_s3_blob_storage_round_trips_with_prefix() -> None:
    async def run() -> None:
        client = _FakeS3Client()
        storage = S3BlobStorage(bucket="memory-assets", prefix="team-a/assets", client=client)

        stored = await storage.write_bytes(
            storage_key="space/scope/aa/blob.txt",
            content=b"hello",
        )
        content = await storage.read_bytes(storage_key=stored.storage_key)
        await storage.delete(storage_key=stored.storage_key)

        assert stored.byte_size == 5
        assert content == b"hello"
        assert client.objects == {}
        assert client.deleted == [("memory-assets", "team-a/assets/space/scope/aa/blob.txt")]

    asyncio.run(run())


def test_s3_blob_storage_missing_object_raises_not_found() -> None:
    async def run() -> None:
        storage = S3BlobStorage(bucket="memory-assets", client=_FakeS3Client())

        with pytest.raises(MemoryNotFoundError):
            await storage.read_bytes(storage_key="space/scope/missing.txt")

    asyncio.run(run())


def test_s3_blob_storage_lists_logical_objects_with_configured_prefix() -> None:
    async def run() -> None:
        client = _FakeS3Client()
        storage = S3BlobStorage(bucket="memory-assets", prefix="tenant-a/assets", client=client)
        await storage.write_bytes(storage_key="space/scope/a.txt", content=b"a")
        await storage.write_bytes(storage_key="space/scope/b.txt", content=b"bb")
        await storage.write_bytes(storage_key="space/other/c.txt", content=b"ccc")

        object_stat = await storage.stat_object(storage_key="space/scope/b.txt")
        first_page = await storage.list_objects(prefix="space/scope", limit=1)
        second_page = await storage.list_objects(
            prefix="space/scope",
            limit=10,
            cursor=first_page.next_cursor,
        )

        assert object_stat.storage_key == "space/scope/b.txt"
        assert object_stat.byte_size == 2
        assert object_stat.updated_at == datetime(2026, 6, 19, tzinfo=UTC)
        assert [item.storage_key for item in first_page.objects] == ["space/scope/a.txt"]
        assert first_page.objects[0].byte_size == 1
        assert first_page.objects[0].updated_at == datetime(2026, 6, 19, tzinfo=UTC)
        assert first_page.next_cursor == "tenant-a/assets/space/scope/a.txt"
        assert [item.storage_key for item in second_page.objects] == ["space/scope/b.txt"]
        assert second_page.next_cursor is None
        assert client.list_requests[0]["Prefix"] == "tenant-a/assets/space/scope"
        assert client.list_requests[1]["ContinuationToken"] == first_page.next_cursor

    asyncio.run(run())


@pytest.mark.parametrize(
    "storage_key",
    ["", "/absolute/key", "space/../secret", "space//secret", "space/\x00secret"],
)
def test_s3_blob_storage_rejects_unsafe_storage_keys(storage_key: str) -> None:
    async def run() -> None:
        storage = S3BlobStorage(bucket="memory-assets", client=_FakeS3Client())

        with pytest.raises(MemoryValidationError):
            await storage.write_bytes(storage_key=storage_key, content=b"blocked")

    asyncio.run(run())


def test_s3_blob_storage_rejects_unsafe_prefix() -> None:
    with pytest.raises(MemoryValidationError):
        S3BlobStorage(bucket="memory-assets", prefix="team-a/../assets", client=_FakeS3Client())


def test_container_wires_s3_storage_backend(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    created: dict[str, object] = {}

    class _FakeStorage:
        def __init__(self, **kwargs: object) -> None:
            created.update(kwargs)

        async def write_bytes(self, *, storage_key: str, content: bytes):  # pragma: no cover
            raise AssertionError("not used")

        async def read_bytes(self, *, storage_key: str) -> bytes:  # pragma: no cover
            raise AssertionError("not used")

        async def delete(self, *, storage_key: str) -> None:  # pragma: no cover
            raise AssertionError("not used")

    monkeypatch.setattr(composition, "S3BlobStorage", _FakeStorage)

    container = composition.build_container(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 's3-composition.db'}",
            asset_storage_backend="s3",
            asset_storage_s3_bucket="memory-assets",
            asset_storage_s3_prefix="tenant-a",
            asset_storage_s3_endpoint_url="https://s3.example.test",
            asset_storage_s3_region="us-east-1",
            asset_storage_s3_force_path_style=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    try:
        assert created["bucket"] == "memory-assets"
        assert created["prefix"] == "tenant-a"
        assert created["endpoint_url"] == "https://s3.example.test"
        assert created["region_name"] == "us-east-1"
        assert created["force_path_style"] is True
        assert container.create_asset._storage_backend == "s3"
        assert container.run_asset_extraction._artifact_storage_backend == "s3"
    finally:
        asyncio.run(container.aclose())
