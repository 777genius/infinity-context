# Core plan round 1 — independent lifecycle/persistence critique

Reviewer: lifecycle owner. Reviewed `core-plan.md` / `core-audit.md` at pinned base `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8` against actual source, imports and tests. No source edits/tests performed. Decision: **revise before round 2**; architectural direction is supported.

## Verified value and already sound boundaries

The 3681-line ranking module really owns multiple full algorithms while bounded modules contain inactive/drifted copies. Existing canonical fact retrieval imports the basic rank-key functions from `context_query_relevance_ranking`, so retaining its semantics separately from the richer strict/plan-aware selector is necessary. The six observed monkeypatch seams in `test_context_ranking.py` match the plan, including cached query terms and late-bound normalization/relevance. The plan correctly uses current main as oracle, avoids DTO conflation, and keeps previous-wave signal ownership. Demand-loading the two package initializers removes actual parent-package import coupling, and a tiny shared technical resolver has two real consumers under ADR-0007.

## Required fixes

### C1 — keyword owner is existing debt, not a new module; reconcile it explicitly

`application/context_keyword_ranking.py` already exists (178 LOC), and contains all four keyword functions plus policy constants. The plan labels it “new” and the audit's shadow-owner table omits it. Actual source has a full duplicate of the current facade's keyword scoring/source boost/cap path, including `_PRECISE_EVIDENCE_SOURCE_REASONS`, suffix precedence, activity thresholds and reason-specific caps. Treating it as new obscures exactly the duplicate authority this PR promises to remove.

Fix: inventory this existing owner and compare its four functions/constants with current ranking before wiring; state current-main-wins behavior for any drift. Record the destination as an existing owner. Include the existing keyword caller tests from `tests/unit/test_context_query_expansion.py` (a focused `-k 'keyword_chunk_score'` selection is sufficient if full file is needlessly broad) or explain which existing full-output fixtures cover those actual callers. Do not create another keyword owner or silently overwrite an unreviewed implementation.

### C2 — basic canonical fact selection is a real changed-module consumer and needs an exact gate

`context_canonical_fact_retrieval.py` imports `query_reason_priority_for_relevance` and `query_relevance_rank_key` from the module being expanded. Its dependency does not appear in the listed ranking glob or packer/citation tests. This path chooses canonical fact candidates and winning reason provenance before downstream ranking. A synthetic strict-selector fixture alone cannot prove that the basic selector's consumer is unchanged.

Fix: explicitly include `tests/unit/test_context_canonical_fact_retrieval.py` in the post-change focused suite and characterize at least one consumer outcome before production work. Existing cases include domain-specific derived winner, protected original head, strong/weak derived admission and fair lane selection. This does not require modifying PR #91 collectors/query files.

### C3 — resolve private coverage DTO alias behavior before promising exact exported-object/name compatibility

The two coverage dataclasses have matching fields/property bodies but different names and defining modules: ranking `_RequirementCoverageSignals` versus existing owner `RequirementCoverageSignals`. Aliasing is a reasonable consolidation, but an alias changes observable `__name__`, repr/class identity and pickle canonical path for old imports. The plan currently leaves this to an “inventory will determine” clause while elsewhere promising exact exported object/name inventory.

Fix: explicitly classify this underscore DTO as private compatibility with unchanged fields/value behavior and old alias/pickle resolution where needed, or preserve any actually supported identity/name contract with a minimal typed boundary. State which identity is canonical after the move and add the corresponding expectation to the pre-source contract record. Do not keep two equal DTO implementations just to avoid deciding the boundary.

## Nonblocking implementation cautions

The planned deterministic policy owner at 850–990 LOC has little margin. Retain a coherent signal assembly even if large; if actual imports/constants exceed the hard cap, re-review a responsibility split before writing another near-limit helper bucket. Preserve no-op item/tuple identity and malformed/bool diagnostic behavior as planned. Core-B's complete isolated import closure and genuine evaluated hints/pickle records are stronger than module-count benchmarks; keep them and use explicit worktree PYTHONPATH in subprocesses.

No other blocker found in core-B. Do not implement either slice until both independent critics' round-2 release.
