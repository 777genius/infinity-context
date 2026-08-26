"""Real strict-v4 LoCoMo fixture for fresh-Postgres cleanup E2E tests.

The fixture deliberately uses the public operation projector commitments, the
sealed SQLite expected-row authority, authenticated production-shaped outbox
receipts, the concrete 15-kind Postgres source, and the real materializer.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.managed_cleanup_v3_canonical_inventory_source import (
    AsyncPostgresManagedCleanupV3CanonicalInventorySource,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_authority import (
    SQLiteManagedCleanupV3ExpectedRowAuthority,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_inventory_materializer import (
    AsyncPostgresManagedCleanupV3InventoryMaterializer,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_scratch import (
    ManagedCleanupV3ReceiptProofScratch,
    create_receipt_scratch_schema,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_source_authenticator import (
    ManagedCleanupV3SourceEvidenceAuthenticator,
)
from infinity_context_adapters.postgres.projection_receipt_repository import (
    PostgresProjectionReceiptRepository,
    _identity_values,
    _receipt_values,
)
from infinity_context_core.features.projection_receipts import (
    ProjectionJobBinding,
    ProjectionMaterialization,
    ProjectionReceiptAuthenticator,
    ProjectionTargetIdentity,
    build_projection_result_receipt,
    projection_outbox_event_commitment,
)
from infinity_context_core.ports.benchmark_cleanup_plan import (
    CLEANUP_PLAN_LIMITS_POLICY_SHA256,
    CLEANUP_PLAN_SCHEMA_VERSION,
    COGNEE_NOT_PROJECTED_POLICY_SHA256,
    INFINITY_NAMESPACE_POLICY_SHA256,
)
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_fact_operation_material,
    managed_benchmark_fact_source_ref_descriptor,
    managed_benchmark_infinity_operation_sha256,
    managed_benchmark_text_sha256,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    LOCOMO_PROFILE,
    PROFILE_ORACLES,
    ManagedCleanupV3Operation,
    build_context,
    commitment,
    corpus_identity_sha256,
    fragment_commitments,
    memory_scope_external_ref_sha256,
    source_ref_commitments,
    thread_external_ref_sha256,
)
from infinity_context_core.ports.managed_cleanup_v3_paged_authority import (
    build_managed_cleanup_v3_authority,
    cleanup_operation_stream_root,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    MANAGED_MEM0_V6_AUTHORITY_SCHEMA_VERSION,
    MANAGED_MEM0_V6_LIMITS_POLICY_SHA256,
    MANAGED_MEM0_V6_PAGE_SIZE,
    PAGE_COMMITMENT_DOMAIN,
    TERMINAL_COMMITMENT_DOMAIN,
    ManagedMem0V6PagedManifestAuthority,
    uniqueness_receipt_sha256,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    authority_body as a1_authority_body,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    domain_sha256 as a1_domain_sha256,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    merkle_root as a1_merkle_root,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    page_body as a1_page_body,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_postgres_schema_upgrade_e2e import _install_versioned_schema_through

WHEN = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
RUN = "b" * 64
BINDING = "1" * 64
TARGET = "a" * 64
SPACE_ID = f"benchmark-space-{RUN[:48]}"
SPACE_SLUG = "managed-cleanup-v3-full-e2e"
AUTHENTICATOR = ProjectionReceiptAuthenticator(b"full-pg-e2e-receipt-key" + b"r" * 32)
INDEX_KEY = b"full-pg-e2e-index-key" + b"i" * 32
INVENTORY_KEY = b"full-pg-e2e-inventory-key" + b"v" * 32
CLEANUP_RECEIPT = "4" * 64


class _Stage:
    def __init__(self, context_sha256: str, expected: int) -> None:
        self.context_sha256 = context_sha256
        self.expected = expected
        self.claims: dict[int, str] = {}
        self.pages = []
        self.authority = None
        self.receipt = None

    def claim(self, *, sequence: int, operation_sha256: str) -> None:
        existing = self.claims.setdefault(sequence, operation_sha256)
        assert existing == operation_sha256

    def append(self, page) -> None:
        self.pages.append(page)

    def commit(self, authority):
        from infinity_context_core.ports.managed_cleanup_v3_contracts import (
            ManagedCleanupV3StoreReceipt,
        )

        self.authority = authority
        body = {
            "schema_version": "memory-comparison-paged-cleanup-store-receipt.v4",
            "context_sha256": self.context_sha256,
            "terminal_commitment_sha256": authority.terminal_commitment_sha256,
            "page_count": len(self.pages),
            "committed": True,
        }
        self.receipt = ManagedCleanupV3StoreReceipt(
            context_sha256=self.context_sha256,
            terminal_commitment_sha256=authority.terminal_commitment_sha256,
            page_count=len(self.pages),
            committed=True,
            receipt_sha256=commitment("store-receipt/v4", body),
        )
        return self.receipt

    def readback(self):
        return self.receipt

    def abort(self) -> None:
        return None


class _Store:
    stage: _Stage | None = None

    def begin(self, *, context_sha256: str, expected_operation_count: int):
        self.stage = _Stage(context_sha256, expected_operation_count)
        return self.stage


@dataclass(slots=True)
class FullPostgresHarness:
    database: PostgresTestDatabase
    context: object
    authority: object
    pages: tuple[object, ...]
    expected_rows: SQLiteManagedCleanupV3ExpectedRowAuthority
    receipt_scratch_db: sqlite3.Connection
    materializer: AsyncPostgresManagedCleanupV3InventoryMaterializer
    source_page_calls: dict[str, int]
    cleanup_receipt_sha256: str = CLEANUP_RECEIPT

    async def close(self) -> None:
        self.receipt_scratch_db.close()
        self.expected_rows.close()
        await self.database.drop()


class _CountingSource:
    def __init__(self) -> None:
        self._source = AsyncPostgresManagedCleanupV3CanonicalInventorySource()
        self.calls: dict[str, int] = {}

    async def read_page(self, connection, **values):
        kind = str(values["kind"])
        self.calls[kind] = self.calls.get(kind, 0) + 1
        return await self._source.read_page(connection, **values)


def _sha(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()


def cleanup_plan_pair(
    *, run_id: str, binding: str, target: str, space_slug: str
) -> tuple[dict[str, object], str]:
    def digest(character: str) -> str:
        return character * 64

    plan: dict[str, object] = {
        "schema_version": CLEANUP_PLAN_SCHEMA_VERSION,
        "run_id_sha256": run_id,
        "binding_commitment_sha256": binding,
        "infinity_target_identity_sha256": target,
        "space_id": f"benchmark-space-{run_id[:48]}",
        "space_slug": space_slug,
        "profile_id": "repository-test",
        "ordered_case_sha256": [digest("1")],
        "corpora": [
            {
                "ordinal": 0,
                "corpus_id_sha256": digest("2"),
                "managed_corpus_projection_sha256": digest("3"),
                "memory_scope_external_ref_sha256": digest("4"),
                "thread_external_ref_sha256": digest("5"),
                "infinity_lane": "fact",
                "ordered_infinity_operation_sha256": [digest("a")],
                "ordered_infinity_source_external_id_sha256": [digest("b")],
                "ordered_infinity_content_sha256": [digest("c")],
                "ordered_document_fragment_count": [],
                "expected_fact_count": 1,
                "expected_document_count": 0,
                "expected_chunk_count": 0,
                "mem0_corpus_identity_sha256": digest("6"),
                "ordered_mem0_source_id_sha256": [digest("5")],
                "ordered_mem0_unit_identity_sha256": [digest("7")],
                "expected_ingest_unit_count": 1,
            }
        ],
        "mem0": {
            "admission_commitment_sha256": digest("8"),
            "ingestion_manifest_sha256": digest("9"),
            "ingestion_root_sha256": digest("d"),
            "expected_operation_count": 1,
        },
        "infinity_namespace_policy_sha256": INFINITY_NAMESPACE_POLICY_SHA256,
        "qdrant": {
            "target_commitment_sha256": digest("e"),
            "collection_projection_policy_sha256": digest("1"),
            "deterministic_scope_mapping_policy_sha256": digest("2"),
            "space_wide_scan_policy_sha256": digest("3"),
        },
        "graphiti": {
            "target_commitment_sha256": digest("4"),
            "group_mapping_policy_sha256": digest("5"),
            "space_prefix_scan_policy_sha256": digest("6"),
        },
        "cognee": {
            "disposition": "not_projected",
            "policy_sha256": COGNEE_NOT_PROJECTED_POLICY_SHA256,
        },
        "cardinality": {
            "case_count": 1,
            "corpus_count": 1,
            "mem0_source_identity_count": 1,
            "expected_ingest_unit_count": 1,
            "infinity_operation_count": 1,
            "expected_fact_count": 1,
            "expected_document_count": 0,
            "expected_chunk_count": 0,
        },
        "limits_policy_sha256": CLEANUP_PLAN_LIMITS_POLICY_SHA256,
    }
    encoded = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    return plan, hashlib.sha256(encoded).hexdigest()


def _a1_authority(context, count: int) -> ManagedMem0V6PagedManifestAuthority:
    pages = []
    for page_index, start in enumerate(range(0, count, MANAGED_MEM0_V6_PAGE_SIZE)):
        operations = tuple(
            _sha(("a1-operation", sequence))
            for sequence in range(start, min(start + MANAGED_MEM0_V6_PAGE_SIZE, count))
        )
        body = a1_page_body(
            profile_id=context.profile_id,
            manifest_context_sha256=context.manifest_context_sha256,
            page_index=page_index,
            start_sequence=start,
            ordered_operation_sha256=operations,
        )
        pages.append(a1_domain_sha256(PAGE_COMMITMENT_DOMAIN, body))
    ordered = tuple(pages)
    root = a1_merkle_root(ordered)
    unique = uniqueness_receipt_sha256(context.manifest_context_sha256, count, root)
    body = a1_authority_body(
        profile_id=context.profile_id,
        manifest_context_sha256=context.manifest_context_sha256,
        operation_count=count,
        ordered_page_commitment_sha256=ordered,
        pages_merkle_root_sha256=root,
        uniqueness_receipt_sha256_value=unique,
    )
    return ManagedMem0V6PagedManifestAuthority(
        profile_id=context.profile_id,
        manifest_context_sha256=context.manifest_context_sha256,
        operation_count=count,
        page_size=MANAGED_MEM0_V6_PAGE_SIZE,
        page_count=len(ordered),
        ordered_page_commitment_sha256=ordered,
        pages_merkle_root_sha256=root,
        uniqueness_receipt_sha256=unique,
        limits_policy_sha256=MANAGED_MEM0_V6_LIMITS_POLICY_SHA256,
        terminal_commitment_sha256=a1_domain_sha256(TERMINAL_COMMITMENT_DOMAIN, body),
        schema_version=MANAGED_MEM0_V6_AUTHORITY_SCHEMA_VERSION,
    )


def _fact_values(sequence: int) -> tuple[str, str, str, str, str, int]:
    count = int(PROFILE_ORACLES[LOCOMO_PROFILE]["operation_count"])
    corpus_count = int(PROFILE_ORACLES[LOCOMO_PROFILE]["corpus_count"])
    corpus = sequence * corpus_count // count
    return (
        f"scope-{corpus}",
        f"thread-{corpus}",
        f"benchmark-corpus:{corpus}",
        f"benchmark-thread:{corpus}",
        f"source:{sequence}",
        corpus,
    )


def _operation(sequence: int) -> ManagedCleanupV3Operation:
    _scope_id, _thread_id, scope_ref, thread_ref, source_id, _corpus = _fact_values(sequence)
    text = f"canonical fact {sequence}"
    raw_ref = managed_benchmark_fact_source_ref_descriptor(
        source_type="memory_comparison_benchmark",
        source_id=source_id,
        quote_preview=text,
    )
    refs_sha, descriptors, refs_root = source_ref_commitments((raw_ref,))
    fragments_sha, fragments, fragments_root = fragment_commitments(())
    material = managed_benchmark_fact_operation_material(
        source_external_id_sha256=managed_benchmark_text_sha256(source_id),
        content_sha256=managed_benchmark_text_sha256(text),
        kind="note",
        classification="internal",
        source_refs=(raw_ref,),
    )
    scope_sha = memory_scope_external_ref_sha256(scope_ref)
    thread_sha = thread_external_ref_sha256(thread_ref)
    body = {
        "schema_version": "memory-comparison-paged-cleanup-operation.v4",
        "sequence": sequence,
        "lane": "fact",
        "corpus_identity_sha256": corpus_identity_sha256(
            lane="fact",
            memory_scope_external_ref_sha256=scope_sha,
            thread_external_ref_sha256=thread_sha,
        ),
        "memory_scope_external_ref_sha256": scope_sha,
        "thread_external_ref_sha256": thread_sha,
        "source_identity_sha256": managed_benchmark_text_sha256(source_id),
        "source_content_sha256": managed_benchmark_text_sha256(text),
        "operation_commitment_sha256": managed_benchmark_infinity_operation_sha256(material),
        "a1_operation_sha256": _sha(("a1-operation", sequence)),
        "original_pair_identity_sha256": None,
        "valid_message_count": 1,
        "source_refs_sha256": refs_sha,
        "ordered_source_ref_descriptor_sha256": list(descriptors),
        "source_ref_root_sha256": refs_root,
        "fragments_sha256": fragments_sha,
        "ordered_fragment_descriptor_sha256": list(fragments),
        "fragment_root_sha256": fragments_root,
    }
    return ManagedCleanupV3Operation(
        **{
            key: tuple(value)
            if key
            in {
                "ordered_source_ref_descriptor_sha256",
                "ordered_fragment_descriptor_sha256",
            }
            else value
            for key, value in body.items()
            if key != "schema_version"
        },
        operation_sha256=commitment("operation/v4", body),
    )


def build_strict_v4_material():
    count = int(PROFILE_ORACLES[LOCOMO_PROFILE]["operation_count"])
    operations = tuple(_operation(sequence) for sequence in range(count))
    cleanup_root = cleanup_operation_stream_root(
        profile_id=LOCOMO_PROFILE,
        operation_sha256=(item.operation_sha256 for item in operations),
    )
    cleanup_plan, _cleanup_plan_sha = cleanup_plan_pair(
        run_id=RUN,
        binding=BINDING,
        target=TARGET,
        space_slug=SPACE_SLUG,
    )
    q_target = cleanup_plan["qdrant"]["target_commitment_sha256"]
    g_target = cleanup_plan["graphiti"]["target_commitment_sha256"]
    q_policy, g_policy = "7" * 64, "8" * 64
    context = build_context(
        profile_id=LOCOMO_PROFILE,
        manifest_context_sha256="0" * 64,
        a1_terminal_commitment_sha256="1" * 64,
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        publishable_profile_commitment_sha256="2" * 64,
        methodology_commitment_sha256="3" * 64,
        dataset_sha256=str(PROFILE_ORACLES[LOCOMO_PROFILE]["dataset_sha256"]),
        admission_commitment_sha256="4" * 64,
        ingestion_root_sha256="d" * 64,
        case_manifest_sha256="5" * 64,
        infinity_target_identity_sha256=TARGET,
        space_id=SPACE_ID,
        space_slug=SPACE_SLUG,
        cleanup_target_authority_sha256="6" * 64,
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
        cognee_policy_sha256="a" * 64,
        namespace_policy_sha256="b" * 64,
        cleanup_operation_stream_root_sha256=cleanup_root,
        omitted_source_identity_root_sha256=str(
            PROFILE_ORACLES[LOCOMO_PROFILE]["omitted_source_identity_root_sha256"]
        ),
    )
    # The public A1 helper binds this fixed manifest terminal into the context.
    context_values = context.payload()
    context_values.pop("schema_version")
    context_values.pop("context_sha256")
    context_values["a1_terminal_commitment_sha256"] = _a1_authority(
        context, count
    ).terminal_commitment_sha256
    context = build_context(**context_values)
    store = _Store()
    authority, _receipt = build_managed_cleanup_v3_authority(
        context=context,
        operations=operations,
        a1_authority=_a1_authority(context, count),
        store=store,
    )
    assert store.stage is not None
    return context, authority, tuple(store.stage.pages), operations


async def create_full_postgres_harness(database_url: str, work_dir: Path) -> FullPostgresHarness:
    import asyncpg

    database = PostgresTestDatabase.from_url(
        database_url, prefix="cleanup_v3_full", asyncpg=asyncpg
    )
    await database.recreate()
    try:
        await _install_versioned_schema_through(database, "0034_")
        engine = build_async_engine(database.app_url)
        try:
            result = await upgrade_schema(engine)
            assert result.current == "0050_locator_profile_outbox_transaction_coalescing"
        finally:
            await engine.dispose()
        context, authority, pages, operations = build_strict_v4_material()
        await _seed_canonical_and_projection(database, context, authority, operations)
        index = SQLiteManagedCleanupV3ExpectedRowAuthority.create(
            work_dir / "expected-rows.sqlite3",
            context=context,
            authority=authority,
            pages=pages,
            authentication_key=INDEX_KEY,
        )
        receipt_scratch_db = sqlite3.connect(work_dir / "receipt-scratch.sqlite3")
        create_receipt_scratch_schema(receipt_scratch_db)
        receipt_scratch = ManagedCleanupV3ReceiptProofScratch(
            receipt_scratch_db,
            INDEX_KEY,
            AUTHENTICATOR,
        )
        evidence = ManagedCleanupV3SourceEvidenceAuthenticator(
            AUTHENTICATOR,
            index,
            receipt_scratch,
        )

        async def connect():
            return await asyncpg.connect(database.raw_dsn)

        async def assert_fenced(connection, expected_context):
            row = await connection.fetchrow(
                """
                SELECT state, projection_cleanup_state
                FROM memory_comparison_benchmark_runs
                WHERE run_id_sha256=$1
                FOR SHARE
                """,
                expected_context.run_id_sha256,
            )
            assert row is not None and tuple(row.values()) == ("cleanup_pending", "pending")

        source = _CountingSource()
        materializer = AsyncPostgresManagedCleanupV3InventoryMaterializer(
            connect=connect,
            source=source,
            authenticate_evidence=evidence,
            assert_writer_fenced=assert_fenced,
            hmac_key=INVENTORY_KEY,
            projection_authenticator=AUTHENTICATOR,
        )
        return FullPostgresHarness(
            database,
            context,
            authority,
            pages,
            index,
            receipt_scratch_db,
            materializer,
            source.calls,
        )
    except BaseException:
        await database.drop()
        raise


async def _seed_canonical_and_projection(database, context, authority, operations) -> None:
    connection = await database.connect()
    cleanup_plan, cleanup_plan_sha = cleanup_plan_pair(
        run_id=RUN, binding=BINDING, target=TARGET, space_slug=SPACE_SLUG
    )
    try:
        await connection.execute(
            """
            INSERT INTO memory_spaces(id,slug,name,status,created_at,updated_at)
            VALUES($1,$2,'Full E2E','active',$3,$3)
            """,
            SPACE_ID,
            SPACE_SLUG,
            WHEN,
        )
        await connection.execute(
            """INSERT INTO memory_comparison_benchmark_runs(
                 run_id_sha256,binding_commitment_sha256,infinity_target_identity_sha256,
                 space_id,space_slug,idempotency_key_sha256,registration_fingerprint_sha256,
                 state,cleanup_fingerprint_sha256,cleanup_receipt_json,created_at,updated_at,
                 projection_manifest_json,projection_manifest_sha256,projection_cleanup_state,
                 cleanup_plan_json,cleanup_plan_sha256,cleanup_plan_state)
               VALUES($1,$2,$3,$4,$5,$6,$7,'active',$8,$9::jsonb,$10,$10,
                      $11::jsonb,$12,'unsealed',$13::jsonb,$14,'sealed')""",
            RUN,
            BINDING,
            TARGET,
            SPACE_ID,
            SPACE_SLUG,
            "2" * 64,
            "3" * 64,
            None,
            None,
            WHEN,
            None,
            None,
            json.dumps(cleanup_plan),
            cleanup_plan_sha,
        )
        scopes, threads = [], []
        for corpus in range(int(PROFILE_ORACLES[LOCOMO_PROFILE]["corpus_count"])):
            scopes.append(
                (
                    f"scope-{corpus}",
                    SPACE_ID,
                    f"benchmark-corpus:{corpus}",
                    f"Scope {corpus}",
                    "deleted",
                    WHEN,
                    WHEN,
                )
            )
            threads.append(
                (
                    f"thread-{corpus}",
                    SPACE_ID,
                    f"scope-{corpus}",
                    f"benchmark-thread:{corpus}",
                    "deleted",
                    WHEN,
                    WHEN,
                )
            )
        await connection.executemany(
            """
            INSERT INTO memory_scopes(
              id,space_id,external_ref,name,status,created_at,updated_at
            ) VALUES($1,$2,$3,$4,$5,$6,$7)
            """,
            scopes,
        )
        await connection.executemany(
            """
            INSERT INTO memory_threads(
              id,space_id,memory_scope_id,external_ref,status,created_at,updated_at
            ) VALUES($1,$2,$3,$4,$5,$6,$7)
            """,
            threads,
        )
        facts, versions, refs = [], [], []
        for sequence, _operation_item in enumerate(operations):
            scope_id, thread_id, _scope_ref, _thread_ref, source_id, _corpus = _fact_values(
                sequence
            )
            fact_id, text = f"fact-{sequence:05d}", f"canonical fact {sequence}"
            facts.append(
                (
                    fact_id,
                    SPACE_ID,
                    scope_id,
                    thread_id,
                    "note",
                    text,
                    "deleted",
                    "medium",
                    "medium",
                    "internal",
                    1,
                    WHEN,
                    WHEN,
                )
            )
            versions.append((fact_id, 1, text, "deleted", "[]", "{}", WHEN))
            refs.append((sequence + 1, fact_id, 1, "memory_comparison_benchmark", source_id, text))
        await connection.executemany(
            """
            INSERT INTO memory_facts(
              id,space_id,memory_scope_id,thread_id,kind,text,status,confidence,
              trust_level,classification,version,created_at,updated_at
            ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            """,
            facts,
        )
        await connection.executemany(
            """
            INSERT INTO memory_fact_versions(
              fact_id,version,text,status,source_refs_json,snapshot_json,created_at
            ) VALUES($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7)
            """,
            versions,
        )
        await connection.executemany(
            """
            INSERT INTO memory_source_refs(
              id,fact_id,fact_version,source_type,source_id,quote_preview
            ) VALUES($1,$2,$3,$4,$5,$6)
            """,
            refs,
        )
    finally:
        await connection.close()

    engine = build_async_engine(database.app_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session, session.begin():
            assert await PostgresProjectionReceiptRepository(
                session, AUTHENTICATOR
            ).register_context_authority(context=context, authority=authority, registered_at=WHEN)
    finally:
        await engine.dispose()
    await _seed_projection_evidence(database, context, operations)
    connection = await database.connect()
    try:
        await connection.execute(
            """
            UPDATE memory_comparison_benchmark_runs
            SET state='cleanup_pending',
                cleanup_fingerprint_sha256=$2,
                cleanup_receipt_json=$3::jsonb,
                projection_manifest_json=$4::jsonb,
                projection_manifest_sha256=$5,
                projection_cleanup_state='pending'
            WHERE run_id_sha256=$1
            """,
            RUN,
            "6" * 64,
            json.dumps({"disposition": "cleanup_pending"}),
            json.dumps({"sealed": True}),
            "5" * 64,
        )
    finally:
        await connection.close()


async def _seed_projection_evidence(database, context, operations) -> None:
    connection = await database.connect()
    outboxes, identities, receipts, links = [], {}, [], []
    for sequence, _operation_item in enumerate(operations):
        scope_id, thread_id, _scope_ref, _thread_ref, _source_id, _corpus = _fact_values(sequence)
        fact_id = f"fact-{sequence:05d}"
        target_items = (
            ProjectionTargetIdentity(
                "graphiti_episode_name",
                fact_id,
                f"fact:{fact_id}",
                context.ingestion_root_sha256,
                context.graphiti_authority_sha256,
            ),
            ProjectionTargetIdentity(
                "graphiti_episode_uuid",
                fact_id,
                f"00000000-0000-4000-8000-{sequence:012d}",
                context.ingestion_root_sha256,
                context.graphiti_authority_sha256,
            ),
        )
        for operation, outbox_id in (
            ("upsert", sequence + 1),
            ("delete", len(operations) + sequence + 1),
        ):
            message_key = f"graph-{operation}-{fact_id}"
            event_type = "graph.upsert_fact" if operation == "upsert" else "graph.delete_fact"
            aggregate_type = "fact" if operation == "upsert" else "benchmark_run"
            aggregate_version = 1 if operation == "upsert" else None
            payload = (
                {
                    "message_id": message_key,
                    "fact_id": fact_id,
                    "version": 1,
                    "space_id": SPACE_ID,
                    "memory_scope_id": scope_id,
                    "thread_id": thread_id,
                    "occurred_at": WHEN.isoformat(),
                }
                if operation == "upsert"
                else {"fact_id": fact_id, "space_id": SPACE_ID, "cleanup_run_id_sha256": RUN}
            )
            event_sha = projection_outbox_event_commitment(
                message_key=message_key,
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=fact_id,
                aggregate_version=aggregate_version,
                payload=payload,
                created_at=WHEN.isoformat(),
            )
            binding = ProjectionJobBinding(
                outbox_id=outbox_id,
                run_id_sha256=RUN,
                context_sha256=context.context_sha256,
                lane="graphiti",
                space_id=SPACE_ID,
                memory_scope_id=scope_id,
                thread_id=thread_id,
                aggregate_type=aggregate_type,
                aggregate_id=fact_id,
                aggregate_version=aggregate_version,
                target_authority_sha256=context.graphiti_authority_sha256,
                worker_authority_sha256=AUTHENTICATOR.authority_sha256,
                lineage_root_sha256=context.ingestion_root_sha256,
                outbox_event_commitment_sha256=event_sha,
            )
            receipt = build_projection_result_receipt(
                binding=binding,
                materialization=ProjectionMaterialization(
                    binding.projection_key_sha256, target_items, WHEN
                ),
                authenticator=AUTHENTICATOR,
                persisted_at=WHEN,
                operation=operation,
                result_state="present" if operation == "upsert" else "absent",
            )
            outboxes.append(
                (
                    outbox_id,
                    message_key,
                    event_type,
                    aggregate_type,
                    fact_id,
                    aggregate_version,
                    json.dumps(payload),
                    "done",
                    0,
                    WHEN,
                    WHEN,
                    WHEN,
                )
            )
            receipt_values = _receipt_values(receipt)
            receipts.append(tuple(receipt_values[name] for name in _RECEIPT_COLUMNS))
            for ordinal, item in enumerate(receipt.identities):
                identity_values = _identity_values(receipt, item)
                identity_key = (
                    identity_values["run_id_sha256"],
                    identity_values["kind"],
                    identity_values["identity_sha256"],
                )
                identities[identity_key] = tuple(
                    identity_values[name] for name in _IDENTITY_COLUMNS
                )
                links.append(
                    (
                        outbox_id,
                        RUN,
                        item.identity.kind,
                        item.identity_sha256,
                        item.identity_commitment_sha256,
                        ordinal,
                    )
                )
    try:
        await connection.executemany(
            """
            INSERT INTO memory_outbox(
              id,message_key,event_type,aggregate_type,aggregate_id,aggregate_version,
              payload_json,status,attempt_count,next_attempt_at,created_at,updated_at
            ) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11,$12)
            """,
            outboxes,
        )
        identity_fields = ",".join(_IDENTITY_COLUMNS)
        identity_args = ",".join(f"${index}" for index in range(1, len(_IDENTITY_COLUMNS) + 1))
        await connection.executemany(
            f"INSERT INTO memory_projection_target_identities({identity_fields}) "
            f"VALUES({identity_args})",
            list(identities.values()),
        )
        receipt_fields = ",".join(_RECEIPT_COLUMNS)
        receipt_args = ",".join(f"${index}" for index in range(1, len(_RECEIPT_COLUMNS) + 1))
        await connection.executemany(
            f"INSERT INTO memory_projection_result_receipts({receipt_fields}) "
            f"VALUES({receipt_args})",
            receipts,
        )
        await connection.executemany(
            """
            INSERT INTO memory_projection_receipt_identity_links(
              outbox_id,run_id_sha256,kind,identity_sha256,
              identity_commitment_sha256,ordinal
            ) VALUES($1,$2,$3,$4,$5,$6)
            """,
            links,
        )
    finally:
        await connection.close()


_IDENTITY_COLUMNS = (
    "run_id_sha256",
    "kind",
    "identity_sha256",
    "identity_commitment_sha256",
    "canonical_source_id",
    "physical_identity",
    "lineage_root_sha256",
    "target_authority_sha256",
    "identity_mac_sha256",
    "created_at",
)
_RECEIPT_COLUMNS = (
    "outbox_id",
    "run_id_sha256",
    "context_sha256",
    "lane",
    "operation",
    "result_state",
    "space_id",
    "memory_scope_id",
    "thread_id",
    "aggregate_type",
    "aggregate_id",
    "aggregate_version",
    "target_authority_sha256",
    "worker_authority_sha256",
    "outbox_event_commitment_sha256",
    "identity_count",
    "ordered_identity_root_sha256",
    "lineage_root_sha256",
    "provider_completed_at",
    "persisted_at",
    "receipt_sha256",
    "receipt_mac_sha256",
)


__all__ = (
    "CLEANUP_RECEIPT",
    "FullPostgresHarness",
    "build_strict_v4_material",
    "create_full_postgres_harness",
)
