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
    P --> Q["Qdrant<br/>optional derived retrieval index"]
    P --> G["Graphiti<br/>optional current-state graph projection"]
    Q -. "retrieval candidates" .-> C
    G -. "retrieval candidates" .-> C
    C --> E["Final prompt context<br/>cited evidence, not instructions"]
~~~

Writes record canonical facts, documents, sources, versions, and scope first.
Derived projections run separately. During search or context assembly, every
derived candidate is checked against current canonical state before it can
appear in a cited evidence block.

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

This is capability positioning, not a quality ranking. There is no matched
four-way benchmark behind this table. The clearest distinction is between two
different goals: Hindsight currently offers the deeper cognitive-memory layer,
while Infinity Context focuses on a governed current-state control plane for
project memory shared by teams and agents.

| Product | Optimized for | Typical fit |
| --- | --- | --- |
| [Infinity Context](https://github.com/777genius/infinity-context) | Governed current-state project memory | Teams sharing evolving project knowledge across agents and apps |
| [Hindsight](https://github.com/vectorize-io/hindsight) | Evidence-grounded observations, maintained mental models, multi-strategy recall, and agentic reflection | Agents that learn from accumulated experience |
| [Mem0 OSS](https://github.com/mem0ai/mem0) | Portable personalization with user, agent, and run scopes | Products that want ADD-only extraction plus application-owned CRUD and policy |
| [Memora](https://github.com/agentic-box/memora) | Local-first MCP memory with smart absorb, typed lineage, documents, and graph interaction | Individual developers wanting inspectable local memory workflows |

See the detailed [agent memory capability comparison](docs/competitive/agent-memory-capability-comparison.md)
for lifecycle, retrieval, temporal behavior, review, isolation, deployment, and
scenario tradeoffs.

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
