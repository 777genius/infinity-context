"""Postgres fences for the provider-free strict-v4 document graph."""

from __future__ import annotations

STRICT_V4_DOCUMENT_CHILD_TABLES = ("memory_chunks", "memory_outbox")

STRICT_V4_DOCUMENT_CHILD_LOCK_SQL = """
CREATE OR REPLACE FUNCTION memory_comparison_lock_benchmark_document_child_target()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    target_document_id VARCHAR(80);
    target_space_id VARCHAR(80);
BEGIN
    IF TG_TABLE_NAME = 'memory_outbox' THEN
        IF TG_OP = 'DELETE' THEN
            IF OLD.aggregate_type <> 'chunk' THEN RETURN OLD; END IF;
            target_document_id := NULL;
            SELECT chunk.document_id, document.space_id
            INTO target_document_id, target_space_id
            FROM public.memory_chunks AS chunk
            JOIN public.memory_documents AS document ON document.id = chunk.document_id
            WHERE chunk.id = OLD.aggregate_id;
        ELSE
            IF NEW.aggregate_type <> 'chunk' THEN RETURN NEW; END IF;
            SELECT chunk.document_id, document.space_id
            INTO target_document_id, target_space_id
            FROM public.memory_chunks AS chunk
            JOIN public.memory_documents AS document ON document.id = chunk.document_id
            WHERE chunk.id = NEW.aggregate_id;
        END IF;
    ELSE
        IF TG_OP = 'DELETE' THEN
            target_document_id := OLD.document_id;
        ELSE
            target_document_id := NEW.document_id;
        END IF;
        SELECT document.space_id INTO target_space_id
        FROM public.memory_documents AS document
        WHERE document.id = target_document_id;
    END IF;
    IF target_document_id IS NULL OR target_space_id IS NULL THEN
        RAISE EXCEPTION 'benchmark document child parent is missing'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    BEGIN
        PERFORM 1
        FROM public.memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = target_space_id
        FOR SHARE NOWAIT;
    EXCEPTION WHEN lock_not_available THEN
        RAISE EXCEPTION 'benchmark document child writer fence rejected data mutation'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
""".strip()

STRICT_V4_DOCUMENT_CHILD_POLICY_SQL = """
CREATE OR REPLACE FUNCTION memory_comparison_enforce_benchmark_document_child_fence()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    target_document_id VARCHAR(80);
    target_space_id VARCHAR(80);
    parent_scope_id VARCHAR(80);
    parent_thread_id VARCHAR(80);
    parent_source_type VARCHAR(80);
    parent_source_external_id VARCHAR(240);
    parent_classification VARCHAR(40);
    parent_status VARCHAR(40);
    registry_state VARCHAR(40);
    registry_projection_state VARCHAR(40);
    registry_cleanup_plan_state VARCHAR(40);
    registry_run_id CHAR(64);
    strict_authorized BOOLEAN := FALSE;
    canonical_writer BOOLEAN := public.memory_comparison_is_strict_v4_canonical_writer();
BEGIN
    IF TG_TABLE_NAME = 'memory_outbox' THEN
        IF TG_OP = 'DELETE' THEN
            IF OLD.aggregate_type <> 'chunk' THEN RETURN OLD; END IF;
            SELECT chunk.document_id INTO target_document_id
            FROM public.memory_chunks AS chunk WHERE chunk.id = OLD.aggregate_id;
        ELSE
            IF NEW.aggregate_type <> 'chunk' THEN RETURN NEW; END IF;
            SELECT chunk.document_id INTO target_document_id
            FROM public.memory_chunks AS chunk WHERE chunk.id = NEW.aggregate_id;
        END IF;
    ELSE
        IF TG_OP = 'DELETE' THEN target_document_id := OLD.document_id;
        ELSE target_document_id := NEW.document_id;
        END IF;
    END IF;
    SELECT document.space_id, document.memory_scope_id, document.thread_id,
           document.source_type, document.source_external_id,
           document.classification, document.status
    INTO target_space_id, parent_scope_id, parent_thread_id,
         parent_source_type, parent_source_external_id,
         parent_classification, parent_status
    FROM public.memory_documents AS document
    WHERE document.id = target_document_id;
    SELECT benchmark_run.state, benchmark_run.projection_cleanup_state,
           benchmark_run.cleanup_plan_state, benchmark_run.run_id_sha256
    INTO registry_state, registry_projection_state,
         registry_cleanup_plan_state, registry_run_id
    FROM public.memory_comparison_benchmark_runs AS benchmark_run
    WHERE benchmark_run.space_id = target_space_id;
    IF registry_state IS NULL THEN
        IF canonical_writer THEN
            RAISE EXCEPTION 'strict-v4 canonical writer cannot mutate an unmanaged document child'
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
    IF TG_OP = 'INSERT' AND NOT canonical_writer AND NOT strict_authorized
        AND registry_state = 'active' AND registry_projection_state = 'unsealed'
        AND registry_cleanup_plan_state = 'sealed'
    THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'INSERT' AND canonical_writer AND strict_authorized
        AND registry_state = 'active' AND registry_projection_state = 'unsealed'
    THEN
        IF TG_TABLE_NAME = 'memory_chunks' THEN
            IF NEW.space_id = target_space_id
                AND NEW.memory_scope_id = parent_scope_id
                AND COALESCE(NEW.thread_id, '') = COALESCE(parent_thread_id, '')
                AND NEW.episode_id IS NULL
                AND NEW.source_type = parent_source_type
                AND NEW.source_external_id = parent_source_external_id
                AND NEW.classification = parent_classification
                AND NEW.status = 'active'
                AND parent_status = 'active'
                AND NEW.sequence >= 0
                AND NEW.char_start >= 0
                AND NEW.char_end >= NEW.char_start
            THEN RETURN NEW; END IF;
        ELSIF TG_TABLE_NAME = 'memory_outbox' THEN
            IF NEW.aggregate_type = 'chunk'
                AND NEW.event_type = 'vector.upsert_chunk'
                AND NEW.aggregate_version IS NULL
                AND NEW.status = 'pending'
                AND NEW.attempt_count = 0
                AND NEW.workload_class = 'projection'
                AND NEW.payload_json = pg_catalog.jsonb_build_object(
                    'chunk_id', NEW.aggregate_id
                )
            THEN RETURN NEW; END IF;
        END IF;
    END IF;
    RAISE EXCEPTION 'benchmark document child writer fence rejected data mutation'
        USING ERRCODE = '23514',
              CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
END;
$$;
""".strip()

STRICT_V4_DOCUMENT_IDEMPOTENCY_SQL = """
CREATE OR REPLACE FUNCTION memory_comparison_enforce_benchmark_document_idempotency()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT public.memory_comparison_is_strict_v4_canonical_writer() THEN
        RETURN NEW;
    END IF;
    IF NEW.result_type <> 'document'
       AND NEW.key NOT LIKE 'managed-benchmark-document-v4-%'
    THEN
        RETURN NEW;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = NEW.space_id
    ) OR NEW.result_type <> 'document'
       OR NEW.key NOT LIKE 'managed-benchmark-document-v4-%'
       OR pg_catalog.length(NEW.key) <> 94
       OR NOT EXISTS (
           SELECT 1 FROM public.memory_documents AS document
           WHERE document.id = NEW.result_id
             AND document.space_id = NEW.space_id
             AND document.content_hash = NEW.fingerprint
             AND document.status = 'active'
       )
    THEN
        RAISE EXCEPTION 'benchmark document idempotency receipt is invalid'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    RETURN NEW;
END;
$$;
""".strip()

STRICT_V4_DOCUMENT_RECEIPT_SQL = """
CREATE OR REPLACE FUNCTION memory_comparison_verify_benchmark_document_receipt()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT public.memory_comparison_is_strict_v4_canonical_writer() THEN
        RETURN NEW;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.memory_comparison_benchmark_runs AS benchmark_run
        WHERE benchmark_run.space_id = NEW.space_id
    ) THEN RETURN NEW; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.memory_idempotency_records AS receipt
        WHERE receipt.space_id = NEW.space_id
          AND receipt.result_type = 'document'
          AND receipt.result_id = NEW.id
          AND receipt.fingerprint = NEW.content_hash
          AND receipt.key LIKE 'managed-benchmark-document-v4-%'
          AND pg_catalog.length(receipt.key) = 94
    ) OR NOT EXISTS (
        SELECT 1 FROM public.memory_chunks AS chunk
        WHERE chunk.document_id = NEW.id
    ) OR EXISTS (
        SELECT 1 FROM public.memory_chunks AS chunk
        WHERE chunk.document_id = NEW.id
          AND NOT EXISTS (
              SELECT 1 FROM public.memory_outbox AS outbox
              WHERE outbox.aggregate_type = 'chunk'
                AND outbox.aggregate_id = chunk.id
                AND outbox.event_type = 'vector.upsert_chunk'
                AND outbox.payload_json = pg_catalog.jsonb_build_object(
                    'chunk_id', chunk.id
                )
          )
    ) THEN
        RAISE EXCEPTION 'benchmark document receipt is missing or incomplete'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_memory_comparison_benchmark_run_writer_fence';
    END IF;
    RETURN NEW;
END;
$$;
""".strip()


def _child_triggers(table: str) -> tuple[str, str, str, str]:
    lock = f"trg_00_{table}_benchmark_document_child_lock"
    policy = f"trg_{table}_benchmark_document_child_fence"
    return (
        f"DROP TRIGGER IF EXISTS {lock} ON {table}",
        f"CREATE TRIGGER {lock} BEFORE INSERT OR UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION "
        "memory_comparison_lock_benchmark_document_child_target()",
        f"DROP TRIGGER IF EXISTS {policy} ON {table}",
        f"CREATE TRIGGER {policy} BEFORE INSERT OR UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION "
        "memory_comparison_enforce_benchmark_document_child_fence()",
    )


STRICT_V4_DOCUMENT_GRAPH_FENCE_STATEMENTS = (
    STRICT_V4_DOCUMENT_CHILD_LOCK_SQL,
    STRICT_V4_DOCUMENT_CHILD_POLICY_SQL,
    STRICT_V4_DOCUMENT_IDEMPOTENCY_SQL,
    STRICT_V4_DOCUMENT_RECEIPT_SQL,
    *_child_triggers("memory_chunks"),
    "DROP TRIGGER IF EXISTS trg_00_memory_outbox_benchmark_fact_child_lock ON memory_outbox",
    "DROP TRIGGER IF EXISTS trg_memory_outbox_benchmark_fact_child_fence ON memory_outbox",
    "CREATE TRIGGER trg_00_memory_outbox_benchmark_fact_child_lock "
    "BEFORE INSERT OR UPDATE ON memory_outbox FOR EACH ROW "
    "WHEN (NEW.aggregate_type = 'fact') EXECUTE FUNCTION "
    "memory_comparison_lock_benchmark_fact_child_target()",
    "CREATE TRIGGER trg_00_memory_outbox_benchmark_fact_child_delete_lock "
    "BEFORE DELETE ON memory_outbox FOR EACH ROW "
    "WHEN (OLD.aggregate_type = 'fact') EXECUTE FUNCTION "
    "memory_comparison_lock_benchmark_fact_child_target()",
    "CREATE TRIGGER trg_memory_outbox_benchmark_fact_child_fence "
    "BEFORE INSERT OR UPDATE ON memory_outbox FOR EACH ROW "
    "WHEN (NEW.aggregate_type = 'fact') EXECUTE FUNCTION "
    "memory_comparison_enforce_benchmark_fact_child_fence()",
    "CREATE TRIGGER trg_memory_outbox_benchmark_fact_child_delete_fence "
    "BEFORE DELETE ON memory_outbox FOR EACH ROW "
    "WHEN (OLD.aggregate_type = 'fact') EXECUTE FUNCTION "
    "memory_comparison_enforce_benchmark_fact_child_fence()",
    "DROP TRIGGER IF EXISTS trg_00_memory_outbox_benchmark_document_child_lock ON memory_outbox",
    "CREATE TRIGGER trg_00_memory_outbox_benchmark_document_child_lock "
    "BEFORE INSERT OR UPDATE ON memory_outbox FOR EACH ROW "
    "WHEN (NEW.aggregate_type = 'chunk') EXECUTE FUNCTION "
    "memory_comparison_lock_benchmark_document_child_target()",
    "CREATE TRIGGER trg_00_memory_outbox_benchmark_document_child_delete_lock "
    "BEFORE DELETE ON memory_outbox FOR EACH ROW "
    "WHEN (OLD.aggregate_type = 'chunk') EXECUTE FUNCTION "
    "memory_comparison_lock_benchmark_document_child_target()",
    "DROP TRIGGER IF EXISTS trg_memory_outbox_benchmark_document_child_fence ON memory_outbox",
    "CREATE TRIGGER trg_memory_outbox_benchmark_document_child_fence "
    "BEFORE INSERT OR UPDATE ON memory_outbox FOR EACH ROW "
    "WHEN (NEW.aggregate_type = 'chunk') EXECUTE FUNCTION "
    "memory_comparison_enforce_benchmark_document_child_fence()",
    "CREATE TRIGGER trg_memory_outbox_benchmark_document_child_delete_fence "
    "BEFORE DELETE ON memory_outbox FOR EACH ROW "
    "WHEN (OLD.aggregate_type = 'chunk') EXECUTE FUNCTION "
    "memory_comparison_enforce_benchmark_document_child_fence()",
    "DROP TRIGGER IF EXISTS trg_memory_idempotency_benchmark_document_policy "
    "ON memory_idempotency_records",
    "CREATE TRIGGER trg_memory_idempotency_benchmark_document_policy "
    "BEFORE INSERT ON memory_idempotency_records FOR EACH ROW EXECUTE FUNCTION "
    "memory_comparison_enforce_benchmark_document_idempotency()",
    "DROP TRIGGER IF EXISTS trg_memory_document_benchmark_document_receipt ON memory_documents",
    "CREATE CONSTRAINT TRIGGER trg_memory_document_benchmark_document_receipt "
    "AFTER INSERT ON memory_documents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
    "EXECUTE FUNCTION memory_comparison_verify_benchmark_document_receipt()",
)

__all__ = (
    "STRICT_V4_DOCUMENT_CHILD_TABLES",
    "STRICT_V4_DOCUMENT_GRAPH_FENCE_STATEMENTS",
)
