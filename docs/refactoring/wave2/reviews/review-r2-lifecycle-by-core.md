# Lifecycle plan round 2 — independent core-owner approval

Reviewed the revised `lifecycle-plan.md` against round-1 findings and the previously inspected pinned-base sources/tests. Read-only review; no production changes or test runs.

## L1 — approved

The revision resolves L-C1 concretely: named <=400-LOC capture/check audit, pinned source-definition/final-owner manifest, exact free-global dependency binding/provenance, supported namespace scope, evaluated hints and old reference pickle resolution. The actual callback trace freezes all fifteen installer positions and verifies `create_schema.__globals__["_ensure_runtime_schema"]` against the UoW compatibility alias, closing the stale-import identity gap. Reverse imports are explicitly rejected. No dynamic forwarding or migration framework was introduced.

The focused schema/error/benchmark repository suites and mandatory root-provisioned PostgreSQL clean/legacy upgrade + writer-fence gates provide appropriate evidence. Actual HTTP/worker composition remains separate from PostgreSQL concurrency claims.

## L2 — approved

The revised plan applies the same global-binding audit to methods and keyword SQL, explicitly covering SQLAlchemy/model/mapper/lock/batching identities and original annotation objects. Canonical implementation `__module__` migration and supported old reference-pickle behavior are now explicit; no unsupported live-session serialization contract is invented. Old/new aliases and both import orders, exact class/method AST and same-session/one-clock-value construction are all reviewable gates. Canonical PostgreSQL repository/replay/document identity tests are mandatory with root's DSN.

## Remaining conditions

No unresolved blocker for either slice. Keep all moved bodies unchanged and new modules bounded; resolve any actual drift against the pinned oracle rather than changing fixtures. Root must still release implementation after both independent critics' approval. Production review must inspect the recorded global bindings and actual test evidence, not rely on this plan approval as proof of executed behavior.
