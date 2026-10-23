# Round 1 core plan critique — runtime owner

Reviewed core-plan.md and actual base source/test callers at
`b0b87bd774f93c2bca9bec14c0efc072a2ba2de8`. Read-only; no tests/source changes.
Decision: **revise before round 2**, with both architectural directions supported.

## Verified architectural value

Core-A addresses real duplicate policy authority rather than merely splitting a large file.
The 3,681-line facade repeats dedupe, BM25, query relevance, requirements, evidence and domain
policies already present in bounded owners. The current facade and owners are not equivalent:
the facade has richer exact-source body selection, stricter plan-aware relevance, and other
evolved policy. Choosing the current production facade as oracle while retaining distinct basic
canonical-fact semantics is appropriate. Existing five monkeypatch seams in the plan match real
tests: `query_terms`, `query_term_frequency`, `text_variant_profile`, `best_query_relevance`, and
`normalize_context_diagnostics`. The shared cached expansion callable and no-op identity are
observable and correctly included. An explicit acyclic consolidation in the legacy adapter graph
is reasonable under ADR-0007; do not relocate it to shared_kernel to manufacture a layer claim.

Core-B fixes actual eager initialization in both root and application package initializers. Static
mapping -> exact original object, cached only on demand, preserves identities better than proxies.
A small technical resolver shared by two real consumers is justified. Complete import closures,
real module identities, legitimate error propagation and explicit star-import behavior provide
useful evidence without fragile timing or imported-module count assertions.

## Required plan fixes

### C1 — resolve moved DTO/name/metadata policy before production edits

Core-A specifies callable/global inventories but does not yet give a concrete preservation policy
for the moved private dataclasses or the proposed `_RequirementCoverageSignals` alias. Actual
facade classes are `_Bm25Document`, `_Bm25PreparedItem`, `_Bm25QueryMatch`,
`_DeterministicRerankSignals`, `_RequirementCoverageSignals`, and `_SamePersonTopicProfile`.
The existing coverage owner class is named `RequirementCoverageSignals`: its fields/properties
match, but its name/module/class identity differ. Aliasing it changes the observable `__name__`,
repr and newly emitted pickle path at the old facade attribute even if numerical behavior matches.
The plan leaves whether aliasing is sufficient to a future inventory; make that decision reviewable
now rather than treating it as an implementation detail after approval.

Required addition: state canonical class/function module migration and name/qualname policy for
each family; capture pre-source representative old class/instance/function pickles plus fields,
defaults and evaluated hints; verify old pickle resolution and intended new canonical identities.
If coverage naming changes intentionally, declare that exact private metadata change and test it;
otherwise keep a single canonical class with the original name and expose the alternate alias.
No `__module__` assignment or duplicated DTO implementation is requested.

### C2 — name the direct-owner integration gates that the proposed ranking globs omit

The plan correctly warns that the basic canonical-fact selector differs from the plan-aware
facade. That distinction has a real production caller:
`context_canonical_fact_retrieval.py` imports the existing query-relevance owner directly.
`tests/unit/test_context_canonical_fact_retrieval.py` must therefore be an explicit gate, not left
to the `test_context_*ranking*.py` shell glob or optional dependency-map follow-up. The existing
`tests/unit/test_context_ranked_evidence_paired_reservation.py` directly imports
`context_rank_dedupe.dedupe_rank_items` and is also omitted by those globs. Add it explicitly.

Capture existing direct-owner public behavior before reconciling those owners, in addition to
facade golden outputs, and record each direct caller's semantic policy choice. This does not mean
preserving obsolete algorithm duplication: share primitives, keep distinct named operations when
the direct caller requires genuinely different semantics. Add the two exact test paths to the
focused integration command and freeze basic selector output/tie behavior at least once.

## Advisory corrections

* `context_keyword_ranking.py` already exists and is tracked at 178 LOC. Mark it as an existing
  destination to reconcile, not a new file. This reinforces the actual DRY value of the slice.
* The deterministic signal owner is estimated at 850–990 LOC; keep the stated stop/review rule if
  final constants/imports push it near 1,000. Splitting only enough lines to pass is not desirable.
* Existing `context_artifact_evidence.py` imports the ranking facade's
  `query_expansion_reason_priority`. It is outside the proposed owner DAG, so this is not currently
  a cycle; ensure no new lower owner imports artifact-evidence orchestration. The direction gate
  should inspect transitive dependency chains where practical, not just direct facade imports.
* For core-B, record whether root/application non-advertised imported module attributes are out of
  compatibility scope. Existing plan preserves the advertised 31/267 exports and four feature
  aliases, which is a reasonable bounded contract; do not accidentally assert the entire eager
  `vars(module)` namespace must remain initialized.

No observed core-B blocking design defect. Approve both directions after the above concrete
Core-A evidence/metadata clarifications receive round-2 review.
