"""Replaceable Qdrant projection targets for canonical Retrieval profiles."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from infinity_context_core.features.context_building.public import (
    CanonicalProjectionItem,
    ExactVersionDeletionProof,
    ProfileCollectionDeleteAuthorization,
    ProjectedGenerationObservation,
    RetrievalProfileIdentity,
    RuntimeFenceOwner,
)
from infinity_context_core.ports.adapters import EmbeddingPort, VectorUpsertItem

from infinity_context_adapters.qdrant.vector_adapter import QdrantVectorMemoryAdapter


@dataclass(slots=True)
class QdrantRetrievalProfileProjection:
    url: str
    api_key: str | None
    vector_size: int
    embedder: EmbeddingPort
    mutation_registry: object | None = None
    runtime_owner: RuntimeFenceOwner = field(
        default_factory=lambda: RuntimeFenceOwner.unrecoverable_current(
            instance_id=f"retrieval-runtime-{uuid4().hex}",
            generation=f"generation-{uuid4().hex}",
        )
    )
    _adapters: dict[str, QdrantVectorMemoryAdapter] = field(default_factory=dict)

    def _adapter(self, identity: RetrievalProfileIdentity) -> QdrantVectorMemoryAdapter:
        existing = self._adapters.get(identity.profile_id)
        if existing is not None:
            return existing
        adapter = QdrantVectorMemoryAdapter(
            url=self.url,
            api_key=self.api_key,
            collection_name=identity.collection_name,
            vector_size=self.vector_size,
            projection_version="document-retrieval-projection.v1",
            index_profile_digest=identity.profile_digest,
            index_generation=identity.generation,
        )
        self._adapters[identity.profile_id] = adapter
        return adapter

    def adapter_for(self, identity: RetrievalProfileIdentity) -> QdrantVectorMemoryAdapter:
        return self._adapter(identity)

    async def prepare_profile(self, identity: RetrievalProfileIdentity) -> None:
        adapter = self._adapter(identity)
        client = None
        try:
            async with self._mutation(identity) as mutation:
                async with asyncio.timeout(50):
                    client, models = await adapter._client()
                    await adapter._ensure_collection(client, models)
                mutation.complete()
        except Exception as exc:
            raise RuntimeError("retrieval_profile_qdrant_prepare_failed") from exc
        finally:
            if client is not None:
                close = getattr(client, "close", None)
                if close is not None:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result

    async def upsert_profile(
        self,
        identity: RetrievalProfileIdentity,
        items: tuple[CanonicalProjectionItem, ...],
    ) -> None:
        if not items:
            return
        embedded = await self.embedder.embed_texts(tuple(item.text for item in items))
        if embedded.status.value != "ok" or len(embedded.vectors) != len(items):
            raise RuntimeError("retrieval_profile_embedding_count_mismatch")
        writes = tuple(
            VectorUpsertItem(
                chunk_id=item.canonical_identity,
                space_id=item.space_id,
                memory_scope_id=item.memory_scope_id,
                thread_id=item.thread_id,
                text=item.text,
                vector=vector,
                projection_version="document-retrieval-projection.v1",
                metadata=dict(item.vector_metadata),
            )
            for item, vector in zip(items, embedded.vectors, strict=True)
        )
        async with self._mutation(identity) as mutation:
            async with asyncio.timeout(50):
                result = await self._adapter(identity).upsert_chunks(writes)
            if result.status.value != "ok":
                raise RuntimeError("retrieval_profile_qdrant_upsert_failed")
            mutation.complete()

    async def delete_profile_if_version(
        self,
        identity: RetrievalProfileIdentity,
        canonical_ids: tuple[str, ...],
        *,
        canonical_version: int,
    ) -> ExactVersionDeletionProof:
        async with self._mutation(identity) as mutation:
            async with asyncio.timeout(50):
                result = await self._adapter(identity).delete_chunks_if_version(
                    canonical_ids, canonical_version=canonical_version
                )
            if result.status.value != "ok":
                raise RuntimeError("retrieval_profile_qdrant_delete_failed")
            remaining = await self._adapter(identity).observe_chunk_versions(canonical_ids)
            mutation.complete()
        return ExactVersionDeletionProof(canonical_ids, canonical_version, remaining)

    async def observe_profile_generation(
        self,
        identity: RetrievalProfileIdentity,
        canonical_id: str,
    ) -> ProjectedGenerationObservation:
        """Observe one point without opening a mutation epoch."""

        try:
            async with asyncio.timeout(50):
                versions = await self._adapter(identity).observe_chunk_versions((canonical_id,))
        except Exception as exc:
            raise RuntimeError("retrieval_profile_qdrant_observation_failed") from exc
        if len(versions) != 1:
            raise RuntimeError("retrieval_profile_qdrant_observation_invalid")
        return ProjectedGenerationObservation(canonical_id, versions[0])

    async def attestation(self, identity: RetrievalProfileIdentity) -> tuple[int, str]:
        return await self._adapter(identity).locator_profile_attestation()

    async def reconcile_provider_mutation(
        self,
        identity: RetrievalProfileIdentity,
        *,
        receipt_id: str,
        maintenance_generation: int,
        evidence_epoch: int,
        operation_id: str,
        owner_instance_id: str,
        owner_generation: str,
        mutation_epoch: int,
        stale_deadline: datetime,
        observed_at: datetime,
    ) -> str:
        """Read Qdrant and persist its exact maintenance-bound observation receipt."""

        if self.mutation_registry is None:
            raise RuntimeError("retrieval_profile_provider_fence_unconfigured")
        adapter = self._adapter(identity)
        client = None
        try:
            client, _ = await adapter._client()
            present = bool(await client.collection_exists(identity.collection_name))
        finally:
            if client is not None:
                close = getattr(client, "close", None)
                if close is not None:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
        if present:
            count, digest = await self.attestation(identity)
        else:
            count, digest = 0, hashlib.sha256(b"").hexdigest()
        return await self.mutation_registry._record_provider_reconciliation_observation(
            receipt_id=receipt_id,
            profile_id=identity.profile_id,
            profile_generation=identity.generation,
            collection_name=identity.collection_name,
            maintenance_generation=maintenance_generation,
            evidence_epoch=evidence_epoch,
            operation_id=operation_id,
            owner_instance_id=owner_instance_id,
            owner_generation=owner_generation,
            mutation_epoch=mutation_epoch,
            stale_deadline=stale_deadline,
            observed_count=count,
            observed_digest=digest,
            provider_state="present" if present else "absent",
            observed_at=observed_at,
        )

    async def attestation_page(
        self,
        identity: RetrievalProfileIdentity,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[tuple[str, int, str], ...], str | None]:
        return await self._adapter(identity).locator_profile_attestation_page(
            cursor=cursor, limit=limit
        )

    async def attestation_epoch(self, identity: RetrievalProfileIdentity, *, now: datetime) -> int:
        if self.mutation_registry is None:
            raise RuntimeError("retrieval_profile_provider_fence_unconfigured")
        return await self.mutation_registry.provider_attestation_epoch(identity.profile_id, now=now)

    async def delete_profile(self, authorization: ProfileCollectionDeleteAuthorization) -> None:
        """Delete a collection idempotently; absence is the desired state."""

        identity = authorization.identity
        adapter = self._adapter(identity)
        client = None
        try:
            async with asyncio.timeout(50):
                client, _ = await adapter._client()
                if await client.collection_exists(identity.collection_name):
                    deleted = await client.delete_collection(identity.collection_name)
                    if deleted is False:
                        raise RuntimeError("retrieval_profile_qdrant_collection_delete_failed")
                if await client.collection_exists(identity.collection_name):
                    raise RuntimeError("retrieval_profile_qdrant_collection_delete_failed")
            self._adapters.pop(identity.profile_id, None)
        except Exception as exc:
            raise RuntimeError("retrieval_profile_qdrant_collection_delete_failed") from exc
        finally:
            if client is not None:
                close = getattr(client, "close", None)
                if close is not None:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result

    def _mutation(self, identity: RetrievalProfileIdentity):
        return _ProviderMutation(self.mutation_registry, identity.profile_id, self.runtime_owner)


class _ProviderMutation:
    def __init__(self, registry, profile_id: str, owner: RuntimeFenceOwner) -> None:
        self.registry = registry
        self.profile_id = profile_id
        self.owner = owner
        self.operation_id = f"qdrant-write-{uuid4()}"
        self.started_epoch: int | None = None
        self._completed = False
        self._stop = asyncio.Event()
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._heartbeat_error: BaseException | None = None

    async def __aenter__(self):
        if self.registry is None:
            raise RuntimeError("retrieval_profile_provider_fence_unconfigured")
        now = datetime.now(UTC)
        self.started_epoch = await self.registry.begin_provider_mutation(
            self.profile_id,
            self.operation_id,
            owner=self.owner,
            now=now,
            expires_at=now + timedelta(seconds=15),
        )
        self._heartbeat_task = asyncio.create_task(self._heartbeat())
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self._stop.set()
        if self._heartbeat_task is not None:
            await self._heartbeat_task
        if exc_type is None and self._completed and self._heartbeat_error is None:
            await self.registry.finish_provider_mutation(
                self.profile_id,
                self.operation_id,
                owner=self.owner,
                started_epoch=self.started_epoch,
                now=datetime.now(UTC),
            )
            return None
        if exc_type is None and self._heartbeat_error is not None:
            raise RuntimeError(
                "retrieval_profile_provider_mutation_fenced"
            ) from self._heartbeat_error
        # Any timeout or ambiguous provider failure deliberately leaves the
        # durable row in place. It cannot be stolen by elapsed wall time.
        return None

    def complete(self) -> None:
        self._completed = True

    async def _heartbeat(self) -> None:
        assert self.started_epoch is not None
        while True:
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=5)
                return
            except TimeoutError:
                now = datetime.now(UTC)
                try:
                    await self.registry.heartbeat_provider_mutation(
                        self.profile_id,
                        self.operation_id,
                        owner=self.owner,
                        started_epoch=self.started_epoch,
                        now=now,
                        expires_at=now + timedelta(seconds=15),
                    )
                except BaseException as error:
                    self._heartbeat_error = error
                    return


__all__ = ("QdrantRetrievalProfileProjection",)
