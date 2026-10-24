# Asset extraction heartbeat and cancellation repair

## Confirmed problem

The full unit run on frozen source `6fce8875ec8e0c2e13a8560cb312557bd67261ef` collected 12,301 unique nodes. Its original result was 12,277 passed, 23 optional skips and one failure, with six passed subtests reported separately. The failure was `test_slow_asset_extraction_refreshes_outbox_running_heartbeat`: both heartbeat assertions passed and cancellation returned HTTP 202, but the worker was still alive after the unchanged five-second join. A single separately recorded repeat reproduced the same failure. Neither attempt is being relabeled as a passing full suite.

A diagnostic then forced this transaction order through the real lifecycle and repository on one event loop and thread:

1. The heartbeat read a running job with no cancellation request and constructed its progress snapshot.
2. Cancellation committed `cancellation_requested_at=2026-10-24 10:14:38.543709+00:00`.
3. The original repository saved the stale heartbeat snapshot. The persisted cancellation became NULL and `updated_at` moved backward to `2026-10-24 10:14:38.540546`.

The diagnostic is causal evidence, not final test proof. Its synthetic SQLite database and JSON event record are preserved outside the repository as `evidence/wave2/cancellation-diagnostic.db` and `cancellation-diagnostic.json`. The lifecycle, repository, mapper, worker and original failing test are unchanged from the earlier baseline. Relevant repair files are also identical between published main `35ea68beab8407995a45683d9592c052f65ed7f4` and the frozen verification source.

The lost update occurs because progress reads a domain snapshot, while generic repository `save` loads the row again and applies every field from that snapshot, including cancellation and lifecycle fields. The defect can occur without fixture cross-event-loop behavior.

## Branch and scope

The focused branch is based on published main `35ea68beab8407995a45683d9592c052f65ed7f4`, so its pull request does not duplicate the open architecture refactor branches. Integration verification uses a separate candidate containing frozen architecture source plus the exact repair delta, and later the corrected multimodal acceptance test.

This repair makes running progress atomic and preserves the original execution identity during extraction supervision. It does not claim to make every existing generic lifecycle read/save transition concurrent-safe. Generic save, retry, new-attempt and terminal transition semantics remain unchanged.

## Reviewed implementation plan

Add one explicit `AssetExtractionRepositoryPort.save_running_progress(proposed, *, expected)` operation returning an extraction job. It never commits. Missing rows use the existing not-found behavior. Mismatched job identities are invalid; non-running, cancelled or mismatched attempt/lease/start snapshots cannot write. Invalid proposed identity and regressing progress timestamps must be rejected rather than trusted.

The adapter performs one atomic conditional update of only four columns: `metadata_json`, `heartbeat_at`, `lease_expires_at` and `updated_at`. Conditions match the expected job ID, running status, attempt count, lease owner, start time, update time, heartbeat time and lease expiry, and require no cancellation request. Nullable comparisons must work for SQLite and PostgreSQL. Rejected writes preserve the complete current row, including cancellation metadata, terminal status and replacement-attempt state.

After either a successful update or a rejected comparison, return freshly loaded persisted state. A cached ORM identity-map object is not evidence of the current state; use `populate_existing` or equivalent. Transaction commit remains the unit of work's responsibility.

Use small domain identity and timestamp helpers shared by application and adapter. Interpret SQLite naive timestamps as UTC and normalize aware timestamps to UTC. Progress must preserve newer heartbeat, update and lease-expiry times, including when the clock moves backward. The adapter must not import application helpers.

The progress lifecycle checks current state and original attempt ownership, returns cancelled/terminal/replacement state unchanged, and uses the dedicated atomic operation. Generic persistence and intentional cancellation resets are not changed or replaced with blanket coalescing.

Supervision retains a fixed original attempt identity. A completed provider task is accepted only after fresh status, ownership and cancellation checks; refreshed state must not let an old task adopt a replacement lease. Discarded completed task exceptions must be consumed during stale/cancellation cleanup, while active-owner parser exceptions still propagate normally. Keep the existing orchestration file at or below 1,000 lines without compressed statements or readability reductions; a full method extraction is not required if the bounded change fits.

## Deterministic verification

The regression must exercise the original lifecycle function on pre-fix source and demonstrate the actual cancellation loss, rather than fail because the new repository API is absent. Use explicit synchronization barriers around the existing read/write boundary, not timing sleeps.

The focused verification covers:

- Cancellation committed between heartbeat read and write remains committed, including its metadata and timestamp.
- A terminal transition or replacement attempt/lease committed in that interval wins completely; stale progress cannot revive it.
- Ordinary owned progress advances the intended fields; a backward clock does not regress heartbeat, update or expiry times.
- Invalid proposed identity, non-running/cancelled snapshots and regressing timestamps cannot write.
- A strongly retained ORM identity-map row does not make conflict results stale.
- Retry, new attempt and successful completion retain their intentional cancellation reset behavior.
- A stale completed provider error is consumed without a task warning; an active-owner parser error still propagates.
- The real repository cases run against SQLite and an isolated PostgreSQL 18 schema or database, coordinated with the service owner.

Inventory all port implementations, including the two existing in-memory extraction repositories and test wrappers. Adapt them to the explicit contract. Keep the original slow-worker test, its heartbeat assertions and five-second completion assertion unchanged. Run affected unit/adapter tests and the exact original failed node on the repaired integration candidate; retain the original full-suite failure and separate repeat evidence. Do not regenerate frozen fixtures, change architecture inventories or run another full unit suite as part of this bounded repair.

## Two critics, two plan rounds

### Root critic, round 1

Accepted the narrow atomic progress operation and requested explicit conflict/missing-row behavior, immutable attempt identity, fresh same-session state, UTC-safe monotonic timestamps, deterministic real-repository regressions, a held ORM-reference case and actual PostgreSQL 18 proof. Rejected a generic cancellation coalesce because legitimate lifecycle transitions intentionally clear cancellation. Also required the existing 990-line supervisor to stay within the 1,000-line cap.

Response: the final plan specifies the port contract, four-column update, complete expected-state guard, fresh reload, domain-level time/identity helpers, fixed supervision identity and the focused cross-dialect regression matrix. Generic save and reset transitions remain outside the changed boundary.

### Independent architecture critic, round 1

Accepted the direction and required explicit return behavior, NULL-safe guards, complete current-row preservation, deterministic barriers, stable ownership through the provider-completed path, timestamp handling and the file-size cap.

Response: these are explicit implementation and code-review acceptance requirements above. Conflict results must come from persisted state and must not be a cached or reconstructed stale snapshot.

### Root critic, round 2

Approved the revised plan, with code-review requirements that the adapter reject invalid proposed identity and regressing times, update only four columns, return fresh conflict state, and demonstrate pre-fix failure through the original lifecycle. Required completed stale task errors to be consumed without masking active parser errors.

### Independent architecture critic, round 2

Approved the revised plan with no design blocker. Confirmed atomic progress-only persistence, immutable attempt identity, NULL guards, fresh reload, UTC monotonicity, unchanged intentional resets and timeout, deterministic SQLite/PostgreSQL proof and the supervisor line cap. Required focused checks for stale completed errors versus active parser errors.

## Commit and review sequence

This plan and the review responses are committed before production implementation for an early draft pull request. Production and meaningful regression changes follow in a separate commit, then independent code review and focused acceptance evidence. No production edits were made before both critics completed both plan rounds.
