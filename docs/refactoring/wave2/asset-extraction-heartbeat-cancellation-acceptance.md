# Asset extraction heartbeat repair acceptance

## Outcome and source

The focused repair and separately reviewed fixture amendment are approved by the root coordinator and independent architecture reviewer. The final normal affected-file gate passed **57 tests with no skips or failures** on source `afde2d95050fac1184b81f5373499c3abeacef9e`, tree `7752f4b48a7b216275c86bd11f713115f91a9825`, unchanged before and after execution.

The branch is based on published main `35ea68be`, so its pull request contains the bounded repair rather than duplicating the architecture refactor branches. Plan commit `7a10a34a` records both critics' two plan rounds. Product `4aeeb4d2`, explicit contract coverage `4e56dd9e` and fixture amendment `afde2d95` remain separate audit steps. This acceptance document adds no production or test changes.

## Original full unit run is preserved

The original frozen architecture candidate was `6fce8875ec8e0c2e13a8560cb312557bd67261ef`, tree `5f519f53bf64c376cbebe9a040c903e5a501bbf7`. Its complete collection contained **12,301 unique nodes in 696 files**, partitioned exactly once across eight deterministic file shards with at most two pytest processes. The original result remains **12,277 passed, 23 skipped and one failed; six passed subtests are reported separately**. Its source pin and tracked state remained unchanged. A single isolated repeat reproduced the same failure and is recorded separately.

The failure was the original heartbeat test's unchanged five-second worker-completion assertion. Its heartbeat timestamp had advanced and HTTP cancellation returned 202. This original full run is not relabeled as a passing run, and focused or repeated test counts are not added to its unique passes.

The 23 optional skips were: eight pinned-mem0 parity cases; three Phase-C runtime requirements and three unavailable pinned Phase-C integrations; four LongMemEval opt-ins and one unstaged official LongMemEval case; two LoCoMo opt-ins and one official LoCoMo opt-in; one PostgreSQL opt-in. Exact skipped node IDs and reasons remain in the source-bound unit summary.

The restored test environment initially lacked `yaml`. Only the existing locked `PyYAML==6.0.3` was restored before successful collection. Source and lockfile were not changed by that environment repair.

## Confirmed production defect and boundary

A same-event-loop diagnostic forced the actual lifecycle to read a heartbeat snapshot, commit a cancellation, then save the stale progress. The original generic save erased `cancellation_requested_at`, overwrote cancellation metadata and moved `updated_at` backward. A retained synthetic SQLite database and event record establish this lost-update defect without a cross-event-loop fixture assumption. The deterministic regression also fails through the original pre-fix lifecycle on erased cancellation and changed persisted state, rather than because a new API is missing.

The repair adds a dedicated atomic running-progress operation. It updates only metadata, heartbeat, lease expiry and update time when the persisted row still matches the expected running attempt, lease and timestamp snapshot and has no cancellation request. Invalid proposals and regressing times cannot write. Both success and conflict return freshly loaded persisted state, including when an ORM identity-map reference is retained. The unit of work still owns commit.

Core progress processing preserves newer times and refuses cancelled, terminal or replacement ownership. Supervision keeps the original execution identity, checks fresh state before accepting completed provider output and consumes discarded completed-task errors while preserving active parser failures. Generic save, retry, new-attempt and terminal cancellation resets remain unchanged. This does not claim that every pre-existing generic lifecycle race has been solved.

## Focused evidence, with overlap kept explicit

| Evidence | Recorded outcome | Scope |
|---|---:|---|
| Original-function pre-fix regression | 1 failed as expected | Actual committed cancellation is erased by the old progress path |
| Initial real SQLite/PostgreSQL 18 CAS matrix | 36 passed | Deterministic transition races, cache freshness, monotonicity, NULL/offset handling, four-column write and reset behavior |
| Expanded explicit-contract matrix | 44 passed | Includes the additional expected-snapshot and nullable-time rejection cases; overlaps the preceding matrix |
| Final explicit/missing selector on `4e56dd9e` | 10 passed | Eight newly explicit dialect cases plus the two dedicated missing-row cases; not added to the matrix as new unique coverage |
| Owner supervision file | 4 passed | Existing terminal behavior plus stale-completed and active-error behavior |
| Independent architecture execution | 6 SQLite cases and 3 supervision cases passed | Overlaps the owner's focused suites; separate independent evidence |
| Normal exact original heartbeat node on `afde2d95` | 1 passed in 9.83 seconds | Original assertions and five-second join retained |
| Final normal affected three files on `afde2d95` | 57 passed in 78.41 seconds | Source-bound log, JUnit and before/after provenance; includes overlapping original-node and supervision coverage |

PostgreSQL tests used uniquely named owned schemas on the cleared PostgreSQL 18.6 service and removed them afterward. No cluster defaults, capabilities, roles or other databases were changed by the CAS proof.

## Separate fixture ownership repair

After the production CAS repair, a focused run still hit the original join assertion while extraction had correctly become `canceled` and its outbox row remained `running`. Inspection confirmed that the fixture shared one pooled async engine across its TestClient loop, worker `asyncio.run` loop and three independent readback loops. A scratch teardown invocation did not reproduce the blocked boundary, so its precise timeout mechanism is not claimed as proven.

The separately twice-reviewed fixture amendment schedules worker construction/execution and all three readbacks through the existing live TestClient portal. The original external worker thread still blocks until asynchronous work completes. No `NullPool`, new engine, retry, sleep, production pooling change or timeout relaxation was introduced.

AST proof established exact equality of all eleven ordered assertion subtrees and the worker constructor, `run_once(limit=10)` and `join(timeout=5)` calls. The API file remains exactly 3,051 lines and its legacy size ceiling is unchanged. An earlier middleware-instrumented ownership probe failed and is preserved as failed scratch instrumentation. A later lightweight SQLAlchemy-event probe added no ASGI middleware or new task scheduling and passed: HTTP database work, worker construction/run/SQL and exactly three readbacks all used the same portal loop and thread. Normal pytest execution, rather than instrumentation, supplies the final 57-test functional result.

## Reviews, limits and evidence records

The independent architecture review is preserved in `reviews/review-code-asset-heartbeat-by-architecture.md`; the coordinator's independent review record is `reviews/review-code-asset-heartbeat-by-root.md`. Both approve the product and final fixture amendment with no remaining blocking code findings. Changed-file Ruff and diff checks passed. The supervisor is 996 lines, repository 919 lines and original API test file 3,051 lines with an unchanged existing ceiling. Frozen fixtures and architecture inventories were not changed.

Coordinator evidence under `evidence/wave2` includes:

- `final-unit-acceptance-summary.json`, `final-unit-acceptance-note.md` and the complete original collection/shard logs, JUnit and source pin.
- `worker-completion-repeat.log`, `.xml` and `.json`, preserving the separate failed repeat.
- `cancellation-diagnostic.json` and `.db`, plus `heartbeat-prefixtest.log`.
- `heartbeat-sqlite-pg18-regressions.log`, `heartbeat-sqlite-pg18-regressions-expanded.log`, `heartbeat-explicit-contract-cases.log` and `heartbeat-supervision.log`.
- `heartbeat-fixture-ast-equivalence.json`, `heartbeat-fixture-loop-proof.json`, retained `heartbeat-fixture-middleware-probe-failed.json` and `worker-teardown-diagnostic.json`.
- `heartbeat-exact-fixed.log` and `heartbeat-affected-fixed.log`, `.xml` and `.json`.

Combined architecture, managed replay and real multimodal/LongMemEval acceptance remain coordinator-owned gates. No outcome for those pending real E2E runs is implied by this focused acceptance.
