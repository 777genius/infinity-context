# Infinity Context LoCoMo Retrieval Quality Notes

## 2026-07-02

- Baseline focused memory-comparison checks passed before changes:
  `uv run --extra dev pytest -q tests/unit/test_memory_comparison_bundle_planner.py tests/unit/test_memory_comparison_rerank_policy.py tests/unit/test_memory_comparison_answer_context.py tests/unit/test_memory_comparison_quality_support_gaps.py tests/unit/test_memory_comparison_query_role_diagnostics.py`
  -> 163 passed.
- Implemented typed `favorite_preference` support so favorite/favourite questions
  require explicit favorite evidence instead of being satisfied by generic
  preference/like evidence.
- Added `favorite_support` across query planning, evidence bundle planning,
  typed rerank support, answer-context backfill matching, and diagnostics.
- Tightened the missing favorite evidence safety cap so generic preference
  matches cannot outrank explicit favorite evidence solely because of upstream
  retrieval score.
- Updated stale query-role expectation for future home-move/current-goal
  decomposition to reflect typed `current_goal_support`.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 495 passed, 1 warning.
- `uv run --extra dev python -m infinity_context_server.eval memory-comparison-benchmark --dataset ./datasets/locomo10.json --memo-api-url http://127.0.0.1:7788 --mem0-url http://127.0.0.1:8888 --benchmark locomo --locomo-ingest-mode official-turns --case-set locomo-fast --report-mode compact --top-k 200 --top-k-cutoff 10 --top-k-cutoff 20 --top-k-cutoff 50 --top-k-cutoff 200 --allow-live --preflight-only`
  -> blocked safely because `./datasets/locomo10.json` is absent. Fast-readiness
  blockers were otherwise empty; no long/full LoCoMo run was attempted.
- `git push origin main` -> blocked because the non-interactive runtime has no
  GitHub username/credential prompt available.

## 2026-07-02 Follow-up 28

- Expanded typed vehicle-profile evidence for owned model shorthand such as
  "My Tesla is blue" and person-possessive model evidence such as
  "Alex's Tesla is blue," which LoCoMo-style car questions should treat as
  vehicle evidence even when the word "car" is absent.
- Kept vehicle model grounding out of compact query fanout: possessive model
  surfaces now satisfy the vehicle category grounding gate without adding
  brand/model terms to search queries.
- Added rerank regressions proving owned/possessive Tesla evidence receives
  typed `vehicle_support` while topical Tesla mentions remain untyped.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_named_vehicle_model_evidence tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_person_possessive_vehicle_model_evidence`
  -> 2 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_relation_support.py packages/infinity_context_server/infinity_context_server/memory_comparison_candidate_features.py tests/unit/test_memory_comparison_benchmark.py`
  -> passed.
- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 520 passed, 1 warning.
- `uv run --extra dev pytest -q tests/architecture/test_memory_boundaries.py`
  -> 6 passed.
- `git diff --check` -> passed.
- `uv run --extra dev python -m infinity_context_server.eval memory-comparison-benchmark --dataset ./datasets/locomo10.json --memo-api-url http://127.0.0.1:7788 --mem0-url http://127.0.0.1:8888 --benchmark locomo --locomo-ingest-mode official-turns --case-set locomo-fast --report-mode compact --top-k 200 --top-k-cutoff 10 --top-k-cutoff 20 --top-k-cutoff 50 --top-k-cutoff 200 --allow-live --preflight-only`
  -> blocked safely because `./datasets/locomo10.json` and memory auth token
  are absent. Fast-readiness blockers were empty; no long/full LoCoMo run was
  attempted.
- `git push origin main` -> still blocked because the non-interactive runtime
  has no GitHub username/credential prompt available.

## 2026-07-02 Follow-up 27

- Expanded typed pet-profile support for breed questions such as "What breed
  is Alex's dog?" and owned/named breed evidence such as "My golden retriever
  is named Luna."
- Kept breed terms conditional in compact pet query fanout so ordinary pet-name
  questions preserve their previous focused query terms.
- Added a rerank regression proving owned golden-retriever evidence receives
  typed `pet_support` while a topical golden-retriever park sighting remains
  untyped.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison_benchmark.py::test_query_decomposition_expands_pet_profile_queries tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_pet_profile_evidence tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_pet_breed_profile_evidence`
  -> 3 passed, 1 warning.
- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 518 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_text.py packages/infinity_context_server/infinity_context_server/memory_comparison_rerank.py packages/infinity_context_server/infinity_context_server/memory_comparison_intent.py packages/infinity_context_server/infinity_context_server/memory_comparison_query_terms.py packages/infinity_context_server/infinity_context_server/memory_comparison_relation_support.py packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_terms.py tests/unit/test_memory_comparison_benchmark.py`
  -> passed.
- `uv run --extra dev pytest -q tests/architecture/test_memory_boundaries.py`
  -> 6 passed.
- `git diff --check` -> passed.
- `uv run --extra dev python -m infinity_context_server.eval memory-comparison-benchmark --dataset ./datasets/locomo10.json --memo-api-url http://127.0.0.1:7788 --mem0-url http://127.0.0.1:8888 --benchmark locomo --locomo-ingest-mode official-turns --case-set locomo-fast --report-mode compact --top-k 200 --top-k-cutoff 10 --top-k-cutoff 20 --top-k-cutoff 50 --top-k-cutoff 200 --allow-live --preflight-only`
  -> blocked safely because `./datasets/locomo10.json` and memory auth token
  are absent. Fast-readiness blockers were empty; no long/full LoCoMo run was
  attempted.
- `git push origin main` -> blocked because the non-interactive runtime has no
  GitHub username/credential prompt available.

## 2026-07-02 Follow-up 26

- Expanded typed employment-profile evidence for explicit occupation identity
  turns such as "I'm a nurse" instead of requiring "work for/at/as" or
  "job is" wording.
- Kept occupation grounding out of query fanout: explicit occupation profile
  surfaces now satisfy the employment category grounding gate without adding a
  broad occupation list to compact search queries.
- Added a rerank regression proving "I'm a nurse at the clinic" receives typed
  `employment_support` and outranks a higher-scored topical nurse appointment
  mention.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison_benchmark.py::test_query_decomposition_expands_employment_profile_queries tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_employment_profile_evidence tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_occupation_employment_profile_evidence`
  -> 3 passed, 1 warning.
- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 517 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_relation_support.py packages/infinity_context_server/infinity_context_server/memory_comparison_candidate_features.py tests/unit/test_memory_comparison_benchmark.py`
  -> passed.
- `uv run --extra dev pytest -q tests/architecture/test_memory_boundaries.py`
  -> 6 passed.
- `git diff --check` -> passed.
- `uv run --extra dev python -m infinity_context_server.eval memory-comparison-benchmark --dataset ./datasets/locomo10.json --memo-api-url http://127.0.0.1:7788 --mem0-url http://127.0.0.1:8888 --benchmark locomo --locomo-ingest-mode official-turns --case-set locomo-fast --report-mode compact --top-k 200 --top-k-cutoff 10 --top-k-cutoff 20 --top-k-cutoff 50 --top-k-cutoff 200 --allow-live --preflight-only`
  -> blocked safely because `./datasets/locomo10.json` and memory auth token
  are absent. Fast-readiness blockers were empty; no long/full LoCoMo run was
  attempted.
- `git push origin main` -> blocked because the non-interactive runtime has no
  GitHub username/credential prompt available.

## 2026-07-02 Follow-up 25

- Expanded location-origin support for "where was X raised" questions and
  "raised in PLACE" evidence.
- Guarded raised-location questions from picking up generic charity/fundraising
  `raise` relation fanout, so location support queries stay focused on origin
  evidence instead of awareness/fundraiser terms.
- Added regressions proving raised-in-Toronto evidence receives
  `location_transition` support while a Toronto fundraising distractor stays
  untyped.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison_benchmark.py::test_query_decomposition_expands_location_profile_queries tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_raised_origin_profile_evidence tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_origin_profile_evidence`
  -> 3 passed, 1 warning.
- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 516 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_text.py packages/infinity_context_server/infinity_context_server/memory_comparison_rerank.py packages/infinity_context_server/infinity_context_server/memory_comparison_intent.py packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_terms.py packages/infinity_context_server/infinity_context_server/memory_comparison_query_terms.py packages/infinity_context_server/infinity_context_server/memory_comparison_relation_support.py packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_policies.py tests/unit/test_memory_comparison_benchmark.py`
  -> passed.
- `uv run --extra dev pytest -q tests/architecture/test_memory_boundaries.py`
  -> 6 passed.
- `git diff --check` -> passed.
- `uv run --extra dev python -m infinity_context_server.eval memory-comparison-benchmark --dataset ./datasets/locomo10.json --memo-api-url http://127.0.0.1:7788 --mem0-url http://127.0.0.1:8888 --benchmark locomo --locomo-ingest-mode official-turns --case-set locomo-fast --report-mode compact --top-k 200 --top-k-cutoff 10 --top-k-cutoff 20 --top-k-cutoff 50 --top-k-cutoff 200 --allow-live --preflight-only`
  -> blocked safely because `./datasets/locomo10.json` and memory auth token
  are absent. Fast-readiness blockers were empty; no long/full LoCoMo run was
  attempted.
- `git push origin main` -> blocked because the non-interactive runtime has no
  GitHub username/credential prompt available.

## 2026-07-02 Follow-up 24

- Expanded typed skill-profile language support for bilingual wording in both
  query planning and evidence detection.
- Prioritized language ability terms in skill support fanout so `know`,
  `fluent`, and `bilingual` questions keep the matching term in the compact
  query instead of being crowded out by lower-priority instrument variants.
- Added regressions proving bilingual-in-Spanish evidence receives typed
  `skill_support` while a topical Spanish cookbook mention stays untyped.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison_benchmark.py::test_query_decomposition_expands_skill_profile_queries tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_fluent_language_skill_evidence tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_bilingual_language_skill_evidence`
  -> 3 passed, 1 warning.
- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 515 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_text.py packages/infinity_context_server/infinity_context_server/memory_comparison_rerank.py packages/infinity_context_server/infinity_context_server/memory_comparison_intent.py packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_terms.py packages/infinity_context_server/infinity_context_server/memory_comparison_query_terms.py packages/infinity_context_server/infinity_context_server/memory_comparison_relation_support.py tests/unit/test_memory_comparison_benchmark.py`
  -> passed.
- `uv run --extra dev pytest -q tests/architecture/test_memory_boundaries.py`
  -> 6 passed.
- `git diff --check` -> passed.
- `uv run --extra dev python -m infinity_context_server.eval memory-comparison-benchmark --dataset ./datasets/locomo10.json --memo-api-url http://127.0.0.1:7788 --mem0-url http://127.0.0.1:8888 --benchmark locomo --locomo-ingest-mode official-turns --case-set locomo-fast --report-mode compact --top-k 200 --top-k-cutoff 10 --top-k-cutoff 20 --top-k-cutoff 50 --top-k-cutoff 200 --allow-live --preflight-only`
  -> blocked safely because `./datasets/locomo10.json` and memory auth token
  are absent. Fast-readiness blockers were empty; no long/full LoCoMo run was
  attempted.
- `git push origin main` -> blocked because the non-interactive runtime has no
  GitHub username/credential prompt available.

## Next Steps

- Continue adding typed support for narrow LoCoMo facets where generic
  categories can over-admit evidence.
- Re-run `locomo-fast` only after dataset/auth/service preflight is green.

## 2026-07-02 Follow-up

- Promoted `date_profile` and `status_profile` relation facets into explicit
  compact query roles (`date_support`, `status_support`) instead of leaving
  their focused lexical fanout under generic/inference roles.
- Added assertions that birthday/anniversary and relationship/kinship queries
  carry the typed support roles in the query plan.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 495 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_rerank.py tests/unit/test_memory_comparison_benchmark.py`
  -> passed.

## 2026-07-02 Follow-up 2

- Added `favorite_support` to query-plan integrity diagnostics so fast gates can
  report missing typed favorite fanout instead of treating any selected query
  family as acceptable.
- Verified the expanded memory-comparison test set after adding typed date,
  status, and favorite query-plan diagnostics.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 496 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_rerank.py packages/infinity_context_server/infinity_context_server/memory_comparison_quality_diagnostics.py tests/unit/test_memory_comparison_benchmark.py tests/unit/test_memory_comparison_quality_diagnostics.py`
  -> passed.

## 2026-07-02 Follow-up 3

- Tightened answer-context backfill role matching: typed query roles such as
  `favorite_support` no longer count as missing-role support unless the
  candidate also has the matching evidence category/content signal.
- Added a regression test where generic preference evidence retrieved by a
  `favorite_support` query loses to explicit favorite evidence and is not marked
  as satisfying the missing favorite role.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 497 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_answer_context_backfill.py tests/unit/test_memory_comparison_answer_context.py`
  -> passed.
- `git push origin main` -> still blocked because the non-interactive runtime
  has no GitHub username/credential prompt available.

## 2026-07-02 Follow-up 19

- Expanded status-profile relation support to recognize named possessive
  person-role evidence such as "Riley is Dana's roommate." This improves
  LoCoMo-style kinship/roommate/colleague questions where evidence is phrased
  with names rather than first-person pronouns.
- Added a rerank regression proving a topical roommate mention is not treated
  as status evidence while the named possessive status turn receives typed
  status support and ranks first.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_named_possessive_status_evidence tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_status_profile_evidence`
  -> 2 passed, 1 warning.
- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 511 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_relation_support.py tests/unit/test_memory_comparison_benchmark.py`
  -> passed.
- `uv run --extra dev python -m infinity_context_server.eval memory-comparison-benchmark --dataset ./datasets/locomo10.json --memo-api-url http://127.0.0.1:7788 --mem0-url http://127.0.0.1:8888 --benchmark locomo --locomo-ingest-mode official-turns --case-set locomo-fast --report-mode compact --top-k 200 --top-k-cutoff 10 --top-k-cutoff 20 --top-k-cutoff 50 --top-k-cutoff 200 --allow-live --preflight-only`
  -> blocked safely because `./datasets/locomo10.json` and memory auth token
  are absent. Fast-readiness blockers were empty; no long/full LoCoMo run was
  attempted.
- `git push origin main` -> blocked because the non-interactive runtime has no
  GitHub username/credential prompt available.
- `git push origin main` -> still blocked because the non-interactive runtime
  has no GitHub username/credential prompt available.

## 2026-07-02 Follow-up 20

- Tightened named status relation matching so possessive role phrases require
  a named person relation surface such as "Riley is Dana's roommate" or
  "Dana's roommate is Riley." A topical phrase like "Dana's roommate matching
  app" no longer satisfies `status_profile`.
- Expanded the named-status rerank regression with a higher-scored named app
  distractor to prove it is not treated as typed status evidence.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_named_possessive_status_evidence tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_status_profile_evidence`
  -> 2 passed, 1 warning.
- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 511 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_relation_support.py tests/unit/test_memory_comparison_benchmark.py`
  -> passed.
- `git push origin main` -> still blocked because the non-interactive runtime
  has no GitHub username/credential prompt available.

## 2026-07-02 Follow-up 21

- Expanded date-profile relation support for birth-date evidence phrased as
  "I was born May 5" or "date of birth is May 5." This lets birthday/date
  questions use typed `date_support` even when the evidence does not repeat the
  word "birthday."
- Added a rerank regression proving a topical birthday-gift mention stays
  untyped while birth-date evidence receives typed date support and ranks first.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_born_date_profile_evidence tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_date_profile_evidence`
  -> 2 passed, 1 warning.
- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 512 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_relation_support.py tests/unit/test_memory_comparison_benchmark.py`
  -> passed.
- `uv run --extra dev python -m infinity_context_server.eval memory-comparison-benchmark --dataset ./datasets/locomo10.json --memo-api-url http://127.0.0.1:7788 --mem0-url http://127.0.0.1:8888 --benchmark locomo --locomo-ingest-mode official-turns --case-set locomo-fast --report-mode compact --top-k 200 --top-k-cutoff 10 --top-k-cutoff 20 --top-k-cutoff 50 --top-k-cutoff 200 --allow-live --preflight-only`
  -> blocked safely because `./datasets/locomo10.json` and memory auth token
  are absent. Fast-readiness blockers were empty; no long/full LoCoMo run was
  attempted.
- `git push origin main` -> still blocked because the non-interactive runtime
  has no GitHub username/credential prompt available.

## 2026-07-02 Follow-up 22

- Expanded education-profile relation support for named school evidence such as
  "I go to Stanford." School questions can now use typed `education_profile`
  support even when the evidence names the institution without repeating
  "school" or "university."
- Added a rerank regression proving a topical Stanford mention stays untyped
  while the named-school education evidence receives typed relation support and
  ranks first.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_named_school_education_evidence tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_education_profile_evidence tests/unit/test_memory_comparison_benchmark.py::test_query_decomposition_expands_education_profile_queries`
  -> 3 passed, 1 warning.
- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 513 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_relation_support.py packages/infinity_context_server/infinity_context_server/memory_comparison_candidate_features.py packages/infinity_context_server/infinity_context_server/memory_comparison_intent.py tests/unit/test_memory_comparison_benchmark.py`
  -> passed.
- `git diff --check` -> passed.
- `uv run --extra dev python -m infinity_context_server.eval memory-comparison-benchmark --dataset ./datasets/locomo10.json --memo-api-url http://127.0.0.1:7788 --mem0-url http://127.0.0.1:8888 --benchmark locomo --locomo-ingest-mode official-turns --case-set locomo-fast --report-mode compact --top-k 200 --top-k-cutoff 10 --top-k-cutoff 20 --top-k-cutoff 50 --top-k-cutoff 200 --allow-live --preflight-only`
  -> blocked safely because `./datasets/locomo10.json` and memory auth token
  are absent. Fast-readiness blockers were empty; no long/full LoCoMo run was
  attempted.
- `git push origin main` -> still blocked because the non-interactive runtime
  has no GitHub username/credential prompt available.

## 2026-07-02 Follow-up 18

- Allowed answerability boosts for grounded typed category evidence even when
  the category detector is the main evidence signal and relation-token hits are
  sparse. This helps typed profile/action evidence rank by direct answerability
  instead of relying only on lexical density.
- Preserved the stricter communication grounding rule: communication
  answerability still requires speaker grounding when the query names a speaker,
  so recipient-side turns do not outrank the actual speaker turn.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison_rerank_policy.py -k "answerability"`
  -> 4 passed, 36 deselected.
- `uv run --extra dev pytest -q tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_speaker_grounded_communication_evidence`
  -> 1 passed, 1 warning.
- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 510 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_policies.py tests/unit/test_memory_comparison_rerank_policy.py`
  -> passed.

## 2026-07-02 Follow-up 4

- Tightened incomplete-bundle answer-context backfill further: when required
  roles are missing, retrieval backfill now excludes candidates that do not
  satisfy any missing role with matching evidence. This prevents generic/noise
  retrieval items from being appended just because the backfill target count has
  spare room.
- Updated answer-context tests so generic preference, metadata-only temporal,
  visual-only temporal and unrelated noise candidates are excluded from
  role-repair backfill.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 497 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_answer_context_backfill.py tests/unit/test_memory_comparison_answer_context.py`
  -> passed.

## 2026-07-02 Follow-up 5

- Surfaced `favorite_support_count` as a first-class evidence bundle and
  answer-context diagnostic instead of only burying it under generic typed
  relation counts.
- Added a regression that a required favorite bundle role is satisfied only by
  explicit `favorite_preference` evidence, while generic preference evidence is
  rejected for that role even when it has stronger bundle score.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 498 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_bundle_planner.py packages/infinity_context_server/infinity_context_server/memory_comparison_answer_context.py tests/unit/test_memory_comparison_bundle_planner.py tests/unit/test_memory_comparison_answer_context.py`
  -> passed.
- `git push origin main` -> still blocked because the non-interactive runtime
  has no GitHub username/credential prompt available.

## 2026-07-02 Follow-up 17

- Tightened answer-context backfill for the new typed `action_support` role.
  Retrieval backfill now requires matching `action_event` evidence before an
  action-support candidate can repair a missing bundle role; merely arriving
  from an `action_support` query role is not enough.
- Added a regression where a stronger query-role-only action candidate is
  excluded and explicit action evidence is backfilled.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison_answer_context.py -k "action_role or backfill_requires"`
  -> 4 passed, 18 deselected.
- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 509 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_answer_context_backfill.py tests/unit/test_memory_comparison_answer_context.py`
  -> passed.

## 2026-07-02 Follow-up 6

- Propagated typed relation support totals and per-role counts from evidence
  bundle quality into answer-context diagnostics and aggregate metrics. This
  gives fast gates visibility into selected health/date/status/education/
  employment/favorite/skill/vehicle/pet support instead of only generic bundle
  source information.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 498 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_answer_context.py tests/unit/test_memory_comparison_answer_context.py`
  -> passed.
- `git push origin main` -> still blocked because the non-interactive runtime
  has no GitHub username/credential prompt available.

## 2026-07-02 Follow-up 7

- Added a bundle-quality component score for grounded typed relation support so
  non-favorite profile evidence such as health/date/status/education/
  employment/skill/vehicle/pet support contributes directly to bundle
  confidence instead of only appearing in reason codes.
- Kept favorite support on its dedicated component to avoid double-counting the
  already first-class favorite evidence score.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 498 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_bundle_planner.py tests/unit/test_memory_comparison_bundle_planner.py`
  -> passed.
- `git push origin main` -> still blocked because the non-interactive runtime
  has no GitHub username/credential prompt available.

## 2026-07-02 Follow-up 8

- Relaxed typed profile rerank grounding for category detectors: health/date/
  status/education/employment/favorite-style profile hits can now receive typed
  relation support when provenance and entity/speaker grounding are present,
  even if no separate relation token hit was extracted.
- Kept non-profile categories such as causal/support-goal on the stricter
  relation-surface path to avoid promoting broad conversational reactions.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 500 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_policies.py tests/unit/test_memory_comparison_rerank_policy.py`
  -> passed.
- `git push origin main` -> still blocked because the non-interactive runtime
  has no GitHub username/credential prompt available.

## 2026-07-02 Follow-up 9

- Tightened typed relation rerank role boosts so the query-role bonus is based
  on typed roles with matching category hits, not every requested typed support
  role. This avoids over-boosting mixed profile queries when only one typed
  facet is actually evidenced.
- Added diagnostics for `benchmark_typed_relation_support_hit_roles` so fast
  reports can distinguish requested typed roles from grounded typed hits.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 501 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_policies.py tests/unit/test_memory_comparison_rerank_policy.py`
  -> passed.

## 2026-07-02 Follow-up 10

- Added query-role effectiveness diagnostics for typed relation hit roles so
  fast reports can distinguish a typed query role that merely appeared on a
  lifted candidate from a typed role with matching evidence.
- Added per-role typed relation hit counts/rates and a
  `roles_without_typed_relation_hits` list to expose mixed profile fanout where
  only part of the requested typed evidence was actually grounded.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 502 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_quality_query_roles.py tests/unit/test_memory_comparison_quality_diagnostics.py`
  -> passed.

## 2026-07-02 Follow-up 11

- Promoted typed relation hit-role gaps into fast-gate query-role breakdowns.
  A lifted or selected typed query role now still reports a gap when no matching
  typed evidence category was actually hit.
- Added fast-gate coverage for mixed health/status profile fanout where only
  health evidence is grounded, so status support is reported as
  `typed_relation_not_hit`.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 503 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_quality_diagnostics.py tests/unit/test_memory_comparison_quality_diagnostics.py`
  -> passed.
- `git push origin main` -> still blocked because the non-interactive runtime
  has no GitHub username/credential prompt available.

## 2026-07-02 Follow-up 12

- Made query-role gaps part of fast-gate readiness. A fast/preflight report now
  fails `ready_for_full_locomo` when selected retrieval has query-role gaps,
  including typed relation roles that were requested but did not produce a
  matching typed evidence hit.
- Added assertions that both a normal query-role selection gap and a mixed
  health/status typed-hit gap fail the new `query_role_gaps_clear` gate.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 503 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_quality_diagnostics.py tests/unit/test_memory_comparison_quality_diagnostics.py`
  -> passed.

## 2026-07-02 Follow-up 13

- Tightened typed-hit gap diagnostics so `roles_without_typed_relation_hits`
  only considers roles from the typed relation support registry. Non-typed
  relation roles such as `preference_support` no longer create false
  typed-hit readiness failures.
- Added diagnostics and fast-gate regressions proving preference support can
  remain clear without typed relation hit metadata, while typed profile roles
  still report typed-hit gaps.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 505 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_quality_query_roles.py tests/unit/test_memory_comparison_quality_diagnostics.py`
  -> passed.

## 2026-07-02 Follow-up 14

- Added lifted-only answerability gap diagnostics to the fast gate so reports
  separate general missing-evidence candidates from candidates the reranker
  actually boosted or otherwise lifted.
- Added a `lifted_answerability_gaps_clear` readiness gate. Full LoCoMo is now
  blocked when a lifted candidate still carries `missing_*_evidence` reason
  codes, while non-lifted distractor gaps remain diagnostic-only.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison_quality_diagnostics.py -k "answerability or ready_for_full or lifted"`
  -> 3 passed, 43 deselected.
- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 506 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_quality_diagnostics.py tests/unit/test_memory_comparison_quality_diagnostics.py`
  -> passed.
- `git push origin main` -> still blocked because the non-interactive runtime
  has no GitHub username/credential prompt available.

## 2026-07-02 Follow-up 15

- Made fast-gate readiness fail when a query plan omits a query family required
  by the evidence roles. This uses the existing
  `missing_evidence_role_query_family_total` signal instead of gating all
  dropped/fanout plan diagnostics.
- Added an otherwise-ready favorite-support regression proving a base-only
  query plan now fails `query_plan_evidence_roles_clear`.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison_quality_diagnostics.py -k "query_plan or ready_for_full"`
  -> 11 passed, 36 deselected.
- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 507 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_quality_diagnostics.py tests/unit/test_memory_comparison_quality_diagnostics.py`
  -> passed.
- `git push origin main` -> still blocked because the non-interactive runtime
  has no GitHub username/credential prompt available.

## 2026-07-02 Follow-up 16

- Added typed `action_support` for concrete "what did X take/send/paint/book/etc."
  action questions that are not better handled by visual evidence. This gives
  LoCoMo-style action asks a compact role, query fanout, typed relation hit,
  bundle selection path, fusion weight, and fast-gate diagnostics.
- Kept visual picture/photo/image/video questions on the existing visual path
  so action support does not over-boost media evidence questions.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 508 passed, 1 warning.
- `uv run --extra dev pytest -q tests/architecture/test_memory_boundaries.py`
  -> 6 passed.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_text.py packages/infinity_context_server/infinity_context_server/memory_comparison_query_terms.py packages/infinity_context_server/infinity_context_server/memory_comparison_rerank.py packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_terms.py packages/infinity_context_server/infinity_context_server/memory_comparison_intent.py packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_policies.py packages/infinity_context_server/infinity_context_server/memory_comparison_bundle_planner.py packages/infinity_context_server/infinity_context_server/memory_comparison_quality_support.py packages/infinity_context_server/infinity_context_server/memory_comparison_quality_diagnostics.py packages/infinity_context_server/infinity_context_server/memory_comparison_quality_query_roles.py packages/infinity_context_server/infinity_context_server/memory_comparison_candidate_fusion.py packages/infinity_context_server/infinity_context_server/memory_comparison_relation_support.py tests/unit/test_memory_comparison_benchmark.py tests/unit/test_memory_comparison_bundle_planner.py`
  -> passed.
- `uv run --extra dev python -m infinity_context_server.eval memory-comparison-benchmark --dataset ./datasets/locomo10.json --memo-api-url http://127.0.0.1:7788 --mem0-url http://127.0.0.1:8888 --benchmark locomo --locomo-ingest-mode official-turns --case-set locomo-fast --report-mode compact --top-k 200 --top-k-cutoff 10 --top-k-cutoff 20 --top-k-cutoff 50 --top-k-cutoff 200 --allow-live --preflight-only`
  -> blocked safely because `./datasets/locomo10.json` and memory auth token
  are absent. Fast-readiness blockers were empty; no long/full LoCoMo run was
  attempted.
- `git push origin main` -> still blocked because the non-interactive runtime
  has no GitHub username/credential prompt available.

## 2026-07-02 Follow-up 23

- Expanded typed skill-profile support for language ability questions phrased
  as "what language does X know" or "what language is X fluent in" instead of
  only "speak" wording.
- Added fluent/know language support to skill query fanout and rerank evidence
  detection while keeping instrument questions on the existing instrument/play
  query terms.
- Added regressions proving fluent-in-Spanish evidence receives typed
  `skill_support` and a topical Spanish-food distractor does not.

## Verification

- `uv run --extra dev pytest -q tests/unit/test_memory_comparison_benchmark.py::test_query_decomposition_expands_skill_profile_queries tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_skill_profile_evidence tests/unit/test_memory_comparison_benchmark.py::test_benchmark_rerank_boosts_fluent_language_skill_evidence`
  -> 3 passed, 1 warning.
- `uv run --extra dev pytest -q tests/unit/test_memory_comparison*.py`
  -> 514 passed, 1 warning.
- `uv run --extra dev ruff check packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_text.py packages/infinity_context_server/infinity_context_server/memory_comparison_rerank.py packages/infinity_context_server/infinity_context_server/memory_comparison_intent.py packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_terms.py packages/infinity_context_server/infinity_context_server/memory_comparison_query_terms.py packages/infinity_context_server/infinity_context_server/memory_comparison_relation_support.py tests/unit/test_memory_comparison_benchmark.py`
  -> passed.
- `uv run --extra dev pytest -q tests/architecture/test_memory_boundaries.py`
  -> 6 passed.
- `git diff --check` -> passed.
- `uv run --extra dev python -m infinity_context_server.eval memory-comparison-benchmark --dataset ./datasets/locomo10.json --memo-api-url http://127.0.0.1:7788 --mem0-url http://127.0.0.1:8888 --benchmark locomo --locomo-ingest-mode official-turns --case-set locomo-fast --report-mode compact --top-k 200 --top-k-cutoff 10 --top-k-cutoff 20 --top-k-cutoff 50 --top-k-cutoff 200 --allow-live --preflight-only`
  -> blocked safely because `./datasets/locomo10.json` and memory auth token
  are absent. Fast-readiness blockers were empty; no long/full LoCoMo run was
  attempted.
