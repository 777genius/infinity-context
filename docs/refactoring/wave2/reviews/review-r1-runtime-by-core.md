# Runtime plan round 1 — independent core-owner critique

Reviewer: core/context owner. Pinned base `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`. Reviewed runtime plan, both intent/score/policy sources, real rerank/evidence consumers, relevant tests, wheel smoke script, package dependencies and accepted benchmark bounded-context ADR. Read-only; no tests or edits.

Decision: **both directions supported; concrete validation selection needed before round 2**. No architecture redesign or extra framework requested.

## R1 findings

The 2,925-line intent module has only stdlib dependencies; its four frozen DTOs and question-only temporal/relation/evidence policy are appropriate benchmark-owned capabilities. Actual consumers are `memory_comparison_rerank.py` and `memory_comparison_evidence.py`. Keeping their core-dependent orchestration server-owned avoids an outward package importing `core.application` and obeys accepted ADR-0008 benchmark bounded contexts.

The proposed predicate partition is feasible: AST call graph confirms time-kind calls only ordinal helper; contrast calls commonality/difference/choice helpers; event/location/current-goal share future-move predicate; causal shares direct-emotion/motivation helpers. No unavoidable cycle exists. Preserve exact facet registry order as promised; grouping facet data by domain without explicit original order would change relation diagnostics.

The actual `query_retrieval_intent` entrypoint is **not** in the moved intent file. It remains at `memory_comparison_rerank.py:2032`, building inputs through server-owned question-term machinery before invoking the moved API. The plan correctly intends a server-consumer capture, but standalone installed benchmark smoke must replay the lower-level canonical intent APIs with frozen explicit inputs rather than importing that server entrypoint. State this ownership explicitly so installed-wheel proof cannot accidentally depend on source/server availability.

## R2 findings

The current score facade is 675 lines and policies are 1,726; both are stdlib-only and belong in the benchmark package. Keeping final score caps and ordered policy composition in the same outward context removes actual serving ownership rather than merely repartitioning a file. The plan preserves the real `policies=` injection on contribution scoring and all 15 default policy positions. `RerankPolicyPlan.score_signals` is order-sensitive (`dict.update`); frozen duplicate-key overwrite and full diagnostics are correctly required.

Do not combine the structural feature protocol with concrete feature DTO. The plan correctly identifies annotation differences in four superficially equivalent helper duplicates and keeps typed delegates while deduplicating their arithmetic body. Requiring global bindings, evaluated hints, old/new pickle resolution and direct consumer snapshots addresses risks AST-normalization alone would miss.

## Required clarification R-C1 — name the exact minimum focused test commands

Both slices currently say tests are “selected by import/call graph” without listing the actual selected files/commands. That leaves the implementation/merge gate underdetermined despite a detailed extraction/evidence plan. Before round 2, record a bounded exact minimum for each slice and identify which tests supply direct consumer output coverage. Existing relevant paths include:

- `tests/unit/test_memory_comparison_relation_support.py`
- `tests/unit/test_memory_comparison_query_plan.py`
- `tests/unit/test_memory_comparison_evidence.py`
- `tests/unit/test_memory_comparison_rerank_policy.py`
- `tests/unit/test_memory_comparison_source_grounding_rerank.py`
- `tests/unit/test_memory_comparison_temporal_grounding.py`
- `tests/unit/test_memory_comparison_answer_context_precision.py`
- `tests/unit/test_memory_comparison_benchmark.py`

Select the genuinely affected subset per slice; this is not a demand to rerun all benchmark tests. Include new frozen-contract tests, the specific architecture/runtime identity/RECORD files, and the exact `scripts/smoke_benchmark_package_wheels.py` invocation/output directory. Existing wheel smoke already exercises five wheels/three contexts under `-I -S`; extend it as proposed rather than inventing a second installation harness. All API/process gates must honor required escalation, without changing guards.

## Nonblocking cautions

1. The compatibility inventory includes all defined/imported names currently discoverable; distinguish documented/observed behavior from unsupported assignment-to-legacy-alias monkeypatch semantics. No dynamic forwarding or hand-set `__module__` is justified.
2. New AST guards must inspect both imports and deliberate dynamic import escape routes, while allowing stdlib only and own capsule modules. Existing generic benchmark guard prohibits product internals but is intentionally weaker than the proposed capsule boundary.
3. A peer's approved lazy package exports will change loaded-module counts. Namespace origins and allowed import closure are valid installed-wheel assertions; fixed module totals are not.
4. Estimated test/generator LOC may be optimistic for full namespace/signature/pickle/branch evidence. Keep test modules bounded and split fixtures by responsibility if needed; do not weaken the evidence to hit an estimate.

Proceed only after both critics' round-2 approval and root release.
