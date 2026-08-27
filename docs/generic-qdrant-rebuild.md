# Generic Qdrant rebuild operator contract

PostgreSQL is authoritative. This workflow repairs the generic Qdrant collection after
`vector.delete_canonical_versions_rebuild_required` or
`qdrant.delete_rebuild_required`, including dead outbox deliveries and historical
points without a canonical version.

First inspect one exact scope without provider I/O:

```bash
infinity-context-admin reindex-qdrant \
  --space SPACE_SLUG \
  --memory_scope SCOPE_EXTERNAL_REF \
  --batch-size 100 \
  --deadline-seconds 30 \
  --preflight-only
```

Apply with a stable operator-generated operation id:

```bash
infinity-context-admin reindex-qdrant \
  --space SPACE_SLUG \
  --memory_scope SCOPE_EXTERNAL_REF \
  --batch-size 100 \
  --deadline-seconds 30 \
  --operation-id incident-2026-08-27-scope-a \
  --i-understand-this-enqueues-projection-jobs
```

The service's configured token remains in `MEMORY_SERVICE_TOKEN`. Put the operator's
matching credential in `INFINITY_CONTEXT_ADMIN_TOKEN`, or pass its environment-variable
name with `--auth-token-env NAME`. Token values are never accepted as command-line
arguments or included in output. `--preflight-only` is read-only. Deadlines are
restricted to the documented bounded choices and page size remains hard-bounded to 1
through 256.

The apply command only persists the first recovery page. A normal projection worker
executes it. The initiating transaction persists the scope's monotonic canonical
commit watermark, the recoverable dead-event watermark, and a composite
`(retrieval_commit_watermark, chunk_id)` cursor in a dedicated operation row. Every
page reads at most `--batch-size` rows in that stable order. Rows inserted or versioned
after the captured watermark are excluded and remain owned by normal ingestion outbox
events.

Reissue the exact command and operation id to inspect/resume an active or dead page.
Changing its scope or batch size is refused. A crash before provider mutation simply
replays the page. A crash after provider mutation but before cursor commit also replays
the same idempotent page. A crash after cursor commit leaves the successor durably
queued behind the current fairness key.

For each row the worker holds its canonical PostgreSQL row lock across the bounded
provider mutation. Active, embeddable rows use the stable deterministic chunk point
identity and a current canonical-version payload. The same lock fences normal upserts
and deletes, so a late older worker cannot overwrite a newer generation. Deleted or
ineligible rows authorize removal only of unversioned, same-tombstone, or older
generations. Qdrant results remain candidate evidence and normal reads still hydrate
and version-check against PostgreSQL.

Only after the final page succeeds are rebuild-required delete events at or below the
captured dead-event watermark marked recovered. Legacy document-delete events without
scope fields are resolved from canonical document/chunk ownership. Later arrivals and
other scopes are untouched. Operation status exposes both watermarks, the composite
cursor, and processed/failed counts; `operation_id` is globally unique across scopes.

This command does not repair locator-profile collections, call Graphiti, or bypass the
retrieval-profile maintenance/lease protocol. It must not be pointed at a live provider
from tests; use provider fakes or an explicitly disposable local Qdrant instance.
