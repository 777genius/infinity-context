"""Opt-in real-Qdrant acceptance for the Retrieval locator profile."""

from __future__ import annotations

import asyncio
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
from contextlib import suppress
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import infinity_context_core.features.context_building.public as core
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from infinity_context_adapters.features.context_building.qdrant_candidate_provider import (
    QdrantContextCandidateProvider,
)
from infinity_context_adapters.postgres import (
    PostgresCanonicalProjectionSource,
    PostgresRetrievalProfileRegistry,
    RuntimeProcessSupervisor,
    build_async_engine,
    build_session_factory,
    registry_document,
    upgrade_schema,
)
from infinity_context_adapters.postgres.supervisor_trust import SupervisorTrustRegistry
from infinity_context_adapters.qdrant.profile_lifecycle import (
    QdrantRetrievalProfileProjection,
)
from infinity_context_adapters.qdrant.vector_adapter import QdrantVectorMemoryAdapter
from infinity_context_core.features.context_building.public import (
    CanonicalProjectionItem,
    ProfileCollectionDeleteAuthorization,
    RetrievalProfileIdentity,
)
from infinity_context_core.ports.adapters import EmbeddingResult, PortStatus, VectorUpsertItem
from infinity_context_server.build_identity import repository_source_release_identity
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.getenv("INFINITY_RUN_LOCATOR_QDRANT_E2E") != "1",
    reason="requires a fresh isolated Qdrant sandbox service",
)

_PROJECTION = "document-retrieval-projection.v1"
_PROFILE = "a" * 64
_GENERATION = "b" * 64


def test_real_qdrant_locator_profile_is_exact_and_fail_closed() -> None:
    asyncio.run(_run_contract())


def test_real_qdrant_profile_targets_are_independent_and_version_deleted() -> None:
    asyncio.run(_run_profile_targets())


def test_real_qdrant_large_profile_resumes_attests_and_physically_deletes() -> None:
    postgres_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not postgres_url:
        pytest.skip("requires a fresh isolated PostgreSQL sandbox service")
    asyncio.run(_run_large_profile(postgres_url))


def test_recoverable_fresh_process_launcher_smoke() -> None:
    postgres_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not postgres_url:
        pytest.skip("requires a fresh isolated PostgreSQL sandbox service")
    asyncio.run(_run_recoverable_fresh_process_smoke(postgres_url))


async def _run_recoverable_fresh_process_smoke(postgres_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        postgres_url, prefix="locator_qd_sup_smoke", asyncpg=asyncpg
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    identity = RetrievalProfileIdentity(
        "profile-supervised-smoke",
        "generation-supervised-smoke",
        "d" * 64,
        f"locator_supervised_smoke_{uuid4().hex}",
    )
    try:
        await upgrade_schema(engine)
        evidence = await _fresh_process_lifecycle(
            "build_activate",
            database.app_url,
            identity,
            process_generation=uuid4().hex,
            acknowledge_owner=None,
        )
        assert int(evidence["count"]) == int(evidence["expected_count"]) == 0
        assert evidence["supervisor_key_id"] == "qdrant-acceptance-supervisor"
        assert evidence["activated"] is True
        assert len(str(evidence["sealed_dead_proof_sha256"])) == 64
    finally:
        from qdrant_client import AsyncQdrantClient

        client = AsyncQdrantClient(
            url=os.environ["INFINITY_SANDBOX_QDRANT_URL"], timeout=10, trust_env=False
        )
        try:
            if await client.collection_exists(identity.collection_name):
                await client.delete_collection(identity.collection_name)
        finally:
            await client.close()
        await engine.dispose()
        await database.drop()


async def _run_profile_targets() -> None:
    qdrant_url = os.environ["INFINITY_SANDBOX_QDRANT_URL"]
    suffix = uuid4().hex
    first = RetrievalProfileIdentity(
        "profile-a", "generation-a", "a" * 64, f"locator_profile_a_{suffix}"
    )
    second = RetrievalProfileIdentity(
        "profile-b", "generation-b", "b" * 64, f"locator_profile_b_{suffix}"
    )
    target = _item("chunk-target", "space-a", "scope-a", "thread-a", 1)
    item = CanonicalProjectionItem(
        "chunk-target",
        1,
        1,
        "c" * 64,
        "space-a",
        "scope-a",
        "thread-a",
        target.text,
        tuple(target.metadata.items()),
    )
    projection = QdrantRetrievalProfileProjection(
        qdrant_url, None, 2, _FixedEmbedder(), _LocalFence()
    )
    try:
        await projection.upsert_profile(first, (item,))
        await projection.upsert_profile(second, (item,))
        first_attestation = await projection.attestation(first)
        second_attestation = await projection.attestation(second)
        assert first_attestation == second_attestation
        assert first_attestation[0] == 1
        assert len(first_attestation[1]) == 64
        assert await projection.adapter_for(first).locator_points_absent(("chunk-target",)) is False
        assert (
            await projection.adapter_for(second).locator_points_absent(("chunk-target",)) is False
        )
        await projection.delete_profile_if_version(first, ("chunk-target",), canonical_version=1)
        assert await projection.adapter_for(first).locator_points_absent(("chunk-target",)) is True
        assert (
            await projection.adapter_for(second).locator_points_absent(("chunk-target",)) is False
        )
        deletion = ProfileCollectionDeleteAuthorization(first, "test-delete-first", 1)
        await projection.delete_profile(deletion)
        await projection.delete_profile(deletion)
        from qdrant_client import AsyncQdrantClient

        client = AsyncQdrantClient(url=qdrant_url, timeout=10, trust_env=False)
        try:
            assert await client.collection_exists(first.collection_name) is False
            assert await client.collection_exists(second.collection_name) is True
        finally:
            await client.close()
    finally:
        from qdrant_client import AsyncQdrantClient

        client = AsyncQdrantClient(url=qdrant_url, timeout=10, trust_env=False)
        try:
            for identity in (first, second):
                if await client.collection_exists(identity.collection_name):
                    await client.delete_collection(identity.collection_name)
        finally:
            await client.close()


class _FixedEmbedder:
    async def embed_texts(self, texts):
        return EmbeddingResult(PortStatus.OK, tuple((1.0, 0.0) for _ in texts))


class _LocalFence:
    def __init__(self):
        self.epoch = 0
        self.active = False

    async def begin_provider_mutation(self, *_args, **_kwargs):
        self.epoch += 1
        self.active = True
        return self.epoch

    async def finish_provider_mutation(self, *_args, **_kwargs):
        self.active = False
        self.epoch += 1
        return self.epoch

    async def heartbeat_provider_mutation(self, *_args, started_epoch, now, expires_at, **_kwargs):
        assert self.active is True
        assert started_epoch == self.epoch
        assert expires_at > now

    async def provider_attestation_epoch(self, *_args, **_kwargs):
        if self.active:
            raise RuntimeError("retrieval_profile_provider_mutation_active")
        return self.epoch


async def _run_large_profile(postgres_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        postgres_url, prefix="locator_qdrant_large", asyncpg=asyncpg
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    identity = RetrievalProfileIdentity(
        "profile-large", "generation-large", "e" * 64, f"locator_large_{uuid4().hex}"
    )
    successor = RetrievalProfileIdentity(
        "profile-successor",
        "generation-successor",
        "f" * 64,
        f"locator_successor_{uuid4().hex}",
    )
    projection = None
    try:
        await upgrade_schema(engine)
        registry = PostgresRetrievalProfileRegistry(build_session_factory(engine))
        await _seed_large_canonical_catalog(database, 16_385)
        await registry.create_building(identity, now=datetime.now(UTC))
        projection = QdrantRetrievalProfileProjection(
            os.environ["INFINITY_SANDBOX_QDRANT_URL"],
            None,
            2,
            _FixedEmbedder(),
            registry,
        )
        source = PostgresCanonicalProjectionSource(build_session_factory(engine))
        cursor = None
        canonical_count = 0
        while True:
            page = await source.page_eligible(after=cursor, limit=512)
            await projection.upsert_profile(identity, page.items)
            await registry.record_projection(
                identity.profile_id, page.items, projected_at=datetime.now(UTC)
            )
            canonical_count += len(page.items)
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
        coverage = await registry.coverage(identity.profile_id)
        assert canonical_count == coverage.expected_count == coverage.projected_count == 16_385
        assert coverage.expected_digest == coverage.projected_digest
        parent_pid = os.getpid()
        checkpointed = await _fresh_process_lifecycle(
            "attest_checkpoint",
            database.app_url,
            identity,
            process_generation=uuid4().hex,
            acknowledge_owner=projection.runtime_owner,
        )
        assert checkpointed["pid"] != parent_pid
        assert checkpointed["checkpoint_complete"] is False
        assert 0 < int(checkpointed["checkpoint_item_count"]) < 16_385
        resumed = await _fresh_process_lifecycle(
            "attest_resume_activate",
            database.app_url,
            identity,
            process_generation=uuid4().hex,
            acknowledge_owner=projection.runtime_owner,
        )
        assert resumed["pid"] != parent_pid
        assert resumed["pid"] != checkpointed["pid"]
        assert int(resumed["resumed_from_item_count"]) == int(checkpointed["checkpoint_item_count"])
        count, digest = int(resumed["count"]), str(resumed["digest"])
        assert count == 16_385
        assert digest == coverage.expected_digest == coverage.projected_digest
        assert resumed["activated"] is True
        async with engine.connect() as connection:
            transition_identity = await connection.scalar(
                text(
                    "SELECT lifecycle_identity_sha256 "
                    "FROM memory_locator_profile_transition_audit WHERE profile_id=:profile_id"
                ),
                {"profile_id": identity.profile_id},
            )
        assert transition_identity == resumed["lifecycle_identity_sha256"]
        for evidence in (checkpointed, resumed):
            assert evidence["supervisor_key_id"] == "qdrant-acceptance-supervisor"
            assert int(evidence["trust_registry_generation"]) == 1
            assert len(str(evidence["trust_root_sha256"])) == 64
            assert len(str(evidence["release_identity_sha256"])) == 64
            assert len(str(evidence["sealed_dead_proof_sha256"])) == 64
            assert len(str(evidence["sealed_lifecycle_identity_sha256"])) == 64
        hits = await projection.adapter_for(identity).search_locator_chunks(
            space_id="space-large",
            memory_scope_id="scope-large",
            thread_id=None,
            query_vector=(1.0, 0.0),
            query_text="synthetic record",
            limit=1,
            filter_spec={"must": [], "must_not": []},
        )
        assert len(hits) == 1
        successor_proof = await _fresh_process_lifecycle(
            "build_activate",
            database.app_url,
            successor,
            process_generation=uuid4().hex,
            acknowledge_owner=projection.runtime_owner,
        )
        assert successor_proof["pid"] != parent_pid
        assert int(successor_proof["count"]) == 16_385
        assert successor_proof["digest"] == successor_proof["expected_digest"]
        assert successor_proof["digest"] == successor_proof["projected_digest"]
        assert successor_proof["activated"] is True
        async with engine.connect() as connection:
            successor_transition_identity = await connection.scalar(
                text(
                    "SELECT lifecycle_identity_sha256 "
                    "FROM memory_locator_profile_transition_audit WHERE profile_id=:profile_id"
                ),
                {"profile_id": successor.profile_id},
            )
        assert successor_transition_identity == successor_proof["lifecycle_identity_sha256"]
        assert identity.profile_id in await registry.retire(
            identity.profile_id, now=datetime.now(UTC), maximum_retained=2
        )
        deletion = await registry.authorize_collection_delete(
            identity.profile_id, now=datetime.now(UTC)
        )
        assert deletion is not None
        await projection.delete_profile(deletion)
        from qdrant_client import AsyncQdrantClient

        client = AsyncQdrantClient(
            url=os.environ["INFINITY_SANDBOX_QDRANT_URL"], timeout=10, trust_env=False
        )
        try:
            assert await client.collection_exists(identity.collection_name) is False
        finally:
            await client.close()
        await registry.mark_collection_deleted(deletion, now=datetime.now(UTC))
        await registry.cleanup_postgres(identity.profile_id, now=datetime.now(UTC))
        await registry.complete_cleanup(identity.profile_id, now=datetime.now(UTC))
        successor_adapter = QdrantVectorMemoryAdapter(
            url=os.environ["INFINITY_SANDBOX_QDRANT_URL"],
            collection_name=successor.collection_name,
            vector_size=2,
            projection_version=_PROJECTION,
            index_profile_digest=successor.profile_digest,
            index_generation=successor.generation,
        )
        assert await successor_adapter.locator_points_absent(("chunk-000000",)) is False
        async with engine.connect() as connection:
            for table in (
                "memory_locator_profile_queries",
                "memory_locator_profile_provider_mutations",
                "memory_locator_profile_reconciliation_operations",
                "memory_locator_profile_projection_receipts",
                "memory_locator_profile_tombstones",
                "memory_locator_profile_lanes",
            ):
                assert (
                    int(
                        await connection.scalar(
                            text(f"SELECT count(*) FROM {table} WHERE profile_id=:profile_id"),
                            {"profile_id": identity.profile_id},
                        )
                        or 0
                    )
                    == 0
                )
            assert (
                await connection.scalar(
                    text(
                        "SELECT phase FROM memory_locator_profile_cleanups "
                        "WHERE profile_id=:profile_id"
                    ),
                    {"profile_id": identity.profile_id},
                )
                == "complete"
            )
    finally:
        if projection is not None:
            with suppress(RuntimeError):
                await projection.delete_profile(
                    ProfileCollectionDeleteAuthorization(identity, "test-delete-finally", 1)
                )
        from qdrant_client import AsyncQdrantClient

        cleanup_client = AsyncQdrantClient(
            url=os.environ["INFINITY_SANDBOX_QDRANT_URL"], timeout=10, trust_env=False
        )
        try:
            for cleanup_identity in (identity, successor):
                if await cleanup_client.collection_exists(cleanup_identity.collection_name):
                    await cleanup_client.delete_collection(cleanup_identity.collection_name)
        finally:
            await cleanup_client.close()
        await engine.dispose()
        await database.drop()


async def _fresh_process_lifecycle(
    mode: str,
    postgres_url: str,
    identity: RetrievalProfileIdentity,
    *,
    process_generation: str,
    acknowledge_owner,
) -> dict[str, object]:
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        str(root / "packages" / package)
        for package in (
            "infinity_context_adapters",
            "infinity_context_core",
            "infinity_context_contracts",
            "infinity_context_server",
        )
    )
    environment["PGSSLMODE"] = "disable"
    for ssl_variable in ("PGSSLCERT", "PGSSLKEY", "PGSSLROOTCERT", "PGSSLCRL"):
        environment.pop(ssl_variable, None)
    release = repository_source_release_identity(root)
    signing_key = Ed25519PrivateKey.generate()
    public_key = (
        signing_key.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex()
    )
    key_id = "qdrant-acceptance-supervisor"
    valid_from = datetime.now(UTC) - timedelta(minutes=1)
    valid_until = datetime.now(UTC) + timedelta(hours=1)
    target = __import__("pathlib").Path(
        tempfile.mkdtemp(prefix="infinity-qdrant-launch-", dir="/tmp")
    )
    target.chmod(0o755)
    registry_raw, trust_root = registry_document(
        registry_id=f"qdrant-acceptance-{process_generation}",
        generation=1,
        valid_from=valid_from,
        valid_until=valid_until,
        keys=((key_id, public_key),),
        installed_release=release,
    )
    registry_path = target / "supervisor-registry.json"
    registry_path.write_bytes(registry_raw)
    registry_path.chmod(0o444)
    nobody = pwd.getpwnam("nobody")
    process = subprocess.Popen(
        [sys.executable, "tests/e2e/locator_retrieval_fresh_process.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(root),
        env=environment,
    )
    supervisor = RuntimeProcessSupervisor(
        key_id=key_id,
        process=process,
        trust_root_sha256=trust_root,
        trust_registry_generation=1,
        installed_release=release,
        signing_key=signing_key,
        instance_id=f"fresh-process-{mode}-{process_generation}",
        generation=process_generation,
    )
    configuration = {
        "mode": mode,
        "postgres_url": postgres_url,
        "qdrant_url": os.environ["INFINITY_SANDBOX_QDRANT_URL"],
        "process_generation": process_generation,
        "runtime_uid": nobody.pw_uid,
        "runtime_gid": nobody.pw_gid,
        "trust_registry_path": str(registry_path),
        "trust_root_sha256": trust_root,
        "supervisor_key_id": key_id,
        "trust_registry_generation": 1,
        "installed_release": release.payload(),
        "launch_identity": asdict(supervisor.owner()),
        "identity": {
            "profile_id": identity.profile_id,
            "generation": identity.generation,
            "profile_digest": identity.profile_digest,
            "collection_name": identity.collection_name,
        },
    }
    try:
        stdout, stderr = await asyncio.to_thread(
            process.communicate, json.dumps(configuration), 600
        )
        if process.returncode != 0:
            raise AssertionError(f"fresh Retrieval process failed: {stderr[-2000:]}")
        result = json.loads(stdout.strip().splitlines()[-1])
        if result["lifecycle_identity_sha256"] != supervisor.owner().lifecycle_identity_sha256():
            raise AssertionError("fresh process lifecycle identity drifted")
        trust = SupervisorTrustRegistry(
            f"qdrant-acceptance-{process_generation}",
            1,
            valid_from,
            valid_until,
            ((key_id, public_key),),
            release,
            trust_root,
        )
        engine = build_async_engine(postgres_url)
        try:
            durable = PostgresRetrievalProfileRegistry(build_session_factory(engine), trust)
            maintenance_generation = await durable.begin_maintenance(
                reason="seal completed isolated Qdrant acceptance runtime"
            )
            if acknowledge_owner is not None:
                await durable.acknowledge_maintenance(
                    owner_instance_id=acknowledge_owner.instance_id,
                    owner_generation=acknowledge_owner.generation,
                    maintenance_generation=maintenance_generation,
                )
            proof = supervisor.prove_exit(maintenance_generation=maintenance_generation)
            proof_digest = await durable.seal_dead_incarnation(proof=proof)
            await durable.complete_maintenance(maintenance_generation)
        finally:
            await engine.dispose()
        result.update(
            {
                "supervisor_key_id": key_id,
                "trust_registry_generation": 1,
                "trust_root_sha256": trust_root,
                "release_identity_sha256": release.digest(),
                "sealed_dead_proof_sha256": proof_digest,
                "sealed_lifecycle_identity_sha256": supervisor.owner().lifecycle_identity_sha256(
                    sealed_proof_id=proof.proof_id,
                    sealed_proof_sha256=proof_digest,
                ),
            }
        )
        return result
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        shutil.rmtree(target)


async def _seed_large_canonical_catalog(database, count: int) -> None:
    """Seed the canonical eligible set; Qdrant is built only from this read model."""

    raw = await database.connect()
    try:
        await raw.execute(
            """
            INSERT INTO memory_spaces
              (id, slug, name, status, created_at, updated_at)
            VALUES ('space-large', 'space-large', 'Large', 'active', now(), now());
            INSERT INTO memory_scopes
              (id, space_id, external_ref, name, status, created_at, updated_at)
            VALUES ('scope-large', 'space-large', 'scope-large', 'Large',
                    'active', now(), now());
            INSERT INTO memory_documents
              (id, space_id, memory_scope_id, thread_id, title, source_type,
               source_external_id, content_hash, classification, status,
               created_at, updated_at, retrieval_projected)
            VALUES ('document-large', 'space-large', 'scope-large', NULL,
                    'Large', 'synthetic', 'large', repeat('a', 64),
                    'internal', 'active', now(), now(), TRUE)
            """
        )
        statement = """
            INSERT INTO memory_chunks
              (id, space_id, memory_scope_id, thread_id, document_id, episode_id,
               source_type, source_external_id, source_hash, kind, text,
               normalized_text, status, sequence, char_start, char_end,
               token_estimate, classification, created_at, updated_at, metadata_json,
               retrieval_locator, retrieval_source_key, retrieval_projection_generation,
               retrieval_sequence_ordinal, retrieval_kind, retrieval_actor_keys_json,
               retrieval_category, retrieval_tags_json)
            VALUES ($1, 'space-large', 'scope-large', NULL, 'document-large', NULL,
                    'synthetic', 'large', $5, 'record', $2, $2,
                    'active', $3, 0, 1, 1, 'internal', now(), now(), '{}'::jsonb,
                    $4, 'source:large', 'projection-v1', $3, 'record',
                    '[]'::jsonb, 'generic', '["accepted"]'::jsonb)
        """
        await raw.executemany(
            statement,
            [
                (
                    f"chunk-{index:06d}",
                    f"Synthetic record {index}",
                    index,
                    f"source:large:item:{index}",
                    f"{index:064x}",
                )
                for index in range(count)
            ],
        )
    finally:
        await raw.close()


async def _run_contract() -> None:
    qdrant_url = os.environ["INFINITY_SANDBOX_QDRANT_URL"]
    collection = f"locator_v2_{uuid4().hex}"
    adapter = _adapter(qdrant_url, collection, _GENERATION)
    target = _item("chunk-target", "space-a", "scope-a", "thread-a", 1)
    foreign_scope = _item("chunk-foreign", "space-b", "scope-b", "thread-b", 2)
    try:
        written = await adapter.upsert_chunks((target, foreign_scope))
        assert written.status == PortStatus.OK, written.diagnostics
        assert written.affected_count == 2
        capabilities = await adapter.capabilities()
        assert capabilities.healthy is True
        assert capabilities.supports_filters is True

        hits = await adapter.search_locator_chunks(
            space_id="space-a",
            memory_scope_id="scope-a",
            thread_id="thread-a",
            query_vector=(1.0, 0.0),
            query_text="synthetic decision",
            limit=5,
            filter_spec={"must": [], "must_not": []},
        )
        assert [hit["canonical_identity"] for hit in hits] == ["chunk-target"]
        lane_result = await QdrantContextCandidateProvider(
            search=adapter,
            embedder=_FixedEmbedder(),
        ).retrieve_locator_candidates(_request())
        assert lane_result.status == "available"
        assert [
            (hit.canonical_identity, hit.canonical_version, hit.provider_rank)
            for hit in lane_result.hits
        ] == [("chunk-target", 1, 1)]
        assert await adapter.locator_profile_complete(
            (
                _row("chunk-target", "space-a", "scope-a", "thread-a", 1),
                _row("chunk-foreign", "space-b", "scope-b", "thread-b", 2),
            )
        )

        foreign_generation = _adapter(qdrant_url, collection, "c" * 64)
        assert (
            await foreign_generation.search_locator_chunks(
                space_id="space-a",
                memory_scope_id="scope-a",
                thread_id="thread-a",
                query_vector=(1.0, 0.0),
                query_text="synthetic decision",
                limit=5,
                filter_spec={"must": [], "must_not": []},
            )
            == ()
        )

        malformed = replace(
            _item("chunk-invalid", "space-a", "scope-a", "thread-a", 3),
            metadata={
                **target.metadata,
                "canonical_identity": "chunk-invalid",
                "chunk_key": "chunk-invalid",
                "tags": "decision\u001faccepted",
            },
        )
        rejected = await adapter.upsert_chunks((malformed,))
        assert rejected.status == PortStatus.DEGRADED
        assert rejected.diagnostics[0].code == "qdrant.locator_profile_invalid"
        assert rejected.diagnostics[0].retryable is False
        assert await adapter.locator_points_absent(("chunk-invalid",)) is True

        newer_target = replace(
            target,
            metadata={**target.metadata, "canonical_version": "2"},
        )
        assert (await adapter.upsert_chunks((newer_target,))).status == PortStatus.OK
        stale_delete = await adapter.delete_chunks_if_version(
            ("chunk-target",), canonical_version=1
        )
        assert stale_delete.status == PortStatus.OK
        surviving = await adapter.search_locator_chunks(
            space_id="space-a",
            memory_scope_id="scope-a",
            thread_id="thread-a",
            query_vector=(1.0, 0.0),
            query_text="synthetic decision",
            limit=5,
            filter_spec={"must": [], "must_not": []},
        )
        assert [hit["canonical_version"] for hit in surviving] == [2]

        current_delete = await adapter.delete_chunks_if_version(
            ("chunk-target",), canonical_version=2
        )
        assert current_delete.status == PortStatus.OK
        deleted = await adapter.delete_chunks(("chunk-foreign",))
        assert deleted.status == PortStatus.OK
        assert await adapter.locator_points_absent(("chunk-target", "chunk-foreign")) is True
    finally:
        from qdrant_client import AsyncQdrantClient

        client = AsyncQdrantClient(url=qdrant_url, timeout=10, trust_env=False)
        try:
            if await client.collection_exists(collection):
                await client.delete_collection(collection)
        finally:
            await client.close()


def _adapter(url: str, collection: str, generation: str) -> QdrantVectorMemoryAdapter:
    return QdrantVectorMemoryAdapter(
        url=url,
        collection_name=collection,
        vector_size=2,
        projection_version=_PROJECTION,
        index_profile_digest=_PROFILE,
        index_generation=generation,
    )


def _request() -> core.LocatorRetrievalRequest:
    return core.LocatorRetrievalRequest(
        contract_version="context-retrieval.v2",
        capability_fingerprint="d" * 64,
        profile_id="qdrant-e2e",
        scope=core.LocatorRetrievalScope("space-a", "scope-a", "thread-a"),
        queries=(core.LocatorQueryVariant("q1", "synthetic decision"),),
        hard_filters=core.LocatorHardFilters(
            source_generations=(core.LocatorSourceGeneration("source:synthetic", "projection-v1"),)
        ),
        soft_preferences=core.LocatorSoftPreferences(),
        bounds=core.LocatorRetrievalBounds(candidate_limit=5, result_limit=5),
    )


def _item(
    chunk: str,
    space: str,
    scope: str,
    thread: str,
    ordinal: int,
) -> VectorUpsertItem:
    return VectorUpsertItem(
        chunk_id=chunk,
        space_id=space,
        memory_scope_id=scope,
        thread_id=thread,
        text=f"Synthetic decision {ordinal}",
        vector=(1.0, 0.0),
        projection_version=_PROJECTION,
        metadata={
            "locator": f"source:synthetic:item:{ordinal}",
            "source_key": "source:synthetic",
            "projection_generation": "projection-v1",
            "sequence_ordinal": str(ordinal),
            "actor_keys": "actor-a",
            "start_at": None,
            "end_at": None,
            "relative_start_ms": str(ordinal * 1000),
            "relative_end_ms": str(ordinal * 1000 + 1500),
            "kind": "record",
            "category": "generic",
            "tags": "accepted\u001fdecision",
            "canonical_identity": chunk,
            "canonical_version": "1",
            "lifecycle_status": "active",
            "document_key": f"document-{space}",
            "chunk_key": chunk,
        },
    )


def _row(chunk: str, space: str, scope: str, thread: str, ordinal: int) -> object:
    return SimpleNamespace(
        id=chunk,
        document_id=f"document-{space}",
        space_id=space,
        memory_scope_id=scope,
        thread_id=thread,
        retrieval_locator=f"source:synthetic:item:{ordinal}",
        retrieval_source_key="source:synthetic",
        retrieval_projection_generation="projection-v1",
        retrieval_sequence_ordinal=ordinal,
        retrieval_actor_keys_json=["actor-a"],
        retrieval_start_at=None,
        retrieval_end_at=None,
        retrieval_relative_start_ms=ordinal * 1000,
        retrieval_relative_end_ms=ordinal * 1000 + 1500,
        retrieval_kind="record",
        retrieval_category="generic",
        retrieval_tags_json=["accepted", "decision"],
        retrieval_version=1,
    )
