from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime

import pytest
from infinity_context_adapters.postgres.managed_cleanup_v3_canonical_inventory_source import (
    AsyncPostgresManagedCleanupV3CanonicalInventorySource,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_inventory_materializer import (
    InventorySourceRow,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_json import (
    strict_json_object as _json_object,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_source_authenticator import (
    ManagedCleanupV3SourceEvidenceAuthenticator,
)
from infinity_context_adapters.qdrant.identity_evidence import qdrant_point_id_for_chunk
from infinity_context_core.features.projection_receipts import (
    ProjectionJobBinding,
    ProjectionMaterialization,
    ProjectionReceiptAuthenticator,
    ProjectionTargetIdentity,
    build_projection_result_receipt,
    projection_outbox_event_commitment,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    LOCOMO_PROFILE,
    PROFILE_ORACLES,
    ManagedCleanupV3Error,
    build_context,
    commitment,
)
from infinity_context_core.ports.managed_cleanup_v3_recovery import INVENTORY_KINDS


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _sha(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()


@pytest.mark.parametrize(
    "value",
    ["[]", "null", '{"duplicate":1,"duplicate":2}', '{"nan":NaN}', ["not-object"]],
)
def test_json_object_boundary_rejects_noncanonical_or_nonobject_values(value):
    with pytest.raises(ManagedCleanupV3Error, match="json_invalid"):
        _json_object(value, "managed_cleanup_v3_inventory_source_json_invalid")


def test_json_object_boundary_decodes_asyncpg_jsonb_text_exactly():
    assert _json_object(
        '{"locator":{"id":"chunk-1"}}',
        "managed_cleanup_v3_inventory_source_json_invalid",
    ) == {"locator": {"id": "chunk-1"}}


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


class _Connection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self.rows


class _ExpectedRows:
    def __init__(self):
        self.calls = []

    async def verify_expected_row(self, **values):
        self.calls.append(values)

    def begin_verification(self, terminal, session):
        self.calls.append(("begin", terminal, session))

    def begin_new_verification(self, terminal, session):
        self.calls.append(("begin_new", terminal, session))

    def finalize_verification(self, terminal, session):
        self.calls.append(("finalize", terminal, session))

    def abort_verification(self, terminal, session):
        self.calls.append(("abort", terminal, session))


class _ReceiptScratch:
    def __init__(self):
        self.calls = []

    def begin_new(self, terminal, session):
        self.calls.append(("begin_new", terminal, session))

    async def prepare_receipts(self, connection, context, terminal, session):
        self.calls.append(("prepare", terminal, session))

    def consume(self, terminal, session, kind, outbox, receipt, link, identity):
        self.calls.append(("consume", kind, receipt.get("outbox_id"), link.get("ordinal")))

    def finalize(self, terminal, session):
        self.calls.append(("finalize", terminal, session))

    def flush_verification_page(self, terminal, session):
        self.calls.append(("flush", terminal, session))

    def abort(self, terminal, session):
        self.calls.append(("abort", terminal, session))


@pytest.mark.anyio
async def test_source_authenticator_delegates_one_terminal_bound_lifecycle():
    expected_rows = _ExpectedRows()
    verifier = ManagedCleanupV3SourceEvidenceAuthenticator(
        ProjectionReceiptAuthenticator(b"r" * 32), expected_rows, _ReceiptScratch()
    )

    await verifier.begin_verification("f" * 64, "e" * 64)
    await verifier.begin_new_verification("f" * 64, "d" * 64)
    await verifier.finalize_verification("f" * 64, "e" * 64)
    await verifier.abort_verification("f" * 64, "e" * 64)

    assert expected_rows.calls == [
        ("begin", "f" * 64, "e" * 64),
        ("begin_new", "f" * 64, "d" * 64),
        ("finalize", "f" * 64, "e" * 64),
        ("abort", "f" * 64, "e" * 64),
    ]


@pytest.mark.anyio
async def test_all_fifteen_kinds_route_to_bounded_keyset_queries():
    source = AsyncPostgresManagedCleanupV3CanonicalInventorySource()
    for kind in INVENTORY_KINDS:
        connection = _Connection()
        page = await source.read_page(
            connection, context=_context(), kind=kind, after=None, limit=512
        )
        assert page.exhausted
        assert page.rows == ()
        if kind != "unsupported_rows":
            assert connection.calls[0][1][-1] == 512
            assert "ORDER BY" in connection.calls[0][0]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kind",
    [
        "qdrant_target_identities",
        "graphiti_target_uuids",
        "qdrant_upsert_jobs",
        "graphiti_delete_jobs",
        "cleanup_outbox_receipts",
    ],
)
async def test_projection_queries_bound_candidates_before_canonical_evidence(kind):
    connection = _Connection()
    await AsyncPostgresManagedCleanupV3CanonicalInventorySource().read_page(
        connection, context=_context(), kind=kind, after=None, limit=512
    )

    sql, args = connection.calls[0]
    candidate_end = sql.index(")\nSELECT jsonb_build_object")
    assert "candidates AS MATERIALIZED" in sql[:candidate_end]
    assert "LIMIT" in sql[:candidate_end]
    if kind == "cleanup_outbox_receipts":
        candidate_sql = sql[:candidate_end]
        assert candidate_sql.index("FROM memory_projection_result_receipts AS r") < (
            candidate_sql.index("memory_projection_receipt_identity_links AS l")
        )
        assert "r.operation = 'delete'" in candidate_sql
        assert sql.index("LEFT JOIN LATERAL (", candidate_end) > candidate_end
        assert "FROM memory_chunks AS c" in sql[candidate_end:]
        assert "FROM memory_facts AS f" in sql[candidate_end:]
    else:
        canonical_table = "memory_chunks" if kind.startswith("qdrant") else "memory_facts"
        lateral_start = sql.index("JOIN LATERAL (", candidate_end)
        assert sql.index(f"FROM {canonical_table} AS c", lateral_start) > lateral_start
        assert sql.index("LIMIT 1", lateral_start) > lateral_start
    assert args[-1] == 512
    assert "count(*) OVER" not in sql


@pytest.mark.anyio
async def test_grouped_qdrant_delete_is_one_physical_job_with_per_target_coverage():
    rows = [
        {
            "locator_json": {
                "physical_outbox_id": 77,
                "logical_target_identity_sha256": identity,
            },
            "row_json": {"outbox": {"id": 77}, "identity": {"identity_sha256": identity}},
            "cursor_1": 77,
            "cursor_2": identity,
        }
        for identity in ("1" * 64, "2" * 64)
    ]
    connection = _Connection(rows)
    page = await AsyncPostgresManagedCleanupV3CanonicalInventorySource().read_page(
        connection,
        context=_context(),
        kind="qdrant_delete_jobs",
        after=None,
        limit=3,
    )

    assert [row.locator_json["physical_outbox_id"] for row in page.rows] == [77, 77]
    assert len({row.locator_json["logical_target_identity_sha256"] for row in page.rows}) == 2
    sql, args = connection.calls[0]
    assert args[3:8] == (
        "qdrant",
        "delete",
        "qdrant_point_id",
        ["vector.delete_chunks"],
        "benchmark_run",
    )
    assert "o.status = 'done'" in sql


@pytest.mark.anyio
async def test_exact_full_page_continues_without_unbounded_lookahead():
    rows = [
        {
            "locator_json": {"id": f"scope-{index}"},
            "row_json": {"id": f"scope-{index}"},
            "cursor_1": f"scope-{index}",
        }
        for index in range(2)
    ]
    connection = _Connection(rows)
    source = AsyncPostgresManagedCleanupV3CanonicalInventorySource()
    first = await source.read_page(
        connection, context=_context(), kind="memory_scopes", after=None, limit=2
    )
    assert not first.exhausted
    assert first.rows[-1].source_cursor == "scope-1"
    assert connection.calls[0][1][-1] == 2


@pytest.mark.anyio
@pytest.mark.parametrize("limit", [0, 513, True])
async def test_invalid_or_over_cap_page_limit_fails_closed(limit):
    with pytest.raises(ManagedCleanupV3Error, match="source_limit_invalid"):
        await AsyncPostgresManagedCleanupV3CanonicalInventorySource().read_page(
            _Connection(), context=_context(), kind="facts", after=None, limit=limit
        )


@pytest.mark.anyio
async def test_wrong_keyset_cursor_shape_fails_before_sql():
    connection = _Connection()
    with pytest.raises(ManagedCleanupV3Error, match="source_cursor_invalid"):
        await AsyncPostgresManagedCleanupV3CanonicalInventorySource().read_page(
            connection,
            context=_context(),
            kind="cleanup_outbox_receipts",
            after="not-a-two-part-cursor",
            limit=10,
        )
    assert connection.calls == []


@pytest.mark.anyio
async def test_target_identity_requires_done_upsert_receipt_link_not_dictionary_only():
    connection = _Connection()
    await AsyncPostgresManagedCleanupV3CanonicalInventorySource().read_page(
        connection,
        context=_context(),
        kind="qdrant_target_identities",
        after=None,
        limit=10,
    )
    sql = connection.calls[0][0]
    assert "memory_projection_receipt_identity_links" in sql
    assert "r.operation = 'upsert'" in sql
    assert "r.result_state = 'present'" in sql
    assert "o.status = 'done'" in sql
    assert "__authority_evidence" in sql
    assert "memory_fact_versions" not in sql


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("kind", "required_sql"),
    (
        (
            "memory_scopes",
            ("memory_scope_external_ref", "thread_external_ref", "source.lane"),
        ),
        (
            "memory_threads",
            ("memory_scope_external_ref", "thread_external_ref", "authority.lane"),
        ),
        ("facts", ("ordered_source_refs", "memory_fact_versions", "source_ref_count = 1")),
        (
            "fact_source_refs",
            ("canonical_fact", "source_ref_ordinal", "source_ref_count = 1"),
        ),
        ("documents", ("ordered_chunks", "LIMIT 106", "ORDER BY c.sequence")),
        ("chunks", ("'document', to_jsonb(d)", "'chunk_ordinal', c.sequence")),
    ),
)
async def test_canonical_queries_supply_stateless_a2_authority_evidence(kind, required_sql):
    connection = _Connection()
    await AsyncPostgresManagedCleanupV3CanonicalInventorySource().read_page(
        connection,
        context=_context(),
        kind=kind,
        after=None,
        limit=10,
    )
    sql = connection.calls[0][0]
    assert "__authority_evidence" in sql
    for fragment in required_sql:
        assert fragment in sql


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kind",
    (
        "qdrant_target_identities",
        "qdrant_upsert_jobs",
        "qdrant_delete_jobs",
        "graphiti_target_names",
        "graphiti_upsert_jobs",
        "graphiti_delete_jobs",
        "cleanup_outbox_receipts",
    ),
)
async def test_projection_queries_embed_same_canonical_authority_evidence(kind):
    connection = _Connection()
    await AsyncPostgresManagedCleanupV3CanonicalInventorySource().read_page(
        connection,
        context=_context(),
        kind=kind,
        after=None,
        limit=10,
    )
    sql = connection.calls[0][0]
    assert "__authority_evidence" in sql
    assert "memory_scope_external_ref" in sql
    assert "thread_external_ref" in sql
    if kind == "cleanup_outbox_receipts":
        assert "to_jsonb(f) || jsonb_build_object" in sql
        assert "to_jsonb(c) || jsonb_build_object" in sql


@pytest.mark.anyio
async def test_divergent_duplicate_identity_proofs_fail_closed():
    row = {
        "locator_json": {
            "kind": "qdrant_point_id",
            "identity_sha256": "1" * 64,
            "identity_commitment_sha256": "2" * 64,
            "lineage_root_sha256": "3" * 64,
            "target_authority_sha256": "4" * 64,
        },
        "row_json": {"identity": {"canonical_source_id": "chunk-1"}},
        "cursor_1": "1" * 64,
        "cursor_2": "2" * 64,
        "source_proof_count": 2,
    }
    with pytest.raises(ManagedCleanupV3Error, match="identity_proof_ambiguous"):
        await AsyncPostgresManagedCleanupV3CanonicalInventorySource().read_page(
            _Connection([row]),
            context=_context(),
            kind="qdrant_target_identities",
            after=None,
            limit=10,
        )


@pytest.mark.anyio
async def test_unsupported_rows_expose_episode_cognee_and_unknown_outbox():
    rows = [
        {
            "locator_json": {"source_table": table, "source_pk": key},
            "row_json": payload,
            "cursor_1": table,
            "cursor_2": key,
        }
        for table, key, payload in (
            ("memory_episodes", "episode-1", {"id": "episode-1"}),
            ("memory_outbox", "8", {"event_type": "cognee.ingest_document"}),
            ("memory_outbox", "9", {"event_type": "provider.unknown"}),
        )
    ]
    connection = _Connection(rows)
    page = await AsyncPostgresManagedCleanupV3CanonicalInventorySource().read_page(
        connection,
        context=_context(),
        kind="unsupported_rows",
        after=None,
        limit=10,
    )
    assert len(page.rows) == 3
    sql = connection.calls[0][0]
    assert "memory_episodes" in sql
    assert "cognee" not in sql
    assert "event_type NOT IN" in sql


def _authenticated_grouped_delete_evidence():
    context = _context()
    authenticator = ProjectionReceiptAuthenticator(b"r" * 32)
    identities = tuple(
        ProjectionTargetIdentity(
            kind="qdrant_point_id",
            canonical_source_id=chunk_id,
            physical_identity=qdrant_point_id_for_chunk(chunk_id),
            lineage_root_sha256="a" * 64,
            target_authority_sha256=context.qdrant_authority_sha256,
        )
        for chunk_id in ("chunk-1", "chunk-2")
    )
    when = datetime(2026, 1, 1, tzinfo=UTC)
    payload = {
        "chunk_ids": ["chunk-1", "chunk-2"],
        "space_id": context.space_id,
        "cleanup_run_id_sha256": context.run_id_sha256,
    }
    outbox = {
        "id": 77,
        "message_key": "delete-77",
        "event_type": "vector.delete_chunks",
        "aggregate_type": "benchmark_run",
        "aggregate_id": context.run_id_sha256,
        "aggregate_version": None,
        "status": "done",
        "payload_json": payload,
        "created_at": when,
    }
    event_commitment = projection_outbox_event_commitment(
        message_key=outbox["message_key"],
        event_type=outbox["event_type"],
        aggregate_type=outbox["aggregate_type"],
        aggregate_id=outbox["aggregate_id"],
        aggregate_version=outbox["aggregate_version"],
        payload=payload,
        created_at=when.isoformat(),
    )
    binding = ProjectionJobBinding(
        outbox_id=77,
        run_id_sha256=context.run_id_sha256,
        context_sha256=context.context_sha256,
        lane="qdrant",
        space_id=context.space_id,
        memory_scope_id="scope-1",
        thread_id=None,
        aggregate_type="benchmark_run",
        aggregate_id=context.run_id_sha256,
        aggregate_version=None,
        target_authority_sha256=context.qdrant_authority_sha256,
        worker_authority_sha256=authenticator.authority_sha256,
        lineage_root_sha256="a" * 64,
        outbox_event_commitment_sha256=event_commitment,
    )
    receipt = build_projection_result_receipt(
        binding=binding,
        materialization=ProjectionMaterialization(
            projection_key_sha256=binding.projection_key_sha256,
            identities=identities,
            completed_at=when,
        ),
        authenticator=authenticator,
        persisted_at=when,
        operation="delete",
        result_state="absent",
    )
    item = receipt.identities[0]
    identity = {
        **item.identity.canonical_payload(),
        "identity_sha256": item.identity_sha256,
        "identity_commitment_sha256": item.identity_commitment_sha256,
        "identity_mac_sha256": item.identity_mac_sha256,
    }
    receipt_row = {
        **asdict(binding),
        "operation": receipt.operation,
        "result_state": receipt.result_state,
        "identity_count": len(receipt.identities),
        "ordered_identity_root_sha256": receipt.ordered_identity_root_sha256,
        "provider_completed_at": when,
        "persisted_at": when,
        "receipt_sha256": receipt.receipt_sha256,
        "receipt_mac_sha256": receipt.receipt_mac_sha256,
    }
    row = InventorySourceRow(
        locator_json={
            "physical_outbox_id": binding.outbox_id,
            "logical_target_identity_sha256": item.identity_sha256,
        },
        row_json={
            "outbox": outbox,
            "receipt": receipt_row,
            "link": {
                "outbox_id": binding.outbox_id,
                "run_id_sha256": context.run_id_sha256,
                "kind": item.identity.kind,
                "identity_sha256": item.identity_sha256,
                "identity_commitment_sha256": item.identity_commitment_sha256,
                "ordinal": 0,
            },
            "identity": identity,
            "canonical_source": {
                "id": "chunk-1",
                "space_id": context.space_id,
                "memory_scope_id": "scope-1",
                "thread_id": None,
                "status": "deleted",
            },
        },
        source_cursor=(item.identity_sha256, binding.outbox_id),
    )
    return context, authenticator, row


@pytest.mark.anyio
async def test_concrete_authenticator_verifies_grouped_delete_mac_root_link_and_mapping():
    context, capability, row = _authenticated_grouped_delete_evidence()
    expected_rows = _ExpectedRows()
    verifier = ManagedCleanupV3SourceEvidenceAuthenticator(
        capability, expected_rows, _ReceiptScratch()
    )
    await verifier(None, context, "f" * 64, "e" * 64, "qdrant_delete_jobs", row)
    assert expected_rows.calls[0]["kind"] == "chunks"

    for field, value, diagnostic in (
        (("canonical_source", "id"), "chunk-other", "binding_invalid"),
        (("canonical_source", "space_id"), "space-other", "binding_invalid"),
        (("canonical_source", "memory_scope_id"), "scope-other", "binding_invalid"),
    ):
        evidence = deepcopy(dict(row.row_json))
        evidence[field[0]][field[1]] = value
        tampered = InventorySourceRow(row.locator_json, evidence, row.source_cursor)
        with pytest.raises(ManagedCleanupV3Error, match=diagnostic):
            await verifier(None, context, "f" * 64, "e" * 64, "qdrant_delete_jobs", tampered)


def test_lane_authorities_are_distinct_in_source_context_fixture():
    context = _context()
    assert context.qdrant_authority_sha256 != context.graphiti_authority_sha256


@pytest.mark.anyio
async def test_expected_row_authority_blocks_canonical_content_tamper():
    class _ExactRows:
        async def verify_expected_row(self, **values):
            if values["row_json"].get("text") != "committed fact text":
                raise ManagedCleanupV3Error("expected_row_divergent")

    context = _context()
    verifier = ManagedCleanupV3SourceEvidenceAuthenticator(
        ProjectionReceiptAuthenticator(b"r" * 32), _ExactRows(), _ReceiptScratch()
    )
    valid = InventorySourceRow(
        {"id": "fact-1"},
        {
            "id": "fact-1",
            "space_id": context.space_id,
            "status": "deleted",
            "text": "committed fact text",
        },
        "fact-1",
    )
    await verifier(None, context, "f" * 64, "e" * 64, "facts", valid)
    tampered = InventorySourceRow(
        valid.locator_json,
        {**valid.row_json, "text": "post-authority tamper"},
        valid.source_cursor,
    )
    with pytest.raises(ManagedCleanupV3Error, match="expected_row_divergent"):
        await verifier(None, context, "f" * 64, "e" * 64, "facts", tampered)
