# Lifecycle plan round 1 — independent core-owner critique

Reviewer: core/context owner. Base inspected: `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`. Reviewed lifecycle plan and actual UoW/repository/package sources, schema/error/batching/replay tests and accepted ADR boundaries. Read-only; no tests or source edits.

Decision: **direction supported; one required evidence clarification before round 2**. Both slices earn their scope without a framework. No discovered behavior defect or reason to relax an ADR.

## Verified architecture value

L1 moves actual schema evolution and bootstrap behavior out of transaction/session ownership. The source does contain the documented exact 15-step bootstrap order; `create_schema` delegates PostgreSQL to a local `upgrade_schema` import and registers `_ensure_runtime_schema` directly for other dialects. `test_benchmark_writer_fence.py:263–268` asserts callback object identity, so explicit aliasing rather than a wrapper is necessary and correctly planned. The current unusual outbox fairness index placement inside the duplicate-suggestion helper is real; keeping it intact avoids an incidental semantic cleanup.

L2 separates six capability implementations currently collected in a 988-line module. Grouping documents/chunks is justified by their shared parent/evidence locks and canonical visibility/version behavior. UoW construction at lines 885–919 passes one session to all repositories and captures `now` once. No repository abstraction or auto-registration is needed. The old repository facade must retain the two `record_repositories` reexports and keyword helper alongside all six class aliases, as planned.

The source/tests support the behavioral ledgers: actual canonical retrieval tests import legacy repository aliases; episode replay deliberately opens a fresh UoW after a conflict; schema tests execute repeated creation and legacy uniqueness reconstruction. Real SQLite HTTP/worker smoke is useful composition evidence, and the plan correctly avoids presenting that as PostgreSQL concurrency proof.

## Required clarification L-C1 — add global-binding proof to the before-source relocation inventory

The plan mandates unchanged AST bodies and aliases, but relocation changes the globals namespace even when AST is identical. This matters directly here: schema functions call installers/introspection globals, and repository methods call mapper, SQL, lock and canonical batching globals imported into their defining module. AST equality plus old/new class identity does not establish that these bindings are still the same objects. Missing or accidentally redirected imports may only affect a rare branch outside the focused tests.

Before moving production code, record each moved function/method's externally loaded global names and identify the defining module/object of callable/class dependencies. After relocation, compare the destination bindings to the original dependencies, allowing only the explicitly moved internal helper aliases. Assert the ordered schema callback references and one-session repository construction against this inventory. This can remain a small audit script/report and independent code-review checklist; do not add a generic runtime indirection layer or large implementation-mirroring test suite. Cover `JSON`, `bindparam`, `inspect`, `text`, metadata/seed/fence/trigram installers for L1, and SQLAlchemy models/mappers/source-ref locks/batching helpers for L2.

Resolve metadata compatibility in that record: functions and repository classes acquire their new canonical `__module__`; old import paths resolve explicit aliases. The plan already explains moved function metadata for L1, but should state the equivalent class metadata scope for L2. Compare evaluated annotations/type hints so moving `AsyncSession`, domain contracts or return types does not leave unresolved annotations. There is no need to promise unsupported assignment-to-old-module monkeypatch behavior.

## Nonblocking cautions

1. Keep the old schema module's genuinely used imported helper/error names in the compatibility inventory; do not blindly preserve every incidental stdlib import as a new public API.
2. No new PostgreSQL service is required for unchanged SQL/locking bodies if global binding and behavioral evidence agree. Existing optional DSN skips should be recorded explicitly.
3. The focused suites are concrete and appropriate; root escalation must be used for actual API/process execution. No additional paid/provider validation is warranted.
4. Add a small dependency-direction assertion or explicit import audit demonstrating schema owners do not import UoW/repositories and new capability owners do not import the compatibility facade. Full architecture currently checks broader package boundaries and may not detect this local regression.

Proceed only after both critics' round-2 approval and root release.
