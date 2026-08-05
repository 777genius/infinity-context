# Architecture and trust model

**Infinity Context is a memory service where Postgres holds the current,
source-backed state and retrieval engines only supply candidates.**

This guide describes the public mental model for the system. It is deliberately
about boundaries and behavior, not a promise of a particular deployment outcome.

## Contents

- [Problem and mental model](#problem-and-mental-model)
- [System shape](#system-shape)
- [Adapter coverage today](#adapter-coverage-today)
- [Trust invariants](#trust-invariants)
- [Canonical write flow](#canonical-write-flow)
- [Canonical read flow](#canonical-read-flow)
- [Architecture and package boundaries](#architecture-and-package-boundaries)
- [Consistency and failure behavior](#consistency-and-failure-behavior)
- [Evidence boundaries](#evidence-boundaries)
- [Security and information limits](#security-and-information-limits)
- [Deployment profiles](#deployment-profiles)
- [Further reading](#further-reading)

## Problem and mental model

Agent memory is useful when it preserves decisions, evidence, and project
history across sessions. It becomes risky when a vector hit, a generated
summary, or a provider-specific record silently decides what the project now
believes.

Infinity Context separates two jobs:

1. **Canonical lifecycle:** decide what exists, which version is current, where
   it came from, which scope can see it, and whether it is active or deleted.
2. **Derived retrieval:** make canonical material easier to find with vector,
   graph, or provider-specific indexes.

Postgres owns the first job. Derived systems may help with the second, but the
application resolves their results back to canonical state before returning
context.

## System shape

~~~mermaid
flowchart LR
    A["Agents and applications"] --> B["HTTP / SDK / MCP / CLI / UI"]
    B --> C["Application use cases"]
    C --> P[("Postgres<br/>canonical lifecycle")]
    P --> O["Transactional outbox"]
    O --> W["Projection and extraction workers"]
    W --> Q["Qdrant<br/>optional vector index"]
    W --> G["Graphiti<br/>optional current-state graph candidate projection"]
    Q -. "candidate IDs" .-> C
    G -. "candidate IDs" .-> C
    C --> E["Context pack<br/>cited evidence, not instructions"]
~~~

The diagram shows authority as well as data movement. Postgres is the system of
record for the lifecycle. Qdrant and Graphiti are derived projections that can
be rebuilt from canonical data when their deployment is enabled.

## Adapter coverage today

Ports keep providers replaceable, but the presence of a port is not a claim
that every capability of the provider is integrated.

| Component | Current coverage | Boundary |
| --- | --- | --- |
| Postgres | Full canonical fact, source, version, scope, visibility, review, and outbox lifecycle | The system of record |
| Qdrant | Derived vector upsert, search, and delete path | Returns candidates that require canonical hydration |
| Graphiti | Partial current-state projection and search path; an update removes the previous episode before adding the current one | Primarily exchanges canonical IDs and does not expose the provider's full source-reference, ontology, or version-history model |
| Cognee | Disabled-by-default, recall-oriented adapter path | No complete ingest, update, or exact-forget lifecycle integration |

There is no Hindsight adapter today. A future integration would need an explicit
ownership boundary between Infinity Context canonical state and Hindsight's
experiential and cognitive representations.

## Trust invariants

- **Canonical current state lives in Postgres.** Spaces, memory scopes, threads,
  facts, documents, chunks, source references, versions, lifecycle state, and
  projection work are recorded there.
- **An active fact needs source references.** A source reference provides
  provenance, not proof that the underlying claim is true.
- **Versions and tombstones are lifecycle data.** Updates advance a version;
  forget operations make a tombstone-style state change rather than silently
  rewriting history.
- **Scope is part of the memory address.** Space, memory scope, and optional
  thread boundaries are considered when storing and reading memory.
- **Derived retrieval is not authority.** A graph or vector result is a
  candidate until canonical hydration and visibility filtering accept it.
- **Prompt context is evidence.** Retrieved text is rendered with citations and
  context, rather than treated as instructions for a model to execute.
- **Suggestions are reviewable.** A suggested fact or relation can remain
  distinct from canonical memory until its lifecycle is resolved.

## Canonical write flow

1. An HTTP client, SDK, MCP tool, CLI command, or UI action submits a fact,
   document, episode, or suggestion with its intended scope.
2. An application use case validates the command against domain and lifecycle
   policies. It does not call a vector or graph provider directly.
3. The Postgres adapter records canonical rows, including source references and
   the next version or lifecycle state where applicable.
4. The same canonical transaction records idempotency and an outbox event for
   required derived work.
5. The caller receives the canonical result. It does not need to wait for an
   optional projection to become current.
6. Workers later read the outbox and update enabled derived projections using
   canonical identifiers.

This flow keeps a provider outage from becoming a hidden alternative source of
truth. It does not mean every optional index updates at the same time as the
canonical write.

## Canonical read flow

1. The application resolves the requested space, memory scope, and optional
   thread boundary.
2. It gathers eligible canonical facts and document evidence.
3. Enabled Qdrant or Graphiti adapters can return additional candidate
   canonical identifiers.
4. The application hydrates every candidate from Postgres.
5. It applies lifecycle, visibility, classification, and scope filtering, then
   removes stale or no-longer-visible candidates.
6. The context builder deduplicates and packs the remaining evidence within the
   requested budget, with source references available to the caller.

The final context pack belongs to the core application. An adapter cannot return
an authoritative prompt block by itself. Rich graph paths or provider ontology
do not automatically become canonical domain objects.

## Architecture and package boundaries

Clean Architecture, SOLID, simple DDD, and ports-and-adapters guide the
dependency direction:

~~~text
domain and application policies
  -> ports and DTO contracts
  <- adapters for storage, retrieval, and providers
  <- delivery layers: HTTP, SDK, MCP, CLI, UI
~~~

SOLID is applied in practical terms:

- **Single responsibility:** lifecycle, context packing, projection, delivery,
  and provider translation have separate reasons to change.
- **Open for extension:** another retrieval or embedding provider is an adapter
  addition rather than a use-case rewrite.
- **Substitutable adapters:** a port implementation must honor its advertised
  capability or report that the capability is unavailable.
- **Focused interfaces:** ports are split by responsibility instead of using
  one generic memory-engine interface.
- **Dependency inversion:** use cases depend on ports; the composition root
  supplies concrete Postgres, Qdrant, Graphiti, or provider adapters.

| Package or layer | Owns | Must not own |
| --- | --- | --- |
| infinity_context_core.domain | Domain entities and invariants | Framework, database, vector, graph, provider, or client imports |
| infinity_context_core.application | Use cases and policy orchestration | HTTP routing or provider SDK calls |
| infinity_context_core.ports | Narrow protocols and DTO contracts | Concrete infrastructure behavior |
| infinity_context_adapters | Postgres, Qdrant, Graphiti, and provider translations | Canonical business-policy decisions |
| infinity_context_server | HTTP delivery, configuration, auth, and composition | Domain behavior duplicated from core |
| infinity_context_sdk | HTTP client calls and client-facing types | Server internals or persistence |
| infinity_context_mcp | MCP tools and HTTP gateway behavior | Persistence and retrieval business rules |
| CLI and UI | Local operator and review experience | A bypass around application use cases |

The infinity_context_core package cannot import FastAPI, SQLAlchemy, Qdrant,
Graphiti, OpenAI, or client application code. This rule is enforced so that a
provider change stays at the boundary.

## Consistency and failure behavior

| Situation | Expected behavior |
| --- | --- |
| Canonical write succeeds, projection is delayed | The write is visible through canonical reads; the outbox retains derived work for a worker |
| Qdrant or Graphiti returns an old candidate | Canonical hydration can reject it before prompt context is rendered |
| A derived adapter is disabled or unavailable | Canonical writes and canonical reads remain the authority; retrieval can be less rich |
| A retry repeats the same command | Idempotency records let the application detect the prior operation or a conflicting payload |
| A version is stale | Update policy can return a conflict instead of silently applying an outdated change |
| A document or fact is forgotten | Canonical visibility changes first; asynchronous derived cleanup follows |

Outbox workers make eventual derived work explicit. They do not turn derived
indexes into a second lifecycle store, and they do not imply immediate cleanup
in every external system.

## Evidence boundaries

The repository contains useful engineering evidence, but its limits matter:

- Retrieval includes deterministic prepasses influenced by LoCoMo-style and
  domain-shaped cases such as people, relationships, books, food, and events.
  This is not ground-truth leakage, but it reduces confidence that current
  results transfer unchanged to unseen coding-agent workloads.
- Existing load and chaos coverage verifies lifecycle and consistency on a
  limited corpus. It is not evidence for 100,000+ memories, dozens of agents,
  or production latency under sustained contention.
- The Infinity Context versus Mem0 runner is a focused engineering canary. It
  does not measure Hindsight or Memora and cannot establish a general product
  ordering.
- Canonical hydration, scope checks, and review gates reduce some attack paths;
  they do not establish resistance to poisoned or sleeper memories. Recent
  preprints demonstrate that memory extraction, rewriting, and later retrieval
  can still be exploited in agent systems.

Accordingly, this guide does not claim universal retrieval quality, proven
large-scale performance, complete Graphiti or Cognee integration, or security
against memory poisoning.

## Security and information limits

- Treat retrieved memory and source text as untrusted evidence. They may contain
  mistakes, stale information, or hostile instructions.
- Source references establish provenance, not truth. A review workflow and
  domain judgment remain necessary.
- Scope boundaries are application data boundaries, not a substitute for
  deployment access controls, network configuration, secret handling, or backup
  policy.
- Do not store credentials, private keys, raw service tokens, or unrelated
  sensitive data as ordinary memory.
- The current project is v0.1. APIs and operational details may change, and
  deployments need their own security review.

For the wider threat model, see the research preprints
[Hidden in Memory: Sleeper Memory Poisoning](https://arxiv.org/abs/2605.15338)
and [Hijacking Agent Memory](https://arxiv.org/abs/2605.29960). They are not
benchmarks of Infinity Context; they show why provenance and review cannot be
treated as complete safety guarantees.

Cognee is disabled by default and only partially represented as an adapter
boundary. It is not part of the primary trust or retrieval claims in this guide.

## Deployment profiles

| Profile | Shape | When to use it |
| --- | --- | --- |
| lite | Postgres, server, and workers; optional provider adapters disabled | Local development and canonical lifecycle work |
| full | Adds Qdrant and Neo4j-backed graph services with configured provider features | When vector or current-state graph candidate retrieval is needed |

The full profile has more services and configuration. It is optional: canonical
lifecycle correctness does not require Qdrant, Graphiti, or Cognee.

## Further reading

- [Core Lite implementation plan](infinity-context-core-lite-plan.md)
- [Global architecture plan](infinity-context-architecture-plan.md)
- [Self-hosted team deployment](self-hosted-team-deployment.md)
- [MCP adapter guide](mcp-adapter.md)
- [ADR-0001: Core Lite boundaries](adr/ADR-0001-infinity-context-core-lite-boundaries.md)
- [ADR-0002: Postgres as canonical truth](adr/ADR-0002-postgres-canonical-truth.md)
- [ADR-0003: Canonical fact lifecycle](adr/ADR-0003-canonical-fact-lifecycle.md)
- [ADR-0004: Derived retrieval adapters](adr/ADR-0004-derived-retrieval-adapters.md)
- [ADR-0005: Capability ports for Cognee and Graphiti](adr/ADR-0005-capability-ports-cognee-graphiti.md)
