# Infinity Context vs agentic-box/memora for coding-agent memory

Status: source-backed comparison plus direct disposable Memora MCP smoke.

Scope: compare agent memory for coding agents and teams: remember facts, update
facts, delete/forget, retrieve facts, ingest documents, graph relations, scopes,
agent plugin ergonomics and production evidence.

This report compares Infinity Context with `agentic-box/memora`, not the unrelated
`memora-ai/memora` marketing site/package.

## Evidence used

Memora public sources:

- https://github.com/agentic-box/memora
- https://mcpservers.org/servers/agentic-mcp-tools/memora
- https://protodex.io/servers/agentic-box-memora.html

Infinity Context local evidence:

- `tests/architecture/test_memory_boundaries.py`
- `tests/architecture/test_file_size_boundaries.py`
- `tests/unit/test_import_boundaries.py`
- `tests/unit/test_document_fragments.py`
- `tests/unit/test_document_fragment_api.py`
- `tests/unit/test_semantic_dedupe.py`
- `tests/unit/test_capture_semantic_dedupe.py`
- `tests/unit/test_fact_taxonomy_api.py`
- `tests/unit/test_cli_memory_commands.py`
- `tests/unit/test_memory_insights_api.py`
- `tests/unit/test_graph_export_api.py`
- `tests/unit/test_graph_export_mcp.py`
- `tests/unit/test_mcp_fact_relations.py`
- `tests/unit/test_mcp_suggestion_batch_review.py`
- `tests/unit/test_suggestions_api.py`
- `tests/unit/test_memory scope_snapshot_api.py`
- `tests/e2e/test_memory_quality_e2e.py`
- `tests/e2e/test_infinity_context_agent_behavior_bench_e2e.py`
- `tests/e2e/test_infinity_context_agent_plugin_e2e.py`
- `scripts/clean_full_smoke.py`
- `.e2e-artifacts/public-benchmark-full-600-current.json`
- `.e2e-artifacts/multimodal-production-goal-audit.json`

Direct Memora smoke command:

```bash
make infinity-context-memora-direct-smoke
```

The target writes a reusable JSON report to
`.tmp/memora-direct-smoke.json` by default. `make infinity-context-compare-memora`
automatically includes that report when it exists, or use
`MEMORA_DIRECT_SMOKE_REPORT=/path/to/report.json` for an explicit report path.
The report includes safe provenance metadata: generator, suite, git commit,
dirty state and Python/platform runtime, but no Memora database contents or
tokens.

The direct smoke uses:

- `uvx --from git+https://github.com/agentic-box/memora.git memora-server --no-graph`
- temp SQLite database
- `MEMORA_EMBEDDING_MODEL=tfidf`
- `MEMORA_LLM_ENABLED=false`
- no cloud sync
- no OpenAI paid LLM/dedup mode

Scenario set: `prod_realistic_coding_agent_memory_v1`

Covered scenarios:

- remember a durable architecture decision with project metadata
- update the decision and ensure retrieval prefers the current version
- keep another project's API fact out of Atlas-scoped recall
- store an ADR-style markdown document and recall risk/plan fragments
- build a source-backed digest
- delete the mutable fact and verify it disappears from search
- export memory state for backup/sync workflows

Latest observed direct smoke result:

```json
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
```

Checks passed:

- core tools available
- create durable fact
- filtered search by metadata
- update fact and retrieve new version text
- old text not primary after update
- exclude another project through metadata filter
- store structured document and recall fragments
- `memory_digest` returns source-backed context
- delete removes fact from search
- export works

Important limitation: this is not a paid OpenAI/LLM/cloud Memora benchmark.
Do not claim Memora fails those modes. This only proves its local MCP contract is
strong.

## Current production proof status

Fresh Infinity Context evidence from the latest local run:

- local multimodal Docker proof, frontend Marionette proof and quality scorecard
  are green on the current commit;
- internal deterministic retrieval, linking, multimodal and safety gates are
  strong, but they are not a substitute for a fresh large public benchmark;
- the current public benchmark artifact in the workspace is canary-sized, so
  retrieval quality must be treated as provisional rather than top-tier proven;
- production goal audit is still blocked by stale live-provider proof because the
  OpenAI/vision/transcription provider canary has not been regenerated for the
  current commit with a safely configured credential.

Current comparison artifact accepts those reports explicitly:

```bash
python -m infinity_context_server.memora_comparison \
  --public-benchmark-report .e2e-artifacts/public-benchmark-full-600-current.json \
  --production-goal-audit .e2e-artifacts/multimodal-production-goal-audit.json
```

This keeps the competitive claim honest: Infinity Context is stronger on
governed multimodal evidence, scope isolation, review policy and verified
architecture. Memora is still stronger as a ready-to-use personal MCP graph UI
with action history, simple local setup and immediately obvious visual memory.

## Scorecard

Generated by:

```bash
make infinity-context-compare-memora
```

| Dimension | Infinity Context | Memora | Winner |
| --- | ---: | ---: | --- |
| Remember durable coding facts | 9.2 | 9.0 | Tie |
| Update facts without stale answers | 9.2 | 8.1 | Infinity Context |
| Forget/delete and review-gated control | 9.5 | 7.8 | Infinity Context |
| Retrieve the right facts for a coding agent | 7.8 | 8.4 | Memora |
| Large documents and architecture notes | 9.4 | 9.1 | Infinity Context |
| Graph relationships and temporal context | 9.5 | 8.4 | Infinity Context |
| Agent hooks, plugins and real agent ergonomics | 8.8 | 8.4 | Infinity Context |
| Local MCP setup and visual memory UX | 7.8 | 9.3 | Memora |
| Project/team/memory scope isolation | 9.2 | 7.5 | Infinity Context |
| Operational confidence and benchmark evidence | 8.6 | 7.7 | Infinity Context |
| Clean Architecture and extensibility | 9.1 | 6.8 | Infinity Context |

Weighted total:

- Infinity Context: 8.90
- Memora: 8.26

## Honest conclusion

Memora is stronger today for a single developer who wants a rich, local MCP
memory quickly. It has a polished tool surface: create/update/delete/search,
hybrid search, digest, document fragments, typed links, clusters, export/import,
image upload, action history, graph UI and cloud sync options.

Infinity Context is stronger for the product we are building: governed project/team
memory for coding agents and multimodal quick capture. The big differences are first-class
space/memory scope/thread isolation, canonical fact lifecycle, expected-version
updates, review-gated suggestions, bounded batch suggestion create/review with
per-item failures, DB-enforced race-safe pending suggestion dedupe, conservative
semantic-equivalent duplicate suppression in core consolidation and MCP
preflight, conflict-aware auto-apply gating for competing decisions, safer delete policy,
Cognee/Qdrant/Graphiti as replaceable adapters,
plugin-kit-ai generated agent plugins, hook capture tests and architecture
boundary tests. For documents/ADR/notes, Infinity Context now
has the missing typed fragment contract: markdown documents are persisted as
claim, risk, plan_item, reference or section_chunk nodes and the API/MCP ingest
response returns a fragment summary. Cognee/Qdrant remain the stronger
replaceable RAG path. Infinity Context also exposes portable canonical graph export
for facts, documents, typed fragments and evidence links. Canonical facts now
carry category/tags/TTL and expired active facts are hidden from active
list/context/export surfaces while staying auditable by direct id. Context/search
now support category plus tags_any/tags_all/tags_none filters for canonical facts. Memory Scope
snapshot export/import is available through HTTP API, SDK, MCP and CLI with
dry-run, explicit confirmation gates and manifest hash verification for backup
or git-sync integrity. Snapshot import also has a dedicated read-only preview
surface through HTTP API, SDK, MCP and CLI, returning deterministic conflicts,
skipped records, would-import counts and superseded facts before a destructive
restore. Read-only memory insights are available through HTTP API, SDK, MCP and
CLI for pending review load, expired facts, document indexing coverage,
taxonomy hotspots, recent activity, duplicate/similar fact review, a safe
consolidation plan and cleanup action items.
Memora still has
more polished local graph UI and a stronger zero-to-first-memory local MCP
experience. Infinity Context now also has `memory_related_facts` and
`GET /v1/facts/{fact_id}/related`, giving agents read-only related fact
traversal with explainable relation reasons before update/delete or summary
work.
Infinity Context now also has durable typed fact relations through API, SDK and MCP:
`supports`, `supersedes`, `contradicts`, `duplicates`, `references`,
`depends_on`, and `related_to`. Those links are exported through canonical
`graph.json`, so graph visualization and git-syncable evidence do not depend on
Graphiti/Cognee runtime state. MemoryScope snapshot export/import also preserves
those typed fact links, remapping relation endpoints when importing into a new
memory scope. That closes the previous portability gap where facts could be restored
without their durable semantic links.

The main honest caveats after the latest proof run:

- Retrieval quality is currently an honest `7.5-8/10`: strong smoke and internal
  evals, but not enough fresh large public benchmark evidence to claim top-tier;
- live provider proof must be rerun on the current commit before calling the
  OpenAI vision/audio provider slice production-ready;
- Memora's local graph/action-history UX is more immediately polished.

## Practical recommendation

Use Memora as a competitive benchmark and inspiration for UX features:

- ready ADR/notes views on top of the structured fragment contract
- graph visualization on top of the portable graph export
- simple import UI on top of memory scope snapshots
- easy local install

Do not replace Infinity Context with Memora if the goal is a reusable platform behind
multiple apps and agents. Our domain and boundaries are more suitable for that.

Best near-term product direction:

1. Keep Infinity Context as the canonical governed platform.
2. Add a Memora-style graph/document UX where it improves agent usability.
3. Optionally add a `MemoraCompetitorRunner` later for direct side-by-side MCP
   benchmarks, but keep it outside `infinity_context_core`.
