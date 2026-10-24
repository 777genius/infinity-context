# Wave 2 runtime implementation plan

Base: `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`.
Status: revised after two independent round-1 critiques; production edits/tests have not started.

## Outcomes and review sequence

Two separately reviewable PR slices move coherent, dependency-free benchmark policy out of
product serving. Each is behavior-preserving and keeps explicit legacy imports. Slice 2 can be
implemented on top of slice 1, but neither depends on its new internal modules. No new framework,
scoring heuristic, relation taxonomy, provider call, persistence, API/schema or lifecycle change.

Before source work: critic A and critic B independently review this plan; fix both sets of
findings; both independently review the revised plan; fix all blockers. Root then authorizes
implementation. After each slice: independent code review, incorporated corrections, focused
validation, prompt commit, root publication/review/merge.

## PR R1 — Benchmark-owned question intent policy

### Exact responsibility graph

New package `packages/infinity_context_benchmarks/infinity_context_benchmarks/retrieval_intent/`:

| Module | Responsibility | Approximate LOC |
| --- | --- | ---: |
| `contracts.py` | Four frozen intent DTOs, properties, query-profile and diagnostics rendering | 160 |
| `temporal.py` | Time-kind precedence, relative-time vocabularies, ordinal event recognition | 135 |
| `profile_patterns.py` | Status/activity/commitment/education/employment/health/contact/diet/pet/skill/vehicle/date/kinship predicates | 480 |
| `event_patterns.py` | Causal/emotion, location/goal/support/community, action/exchange/participation/communication predicates | 610 |
| `comparison_patterns.py` | Contrast/commonality/choice/count/list/negative-absence predicates and regexes | 150 |
| `profile_facets.py` | Profile/identity/community/relation facet data | 620 |
| `event_facets.py` | Event/activity/preference/goal/causal/location/contrast facet data | 510 |
| `relations.py` | Ordered facet registry composition, relation inference/reasons/deduplication | 260 |
| `evidence.py` | Evidence-need inference/merge, bundle roles, query risk flags | 310 |
| `__init__.py` | Explicit intentionally narrow public API | 70 |

These exact module names form the approved production scope. Owner-manifest entries select exact
definitions in these modules before relocation; an ownership change requires critic re-review.
These modules must form an acyclic dependency graph: contracts <- patterns/temporal/data <-
relations/evidence <- public capsule. Shared question predicates have exactly one canonical owner.
`event_patterns` uses `comparison_patterns` where required; `evidence` and `relations` use the same
predicate implementations. No function uses public `__init__` to import internal siblings.

Facet registry order is the exact original 31-key order, expressed explicitly when combining the
two semantic data owners; do not concatenate semantically grouped maps and change order. Keys,
sets, regexes and all classification precedence stay identical.

Modify existing `memory_comparison_intent.py` into documented explicit imports of every
currently defined public/helper/constant name. Preserve existing imported stdlib symbols too if
the compatibility inventory records them. No star import, module alias, `sys.modules` forwarding,
`__getattr__` dispatch, duplicated implementation, or hand-set `__module__`.
The four classes become canonically benchmark-owned; current pickles encode new canonical paths,
and pre-change pickles still resolve through old module aliases to the same class objects.
Moved functions likewise gain their canonical benchmark `__module__`; their `__name__`,
`__qualname__`, signatures, parameter kinds, defaults, annotations and docstrings are preserved.
Freeze legacy top-level function pickles too, and prove both old function references and new
canonical round trips. This metadata migration is deliberate and documented, not hidden with
manually assigned module names. Module namespace inventory includes imported typing/stdlib names
that callers could resolve; non-dunder compatibility is explicit and testable.

Migrate `memory_comparison_rerank.py` and `memory_comparison_evidence.py` direct policy imports to
the benchmark public capsule. These two server callers remain server-owned; do not move their
core-application-dependent orchestration into benchmark. Any touched oversized caller shrinks and
its size baseline is lowered by root; zero size ceiling increases.

`query_retrieval_intent` is defined in the server rerank consumer and remains there. Standalone
installed intent proof replays lower-level public APIs with frozen explicit inputs; server/bundle
proof additionally runs that real server consumer against frozen full query-profile/diagnostic
results. The standalone benchmark never imports the server's query-term machinery.

### Frozen behavior before source edits

1. Record old module namespace, definitions/signatures, dataclass fields/defaults/annotations,
   aliases, four legacy pickles, and the ordered facet registry/config values. Checked-in fixture
   manifest states base SHA and generation procedure. Preserve dictionary/list ordering in JSON.
2. Capture full `query_retrieval_intent` diagnostics and `to_query_profile` for the real existing
   benchmark/rerank question corpus, including temporal variants, all 31 relation facets, multiple
   facets and merged order, all evidence needs/roles, source grounding/negative/count/list/contrast,
   zero entities, >2 entities, broad query and wide expansion. Inputs are explicit question-only
   data; no answer labels enter policy.
3. Capture direct inference API cases for boundary/precedence combinations not reached by that
   corpus: temporal false vs duration/sequence/relative/explicit/lookup; visual/multi-hop; missing
   relation terms; direct-support role metadata; empty and duplicate relation intents. Freeze full
   diagnostics/profile/results, not only hashes. At least one fixture exercises each facet and
   each evidence-role branch, with coverage inventory proving that instead of a guessed count.
4. Run fixture generator and compatibility fixtures against untouched base, commit fixture/test
   evidence before production move in the eventual slice. Expected outputs are never regenerated
   from moved implementation to fix failures. Transient capture instruments only test process.

Frozen corpus test covers new direct public API and old imports; normal existing tests cover real
rerank/evidence consumers. Verify type identity, `get_type_hints`, dataclass replace/equality,
new pickle round trips and pre-source legacy pickle decoding. Search shows no existing helper
monkeypatch contract; include an explicit compatibility inventory test rather than promising that
assigning an alias in one module changes another module's globals.

### Focused gates

* New frozen intent/compatibility tests; existing relation-support, query-plan, evidence,
  source-grounding-rerank, benchmark and answer-context question tests selected by import/call graph.
* Architecture package direction and new AST guard: intent subpackage imports only stdlib or its
  own modules; no server/adapters/core.application imports or dynamic escape routes.
* Exact unchanged classification/ordered outputs; all modified/new files lint; new files <=1,000.
* Extend existing five-wheel/three-context script: standalone constructs all four DTOs and invokes
  temporal/relation/evidence APIs from installed benchmark; server/bundle decode frozen old pickles,
  assert aliases and compare frozen diagnostic output; every loaded infinity module resolves inside
  target installation. Standalone server/adapters stay unavailable.
* Runtime digest/RECORD focused tests continue fail-closed and include new policy paths. Root runs
  exact file-size/debt ratchet checks after applying the measured lower ceilings.

Exact shared ratchet proposal for R1: remove the baseline key ending
`infinity_context_server/memory_comparison_intent.py` (2,925); lower the existing
`memory_comparison_rerank.py` key only if its import migration reduces its actual line count.
Keep debt file cap 483. New server line cap is `208182 - 2925 + actual_intent_facade_lines +
actual_rerank_line_delta + actual_evidence_line_delta`. Actual R1 deltas are 0 and +1 respectively:
the required import-group separator makes evidence 877 -> 878, while aggregate debt decreases
2,835 lines to 205,347. Coordinator accepted this explicit estimate correction; no frozen ceiling
grows and useful whitespace is preserved.
Root computes and commits the concrete integer from this PR's tree, not an estimated allowance.

Estimated implementation + verification: 1.5-2.5 hours, ~3,100-3,500 new/moved production LOC,
~2,800 server production lines removed, 250-450 focused test/generator LOC plus JSON fixtures.

## PR R2 — Benchmark-owned complete candidate score policy

### Exact responsibility graph

New package `packages/infinity_context_benchmarks/infinity_context_benchmarks/rerank_policy/`:

| Module | Responsibility | Approximate LOC |
| --- | --- | ---: |
| `contracts.py` | Feature protocol, frozen concrete feature/score DTOs, contribution and plan DTOs, policy protocol | 235 |
| `common.py` | Shared numeric rounding, measured/precise locality, positive boost, reason-code helpers | 95 |
| `evidence.py` | Entity/speaker, relation coverage, focused turn, bundle, source-grounding contributions and grounding helpers | 500 |
| `temporal.py` | Temporal contribution and temporal grounding/sequence/currentness predicates | 270 |
| `intent.py` | Preference/multi-hop/contrast/negative/location contributions and their own predicates | 350 |
| `answer_shapes.py` | Answerability and value/count/list shape contributions and predicates | 250 |
| `typed_relations.py` | Typed relation role/category support and grounding policy/configuration | 240 |
| `scoring.py` | Ordered default policy composition, aggregation, final/provenance caps, final score diagnostics | 560 |
| `__init__.py` | Explicit intentionally narrow public API | 75 |

contracts <- common and specialized policies <- scoring <- public capsule. Specialized policies
depend only on contracts/common plus a narrowly imported owning predicate when genuinely shared;
no policy imports scoring/default registry. The complete end-to-end scorer has zero product imports.
Keep original ordered defaults exactly: EntitySpeaker, RelationCoverage, Temporal, PreferenceIntent,
FocusedTurn, EvidenceBundle, SourceGrounding, Answerability, MultiHop, ContrastIntent,
NegativeAbsence, TypedRelationSupport, LocationIntent, CountListAnswerShape, ValueAnswerShape.

Move `memory_comparison_rerank_policy.py` AND `memory_comparison_rerank_policies.py` into explicit
compatibility export modules; retain all original names and the explicit `policies=` injection seam.
Migrate the one real production caller in `memory_comparison_rerank.py` to the benchmark public API.
No final-score cap, rounding, comparison, mapping order, default value, reason, or schema changes.

Consolidate the five body-equivalent helpers into their natural owner (`common`, `evidence`,
`temporal`), with explicit aliases or typed delegating functions according to the concrete contract
below. Assert alias identity only where contracts match; assert typed-delegate signatures and
frozen outputs elsewhere. Do not leave dormant duplicate policy bodies. Keep the feature protocol and the
concrete DTO distinct because they serve different consumers; do not invent a provider abstraction.

Before consolidation, prove equivalence beyond normalized AST: inventory all loaded global names
and bound values, parameter/default/return contracts, evaluated type hints, and real callers.
The current concrete/protocol feature parameter annotations are an actual difference for four
helpers; preserve that observable difference with tiny typed delegating compatibility functions
in the canonical scoring owner where necessary, while sharing one arithmetic/predicate body.
`_rounded_boosts` has identical Mapping annotations and can be one direct alias. Do not assert
cross-module function identity for typed compatibility delegates; assert their exact original
signature/type hints and equal behavior instead. No caller-defined global or mutable registry is
involved in the five arithmetic bodies: current loaded names are only `len`/`min`, `round`/`float`,
or `bool` plus the feature parameter. Confirm that from AST and original namespace before edits.

Canonical DTO module becomes benchmark-owned; retain pre-change pickles for both contribution/plan
and concrete feature/score classes through explicit old aliases, and test dataclass/type hints.
Canonical moved function modules change openly; names, qualnames, signatures, defaults, annotations,
docstrings and old function-pickle resolution stay covered. Any real difference found during the
global binding/contract inventory takes precedence over a desire to deduplicate.

### Frozen behavior before source edits

1. Record both old module namespaces/signatures/defaults/fields/annotations and legacy DTO pickles.
2. Instrument the existing candidate score entrypoint before test collection, capture every feature
   input and complete final score/signals/policy diagnostics observed in current rerank-policy,
   source-grounding and evidence tests. Replay as explicit JSON vectors against untouched base.
   Also freeze raw contribution plans, signal overwrite order and total raw score.
3. Add deliberately explicit vectors for 15 individual policies, empty/default policy selection,
   caller-supplied policy order and duplicate signal-key overwrite, scores exactly on either side
   of locality/coverage/cap thresholds, unmeasured locality zero, precise source refs, broad/stale/
   missing-role cases, all temporal directions and source grounding, and near-boundary rounding.
   Inputs are independent of output code. Freeze raw numeric outputs and full ordered reasons.
4. Add full rerank consumer input/output examples to ensure equal scores retain tie order and
   `RetrievedMemory` metadata/boost signals are identical; this is a scorer extraction, not merely
   a sum check. Frozen fixtures are captured on current main before moving either production file.

### Focused gates

* Replay all frozen vectors through old and new public APIs, including arbitrary structural
  feature objects satisfying protocol and caller-supplied policies. Existing rerank-policy,
  candidate/evidence/source-grounding tests, exact actual rerank consumer results, policy ordering,
  legacy pickles/type identity and explicit aliases/typed delegates.
* AST boundary proof enforces stdlib/own-subpackage imports only for this capsule; zero new product
  import edges. Verify five duplicated bodies have one implementation, with contract-appropriate
  aliases or typed delegates at existing paths.
* Extend five-wheel/three-context install proof to standalone concrete feature construction and
  end-to-end scoring from frozen vectors; server/bundle legacy aliases/pickles and real old score
  entrypoint must match. Check installed paths and target-only namespace origins.
  Never assert hardcoded imported-module totals: a peer's approved core lazy exports can change
  module counts without violating dependency isolation, object identity or namespace origin.
* Existing source/runtime identity and RECORD tests plus nested new scorer module digest mutation;
  no guards weakened. Root ratchets actual aggregate benchmark lines and removes oversized policies
  baseline entry. Exact current-tree and base-ref file-size checks; lint changed files.

Exact shared ratchet proposal for R2: remove baseline key ending
`infinity_context_server/memory_comparison_rerank_policies.py` (1,726); score module has no oversized
entry. Lower rerank caller key only if smaller. Keep debt file cap 483. Given the measured R1 line
cap `R1`, new cap is `R1 - 1726 - 675 + actual_policies_facade_lines + actual_score_facade_lines +
actual_rerank_line_delta`. Root commits the exact measured integer. No core debt change is expected.

Estimated implementation + verification: 1.5-2.5 hours, ~2,500-2,800 new/moved production LOC,
~2,100-2,300 server lines removed, 250-450 focused test/generator LOC plus JSON vectors.

## Exact evidence, ownership and validation scope — round-1 fixes

This section makes the earlier gate descriptions executable and controls their minimum scope.
All commands run from this worktree with the shared frozen interpreter and an explicit worktree
package path, never editable-install fallback to the main checkout:

```bash
PYTHON=/workspace/scratch/b6182bae50e9/infinity-context/.venv/bin/python
export PYTHONPATH="$PWD/packages/infinity_context_core:$PWD/packages/infinity_context_contracts:$PWD/packages/infinity_context_adapters:$PWD/packages/infinity_context_server:$PWD/packages/infinity_context_benchmarks:$PWD/packages/infinity_context_runtime_bridge:$PWD/packages/infinity_context_sdk:$PWD/packages/infinity_context_mcp:$PWD/packages/infinity_context_cli:$PWD/tests"
```

### Exact new or modified verification files

R1 creates `scripts/freeze_benchmark_retrieval_intent.py` (<=600 LOC),
`scripts/benchmark_policy_contract_inventory.py` (shared inventory utility, <=450 LOC),
`tests/unit/test_benchmark_retrieval_intent_contract.py` (<=750 LOC), and
`tests/architecture/test_benchmark_policy_ownership.py` (<=350 LOC). Fixtures are in
`tests/fixtures/benchmark_retrieval_intent/`: `ownership.json`, `contract.json`, and ordered case
JSON files. R2 creates `scripts/freeze_benchmark_rerank_policy.py` (<=650 LOC),
`tests/unit/test_benchmark_rerank_policy_contract.py` (<=800 LOC), and fixtures in
`tests/fixtures/benchmark_rerank_policy/` with the same manifest/contract/case structure. R2 extends
the shared inventory utility and architecture guard only where its independent capsule needs it.

Both slices modify `scripts/smoke_benchmark_package_wheels.py` and
`tests/unit/test_benchmark_build_identity.py`; these are owned verification scope. The build-identity
test gains actual nested intent/scoring policy path mutations, preserving its existing RECORD and
shadow-import rejection checks. No modifications to `build_identity.py` are planned. No new test
file may exceed 1,000 LOC; split characterization tests by contract responsibility if necessary,
and keep fixture data outside source tests.

### Executable owner / export / free-global manifest

Before moving a source definition, `ownership.json` records every supported non-dunder legacy
binding, its original kind/name/qualname/module, its exact final owner, and one of public API,
compatibility-only definition/constant, or imported compatibility binding. Canonical public
`__all__` exposes only four intent DTOs and the six inference operations for R1; R2 exposes the
feature/score/contribution/plan DTOs and protocols, 15 policy classes, and the two scorer operations.
Helpers and implementation constants are explicitly imported from their owning internal modules
by old facades; they are not advertised by canonical public `__all__`. No duplicate implementation
or undeclared facade-only helper is permitted.

The inventory utility derives loaded global names from code/AST (including class methods and
comprehension code objects), resolves every original binding, and records expected final bindings.
Contract tests check each moved callable's `__globals__` and resolved annotations against that
manifest, comparing object identity for relocated canonical objects/imports, primitive/container
values for constants, and explicit typed-delegate targets for the four concrete/protocol helper
differences. Exclude function arguments, locals and builtins from cross-owner binding requirements,
but prove builtin lookup still resolves to the original builtin. Check complete supported old
namespace equality: no missing/extra non-dunder names relative to the frozen inventory. Intent
facet registry order and default policy registry order receive independent assertions. No support
is added for assigning a replacement into an old facade and expecting another module's globals
to change; the observed supported policy-injection parameter remains explicit.

R1's six top-level operations are infer_time_intent_kind, infer_relation_intents,
infer_evidence_need, infer_bundle_evidence_roles, merge_relation_evidence_needs and infer_risk_flags.
Existing DTO diagnostic/profile methods remain methods rather than new top-level exports.

Before-source fixture capture commands, run only after root release on unchanged production:

```bash
$PYTHON scripts/freeze_benchmark_retrieval_intent.py --base-sha b0b87bd774f93c2bca9bec14c0efc072a2ba2de8 --output tests/fixtures/benchmark_retrieval_intent
$PYTHON scripts/freeze_benchmark_rerank_policy.py --base-sha b0b87bd774f93c2bca9bec14c0efc072a2ba2de8 --output tests/fixtures/benchmark_rerank_policy
```

Each capture checks the original source blobs against the pinned base, records its source SHA and
input/output coverage inventory, and refuses changed production. R2 capture remains against its
unchanged scorer source on the reviewed R1 integration base; immutable original source blobs are
still pinned to main. Original sources, rather than the current checkout's overall HEAD, determine
the oracle. Tests/generators/fixtures are committed as the evidence portion before source moves;
expected outputs are not regenerated after relocation.

### R1 exact minimum focused commands

```bash
$PYTHON -m pytest -q tests/unit/test_benchmark_retrieval_intent_contract.py tests/unit/test_memory_comparison_relation_support.py tests/unit/test_memory_comparison_query_plan.py tests/unit/test_memory_comparison_evidence.py tests/unit/test_memory_comparison_source_grounding_rerank.py tests/unit/test_memory_comparison_benchmark.py
$PYTHON -m pytest -q tests/architecture/test_benchmark_policy_ownership.py tests/architecture/test_benchmark_bounded_context_boundaries.py tests/architecture/test_memory_boundaries.py tests/unit/test_benchmark_build_identity.py
$PYTHON scripts/smoke_benchmark_package_wheels.py --output /tmp/infinity-runtime-r1-wheels
```

The source-grounding file calls real `benchmark_rerank_memories`; benchmark/evidence files exercise
the server intent consumer and actual evidence role propagation. Frozen tests compare complete
consumer results and direct lower-level inference operations. Architecture and identity commands
cover package edges, executable owner inventories, source/runtime hashes, RECORD absence and
shadow imports. Wheel command builds the existing five wheels and runs all three isolated
installations, not an alternative source-tree smoke. Root schedules build temp use and retains
compact report evidence while disposing reproducible staging/install trees after review.

### R2 exact minimum focused commands

```bash
$PYTHON -m pytest -q tests/unit/test_benchmark_rerank_policy_contract.py tests/unit/test_memory_comparison_rerank_policy.py tests/unit/test_memory_comparison_source_grounding_rerank.py tests/unit/test_memory_comparison_evidence.py tests/unit/test_memory_comparison_temporal_grounding.py tests/unit/test_memory_comparison_answer_context_precision.py tests/unit/test_memory_comparison_benchmark.py
$PYTHON -m pytest -q tests/architecture/test_benchmark_policy_ownership.py tests/architecture/test_benchmark_bounded_context_boundaries.py tests/architecture/test_memory_boundaries.py tests/unit/test_benchmark_build_identity.py
$PYTHON scripts/smoke_benchmark_package_wheels.py --output /tmp/infinity-runtime-r2-wheels
```

For each slice run focused ruff on every changed `.py`, `git diff --check`, and the root-owned
exact current-tree/base-ref file-size and measured debt ratchet gates after root applies their
shared-file edits. Full architecture runs once per slice only after focused fixes settle.
Additional testing is justified by a concrete uncovered dependency or risk, not a broad rerun.
No process/API/worker gate runs without required escalation; guard weakening is prohibited.

### Explicit round-1 dispositions

* Core R-C1: accepted; exact paths/commands added above, and lower-level standalone intent replay
  is distinguished from the server-owned `query_retrieval_intent` consumer.
* Lifecycle R1: accepted; four concrete/protocol helpers use typed delegates preserving signature
  differences, while exact-contract `_rounded_boosts` uses an alias. All contradictory blanket
  alias-identity wording is replaced.
* Lifecycle R2: accepted; exact scripts/fixture/tests/architecture/identity/wheel ownership and
  commands are named above. New modules have explicit size limits.
* Lifecycle R3: accepted; executable final-owner/visibility/free-global inventory, narrow canonical
  `__all__`, complete supported old namespace checks and supported injection semantics are explicit.

## Final integration verification, owned by root

Reuse the established exact-main baseline (11,134 unit pass / 40 skip / 6 subtests; 219 architecture;
seven exact offline evals; three actual HTTP/worker E2E; five wheels in three isolated contexts).
During each slice run affected focused gates and full architecture once. After both slices and
peer integration, root chooses the one combined full unit run, exact seven offline eval comparisons,
and actual HTTP/worker composition checks needed for merged release evidence. Process/runtime/API
checks require proper sandbox escalation because namespace identity is intentional. No paid/live
provider calls or provider canaries are a structural gate.

## Stop / revise conditions

If frozen pre-source outputs reveal behavior drift, stop extraction and fix it against the frozen
oracle. If complete compatibility requires cycles or hidden forwarding, revise the package seam
instead of adding forwarding machinery. If any proposed file approaches 1,000 LOC, split by its
existing policy reason to change and re-review that responsibility mapping. Do not increase debt
ceilings or install requirements. The exact #91 exclusions have been read from root's shared
`excluded-pr91.txt`; proposed source scope has no intersection and remains subject to that list.
