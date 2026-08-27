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
  --dry-run
```

Apply with a stable operator-generated operation id:

```bash
infinity-context-admin reindex-qdrant \
  --space SPACE_SLUG \
  --memory_scope SCOPE_EXTERNAL_REF \
  --batch-size 100 \
  --operation-id incident-2026-08-27-scope-a \
  --i-understand-this-enqueues-projection-jobs
```

The apply command only persists the first recovery page. A normal projection worker
executes it. Every page reads at most `--batch-size` canonical chunk rows in stable id
order and commits the next cursor as another outbox delivery. The hard batch range is
1 through 256. The initial row also persists the scan upper bound, so concurrent new
ingestion cannot make the run unbounded; normal ingestion outbox events own rows created
after that boundary.

Reissue the exact command and operation id to inspect/resume an active or dead page.
Changing its scope or batch size is refused. A crash before provider mutation simply
replays the page. A crash after provider mutation but before cursor commit also replays
the same idempotent page. A crash after cursor commit leaves the successor durably
queued behind the current fairness key.

For each row the worker rereads canonical lifecycle inside the projection fence.
Active, embeddable rows are written at their current canonical generation; the generic
point identity includes that generation, so an older late delivery cannot overwrite a
newer point. Deleted or ineligible rows authorize removal only of unversioned or older
generations. Canonical state is reread after the provider effect, and a concurrently
reactivated row is reprojected. Qdrant results remain candidate evidence and normal
reads still hydrate and version-check against PostgreSQL.

Only after the final page succeeds are scope-bound dead rebuild-required delete events
marked recovered. Other dead events are untouched. Keep the operation row for audit;
normal outbox compaction policy may later remove completed rows.

This command does not repair locator-profile collections, call Graphiti, or bypass the
retrieval-profile maintenance/lease protocol. It must not be pointed at a live provider
from tests; use provider fakes or an explicitly disposable local Qdrant instance.
