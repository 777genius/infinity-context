# Wave 2 runtime / benchmark boundary audit

Owner: runtime. Worktree: `worktrees/arch-runtime`. Branch: `refactor/architecture-runtime-20261023`.

Audited base: `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8` (current main).
Status: read-only production audit; implementation requires two critics, two rounds, and incorporated fixes.

## Governing decisions read

`AGENTS.md`, Core Lite source-of-truth plan, global architecture plan, client integration plan,
architecture/trust model, accepted ADR-0001, ADR-0007, BOTH ADR-0008 documents, and ADR-0009.
The strict package rule remains benchmark -> public product contracts only, never benchmark ->
server/adapters/core.application. Server owns delivery/composition, not benchmark question policy.
No provider/scoring, lifecycle, schema, authorization, or engine changes are in scope.

## Prioritized findings from actual source

### 1. Benchmark question interpretation is still owned by product serving

`packages/infinity_context_server/infinity_context_server/memory_comparison_intent.py` is 2,925
lines, with stdlib-only imports. It owns four immutable intent DTOs, temporal interpretation,
31 ordered relation facet configurations, question predicates, evidence requirements, evidence
bundle roles, risk flags, and stable diagnostic rendering. These are benchmark retrieval policies,
not HTTP or composition responsibilities.

Actual direct production consumers:

* `memory_comparison_rerank.py`: the four intent concepts and inference operations, including
  query intent construction that downstream query plans and candidate scoring consume.
* `memory_comparison_evidence.py`: `infer_bundle_evidence_roles`.

The focused direct test consumer is `test_memory_comparison_relation_support.py`; question
interpretation also has substantial indirect coverage in benchmark/rerank/evidence tests.
There are no observed monkeypatches of intent module helpers/constants in packages/tests/scripts.
The AST call graph has clean acyclic seams: immutable contracts; temporal classification;
profile predicates; event/goal predicates; comparison/count predicates; relation classification;
evidence requirements; facet configuration. Relation ordering is observable and must be frozen.

Moving only DTOs would leave ownership wrong. Moving the whole question-policy capsule into the
already installable benchmark package removes an inward ownership mistake and lets query/evidence
callers use a single standalone policy owner. Merely dividing this module inside server would not
achieve the architectural objective.

### 2. Candidate scoring is split between two server policy owners with real duplication

`memory_comparison_rerank_policies.py` is 1,726 lines and imports stdlib only. It owns the feature
protocol, contribution/plan DTOs, 15 policy objects, grounding predicates, ordered defaults, and
contribution aggregation. `memory_comparison_rerank_policy.py` is 675 lines and also imports only
stdlib plus the former module. It owns concrete feature/score DTOs, final score caps, provenance
safety caps, and public score rendering. `memory_comparison_rerank.py` consumes the latter.

Five functions in the latter duplicate policies functions exactly after normalizing the feature
type annotation: `_relation_boost`, `_relation_coverage_boost`,
`_focused_relation_density_boost`, `_rounded_boosts`, and `_stale_only_current_state_evidence`.
The first three have zero local call sites in the score module; the other two are active.
All five can retain legacy imports as aliases to one canonical helper instead of maintaining
two implementations. No policy arithmetic should be rewritten during that consolidation.

This entire candidate score boundary is independently extractable: no provider, HTTP, persistence,
core application, or adapter dependency exists. Keeping final caps in server after extracting
contribution policies would leave an arbitrary half-boundary; move both together.

The actual direct tests are `test_memory_comparison_rerank_policy.py` (many explicit grounded,
ungrounded, stale, temporal, count/list, speaker, source-grounding and role support cases).
Indirect consumers include query/rerank, source-grounding, evidence bundle and benchmark tests.
No observed monkeypatches target these policy helpers/default registry. Custom policy injection
through `score_rerank_policy_contributions(..., policies=...)` is an explicit supported seam.

### 3. Composition / evaluation alternatives are larger or less isolated for this wave

`composition.py` is 948 lines and `build_container` occupies 626 lines. It imports product
composition plus benchmark-managed admission and run lifecycle. Separating that wiring needs
cross-owner lifecycle agreement and cannot safely be reduced to moving imports. It is deferred.

`memory_comparison_rerank.py` is 3,209 lines and mixes query decomposition, intent construction,
temporal ordering, source grounding, and candidate feature/scoring orchestration. Its direct core
application imports (`context_answer_unit_shapes`, `context_source_grounding`) prohibit moving it
to benchmarks under current strict boundaries. The two selected slices reduce its inward policy
ownership without pretending the remaining module is standalone.

`memory_comparison_candidate_features.py` is 2,014 lines and also imports core application
answer shapes/count cardinality/speaker attribution. `eval.py` is 3,066 lines and composes product
FastAPI app setup, seeding, provider canaries, benchmark CLIs and suite dispatch. Those need
different contracts and broad API/eval coverage; they are deferred, not hidden via facades.

## Ratchet evidence

The checked-in architecture gate records server benchmark debt ceilings 483 files / 208,182 lines,
core benchmark debt 21 files / 7,205 lines. The global file-size baseline contains entries for
intent (2,925) and policies (1,726). Extraction retains the existing server module paths as small
explicit compatibility exports; they continue to count as debt. No relabeling/classification
evasion is proposed. Server debt file count stays 483; aggregate lines materially decline by
approximately 4,800-5,000; two global oversized entries disappear (102 -> 100 absent peer changes).
Exact resulting counts must be measured after each slice and lowered by the root's shared gate edit.

## Existing package/runtime proof to extend

`scripts/smoke_benchmark_package_wheels.py` already builds five wheels from a staged source tree
and runs `-I -S` isolated standalone, server and bundle installations. Its standalone context has
core+benchmarks only and asserts server/adapters cannot be found; it checks module paths, metadata,
legacy pickles and real policy results. Extend this proof for moved intent/scoring rather than
substituting source-tree imports for installation proof.

`tests/unit/test_benchmark_build_identity.py` proves benchmark source and installed RECORD changes
affect runtime identity, and rejects missing/shadow package roots. Existing build identity already
includes benchmark package runtime modules. Extend assertions for the real new subpackages and
unchanged fail-closed behavior; do not weaken namespace identity guards to run tests in sandbox.

## Ownership / exclusions

No edits to core context ranking, canonical lifecycle/persistence, query_execution,
context_collectors, or vector_candidates. Root's complete #91 list has been read at
`/workspace/scratch/b6182bae50e9/plans/wave2/excluded-pr91.txt`; none intersects proposed source scope.
Root owns GitHub publication/merging and shared debt/file-size gate edits. This worktree owns only
the two benchmark capsules, three old modules, their direct benchmark callers, focused fixture and
test additions, and the agreed wheel smoke extension. Baseline unit/architecture/eval/HTTP/worker/
five-wheel checks already passed on this exact main and are reused, not redundantly rerun now.
