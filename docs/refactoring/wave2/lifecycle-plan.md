# Wave 2 canonical persistence separation plan

Status: draft for two independent critics, two rounds, owner fixes between rounds. Production work is blocked until coordinator explicitly releases this plan after both rounds. Plan owner: lifecycle/persistence. Base `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`. Audit: `lifecycle-audit.md`.

## Outcome and bounded scope

Deliver two separately reviewable PR slices that remove mixed schema/runtime and multi-capability repository ownership without changing canonical behavior. This is adapter-local partitioning by responsibility; it does not migrate unfinished feature placeholder stores or alter legacy feature ports. No domain, application, contracts, API routes, accepted ADR, SQL migration, outbox protocol, provider or transport changes. Existing `asset_extraction_*` boundaries remain intact.

Dependency DAG: pinned main → L1 schema/UoW separation → L2 repository capability separation. The semantic changes are independent, but L2 deliberately follows L1 because both touch UoW imports; serializing that file gives an unambiguous review and publication base. Coordinator owns PR publication, exact branch cutting, merging and shared debt-gate reconciliation. Owner supplies commits and validation evidence promptly after release.

## L1 — isolate schema compatibility from UoW transaction ownership

Production ownership is confined to the following adapter files:

| File | Exact responsibility | Anticipated size |
| --- | --- | --- |
| `postgres/unit_of_work.py` | Existing engine/session builders, UoW/factory, exact integrity mapping and source-ref coordination; explicit compatibility aliases for relocated schema names | 260–340 LOC, down from 996 |
| `postgres/schema_compatibility.py` (new) | Existing additive-column constants; legacy profile/scope conversion; additive-column upgrade; document thread uniqueness upgrade and SQLite legacy table reconstruction; common `_column_names` introspection helper | 480–540 LOC |
| `postgres/schema_runtime.py` (new) | Existing `create_schema`, one ordered `_ensure_runtime_schema` bootstrap, temporal backfill/index helpers and outbox/capture/suggestion index installers; unchanged benchmark installer invocation | 310–370 LOC |

Move complete functions/constants, retaining original signatures and bodies. Helpers have one definition and explicit imports/reexports. No generic migration runner/strategy, new registry, wrapper context, closure factory or schema DSL. The schema runtime module imports compatibility helpers and the existing authoritative metadata/singleton/benchmark/trigram installers; it never imports UoW or repository implementations. UoW imports its actual runtime/compatibility aliases. Keep the lazy package export resolution unchanged. `create_schema` still imports `upgrade_schema` only inside its PostgreSQL branch.

Compatibility guarantees: existing imports from `postgres` and `postgres.unit_of_work` continue to resolve; all existing schema helper/constant names that were defined in UoW are explicitly available as aliases. In particular `_ensure_runtime_schema` object identity equals the callback used by relocated `create_schema`, and benchmark helper/error test imports remain valid. No star imports or dynamic forwarding. No class, constructor, builder or transaction signature changes. Public classes remain identical; function `__module__` naturally reflects its implementation owner, and private module-global monkeypatch behavior is not expanded into a new API promise. Supported namespace inventory includes the package's advertised exports, the module's defined classes/functions/constants, genuinely consumed imported benchmark helper/error aliases, and the explicit schema aliases. Incidental imported stdlib/SQLAlchemy implementation names do not become a new public API contract.

### Frozen operation ledger

1. `create_schema`: PostgreSQL → existing `upgrade_schema` → return; other dialect → one `engine.begin` context → `run_sync(_ensure_runtime_schema)`.
2. Runtime callback exact order: legacy profile compatibility; full model registry `create_all`; singleton seed; benchmark manifest compatibility; additive columns; temporal backfill; temporal indexes; code-scope index; supersession index; document thread indexes; outbox lifecycle indexes; capture indexes; suggestion metadata indexes; trigram access path; benchmark writer fence installer.
3. Suggestion helper still expires duplicate pending suggestions before either unique index; its nested outbox fairness index remains at the current position.
4. UoW `__aenter__`, `__aexit__`, `commit`, `rollback`, `coordinate_fact_source_refs` and factory construction remain source/AST-equivalent. Error strings, original exception causes, rollback/close/reset order, captured per-entry clock value and optional reviewed fact executor lifetime do not change.

### Characterization and executable gates

After plan release and before source relocation, run exactly the focused existing schema/error suite below against unchanged production. Record counts/skips. Add a bounded `tests/canonical_persistence_relocation_audit.py` executable audit helper (<=400 LOC) and capture versioned `tests/fixtures/canonical_persistence_refactor/l1_contract.json` from unchanged production, with pinned base SHA and the explicit source-definition→final-owner manifest. Before moving production code, record each moved function's externally loaded globals and expected final owner, dependency defining module/qualified name, supported namespace/signatures/defaults/docstrings and evaluated annotations. Include `JSON`, `bindparam`, `inspect`, `text`, metadata/seed/manifest/fence/trigram installers, and moved helper/constants. Store old class-reference pickles for unchanged UoW/factory and representative relocated top-level functions, without serializing any sessions. After relocation run the same suite; compare every moved function/constant AST to pinned base and verify all retained UoW/factory methods are unchanged. Compare actual live dependency bindings to their original canonical imports, allowing only explicitly moved helper aliases; constants have one definition and compatibility aliases point to that same object. Verify evaluated annotations still resolve to the same domain/SQLAlchemy objects and old reference pickles decode to the exact canonical alias objects. The AST/global comparison is a small audit artifact, not a new test that merely mirrors implementation. Fresh interpreter imports of old package, old module and new owners in both orders verify alias identities and cycle safety; repeat schema creation is already behaviorally covered by singleton and schema upgrade tests.

The audit runs the actual `_ensure_runtime_schema` callback with its installer globals replaced only inside the test process by recording operations; the fake metadata's real `create_all` position is recorded too. Freeze the complete fifteen-operation trace from unchanged production, then require the exact trace after relocation. Do not snapshot every SQL statement. Assert `create_schema.__globals__["_ensure_runtime_schema"] is unit_of_work._ensure_runtime_schema`, rather than comparing two potentially stale imported aliases. Explicitly reject imports from schema owners back to UoW/repository implementations. The helper supports `capture/check --slice l1` modes and expected files are not regenerated after production changes.

```bash
PYTHON=/workspace/scratch/b6182bae50e9/infinity-context/.venv/bin/python
$PYTHON -m pytest -q \
  tests/unit/test_schema_migrations.py \
  tests/unit/test_legacy_profile_schema_migrations.py \
  tests/unit/test_document_uniqueness_schema_migrations.py \
  tests/unit/test_benchmark_schema_upgrade.py \
  tests/unit/test_sqlite_schema_singletons.py \
  tests/unit/test_benchmark_writer_fence.py \
  tests/unit/test_postgres_benchmark_run_repository.py
$PYTHON tests/canonical_persistence_relocation_audit.py check --slice l1
```

Then mandatory lint/file-size and architecture gates listed below. Run one real provider-free HTTP/worker E2E (`test_asset_extractions_e2e.py`) to demonstrate cold composition/schema creation and worker persistence. API/process tests require approved real-process execution under the existing sandbox escalation; attestation code remains unchanged. Root is provisioning an isolated official PostgreSQL 18.6 runtime; once its DSN is supplied, the two exact real-PG gates below are mandatory and a missing-DSN skip does not satisfy acceptance. They exercise clean/unversioned legacy forward upgrades plus the canonical writer/cleanup lock and exact conflict identity. Preserve actual results separately from SQLite callback evidence.

```bash
$PYTHON -m pytest -q \
  tests/e2e/test_postgres_schema_upgrade_e2e.py \
  tests/unit/test_benchmark_writer_fence.py::test_real_postgres_writer_share_lock_serializes_cleanup_when_configured
```

Anticipated production diff: 720–780 existing lines moved, 70–130 import/reexport/docstring lines added; no intentional logic change. No legacy size-baseline change: the original is already below the hard cap. Supporting changes: bounded executable audit helper and pre-source contract fixture named above, plus a PR implementation/validation record under `docs/refactoring/`; no changes to shared gates.

## L2 — give canonical repository capabilities explicit owners

Production ownership is confined to `postgres/repositories.py`, existing `postgres/unit_of_work.py` import statements only, and these new modules:

| File | Exact moved definitions | Anticipated size |
| --- | --- | --- |
| `postgres/document_repositories.py` | `_keyword_search_statement`, `PostgresDocumentRepository`, `PostgresChunkRepository`, only their existing imports | 530–600 LOC |
| `postgres/anchor_repositories.py` | `PostgresAnchorRepository`, only its existing imports | 115–150 LOC |
| `postgres/episode_repositories.py` | `PostgresEpisodeRepository`, only its existing imports | 65–90 LOC |
| `postgres/capture_repositories.py` | `PostgresCaptureRepository`, only its existing imports | 135–165 LOC |
| `postgres/suggestion_repositories.py` | `PostgresSuggestionRepository`, only its existing imports | 180–215 LOC |
| `postgres/repositories.py` | Explicit compatibility aliases for all six repository classes, `_keyword_search_statement`, existing outbox/idempotency reexports | 35–65 LOC, down from 988 |

Documents and chunks remain together because parent/evidence locking, visibility and deletion are one canonical persistence capability. Episode/capture/suggestion/anchor classes do not gain artificial shared superclass or helper framework. Existing batch/keyword/scoped-lock helpers retain ownership. UoW imports each actual capability owner directly; downstream legacy imports continue to work through exact class aliases. No placeholder feature store is wired, advertised or changed.

Compatibility guarantees: identical class objects are exported from legacy and new owners; every method and signature is copied intact. Repository class/function `__module__` acquires its new implementation owner; aliases preserve old import/attribute resolution, original `__name__`/`__qualname__`, signatures/defaults/docstrings and evaluated method annotations. New class/function reference pickles use their canonical owner; pre-change reference pickles still decode through old aliases to those exact canonical objects. No live session/repository-instance pickle contract is introduced. Module-defined private keyword helper and historical outbox/idempotency class reexports are supported; incidental imported mapper/ORM/stdlib names are implementation details. The original `_keyword_search_statement` import remains valid as an alias to the document owner. SQL text and expressions, row ordering/limits, exact/global thread fallback, scoped predicates, chunk retrieval version increments, document/chunk locks, flush/rollback/optimistic-update behavior, ORM mapping and caller-owned session lifetime remain unchanged. No repository performs its own commit; outbox/idempotency implementation remains in `record_repositories.py` unchanged.

### Frozen lifecycle ledger

| Path | Exact behavior to retain |
| --- | --- |
| Document create | Optional exact-thread fence, add mapped row, flush, integrity failure rollback then typed canonical conflict with original cause |
| Chunk upsert | Optional exact-thread fence, parent lock, existing scoped source-hash lookup, duplicate return or row add; no commit |
| Document delete | Existing evidence/parent lock helper, ordered locked chunk snapshots, capture old canonical versions, mark deleted and increment each chunk version, conditional document status update; caller commits |
| Anchor create/save | Create flush and rollback-on-integrity behavior; save fetch, missing-row conflict, mapping and flush unchanged |
| Capture create/save | Existing idempotency and optimistic-update/flush semantics unchanged |
| Episode and suggestion | Existing scope/status/replay/order/limit semantics unchanged; replay recovery still owns fresh UoW in the application |

### Characterization and executable gates

After L1 is complete and L2 is released, before source moves run the focused existing suite below. Extend the same bounded audit helper's `capture/check --slice l2` modes; capture `tests/fixtures/canonical_persistence_refactor/l2_contract.json` from unchanged L2 production with the exact approved branch base SHA. Record every moved function/method's externally loaded globals, source-definition→final-owner map, callable/class dependency defining module/qualified name, supported namespace/signatures/defaults/docstrings and evaluated annotations. Freeze old reference pickles for all six repository classes and `_keyword_search_statement`. After relocation rerun the suite and compare all six class ASTs plus `_keyword_search_statement` with pinned base; require no changed body, signature, SQL expression or helper call. Audit actual live binding identities/provenance for SQLAlchemy constructors/models, ORM classes, mappers, source-ref/parent/evidence locking and canonical batching helpers, allowing only the explicit relocated keyword/helper aliases. Verify evaluated method annotations resolve to the original domain/port/AsyncSession objects and old reference pickles decode to the canonical objects. Verify old/new alias identities in fresh processes, both old-first/new-first imports, and that every constructed repository receives the same UoW session, with a single per-entry `now` capture. Explicitly audit no new capability owner imports the legacy `repositories` facade. Existing shared-session/failure tests supply behavioral evidence; add a new bounded regression only if a concrete uncovered risk is identified and prove it against unchanged source first.

```bash
$PYTHON -m pytest -q \
  tests/adapters/test_postgres_canonical_retrieval_batching.py \
  tests/adapters/test_postgres_canonical_keyword_trigram.py \
  tests/unit/test_document_fragment_api_integration.py \
  tests/unit/test_ingest_document_identity_compatibility.py \
  tests/unit/test_ingest_episode_sqlalchemy_recovery.py \
  tests/unit/test_episode_ingestion_replay_contract.py \
  tests/unit/test_anchor_lifecycle_api.py \
  tests/unit/test_capture_api.py \
  tests/unit/test_suggestions_api.py \
  tests/unit/test_suggestion_review_atomicity.py \
  tests/unit/test_suggestion_validation_contract.py
$PYTHON tests/canonical_persistence_relocation_audit.py check --slice l2
```

Run provider-free `tests/e2e/test_asset_extractions_e2e.py` after L2 to verify actual HTTP upload, canonical document/chunk persistence, worker CLI and artifact download through new repository owners; the already-frozen full eval baseline is reused because prompt/ranking policies are untouched. With the root-provisioned isolated PostgreSQL DSN, the following four concrete tests are mandatory: repository/CodeScope full flow; suggestion ambiguous-commit/concurrent replay; ordinary/projected document identity; managed document identity/strict-v4 receipts. Missing-DSN skips do not satisfy acceptance. Do not rerun unrelated paid/live canaries or expand benchmark policy coverage.

```bash
$PYTHON -m pytest -q \
  tests/e2e/test_postgres_repository_scope_e2e.py \
  tests/e2e/test_postgres_suggestion_replay_e2e.py \
  tests/e2e/test_document_content_identity_postgres.py
```

Anticipated production diff: about 900 original lines moved, 100–170 focused imports/reexports/docstrings added. Each new file <=1000 LOC. No file-size baseline changes. Supporting changes: extend the single audit helper within its <=400 LOC budget, pre-source contract fixture, and bounded implementation/validation record under `docs/refactoring/`.

## Shared acceptance, critic process and implementation review

Two independently authored plan critiques in round 1 → owner fixes → same two independent critiques in round 2 → coordinator release. Until release, no source edits, characterization runs, commits or publication. Both slices receive independent code review after implementation; fix findings and rerun only the gates they affect. Coordinator owns branch/PR integration and final independent review/merge.

```bash
$PYTHON -m pytest -q tests/architecture
FILE_SIZE_BASE_REF=b0b87bd774f93c2bca9bec14c0efc072a2ba2de8 \
  make infinity-context-lint PYTHON="$PYTHON" \
  RUFF=/workspace/scratch/b6182bae50e9/infinity-context/.venv/bin/ruff
git diff --check
```

For L2 use its exact approved branch base for the monotonic gate. No baseline weakening or inventory increase. If a static gate counts compatibility imports differently after an alias move, report the exact semantic reason to coordinator; do not self-edit shared inventories or suppress checks.

Excluded paths: all context ranking/packing/collectors/query-execution/vector-candidate modules/tests, all benchmark policy/evidence modules, API/SDK/transport/frontend, schemas/migrations, runtime attestation, existing feature placeholders and the complete extraction use-case family. Exact PR #91 path list from coordinator further restricts this already-disjoint scope.

Review must focus on import cycles, helper identity, schema callback order and private compatibility imports for L1; exact SQL/lock/mapping/session/error behavior and complete facade exports for L2. Unknown adjacent debt stays deferred. No acceptance claim may confuse local SQLite HTTP/worker validation with PostgreSQL concurrency proof.

## Plan review and owner fixes

- Round 1 core critic (`review-r1-lifecycle-by-core.md`), L-C1: fixed by mandatory pre-source free-global/owner and supported-namespace inventory, post-move actual binding identity/provenance, evaluated annotation comparison and explicit repository `__module__` scope. The small audit covers schema installers/introspection/SQL constants plus repository SQLAlchemy/ORM/mappers/locks/batching. Also incorporated the nonblocking local reverse-import audit; no runtime indirection or new test framework introduced.
- Round 1 runtime critic (`review-r1-lifecycle-by-runtime.md`), L-C1: fixed by naming the bounded executable audit/contract manifests, exact free-global binding and final-owner checks, full fifteen-operation trace through the actual schema callback, direct callback-global identity assertion and source-definition uniqueness/reverse-import audit. L-C2: fixed by explicit canonical module/name/qualname/signature/default/docstring/hint/reference-pickle policy, old/new import orders and pre-source class/function reference samples. Incorporated the advisory direct benchmark repository test; actual live sessions are never pickled.
- Coordinator requested stronger canonical evidence after provisioning an isolated official PostgreSQL runtime: L1 clean/legacy schema plus writer-fence gates and all four named L2 Postgres tests are now mandatory with that DSN. No process guards or SQL policy changes.
- Round 2 core critic (`review-r2-lifecycle-by-core.md`): L1 and L2 separately approved, no unresolved blocker.
- Round 2 runtime critic (`review-r2-lifecycle-by-runtime.md`): L1 and L2 separately approved, no unresolved blocker.
- Coordinator implementation release: pending. Do not infer source authorization from critic approval alone.

## L1 implementation evidence

Coordinator released L1 after both independent critics' round-2 approvals. L2 remains a separate
future branch/PR. Before changing production source, the bounded executable audit captured all
31 original definitions/constants with explicit final owners, function/method global bindings,
signatures/evaluated hints/docstrings, legacy class/function reference pickles, the complete
15-step actual schema callback trace and the one-session/one-clock UoW contract. The capture
checks that production source is byte-identical to pinned `b0b87bd7` and refuses fixture overwrite.

The approved focused schema/error/repository suite passed against unchanged production:
**39 passed, 1 skipped in 8.55s**. The skip is the PostgreSQL fence case without a DSN in this
focused invocation; coordinator separately proved all six targeted real-Postgres baseline cases
on the isolated PostgreSQL 18.6 runtime. Post-change real-PG evidence remains mandatory and will
run when coordinator releases that shared runtime after the broader baseline E2E.
