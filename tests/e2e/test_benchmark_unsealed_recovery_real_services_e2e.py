"""Opt-in real-service sandbox for direct unsealed derived absence."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from infinity_context_adapters.graphiti.identity_evidence import (
    GraphitiIdentityEvidenceError,
    Neo4jGraphitiIdentityEvidenceAdapter,
)
from infinity_context_adapters.graphiti.scope_identity import graphiti_group_id
from infinity_context_adapters.qdrant.identity_evidence import (
    QdrantIdentityEvidence,
    qdrant_point_id_for_chunk,
)
from infinity_context_core.ports.benchmark_cleanup_plan import (
    COGNEE_NOT_PROJECTED_POLICY_SHA256,
    GRAPHITI_GROUP_MAPPING_POLICY_SHA256,
    GRAPHITI_SPACE_PREFIX_SCAN_POLICY_SHA256,
    QDRANT_COLLECTION_PROJECTION_POLICY_SHA256,
    QDRANT_SCOPE_MAPPING_POLICY_SHA256,
    QDRANT_SPACE_WIDE_SCAN_POLICY_SHA256,
)
from infinity_context_core.ports.benchmark_unsealed_projection import (
    BenchmarkUnsealedProjectionScope,
    BenchmarkUnsealedRecoveryInventory,
)
from infinity_context_server.benchmark_unsealed_projection_absence import (
    ServerBenchmarkUnsealedProjectionAbsence,
)

pytestmark = pytest.mark.skipif(
    os.getenv("INFINITY_RUN_UNSEALED_DERIVED_SANDBOX_E2E") != "1",
    reason="requires fresh isolated Qdrant and Neo4j sandbox services",
)


class _InventoryPort:
    def __init__(self, inventory: BenchmarkUnsealedRecoveryInventory) -> None:
        self._inventory = inventory

    async def load_inventory(self, **_: object) -> BenchmarkUnsealedRecoveryInventory:
        return self._inventory


async def _run_contract() -> None:
    from neo4j import AsyncGraphDatabase
    from qdrant_client import AsyncQdrantClient, models

    qdrant_url = os.environ["INFINITY_SANDBOX_QDRANT_URL"]
    neo4j_uri = os.environ["INFINITY_SANDBOX_NEO4J_URI"]
    neo4j_password = os.environ["INFINITY_SANDBOX_NEO4J_PASSWORD"]
    run_id = uuid4().hex
    collection = f"unsealed_recovery_{run_id}"
    space_id = f"sandbox-space-{run_id}"
    memory_scope_id = f"scope-{run_id}"
    thread_id = f"thread-{run_id}"
    chunk_id = f"chunk-{run_id}"
    fact_id = f"fact-{run_id}"
    scope = BenchmarkUnsealedProjectionScope(
        memory_scope_id,
        thread_id,
        (chunk_id,),
        (fact_id,),
    )

    async def qdrant_factory() -> tuple[object, object]:
        return AsyncQdrantClient(url=qdrant_url, timeout=10), models

    qdrant = QdrantIdentityEvidence(
        client_factory=qdrant_factory,
        url=qdrant_url,
        collection_name=collection,
        projection_version="v1",
    )
    qdrant_client = AsyncQdrantClient(url=qdrant_url, timeout=10)
    neo4j_driver = AsyncGraphDatabase.driver(
        neo4j_uri,
        auth=("neo4j", neo4j_password),
    )
    graphiti = Neo4jGraphitiIdentityEvidenceAdapter(
        driver=neo4j_driver,
        target_commitment_sha256="a" * 64,
    )
    group_id = graphiti_group_id(space_id, memory_scope_id)
    group_prefix = group_id.rsplit("__", 1)[0] + "__"

    try:
        await qdrant_client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(size=1, distance=models.Distance.COSINE),
        )
        await _qdrant_upsert(
            qdrant_client,
            models,
            collection=collection,
            point_id=qdrant_point_id_for_chunk(chunk_id),
            chunk_id=chunk_id,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
        )
        await _neo4j_episode(
            neo4j_driver,
            run_id=run_id,
            uuid=f"episode-{run_id}",
            group_id=group_id,
            name=f"fact:{fact_id}",
        )
        record, inventory = _absence_inputs(
            space_id=space_id,
            scope=scope,
            qdrant_target=qdrant.target_commitment_sha256,
            graphiti_target="a" * 64,
        )
        absence = ServerBenchmarkUnsealedProjectionAbsence(
            inventory=_InventoryPort(inventory),
            qdrant=qdrant,
            graphiti=graphiti,
            qdrant_target_commitment_sha256=qdrant.target_commitment_sha256,
            graphiti_target_commitment_sha256="a" * 64,
        )
        proof = await absence.prove_absence(record=record)
        assert proof.qdrant_pass_receipt_sha256s[0] != proof.qdrant_pass_receipt_sha256s[1]
        assert proof.graphiti_pass_receipt_sha256s[0] != proof.graphiti_pass_receipt_sha256s[1]
        assert await _qdrant_count(qdrant_client, models, collection, space_id) == 0
        assert await _neo4j_prefix_count(neo4j_driver, group_prefix) == 0
        replay_proof = await absence.prove_absence(record=record)
        assert replay_proof.run_id_sha256 == proof.run_id_sha256

        moved_chunk_id = f"moved-{run_id}"
        moved_scope = BenchmarkUnsealedProjectionScope(
            memory_scope_id,
            thread_id,
            (moved_chunk_id,),
            (),
        )
        moved_point_id = qdrant_point_id_for_chunk(moved_chunk_id)
        await _qdrant_upsert(
            qdrant_client,
            models,
            collection=collection,
            point_id=moved_point_id,
            chunk_id=moved_chunk_id,
            space_id="foreign-space",
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
        )
        with pytest.raises(ValueError, match="moved or is malformed"):
            await qdrant.delete_benchmark_space_two_pass(
                space_id=space_id,
                scopes=(moved_scope,),
            )
        await _qdrant_delete(qdrant_client, models, collection, (moved_point_id,))

        unknown_point_id = str(uuid4())
        await _qdrant_upsert(
            qdrant_client,
            models,
            collection=collection,
            point_id=unknown_point_id,
            chunk_id=f"unknown-{run_id}",
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
        )
        with pytest.raises(ValueError, match="unknown space point"):
            await qdrant.delete_benchmark_space_two_pass(
                space_id=space_id,
                scopes=(moved_scope,),
            )
        await _qdrant_delete(qdrant_client, models, collection, (unknown_point_id,))

        moved_episode_id = f"moved-episode-{run_id}"
        await _neo4j_episode(
            neo4j_driver,
            run_id=run_id,
            uuid=moved_episode_id,
            group_id="foreign-group",
            name=f"fact:{fact_id}",
        )
        with pytest.raises(GraphitiIdentityEvidenceError, match="moved to a foreign group"):
            await graphiti.delete_benchmark_space_two_pass(
                space_id=space_id,
                scopes=(scope,),
            )
        await _neo4j_cleanup(neo4j_driver, run_id)

        await _neo4j_entity(
            neo4j_driver,
            run_id=run_id,
            uuid=f"unknown-entity-{run_id}",
            group_id=f"{group_prefix}unknown",
        )
        with pytest.raises(GraphitiIdentityEvidenceError, match="unknown group"):
            await graphiti.delete_benchmark_space_two_pass(
                space_id=space_id,
                scopes=(scope,),
            )
    finally:
        await _neo4j_cleanup(neo4j_driver, run_id)
        if await qdrant_client.collection_exists(collection):
            await qdrant_client.delete_collection(collection)
        await qdrant_client.close()
        await neo4j_driver.close()


def _absence_inputs(
    *,
    space_id: str,
    scope: BenchmarkUnsealedProjectionScope,
    qdrant_target: str,
    graphiti_target: str,
) -> tuple[SimpleNamespace, BenchmarkUnsealedRecoveryInventory]:
    run_id_sha256 = "b" * 64
    cleanup_plan_sha256 = "c" * 64
    cleanup_receipt_sha256 = "d" * 64
    inventory = BenchmarkUnsealedRecoveryInventory(
        run_id_sha256=run_id_sha256,
        space_id=space_id,
        cleanup_plan_sha256=cleanup_plan_sha256,
        cleanup_receipt_sha256=cleanup_receipt_sha256,
        scopes=(scope,),
        document_source_external_ids=(),
        episode_source_external_ids=(),
        chunk_source_external_ids=("source",),
        chunk_source_hashes=("hash",),
        delete_outbox_ids=(),
        inventory_sha256="e" * 64,
    )
    plan = {
        "qdrant": {
            "target_commitment_sha256": qdrant_target,
            "collection_projection_policy_sha256": QDRANT_COLLECTION_PROJECTION_POLICY_SHA256,
            "deterministic_scope_mapping_policy_sha256": QDRANT_SCOPE_MAPPING_POLICY_SHA256,
            "space_wide_scan_policy_sha256": QDRANT_SPACE_WIDE_SCAN_POLICY_SHA256,
        },
        "graphiti": {
            "target_commitment_sha256": graphiti_target,
            "group_mapping_policy_sha256": GRAPHITI_GROUP_MAPPING_POLICY_SHA256,
            "space_prefix_scan_policy_sha256": GRAPHITI_SPACE_PREFIX_SCAN_POLICY_SHA256,
        },
        "cognee": {
            "disposition": "not_projected",
            "policy_sha256": COGNEE_NOT_PROJECTED_POLICY_SHA256,
        },
    }
    record = SimpleNamespace(
        run_id_sha256=run_id_sha256,
        space_id=space_id,
        state="cleanup_pending",
        projection_cleanup_state="blocked",
        projection_manifest_json=None,
        projection_manifest_sha256=None,
        cleanup_receipt=SimpleNamespace(
            receipt_sha256=cleanup_receipt_sha256,
            cognee_delete_outbox_ids=(),
        ),
        cleanup_plan_json=plan,
        cleanup_plan_sha256=cleanup_plan_sha256,
        cleanup_plan_state="sealed",
    )
    return record, inventory


async def _qdrant_upsert(
    client: object,
    models: object,
    *,
    collection: str,
    point_id: str,
    chunk_id: str,
    space_id: str,
    memory_scope_id: str,
    thread_id: str,
) -> None:
    await client.upsert(
        collection_name=collection,
        points=[
            models.PointStruct(
                id=point_id,
                vector=[1.0],
                payload={
                    "chunk_id": chunk_id,
                    "space_id": space_id,
                    "memory_scope_id": memory_scope_id,
                    "thread_id": thread_id,
                    "projection_version": "v1",
                },
            )
        ],
        wait=True,
    )


async def _qdrant_delete(
    client: object,
    models: object,
    collection: str,
    point_ids: tuple[str, ...],
) -> None:
    await client.delete(
        collection_name=collection,
        points_selector=models.PointIdsList(points=list(point_ids)),
        wait=True,
    )


async def _qdrant_count(client: object, models: object, collection: str, space_id: str) -> int:
    result = await client.count(
        collection_name=collection,
        count_filter=models.Filter(
            must=[models.FieldCondition(key="space_id", match=models.MatchValue(value=space_id))]
        ),
        exact=True,
    )
    return result.count


async def _neo4j_episode(
    driver: object,
    *,
    run_id: str,
    uuid: str,
    group_id: str,
    name: str,
) -> None:
    await driver.execute_query(
        "CREATE (:Episodic {uuid: $uuid, group_id: $group_id, name: $name, "
        "entity_edges: [], sandbox_run_id: $run_id})",
        uuid=uuid,
        group_id=group_id,
        name=name,
        run_id=run_id,
    )


async def _neo4j_entity(driver: object, *, run_id: str, uuid: str, group_id: str) -> None:
    await driver.execute_query(
        "CREATE (:Entity {uuid: $uuid, group_id: $group_id, sandbox_run_id: $run_id})",
        uuid=uuid,
        group_id=group_id,
        run_id=run_id,
    )


async def _neo4j_prefix_count(driver: object, group_prefix: str) -> int:
    records, _, _ = await driver.execute_query(
        "MATCH (node) WHERE node.group_id STARTS WITH $group_prefix RETURN count(node) AS count",
        group_prefix=group_prefix,
    )
    return records[0]["count"]


async def _neo4j_cleanup(driver: object, run_id: str) -> None:
    await driver.execute_query(
        "MATCH (node {sandbox_run_id: $run_id}) DETACH DELETE node",
        run_id=run_id,
    )


def test_real_qdrant_and_neo4j_unsealed_recovery_contract() -> None:
    asyncio.run(_run_contract())
