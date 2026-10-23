# Core wave 2 concrete plan — critic draft v2 — round-1 dispositions incorporated

Status: NOT AUTHORIZED FOR IMPLEMENTATION until two independent critics complete two rounds and issues are resolved. Audit: `core-audit.md`. Base: `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`.

## PR core-A — one authority per ranking responsibility

### Scope and concrete files

All production files below are in `packages/infinity_context_core/infinity_context_core/application/`.

| File | Responsibility after change | Estimated final LOC |
| --- | --- | ---: |
| context_ranking.py | Existing public compatibility functions and deterministic batch orchestration; explicit callback passing for observable legacy globals. No repeated algorithms. | 350–650 |
| context_rank_dedupe.py | Sole current dedupe/source merge/body selection policy, reconciled from current facade. | 220–300 |
| context_rank_fusion.py | Sole RRF scorer and diagnostic score mutation policy. | 180–220 |
| context_bm25_ranking.py | Sole BM25 preparation/scoring/cache implementation, existing callback seams preserved. | 450–520 |
| context_query_relevance_ranking.py | Shared lexical selection primitives; retains existing basic canonical-fact call semantics; separate named plan-aware selector owns current strict/false-friend ranking behavior. | 200–280 |
| context_keyword_ranking.py (existing, 178 LOC) | Sole keyword chunk score/source boost policy and reason-specific caps, compared and reconciled against the current facade before wiring. | 178–220 |
| context_anchor_intent_ranking.py (existing, 84 LOC) | Sole query-anchor boost/diagnostics policy, reconciled to current facade, with explicit supported normalization binding where required. | 90–120 |
| context_requirement_ranking.py | Sole requirement boost and typed-unit mismatch policy, current main behavior wins. | 220–280 |
| context_requirement_signals.py | Sole immutable coverage DTO and extraction policy. | 100–130 |
| context_rerank_relevance.py | Sole diagnostic relevance bridge and current score conversion rules; callback for late-bound best_query_relevance. | 130–170 |
| context_rerank_evidence_signals.py | Sole localized/citation/source quote/decomposition/artifact support policy; current main behavior wins. | 450–580 |
| context_rerank_domain_heuristics.py | Sole domain noise/temporal/dialogue helpers; current metadata handling wins. | 450–550 |
| context_deterministic_rerank_policy.py (new) | Current 662-line signal assembly and its constants/result DTO; no generic registry or strategy framework. | 850–990 |
| context_deterministic_rerank.py (new) | Item diagnostics/score application and artifact score floor; stable no-op identity and explicit normalization/relevance callbacks. | 180–250 |
| context_same_person_disambiguation.py (new) | Batch same-person topic profiles and penalties; owned constants/DTOs. | 250–330 |

ADR-0007 ownership reconciliation: this slice deliberately consolidates the current legacy application adapter graph without moving its business policy into `shared_kernel` or pretending it belongs to a new feature/domain layer. The actual capability owner remains `context_building`; legacy `ContextItem`, `QueryExpansionPlan` and query-intent contracts are not interchangeable with the feature capsule's DTOs. Migrating the whole legacy packer to feature contracts would expand scope and risk parallel authorities. Existing bounded owners therefore remain under legacy application with dependency gates proving no feature internals imports. Future feature migration can replace this one coherent adapter graph through `context_building.public`; this PR neither adds exceptions nor reverses feature dependency direction.

### Dependency DAG

`context_ranking compatibility facade -> bounded ranking owners`.

`deterministic item application -> deterministic signal policy -> evidence + domain heuristics + requirement signals + relevance bridge + existing domain signal facade`.

`same-person batch policy -> lexical/relevance/query intent + diagnostics/DTO`.

`BM25/query relevance/keyword/dedupe/fusion/anchor-intent/requirement owners -> their current lexical/reason/coverage/diagnostics/DTO/domain dependencies`.

No owner imports `context_ranking`. No dependency from prior-wave domain signal modules to these orchestrators. Existing distinct `DomainRerankSignal` classes remain distinct. Source review/gate must reject reverse facade imports; no module-level `sys.modules` replacement, globals copying, generic getattr forwarding or mutable service locator.

### Behavior and DRY decisions

Current facade is the behavior oracle; pre-existing shadow owners are implementation destinations, not the behavior oracle. Reconcile helper-by-helper with an inventory of changed signatures/body differences before wiring. Do not replace richer plan-aware query selection with the basic canonical fact selector: retain basic selector as a distinct named policy operation and share only genuine selection primitives. Do not merge semantically distinct DTOs. Concrete metadata/DTO decision: use exactly one implementation per DTO. The already existing `context_requirement_signals.RequirementCoverageSignals` remains the canonical class; expose `_RequirementCoverageSignals` from the old ranking facade as a direct alias. Its fields/defaults/frozen behavior/property values are preserved. The old underscore name is a private compatibility attribute, not a stable repr/type-name contract: its newly emitted repr/class name becomes `RequirementCoverageSignals` and new pickles encode the existing owner path. Old pickles naming `context_ranking._RequirementCoverageSignals` must still decode via the alias to the canonical class. This is an explicit private metadata migration, not unchanged cross-process class identity.

The three `_Bm25Document`, `_Bm25PreparedItem`, `_Bm25QueryMatch` classes become canonical in the already existing `context_bm25_ranking` owner, preserving their names and qualnames. `_DeterministicRerankSignals` and `_SamePersonTopicProfile` retain names/qualnames in `context_deterministic_rerank_policy` and `context_same_person_disambiguation` respectively. Old facade names remain explicit aliases for old class/instance pickle resolution. No duplicated DTOs or hand-set `__module__`.

Moved algorithm functions retain names/qualnames/signatures/defaults/evaluated hints; defining `__module__` changes to the actual owner for direct reexports. Facade wrappers needed for supported callbacks retain their facade metadata. Old top-level function pickles resolve through the old explicit attributes; new pickles use the real current defining module. Capture representative old class, instance and function pickle bytes before moving source, and assert this declared metadata policy plus field/value behavior after moving.

Keep legacy callable signatures/default values. Facade wrappers explicitly pass current `query_terms`, `query_term_frequency`, `text_variant_profile`, `best_query_relevance`, and normalization callbacks at call time wherever tests observe monkeypatches. Keep `_query_expansion_terms_for_signature` as one cached facade callable with its `cache_clear` behavior; pass its plan term function into BM25 and plan-aware query relevance. Pure function re-exports are used when no late-bound global seam exists. Preserve same tuple/item identity on no-op paths, including already-applied normalization guard. Do not create callbacks for unrelated internals speculatively.

### Evidence before source changes

After plan approval but before production edits, generate versioned synthetic golden fixtures from an untouched base checkout using a separate script and explicit base SHA in fixture metadata. Never regenerate from the changed tree. Include full `ContextItem` diagnostics/refs/ordering and rendered pack output for: exact source sibling body selection; reason priority near dedupe tolerance; rank fusion; BM25/prepared cache behavior; strict lexical false friends and direct visual/count compound queries; typed answer-unit mismatch; citation/source quote anchor coverage; temporal metadata and source quote temporal answers; malformed/bool diagnostics; already-applied/no-op paths; same-person topic disambiguation. Existing seven policy snapshot fixtures remain unchanged. Also capture direct-owner behavior before reconciling implementations: the basic query relevance operation and canonical fact selection keep their distinct existing semantic choice; record domain-derived winner, protected original head and a tie outcome from `context_canonical_fact_retrieval`. The direct `context_rank_dedupe.dedupe_rank_items` consumer in paired-reservation tests must keep typed role-membership merge and ordering output. Capture those complete results independently of facade scenarios. The keyword owner already exists at 178 LOC: compare every one of its four functions and owning constants against current facade source and include actual keyword caller coverage; do not overwrite or create another unreviewed authority. Every direct owner import found by the source inventory gets a recorded semantic disposition; retain a genuinely distinct named operation when required by a real consumer, sharing primitives rather than retaining duplicate bodies.

Add a bounded test module `tests/unit/test_context_ranking_policy_ownership.py` (estimated 400–700 LOC), fixture capture helper under tests/fixtures/context_policy_refactor or scripts only if needed (<=400 LOC), JSON fixtures under `tests/fixtures/context_policy_refactor/wave2_ranking/`, and `tests/architecture/test_context_ranking_policy_ownership.py` (<=180 LOC). New architecture tests check directional dependency and absence of duplicate policy definitions in the facade, with a focused semantic invariant rather than hardcoding incidental imports. The direction guard checks transitive local application import reachability as well as direct edges: no owner may reach the ranking facade or artifact-evidence orchestration; the existing `context_artifact_evidence -> context_ranking.query_expansion_reason_priority` edge must not become a cycle. Code/AST/global-binding evidence is mandatory: inventory each moved callable's free globals against its final defining module, verify aliases point to the intended owner, demonstrate each supported late-bound callback reaches the current facade binding, and check the algorithm body lives in exactly one owner. Counters alone cannot establish consolidation; frozen full-output fixtures, AST definition inventory, function identity/global inspection and independent code review are complementary proof.

### Validation (no full baseline repetition)

Use the frozen shared Python 3.12 .venv with explicit PYTHONPATH/worktree context; resolve actual executable from root. Commands after implementation:

- `.venv/bin/python -m pytest tests/unit/test_context_ranking.py tests/unit/test_context_ranking_policy_ownership.py tests/unit/test_context_policy_behavior_snapshots.py -q`.
- `.venv/bin/python -m pytest tests/unit/test_context_*ranking*.py tests/unit/test_context_answer_shape_ranking.py tests/unit/test_context_citation_frame.py tests/unit/test_context_packer.py tests/unit/test_context_canonical_fact_retrieval.py tests/unit/test_context_ranked_evidence_paired_reservation.py tests/unit/test_context_query_expansion.py -q` (only once for integration; explicit canonical-fact/direct-dedupe/keyword callers are mandatory rather than optional dependency-map follow-up).
- `.venv/bin/python -m pytest tests/architecture/test_context_ranking_policy_ownership.py tests/architecture/test_memory_boundaries.py tests/architecture/test_feature_owned_vertical_slices.py -q`.
- `FILE_SIZE_BASE_REF=origin/main make infinity-context-file-size-boundaries`; focused ruff on changed production/tests and `git diff --check`.
- Root reruns the seven deterministic evals and actual HTTP/worker E2E only if shared-gate risk requires it; never invoke live/paid providers. Runtime tests requiring namespace identity use escalation, not modified guards.

Remove the 3,681-line ranking baseline entry when facade <=1,000, request root reconciliation. No new baseline entries. Commit/push promptly after code review/fixes; root owns PR API and merge. Separate PR, independently reviewable against base.

## PR core-B — demand-loaded compatibility surfaces

### Scope and concrete files

- `packages/infinity_context_core/infinity_context_core/__init__.py`: replace eager exports with explicit demand resolver; preserve 31 advertised names/order and runtime object identities. Estimated 80–140 LOC.
- `.../application/__init__.py`: preserve 267 names/order, four feature-public module attributes and bundle aliases through demand resolver. Estimated 340–500 LOC including static typing imports if required.
- `.../application/_compatibility_exports.py` (new): explicit module/attribute export manifest, estimated 400–700 LOC. One authoritative manifest; derive `__all__` from its insertion order, no duplicated export list.
- `.../shared_kernel/__init__.py` (new, 1–3 LOC) and `.../shared_kernel/lazy_exports.py` (new): technical stdlib-only import-and-cache resolver, estimated 25–50 LOC. The source tree currently has no shared_kernel package; this creates the ADR-0007 technical namespace with no feature imports. No policy, auto-discovery, exception swallowing or import fallback.
- `tests/unit/test_core_compatibility_exports.py` (new), <=400 LOC; `tests/architecture/test_core_import_isolation.py` (new), <=250 LOC; JSON static API inventory fixture <=300 entries.

Compatibility scope is the advertised 31/267 export names in exact `__all__` order, the four advertised feature-module names and the documented bundle aliases. Incidental eager namespace attributes such as automatically initialized parent submodules are not promised as pre-materialized `vars(module)` entries. Normal explicit submodule imports remain supported. Do not record the entire eager `vars(module)` as an initialization contract.

Do not modify ports/features package initializers, use case implementations, previous-wave signal/answer modules or any of the 15 exact PR #91 paths in `/workspace/scratch/b6182bae50e9/plans/wave2/excluded-pr91.txt`. This is a separate independent branch/commit split after core-A; no semantic dependency on core-A.

### Dependency DAG and behavior

Bare root/application imports -> stdlib + technical resolver + static mapping only. Attribute request -> exact defining module -> exact original object cached in module globals. Root and application aliases resolving to the same definition satisfy `is`. Feature module attributes resolve to the real module. Existing Python submodule importing remains conventional. No proxy objects; original classes retain `__module__`, exceptions, pickle path and dataclass identity. Unknown attributes raise conventional AttributeError; real import errors propagate intact.

`__dir__` advertises the existing public names before materialization. Star import resolves all declared names and retains `__all__` order/type. Use a TYPE_CHECKING block for static type discoverability if compatible with size limits; importing TYPE_CHECKING itself must not load use cases. A single shared resolver is justified by two real technical consumers and contains no business policy. Runtime import graph improvement is asserted using fresh interpreters, not estimated by performance thresholds.

### Evidence before source changes

Extract the exact root/application `__all__` order and every exported object's defining module/name from untouched base in a separate fresh interpreter. Record module-valued exports and bundle aliases explicitly. Capture evaluated `typing.get_type_hints` for representative public DTO/use-case/error exports and annotation forward references; do not merely assert TYPE_CHECKING imports exist. Capture pickle round-trips for representative DTO, domain class and error and verify against exact defining objects. Pin these records before edits. Do not snapshot incidental `sys.modules` order or all underscore internals.

New fresh-interpreter tests assert importing a feature domain module, core domain entities, a core ports protocol, `infinity_context_core.sensitive_text` and `infinity_context_core.application.safe_payload` safety modules and a single application DTO does not initialize unrelated legacy use cases or ranking/packing/collectors. Assert the complete loaded core-module closure matches allowed dependency roots for each isolated import, so an unlisted accidental use-case import cannot evade a short blocklist. For direct import/application export requests prove exact identity, import cache reuse, `dir`, star import, unknown attributes, legitimate import failure propagation and unchanged pickle identity and evaluated type hints. Fresh-process results identify exact module/object binding and allowed closure, rather than relying only on module counts or timing. Tests should use `sys.executable` with explicit worktree PYTHONPATH (frozen venv editable paths point to base checkout); avoid environment pollution and provider calls.

### Validation and gates

- `.venv/bin/python -m pytest tests/unit/test_core_compatibility_exports.py tests/architecture/test_core_import_isolation.py -q`.
- `.venv/bin/python -m pytest tests/architecture/test_memory_boundaries.py tests/architecture/test_feature_owned_vertical_slices.py tests/architecture/test_cognitive_memory_boundaries.py -q`.
- Focused existing API/core fact use-case tests and context behavior snapshots to expose import-order/cycle regressions.
- File-size gate, ruff on changed files, `git diff --check`.
- Root-owned integration only as required for remaining import/composition risk; no full baseline repetition.

## Review workflow and stop conditions

For EACH PR direction: critic A round 1 + critic B round 1 -> fix plan -> both critics round 2 -> fix/explicit approval -> capture base evidence -> implement -> two independent code reviews/fixes -> focused validation -> commit/push -> root PR/merge. Do not start core-B from core-A's approval alone. Stop if a current-source behavior cannot be preserved within bounded modules, an excluded/open-PR file is required, an ADR exception would grow, or identity/callback compatibility would require hidden global forwarding; report concrete alternative to root. No accepted ADR changes or file-size relaxations.


## Round-1 critique dispositions (v2)

| Reviewer/item | Disposition and exact plan change |
| --- | --- |
| Lifecycle C1; runtime advisory keyword inventory | Accepted. Existing `context_keyword_ranking.py` is 178 LOC, now listed as an existing authority and included in audit. Its four functions/constants receive before-source comparison; actual `test_context_query_expansion.py` is an explicit gate. |
| Lifecycle C2; runtime C2 canonical-fact owner | Accepted. Freeze direct basic selector/canonical-fact winner/protected-head/tie outputs and run exact `test_context_canonical_fact_retrieval.py`. Preserve basic vs richer plan-aware operations. |
| Runtime C2 direct dedupe caller | Accepted. Freeze typed paired-role merge output and run exact `test_context_ranked_evidence_paired_reservation.py`; direct-owner semantics are recorded rather than assumed equivalent. |
| Lifecycle C3; runtime C1 metadata | Accepted. Explicit canonical class/name/module policy now covers all six private DTOs, direct function reexports and facade wrappers; old class/instance/function pickles and evaluated hints are captured before edits. Coverage canonical name remains existing `RequirementCoverageSignals`; old underscore attribute is an alias with explicitly changed private repr/name/new pickle path. |
| Both reviewers near-cap caution | Accepted. Static source count for the 662-line assembly plus its two local constant definitions is 697 lines before DTO/imports; 850–990 estimate is feasible. Stop/re-review if the actual responsibility cannot fit below 1,000; no threshold-driven helper bucket. |
| Runtime artifact reverse-edge advisory | Accepted. Add transitive local import reachability to the ownership guard; lower owners cannot import artifact orchestration or reach the compatibility facade. |
| Runtime core-B incidental namespace advisory | Accepted. Advertised exports/feature-module aliases are compatibility scope; incidental eager `vars(module)` initialization is explicitly excluded. |

Both independent round-1 reviewers support core-B with no design blocker. No production changes or characterization runs occurred during this revision. Request both independent round-2 reviews of v2 before root release, separately for core-A and core-B.


### Final read-only inventory correction before release

`context_anchor_intent_ranking.py` already exists at 84 LOC and duplicates the facade's `apply_query_anchor_intent_boosts`, `_with_query_anchor_intent_boost` and already-applied helper. It has no direct production/test consumers. Include this existing owner in core-A's single-authority inventory, reconciling current facade behavior and explicit normalizer callbacks where the supported facade seam reaches it. No new responsibility/module or extension framework is introduced. Before-source full pipeline fixtures cover its score/diagnostics/no-op output. Both critics must acknowledge this narrow correction before root release.
