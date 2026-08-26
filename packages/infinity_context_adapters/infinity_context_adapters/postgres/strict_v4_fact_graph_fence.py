"""Postgres fences for strict-v4 fact rows without a direct space_id."""

from __future__ import annotations

STRICT_V4_FACT_CHILD_TABLES = (
    "memory_fact_versions",
    "memory_source_refs",
    "memory_outbox",
)

STRICT_V4_FACT_CHILD_LOCK_SQL = """
CREATE OR REPLACE FUNCTION memory_comparison_lock_benchmark_fact_child_target()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    target_fact_id VARCHAR(80);
    target_space_id VARCHAR(80);
    target_aggregate_type VARCHAR(80);
BEGIN
    IF TG_TABLE_NAME = 'memory_outbox' THEN
        IF TG_OP = 'UPDATE' AND (
            OLD.aggregate_type IS DISTINCT FROM NEW.aggregate_type
            OR OLD.aggregate_id IS DISTINCT FROM NEW.aggregate_id
        ) THEN
            RAISE EXCEPTION 'benchmark fact child identity is immutable'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
        END IF;
        IF TG_OP = 'DELETE' THEN
            target_aggregate_type := OLD.aggregate_type;
            target_fact_id := OLD.aggregate_id;
            target_space_id := OLD.payload_json->>'space_id';
        ELSE
            target_aggregate_type := NEW.aggregate_type;
            target_fact_id := NEW.aggregate_id;
            target_space_id := NEW.payload_json->>'space_id';
        END IF;
        IF target_aggregate_type = 'fact' THEN
            SELECT fact.space_id INTO target_space_id
            FROM public.memory_facts AS fact
            WHERE fact.id = target_fact_id;
        END IF;
    ELSE
        IF TG_OP = 'UPDATE' AND OLD.fact_id IS DISTINCT FROM NEW.fact_id THEN
            RAISE EXCEPTION 'benchmark fact child identity is immutable'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
        END IF;
        IF TG_OP = 'DELETE' THEN
            target_fact_id := OLD.fact_id;
        ELSE
            target_fact_id := NEW.fact_id;
        END IF;
        SELECT fact.space_id INTO target_space_id
        FROM public.memory_facts AS fact
        WHERE fact.id = target_fact_id;
    END IF;

    IF target_space_id IS NULL THEN
        RAISE EXCEPTION 'benchmark fact child parent is missing'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    BEGIN
        PERFORM 1
        FROM public.memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = target_space_id
        FOR SHARE NOWAIT;
    EXCEPTION WHEN lock_not_available THEN
        RAISE EXCEPTION 'benchmark fact child writer fence rejected data mutation'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;
""".strip()

STRICT_V4_FACT_CHILD_POLICY_SQL = """
CREATE OR REPLACE FUNCTION memory_comparison_enforce_benchmark_fact_child_fence()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    target_fact_id VARCHAR(80);
    target_space_id VARCHAR(80);
    parent_scope_id VARCHAR(80);
    parent_thread_id VARCHAR(80);
    parent_version INTEGER;
    parent_status VARCHAR(40);
    parent_text TEXT;
    target_aggregate_type VARCHAR(80);
    registry_state VARCHAR(40);
    registry_projection_state VARCHAR(40);
    registry_cleanup_plan_state VARCHAR(40);
    registry_run_id CHAR(64);
    strict_authorized BOOLEAN := FALSE;
    fact_writer BOOLEAN := public.memory_comparison_is_strict_v4_canonical_writer();
BEGIN
    IF TG_TABLE_NAME = 'memory_outbox' THEN
        IF TG_OP = 'DELETE' THEN
            target_aggregate_type := OLD.aggregate_type;
            target_fact_id := OLD.aggregate_id;
            target_space_id := OLD.payload_json->>'space_id';
        ELSE
            target_aggregate_type := NEW.aggregate_type;
            target_fact_id := NEW.aggregate_id;
            target_space_id := NEW.payload_json->>'space_id';
        END IF;
        IF target_aggregate_type <> 'fact' THEN
            target_fact_id := NULL;
        END IF;
    ELSE
        IF TG_OP = 'DELETE' THEN
            target_fact_id := OLD.fact_id;
        ELSE
            target_fact_id := NEW.fact_id;
        END IF;
    END IF;
    IF target_fact_id IS NOT NULL THEN
        SELECT fact.space_id, fact.memory_scope_id, fact.thread_id,
               fact.version, fact.status, fact.text
        INTO target_space_id, parent_scope_id, parent_thread_id,
             parent_version, parent_status, parent_text
        FROM public.memory_facts AS fact
        WHERE fact.id = target_fact_id;
    END IF;
    SELECT benchmark_run.state, benchmark_run.projection_cleanup_state,
           benchmark_run.cleanup_plan_state, benchmark_run.run_id_sha256
    INTO registry_state, registry_projection_state,
         registry_cleanup_plan_state, registry_run_id
    FROM public.memory_comparison_benchmark_runs AS benchmark_run
    WHERE benchmark_run.space_id = target_space_id;

    IF registry_state IS NULL THEN
        IF fact_writer THEN
            RAISE EXCEPTION 'strict-v4 fact writer cannot mutate an unmanaged child'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
        END IF;
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    SELECT EXISTS (
        SELECT 1
        FROM public.memory_comparison_strict_v4_preparations AS preparation
        JOIN public.memory_cleanup_v3_context_authorities AS context_authority
          ON context_authority.run_id_sha256 = preparation.run_id_sha256
         AND context_authority.context_sha256 = preparation.context_sha256
         AND context_authority.authority_terminal_sha256
             = preparation.authority_terminal_sha256
        WHERE preparation.run_id_sha256 = registry_run_id
          AND preparation.state = 'sealed'
          AND preparation.provider_calls = 0
          AND preparation.paid_go_ready = FALSE
          AND preparation.registration_sha256 = context_authority.registration_sha256
          AND preparation.registration_mac_sha256 = context_authority.registration_mac_sha256
    ) INTO strict_authorized;

    IF TG_OP = 'INSERT' AND NOT fact_writer AND NOT strict_authorized
        AND registry_state = 'active' AND registry_projection_state = 'unsealed'
        AND registry_cleanup_plan_state = 'sealed'
    THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'INSERT' AND fact_writer AND strict_authorized
        AND registry_state = 'active' AND registry_projection_state = 'unsealed'
    THEN
        IF TG_TABLE_NAME = 'memory_fact_versions' THEN
            IF NEW.version = 1 AND parent_version = 1
                AND NEW.status = 'active' AND parent_status = 'active'
                AND NEW.text = parent_text
            THEN
                RETURN NEW;
            END IF;
        ELSIF TG_TABLE_NAME = 'memory_source_refs' THEN
            IF NEW.fact_version = 1 AND parent_version = 1
                AND parent_status = 'active'
            THEN
                RETURN NEW;
            END IF;
        ELSIF TG_TABLE_NAME = 'memory_outbox' THEN
            IF NEW.aggregate_type = 'fact'
                AND NEW.aggregate_version = 1
                AND NEW.event_type = 'fact.created'
                AND NEW.status = 'pending' AND NEW.attempt_count = 0
                AND NEW.message_key IS NOT NULL
                AND NEW.payload_json->>'fact_id' = target_fact_id
                AND NEW.payload_json->>'space_id' = target_space_id
                AND NEW.payload_json->>'memory_scope_id' = parent_scope_id
                AND COALESCE(NEW.payload_json->>'thread_id', '')
                    = COALESCE(parent_thread_id, '')
                AND (NEW.payload_json->>'version')::integer = 1
            THEN
                RETURN NEW;
            END IF;
        END IF;
    END IF;
    RAISE EXCEPTION 'benchmark fact child writer fence rejected data mutation'
        USING ERRCODE = '23514',
              CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
END;
$$;
""".strip()

STRICT_V4_FACT_OUTBOX_RECEIPT_SQL = """
CREATE OR REPLACE FUNCTION memory_comparison_verify_benchmark_fact_outbox_receipt()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT public.memory_comparison_is_strict_v4_canonical_writer() THEN
        RETURN NEW;
    END IF;
    IF NEW.aggregate_type <> 'fact' OR NOT EXISTS (
        SELECT 1 FROM public.memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = NEW.payload_json->>'space_id'
    ) THEN
        RETURN NEW;
    END IF;
    IF NEW.message_key IS NULL THEN
        RAISE EXCEPTION 'benchmark fact outbox message key is missing'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.memory_fact_operation_receipts AS receipt
        WHERE receipt.result_fact_id = NEW.aggregate_id
    ) THEN
        RAISE EXCEPTION 'benchmark fact outbox result receipt is missing'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.memory_fact_operation_receipts AS receipt
        WHERE receipt.result_fact_id = NEW.aggregate_id
          AND receipt.space_id = NEW.payload_json->>'space_id'
    ) THEN
        RAISE EXCEPTION 'benchmark fact outbox receipt space is invalid'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.memory_fact_operation_receipts AS receipt
        WHERE receipt.result_fact_id = NEW.aggregate_id
          AND receipt.space_id = NEW.payload_json->>'space_id'
          AND receipt.result_fact_version = NEW.aggregate_version
    ) THEN
        RAISE EXCEPTION 'benchmark fact outbox receipt version is invalid'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.memory_fact_operation_receipts AS receipt
        WHERE receipt.space_id = NEW.payload_json->>'space_id'
          AND receipt.result_fact_id = NEW.aggregate_id
          AND receipt.result_fact_version = NEW.aggregate_version
          AND receipt.operation = 'remember'
          AND receipt.idempotency_key LIKE 'managed-benchmark-fact-v4-%'
          AND pg_catalog.length(receipt.idempotency_key) = 90
    ) THEN
        RAISE EXCEPTION 'benchmark fact outbox receipt identity is missing'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.memory_fact_operation_receipts AS receipt
        WHERE receipt.space_id = NEW.payload_json->>'space_id'
          AND receipt.result_fact_id = NEW.aggregate_id
          AND receipt.result_fact_version = NEW.aggregate_version
          AND receipt.operation = 'remember'
          AND receipt.outbox_message_ids_json
              @> pg_catalog.jsonb_build_array(NEW.message_key)
    ) THEN
        RAISE EXCEPTION 'benchmark fact outbox receipt link is missing'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    RETURN NEW;
END;
$$;
""".strip()

STRICT_V4_FACT_RECEIPT_POLICY_SQL = """
CREATE OR REPLACE FUNCTION memory_comparison_enforce_benchmark_fact_receipt()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT public.memory_comparison_is_strict_v4_canonical_writer() THEN
        RETURN NEW;
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = NEW.space_id
    ) AND (
        NEW.operation <> 'remember'
        OR NEW.result_fact_version <> 1
        OR NEW.idempotency_key NOT LIKE 'managed-benchmark-fact-v4-%'
        OR pg_catalog.length(NEW.idempotency_key) <> 90
        OR NEW.tombstone_id IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'benchmark fact receipt is invalid'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    RETURN NEW;
END;
$$;
""".strip()


def _child_triggers(table: str) -> tuple[str, str, str, str]:
    lock_name = f"trg_00_{table}_benchmark_fact_child_lock"
    policy_name = f"trg_{table}_benchmark_fact_child_fence"
    return (
        f"DROP TRIGGER IF EXISTS {lock_name} ON {table}",
        f"CREATE TRIGGER {lock_name} BEFORE INSERT OR UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION "
        "memory_comparison_lock_benchmark_fact_child_target()",
        f"DROP TRIGGER IF EXISTS {policy_name} ON {table}",
        f"CREATE TRIGGER {policy_name} BEFORE INSERT OR UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION "
        "memory_comparison_enforce_benchmark_fact_child_fence()",
    )


STRICT_V4_FACT_GRAPH_FENCE_STATEMENTS = (
    STRICT_V4_FACT_CHILD_LOCK_SQL,
    STRICT_V4_FACT_CHILD_POLICY_SQL,
    STRICT_V4_FACT_RECEIPT_POLICY_SQL,
    STRICT_V4_FACT_OUTBOX_RECEIPT_SQL,
    *(statement for table in STRICT_V4_FACT_CHILD_TABLES for statement in _child_triggers(table)),
    "DROP TRIGGER IF EXISTS trg_memory_outbox_benchmark_fact_receipt ON memory_outbox",
    "CREATE CONSTRAINT TRIGGER trg_memory_outbox_benchmark_fact_receipt "
    "AFTER INSERT ON memory_outbox DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
    "EXECUTE FUNCTION memory_comparison_verify_benchmark_fact_outbox_receipt()",
    "DROP TRIGGER IF EXISTS trg_memory_fact_operation_receipt_benchmark_fact_policy "
    "ON memory_fact_operation_receipts",
    "CREATE TRIGGER trg_memory_fact_operation_receipt_benchmark_fact_policy "
    "BEFORE INSERT ON memory_fact_operation_receipts FOR EACH ROW EXECUTE FUNCTION "
    "memory_comparison_enforce_benchmark_fact_receipt()",
)


__all__ = (
    "STRICT_V4_FACT_CHILD_TABLES",
    "STRICT_V4_FACT_GRAPH_FENCE_STATEMENTS",
)
