"""Fresh-interpreter worker for the mandatory durable Qdrant lifecycle proof."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta

import asyncpg  # noqa: F401  # preload before the disposable runtime drops OS identity
import qdrant_client  # noqa: F401  # preload before the disposable runtime drops OS identity
from infinity_context_adapters.postgres import build_async_engine, build_session_factory
from infinity_context_adapters.postgres.locator_profile_lifecycle import (
    PostgresCanonicalProjectionSource,
    PostgresRetrievalProfileRegistry,
)
from infinity_context_adapters.postgres.models import (
    MemoryLocatorProfileAttestationCheckpointRow,
)
from infinity_context_adapters.postgres.supervisor_trust import load_pinned_supervisor_trust
from infinity_context_adapters.qdrant.profile_lifecycle import QdrantRetrievalProfileProjection
from infinity_context_core.features.context_building.public import (
    InstalledReleaseIdentity,
    RetrievalProfileIdentity,
    RuntimeFenceOwner,
)
from infinity_context_core.ports.adapters import EmbeddingResult, PortStatus
from infinity_context_server.retrieval_profile_composition import _bounded_qdrant_attestation
from locator_retrieval_process_identity import enter_runtime_identity
from sqlalchemy import select


class _FixedEmbedder:
    async def embed_texts(self, texts):
        return EmbeddingResult(PortStatus.OK, tuple((1.0, 0.0) for _ in texts))


async def _attest(registry, projection, identity, *, checkpoint_only: bool = False):
    initial = await _incomplete_checkpoint(registry, identity.profile_id)
    attempts = 1 if checkpoint_only else 12
    for _ in range(attempts):
        try:
            result = await _bounded_qdrant_attestation(
                registry,
                projection,
                identity,
                operation_id=f"fresh-process-{identity.profile_id}",
                now=datetime.now(UTC),
                page_size=256,
                maximum_pages=1 if checkpoint_only else 16,
                deadline=timedelta(seconds=30),
            )
            if checkpoint_only:
                raise RuntimeError("retrieval_profile_checkpoint_process_completed_unexpectedly")
            return result, initial
        except RuntimeError as exc:
            if str(exc) != "retrieval_profile_attestation_incomplete":
                raise
    if checkpoint_only:
        checkpoint = await _incomplete_checkpoint(registry, identity.profile_id)
        if checkpoint is None or checkpoint.complete or checkpoint.item_count <= 0:
            raise RuntimeError("retrieval_profile_checkpoint_process_did_not_persist")
        return None, checkpoint
    raise RuntimeError("retrieval_profile_fresh_process_attestation_incomplete")


async def _incomplete_checkpoint(registry, profile_id):
    async with registry.sessions() as session:
        return await session.scalar(
            select(MemoryLocatorProfileAttestationCheckpointRow)
            .where(
                MemoryLocatorProfileAttestationCheckpointRow.profile_id == profile_id,
                MemoryLocatorProfileAttestationCheckpointRow.complete.is_(False),
            )
            .order_by(MemoryLocatorProfileAttestationCheckpointRow.updated_at.desc())
            .limit(1)
        )


async def _run(configuration: dict[str, object]) -> dict[str, object]:
    # The disposable interpreter lives below a root-only toolchain directory.
    # Construct and close the provider client to load code only; no request is sent
    # until after the public registry is verified under the dropped runtime identity.
    preload = qdrant_client.AsyncQdrantClient(
        url=str(configuration["qdrant_url"]), timeout=10, trust_env=False
    )
    await preload.close()
    enter_runtime_identity(
        int(configuration["runtime_uid"]), int(configuration["runtime_gid"])
    )
    engine = build_async_engine(str(configuration["postgres_url"]))
    sessions = build_session_factory(engine)
    release = InstalledReleaseIdentity(**configuration["installed_release"])
    trust = load_pinned_supervisor_trust(
        path=str(configuration["trust_registry_path"]),
        expected_root_sha256=str(configuration["trust_root_sha256"]),
        expected_key_id=str(configuration["supervisor_key_id"]),
        expected_generation=int(configuration["trust_registry_generation"]),
        expected_release=release,
    )
    registry = PostgresRetrievalProfileRegistry(sessions, trust)
    identity = RetrievalProfileIdentity(**configuration["identity"])
    owner = RuntimeFenceOwner.from_launch_identity_json(
        json.dumps(configuration["launch_identity"], separators=(",", ":"))
    )
    owner.assert_current_process()
    trust.verify_launch(owner, now=datetime.now(UTC))
    await registry.register_runtime_incarnation(owner, now=datetime.now(UTC))
    projection = QdrantRetrievalProfileProjection(
        str(configuration["qdrant_url"]), None, 2, _FixedEmbedder(), registry, owner
    )
    try:
        if str(configuration["mode"]).startswith("build"):
            await registry.create_building(identity, now=datetime.now(UTC))
            source = PostgresCanonicalProjectionSource(sessions)
            cursor = None
            while True:
                page = await source.page_eligible(after=cursor, limit=512)
                await projection.upsert_profile(identity, page.items)
                await registry.record_projection(
                    identity.profile_id, page.items, projected_at=datetime.now(UTC)
                )
                await registry.checkpoint_backfill(
                    identity.profile_id,
                    previous_cursor=cursor,
                    cursor=page.next_cursor,
                    watermark=page.canonical_watermark,
                    complete=page.next_cursor is None,
                    now=datetime.now(UTC),
                )
                cursor = page.next_cursor
                if cursor is None:
                    break
        proof, initial_checkpoint = await _attest(
            registry,
            projection,
            identity,
            checkpoint_only=configuration["mode"] == "attest_checkpoint",
        )
        coverage = await registry.coverage(identity.profile_id)
        if proof is None:
            return {
                "pid": __import__("os").getpid(),
                "checkpoint_complete": False,
                "checkpoint_item_count": initial_checkpoint.item_count,
                "checkpoint_operation_id": initial_checkpoint.operation_id,
                "lifecycle_identity": owner.lifecycle_identity_payload(),
                "lifecycle_identity_sha256": owner.lifecycle_identity_sha256(),
            }
        count, digest, epoch = proof
        activated = False
        if "activate" in str(configuration["mode"]):
            await registry.update_lane(
                identity.profile_id,
                "qdrant_dense",
                required=True,
                healthy=True,
                profile_qualified=True,
                failure_code=None,
                checked_at=datetime.now(UTC),
                observed_count=count,
                observed_digest=digest,
            )
            evidence = await registry.activation_evidence(
                identity.profile_id, now=datetime.now(UTC)
            )
            lease_now = datetime.now(UTC)
            lease = await registry.issue_activation_lease(
                identity.profile_id,
                evidence,
                lease_id=f"fresh-activation-{owner.generation}",
                now=lease_now,
                expires_at=lease_now + timedelta(minutes=2),
                mutation_epoch=epoch,
            )
            await registry.activate(
                lease,
                await registry.activation_evidence(identity.profile_id, now=datetime.now(UTC)),
                now=datetime.now(UTC),
                maximum_queue_lag=timedelta(minutes=5),
                maximum_retained=2,
                runtime_owner=owner,
            )
            activated = True
        return {
            "pid": __import__("os").getpid(),
            "count": count,
            "digest": digest,
            "epoch": epoch,
            "expected_count": coverage.expected_count,
            "expected_digest": coverage.expected_digest,
            "projected_digest": coverage.projected_digest,
            "resumed_from_item_count": (
                initial_checkpoint.item_count if initial_checkpoint is not None else 0
            ),
            "lifecycle_identity": owner.lifecycle_identity_payload(),
            "lifecycle_identity_sha256": owner.lifecycle_identity_sha256(),
            "activated": activated,
        }
    finally:
        await engine.dispose()


if __name__ == "__main__":
    config = json.loads(sys.stdin.read())
    print(json.dumps(asyncio.run(_run(config)), sort_keys=True))
