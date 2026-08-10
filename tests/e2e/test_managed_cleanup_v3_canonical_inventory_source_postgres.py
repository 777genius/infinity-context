"""Fresh-Postgres proof for grouped cleanup inventory source semantics."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os

import pytest
from infinity_context_adapters.postgres.managed_cleanup_v3_canonical_inventory_source import (
    AsyncPostgresManagedCleanupV3CanonicalInventorySource,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_canonical_inventory_sql import (
    IDENTITY_SQL,
    JOB_SQL,
    canonical_evidence,
    cleanup_receipts_sql,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    LOCOMO_PROFILE,
    PROFILE_ORACLES,
    build_context,
    commitment,
)
from postgres_test_database import PostgresTestDatabase


def test_grouped_delete_uses_one_physical_job_with_two_linked_targets_on_fresh_postgres():
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_grouped_delete(database_url))


def _sha(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()


def _context():
    q_target, q_policy = _sha("qt"), _sha("qp")
    g_target, g_policy = _sha("gt"), _sha("gp")
    return build_context(
        profile_id=LOCOMO_PROFILE,
        manifest_context_sha256=_sha("manifest"),
        a1_terminal_commitment_sha256=_sha("a1"),
        run_id_sha256=_sha("run"),
        binding_commitment_sha256=_sha("binding"),
        publishable_profile_commitment_sha256=_sha("profile"),
        methodology_commitment_sha256=_sha("method"),
        dataset_sha256=str(PROFILE_ORACLES[LOCOMO_PROFILE]["dataset_sha256"]),
        admission_commitment_sha256=_sha("admit"),
        ingestion_root_sha256=_sha("ingest"),
        case_manifest_sha256=_sha("cases"),
        infinity_target_identity_sha256=_sha("target"),
        space_id="inventory-space",
        space_slug="inventory-space",
        cleanup_target_authority_sha256=_sha("cleanup-target"),
        qdrant_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "qdrant",
                "target_commitment_sha256": q_target,
                "policy_commitment_sha256": q_policy,
            },
        ),
        qdrant_target_commitment_sha256=q_target,
        qdrant_policy_commitment_sha256=q_policy,
        graphiti_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "graphiti",
                "target_commitment_sha256": g_target,
                "policy_commitment_sha256": g_policy,
            },
        ),
        graphiti_target_commitment_sha256=g_target,
        graphiti_policy_commitment_sha256=g_policy,
        cognee_policy_sha256=_sha("cognee"),
        namespace_policy_sha256=_sha("namespace"),
        cleanup_operation_stream_root_sha256=_sha("operations"),
        omitted_source_identity_root_sha256=str(
            PROFILE_ORACLES[LOCOMO_PROFILE]["omitted_source_identity_root_sha256"]
        ),
    )


async def _assert_grouped_delete(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="cleanup_v3_source", asyncpg=asyncpg
    )
    await database.recreate()
    connection = await database.connect()
    try:
        await connection.execute(_DDL)
        context = _context()
        await connection.execute(
            "INSERT INTO memory_scopes VALUES ('scope-1',$1,'scope-ref')",
            context.space_id,
        )
        await connection.execute(
            "INSERT INTO memory_threads VALUES ('thread-1',$1,'scope-1','thread-ref')",
            context.space_id,
        )
        await connection.execute(
            "INSERT INTO memory_documents VALUES ('document-1',$1,'scope-1','thread-1','source-1')",
            context.space_id,
        )
        await connection.executemany(
            "INSERT INTO memory_chunks VALUES "
            "($1,$2,'scope-1','thread-1','document-1','source-1',$3,'deleted')",
            [("chunk-1", context.space_id, 0), ("chunk-2", context.space_id, 1)],
        )
        await connection.execute(
            "INSERT INTO memory_outbox VALUES "
            "(77,'delete-77','vector.delete_chunks','benchmark_run',$1,NULL,$2::jsonb,"
            "'done',transaction_timestamp())",
            context.run_id_sha256,
            '{"chunk_ids":["chunk-1","chunk-2"]}',
        )
        await connection.execute(
            "INSERT INTO memory_projection_result_receipts VALUES "
            "(77,$1,$2,$3,'qdrant','delete','absent',2)",
            context.run_id_sha256,
            context.context_sha256,
            context.space_id,
        )
        for ordinal, (chunk_id, identity) in enumerate(
            (("chunk-1", "1" * 64), ("chunk-2", "2" * 64))
        ):
            await connection.execute(
                "INSERT INTO memory_projection_target_identities VALUES "
                "($1,'qdrant_point_id',$2,$3,$4,$5,$6)",
                context.run_id_sha256,
                identity,
                str(ordinal + 3) * 64,
                chunk_id,
                "a" * 64,
                context.qdrant_authority_sha256,
            )
            await connection.execute(
                "INSERT INTO memory_projection_receipt_identity_links VALUES "
                "(77,$1,'qdrant_point_id',$2,$3,$4)",
                context.run_id_sha256,
                identity,
                str(ordinal + 3) * 64,
                ordinal,
            )
        page = await AsyncPostgresManagedCleanupV3CanonicalInventorySource().read_page(
            connection,
            context=context,
            kind="qdrant_delete_jobs",
            after=None,
            limit=10,
        )
        assert [row.locator_json["physical_outbox_id"] for row in page.rows] == [77, 77]
        assert len({row.locator_json["logical_target_identity_sha256"] for row in page.rows}) == 2
        await _seed_delete_scale(connection, context, count=1_023)
        for paged_kind in ("qdrant_delete_jobs", "cleanup_outbox_receipts"):
            paged_source = AsyncPostgresManagedCleanupV3CanonicalInventorySource()
            first_page = await paged_source.read_page(
                connection, context=context, kind=paged_kind, after=None, limit=512
            )
            second_page = await paged_source.read_page(
                connection,
                context=context,
                kind=paged_kind,
                after=first_page.rows[-1].source_cursor,
                limit=512,
            )
            third_page = await paged_source.read_page(
                connection,
                context=context,
                kind=paged_kind,
                after=second_page.rows[-1].source_cursor,
                limit=512,
            )
            pages = (first_page, second_page, third_page)
            assert [len(item.rows) for item in pages] == [512, 512, 1]
            assert [item.exhausted for item in pages] == [False, False, True]
            locators = [
                (
                    row.locator_json["physical_outbox_id"],
                    row.locator_json["logical_target_identity_sha256"],
                )
                for item in pages
                for row in item.rows
            ]
            assert len(locators) == len(set(locators)) == 1_025
        canonical_row, authority_joins = canonical_evidence("memory_chunks")
        explain_sql = JOB_SQL.format(
            canonical_table="memory_chunks",
            canonical_row_json=canonical_row,
            canonical_authority_joins=authority_joins,
        )
        await connection.execute("SET enable_seqscan=off")
        raw_plan = await connection.fetchval(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {explain_sql}",
            context.run_id_sha256,
            context.context_sha256,
            context.space_id,
            "qdrant",
            "delete",
            "qdrant_point_id",
            ["vector.delete_chunks"],
            "benchmark_run",
            None,
            None,
            513,
        )
        plan = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
        encoded_plan = json.dumps(plan)
        assert "CTE Scan" in encoded_plan
        assert "Limit" in encoded_plan
        assert "ix_projection_links_outbox_page" in encoded_plan
        assert "memory_projection_result_receipts" in encoded_plan
        assert _relation_visits(plan, "memory_projection_receipt_identity_links") <= 1_026

        identity_sql = IDENTITY_SQL.format(
            canonical_table="memory_chunks",
            canonical_row_json=canonical_row,
            canonical_authority_joins=authority_joins,
        )
        identity_plan = await connection.fetchval(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {identity_sql}",
            context.run_id_sha256,
            context.context_sha256,
            context.space_id,
            "qdrant",
            "qdrant_point_id",
            ["vector.upsert_chunk", "vector.upsert_chunks"],
            "chunk",
            None,
            None,
            513,
        )
        identity_encoded = json.dumps(
            json.loads(identity_plan) if isinstance(identity_plan, str) else identity_plan
        )
        assert "Limit" in identity_encoded
        assert "memory_projection_receipt_identity_links" in identity_encoded
        assert "ix_projection_links_identity_outbox" in identity_encoded
        assert "ix_memory_scopes_space_id_id" in identity_encoded
        assert "ix_memory_threads_space_scope_id" in identity_encoded
        identity_cursor = await connection.fetchrow(
            "SELECT identity_sha256, identity_commitment_sha256 "
            "FROM memory_projection_target_identities "
            "WHERE run_id_sha256=$1 AND kind='qdrant_point_id' "
            "ORDER BY identity_sha256, identity_commitment_sha256 OFFSET 511 LIMIT 1",
            context.run_id_sha256,
        )
        second_identity_plan = await connection.fetchval(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {identity_sql}",
            context.run_id_sha256,
            context.context_sha256,
            context.space_id,
            "qdrant",
            "qdrant_point_id",
            ["vector.upsert_chunk", "vector.upsert_chunks"],
            "chunk",
            identity_cursor["identity_sha256"],
            identity_cursor["identity_commitment_sha256"],
            513,
        )
        if isinstance(second_identity_plan, str):
            second_identity_plan = json.loads(second_identity_plan)
        assert _relation_visits(second_identity_plan, "memory_projection_target_identities") <= 514
        assert (
            _page_scan_filter_removals(second_identity_plan, "memory_projection_target_identities")
            <= 1
        )

        cleanup_plan = await connection.fetchval(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {cleanup_receipts_sql()}",
            context.run_id_sha256,
            context.context_sha256,
            context.space_id,
            None,
            None,
            513,
        )
        cleanup_encoded = json.dumps(
            json.loads(cleanup_plan) if isinstance(cleanup_plan, str) else cleanup_plan
        )
        assert "Limit" in cleanup_encoded
        assert "memory_projection_receipt_identity_links" in cleanup_encoded
        assert "ix_projection_receipts_delete_page" in cleanup_encoded
        assert _relation_visits(cleanup_plan, "memory_projection_receipt_identity_links") <= 1_028
        assert _relation_visits(cleanup_plan, "memory_projection_result_receipts") <= 514
        assert _page_scan_filter_removals(cleanup_plan, "memory_projection_result_receipts") == 0
        cleanup_cursor = await connection.fetchrow(
            "SELECT r.outbox_id,l.identity_sha256 "
            "FROM memory_projection_result_receipts AS r "
            "JOIN memory_projection_receipt_identity_links AS l "
            "ON l.run_id_sha256=r.run_id_sha256 AND l.outbox_id=r.outbox_id "
            "WHERE r.run_id_sha256=$1 AND r.context_sha256=$2 AND r.space_id=$3 "
            "AND r.operation='delete' "
            "ORDER BY r.outbox_id,l.identity_sha256 OFFSET 511 LIMIT 1",
            context.run_id_sha256,
            context.context_sha256,
            context.space_id,
        )
        second_cleanup_plan = await connection.fetchval(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {cleanup_receipts_sql()}",
            context.run_id_sha256,
            context.context_sha256,
            context.space_id,
            cleanup_cursor["outbox_id"],
            cleanup_cursor["identity_sha256"],
            513,
        )
        if isinstance(second_cleanup_plan, str):
            second_cleanup_plan = json.loads(second_cleanup_plan)
        assert "ix_projection_receipts_delete_page" in json.dumps(second_cleanup_plan)
        assert _relation_visits(second_cleanup_plan, "memory_projection_result_receipts") <= 515
        assert (
            _page_scan_filter_removals(second_cleanup_plan, "memory_projection_result_receipts")
            == 0
        )
    finally:
        await connection.close()
        await database.drop()


def _relation_visits(plan: object, relation: str) -> int:
    if isinstance(plan, list):
        return sum(_relation_visits(item, relation) for item in plan)
    if not isinstance(plan, dict):
        return 0
    own = 0
    if plan.get("Relation Name") == relation:
        own = int(plan.get("Actual Rows", 0)) * int(plan.get("Actual Loops", 0))
    return own + sum(_relation_visits(value, relation) for value in plan.values())


def _page_scan_filter_removals(plan: object, relation: str) -> int:
    if isinstance(plan, list):
        return sum(_page_scan_filter_removals(item, relation) for item in plan)
    if not isinstance(plan, dict):
        return 0
    own = 0
    if plan.get("Relation Name") == relation and int(plan.get("Actual Rows", 0)) >= 512:
        own = int(plan.get("Rows Removed by Filter", 0)) * int(plan.get("Actual Loops", 0))
    return own + sum(_page_scan_filter_removals(value, relation) for value in plan.values())


async def _seed_delete_scale(connection, context, *, count: int) -> None:
    rows = range(1_000, 1_000 + count)
    await connection.executemany(
        "INSERT INTO memory_chunks VALUES "
        "($1,$2,'scope-1','thread-1','document-1','source-1',$3,'deleted')",
        [(f"chunk-{row}", context.space_id, row) for row in rows],
    )
    rows = range(1_000, 1_000 + count)
    await connection.executemany(
        "INSERT INTO memory_outbox VALUES "
        "($1,$2,'vector.delete_chunks','benchmark_run',$3,NULL,$4::jsonb,"
        "'done',transaction_timestamp())",
        [
            (
                row,
                f"delete-{row}",
                context.run_id_sha256,
                json.dumps({"chunk_ids": [f"chunk-{row}"]}),
            )
            for row in rows
        ],
    )
    rows = range(1_000, 1_000 + count)
    await connection.executemany(
        "INSERT INTO memory_projection_result_receipts VALUES "
        "($1,$2,$3,$4,'qdrant','delete','absent',1)",
        [(row, context.run_id_sha256, context.context_sha256, context.space_id) for row in rows],
    )
    identities = [
        (
            context.run_id_sha256,
            _sha(("identity", row)),
            _sha(("commitment", row)),
            f"chunk-{row}",
            "a" * 64,
            context.qdrant_authority_sha256,
            row,
        )
        for row in range(1_000, 1_000 + count)
    ]
    await connection.executemany(
        "INSERT INTO memory_projection_target_identities VALUES "
        "($1,'qdrant_point_id',$2,$3,$4,$5,$6)",
        [identity[:-1] for identity in identities],
    )
    await connection.executemany(
        "INSERT INTO memory_projection_receipt_identity_links VALUES "
        "($1,$2,'qdrant_point_id',$3,$4,0)",
        [
            (row, run_id, identity_sha256, identity_commitment_sha256)
            for (
                run_id,
                identity_sha256,
                identity_commitment_sha256,
                _canonical_source_id,
                _lineage_root,
                _authority,
                row,
            ) in identities
        ],
    )


_DDL = """
CREATE TABLE memory_scopes (id text PRIMARY KEY, space_id text, external_ref text);
CREATE INDEX ix_memory_scopes_space_id_id ON memory_scopes(space_id,id);
CREATE TABLE memory_threads (
  id text PRIMARY KEY, space_id text, memory_scope_id text, external_ref text
);
CREATE INDEX ix_memory_threads_space_scope_id
  ON memory_threads(space_id,memory_scope_id,id);
CREATE TABLE memory_documents (
  id text PRIMARY KEY, space_id text, memory_scope_id text, thread_id text,
  source_external_id text
);
CREATE TABLE memory_chunks (
  id text PRIMARY KEY, space_id text NOT NULL, memory_scope_id text, thread_id text,
  document_id text, source_external_id text, sequence integer, status text NOT NULL
);
CREATE TABLE memory_facts (
  id text PRIMARY KEY, space_id text NOT NULL, memory_scope_id text, thread_id text,
  version integer, status text NOT NULL
);
CREATE TABLE memory_fact_versions (id bigint, fact_id text, version integer);
CREATE TABLE memory_source_refs (
  id bigint PRIMARY KEY, fact_id text, fact_version integer
);
CREATE TABLE memory_episodes (id text PRIMARY KEY, space_id text NOT NULL);
CREATE TABLE memory_outbox (
  id integer PRIMARY KEY, message_key text, event_type text, aggregate_type text,
  aggregate_id text, aggregate_version integer, payload_json jsonb, status text,
  created_at timestamptz
);
CREATE TABLE memory_projection_result_receipts (
  outbox_id integer PRIMARY KEY, run_id_sha256 text, context_sha256 text, space_id text,
  lane text, operation text, result_state text, identity_count integer
);
CREATE TABLE memory_projection_target_identities (
  run_id_sha256 text, kind text, identity_sha256 text,
  identity_commitment_sha256 text, canonical_source_id text,
  lineage_root_sha256 text, target_authority_sha256 text,
  PRIMARY KEY (run_id_sha256,kind,identity_sha256)
);
CREATE TABLE memory_projection_receipt_identity_links (
  outbox_id integer, run_id_sha256 text, kind text, identity_sha256 text,
  identity_commitment_sha256 text, ordinal integer
);
CREATE INDEX ix_projection_receipts_cleanup_page
  ON memory_projection_result_receipts(run_id_sha256,context_sha256,space_id,outbox_id);
CREATE INDEX ix_projection_receipts_inventory_page
  ON memory_projection_result_receipts(
    run_id_sha256,context_sha256,space_id,lane,operation,outbox_id
  );
CREATE INDEX ix_projection_receipts_operation_page
  ON memory_projection_result_receipts(
    run_id_sha256,context_sha256,space_id,operation,outbox_id
  );
CREATE INDEX ix_projection_receipts_delete_page
  ON memory_projection_result_receipts(
    run_id_sha256,context_sha256,space_id,outbox_id
  ) WHERE operation='delete';
CREATE INDEX ix_projection_links_identity_outbox
  ON memory_projection_receipt_identity_links(
    run_id_sha256,kind,identity_sha256,identity_commitment_sha256,outbox_id
  ) INCLUDE (ordinal);
CREATE INDEX ix_projection_links_outbox_page
  ON memory_projection_receipt_identity_links(
    run_id_sha256,outbox_id,identity_sha256,kind,identity_commitment_sha256
  );
"""
