# Asset extraction lifecycle responsibility refactor

Status: implemented after both independent critics completed both review rounds;
coordinator released implementation after publishing the approved plan in PR #94.
Final verification and independent code review are recorded below.

Base: `main` at `44ac164a8395c5847ae8792dded95d0dfe4526dd`.
Owner: direction C / lifecycle services.
Branch: `refactor/lifecycle-services-20261023`.

## Problem and evidence

The selected debt is accumulated orchestration responsibility in
`packages/infinity_context_core/infinity_context_core/application/use_cases/asset_extractions.py`.
The current 1,454-line module contains seven public use cases. The worker use case
also implements independent policies for canonical job mutation, parser task
supervision, compensating artifact persistence, media usage reconciliation, and
resource/output mapping. Changes to one failure domain require reviewing the
others in the same class.

Concrete seams on the base revision:

- Lines 119–438: request/deduplication/quota reservation, lookup/list/download,
  explicit retry, and cancellation use cases.
- Lines 442–814: runner composition, workflow, and supervised parser task.
- Lines 815–949 and 1035–1078, 1150–1240: canonical job reads/transitions,
  lease/progress, cancellation acknowledgment, safe finalization and retry policy.
- Lines 950–1033: artifact candidate preparation, blob writes, metadata transaction,
  and best-effort blob compensation preserving the original exception.
- Lines 1080–1148: idempotent media quota reconciliation.
- Lines 1266–1454: datetime comparison and safe result/artifact policy functions.

The behavior already has meaningful tests, including late-cancel handling,
terminal-state races, active-lease deferral, retry exhaustion, timeout/cancellation,
artifact cleanup, resource/security rejection, quota reconciliation, and real
HTTP/server/worker extraction. The goal is clearer ownership with the same
observable behavior, not new capabilities or speculative infrastructure.

Other inspected candidates are deliberately excluded. `anchors.py` combines
identity and lifecycle policies but its behavior overlaps context selection;
`postgres/unit_of_work.py` mixes compatibility schema upgrade code with UoW setup,
but changing that area would cross the explicit schema/engine exclusion;
the Python SDK already has feature-specific modules. Asset extraction is the
strongest coherent and independently testable boundary for this direction.

## Architecture and precise scope

Keep all seven public class definitions, constructor signatures and `execute`
methods reachable through their existing module and application package imports.
In particular, retain the class definitions in `asset_extractions.py`; the
canonicalization inventory records those owner paths. No compatibility subclass,
dynamic import forwarding, wildcard exports, or `__module__` reassignment.

Retain the runner's ordered `execute` workflow and parser supervision in that
module. Extract internal collaborators beside it by actual responsibility:

| Module | Responsibility | Expected size |
| --- | --- | ---: |
| `asset_extractions.py` | Existing public use cases; worker workflow and supervision; thin existing private-method seams | 800–950 lines, hard maximum 1000 |
| `asset_extraction_lifecycle.py` | Concrete canonical job transition operations: claim, heartbeat, cancellation, post-document cancellation acknowledgment, metadata updates, success, unsupported and failed states | 300–400 lines |
| `asset_extraction_artifacts.py` | Artifact candidate assembly/bounding, deterministic storage identity, blob persistence, metadata transaction, compensation | 190–260 lines |
| `asset_extraction_usage.py` | Actual-versus-reserved media usage reconciliation and its idempotency/metadata transaction | 90–130 lines |
| `asset_extraction_result_policy.py` | Pure resource/upload rejection result mapping, detection metadata and output truncation | 120–180 lines |

The existing `asset_extraction_support.py` remains the owner of retry policy,
safe error mapping, usage keys, event creation, and media-duration calculations.
Place the small mixed-timezone datetime comparator in that support module if
both runner and lifecycle need it; do not duplicate it or create a generic
cross-feature utility layer. Artifact-specific bounds/summaries stay with the
artifact writer, not with general result policy.

Use named async operations with explicit keyword dependencies, not collaborator
classes. Their lifetime is one invocation; they hold no state between calls.
Lifecycle operations accept `uow_factory`, `clock` where needed, the job/command,
and only the relevant current lease, limits metadata or retry policy. The artifact
operation accepts `uow_factory`, `blob_storage`, `clock`, `ids`, `limits`,
`artifact_storage_backend`, asset/job/result and markdown. The usage operation
accepts `uow_factory`, `clock`, `ids`, job and result. Result-policy helpers remain
pure functions. No operation receives/stores the runner, an `Any` runner-shaped
context, an aggregate dependency bag, callbacks into arbitrary runner behavior,
or a closure capturing mutable runner configuration. Do not add new domain ports,
public DTOs, inheritance mixins, a generic transition callback framework, or a
reusable workflow engine. All dependencies remain core domain/application/ports
plus the standard library.

Retain runner methods `_mark_running`, `_save_progress`, `_get_current_job`,
`_cancel_if_requested`, `_acknowledge_cancel_after_document_commit`,
`_store_artifacts`, `_mark_succeeded`, `_reconcile_media_usage`,
`_update_job_metadata`, `_mark_unsupported`, and `_mark_failed` as thin delegating
instance methods. Preserve `_mark_failed_unless_terminal` calling
`self._mark_failed` so overrides remain effective. Keep supervision calling the
existing instance methods, including `_cancel_supervised_task`.

Read live runner fields when an operation is invoked. A collaborator must not
cache copies of mutable runner configuration or injected dependencies at
construction. Each retained method forwards its current `self` fields as explicit
keyword arguments at invocation time. Existing tests replace `_extractor`, `_limits`, `_retry_policy`,
`_ingest_document`, `_blob_storage`, and `_store_artifacts` after construction.
An override or replacement must still be observed by the same workflow stage.
No collaborator retains a UoW/session across calls.

The request, query, retry and explicit cancellation implementations remain in
place. This avoids broadening the scope into deduplication or admission-policy
redesign while separating the worker's distinct failure domains.

## Invariants: behavior must remain unchanged

1. **Public compatibility:** all seven original use cases, constructors, commands,
   result shapes, import paths, and container wiring work unchanged. Existing
   subclass/instance overrides at the retained runner methods remain effective.
2. **Transaction boundaries:** preserve the exact relative order of reads, saves,
   commits, outbox enqueues, parser calls, blob writes and document ingestion.
   Do not merge transactions or wrap the parser/blob/ingestion stages in a UoW.
3. **Canonical authority:** every transition re-reads the current canonical job as
   today. Preserve terminal state checks and current non-running success
   finalization diagnostics. Derived indexes remain outbox-driven after document
   ingestion; no direct projection calls or changes to canonical visibility.
4. **Lease and retry:** preserve force handling, active/expired/missing lease
   behavior, retry-after deferral, attempt limits, permanent classification, exact
   safe codes/messages, and outbox rescheduling without attempt burn.
5. **Cancellation and supervision:** cancel parser tasks on timeout, cancellation
   or externally changed job state. Preserve heartbeat timing and progress. Honor
   cancellation before document commit; record and ignore a late cancellation as
   today so already committed evidence is finalized consistently. Do not claim
   stronger atomicity or race guarantees than the existing implementation.
6. **Artifact compensation:** preserve candidate order, content, bounds, metadata,
   digest/storage keys, generated ID order, and all artifact metadata in one
   transaction. On failure attempt deletion of all successfully written blobs;
   cleanup errors must never replace the original failure.
7. **Usage:** preserve request reservation and reconciliation keys, delta arithmetic,
   source identity, current window selection, no-op cases, and the joint adjustment
   plus metadata commit. No accounting/window correctness redesign in this PR.
8. **Safety:** preserve upload revalidation before detector/parser use, archive and
   result limits, safe/truncated diagnostics, text/artifact bounds and provenance.
   Retrieved text remains evidence. No raw provider errors or storage identities
   gain new public exposure.
9. **Optional providers:** no new imports of adapters or parser/provider packages in
   core; import and text extraction work without external AI/OCR/media tools.
   Existing disabled/missing-provider fallback behavior remains covered.

## Implementation sequence after the review gate

1. Run focused baseline tests and record results before production edits. Check
   optional media tool availability and distinguish required tests from skips.
2. Extract pure result policy and artifact persistence with unchanged expressions
   and control flow. Keep the runner's `_store_artifacts` method as the seam and
   pass live storage/limits/ID/clock/UoW dependencies. Add the bounded blob-write
   compensation regression below against the unchanged implementation before
   moving the persistence operation.
3. Extract media reconciliation and concrete lifecycle operations. Keep existing
   runner private seams and terminal-exception routing. Dependency/configuration
   values are passed explicitly per invocation; there is no collaborator object.
4. Remove now-unused imports, inspect the control-flow diff for changed ordering,
   and remove only this module's legacy size-baseline entry once it is <=1000.
   Ratchet the entry only if an intermediate commit remains oversized. As agreed
   across all three branches, delete the brittle `assert len(baseline) == 107`
   assertion in `tests/architecture/test_file_size_boundaries.py`; preserve actual
   filesystem checks, monotonic fixture checks and the CI `--base-ref` gate. Each
   branch makes this identical deletion, which is safe to merge across branches.
5. Complete the side-by-side operation-order audit below. Run focused tests,
   architecture/lint gates, the provider-free E2E, and adjacent
   contract coverage. Add a small regression only where an extraction introduces
   a concrete uncovered compatibility risk; do not mirror internal forwarding
   implementation or rewrite existing fixtures. One identified missing regression
   is required: `tests/unit/test_asset_extraction_blob_write_compensation.py`
   (new, <=200 lines) makes the second artifact blob write fail and its cleanup
   deletion fail. Assert only successful writes are considered for cleanup, no
   metadata UoW begins, and the original write exception survives. Record write/
   delete/UoW events to verify this failure boundary without testing delegation.

### Required side-by-side operation-order audit

Record the new operation locations next to these pinned-base sequences in the
implementation review notes. Bodies move without changing await/UoW boundaries;
existing outcome tests supplement this control-flow audit rather than being
claimed as proof of every transaction ordering detail.

| Scenario | Pinned-base operation sequence to preserve |
| --- | --- |
| Successful worker extraction | Claim job read/save/commit (`_mark_running`); asset read; source/resource/upload checks; upload metadata save/commit; detecting progress heartbeat save/commit; cancellation read/check; detector call; detection metadata save/commit; archive assessment metadata save/commit; extracting progress save/commit; cancellation read/check; supervised parser with canonical polls/heartbeats; post-parser cancellation read/check; result checks/text bounding; `ingest_document.execute` canonical document/chunk/outbox commit; storing progress save/commit; late-cancel acknowledgment read and conditional metadata commit; all artifact blob writes; all artifact metadata creates in one UoW and commit; late-cancel acknowledgment read and conditional metadata commit; indexing progress save/commit; optional usage delta plus job metadata in one UoW/commit; success current-job read/save/commit. |
| Artifact metadata persistence fails | All successful blob writes complete; artifact metadata UoW opens; metadata create fails with no commit; attempt deletion for each successfully written key in insertion order, suppressing cleanup failures; rethrow original metadata error; runner re-reads canonical job, preserves terminal state or calls retained `self._mark_failed` with its own fresh read/save/commit. |
| Second artifact blob write fails | First blob succeeds and its key is recorded; second write raises before recording that key; no artifact metadata UoW opens; attempt cleanup only for the first key; cleanup errors are suppressed and the original second-write error propagates. |
| Cancellation arrives after document commit | Explicit cancellation saves request on running job; retained late-cancel acknowledgment re-reads and conditionally commits ignored-after-document-commit diagnostics; artifacts and metadata continue in the success order above; second late-cancel acknowledgment preserves the same diagnostics; usage and success finalization proceed, with finalization's existing non-running-state guard unchanged. |

Do not fold these steps into a single transaction, move acknowledgment before
document ingestion, or change the existing request/retry outbox transactions.

## Validation commands and acceptance

Use the shared frozen Python environment, with the lifecycle worktree as cwd.
The illustrative commands use `$PYTHON` set to the shared environment interpreter.

```bash
$PYTHON -m pytest -q \
  tests/unit/test_asset_extractions_api.py \
  tests/unit/test_asset_extraction_lifecycle_races.py \
  tests/unit/test_asset_extraction_artifact_cleanup.py \
  tests/unit/test_asset_extraction_blob_write_compensation.py \
  tests/unit/test_asset_extraction_resource_limits.py \
  tests/unit/test_asset_extraction_retry_policy.py \
  tests/unit/test_asset_extraction_domain.py \
  tests/unit/test_extraction_artifact_public_contract.py

$PYTHON -m pytest -q \
  tests/unit/test_asset_extraction_transcription_api.py \
  tests/unit/test_asset_extraction_media_contracts.py \
  tests/unit/test_context_linked_extraction_artifact_api.py

$PYTHON -m pytest -q tests/unit/test_worker_eval.py \
  -k 'asset_extraction or extraction_worker'

$PYTHON -m pytest -q tests/architecture
$PYTHON -m pytest -q tests/e2e/test_asset_extractions_e2e.py
FILE_SIZE_BASE_REF=origin/main make infinity-context-lint \
  PYTHON="$PYTHON" RUFF=/workspace/scratch/b6182bae50e9/infinity-context/.venv/bin/ruff
```

The mandatory E2E starts a real local HTTP server, uploads a text asset, launches
the actual worker CLI, reads the resulting canonical document/chunks, lists jobs,
and downloads the persisted markdown artifact. It is provider-free and requires
no PostgreSQL/vector/graph service. This is sufficient process-level evidence for
a core-only move that does not change SQL or persistence adapters; do not present
it as PostgreSQL concurrency validation. Media/transcription tests exercise local
fallback and fake-provider contracts; report ffmpeg/ffprobe/OCR-dependent skips
accurately. A paid/cloud parser or real provider canary is not required for this
behavior-preserving internal refactor.

Acceptance requires all mandatory focused tests and the text HTTP/worker E2E to
pass, no new architecture/lint failures, the original module <=1000 lines, and
every new module <=1000 lines. Prefer the table's lower target sizes without
splitting an operation merely to meet an arbitrary target. Remove the original
module's oversized baseline entry and do not add or increase any other entry.
The review must verify the invariants above, especially live dependency mutation,
late cancellation, terminal finalization, original-error preservation and commit
order. Record exact commands, counts and skips in the final PR description.

## Boundaries, coordination and risk

Production changes are confined to the extraction use-case module, the four new
internal extraction modules, and the existing extraction support module if needed.
Allowed supporting changes are this plan, the single size-baseline entry removal,
the shared brittle baseline-count assertion deletion, the named bounded blob-write
regression, and a small focused compatibility regression only if another concrete
uncovered risk is identified. No schema/migrations,
engine/session construction, SQL repositories, server composition, SDK, frontend,
API schemas, ADRs, feature-owned vertical slice migration, benchmark code, eval
logic, context ranking/packing or collectors/query execution/vector candidates.
Concurrent PR #91 and directions A/B own those other areas.

Estimated production diff: 600–850 existing lines relocated, approximately
100–180 lines of explicit imports/dependency passing/delegation, no intended net
behavior change. The main risk is stale captured dependencies or bypassing an
existing instance-method override; the retained seams and current replacement
tests directly address it. The second risk is accidentally changing commit/cleanup
ordering while moving code; review the old and new bodies side by side and run
the existing failure/late-cancel/race tests. Unknown adjacent debt is documented
for follow-up rather than absorbed into this PR.

## Review record

- Round 1 critic A (core): explicit dependency ownership and operation-order audit
  requested. Resolved by named per-call operations, no runner/dependency bag,
  retained self-method dispatch, and the mandatory side-by-side audit above.
- Round 1 critic B (server): freeze operation interface/lifetime and cover second
  blob-write plus cleanup failure. Resolved by the same explicit operation
  boundary and the named <=200-line semantic compensation regression.
- Round 1 owner fixes: incorporated; no production edits.
- Round 2 same critic A (core): approved at revised commit `c7d4c4ac`; explicit
  per-call dependency boundary and operation ledger resolve round-one findings.
  Record: `plans/review-r2-lifecycle-by-core.md`.
- Round 2 same critic B (server): approved at revised commit `c7d4c4ac`; named
  operations, compensation regression and ledger resolve round-one findings.
  Record: `plans/review-r2-lifecycle-by-server.md`.
- Round 2 owner fixes: none requested. Coordinator released implementation after
  publishing the exact approved plan tree in PR #94 (remote `86f4e038`).

## Implementation and operation-order evidence

Unchanged baseline: the complete listed extraction/API/media/transcription/artifact
suite plus real HTTP/worker E2E passed **89 tests in 88.09s**, no skips, one existing
Starlette/httpx deprecation warning. The new second-write compensation regression
then passed against unchanged production code before extraction (**1 test in
1.87s**, commit `e4d16c66`). The initial sandbox collection problem came from a
virtual PID mismatch with `/proc`; approved normal-process test execution resolved
it without any production/runtime/supervisor change.

Production extraction is commit `92f40fa3`. Actual sizes are 990 lines for the
original public use-case module (was 1454), 334 for lifecycle, 195 for artifacts,
122 for result policy and 96 for usage. Support grows by the existing eight-line
datetime comparator; no logic is duplicated. The production diff adds 289 net
lines for explicit imports, typed per-operation dependencies and retained seam
delegation. This is above the estimate, chiefly because live dependency seams
are preserved explicitly rather than captured in a runner context.

A source AST comparison against pinned base `44ac164a` verified all seven class
paths and all original method signatures. The six other use-case definitions,
runner constructor, ordered `execute`, parser supervision, task cancellation and
`_mark_failed_unless_terminal` are identical. Each of the eleven extracted method
bodies is identical after replacing its specific `self._dependency` attributes
with explicit operation parameter names. All twelve original pure helpers match,
with only `_datetime_after` renamed in its shared owner and imported under its
original runner name. Original helper import paths remain explicitly available.

| Reviewed sequence | New operation locations and audit result |
| --- | --- |
| Success | Original `RunAssetExtractionUseCase.execute` is AST-identical. Claim/heartbeat/metadata/success bodies now live in `asset_extraction_lifecycle.py`; parser supervision remains original; artifact and usage calls retain their original instance-method dispatch and position. No await, commit, outbox, parser, ingestion or blob operation was reordered. |
| Artifact metadata persistence failure | `asset_extraction_artifacts.store_artifacts` is the unchanged original body with explicit dependency names: blob writes precede one metadata UoW/commit; exception cleanup iterates successful keys and suppresses deletion failures before rethrowing the original error. Existing cleanup tests cover metadata failures. |
| Second blob write failure | The same body records a key only after its write succeeds. New semantic regression records `write`, `write`, `delete`; no UoW opens; cleanup targets only the first successful key and the exact original write exception survives the failed deletion. |
| Cancellation after document commit | Original runner workflow, both acknowledgment call sites and exception routing are unchanged. `asset_extraction_lifecycle.acknowledge_cancel_after_document_commit` and `mark_succeeded` retain the original current-state reads, conditional commits and non-running finalization diagnostics. Existing late-cancel and terminal-race tests exercise this path. |

Verification completed so far: **30 pure extraction tests passed in 2.95s**;
**3 worker tests passed in 12.69s** (48 unrelated cases deselected); repository
Ruff and the monotonic file-size gate against the pinned base passed with 106
remaining legacy ceilings. The only removed baseline entry is the owned original
module; the shared brittle count assertion is deleted as reviewed.

Final verification: the complete extraction/API/media/transcription/artifact suite
plus real HTTP/worker E2E passed **90 tests in 90.90s**, no skips, the same existing
Starlette/httpx deprecation warning. Full architecture suite passed **216 tests
in 89.87s**. All reviewed mandatory commands have passed.
Independent code reviews by the same core and server owners: requested.
