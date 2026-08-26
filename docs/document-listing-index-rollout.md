# Online document listing index rollout

Migration `0052_document_scope_listing_indexes` is an online, forward-only
migration executed by the existing Infinity Context migration runner.

## Invariants

- Run exactly one migration service during rollout. The runner also holds the
  Infinity Context session advisory lock. A second conforming runner polls for
  at most 60 seconds total, including every lock query, without retaining a
  transaction snapshot that could block `CREATE INDEX CONCURRENTLY`. The runner
  issues no lock query after that deadline and fails if the first runner is
  still active. A timed-out, cancelled, or failed acquisition
  discards its physical connection because PostgreSQL may have acquired the
  session lock before the driver returned control.
- The migration service must use a direct PostgreSQL connection. Transaction
  poolers cannot preserve the session advisory lock.
- Each `CREATE INDEX CONCURRENTLY` statement runs in autocommit mode and outside
  the schema-history transaction.
- Application instances may keep serving reads and writes during index builds.
- Do not enable the collection scan consumer until the migration history records
  `0052_document_scope_listing_indexes`.

## Preflight and observation

Before rollout, record table size and active writes:

```sql
SELECT pg_size_pretty(pg_total_relation_size('memory_documents'));
SELECT pid, state, wait_event_type, wait_event, query
FROM pg_stat_activity
WHERE datname = current_database();
```

During rollout, observe build progress and blocking:

```sql
SELECT * FROM pg_stat_progress_create_index
WHERE relid = 'memory_documents'::regclass;

SELECT pid, wait_event_type, wait_event, query
FROM pg_stat_activity
WHERE query ILIKE '%memory_documents%';
```

A populated-clone qualification must install the exact published PR57 migration
history through `0051` before applying `0052`, demonstrate that ordinary inserts
continue while all three indexes build, and record wall time, maximum insert
latency, pre/post table row count, concurrent insert count, and each final public
index's `indisready`, `indisvalid`, and canonical `pg_get_indexdef` definition.
Run the bounded qualification against a disposable hosted PostgreSQL 18 server
with:

```bash
INFINITY_CONTEXT_TEST_POSTGRES_URL="$DISPOSABLE_POSTGRES_ADMIN_URL" \
  .venv/bin/python -m pytest \
  tests/e2e/test_document_listing_online_indexes_postgres18.py -q -s
```

The test creates and drops its own uniquely named database and skips when the
environment variable is absent. Preserve the single
`document_listing_online_index_qualification=...` JSON line as rollout evidence.

## Crash and invalid-index recovery

A concurrent build interrupted by a crash can leave an invalid index. On retry,
the runner checks the three declared recoverable index names in `pg_index`,
drops only invalid ones with `DROP INDEX CONCURRENTLY`, rebuilds them, verifies
that every index exists with `indisvalid = true`, and only then records schema
history. A valid index from a crash after completion is reused by
`CREATE INDEX CONCURRENTLY IF NOT EXISTS`.

To inspect manually:

```sql
SELECT index_class.relname, index_state.indisready, index_state.indisvalid
FROM pg_index AS index_state
JOIN pg_class AS index_class ON index_class.oid = index_state.indexrelid
WHERE index_class.relname IN (
  'ix_memory_documents_scope_status_page',
  'ix_memory_documents_scope_thread_status_page',
  'ix_memory_documents_scope_thread_source_page'
);
```

## Deterministic rollback

Rollback is operational and does not rewind schema history automatically. Stop
the document collection consumer, obtain the same one-writer maintenance window,
then run each statement separately in autocommit mode:

```sql
DROP INDEX CONCURRENTLY IF EXISTS ix_memory_documents_scope_thread_source_page;
DROP INDEX CONCURRENTLY IF EXISTS ix_memory_documents_scope_thread_status_page;
DROP INDEX CONCURRENTLY IF EXISTS ix_memory_documents_scope_status_page;
```

After rollback, remove the `0052` history row only as part of an approved restore
procedure. A normal forward deployment must never edit published migration
history.
