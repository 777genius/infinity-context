# Wave 2 lifecycle/persistence audit — 2026-10-23

Status: read-only source audit completed; no production edits, test execution, commits or publication. Owner worktree: `worktrees/arch-lifecycle`; branch `refactor/architecture-lifecycle-20261023`; pinned base `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`.

## Authority and constraints checked

Read `AGENTS.md`, documentation entry points, relevant sections of the three designated source-of-truth plans, accepted ADRs 0002, 0003, 0004, 0007, monotonic-file-size ADR 0008 and ADR 0012, and the preceding lifecycle refactor record `docs/refactoring/lifecycle-services-20261023.md`. Core Lite source-of-truth sections inspected include Architecture/SOLID/fitness functions, Transaction Boundaries, Migration Plan and Outbox And Worker Lite; global reference Postgres Adapter; client integration Transaction And Outbox Policy. No accepted decision changes are proposed.

Postgres remains canonical; application/domain/ports remain inward; all external derived writes remain after canonical commit through existing outbox behavior. Feature capsule placeholders must not be presented as actual implementations by simply relocating legacy adapters. New/repartitioned files remain below 1000 LOC. No runtime attestation weakening, paid provider call, schema redesign, lifecycle policy change, new abstraction framework or dependency bag.

## Highest-impact verified debt

| Rank | Current source | Evidence | Critical improvement proposed |
| --- | --- | --- | --- |
| 1 | `adapters/postgres/unit_of_work.py`, 996 LOC | Engine/session builders, old profile-to-scope schema conversion, additive-column declarations, SQLite table rebuild, temporal backfill/index SQL, outbox/suggestion/capture indexes, runtime schema orchestration, and session/transaction/error lifecycle coexist. Schema compatibility occupies roughly three quarters of a module whose transaction owner is near the hard ceiling. | Separate unchanged schema compatibility and runtime bootstrap from session/UoW lifecycle. Preserve one authoritative bootstrap sequence, legacy compatibility imports and existing integrity-error translation. |
| 2 | `adapters/postgres/repositories.py`, 988 LOC | One module owns episodes, anchors, documents, chunks, captures, suggestions, chunk keyword SQL, and historical reexports of outbox/idempotency classes. Independent capabilities share unrelated ORM/model/mapper imports. Document/chunk deletion and lock semantics are difficult to review alongside suggestion replay and capture optimistic updates. | Move complete repository classes into capability-owned adapter modules, keep document+chunk lifecycle together and preserve the existing import path as an explicit compatibility facade. No algorithm extraction, SQL rewrite or repository port change. |
| 3, deferred | `adapters/postgres/fact_repositories.py`, 995 LOC | Legacy fact writes/history/canonical-snapshot conversion, retrieval batching and relations coexist; actual canonical feature store already exists. | A later fact lifecycle migration needs a dedicated compatibility design; moving this in the same wave risks overlapping canonical fact and temporal behavior. |
| 4, deferred | `application/use_cases/anchors.py`, 1165 LOC; `anchor_extraction.py`, 1144; `anchor_event_extraction.py`, 1571; context-link suggestion use case, 1060 | Large mixed policies remain, but anchor derivation/review/use-case ownership needs a separate feature plan. | Do not broaden persistence changes into extraction/ranking/review policy or mechanically split these merely for line count. |

`record_repositories.py` is already a small focused owner for outbox/idempotency (under 130 LOC), so no new outbox abstraction is justified. The new extraction lifecycle/artifact/result/usage ownership from the first wave remains entirely untouched.

## Compatibility and safety observations

The package `postgres/__init__.py` resolves UoW/builders/create_schema lazily; preserve that import topology. `create_schema` sends PostgreSQL directly to the forward migration runner and only other dialects to the runtime compatibility callback. `test_benchmark_writer_fence.py` imports `_ensure_runtime_schema`, `_ensure_managed_benchmark_writer_fence`, `_is_benchmark_writer_fence_error` directly and asserts callback object identity. Explicit aliases can preserve that identity without copying helper implementations.

Runtime schema order is meaningful: profile conversion before registry `create_all`; singleton seed before compatibility/index work; duplicate pending-suggestion expiration before unique suggestion indexes. Existing outbox fairness index creation is nested in the duplicate-expiration helper; keep that unusual order unchanged in this refactor. Do not fix adjacent ordering issues during relocation.

UoW rollback/close/translation is already sensitive: failed commit rolls back and raises a typed conflict; exceptional exit can roll back again, then close, reset state, and translate only integrity errors. Existing tests assert those counts and original exception causes. The transaction methods and exact benchmark fence matching stay unchanged.

Document and anchor create flush can roll back the caller-owned session on integrity failure; capture optimistic-update flush and episode replay recovery are also observable. Preserve all of them, rather than “improving” transaction handling during separation. Document/chunk writes retain exact thread fences, parent/evidence lock calls, status filters, canonical-version increments, deterministic ordering and batching helpers.

`tests/adapters/test_postgres_canonical_keyword_trigram.py` imports `_keyword_search_statement` from the legacy module, so preserve it as an alias to the actual document repository owner. A repository-wide search found no monkeypatch or qualified-global replacement targeting `postgres.repositories` or `postgres.unit_of_work` helper names; class/session method replacement is separate and continues to operate on the identical class objects. This is a bounded observation, not a promise that undocumented private module-global monkeypatches are public API.

## Validation evidence available and intentionally not repeated

Coordinator-provided base: 11134 unit tests passed, 40 skipped, 6 subtests; 219 architecture checks; seven deterministic eval suites exact; three real HTTP/worker E2E. The shared frozen Python 3.12 environment is reused. No full baseline rerun is proposed. Focused gates are specified in `lifecycle-plan.md`, including unchanged-source characterization before each production slice, AST/body movement audit, import compatibility and local process E2E after the relevant slice. PostgreSQL-only concurrency tests remain conditional on an explicitly available local test DSN; SQLite/process evidence will not be described as Postgres concurrency proof.
