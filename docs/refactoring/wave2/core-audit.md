# Wave 2 core architecture audit

Base: `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`.
Worktree: `/workspace/scratch/b6182bae50e9/worktrees/arch-core`.
Branch: `refactor/architecture-core-20261023`.
Status: READ-ONLY SOURCE AUDIT COMPLETE; implementation awaits two independent critics, two rounds.

## Authority and exclusions

Read `AGENTS.md`, Core Lite source of truth, global/client reference plans, architecture/trust model, ADR-0001, accepted ADR-0007, ADR-0008 monotonic budgets, ADR-0009, ADR-0011, and ADR-0013. Core cannot import infrastructure; canonical hydration, lifecycle, scope and provider trust policies stay unchanged. Existing explicit feature boundary exceptions must not expand. Flat legacy context application modules remain compatibility adapters; this wave does not pretend they are feature-domain code.

Exclude PR #91 paths `context_collectors.py`, `context_query_execution.py`, `context_vector_candidates.py`, and their owned tests. Do not change previous-wave domain signal or answer-support boundaries, combine distinct DomainRerankSignal contracts, alter SDK artifacts, or weaken runtime/process identity guards. Root owns publishing, shared gate ratchets and final merges. No provider calls. Baseline verification supplied by root is reused: 11,134 unit passed, 40 skipped, 6 subtests; 219 architecture; seven deterministic evals exact; three actual HTTP/worker E2E.

## Highest-value finding 1: duplicate live and shadow ranking authorities

`application/context_ranking.py` is 3,681 LOC. It owns dedupe/body selection/source reference merge, reciprocal rank fusion, BM25, query relevance/keyword scoring, requirement boosts, deterministic rerank evidence, domain noise, same-person topic disambiguation and diagnostics mutation.

Bounded modules already exist, but the ranking facade never imports them:

| Existing prospective owner | LOC | Current status and drift |
| --- | ---: | --- |
| context_rank_dedupe.py | 171 | Shadow duplicate; lacks current reason priority and exact source sibling body selection additions. |
| context_rank_fusion.py | 191 | Shadow duplicate; fusion scorer/helper bodies match; minor expression rearrangement. |
| context_bm25_ranking.py | 450 | Shadow duplicate with existing explicit callback seams and cache helpers. |
| context_keyword_ranking.py | 178 | Existing shadow owner of all four keyword/reason boost/cap functions; requires current-source comparison before wiring. |
| context_query_relevance_ranking.py | 76 | Used by canonical fact retrieval, while ranking has a richer independent variant. Strict query filtering, plan-specific priority and false friend exclusions differ. |
| context_anchor_intent_ranking.py | 84 | Existing shadow query-anchor boost/diagnostic owner, absent from facade import graph. |
| context_requirement_ranking.py | 181 | Shadow duplicate; lacks current typed answer-unit mismatch handling. |
| context_requirement_signals.py | 101 | Parallel coverage DTO/helper implementation, consumed by evidence helper module. |
| context_rerank_relevance.py | 131 | Shadow diagnostic relevance bridge; multiple helper bodies exactly match current ranking. |
| context_rerank_evidence_signals.py | 400 | Shadow evidence owner; numerous exact duplicate helper bodies, but citation/source quote and some reason handling have evolved in ranking. |
| context_rerank_domain_heuristics.py | 433 | Shadow domain noise/grounding owner; temporal metadata/source quote behavior needs current-source reconciliation. |

This is more serious than file size: edits to one apparent policy owner do not update actual ranking. Switching to the existing helpers blindly would regress current behavior. AST body comparison confirmed exact copies for fusion scoring, diagnostic score conversion, coverage ratios, localized evidence, canonical anchor summary evidence, artifact inventory evidence and other helpers. Source callsite search shows the shadow modules have no production consumers except the documented query relevance and evidence/coverage links. One direct test consumer also imports `context_rank_dedupe.dedupe_rank_items` in paired-evidence reservation tests, so its typed role-membership merge behavior is an explicit integration gate.

Concrete current source boundaries: public ranking functions at lines 534–794; relevance/keyword at 798–1037; dedupe at 1040–1229; BM25 DTOs/helpers at 1233–1587; requirement ranking at 1632–1786; deterministic assembly/mutation at 1789–2530; same-person disambiguation at 2541–2712; evidence support at 2715–3099; relevance bridge at 3102–3206; noise/temporal/dialogue helpers at 3209–3523; requirement signals at 3526–3623; fusion mutation at 3626–3681.

Compatibility is real: `tests/unit/test_context_ranking.py` monkeypatches module globals `query_term_frequency` (281–289), `query_terms` and `_query_expansion_terms_for_signature.cache_clear()` (328–349, 397–417), `text_variant_profile` (367–375), `best_query_relevance` (9714) and `normalize_context_diagnostics` (9752). Re-exporting old function objects alone would silently bypass these seams. Existing caches are observable optimization contracts. Public signatures/defaults, no-op tuple/item identity, deterministic ordering, score rounding, diagnostics reasons and exact source reference/body selection must survive.

## Highest-value finding 2: root import defeats architectural isolation

Root `__init__.py` (76 LOC) eagerly imports fact application DTOs/use cases, which initializes `application/__init__.py` (586 LOC). That package eagerly imports four feature public surfaces, collectors and essentially all legacy use cases. A static AST top-level traversal (including Python parent-package initialization) found root reachability into 500 of 640 core modules. This is static source evidence, not a runtime timing claim. Importing a feature domain or port thus begins with most legacy application code, despite source dependencies appearing clean.

Root exposes 31 advertised names and application exposes 267. These are compatibility surfaces; demand loading must return the exact defining object rather than wrappers/proxies. Feature public module exports and bundle aliases must retain identity. Explicit import manifests can preserve `__all__` insertion order, `dir`, star imports, normal submodule imports and AttributeError behavior without importing business use cases on plain package import. A small stdlib-only shared-kernel resolver is valid under ADR-0007; it holds technical mechanics only.

## Answer-support audit / deferred debt

Previous-wave orchestration remains 527 LOC and is intentionally not undone. Active support slots/patterns remain 1,209/1,267 LOC. `context_packer_answer_slots.py` (733 LOC) has no source consumers anywhere in packages/tests and duplicates some older slot/content policy; it has drifted from active support slots and inventory helpers. Therefore replacing this module with aliases would not prove equivalence. Splitting only active slots/patterns is useful future debt reduction, but it does not outrank removing duplicate ranking authorities and import-time architecture inversion. No blanket regex/table merge or new generic policy framework is justified here.

## Proposed work

1. PR core-A: make existing bounded ranking modules the single authorities, reconcile them to current main and retain a compatibility/orchestration facade <=1,000 LOC. Reduce actual duplication and gate reverse imports.
2. PR core-B: demand-load legacy root/application compatibility exports with exact object identity, backed by fresh interpreter import isolation tests. No behavior or provider/lifecycle policy changes.

Every new/repartitioned production module <=1,000 LOC; every changed frozen oversized ceiling strictly decreases or is removed. Root reconciles the shared baseline rather than parallel agents editing it blindly.
