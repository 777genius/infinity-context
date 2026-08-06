# Historical Infinity Context and Memora engineering experiment

> **Historical internal note.** The former numeric scorecard in this document
> was a project-weighted opinion, not a benchmark, and has been removed. Use the
> [living agent-memory capability comparison](agent-memory-capability-comparison.md)
> for current public positioning.

This report preserves one useful artifact: a direct, disposable local MCP smoke
of [`agentic-box/memora`](https://github.com/agentic-box/memora). It does not
rank overall retrieval quality, production readiness, scale, or security.

## Contents

- [Scope](#scope)
- [Direct Memora smoke](#direct-memora-smoke)
- [What the smoke proves](#what-the-smoke-proves)
- [Capability notes](#capability-notes)
- [Evidence limits](#evidence-limits)
- [Practical conclusion](#practical-conclusion)
- [Sources](#sources)

## Scope

The experiment compared a narrow coding-agent workflow: remember, update,
retrieve, document ingest, digest, delete, and export. It used Memora's local MCP
server with TF-IDF embeddings, SQLite, graph disabled, and no LLM or cloud sync.

This is specifically about `agentic-box/memora`, not the unrelated
`memora-ai/memora` product.

## Direct Memora smoke

The repository target is:

~~~bash
make infinity-context-memora-direct-smoke
~~~

It writes `.tmp/memora-direct-smoke.json` by default. The report contains safe
provenance metadata such as suite version, git state, and runtime, but no Memora
database contents or tokens.

The disposable runtime used:

~~~bash
uvx --from git+https://github.com/agentic-box/memora.git memora-server --no-graph
~~~

Configuration:

- temporary SQLite database;
- `MEMORA_EMBEDDING_MODEL=tfidf`;
- `MEMORA_LLM_ENABLED=false`;
- no cloud sync;
- no paid OpenAI or LLM deduplication path.

The observed report was:

~~~json
{
  "system": "agentic-box/memora",
  "mode": "direct_mcp_stdio",
  "scenario_set": "prod_realistic_coding_agent_memory_v1",
  "embedding_model": "tfidf",
  "llm_enabled": false,
  "tool_count": 42,
  "scenario_count": 7,
  "document_fragment_count": 4,
  "ok": true
}
~~~

## What the smoke proves

For that exact local configuration, the smoke verified:

- core tools were available;
- a durable fact could be created and found through filtered search;
- an updated fact was returned while the old text was no longer primary;
- metadata filtering excluded another project's fact;
- an ADR-style Markdown document could be stored and recalled as fragments;
- `memory_digest` returned source-backed context;
- deletion removed the mutable fact from search;
- export completed successfully.

It proves a strong local MCP contract for this scenario. It does not measure
Memora's LLM, graph, cloud, or large-corpus behavior.

## Capability notes

### Memora

Memora's public code offers more than the narrow smoke exercised:

- smart `absorb` decisions for duplicate, update, contradiction, and related
  memories;
- typed lineage, documents, action history, graph interaction, and direct MCP
  actions;
- full-text, semantic, hybrid, tag, date, cross-reference, and multi-query
  retrieval with reciprocal-rank fusion;
- local-first storage plus D1, S3, and R2 options. Object-storage paths include
  local locking, ETag conflict detection, and retry/backoff behavior.

The current architecture also has limits relevant to large shared deployments:

- semantic retrieval scans stored embeddings, so its vector path grows linearly
  with the corpus;
- full cross-reference rebuild compares all pairs and approaches quadratic work;
- related cross-references can remain stale after an update until rebuilt;
- D1 does not provide the SQLite FTS5 path;
- team isolation and governance depend on storage and application conventions,
  rather than a native review-gated canonical project lifecycle.

These tradeoffs do not diminish Memora's fit as an inspectable personal MCP
memory tool; they narrow what this experiment can infer about distributed use.

### Infinity Context

Infinity Context is shaped around a different contract: Postgres owns canonical
facts, versions, source references, scopes, visibility, review state, and
outbox-driven projections. This is useful when several agents and applications
must share an explicit current project state.

Provider boundaries should not be overstated:

- Qdrant is the primary derived vector projection;
- Graphiti has a real but narrower current-state write, search, and delete path;
  updates remove the previous episode before adding the current one, and the
  adapter does not expose the provider's full source-reference, ontology, or
  temporal-history model;
- Cognee is disabled by default and currently recall-oriented, without a
  complete ingest, update, or exact-forget lifecycle.

Infinity Context also lacks Memora's mature local graph-first exploration and
does not yet have large public evidence for retrieval or many-agent scale.

## Evidence limits

The former scorecard assigned 9.x values and a weighted winner from a direct
TF-IDF/SQLite smoke plus Infinity Context's internal tests. Those inputs cannot
support product-wide scores, so the table and winner language were removed.

In particular:

- the smoke is not a matched retrieval benchmark;
- internal architecture and safety tests are not evidence of competitor quality;
- benchmark-shaped retrieval rules reduce confidence in transfer to unseen
  workloads;
- neither project's security or large-scale production behavior follows from
  these scenarios.

## Practical conclusion

The experiment supports a qualitative distinction, not a winner:

- Memora provides a strong, inspectable local MCP memory workflow with smart
  absorb, documents, lineage, action history, and graph-oriented UX.
- Infinity Context provides a more explicit governed project-memory contract
  with canonical versions, provenance, scopes, review, and derived-index
  revalidation.

Choose and test against the actual deployment scenario. A combined design is
possible only if canonical ownership and synchronization behavior are explicit.

## Sources

- [Memora repository at audited commit](https://github.com/agentic-box/memora/tree/bc64ff745a9b2c0e6245e0137654f041fba0c155)
- [Infinity Context living capability comparison](agent-memory-capability-comparison.md)
- [Infinity Context architecture and trust model](../architecture-and-trust-model.md)
- Local experiment implementation: `scripts/memora_direct_mcp_smoke.py`
