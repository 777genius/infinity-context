# Memory Comparison Benchmark

This runner compares memo-stack / Infinity Context with mem0 using the same
high-level pipeline used by public memory benchmark runners:

```text
ingest -> search -> answer -> judge
```

It is separate from the existing `public-benchmark` command. The existing
runner checks retrieval and evidence coverage. This runner preserves each
pipeline stage for side-by-side accuracy, retrieval, latency, token/context and
failure analysis.

## Command

```sh
MEMORY_SERVICE_TOKEN=... \
MEMORY_OPENAI_API_KEY=... \
MEMORY_COMPARISON_ANSWERER_MODEL=... \
MEMORY_COMPARISON_JUDGE_MODEL=... \
MEMORY_COMPARISON_ANSWERER_INPUT_USD_PER_1M=... \
MEMORY_COMPARISON_ANSWERER_OUTPUT_USD_PER_1M=... \
MEMORY_COMPARISON_JUDGE_INPUT_USD_PER_1M=... \
MEMORY_COMPARISON_JUDGE_OUTPUT_USD_PER_1M=... \
python -m infinity_context_server.eval memory-comparison-benchmark \
  --dataset ./datasets/locomo10.json \
  --memo-api-url http://127.0.0.1:8000 \
  --mem0-url http://127.0.0.1:8888 \
  --benchmark locomo \
  --max-cases 20 \
  --capability single-hop \
  --top-k 200 \
  --top-k-cutoff 10 \
  --top-k-cutoff 20 \
  --top-k-cutoff 50 \
  --top-k-cutoff 200 \
  --answerer-provider openai \
  --judge-provider openai \
  --answerer-input-usd-per-1m 2.50 \
  --answerer-output-usd-per-1m 10.00 \
  --judge-input-usd-per-1m 2.50 \
  --judge-output-usd-per-1m 10.00 \
  --allow-live \
  --allow-paid-llm \
  --run-id locomo-side-by-side-sandbox-001 \
  --report-out .e2e-artifacts/memory-comparison-locomo.json
```

`--mem0-url` is the self-hosted mem0 OSS REST server base URL. The adapter uses
the OSS endpoints `POST /memories`, `POST /search` and `DELETE /memories`; it
does not target the hosted mem0 Platform `/v3` API.

Use deterministic answer/judge for a no-paid dry run by omitting
`--answerer-provider openai`, `--judge-provider openai` and `--allow-paid-llm`.

## Safety Gates

- `--allow-live` is required before the command calls memo-stack or mem0 HTTP
  endpoints.
- `--allow-paid-llm` is required before OpenAI answerer or judge calls.
- OpenAI models are explicit: pass `--answerer-model` / `--judge-model` or set
  `MEMORY_COMPARISON_ANSWERER_MODEL` / `MEMORY_COMPARISON_JUDGE_MODEL`.
- OpenAI key is read from `MEMORY_OPENAI_API_KEY` by default, with
  `OPENAI_API_KEY` as fallback. Do not commit keys or generated raw provider
  payloads.
- Token cost reporting uses explicit USD-per-1M-token rates from CLI flags or
  `MEMORY_COMPARISON_*_USD_PER_1M` env vars. The runner does not hardcode
  provider prices.
- The memo-stack backend isolates state with a run-specific benchmark space.
- The mem0 backend uses a run-specific `user_id` / `run_id` and deletes that
  isolated user/run at startup by default.
- Corpus reuse is keyed by memory scope, thread and source content fingerprint;
  failed ingests are not cached for later questions in the same conversation.

## Report Shape

The JSON report includes:

- per-backend accuracy and category/group breakdown;
- LoCoMo category 5 reported in `by_category` with unscored counts but excluded
  from scored accuracy;
- retrieved memory count, retrieval recall and missing expected terms;
- ingest/search/generation/judge latency averages;
- context token estimates, answerer/judge token usage and configured token cost;
- top-k cutoff metrics;
- per-case failure analysis with backend, group, score, retrieval recall and
  missing terms;
- backend reset/ingest/search/answer/judge exceptions as scored stage failures with
  redacted error metadata.
