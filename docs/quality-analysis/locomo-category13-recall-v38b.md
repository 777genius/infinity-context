# LoCoMo category 1/3 recall diagnostic V38b

Analysis date: 2026-07-21. This checkpoint was created before any production
edit. The diagnostic is intentionally limited to four failed cases and nearby
passing controls; no medium or full benchmark is in scope.

## Decision

**Query recall is not causal in this four-case slice. Do not add
`context_query_recall_fanout.py`.** All missing evidence is already in the
baseline canonical keyword candidate union. Three cases lose it between that
union and final selection; one selects a source containing it but does not make
the target segment prompt-visible. The existing question-only query plans are
byte-for-byte identical at the baseline generator commit and the diagnostic
worktree commit.

No production or test file was changed. The only worktree change is this
diagnostic report.

The required loss labels are:

- `no_candidate`: expected evidence is absent from the candidate union;
- `candidate_not_selected`: expected evidence is a candidate but absent from
  the selected context items;
- `selected_not_rendered`: expected evidence is selected but absent from the
  rendered prompt context.

## Fixed scope and baseline

Read-only baseline root:
`/var/data/workspaces/infinity-context/.e2e-artifacts/quality-baseline-current-20260718`.
The four LoCoMo shard reports record dataset SHA-256
`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` and
generator commit `d6a856549329fd4ca1986bd86ddb0581d80c8fc4`. The diagnostic
worktree began at `44d700acc993c98a142be4485eafaca979200627`.

| Case | Capability | Question | Baseline missing evidence |
| --- | --- | --- | --- |
| `conv-26:qa:44` | `locomo_category_1` | What kind of art does Caroline make? | `D11:12` |
| `conv-26:qa:39` | `locomo_category_1` | What activities has Melanie done with her family? | `D6:4`, `D1:18` |
| `conv-41:qa:9` | `locomo_category_3` | What might John's financial status be? | `D5:5` |
| `conv-42:qa:61` | `locomo_category_3` | What Console does Nate own? | `D27:23` |

The baseline reports prove the final missing-evidence symptom and final item
identities. Candidate presence and per-query ranks were established separately
with baseline code at the recorded generator commit against the shard SQLite
files opened with `mode=ro`. No shard was copied, migrated, or mutated.

## Diagnostic method

For each failed case, compare its question decomposition and retrieval queries
with passing cases that exercise the same conversation, subject, relation, or
evidence pattern. Trace expected evidence in this order:

1. canonical source/chunk presence;
2. candidate union across the selected query plan;
3. selected context item identities;
4. rendered prompt evidence.

Stop causal analysis at the first absent boundary and assign exactly one of the
three required labels. Any candidate fanout experiment must be derived only
from the question and general linguistic rules, remain provider-neutral, and
preserve the question's subject, relation/action, and constraints.

## Boundary result

| Case / evidence | Baseline candidate proof | First loss | Direct downstream proof |
| --- | --- | --- | --- |
| `conv-26:qa:44` / `D11:12` | Candidate-union ranks 20, 24, 51, 66, and 72. `art_style_bridge` has target-bearing rows at ranks 2, 5, 8, 10, and 13. | `candidate_not_selected` | None of the 15 baseline final item ids contains `D11:12`. The current exact trace admits eight target-bearing pack candidates and renders `D11:12`, without any query-plan change. |
| `conv-26:qa:39` / `D6:4` | Candidate-union ranks 4, 32, 51, and 79. `family_museum_activity_bridge` ranks target-bearing rows 1, 2, 7, and 9. | `candidate_not_selected` | The baseline final items contain no `D6:4` evidence. The current trace puts the exact turn at guarded/pre-pack rank 5 and renders it. |
| `conv-26:qa:39` / `D1:18` | Candidate-union ranks 5, 50, and 59. `family_swimming_activity_bridge` ranks the exact turn first. | `candidate_not_selected` | Baseline `related_marker` items derived from the session observation select other markers (`D1:11` and `D1:9`), not the `D1:18` segment. The post-baseline bounded family-activity exact-turn policy selects and renders `D1:18`. |
| `conv-41:qa:9` / `D5:5` | The observation is candidate-union rank 51 and rank 1 for `decomposition_inference_support`; the exact turn is original-query rank 89. | `candidate_not_selected` | No baseline final item contains the target. On the current exact trace the target observation reaches guarded and pre-pack rank 27 (score `0.935`) but is rejected at final-selection rank 24 by `char_cap`: projected 19,375 rendered characters against the 18,000 cap. |
| `conv-42:qa:61` / `D27:23` | Candidate-union ranks 1, 7, and 44. `console_game_cover_bridge` ranks the exact turn, session chunk, and observation 1, 2, and 3. | `selected_not_rendered` | The baseline final item list selects observation `chunk_87e12724a0e4448189a4347c06a22888`. Its canonical text contains `D27:23` at character 547, but the benchmark response evidence omits `D27:23`; therefore the selected source's target segment was not rendered/projected. The current exact trace selects the exact turn and renders it. |

No case is `no_candidate`.

## Passing-neighbor query comparison

The selected query plans were generated from question text only for the four
targets and nearby passing controls. JSON produced by baseline code and current
code compared equal byte-for-byte.

| Failed baseline case | Selected query reasons | Passing controls from the same baseline | Comparison |
| --- | --- | --- | --- |
| `conv-26:qa:44` | `original_query`, `painting_inventory_bridge`, `art_style_bridge`, `decomposition_kind_type_descriptor` | `conv-26:qa:38` uses only `original_query`; `conv-26:qa:52` uses `original_query` plus `painting_inventory_bridge` | The failed case has broader, more precise fanout than both passing painting neighbors, and its precise bridge returns the target near the head. |
| `conv-26:qa:39` | Eight selected queries, including the family, museum, swimming, visual-self-care, and activity-participation routes | `conv-26:qa:16` selects six activity routes; `conv-26:qa:67` selects four family-hike routes | The failed case is already at the bounded fanout maximum and both missing activity slots are heads of dedicated routes. |
| `conv-41:qa:9` | `original_query`, `decomposition_inference_support` | `conv-41:qa:15` and `conv-41:qa:18` add a specialized inference bridge before the same generic inference route | Although it lacks a specialized bridge, the generic route ranks the target observation first and the packer receives it. Adding another route would address neither first loss nor the hard character-cap rejection. |
| `conv-42:qa:61` | `original_query`, `console_game_cover_bridge`, `decomposition_followup_task` | Passing inference neighbors `conv-42:qa:13`, `conv-42:qa:67`, and `conv-42:qa:86` select three to eight routes | The console bridge already places every target-bearing representation in its top three; loss is after selection, not fanout. |

## Four exact replays

Exactly the four allowed cases were replayed on the current worktree, using the
existing local deterministic profile (`token_budget=4000`, `max_facts=20`,
`max_chunks=50`, provider adapters disabled). No other LoCoMo case and no
medium/full benchmark was run.

| Case | Current result | Boundary detail |
| --- | --- | --- |
| `conv-26:qa:44` | pass, 3/3 refs rendered | The target has eight pack candidates; a source chunk carrying `D11:12` is preselected. |
| `conv-26:qa:39` | pass, 6/6 refs rendered | Exact `D6:4` and `D1:18` turns are selected by the bounded family-activity policy. |
| `conv-41:qa:9` | fail, 0/1 refs rendered | One target-bearing pack candidate is rejected only by the hard character cap. |
| `conv-42:qa:61` | pass, 1/1 refs rendered | Observation and exact-turn evidence are selected; the exact turn is prompt-visible. |

The gate is therefore 3/4, and the one remaining failure is outside query
decomposition.

## Exact next slice

Keep query decomposition unchanged. The next diagnostic/implementation slice
belongs to the feature-owned evidence-selection boundary:

1. Add a synthetic, dataset-neutral application test reproducing the
   `decomposition_inference_support` pressure profile: a named-subject,
   relation-constrained inference candidate at pre-pack rank 27, several
   higher-scored generic inference families, and the 18,000-character hard cap.
2. In
   `packages/infinity_context_core/infinity_context_core/application/context_packer_answer_support.py`
   and, only if the test proves the needed contract,
   `packages/infinity_context_core/infinity_context_core/features/context_building/application/coverage_reservation_selector.py`,
   define one bounded subject-and-relation inference-evidence obligation. It
   must select existing candidates only, preserve the hard cap, and displace at
   most one less-constrained generic inference family.
3. Cover integration in
   `tests/unit/test_context_packer_answer_support_ordering.py` and
   `tests/unit/test_context_packer_coverage_reservations.py`; retain the existing
   hard-cap and unresolved-conflict safety tests.

That slice must first prove a general discriminator from question and candidate
text. It must not reserve benchmark refs or infer an expected answer. If no
generic discriminator separates the target from competing evidence, stop and
leave selection unchanged rather than adding a dataset-specific rule.

## Verification contract

Completed checks:

- focused query/decomposition, family-activity, trace-boundary, and coverage
  reservation tests: **335 passed**;
- architecture/import/file-size suite: **34 passed**;
- `ruff check .`: **passed**;
- four-case exact gate: **3 passed, 1 failed at the documented char-cap
  selection boundary**;
- diff audit: only this report is untracked/changed; there is no production or
  test diff.

Bounded trace JSON and the two baseline/current query-plan projections are in
`/tmp/infinity-context-locomo-recall-diagnostic-v38b-artifacts`. These are
diagnostic handoff artifacts, not repository source.
