# Infinity Context

**Self-hosted memory for AI teams that keeps current project knowledge
source-backed, scoped, and reviewable.**

Infinity Context gives agents and applications durable project memory without
treating every chat fragment or retrieval result as permanent truth. Postgres
owns canonical lifecycle state; optional retrieval systems help find candidates
but do not decide what is current or visible.

It is available through HTTP, a Python SDK, MCP, CLI, and a local UI for shared
project knowledge as well as team, project, and thread-scoped memory.

## Contents

- [Why Infinity Context](#why-infinity-context)
- [How it works](#how-it-works)
- [Architecture and trust model](#architecture-and-trust-model)
- [Quickstart](#quickstart)
- [Integration entry points](#integration-entry-points)
- [Capability positioning](#capability-positioning)
- [Memory evaluation snapshot](#memory-evaluation-snapshot)
- [Status and limitations](#status-and-limitations)
- [Documentation](#documentation)

## Why Infinity Context

Teams need more than semantically similar notes. They need a shared memory
layer where a decision can be traced to its source, updated when the project
changes, and recalled only in the right context.

- **Current knowledge, not a history dump.** Facts have lifecycle state,
  versions, source references, and visibility rules in Postgres.
- **Source-backed and reviewable.** Agents can submit suggestions for review
  instead of silently promoting every generated conclusion to durable memory.
- **Scoped for real work.** Spaces, memory scopes, and threads separate
  projects, workstreams, and sessions.
- **Retrieval is not authority.** Optional Qdrant and Graphiti indexes return
  candidates that are rehydrated from canonical state before prompt rendering.
- **Prompt memory is evidence.** Retrieved material includes citations and
  provenance rather than being phrased as instructions for a model to follow.

A typical team loop is simple: capture a decision with its evidence, propose a
change when the decision evolves, and retrieve only the current scoped context
before a new task. That makes the memory useful to people reviewing work as well
as agents continuing it.

## How it works

~~~mermaid
flowchart LR
    A["Agents and apps"] --> B["HTTP / SDK / MCP / CLI / UI"]
    B --> C["Application use cases"]
    C --> P[("Postgres<br/>canonical current truth")]
    P -->|"when async work is needed"| O["Transactional outbox"]
    O --> W["Projection and extraction workers"]
    W --> Q["Qdrant<br/>optional derived retrieval index"]
    W --> G["Graphiti<br/>optional current-state graph projection"]
    Q -. "candidate IDs" .-> C
    G -. "candidate IDs" .-> C
    C -. "hydrate and revalidate" .-> P
    C --> E["Final prompt context<br/>cited evidence, not instructions"]
~~~

Canonical mutations commit their lifecycle records first. When derived or
extraction work is required, the same transaction also records an outbox event.
Workers update enabled projections asynchronously. During search or context
assembly, candidate IDs are rehydrated from Postgres and revalidated for
lifecycle, scope, and visibility before they can appear in a cited evidence
block.

## Architecture and trust model

Infinity Context applies Clean Architecture, SOLID, simple DDD, and
ports-and-adapters boundaries:

- Postgres owns the canonical lifecycle; Qdrant and Graphiti are optional,
  derived indexes.
- The infinity_context_core package cannot import FastAPI, SQLAlchemy, Qdrant,
  Graphiti, OpenAI, or client application code.
- Adapters provide delivery and infrastructure details without becoming the
  source of truth.

Read the [architecture and trust model](docs/architecture-and-trust-model.md)
for write and read flows, package ownership, consistency behavior, and security
limits.

## Quickstart

The recommended installer sets up the complete local stack, connects your
coding agent, enables review-gated memory suggestions, and opens the UI.

Requirements: Git, Python 3.11 or later, and Docker with Compose.

~~~bash
curl -fsSLo infinity-context-install.sh \
  https://raw.githubusercontent.com/777genius/infinity-context/v0.1.0/scripts/install.sh
bash infinity-context-install.sh --agent codex
~~~

> **Persistence warning:** v0.1.0 does not declare a named Postgres volume.
> Back up canonical Postgres data before `docker compose down`, container
> recreation, reset, or upgrade. The persistence fix currently exists on
> `main` and will reach installers in the next release.

Replace `codex` with `claude`, `gemini`, `opencode`, or `cursor`. Repeat
`--agent` to connect several agents, or use `--all-agents`. The installer
reports whether every requested integration was confirmed instead of claiming
success when manual setup is still required.

After a successful start, the browser opens the local memory UI. Automatic
capture creates suggestions for review; it does not silently promote them to
durable memory.

### Other installation options

Install only the CLI, SDK, and MCP server for an existing deployment:

~~~bash
pipx install 'infinity-context[mcp]==0.1.0'
infinity-context --version
~~~

Pull the versioned multi-architecture server image:

~~~bash
docker pull ghcr.io/777genius/infinity-context:0.1.0
~~~

Contributors can install from source:

~~~bash
git clone https://github.com/777genius/infinity-context.git
cd infinity-context
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[mcp]'
.venv/bin/infinity-context quickstart --agent codex --open-ui
~~~

Use `--no-install-agents` if you only want generated MCP configuration, or
`--retrieve-only` to keep recall while disabling automatic capture creation.

| Profile | Intended local setup |
| --- | --- |
| lite | Postgres, the server, and workers with optional provider adapters disabled |
| full | Adds Qdrant and Neo4j-backed graph services; enabled provider features need their own configuration |

The [public installation guide](docs/public-installation.md) and
[self-hosted deployment guide](docs/self-hosted-team-deployment.md) cover
first-run and operational details.

## Integration entry points

| Entry point | Use it when |
| --- | --- |
| HTTP API | An application needs canonical memory and context endpoints |
| Python SDK | A Python service needs typed HTTP client calls |
| MCP | A coding agent or MCP client needs memory tools and evidence resources |
| CLI | A developer is starting, configuring, or inspecting a local instance |
| Local UI | A person wants to browse evidence and review suggestions locally |

The [MCP adapter guide](docs/mcp-adapter.md) explains the agent-facing boundary.
Retrieved memory is evidence to inspect, not an instruction source.

## Capability positioning

This **source-audited, project-weighted architecture assessment** is dated
**2026-08-05**. It is not a matched performance benchmark, and there is no
universal winner. Under its explicit trust-weighted coding-agent rubric,
Infinity Context is the strongest fit for governed current-state project
memory.

The same published rubric was applied to every system, with no
Infinity-specific bonus. Popularity, company size, and managed-only features
were excluded. A separate source-check review pass verified claims against
pinned public code, documentation, and current issues. Readers can inspect the
[method and sources](docs/competitive/agent-memory-capability-comparison.md#scope-and-method)
and recalculate the assessment. Scores are architecture-fit scores out of 100,
not performance measurements; estimated uncertainty is plus or minus three
points, and differences within three points place products in the same
technical class.

| Rank | Product | Research score / 100 | Leads in | Best fit |
| --- | --- | --- | --- | --- |
| 1 | [Infinity Context](https://github.com/777genius/infinity-context) | **93.9** | Governed current state: canonical versions, provenance, scoped visibility, review-gated promotion, and revalidated derived hits | Teams sharing changing project knowledge across agents and apps |
| 2 | [Hindsight](https://github.com/vectorize-io/hindsight) | 91.5 | Cognitive memory: evidence-grounded observations, maintained mental models, broad recall, and reflection | Agents that learn from accumulated experience |
| 3 | [OpenViking](https://github.com/volcengine/OpenViking) | 90.7 | Unified coding-agent context across memories, resources, and skills | Agents that need one browsable project-context layer |
| 4 | [MemOS](https://github.com/MemTensor/MemOS) | 86.2 | Broad Memory OS building blocks, MemCubes, routing, and schedulers | Products experimenting with multiple memory forms and providers |
| 5 | [MatrixOrigin Memoria](https://github.com/matrixorigin/Memoria) | 84.5 | Memory branches, snapshots, diffs, merges, and rollback | Workflows that need recoverable alternative memory states |
| 6 | [MemMachine](https://github.com/MemMachine/MemMachine) | 84.3 | Source-linked episodic memory and conversational recall | Assistants that must point back to source conversations |
| 7 | [Honcho](https://github.com/plastic-labs/honcho) | 83.9 | Peer and user modeling with explicit and inferred conclusions | Assistants that reason about a person's evolving model |
| 8 | [EverOS](https://github.com/EverMind-AI/EverOS) | 83.1 | Markdown-first local memory with transparent files and derived indexes | Developers who want readable, Git-friendly local memory |
| 9 | [Memora](https://github.com/agentic-box/memora) | 80.1 | Lightweight local MCP memory with lineage and graph interaction | Individual developers wanting inspectable local workflows |
| 10 | [Mem0 OSS](https://github.com/mem0ai/mem0) | 74.4 | Portable memory SDK and integrations | Products that own their lifecycle policy and need quick integration |

**Where Infinity Context stands out.** Vector and graph search can find a
candidate. Only current, visible Postgres state can enter the prompt. A
transactional outbox drives derived projections; every hit is rechecked against
canonical scope, version, and deletion rules, then rendered as cited evidence
rather than an instruction. That directly reduces the chance that an agent
acts on stale, out-of-scope, or silently invented project state.

See the detailed [agent memory capability comparison](docs/competitive/agent-memory-capability-comparison.md)
for lifecycle, retrieval, temporal behavior, review, isolation, deployment, and
scenario tradeoffs.

## Memory evaluation snapshot

Recorded on **2026-10-14**, using diagnostic measurements from **2026-10-13**.
The measured baseline includes [PR #75](https://github.com/777genius/infinity-context/pull/75)
at commit `c238bc9f84f80a7effe83140825ab3a6e576719b`. The table reproduced
exactly on **2026-10-18** when the frozen diagnostic inputs were re-measured
against PR #76.

| Diagnostic set | Questions with all required sources in the context | Required sources covered |
| --- | --- | --- |
| Frozen 100 questions | **90/100 (90.0%)** | 201/216 |
| Separate frozen 48 questions | **38/48 (79.2%)** | 90/104 |

These results measure **source coverage**, not LLM answer accuracy. Both sets have
now been used for diagnosis; the 48-question set is no longer an untouched holdout.
They are not a full LongMemEval result, a production qualification, or a matched
comparison with competing memory systems. Broader quality still needs a fresh
holdout and end-to-end answer evaluation.

PR #75 reduced median context latency from **6.334 s to 5.586 s (11.8%)** in
three alternating ASGI before/after pairs on **one query**. This is a small paired
measurement, not an overall p95 latency estimate.

The citation remediation is [PR #76](https://github.com/777genius/infinity-context/pull/76):
quote previews and query-snippet diagnostics now quote the verbatim chunk body
instead of retrieval metadata, and snippet offsets map to source coordinates.
Focused citation and hydration checks, the provider-consistency and context-sweep
suites, and full CI pass. On the same seeded LongMemEval corpus the real ASGI
`/v1/context` path returned HTTP 200 before and after: 18 of 19 selected items
kept identical text and scores with corrected citations, one near-tie item
(0.7982 vs 0.7975) swapped at the token-budget margin, and quote previews
embedding retrieval hints dropped from 2 selected items to 0. Two independent
review passes approved after two review findings were fixed. The frozen-148
rerun on 2026-10-18 found packed items, scores, and source sets bit-identical
before and after and the coverage table unchanged — **no recall gain and no
recall regression**. Answer-quality impact remains unmeasured.

## Status and limitations

Infinity Context is v0.1 and under active development. APIs, CLI behavior, and
deployment details may evolve.

- Postgres is the canonical lifecycle store. Qdrant is the primary derived
  vector projection. The Graphiti adapter is a narrower current-state
  projection: updates remove the prior episode before adding the new one, and
  the adapter does not expose Graphiti's complete source-reference, ontology,
  or version-history surface.
- Canonical visibility updates take effect before asynchronous derived-index
  cleanup. A stale derived hit is rechecked before rendering.
- Cognee is disabled by default and currently provides a recall-oriented
  boundary without complete ingest, update, or exact-forget lifecycle support.
- The current `main` branch contains provider-neutral cognitive candidate types
  and derivation policy for experiences, observations, lessons, and mental
  models. The foundation itself is not included in v0.1.0. Main still has no
  cognitive persistence, public API, runtime composition wiring, deployment
  dependency, or live adapter; cognitive memory is not part of the active
  runtime shown above.
- Retrieval includes deterministic prepasses shaped by the current evaluation
  domains. This is not ground-truth leakage, but broader transfer quality still
  needs independent evidence.
- Current load and chaos tests exercise lifecycle and consistency on a limited
  corpus; they do not prove behavior at 100,000+ memories or across dozens of
  concurrent agents.
- Review and canonical revalidation reduce memory-poisoning exposure, but they
  are not a proof of safety against sleeper-memory attacks.
- Source references prove provenance, not truth. Review and domain judgment
  remain necessary.
- Evaluate deployment, access control, backups, and operational fit for your
  environment before relying on any self-hosted configuration.

## Documentation

- [Public installation and first run](docs/public-installation.md)
- [Architecture and trust model](docs/architecture-and-trust-model.md)
- [Agent memory capability comparison](docs/competitive/agent-memory-capability-comparison.md)
- [Documentation index](docs/README.md)
- [Core Lite implementation plan](docs/infinity-context-core-lite-plan.md)
- [MCP adapter guide](docs/mcp-adapter.md)
- [Self-hosted team deployment](docs/self-hosted-team-deployment.md)
- [ADR-0002: Postgres as canonical truth](docs/adr/ADR-0002-postgres-canonical-truth.md)
- [ADR-0004: Derived retrieval adapters](docs/adr/ADR-0004-derived-retrieval-adapters.md)
- [Infinity Context vs Mem0 engineering runner](docs/memory-comparison-benchmark.md)
