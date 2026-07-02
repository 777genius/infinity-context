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
