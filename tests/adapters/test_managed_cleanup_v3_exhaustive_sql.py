from infinity_context_adapters.postgres.managed_cleanup_v3_canonical_inventory_sql import (
    CANONICAL_EVIDENCE,
    SIMPLE_QUERIES,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_exhaustive_sql import (
    UNSUPPORTED_SQL,
)


def test_fact_authority_aggregates_stop_after_expected_plus_one_row():
    assert "ORDER BY bounded.id LIMIT 2" in SIMPLE_QUERIES["facts"].sql
    assert "ORDER BY bounded.id LIMIT 2" in SIMPLE_QUERIES["fact_source_refs"].sql
    fact_joins = CANONICAL_EVIDENCE["memory_facts"][1]
    assert "ORDER BY bounded.id LIMIT 2" in fact_joins


def test_unsupported_stream_exposes_hidden_canonical_join_failures():
    for table in (
        "memory_scopes",
        "memory_threads",
        "memory_facts",
        "memory_source_refs",
        "memory_documents",
        "memory_chunks",
    ):
        assert f"'{table}'" in UNSUPPORTED_SQL
    assert "LIMIT 2" in UNSUPPORTED_SQL
    assert "__unsupported_pk" in UNSUPPORTED_SQL


def test_unsupported_stream_exposes_related_projection_orphans_and_supported_jobs():
    for table in (
        "memory_outbox",
        "memory_projection_result_receipts",
        "memory_projection_target_identities",
        "memory_projection_receipt_identity_links",
    ):
        assert f"'{table}'" in UNSUPPORTED_SQL
    assert "o.aggregate_type = 'benchmark_run' AND o.aggregate_id = $2" in UNSUPPORTED_SQL
    assert "o.event_type NOT IN" in UNSUPPORTED_SQL
    assert "OR NOT EXISTS" in UNSUPPORTED_SQL


def test_unsupported_stream_remains_bounded_and_keyset_ordered():
    assert "r.context_sha256 = $3" in UNSUPPORTED_SQL
    assert "(source_table, source_pk) > ($4, $5)" in UNSUPPORTED_SQL
    assert "ORDER BY source_table, source_pk" in UNSUPPORTED_SQL
    assert UNSUPPORTED_SQL.rstrip().endswith("LIMIT $6")
