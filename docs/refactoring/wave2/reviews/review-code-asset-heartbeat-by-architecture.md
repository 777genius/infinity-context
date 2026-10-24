# Independent code review: extraction progress concurrency

Decision: **production source APPROVED; no blocking code finding**. Reviewed exact product commit `4aeeb4d274b2eacc8b673154b4370732788d85d8` and test-only followup `4e56dd9e2443ba6a348f186b66e4b5c8fa4f867c`. The separate pooled-loop fixture amendment and its functional completion evidence are not implied by this production approval.

## Atomic boundary

The dedicated progress port has an explicit snapshot/return/error/commit contract. The PostgreSQL adapter rejects invalid identities, canceled snapshots and regressing progress timestamps. One atomic conditional UPDATE guards running status, id, attempt, lease owner, start/update/heartbeat/expiry snapshot and absent cancellation. It modifies only progress metadata, heartbeat, lease expiry and update time, then reloads the persisted row with populate_existing on both success and conflict. Missing rows raise not-found; the caller owns commit. Generic save and intentional retry/new-attempt/success reset transitions remain unchanged.

Read the entire production diff: shared domain helpers handle execution identity and UTC interpretation without infrastructure dependencies. Core progress processing refuses canceled/terminal/replacement state and keeps timestamps monotonic even if the clock moves backward. Supervision retains the original immutable attempt, checks fresh identity/cancellation before returning a completed provider result, and rejects a replacement returned from a heartbeat conflict. Completed stale task exceptions are retrieved; active-owner provider errors still propagate. No call traversal, provider implementation, worker scheduling policy or timeout assertion changes. The near-cap orchestrator remains 996 lines and repository 919.

## Independent assessment and execution

Inspected all deterministic real-repository race tests and the expanded negative matrix. Barriers force cancellation, terminal state or a new attempt to commit after the heartbeat snapshot but before its write; whole returned/persisted rows are checked. Strong ORM-reference coverage establishes a genuinely fresh conflict read. Other cases cover nullable snapshots, timezone offsets, backward clocks, owned SQL columns, no adapter commit, invalid proposals and legitimate reset semantics. This is stronger than a timing-only cancellation reproducer.

Independently ran **six SQLite cases** covering all three winning transitions, a retained ORM identity-map conflict, nullable/offset handling and allowed-column writes: **6 passed, 6 PostgreSQL variants deselected in 3.13 seconds**. Independently ran the three completed-provider stale/active exception cases: **3 passed in 3.79 seconds**. Full logs are `heartbeat-independent-architecture-sqlite.log` and `heartbeat-independent-architecture-supervision.log` under coordinator evidence. Counts overlap the owner's focused suites and must not be added as distinct cases.

The owner separately established actual PostgreSQL 18 and SQLite execution, the original-function pre-fix lost-cancellation diagnostic, expanded adapter validation and supervisor regressions. These are separate evidence, not claimed as independently rerun here.

The unchanged original heartbeat API test still exposed an unsupported shared-engine cross-event-loop fixture topology after the production CAS repair. A distinct twice-reviewed fixture-only amendment routes its worker and three readbacks to the existing live TestClient portal, preserving all assertions and the five-second join. This approval does not claim that residual timeout's exact internal mechanism was proven or that the amended original node has already passed. No broader lifecycle race-safety claim is made beyond the owned progress transition.

## Separate fixture amendment review

Exact fixture commit `afde2d95050fac1184b81f5373499c3abeacef9e` is **APPROVED; no blocking findings**. Independently reversed only its four portal execution wrappers in the complete parsed file and obtained exact original file AST equality. The worker still runs behind the same blocking external thread; constructor/run_once options, all eleven ordered assertions, the five-second join, failure capture and cleanup are unchanged. The existing live TestClient portal owns all database operations; no pool, engine, timeout, retry or production configuration changes.

Inspected separate runtime evidence: the normal original node passed **1 test in 9.83 seconds**. A less intrusive SQLAlchemy-event scratch probe, without added middleware/tasks, also passed and recorded HTTP database work, worker construction/run/SQL and exactly three readbacks on the same portal loop/thread. An earlier middleware-instrumented probe failed and remains retained; neither this review nor the owner claims that its precise residual timeout mechanism was proven. The serial affected-file gate remains separate runtime acceptance evidence.
