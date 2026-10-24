# Independent implementation review — core A

Reviewed the source-stage `arch-core` working tree after immutable evidence commits `7cb90d5a`
and `7c397ce8`, against pinned main `b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`.
Decision: **approved; no blocking source or architecture finding**.

Inspected the ranking facade, existing reconciled owners, new deterministic/same-person owners,
evidence/source-quote branches, strict versus basic relevance operations, compatibility wrappers,
DTO alias policy, frozen contract tests and ownership auditor. The source now has one algorithm
owner per responsibility; the facade retains explicit callback plumbing and batch orchestration.
The six private DTO families follow the declared canonical metadata migration and old aliases.
No shared-kernel policy, reverse facade import, hidden forwarding or strategy framework is added.

The real canonical-fact caller still uses the basic selector operation, while the facade uses the
plan-aware strict/false-friend selector. Both share the intended lexical primitives without
silently exchanging semantics. BM25 facade calls pass current lexical bindings and the cached
query-expansion function at call time. Deterministic relevance and source-quote/citation branches
propagate the current `best_query_relevance` callback to actual execution. Normalization/no-op
paths preserve identity and avoid the previously observed unnecessary callback execution.

Independently executed with explicit worktree/test-support paths:

* `scripts/check_context_ranking_ownership.py`: **127 original callable bodies and 267 actual
  canonical global bindings verified**, after its explicit callback/coverage-name normalization.
* `tests/unit/test_context_ranking_policy_ownership.py` plus
  `tests/architecture/test_context_ranking_ownership_boundaries.py`: **806 passed** in 7.75s.

The architecture guard's basename intentionally differs from the unit contract file to avoid
pytest module-name collision; it checks transitive facade/artifact reachability, acyclic owners,
thin facade shape, bounded files and absence of dynamic import escape routes. I inspected it.

Initial review invocations encountered infrastructure/invocation problems (disk-backed temporary
capture unavailable, and missing explicit editable-worktree/test-support paths); corrected bounded
read-only runs passed using in-memory capture and no pytest cache. These were not source failures,
and no runtime/security guard changed. No owned source was modified during independent review.

Owner/root still provide the remaining full architecture/eval/actual E2E and ratchet evidence
required for integration. Any new semantic/callback/metadata change after this source stage needs
review of that delta.
