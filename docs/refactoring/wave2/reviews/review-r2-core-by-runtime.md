# Round 2 core plan critique — runtime owner

Reviewed revised `core-plan.md` v2 against the actual source/test call sites inspected in round 1.
No source edits or tests. Base: `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`.

## Core-A — approved

Both required round-1 findings are resolved explicitly.

* The plan now names all six private DTO families and chooses one canonical class per family.
  `_RequirementCoverageSignals` deliberately becomes an alias to existing
  `RequirementCoverageSignals`, with its private repr/name/new pickle-path change declared rather
  than claimed unchanged. Old facade class/instance/function pickles, field/default/frozen/property
  behavior, evaluated hints and actual alias identities are required before/after the move.
* Existing direct-owner semantics are frozen independently from facade behavior. The basic
  canonical-fact selection keeps its distinct policy; canonical winner/protected-head/tie cases
  and paired-reservation typed role merges have explicit full-output capture. Their exact tests,
  `test_context_canonical_fact_retrieval.py` and
  `test_context_ranked_evidence_paired_reservation.py`, are mandatory integration gates.
* Existing keyword owner inventory is corrected, its actual callers/functions/constants are
  reconciled, and the direction guard now checks transitive reachability back to the ranking
  facade/artifact orchestration.

The plan has concrete architectural value: one implementation per existing responsibility, actual
late-bound callback/cache/no-op identity preservation, and no feature-boundary or source-size
exception growth. Approval is for this bounded consolidation; any change in the stated metadata,
direct-owner semantic choices, callback contracts or responsibility graph needs re-review.

## Core-B — approved

The advertised root/application `__all__` and module/bundle aliases form an explicit bounded
compatibility contract; incidental eager `vars(module)` entries are now correctly excluded.
The demand resolver returns exact original objects and keeps normal explicit submodule importing,
real import failures, pickle identity and evaluated hints. Static mapping and a small stdlib-only
technical resolver are appropriate. Fresh-process complete allowed closures test actual import
isolation without hardcoded imported-module totals or timing thresholds.

No unresolved blocking finding. Both slices remain subject to the other independent critic's
approval and root release, followed by pre-source evidence and independent implementation review.
