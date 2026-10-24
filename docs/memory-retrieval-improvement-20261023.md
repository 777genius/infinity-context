# Bounded memory retrieval improvements — 2026-10-23

Base: `44ac164a8395c5847ae8792dded95d0dfe4526dd`.
Status: reviewed plan; implementation and acceptance evidence follow in this PR.

## Goal and observations

Improve the actual context retrieval path, not the synthetic benchmark scheduler.
The existing system already has hybrid fusion, canonical hydration and final
visibility revalidation; do not build another memory engine.

`VectorContextCollector`, `GraphContextCollector` and `RagContextCollector`
currently execute up to eight query variants serially inside each lane. The
lanes themselves already run concurrently. Vector search also requests only
its final per-query result allowance before canonical visibility filtering;
a stale head can therefore hide valid evidence just below that allowance.

## Competitive references

- Hindsight runs complementary semantic/keyword/graph/temporal strategies in
  parallel and fuses/reranks candidates:
  https://hindsight.vectorize.io/developer/retrieval
- Graphiti executes configured search methods concurrently and overfetches
  before ranking:
  https://github.com/getzep/graphiti/blob/main/graphiti_core/search/search.py
- Mem0 offers a separate reranking stage, explicitly trading latency/cost for
  relevance: https://docs.mem0.ai/open-source/features/reranker-search

Adopt bounded candidate retrieval and concurrency, not competitor benchmark
claims. A new model-backed reranker is not justified without evaluation access.

## Plan

1. Add a small application-owned ordered query runner. At most four external
   searches per lane may execute simultaneously, and at most eight query
   variants are selected by the existing planner. Per-call timeouts begin only
   when a call gets a slot. Ordinary provider failures remain isolated; caller
   cancellation cancels and joins all owned tasks, including repeated cancellation.
2. Use it in the three existing derived collectors. Preserve query-order result
   reduction, fusion, diagnostics, one batched hydration per lane, and final
   canonical revalidation. Never share a UnitOfWork/session between tasks.
3. Overfetch only vector candidates, conservatively and with an explicit cap,
   before existing canonical filtering/ranking. Do not increase final context
   limits, alter graph/RAG provider billing, add retries, or weaken visibility.
4. Add adversarial unit/integration cases: reversed completion order, partial
   failure, timeouts, cancellation cleanup, stale/missing/wrong-scope head hits,
   valid evidence below the previous cutoff and final context budget.
5. Measure unchanged-output scheduling separately from changed candidate recall.
   Use repeatable query counts and peak-inflight counters, a controlled-latency
   comparison, and real PostgreSQL/Qdrant E2E. Record synthetic versus real
   components explicitly; do not present controlled sleeps as production latency.
6. Run relevant regression suites and repository CI, review the final diff,
   resolve substantive review findings, push each coherent commit and merge
   only the tested head. Avoid touching unrelated concurrent work.

## Plan critique and revisions

These are coordinator critical passes, not claimed independent model reviews.

- Architecture/scope: rejected global result caches and SQLite integrity-check
  removal. Those target freshness or benchmark machinery rather than this path.
  Keep ports, API schemas, canonical ownership, accepted ADRs and dependencies.
- Concurrency/safety: rejected unbounded gather and completion-order merging.
  Bound external work, drain cancellation, retain per-query degradation, keep
  database operations outside fanout and preserve deterministic fusion order.
- Quality/evaluation: rejected claiming better answer quality from a green
  scheduler test or fake LLM. Require a previously missed eligible source to be
  recovered through the mounted context path without stale/cross-scope leakage.
  Restrict overfetch to vectors; graph/RAG cost behavior stays unchanged.
- Operations: a four-call per-lane limit is per request, not a global load
  guarantee. Characterize this explicitly and retain existing provider budgets.

## LLM execution probe

GitHub Actions run `39975157702` installed Codex CLI 0.164.0 and attempted a
read-only `codex exec` requesting only `READY`. It exited 1 with HTTP 401
(missing authentication). No credentials were copied, no login was requested,
and no model answer or independent critic run is claimed. The chat session is
not automatically an authenticated CLI endpoint. Provider-free retrieval tests
remain sufficient for this bounded change, not for competitor answer-quality claims.
