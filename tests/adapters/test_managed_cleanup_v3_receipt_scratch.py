from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres.managed_cleanup_v3_receipt_scratch import (
    LINK_PAGE_SQL,
    PAYLOAD_PAGE_SQL,
    RECEIPT_PAGE_SIZE,
    ManagedCleanupV3ReceiptProofScratch,
    ReceiptPreflightMetrics,
    _array_event,
    _event_prefix,
    _finish_grouped_event,
    _GlobalLinkStream,
    _GlobalPayloadStream,
    _link_evidence,
    _row_header,
    _sha,
    create_receipt_scratch_schema,
)
from infinity_context_core.features.projection_receipts import ProjectionReceiptAuthenticator
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Error,
    canonical_bytes,
)

TERMINAL = "1" * 64
SESSION = "2" * 64


def _scratch():
    db = sqlite3.connect(":memory:")
    create_receipt_scratch_schema(db)
    scratch = ManagedCleanupV3ReceiptProofScratch(
        db, b"s" * 32, ProjectionReceiptAuthenticator(b"r" * 32)
    )
    scratch.begin_new(TERMINAL, SESSION)
    return db, scratch


def _seed_use(db, scratch):
    outbox = {
        "id": 7,
        "message_key": "delete-7",
        "event_type": "vector.delete_chunks",
        "aggregate_type": "benchmark_run",
        "aggregate_id": "3" * 64,
        "aggregate_version": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "status": "done",
    }
    receipt = {"outbox_id": 7, "receipt_sha256": "4" * 64}
    link = {
        "outbox_id": 7,
        "run_id_sha256": "3" * 64,
        "ordinal": 0,
        "kind": "qdrant_point_id",
        "identity_sha256": "5" * 64,
        "identity_commitment_sha256": "6" * 64,
    }
    identity = {
        "kind": "qdrant_point_id",
        "identity_sha256": "5" * 64,
        "identity_commitment_sha256": "6" * 64,
    }
    header = _sha(_row_header(outbox, receipt))
    evidence = _sha(_link_evidence(link, identity))
    db.execute(
        "INSERT INTO verified_receipts VALUES(?,?,?,?,?)",
        (
            7,
            header,
            "4" * 64,
            0,
            scratch._mac("receipt", TERMINAL, SESSION, 7, header, "4" * 64, 0),
        ),
    )
    values = (7, 0, "qdrant_delete_jobs", "qdrant_point_id", "5" * 64, "6" * 64, evidence)
    db.execute(
        "INSERT INTO verified_links VALUES(?,?,?,?,?,?,?,0,?)",
        (*values, scratch._mac("link", TERMINAL, SESSION, *values, 0)),
    )
    db.commit()
    return outbox, receipt, link, identity


def test_consume_is_exact_once_and_finalize_authenticates_tamper():
    db, scratch = _scratch()
    evidence = _seed_use(db, scratch)
    scratch.consume(TERMINAL, SESSION, "qdrant_delete_jobs", *evidence)
    scratch.flush_verification_page(TERMINAL, SESSION)
    with pytest.raises(ManagedCleanupV3Error, match="authentication_invalid"):
        scratch.consume(TERMINAL, SESSION, "qdrant_delete_jobs", *evidence)
    db.execute("UPDATE verified_links SET consumed=0")
    db.commit()
    with pytest.raises(ManagedCleanupV3Error, match="coverage_invalid"):
        scratch.finalize(TERMINAL, SESSION)


def test_366440_streaming_instrumentation_stays_within_512_items():
    count = 366_440
    _db, scratch = _scratch()
    outbox = {
        "aggregate_id": "3" * 64,
        "aggregate_type": "benchmark_run",
        "aggregate_version": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "event_type": "vector.delete_chunks",
        "message_key": "delete-all",
        "payload_without_chunk_ids": {
            "cleanup_run_id_sha256": "3" * 64,
            "space_id": "space",
        },
    }
    streamed = _event_prefix(outbox)
    max_retained = 0
    pages = 0
    for start in range(0, count, RECEIPT_PAGE_SIZE):
        stop = min(start + RECEIPT_PAGE_SIZE, count)
        page = range(start, stop)
        max_retained = max(max_retained, len(page))
        pages += 1
        for ordinal in page:
            if ordinal:
                streamed.update(b",")
            streamed.update(canonical_bytes(f"chunk-{ordinal:06d}"))
            scratch._before_mutations(1)
            scratch._record_mutations(1)
    scratch._checkpoint()
    result = _finish_grouped_event(streamed, outbox)

    assert len(result) == hashlib.sha256().digest_size * 2
    assert max_retained == RECEIPT_PAGE_SIZE
    assert pages == 716
    assert scratch.metrics.scratch_checkpoints == 716
    assert scratch.metrics.max_pending_mutations == RECEIPT_PAGE_SIZE
    assert "generate_series" in PAYLOAD_PAGE_SQL
    assert "payload_json" not in LINK_PAGE_SQL


def test_global_link_stream_scales_with_pages_not_receipt_count():
    receipt_count = 11_764

    class Connection:
        def __init__(self):
            self.calls = []

        async def fetch(self, sql, *parameters):
            self.calls.append((sql, parameters))
            after_outbox, after_ordinal, limit = parameters[3:]
            assert after_ordinal in {-1, 0}
            start = after_outbox + 1
            return [
                {"outbox_id": outbox_id, "ordinal": 0}
                for outbox_id in range(start, min(start + limit, receipt_count))
            ]

    async def consume_all():
        connection = Connection()
        metrics = ReceiptPreflightMetrics()
        context = SimpleNamespace(
            run_id_sha256="3" * 64,
            context_sha256="4" * 64,
            space_id="space",
        )
        stream = _GlobalLinkStream(connection, context, metrics)
        observed = 0
        while await stream.peek() is not None:
            stream.advance()
            observed += 1
        return connection, metrics, observed

    connection, metrics, observed = asyncio.run(consume_all())

    assert observed == receipt_count
    assert len(connection.calls) == 23
    assert metrics.link_pages == 23
    assert metrics.max_link_page == RECEIPT_PAGE_SIZE
    assert metrics.max_retained_identities == RECEIPT_PAGE_SIZE
    assert all(call[0] == LINK_PAGE_SQL for call in connection.calls)
    assert all(call[1][-1] == RECEIPT_PAGE_SIZE for call in connection.calls)
    assert "(l.outbox_id,l.ordinal) > ($4,$5)" in LINK_PAGE_SQL
    assert "ORDER BY l.outbox_id,l.ordinal" in LINK_PAGE_SQL


def test_global_payload_stream_pages_across_multiple_receipt_groups():
    receipt_count = 1_000
    payloads_per_receipt = 3
    total_payloads = receipt_count * payloads_per_receipt

    class Connection:
        def __init__(self):
            self.calls = []

        async def fetch(self, sql, *parameters):
            self.calls.append((sql, parameters))
            after_outbox, after_ordinal, limit = parameters[3:]
            start = (
                0
                if after_outbox == -1
                else (after_outbox - 1) * payloads_per_receipt + after_ordinal + 1
            )
            return [
                {
                    "outbox_id": flat // payloads_per_receipt + 1,
                    "ordinal": flat % payloads_per_receipt,
                }
                for flat in range(start, min(start + limit, total_payloads))
            ]

    async def consume_all():
        connection = Connection()
        metrics = ReceiptPreflightMetrics()
        context = SimpleNamespace(
            run_id_sha256="3" * 64,
            context_sha256="4" * 64,
            space_id="space",
        )
        stream = _GlobalPayloadStream(connection, context, metrics)
        grouped = {}
        while (raw := await stream.peek()) is not None:
            grouped[raw["outbox_id"]] = grouped.get(raw["outbox_id"], 0) + 1
            stream.advance()
        return connection, metrics, grouped

    connection, metrics, grouped = asyncio.run(consume_all())

    assert grouped == {outbox_id: 3 for outbox_id in range(1, receipt_count + 1)}
    assert len(connection.calls) == 6
    assert metrics.link_pages == 0
    assert metrics.payload_pages == 6
    assert metrics.max_payload_page == RECEIPT_PAGE_SIZE
    assert all(call[0] == PAYLOAD_PAGE_SQL for call in connection.calls)
    assert "(o.id,n) > ($4,$5)" in PAYLOAD_PAGE_SQL
    assert "ORDER BY o.id,n" in PAYLOAD_PAGE_SQL


def test_grouped_payload_stream_preserves_hash_mac_and_scratch_rows():
    rows = [
        {"outbox_id": 7, "ordinal": 0, "source_id": "chunk-a"},
        {"outbox_id": 7, "ordinal": 1, "source_id": "chunk-b"},
        {"outbox_id": 9, "ordinal": 0, "source_id": "chunk-c"},
    ]

    class Connection:
        async def fetch(self, _sql, *_parameters):
            return rows

    async def prepare_groups(scratch):
        context = SimpleNamespace(
            run_id_sha256="3" * 64,
            context_sha256="4" * 64,
            space_id="space",
        )
        stream = _GlobalPayloadStream(Connection(), context, scratch.metrics)
        first_hash = hashlib.sha256()
        second_hash = hashlib.sha256()
        await scratch._prepare_payload_sources(TERMINAL, SESSION, 7, first_hash, stream)
        await scratch._prepare_payload_sources(TERMINAL, SESSION, 9, second_hash, stream)
        return first_hash.hexdigest(), second_hash.hexdigest()

    db, scratch = _scratch()
    first_hash, second_hash = asyncio.run(prepare_groups(scratch))
    expected_first = hashlib.sha256(
        canonical_bytes("chunk-a") + b"," + canonical_bytes("chunk-b")
    ).hexdigest()
    expected_second = hashlib.sha256(canonical_bytes("chunk-c")).hexdigest()
    stored = db.execute(
        "SELECT outbox_id,ordinal,source_id,claimed,row_mac "
        "FROM verified_receipt_sources ORDER BY outbox_id,ordinal"
    ).fetchall()

    assert (first_hash, second_hash) == (expected_first, expected_second)
    assert [row[:4] for row in stored] == [
        (7, 0, "chunk-a", 0),
        (7, 1, "chunk-b", 0),
        (9, 0, "chunk-c", 0),
    ]
    assert all(
        row[4] == scratch._mac("source", TERMINAL, SESSION, row[0], row[1], row[2], row[3])
        for row in stored
    )


@pytest.mark.parametrize(
    ("event_type", "payload_count"),
    [("vector.delete_chunks", None), ("vector.upsert_chunks", None), ("vector.upsert_chunk", 1)],
)
def test_event_kind_requires_exact_payload_array_shape(event_type, payload_count):
    with pytest.raises(ManagedCleanupV3Error, match="payload_shape_invalid"):
        _array_event(event_type, payload_count)
