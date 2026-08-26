"""Static contract for transaction-coalesced locator-profile outbox invalidation."""

from pathlib import Path

MIGRATIONS = (
    Path(__file__).resolve().parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
)
BASE_MIGRATION = MIGRATIONS / "0046_locator_profile_linearizable_fences.sql"
COALESCING_MIGRATION = MIGRATIONS / "0050_locator_profile_outbox_transaction_coalescing.sql"


def _function_sql(sql: str) -> str:
    return sql.split(
        "CREATE OR REPLACE FUNCTION memory_locator_profile_invalidate_outbox_evidence_v2()",
        1,
    )[1].split("REVOKE ALL ON FUNCTION", 1)[0]


def _trigger_sql(sql: str) -> str:
    return sql.split("-- Drop every historical outbox invalidator", 1)[1]


def test_0046_keeps_the_original_before_row_lock_order_contract() -> None:
    sql = BASE_MIGRATION.read_text(encoding="utf-8")
    triggers = sql.split("DROP TRIGGER IF EXISTS trg_locator_profile_outbox_evidence_version", 1)[
        1
    ].split("DROP TRIGGER IF EXISTS trg_locator_profile_canonical", 1)[0]

    assert "Global lock order is evidence -> profiles -> trigger-bearing/dependent rows" in sql
    assert triggers.count("BEFORE ") == 3
    assert triggers.count("FOR EACH ROW") == 3
    assert "AFTER INSERT ON memory_outbox" not in triggers
    assert "REFERENCING " not in triggers


def test_0050_uses_an_atomic_non_forgeable_transaction_marker() -> None:
    sql = COALESCING_MIGRATION.read_text(encoding="utf-8")
    function = _function_sql(sql)

    assert "ADD COLUMN IF NOT EXISTS outbox_invalidation_xid XID8" in sql
    assert "SECURITY DEFINER" in function
    assert "SET search_path = pg_catalog, public" in function
    assert "outbox_invalidation_xid = pg_catalog.pg_current_xact_id()" in function
    assert "outbox_invalidation_xid IS DISTINCT FROM pg_catalog.pg_current_xact_id()" in function
    assert function.index("UPDATE public.memory_locator_profile_evidence_versions") < (
        function.index("UPDATE public.memory_locator_profiles")
    )
    assert "GET DIAGNOSTICS invalidated_rows = ROW_COUNT" in function
    assert "IF invalidated_rows > 0 THEN" in function
    assert "BEFORE UPDATE OF outbox_invalidation_xid" in sql
    assert "IF CURRENT_USER <> evidence_owner THEN" in sql
    assert "USING ERRCODE = 'insufficient_privilege'" in sql
    assert "REVOKE ALL ON FUNCTION memory_locator_profile_guard_outbox_xid_v1()" in sql
    assert "REVOKE ALL ON FUNCTION memory_locator_profile_invalidate_outbox_evidence_v2()" in sql
    assert "current_setting" not in sql
    assert "set_config" not in sql
    assert "pg_temp" not in sql


def test_0050_preserves_before_row_relevance_and_return_semantics() -> None:
    sql = COALESCING_MIGRATION.read_text(encoding="utf-8")
    function = _function_sql(sql)
    triggers = _trigger_sql(sql)

    assert triggers.count("CREATE TRIGGER trg_00_locator_profile_outbox_evidence_") == 3
    assert triggers.count("BEFORE ") == 3
    assert triggers.count("FOR EACH ROW") == 3
    assert "AFTER " not in triggers
    assert "WHEN (NEW.event_type IN" in triggers
    assert "OLD.event_type IN" in triggers
    assert ") OR NEW.event_type IN (" in triggers
    assert "WHEN (OLD.event_type IN" in triggers
    assert triggers.count("'vector.upsert_locator_profile'") == 4
    assert triggers.count("'vector.delete_locator_profile'") == 4
    assert (
        triggers.count("EXECUTE FUNCTION memory_locator_profile_invalidate_outbox_evidence_v2()")
        == 3
    )
    assert "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;" in function
    assert "RETURN NEW;" in function


def test_0050_is_safe_to_reexecute_after_either_0046_trigger_shape() -> None:
    sql = COALESCING_MIGRATION.read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS" in sql
    assert "CREATE OR REPLACE FUNCTION" in sql
    for operation in ("insert", "update", "delete"):
        trigger = f"trg_00_locator_profile_outbox_evidence_{operation}"
        assert f"DROP TRIGGER IF EXISTS {trigger} ON memory_outbox" in sql
        assert f"CREATE TRIGGER {trigger}" in sql
    assert "DROP TRIGGER IF EXISTS trg_locator_profile_outbox_evidence_version" in sql
