# Runtime plan round 1 — independent lifecycle/persistence critique

Reviewer: lifecycle owner. Reviewed `runtime-plan.md`, accepted benchmark bounded-context ADR 0008, actual intent/scoring modules, their production callers, package metadata, wheel smoke and existing tests at pinned base `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`. No source edits/tests performed. Decision: **revise before round 2**; both architectural directions are justified.

## Verified value and sound decisions

The intent module is provider-free/stdlib-only but currently server-owned; two real server consumers import it. Complete scorer separation is likewise valid: concrete feature/score DTO/final cap logic live in `memory_comparison_rerank_policy.py`, with contribution protocol/policies in `memory_comparison_rerank_policies.py`. Moving both avoids leaving an apparent benchmark scorer dependent on server. Existing benchmark distribution already depends on core while installed smoke uses target-only `-I -S` namespaces; the new pure subpackages can be proven independently without new requirements. Keeping concrete feature DTO and structural feature protocol distinct is correct.

Exact default policy order and facets require the planned ordered fixtures. Public legacy class aliases plus old pickle samples are a good compatibility boundary; no artificial `__module__` mutation or global-forwarding machinery is needed.

## Required fixes

### R1 — duplicate helper bodies have different annotations; define the compatibility boundary explicitly

At least `_relation_boost`, `_relation_coverage_boost`, `_focused_relation_density_boost` and `_stale_only_current_state_evidence` are body-equivalent but signatures annotate `BenchmarkRerankFeatures` in the final-score module and `RerankPolicyFeatures` in the contribution module. Therefore these are not completely equivalent function definitions. One identical alias at both paths cannot preserve both evaluated parameter annotations. The plan simultaneously promises recording signatures/annotations and consolidating five helpers with alias identity.

Fix: list the exact five helpers and compare bodies, signatures/defaults and free globals. Decide explicitly that private helper annotations become the owning structural protocol while public scorer/DTO hints remain exact, and freeze that intended compatibility classification; alternatively use minimal legacy typed wrappers for any actually supported public annotation contract. Either is coherent. Do not discover this as an unexplained fixture failure or claim signatures unchanged when only bodies match. No reason to duplicate the algorithms.

### R2 — focused gates and verification file scope need exact executable names before production release

Both slices list categories of tests and “existing runtime digest/RECORD focused tests” without exact paths/commands, and new test/generator files are not named. The user asks for a concrete independently reviewed plan before each direction, and these moves change package ownership/runtime source identity. Reviewers must be able to tell which consumers and integrity gates will actually run and which shared files the owner intends to edit.

Fix: name the bounded fixture generators, fixture directories, compatibility/replay test modules and architecture guard module(s); enumerate the initial existing focused test commands per slice, including actual `test_memory_comparison_relation_support.py`, `test_memory_comparison_query_plan.py`, `test_memory_comparison_evidence.py`, `test_memory_comparison_source_grounding_rerank.py`, `test_memory_comparison_rerank_policy.py` where applicable, plus exact source/runtime identity and RECORD gates. Name modifications to `scripts/smoke_benchmark_package_wheels.py` explicitly as owned verification scope. Give the installed smoke command and exact relevant test paths; this is not a request for another full suite.

### R3 — public function/constant export ownership cannot remain an informal namespace promise

Intent is 2925 LOC with many interdependent predicate/constants, while the plan gives approximate semantic groups and says names “may be tightened.” It also promises every old helper/imported stdlib name. That is possible with explicit aliases, but the public capsule and compatibility facade could accidentally become a global bag unless the export inventory is a concrete gate.

Fix: state a pre-source checked-in manifest of all legacy defined names, their final owners and classifications (public API versus compatibility-only helper/import). Keep canonical public `__all__` intentionally scoped; compatibility-only names may be imported explicitly by the old module without being advertised by the new public API. Require an exact no-missing/no-extra legacy namespace comparison for the supported inventory and cross-check every moved callable's free globals against its final module. The existing plan's general namespace capture is a good start; make ownership and visibility executable, rather than inferring them from frozen end-to-end outputs.

## Nonblocking cautions

The final scorer uses the contribution scorer via an imported global, and the contribution scorer accepts an ordered `policies=` list. Preserve the latter including empty-sequence fallback and duplicate signal-key overwrite as planned. Helper-global monkeypatches are private and no observed contract justifies forwarding them. Keep the modern canonical pickle path change explicit; old aliases must still decode old samples in the installed server/bundle contexts. Root should ratchet aggregate debt and oversized baseline entries, leaving ownership files out of concurrent edits.

Do not implement until both independent critics approve the revised concrete slice plans in round 2.
