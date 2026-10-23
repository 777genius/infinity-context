# Core context policy decomposition plan

Status: both independent plan-review rounds completed and coordinator released implementation after plan PR publication. Implementation and mandatory validation are complete; final independent code-review evidence is recorded below.

## Outcome and evidence

Reduce two overgrown core application modules to reviewable policy modules while preserving every ranking and packing result. This addresses a concentrated maintainability failure in a prompt-impacting path without changing the retrieval engine, scoring policy, canonical lifecycle, or deployment.

Read first: `AGENTS.md`, `docs/infinity-context-core-lite-plan.md`, `docs/architecture-and-trust-model.md`, the architecture plan, both source modules, their import consumers, and their existing focused tests.

At base `44ac164a8395c5847ae8792dded95d0dfe4526dd`:

- `context_domain_rerank_signals.py` has 2,391 lines, including approximately 923 lines of regex/reason declarations, 25 signal functions, the legacy frozen signal DTO, and unrelated candidate/evidence helpers. Its DTO is imported by independently owned signal modules, and `context_domain_rerank_apply.py` owns signal application order. Audit also found a DISTINCT `DomainRerankSignal` in existing `context_domain_rerank_types.py`, used by `context_identity_rerank.py`, `context_commonality_rerank.py` and `context_preference_goal_rerank.py`. The two classes currently have the same fields but different identity/equality families; preserve both and do not unify them here.
- `context_packer_answer_support.py` has 3,101 lines. It combines diversity candidate selection, source grouping and limits, family classification, exact evidence predicates, query ordering, and content quality rankers. Private helpers are imported by the packer and numerous dedicated prepasses; those imports are compatibility contracts even though names begin with underscores.
- The 3,681-line `context_ranking.py` also needs decomposition, but existing tests monkeypatch its `query_terms`, `text_variant_profile`, and `best_query_relevance` globals and inspect its expansion-term cache. Moving its internals concurrently would increase compatibility risk. It is an explicit follow-up, outside this PR.
- Existing answer-support pattern and slot modules already exceed the cap (1,267 and 1,209 lines). This PR does not grow or repartition those modules. New code files must be at most 1,000 lines; the two selected old modules must fall below that cap.

## Ownership and exclusions

Existing production files owned:

1. `packages/infinity_context_core/infinity_context_core/application/context_domain_rerank_signals.py`
2. `packages/infinity_context_core/infinity_context_core/application/context_packer_answer_support.py`
3. `packages/infinity_context_core/infinity_context_core/application/context_packer_answer_support_utils.py`, only to house shared, dependency-free item query/source/marker helpers needed to keep the decomposition acyclic; its final size must remain below 1,000.

All new production modules are siblings in that same application directory:

| New module | Responsibility and source groups | Target LOC |
| --- | --- | --- |
| `context_domain_rerank_legacy_contract.py` | Relocated legacy `DomainRerankSignal` type plus common reason-match helper; existing alternate types module stays untouched; no new third DTO or policy registry | 40–80 |
| `context_domain_rerank_inventory.py` | Inventory and aggregation signals, owner/subject guards, aggregation count/list evidence | 550–750 |
| `context_domain_rerank_social.py` | Support networks, commonality, family/camping detail and event sequence; colocated patterns and candidate predicates | 650–900 |
| `context_domain_rerank_state.py` | Identity, relationship status/duration/origin, current and stale states, state transition, age/birthplace, correction evidence | 500–750 |
| `context_domain_rerank_preferences.py` | Current goals, preferences, followups/lifestyle, beach/mountains, purchase, symbolic importance and emotion | 600–900 |
| `context_packer_answer_support_content.py` | Precise answer-content dispatch, domain-specific content rankers, object rank, and precise-turn quality | 550–800 |
| `context_packer_answer_support_evidence.py` | Exact evidence predicates plus non-location domain evidence rankers (common interests, volunteering, awards, participation); no family-ordering orchestration | 650–950 |
| `context_packer_answer_support_locations.py` | Place/state residence/destination predicates and rankers | 250–450 |
| `context_packer_answer_support_temporal.py` | Shared temporal eligibility predicate, degree completion, temporal query-object/source-span evidence and pet-acquisition date support; depends on existing slots/patterns/utils only | 200–400 |
| `context_packer_answer_support_families.py` | Family identity, source grouping, reason keys, caps, marker-vs-inventory family decisions and coverage family slots | 650–950 |
| `context_packer_answer_support_ordering.py` | Query focus, family priority, item tie-break keys and coverage round-robin ordering | 650–950 |

The old signal module becomes an explicit import/re-export compatibility facade. The old answer-support module retains bounded top-level candidate selection/sampling/orchestration and explicitly re-exports existing helpers. Exact partitioning follows static dependency analysis before moving bodies; no module may import either compatibility facade. Small helper relocation between the listed modules is allowed only to remove a cycle and must be recorded in implementation notes.

New tests: `tests/unit/test_context_policy_import_contracts.py` and `tests/unit/test_context_policy_behavior_snapshots.py`, each below 1,000 lines, with fixtures only in `tests/fixtures/context_policy_refactor/` if readable expected snapshots require them. Existing overlarge tests will not grow. Plan/review evidence remains in this document.

Shared architectural bookkeeping: remove only the two selected source-file entries from `tests/architecture/file_size_legacy_baseline.json` once each is below the cap. Delete the brittle exact `assert len(baseline) == 107` assertion in `tests/architecture/test_file_size_boundaries.py`; every direction makes that identical one-line deletion, which permits legitimate exception removal while retaining the actual repository scan and all monotonic no-new/no-growth checks and fixtures. Coordinate combined baseline reconciliation with the coordinator. Do not relax the cap, baseline monotonicity, or any other architecture rule.

Exclude all files in concurrent PR #91, especially `context_collectors.py`, `context_query_execution.py`, `context_vector_candidates.py`, their tests, and CI. Also exclude server comparison/evaluation code, provider/runtime lifecycle code, architecture-wide renaming, the retrieval pipeline, SDK/API contracts, all migrations and dependency files.

## Behavior and architecture invariants

1. Public imports and every currently imported private helper continue to resolve from their old modules. Use direct explicit re-exports, not star exports, `__getattr__`, `sys.modules` aliases, proxy registries, or runtime import tricks.
2. Preserve both preexisting frozen signal DTO families. Move only the legacy class into `context_domain_rerank_legacy_contract.py`; all legacy producers and original-path re-exports use that identical class. Preserve the original `__module__` explicitly for introspection and pickle compatibility. Do not edit `context_domain_rerank_types.py` or its distinct producers. Freeze old/new-family distinctness, same-family equality, defaults, fields, constructor signature and old-path pickle readability. The contract module relocates a definition; it does not introduce a third runtime DTO definition.
3. Move functions and declarations verbatim except required import references and minimal module documentation. Preserve regex strings/flags, reason sets, thresholds, cap values, number arithmetic, short-circuit order, signal application order, diagnostic keys and values, tuple ordering, stable-sort/tie-break behavior and malformed-diagnostic fallbacks.
4. `context_domain_rerank_apply.py` is unchanged: it retains registration and application order. No registry or strategy engine is introduced.
5. Do not recompute relevance, hydrate sources, gather candidates or move filtering into the new policies. Postgres remains canonical; source-reference requirements and space/scope/thread/tenant boundaries remain upstream and unchanged. Existing source-group and owner guards move together with their policy.
6. Core continues to depend only on domain/application/ports. No framework/provider imports, dynamic loading, new packages, network-dependent tests, or runtime configuration changes.
7. No source edits in `context_ranking.py`; its cache and monkeypatch call sites remain untouched. Before moving answer-support helpers, search all tests and application imports for monkeypatch use, exported imports and direct module attribute access. Any observed seam must be preserved or cause the affected body to remain in the compatibility module.
8. Dependency direction follows the explicit graph below; signal facade → grouped policies → legacy contract. Grouped leaves never import the old facade. Do not move shared helpers into a lower module if they in turn depend on a higher policy.

### Concrete shared-helper ownership and dependency graph

- Existing `context_packer_answer_support_utils.py` receives `_answer_support_query_reason`, `_answer_support_source_group`, `_has_derived_source_group_ref`, `_first_dialogue_marker`, `_primary_exact_turn_marker`, `_exact_marker_should_precede_inventory`, and `_is_business_commonality_reason`. These require only diagnostics, DTOs, existing utility functions and regexes. The source-group key/derivation guard moves together, preserving provenance semantics.
- New `context_packer_answer_support_temporal.py` owns `_is_temporal_answer_support_item` and its callers concerning degree completion, temporal query object/source span, exact temporal families, and pet date anchors. It imports `_business_commonality_answer_slot`, `_is_community_participation_reason` and `_inventory_answer_slot` from existing slots. It cannot live in utils because slots already imports utils.
- Evidence owns the four `_answer_support_{inventory,animal_evidence,career,common_interest}_family_slot` adapters and the exact-evidence predicates that use them. These adapters parse existing slot formats using existing slots; they do not call family classification. The coverage-slot adapter/priority and round-robin algorithm belong to ordering, which can consume evidence adapters.
- Content owns precise content/turn rankers and may read the shared temporal predicate. Locations owns only geography/residence/destination evidence. Evidence can consume content, temporal and locations. Families consumes temporal plus low-level slots/patterns/utils, never evidence or ordering. Ordering consumes families, evidence, content, locations and temporal. The original module retains top-level candidate collection/sampling and imports all needed implementations directly.

Read arrows below as imports; all modules also may use domain DTOs/diagnostics as today:

```text
patterns -> standard library
utils -> DTO + diagnostics + standard library
slots -> patterns + utils + existing independent evidence helpers
temporal -> slots + patterns + utils
locations -> slots + patterns + utils + existing independent geographic evidence
content -> temporal + slots + patterns + utils
evidence -> content + temporal + locations + slots + patterns + utils
families -> temporal + slots + patterns + utils
ordering -> families + evidence + content + locations + temporal + slots + patterns + utils
old answer-support module -> ordering + families + evidence + content + locations + temporal + slots + patterns + utils
```

No existing patterns/slots/utils module can import a new higher policy. If a helper's actual dependency violates this graph or pushes a module over 1,000 lines, revise its explicit owner and obtain renewed review before production extraction; do not introduce dynamic forwarding.

## Sequence and review gate

1. Publish this plan in a draft PR before production work.
2. Obtain round-one critiques from the other two direction owners; record each actionable finding and fix this plan.
3. Obtain round-two critiques from the same two independent critics on the revised plan; record resolutions and any explicit follow-up limitations. Implementation starts only after coordinator confirms this gate.
4. Capture focused baseline tests and deterministic characterization outputs on unchanged base. Inventory imported names/signatures and identify any monkeypatch seams. Verify the planned dependency graph can be acyclic within the proposed LOC targets.
5. Extract domain signal contract and policy groups, preserving old imports. Run domain signal/application/ranking focused tests and compare baseline signal snapshots. Commit independently.
6. Extract packer leaf content/evidence/family policies and ordering, retaining old imports. Run packer-focused tests and compare final rendered packing snapshots. Commit independently.
7. Apply the coordinated two-entry baseline decrease, run combined verification, publish implementation and review evidence, and request independent code review. Address findings in follow-up commits before merge.

## Meaningful verification and acceptance

Baseline and post-change verification use the root-managed frozen environment and run inside this worktree so imports resolve to this checkout. Record exact commands and test counts after environment preparation; no provider services are required for this pure-policy change.

- Domain behavior: existing `tests/unit/test_context_domain_rerank_signals.py` and `test_context_domain_rerank_apply.py`, including exact-vs-weak evidence, wrong owner, subject mismatch, singleton aggregation vs multi-evidence, temporal correction and current/stale state. Existing `test_context_ranking.py` and the focused ranking tests exercise combined scoring and diagnostics through the unchanged pipeline.
- Packing behavior: all existing `tests/unit/test_context_packer*.py`, plus recommendation, location/item inventory, parent activity and exact support consumers. This covers constrained token budgets, family and source diversity, marker precedence, source spans, ties, duplicate evidence, exact answer preference and rendered citations.
- Characterization: before extraction, add a compact fixed synthetic corpus spanning inventory/aggregation, state corrections, relationship self-report vs question-only, place/temporal evidence and unrelated distractors. Persist the expected full `DomainRerankAdjustment` and selected item IDs/order, diagnostic signals, source refs and final rendered prompt for normal and tight budgets. Freeze those expectations from baseline before implementation; compare them unchanged after extraction. Do not approve regenerated expectations merely because the refactor differs.
- Import compatibility: assert explicitly inventoried original import names resolve and retain signatures; assert each moved legacy producer returns the same `DomainRerankSignal` object re-exported at the old path while existing alternate producers retain their distinct existing class. Check both families’ identity/equality/defaults and an unconditional baseline old-path legacy pickle fixture. Import leaves and facades in fresh Python processes in both orders to reveal hidden cycles.
- Mandatory process-level composition: run `/workspace/scratch/b6182bae50e9/infinity-context/.venv/bin/python -m pytest -q tests/e2e/test_memory_quality_e2e.py`. Its two provider-free tests launch the real local server and exercise fact lifecycle/scope isolation plus document recall/restriction/delete through context ranking and packing. No optional skip or external provider is permitted for this gate; record baseline and post-change counts. The direct unit-level rendered snapshots remain the tighter behavioral drift detector.
- Architecture: run `tests/architecture`, file-size monotonicity against the base ref, and Ruff for changed files. Add a narrow import-boundary assertion if the static graph reveals a non-obvious facade-backedge risk; avoid tests that merely mirror a list of moved functions.
- Acceptance is zero behavioral/snapshot drift, zero existing focused-test regressions, all compatibility imports working, no new core infrastructure dependencies, two old modules and every new/modified module below 1,000 lines, no changes to excluded ownership paths, and reviewed fixes before merging.

## Scope, risk, and deferral

Approximately 5,492 existing lines are repartitioned; expect roughly 400–700 net lines of explicit imports, module documentation and narrow characterization/compatibility tests. The value is cohesive policy ownership and removal of two major legacy size exceptions. This is not an algorithm or retrieval quality change.

Main risks are a facade/leaf import cycle, duplicate DTO definitions, losing a private imported helper, unintentionally binding a monkeypatched global in a new module, ordering drift, and splitting source/owner guards away from their associated evidence policy. Mitigate through the pre-move import/dependency inventory, colocation, exact baseline outputs, fresh-process import checks and existing composed unit packing tests plus the mandatory real-server memory-quality E2E. If an acyclic split cannot meet the cap while retaining a compatibility seam, stop and revise the reviewed plan instead of inventing dynamic forwarding.

Defer `context_ranking.py` and the independently oversized existing answer-support pattern/slot modules. They need separate reviewed decompositions; this PR must not claim that all core technical debt is resolved.

## Critique and resolution log

Round 1 completed independently by server and lifecycle direction owners before production edits:

- Server R1-S1 (blocking): two preexisting signal DTO families made the original all-producers-one-type invariant a behavior change. Fixed by preserving both, relocating only the legacy class into a specifically named legacy contract, leaving the existing alternate type/producers untouched, and freezing class distinctness plus legacy old-path pickle compatibility. The relocation adds no third class.
- Server R1-S2 / lifecycle R1-C1 (medium): shared query/source/temporal predicates were under-specified. Fixed with the named shared-helper allocation and acyclic graph above, including the existing slots → utils edge. Added a temporal module so temporal evidence does not get conflated with geographical evidence or imported into utils in a cycle.
- Lifecycle R1-C2 (medium): no exact real-caller E2E/golden command. Fixed by making both provider-free `test_memory_quality_e2e.py` cases mandatory alongside the stronger direct snapshots.
- Both noted baseline pickle coverage should be unconditional; fixed.

Read-only baseline while awaiting reviews: domain signals + apply + main packer + answer-support ordering: 278 passed in 5.82s. No production edits occurred.

Round 2 completed independently by the same server and lifecycle direction owners:

- Server: approved revised plan; preserving two DTO families, legacy-only relocation, unconditional baseline pickle/identity checks, explicit helper graph and real-server composition gate resolve its findings. Record: `plans/review-r2-core-by-server.md` (temporary coordination record).
- Lifecycle: approved revised plan; shared predicate ownership, slots/utils graph, mandatory process-level command and distinct DTO compatibility resolve its findings. Record: `plans/review-r2-core-by-lifecycle.md` (temporary coordination record).
- No further blocking or medium findings. No production code was edited during either plan-review round. Implementation remains blocked until the coordinator releases the gate.

Additional unchanged-source baseline: real local HTTP `tests/e2e/test_memory_quality_e2e.py`: 2 passed in 12.27s. Initial sandbox execution could not create sockets; the identical command passed after approved localhost-capable execution. This is not a product failure or an optional skip.


## Implementation and final verification

Pinned source base: `44ac164a8395c5847ae8792dded95d0dfe4526dd`. The coordinator published the reviewed plan before releasing implementation.

Commits in order:

- `81fa1241`: captured behavior/import characterization while both production modules were unchanged. Seven fixed synthetic scenarios (inventory ownership, aggregation, state, relationship, place, temporal and support) each exercise three candidates under normal/tight budgets. Full adjustments, selected item order/content/source refs/diagnostics and rendered evidence are frozen. The contract fixture also captured original callable signatures, both DTO families and an actual pre-move legacy pickle.
- `3b77d671`: extracted domain policies and the specifically legacy DTO; retained the distinct existing alternate DTO/producers. The old module is an explicit compatibility export list.
- `c53a008d`: extracted answer-support content/evidence/geography/temporal/family/ordering policies. The old module retains candidate orchestration and direct compatibility exports. The agreed shared query/source/marker helpers moved to existing utils.

All original function/class/constant declarations are preserved. Independent root and lifecycle audits matched all **212 domain declarations** and **175 original packer/utils declarations**, exactly once, with identical ASTs. No scoring expression, regex, reason set, guard, branch, helper signature or packing algorithm changed. Original legacy type `__module__` identity is deliberately retained for historical import/pickle compatibility; the existing alternate class remains distinct. The only extra cross-policy domain dependencies are social → inventory for exact inventory evidence and social → state for the shared transition regex; these are acyclic and avoid duplicate definitions.

| Module | Final lines |
| --- | ---: |
| Existing domain signal compatibility module | 261 (was 2,391) |
| Legacy signal contract | 30 |
| Inventory policies | 545 |
| Social policies | 639 |
| State policies | 599 |
| Preference policies | 695 |
| Existing answer-support orchestration/compatibility module | 527 (was 3,101) |
| Answer content | 617 |
| Exact/domain evidence | 610 |
| Family/source grouping | 482 |
| Geography/residence evidence | 256 |
| Query ordering | 821 |
| Temporal evidence | 188 |
| Existing shared utils | 541 (was 473) |

Every new or modified production code file is below 1,000 lines. Exactly the two owned legacy ceilings were removed. The shared brittle baseline cardinality assertion was deleted while all real size/monotonicity checks remain. Existing oversized pattern/slot modules, ranking, collection/query/vector files, application consumers and all server/adapters/lifecycle code are unchanged.

### Exact final gates

Run inside the core worktree with `.venv` pointing at the coordinator-managed frozen environment:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_context_packer*.py tests/unit/test_context_*ranking*.py \
  tests/unit/test_context_domain_rerank*.py \
  tests/unit/test_context_recommendation_answer_support.py \
  tests/unit/test_context_location_inventory.py \
  tests/unit/test_context_item_collection_inventory.py \
  tests/unit/test_context_policy_behavior_snapshots.py \
  tests/unit/test_context_policy_import_contracts.py

.venv/bin/python -m pytest -q tests/architecture

FILE_SIZE_BASE_REF=44ac164a8395c5847ae8792dded95d0dfe4526dd \
  make infinity-context-lint PYTHON=.venv/bin/python RUFF=.venv/bin/ruff

.venv/bin/python -m pytest -q tests/e2e/test_memory_quality_e2e.py
```

Results at source commit `c53a008d`:

- **999 focused tests passed** in 21.31s: 986 existing tests plus 13 frozen behavior/import/pickle/fresh-process import checks. Untouched baseline for the same 986 existing tests passed in 22.47s. No expected golden changed after source extraction.
- **216 architecture tests passed** in 94.08s.
- **Repository Ruff passed** and the pinned-base file-size monotonicity gate passed with 105 remaining legacy ceilings; no new/increased exception.
- **2 real local HTTP memory-quality E2E tests passed** in 12.30s after extraction (unchanged baseline: 2 passed in 12.27s). This required approved socket-capable execution; the restricted sandbox cannot create localhost sockets. No service/config/source changes or skipped gates were used to work around that environment constraint.

The characterization/import fixtures remain the bytes captured before production edits. Each fixture is below 600 lines; the full diagnostic maps account for most of the fixture data. Fresh-process import checks exercise leaf/facade orders in both directions. Tests preserve the existing outputs without claiming improved retrieval quality or changed lifecycle guarantees.

### Independent code review

- Lifecycle direction owner approved domain stage `3b77d671` and final packer stage `c53a008d`, with no substantive findings. Independently verified all 387 declarations, direct old-path exports (137 packer declaration names), acyclic imports/no facade backedges, and query/source guard colocation. Temporary review records: `plans/review-code-core-domain-by-lifecycle.md` and `plans/review-code-core-by-lifecycle.md`.
- Root independently verified all 387 declarations and unchanged golden fixtures and reported no substantive concern.
- Server direction owner approved source commit `c53a008d`, with no substantive findings. Independently matched all 212 domain and all 137 packer declarations, inspected actual DTO/source-query/ordering imports, baseline identity/pickle/rendered snapshots and acyclic/no-facade-backedge graph. Temporary review record: `plans/review-code-core-by-server.md`.
- Root independently verified the combined 387 original domain + packer/utils declarations exactly once and the acyclic dependency graph; no substantive concerns. Both independent peer code reviews and all direction-specific gates are complete. The coordinator owns final integrated CI and merge; this direction makes no remote merge itself.
