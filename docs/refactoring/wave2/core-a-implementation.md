# Ranking policy ownership consolidation

Base: `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`.
Source commit: `e4ce8443`. Immutable pre-source capture: `7cb90d5a`; lossless fixture packaging cleanup: `7c397ce8`.

## Result

The old 3,681-line context ranking module repeated algorithms already present in bounded modules. Those shadow implementations had drifted: using them without reconciliation would lose exact source body selection, strict plan-aware relevance, typed answer-unit and citation/temporal behavior. This change reconciles current production behavior into the existing owners and retains explicit legacy aliases and adapters.

The facade is now 942 lines. Deterministic signal assembly is 746 lines; every other production owner is smaller, and all are below the 1,000-line hard cap. Dedupe, fusion, BM25, keyword scoring, anchor intent, requirement boosts/coverage, diagnostic relevance, evidence support, and domain heuristics each have one implementation authority. Three new modules own deterministic assembly, item mutation and same-person batch disambiguation. The basic canonical-fact relevance selector remains distinct from the richer plan-aware operation, sharing the actual ranking primitives.

Supported lexical/relevance/normalization globals are passed explicitly at call time. The original cached expansion callable still exposes `cache_clear`. Quote anchor and citation evidence receive the same selector callback as item relevance. Owners cannot directly or transitively reach the compatibility facade or artifact-evidence orchestration. No dynamic module forwarding, mutable dependency registry, feature-internal exception, provider dependency, or lifecycle/trust change was introduced. Previous-wave domain signal and answer-support boundaries remain intact.

The existing `RequirementCoverageSignals` is the one canonical coverage DTO. Historical `_RequirementCoverageSignals` imports and old pickles resolve through its alias; the private generated class name/repr and new pickle path deliberately use the canonical owner. The remaining private DTO names/qualnames remain unchanged in their bounded implementation modules. All old class, instance and function references, fields, values, signatures and evaluated annotations are checked.

## Evidence and validation

Before any production edits, 375 focused existing tests passed and captured 670 complete input/output/identity records. There are 640 distinct records after ignoring provenance labels; the other 30 remain for provenance. Deterministic gzip preserves the full 5,361,672-byte compact JSON in 189,980 bytes. Human-readable metadata records exact source blobs, compressed/uncompressed SHA-256, 127 callable contracts and six private DTO instance pickles. Expected behavior was never regenerated from changed production.

Post-change verification:

- **1,147 passed:** original ranking tests, all frozen outputs, signature/type-hint/pickle/no-op contracts, existing seven policy snapshots and the new ownership guard.
- **639 passed:** the remaining 21 affected integration files, including ranking consumers, canonical fact retrieval, direct paired-reservation dedupe, query-expansion keyword scores, citations, packing and package/feature boundary checks.
- The independent source audit verifies **127 original callable bodies**, normalizing only explicit callback plumbing and the declared coverage DTO name, and **267 actual canonical global bindings** against the immutable original source SHA.
- Ruff on all changed Python files and `git diff --check` pass.

The first frozen replay caught a provenance-helper parameter mismatch and a missing quote-selector callback. Both were corrected in source without changing the oracle. Independent runtime-owner review found no source blocker and independently reran the audit plus 806 contract/architecture tests successfully. The lifecycle-owner review and root-owned shared ratchet/release evidence are tracked separately.

The root coordinator owns removing the obsolete 3,681-line size-baseline entry, final full offline evaluations, available E2E checks, publication and merge. No paid/live provider calls are used.

## Independent review correction

The lifecycle reviewer found that the new contract test's bare helper import required adding `tests/` to `PYTHONPATH`, which the standard repository pytest invocation does not do. The import now uses the existing `tests.context_ranking_contract_support` package path. With `PYTHONPATH` removed entirely, the frozen contracts plus canonical-fact and paired-reservation consumer files pass **825 tests**. No production code or frozen expected behavior changed for this correction.

## Coordinator acceptance after independent review

Both independent implementation reviews approved the final source. The lifecycle reviewer found a standard pytest helper-import issue; commit `3f64371c` resolves it without changing production or frozen expected outputs. The standard `PYTHONPATH`-unset contract/direct-consumer gate passed 825 cases. Review reports are committed under `reviews/review-code-core-a-by-{lifecycle,runtime}.md`.

The complete architecture suite passed **222 tests in 73.27 seconds** on the final source and lowered size baseline. The obsolete 3,681-line `context_ranking.py` exception is removed; its actual 942 lines are now under the ordinary 1,000-line limit. No other oversized allowance grew. Combined-branch unit/evaluation/E2E acceptance is coordinated separately; this record does not claim hosted CI completed.
