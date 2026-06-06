# ADR-0005 - Capability Ports For Cognee And Graphiti

## Status

Accepted.

## Context

Memo Stack should use ready engines instead of rebuilding every ingestion,
RAG and temporal graph capability from scratch. Cognee and Graphiti overlap in
the broad "memory" label, but they are strong in different roles:

- Cognee is a good candidate for document ingestion, RAG recall, summaries,
  chunk/vector/graph pipelines, session-to-permanent memory and multi-mode
  retrieval.
- Graphiti is a good candidate for direct temporal fact projection, evolving
  relationships, fact invalidation, episode search and time-aware project/user
  memory.
- Qdrant remains useful as a direct vector projection where Cognee is not the
  owner of the vector path or where Memo Stack needs lower-level control.

The dangerous simplification would be a single generic interface:

```python
class MemoryEnginePort(Protocol):
    async def add(...) -> ...
    async def search(...) -> ...
    async def delete(...) -> ...
```

That interface is too small. It would hide important engine capabilities,
encourage leaky adapter-specific conditionals in use cases, and make Cognee or
Graphiti either underused or accidentally canonical.

## Decision

Use capability-specific ports rather than one universal memory-engine port.
Postgres remains canonical. Cognee, Graphiti and Qdrant are infrastructure
adapters behind ports that match the capability being used.

```text
memo_stack_core.domain
  MemoryAddress
  MemoryCell / canonical fact aggregate
  EvidenceRef
  BankPolicy
  ContextPack

memo_stack_core.ports
  DocumentMemoryPort        # Cognee primary
  RagRecallPort             # Cognee primary
  SessionMemoryPort         # Cognee primary when enabled
  TemporalFactGraphPort     # Graphiti primary
  FactProjectionPort        # Graphiti primary, Cognee optional
  VectorRecallPort          # Qdrant direct or Cognee-backed
  EngineHealthPort          # all engines
  ProjectionForgetPort      # all derived projections
```

Adapters implement only the capabilities they can support well:

```text
CogneeAdapter
  DocumentMemoryPort
  RagRecallPort
  SessionMemoryPort
  ProjectionForgetPort
  EngineHealthPort

GraphitiAdapter
  TemporalFactGraphPort
  FactProjectionPort
  ProjectionForgetPort
  EngineHealthPort

QdrantAdapter
  VectorRecallPort
  ProjectionForgetPort
  EngineHealthPort
```

Use cases depend on the narrow port they need:

```text
IngestDocumentUseCase
  -> canonical document/chunk repositories
  -> DocumentMemoryPort

RememberFactUseCase
  -> canonical fact repository
  -> outbox
  -> FactProjectionPort / TemporalFactGraphPort through worker

BuildContextPackUseCase
  -> canonical repositories
  -> RagRecallPort
  -> TemporalFactGraphPort
  -> VectorRecallPort when configured
  -> canonical hydration/filtering

ForgetMemoryUseCase
  -> canonical tombstone/update
  -> ProjectionForgetPort[] through outbox
```

Capability routing is explicit deployment configuration, not hidden adapter
autodetection:

```text
Capability              Primary v1 adapter     Secondary/fallback
document_ingestion       Cognee                 canonical-only ingest
rag_chunk_recall         Cognee                 Qdrant + Postgres keyword
rag_summary_recall       Cognee                 disabled
session_memory           Cognee                 Postgres episodes
temporal_fact_graph      Graphiti direct        disabled or Zep Cloud later
fact_projection          Graphiti direct        Cognee optional, not default
vector_recall            Qdrant direct          Cognee when configured
projection_forget        all enabled adapters   canonical lifecycle filter
engine_health            all enabled adapters   safe degraded status
```

The composition root owns this routing. Use cases receive already-selected
ports. Use cases must not ask "if Cognee then..." or "if Graphiti then...".

Illustrative port shape:

```python
from typing import Protocol


class DocumentMemoryPort(Protocol):
    async def ingest_document(self, command: IngestDocumentCommand) -> DocumentIngestResult:
        """Index a canonical document into a derived document/RAG engine."""

    async def forget_document(self, command: ForgetDocumentCommand) -> ProjectionForgetResult:
        """Remove derived document/chunk state by canonical ids."""


class RagRecallPort(Protocol):
    async def recall_chunks(self, query: RecallQuery) -> tuple[EvidenceChunk, ...]:
        """Return evidence candidates. Caller must hydrate and policy-filter."""

    async def recall_summaries(self, query: RecallQuery) -> tuple[EvidenceSummary, ...]:
        """Return summary candidates. Caller must hydrate and policy-filter."""


class TemporalFactGraphPort(Protocol):
    async def upsert_fact_episode(self, fact: CanonicalFactProjection) -> ProjectionWriteResult:
        """Project an active canonical fact into a temporal graph engine."""

    async def invalidate_fact(self, fact_id: str) -> ProjectionWriteResult:
        """Delete or invalidate a canonical fact projection."""

    async def search_temporal_facts(
        self, query: TemporalFactQuery
    ) -> tuple[TemporalFactHit, ...]:
        """Return canonical ids only. Caller must hydrate and resolve lifecycle."""
```

The current `VectorMemoryPort` and `GraphMemoryPort` are acceptable for Core
Lite, but the next architecture step should split them along these capability
boundaries before adding Cognee.

## Anti-Corruption Boundary

Cognee, Graphiti and Qdrant concepts must be translated at adapter boundaries:

```text
Cognee dataset/user/node_set/search_type
  -> Memo Stack space/profile/bank/evidence DTOs

Graphiti group_id/episode_uuid/fact edge
  -> Memo Stack canonical ids and temporal fact DTOs

Qdrant collection/payload/point_id
  -> Memo Stack chunk ids and vector candidate DTOs
```

No external SDK type crosses into `memo_stack_core`. No external engine id becomes a
public API id unless Memo Stack Core minted or mapped it. Adapter-specific metadata
can appear only in safe diagnostics or projection records.

## Context Compiler Ownership

The final prompt context is not an adapter result. It is compiled by Memory
Core:

```text
canonical facts
  + Cognee RAG evidence
  + Graphiti temporal fact hits
  + Qdrant vector chunks
  -> canonical hydration
  -> policy and lifecycle filtering
  -> dedupe by canonical source/evidence lineage
  -> authority and freshness ordering
  -> token budget packing
  -> ContextPack
```

Adapters return candidates. The context compiler decides what is current,
allowed, trusted and worth spending tokens on.

## Scalability Contract

This ADR is not only about naming ports. It also defines how the platform should
scale when Cognee, Graphiti, Qdrant, Postgres, workers and future SaaS tenants
are all active.

### Bounded contexts

Keep these responsibilities separate even if they live in one Python repo in
Core Lite:

```text
canonical lifecycle
  facts, documents, chunks, suggestions, tombstones, evidence refs

document/RAG enrichment
  document ingestion, chunking, summaries, semantic recall

temporal graph projection
  evolving facts, relations, invalidation, temporal search

vector projection
  embeddings, vector indexes, low-level chunk candidates

context compilation
  hydration, policy, dedupe, ranking, budget packing

policy/governance
  auth scope, data classification, purpose permissions, retention

operations
  health, capabilities, lag, repair, rebuild, benchmark isolation
```

The same class or use case must not own more than one of these contexts unless
it is a thin orchestration layer. For example, `BuildContextUseCase` can
orchestrate recall sources, but it must not embed text, mutate Graphiti, create
Cognee datasets or decide retention policy.

### Read plane and write plane

Writes and reads must stay intentionally asymmetric:

```text
write plane
  validate command
  -> canonical transaction in Postgres
  -> outbox projection jobs
  -> async adapters with idempotency and version checks

read plane
  resolve scope and policy
  -> fetch canonical candidates
  -> fetch adapter candidates
  -> hydrate every derived hit from Postgres
  -> drop stale/forbidden/deleted data
  -> dedupe/rerank/budget
  -> ContextPack
```

Never add a shortcut where Cognee, Graphiti or Qdrant returns prompt-ready
memory directly to an API response. This keeps tenant isolation, fact lifecycle,
forget semantics and scoring rules in Memo Stack Core.

### Capability routing manifest

The composition root should expose one effective routing manifest at startup and
through `/v1/capabilities`:

```text
capability
primary_adapter
secondary_adapters
enabled
health
degraded_reason
external_ai_allowed
projection_lag
adapter_version
schema_version
config_fingerprint
```

This gives clients and agents a stable way to understand what the server can do
without learning Cognee, Graphiti or Qdrant internals. It also makes local mode,
CI mode, full-memory mode and future SaaS mode debuggable.

### Workload classes and budgets

All work should be assigned to a workload class:

```text
prompt_path
interactive_write
document_ingestion
fact_projection
repair_rebuild
benchmark
admin_export
```

Rules:

- prompt path has the strictest latency budget and cannot start heavy external
  indexing;
- ingestion/projection workers have per-space/profile fairness keys;
- repair/rebuild jobs run behind normal interactive traffic;
- benchmark jobs must run in isolated scopes and never consume production
  prompt-path capacity;
- worker backlog and oldest job age are part of capability health.

### Tenant and scope evolution

Core Lite uses `space_id` and `profile_id`. Future team/SaaS mode will add
tenant/workspace/principal concepts. The adapter contracts must already behave
as if those will exist:

- public ids are opaque and globally safe to move across adapters;
- adapter-local ids include hard scope in their mapping layer;
- slugs, tags, categories and human-readable labels are never isolation
  boundaries;
- repository queries and adapter hydration use a resolved scope object, not raw
  caller-provided strings;
- cross-profile context is an explicit query mode with labelled sections, not a
  side effect of broad search.

### Kill switches and degraded modes

Every external engine must be independently disableable without breaking
canonical memory:

```text
Cognee disabled
  documents remain canonical; RAG recall degrades to Postgres/Qdrant/keyword

Graphiti disabled
  facts remain canonical; temporal graph recall is skipped

Qdrant disabled
  semantic chunk recall degrades to Cognee or keyword search

External AI disabled
  no embeddings/extraction calls; canonical CRUD and local keyword context work
```

A disabled adapter must report a degraded or unavailable capability and a safe
reason. It must not pretend that derived projections are current.

### Rebuild and portability

The platform must be able to throw away any derived engine and rebuild it from
canonical Postgres:

- rebuild can target one space, profile, bank, document, fact type or adapter;
- rebuild starts with a dry-run plan and expected projection counts;
- running rebuild does not make stale derived results visible because reads
  still hydrate through canonical lifecycle;
- adapter migrations are projection migrations, not domain migrations;
- export/import is based on canonical data, not Cognee/Graphiti/Qdrant dumps.

### Context compiler fitness rules

The context compiler is the quality gate. It must satisfy these invariants:

- no item enters rendered context without canonical hydration or an explicit
  canonical-only source;
- no deleted, superseded, expired, restricted or wrong-scope row is rendered;
- raw adapter scores are never directly mixed as final ranking;
- repeated projections of the same evidence do not increase authority;
- every rendered item can explain `profile_id`, source refs and retrieval
  source in diagnostics;
- token budget is deterministic for the same query and canonical state.

## Current Core Lite Gap To Target

The current implementation still uses broad `VectorMemoryPort`,
`GraphMemoryPort`, `EmbeddingPort`, `AdapterCapabilities` and
`BuildContextUseCase` contracts. This is acceptable for Core Lite, because the
only derived engines are direct Qdrant, direct Graphiti and noop adapters.

This broad shape must stop before Cognee enters prompt-path RAG. At that point:

- broad method flags like `supports_search` must become capability descriptors
  such as `rag_chunk_recall`, `temporal_fact_graph`, `projection_forget` and
  `session_memory`;
- `BuildContextUseCase` should be split into candidate collectors, canonical
  hydration, policy filtering, dedupe/rerank and packing;
- Cognee summaries must enter context as derived evidence, not canonical facts;
- outbox jobs need workload class, fairness key, idempotency key and canonical
  aggregate version before large document ingestion or auto-memory;
- team/SaaS mode needs a resolved `MemoryScope` / `ReadScope` value object
  shared by repositories, use cases, adapter DTOs, MCP and legacy routes.

In short: generic ports are a Core Lite bootstrap tactic, not the platform
architecture.

## Public Contract And Agent Consistency

Agents, SDKs and MCP clients should not infer platform behavior from adapter
names. Public responses should expose stable Memo Stack semantics:

- `api_version` and contract version;
- resolved scope, profile set and thread scope;
- canonical lifecycle status;
- operation id for async work;
- projection freshness by capability;
- safe diagnostics without raw memory text;
- recommended next action when memory is degraded or still indexing.

Read APIs should support explicit consistency modes:

```text
canonical_only
  returns only Postgres-backed memory; fastest and safest fallback

best_effort
  returns canonical memory plus currently available projections

require_fresh_projection
  waits or fails when required projections are stale
```

Default prompt-path behavior should be `best_effort` with visible freshness
diagnostics. Admin, benchmark and compliance flows can ask for stricter modes.

MCP write tools should remain conservative:

- remember creates durable facts only with source refs and idempotency;
- update requires `fact_id` and `expected_version`;
- forget requires concrete ids and never broad matching deletes;
- auto-memory can create suggestions or candidate facts before promotion;
- agents treat retrieved memory as evidence, never as system instructions.

## Step By Step Implementation Roadmap

This is the safe order for moving from Core Lite to the full Cognee + Graphiti +
Qdrant architecture.

### Phase 0 - Freeze current guarantees

Goal: make the current Core Lite behavior explicit before changing adapters.

Do:

- keep Postgres as canonical truth for facts, documents, chunks and lifecycle;
- keep Qdrant and Graphiti derived-only;
- keep every context item hydrated through Postgres before rendering;
- keep MCP write operations conservative.

Gate:

- import-boundary tests pass;
- current memory quality e2e passes in canonical/noop mode;
- context does not leak deleted, restricted or wrong-profile rows.

### Phase 1 - Add capability-shaped contracts

Goal: introduce target ports without replacing working adapters yet.

Do:

- add `memo_stack_core.ports.capabilities`;
- define `DocumentMemoryPort`, `RagRecallPort`, `TemporalFactGraphPort`,
  `FactProjectionPort`, `VectorRecallPort`, `ProjectionForgetPort` and
  `EngineHealthPort`;
- add DTOs for candidate hits, projection freshness and capability health;
- keep existing `VectorMemoryPort` and `GraphMemoryPort` as compatibility
  wrappers during migration.

Gate:

- no external SDK imports in `memo_stack_core`;
- no use case accepts Cognee/Graphiti/Qdrant ids directly;
- `/v1/capabilities` can describe capabilities, not only adapter method flags.

### Phase 2 - Split context compilation

Goal: keep prompt context quality in Memo Stack Core, not in adapters.

Do:

- split `BuildContextUseCase` into candidate collectors, hydrator, policy
  filter, deduper, ranker and packer;
- make adapter collectors return candidates only;
- add consistency mode to context queries: `canonical_only`, `best_effort`,
  `require_fresh_projection`;
- include projection freshness diagnostics in context results.

Gate:

- same query in canonical-only mode never calls embeddings, Cognee, Graphiti or
  Qdrant;
- best-effort mode degrades safely when any adapter is down;
- mixed scores are reranked by Memo Stack Core, not raw adapter scores.

### Phase 3 - Harden outbox and projection lifecycle

Goal: make async projection reliable before adding heavier engines.

Do:

- add workload class, fairness key, idempotency key and aggregate version to
  projection jobs;
- make stale worker events no-op when canonical version changed;
- add projection lag diagnostics by capability;
- add dead-letter handling for poison jobs.

Gate:

- retrying a worker job does not duplicate derived data;
- deleting or updating a fact hides it from context before projection cleanup
  finishes;
- diagnostics show backlog and oldest pending job without raw memory text.

### Phase 4 - Migrate direct Graphiti to temporal capability

Goal: keep Graphiti focused on temporal facts and relations.

Do:

- move direct Graphiti adapter from `GraphMemoryPort` toward
  `TemporalFactGraphPort` and `FactProjectionPort`;
- keep Graphiti `group_id` derived from hard scope only;
- return canonical fact ids from temporal search;
- keep direct Graphiti independent from Cognee's optional Graphiti support.

Gate:

- stale Graphiti hits are dropped by canonical hydration;
- Graphiti disabled mode keeps canonical facts working;
- temporal conflict resolution prefers Memo Stack Core lifecycle.

### Phase 5 - Add Cognee behind document/RAG capabilities

Goal: use Cognee for document memory without making the platform Cognee-shaped.

Do:

- add `CogneeAdapter` behind `DocumentMemoryPort`, `RagRecallPort` and optional
  `SessionMemoryPort`;
- map Cognee dataset/user/node_set/search_type to Memo Stack DTOs in the
  adapter only;
- treat Cognee summaries as derived evidence;
- gate external AI processing by purpose policy.

Gate:

- Cognee disabled mode falls back to canonical/Qdrant/keyword recall;
- Cognee search results include source refs or are excluded from final context;
- no Cognee SDK type crosses into `memo_stack_core` or public API.

### Phase 6 - Enable auto-memory as policy-driven suggestions

Goal: support auto-memory without letting LLM extraction overwrite canonical
truth.

Do:

- route transcript/document candidates through classifier policy;
- create suggestions or candidate facts first;
- require promotion policy before durable shared facts;
- preserve evidence lineage and ontology version.

Gate:

- agent-generated summaries cannot confirm themselves;
- private/session facts are not promoted to shared facts accidentally;
- benchmark scopes stay non-promotable and purgeable.

### Phase 7 - Prepare team/SaaS mode

Goal: scale scopes and permissions before multi-user sharing.

Do:

- introduce resolved `MemoryScope` / `ReadScope`;
- centralize visibility guard for list, context, export, diagnostics, MCP and
  legacy routes;
- add principal/workspace/profile grants;
- make projection ids deterministic from canonical ids plus scope.

Gate:

- cross-tenant/profile leak tests pass across every read path;
- scoped tokens cannot list, read, update, forget, export or diagnose outside
  grants;
- context cache key includes scope, policy version, ontology version and
  canonical commit cursor.

## Implementation Work Packages

Use these packages as the concrete work map. Since this repo is being developed
directly on `main`, each package should be a small conventional commit series
with tests, not a separate pull request.

### WP1 - Capability contracts

Files:

```text
packages/memo_stack_core/memo_stack_core/ports/capabilities.py
packages/memo_stack_core/memo_stack_core/application/dto.py
packages/memo_stack_core/memo_stack_core/ports/__init__.py
tests/unit/test_import_boundaries.py
tests/unit/test_health_capabilities.py
```

Work:

- add capability enums and DTOs;
- add narrow Protocol ports;
- keep existing broad ports as compatibility layer;
- update import-boundary tests to protect `memo_stack_core`.

Done when:

- `memo_stack_core` has no SDK imports;
- capabilities can describe `rag_chunk_recall`, `temporal_fact_graph`,
  `vector_recall`, `projection_forget` and `engine_health`.

### WP2 - Context compiler split

Files:

```text
packages/memo_stack_core/memo_stack_core/application/use_cases/build_context.py
packages/memo_stack_core/memo_stack_core/application/context_packer.py
packages/memo_stack_core/memo_stack_core/application/context_collectors.py
packages/memo_stack_core/memo_stack_core/application/context_hydration.py
packages/memo_stack_core/memo_stack_core/application/context_policy.py
tests/unit/test_context_packer.py
tests/unit/test_legacy_and_context_api.py
```

Work:

- extract canonical, vector, graph and later RAG candidate collectors;
- add explicit hydration step for every derived candidate;
- add consistency mode to `BuildContextQuery`;
- keep output DTO backward compatible for Client App until SDK/API version
  is bumped.

Done when:

- `canonical_only` never calls external adapters;
- `best_effort` survives any adapter outage;
- context still drops wrong-profile, restricted, deleted and stale hits.

### WP3 - Capability diagnostics API

Files:

```text
packages/memo_stack_server/memo_stack_server/composition.py
packages/memo_stack_server/memo_stack_server/api/v1/capabilities.py
packages/memo_stack_server/memo_stack_server/diagnostics.py
packages/memo_stack_sdk/memo_stack_sdk/__init__.py
packages/memo_stack_mcp/memo_stack_mcp/application/service.py
tests/unit/test_health_capabilities.py
tests/unit/test_mcp_adapter.py
```

Work:

- expose capability-shaped status instead of only adapter method flags;
- include safe config fingerprint, projection lag and degraded reasons;
- keep MCP `memory_status` readable for agents;
- never include raw memory text or secrets in diagnostics.

Done when:

- API, SDK and MCP can show which capability is active and why it is degraded;
- prompt-path callers can detect stale projections.

### WP4 - Projection lifecycle hardening

Files:

```text
packages/memo_stack_core/memo_stack_core/domain/events.py
packages/memo_stack_core/memo_stack_core/ports/unit_of_work.py
packages/memo_stack_adapters/memo_stack_adapters/postgres/models.py
packages/memo_stack_adapters/memo_stack_adapters/postgres/repositories.py
packages/memo_stack_adapters/memo_stack_adapters/postgres/migrations/
packages/memo_stack_server/memo_stack_server/worker.py
tests/unit/test_worker_eval.py
tests/integration/test_outbox_worker.py
```

Work:

- add workload class, fairness key and aggregate version checks;
- make worker retries idempotent;
- add dead-letter state for poison jobs;
- keep canonical lifecycle visible immediately even if projections lag.

Done when:

- update/delete hides old memory from context before derived cleanup finishes;
- repeated worker runs do not duplicate Qdrant/Graphiti/Cognee projections.

### WP5 - Direct Graphiti capability adapter

Files:

```text
packages/memo_stack_adapters/memo_stack_adapters/graphiti/adapter.py
packages/memo_stack_adapters/memo_stack_adapters/noop/adapters.py
packages/memo_stack_server/memo_stack_server/composition.py
tests/unit/test_provider_adapters.py
tests/unit/test_legacy_and_context_api.py
```

Work:

- implement `TemporalFactGraphPort` and `FactProjectionPort`;
- keep `GraphMemoryPort` wrapper until callers migrate;
- return canonical fact ids only;
- report Graphiti version and capability health safely.

Done when:

- Graphiti disabled mode is safe;
- stale Graphiti ids are counted and dropped;
- direct Graphiti and future Cognee Graphiti mode cannot both own fact truth.

### WP6 - Cognee document/RAG adapter

Files:

```text
packages/memo_stack_adapters/memo_stack_adapters/cognee/
packages/memo_stack_server/memo_stack_server/config.py
packages/memo_stack_server/memo_stack_server/composition.py
packages/memo_stack_core/memo_stack_core/application/context_collectors.py
tests/unit/test_provider_adapters.py
tests/e2e/test_memory_quality_e2e.py
```

Work:

- add Cognee behind `DocumentMemoryPort`, `RagRecallPort` and optional
  `SessionMemoryPort`;
- map Cognee ids and search modes inside the adapter only;
- reject Cognee results without source refs unless explicitly allowed as
  untrusted summaries;
- keep external AI policy gates before sending text to Cognee pipelines.

Done when:

- Cognee can be disabled without breaking canonical memory;
- RAG recall improves document search while final context remains Memo Stack Core
  owned.

### WP7 - Auto-memory and team readiness

Files:

```text
packages/memo_stack_core/memo_stack_core/application/use_cases/suggestions.py
packages/memo_stack_core/memo_stack_core/ports/auth.py
packages/memo_stack_server/memo_stack_server/auth_scope.py
packages/memo_stack_server/memo_stack_server/api/v1/
packages/memo_stack_mcp/memo_stack_mcp/
tests/unit/test_suggestions_api.py
tests/unit/test_admin_tokens.py
tests/e2e/test_memo_stack_mcp_e2e.py
```

Work:

- route auto-memory to suggestions or candidate facts first;
- add resolved `MemoryScope` / `ReadScope` across API, SDK and MCP;
- keep broad forget/delete unavailable to agents;
- enforce scoped tokens across all read/write/diagnostic routes.

Done when:

- agents can save/update/forget facts safely through MCP;
- cross-profile and future cross-tenant leak count is zero in e2e.

## Execution Protocol

Each work package should follow the same delivery shape:

1. Add or update contracts first.
2. Add noop/fake adapters next.
3. Add import-boundary and contract tests before real provider code.
4. Wire composition root behind disabled-by-default config.
5. Add real adapter behavior.
6. Add diagnostics and rollback/kill-switch coverage.
7. Enable the capability only after its gate is green.

Do not mix Cognee runtime behavior, context compiler refactor and outbox schema
changes in one commit slice. Those are separate failure domains.

Main branch rules:

- keep `main` runnable after every commit;
- use conventional commits, for example `feat(memory): add capability DTOs`;
- commit docs/contract changes separately from runtime behavior;
- do not commit generated caches, local databases, `.e2e-artifacts` or venv
  changes;
- before risky runtime changes, make sure the previous commit has passed the
  minimal verification commands below;
- if a gate fails, fix forward in the next commit or revert only the failed
  commit.

Minimal verification commands:

```bash
make memo-stack-lint
make memo-stack-test-application
make memo-stack-test-integration
make memo-stack-eval
make memo-stack-doctor
```

Run full tests when disk/CI capacity allows:

```bash
make memo-stack-test-unit
make memo-stack-test-e2e
```

Rollback rule:

- contract-only commits roll back by reverting the package change;
- adapter commits must have a config kill switch;
- schema/outbox commits must be additive and safe with old workers;
- prompt-path commits require `canonical_only` or existing local fallback to keep
  answers working while derived memory is disabled.

The first implementation slice should be WP1 + capability diagnostics only.
Do not start WP6 Cognee integration until WP1, WP2 and WP3 are done.

### Immediate first slice

Start with three small commits on `main`:

1. Commit A - capability DTOs only.
   Files: `ports/capabilities.py`, `application/dto.py`,
   `tests/unit/test_import_boundaries.py`.
   No runtime behavior change.

2. Commit B - capability diagnostics shape.
   Files: `use_cases/get_capabilities.py`, `api/v1/capabilities.py`,
   `memo_stack_sdk/__init__.py`, `memo_stack_mcp/application/service.py`,
   `tests/unit/test_health_capabilities.py`, `tests/unit/test_mcp_adapter.py`.
   Keep old adapter fields for backward compatibility.

3. Commit C - context consistency enum without adapter changes.
   Files: `application/dto.py`, `use_cases/build_context.py`,
   `tests/unit/test_legacy_and_context_api.py`.
   Add `canonical_only` behavior first; leave `best_effort` as current default.

Do not add a Cognee dependency, new database migration or prompt-path behavior
change in these commits. Approx total: 500-900 lines.

## Non-Goals

- Do not fork Cognee as Memo Stack core.
- Do not expose Cognee datasets, Graphiti group ids or Qdrant collections in the
  Memo Stack public API.
- Do not make Cognee's graph extraction or Graphiti's edge invalidation the
  canonical lifecycle.
- Do not start heavy document ingestion or graph extraction in the live prompt
  path.
- Do not require Cognee, Graphiti or Qdrant for local canonical CRUD to work.

## SOLID Constraints

- Single Responsibility: each port has one reason to change. Cognee document
  ingestion changes do not force Graphiti temporal fact changes.
- Interface Segregation: use cases should not depend on methods they do not use.
- Dependency Inversion: application code depends on Memo Stack contracts,
  not Cognee, Graphiti, Qdrant, Neo4j or vector-store SDKs.
- Open/Closed: adding a Cognee-backed RAG path or a new temporal graph engine
  should add an adapter, not change canonical lifecycle use cases.
- Liskov: a degraded adapter must preserve the port contract. It can return a
  degraded result, but cannot return unhydrated private/deleted memory as valid
  context.

## Edge Cases And Guard Conditions

### 1. Adapter overlap

Cognee may also expose graph retrieval and Graphiti may also return text-like
evidence. The composition root must choose a primary adapter per capability.

Rule:

```text
one primary adapter per capability per deployment profile
optional secondary adapters only through explicit fan-out/fan-in policy
```

Do not let both Cognee and Graphiti independently write the same canonical fact
projection unless the projection id, source id and conflict strategy are
explicitly deduplicated.

### 2. Canonical truth drift

Cognee or Graphiti may return stale ids after a canonical update or forget.

Rules:

- all retrieval candidates are canonical ids or evidence refs, not final memory;
- every derived hit is hydrated from Postgres before context rendering;
- deleted, superseded, restricted or policy-denied canonical rows are dropped;
- diagnostics count stale drops per adapter.

### 3. Forget propagation

Forget is not one delete call. A document or fact can have derived chunks,
summaries, graph nodes, graph edges, embeddings and cached context.

Rules:

- canonical tombstone/update commits first;
- outbox emits projection forget jobs per affected adapter;
- projection forget jobs are idempotent;
- context reads must respect canonical lifecycle even while projection cleanup is
  still pending;
- hard delete must include a dependency graph for derived artifacts before team
  or remote mode.

### 4. Temporal semantics conflict

Cognee temporal search is useful for event/document timelines. Graphiti is
primary for evolving facts and invalidation.

Rules:

```text
document/event temporal recall -> Cognee temporal/RAG capability
canonical fact supersession -> Memo Stack Core lifecycle + Graphiti projection
current truth -> canonical lifecycle resolver, not engine-specific recency
```

If Cognee and Graphiti disagree, the context compiler must surface a safe
diagnostic and prefer canonical Memo Stack Core lifecycle/authority rules.

### 5. Scope mapping mismatch

Cognee may use datasets/users/node sets. Graphiti uses group ids. Memo Stack
uses space/profile/bank and later tenant/workspace.

Rules:

- mapping is adapter-local;
- use cases never accept Cognee dataset ids or Graphiti group ids;
- Graphiti `group_id` is derived from hard scope, not category/tag;
- Cognee dataset/node-set mapping must not be treated as an ACL boundary unless
  Memo Stack Core policy also allows it.

### 6. Retrieval mode leakage

Cognee has multiple search modes. Some modes can ignore grouping filters or use
different result shapes.

Rules:

- each Cognee retrieval mode must be declared in adapter capabilities;
- unsupported filter combinations fail closed or degrade;
- RAG/completion outputs are treated as untrusted summaries until backed by
  canonical evidence refs;
- source text from documents is evidence, not a canonical policy/fact by itself.

### 7. Double extraction and self-reinforcement

If Cognee extracts a summary and Graphiti extracts a fact from that summary, the
same source can appear as multiple independent evidence items.

Rules:

- preserve evidence lineage;
- repeated derived outputs from the same source do not increase authority;
- agent-generated summaries cannot confirm themselves;
- accepted facts require canonical source refs and authority classification.

### 8. Partial engine outage

Cognee, Graphiti, Qdrant, OpenAI embeddings or Neo4j can be unavailable.

Rules:

- canonical writes still succeed when derived adapters are disabled, unless the
  policy explicitly requires a projection;
- context building degrades by capability, not globally;
- answer path has strict latency budgets and falls back to canonical keyword
  facts/chunks;
- health reports adapter readiness by capability.

### 9. Cost and latency spikes

Cognee ingestion and Graphiti graph extraction can trigger LLM/embedding calls.

Rules:

- long-running enrichment is async;
- prompt-path context does not start heavy indexing;
- worker jobs have budgets, retries and circuit breakers;
- local/private mode can disable external AI processing while keeping canonical
  storage.

### 10. Data classification

Restricted or unknown data must not be sent to external embeddings or LLM-based
extractors just because a derived adapter can process it.

Rules:

- Memo Stack Core policy decides whether a source can be processed externally;
- adapter receives already-approved work only;
- adapter diagnostics must not include raw memory text;
- restricted data can remain canonical-only.

### 11. Version and schema drift

Cognee and Graphiti can change their internal schemas, SDK versions or search
payloads.

Rules:

- adapter maps external payloads to stable Memo Stack DTOs;
- adapter contract tests cover all enabled capabilities;
- no external SDK types cross into `memo_stack_core`;
- capabilities include adapter version/schema when available.

### 12. Benchmark contamination

Synthetic e2e memories can pollute live project memory.

Rules:

- benchmarks run in isolated spaces/profiles;
- benchmark sources are marked non-promotable;
- cleanup uses canonical forget plus projection cleanup;
- context tests assert synthetic markers do not appear outside benchmark scope.

### 13. Capability fan-in duplicates

Cognee RAG, Qdrant vector recall and Graphiti search may surface the same source
through different candidates.

Rules:

- dedupe by canonical fact id, chunk id, document id and evidence lineage;
- do not count multiple projections of the same evidence as independent support;
- preserve the strongest safe retrieval reason in diagnostics;
- context pack ordering should prefer authority and applicability over raw score.

### 14. Capability fan-out write ordering

A canonical fact update can require Graphiti invalidation, Cognee cleanup and
Qdrant vector deletion.

Rules:

- outbox events are derived from one canonical transaction;
- projection workers may run in any order;
- every projection event has an idempotency key;
- projection event payloads include canonical version or tombstone revision;
- stale worker events are skipped if the canonical version has moved on.

### 15. Rebuild and repair

Derived engines can be corrupted, dropped or upgraded.

Rules:

- rebuild starts from canonical Postgres, never from another projection;
- projection version is recorded per adapter and per candidate where practical;
- repair can rebuild one space/profile/bank without global downtime;
- context reads continue through canonical fallback during rebuild.

### 16. Multi-tenant future migration

Core Lite currently centers on space/profile. Future team/SaaS mode will add
tenant/workspace.

Rules:

- new ports must not assume globally unique human-readable slugs;
- adapter-local ids must include hard scope or use canonical ids;
- no adapter can use category/tag as a tenant boundary;
- cross-space recall requires an explicit MemoryViewPolicy later.

### 17. Capability-specific security policy

Document ingestion, vector embedding and temporal graph extraction have different
privacy and cost risks.

Rules:

- policy is resolved by purpose: `document_ingestion`, `embedding`,
  `temporal_fact_projection`, `rag_recall`, `context_render`;
- a source allowed for canonical storage is not automatically allowed for
  external extraction or embedding;
- prompt-path retrieval must not trigger new external processing;
- adapter capability diagnostics expose purpose availability without raw text.

### 18. Engine-specific score incompatibility

Cognee, Graphiti and Qdrant scores are not comparable.

Rules:

- adapter scores are local signals only;
- Memo Stack Core normalizes candidates into coarse tiers or reranks after hydration;
- never sort final context by raw mixed-engine scores alone;
- diagnostics should show source adapter and normalization reason.

### 19. Session-to-permanent promotion

Cognee may be useful for session memory. Permanent shared memory still requires
Memo Stack Core policy.

Rules:

- session memory is not automatically team/shared memory;
- session-to-permanent promotion creates canonical candidates or suggestions;
- private-to-shared promotion requires explicit policy/review later;
- session cleanup must not delete already-promoted canonical memory.

### 20. Adapter version skew

Cognee can lag Graphiti upstream. Direct Graphiti can move faster than Cognee's
integration.

Rules:

- Graphiti direct adapter is versioned independently from Cognee adapter;
- Cognee Graphiti integration is not assumed to replace direct Graphiti;
- feature flags declare which temporal path is active;
- contract tests pin expected behavior, not internal SDK shapes.

### 21. Capability route drift

API and worker processes can start with different configs, for example API uses
Cognee for RAG while worker projects only Qdrant.

Rules:

- API, worker and admin CLI expose a safe config fingerprint;
- workers refuse jobs requiring a capability missing in their runtime config;
- `/v1/capabilities` reports the effective runtime, not only static env values;
- deploy checks compare API and worker capability manifests before enabling
  prompt-path adapters.

### 22. Backlog and fairness collapse

One huge import or broken adapter can fill the outbox and make interactive
memory feel stale.

Rules:

- projection jobs include workload class and scope fairness key;
- worker claims reserve capacity per workload class;
- stale recall diagnostics include projection lag when relevant;
- poison jobs move to dead-letter after bounded retries and do not block newer
  independent scopes.

### 23. Ontology and category evolution

Facts, categories and tags will evolve. A tag rename must not corrupt adapter
scope or Graphiti groups.

Rules:

- categories/tags are metadata and retrieval hints, not physical partitions;
- ontology version is stored with extracted/promoted facts when used;
- category changes enqueue reclassification or projection update jobs when they
  affect retrieval;
- old category labels remain searchable through aliases until migration
  completes.

### 24. Prompt cache leakage

Future caching can accidentally reuse a context pack across profiles, policy
versions or fact updates.

Rules:

- context cache key includes principal/scope, profile set, policy version,
  canonical commit cursor, ontology version and retrieval mode;
- cached context is invalidated by fact/document lifecycle changes;
- cached rendered text is treated as derived data and excluded from canonical
  export unless explicitly requested.

### 25. Adapter-managed summaries become facts

Cognee can produce high-quality summaries, but summaries are still derived
outputs.

Rules:

- adapter summaries can be shown as evidence only when source refs are present;
- permanent facts are created through Memo Stack Core suggestion/review or
  auto-memory policy;
- summary text cannot supersede a canonical fact without a lifecycle command;
- summary confidence is separate from canonical fact confidence.

## Implementation Order

1. Keep current Core Lite ports and adapter behavior stable.
2. Add capability routing config and safe capability diagnostics before adding
   any Cognee runtime dependency.
3. Add capability DTOs and ports in `memo_stack_core.ports.capabilities` or split the
   current `ports/adapters.py` once the first Cognee adapter starts.
4. Add no-op capability adapters and import-boundary tests first.
5. Add Cognee adapter for document ingestion/RAG recall behind
   `DocumentMemoryPort` and `RagRecallPort`.
6. Keep direct Graphiti adapter for temporal facts, but migrate it from generic
   `GraphMemoryPort` toward `TemporalFactGraphPort`.
7. Update `BuildContextUseCase` into a `ContextPack` compiler that merges
   canonical facts, Cognee evidence and Graphiti temporal hits under budget.
8. Add projection forget fan-out, reindex/repair commands and per-adapter lag
   diagnostics.

## Architecture Fitness Checks

These checks should become tests or `doctor` assertions as the adapters mature:

- `memo_stack_core` imports no Cognee, Graphiti, Qdrant, OpenAI, Neo4j or HTTP SDK
  modules;
- use cases depend on capability ports, not concrete adapters;
- composition root is the only place that selects concrete adapters for a
  capability;
- every adapter candidate returned to context build is hydrated through
  canonical repositories before rendering;
- every public read path uses the same visibility guard for deleted, superseded,
  restricted and wrong-scope data;
- prompt-path context build does not enqueue document ingestion, embeddings or
  graph extraction;
- disabled external AI mode sends no memory text to embedding or LLM providers;
- projection rebuild can restore one adapter from canonical data without using
  another derived adapter as source;
- capability diagnostics are redacted and contain no raw memory text or secrets;
- multi-profile context keeps profile labels and drops wrong-profile adapter
  hits;
- adapter contract tests cover healthy, disabled, degraded, stale-hit and
  version-mismatch states;
- performance tests enforce separate budgets for prompt path, ingestion,
  projection and repair.

## Tests Required Before Enabling Cognee In A Prompt Path

- import-boundary test: `memo_stack_core` imports no Cognee/Graphiti/Qdrant SDKs;
- adapter contract tests for each capability;
- scope-isolation tests across two spaces and two profiles;
- stale projection tests: deleted/superseded rows returned by Cognee/Graphiti are
  dropped after canonical hydration;
- forget propagation tests for fact, document and thread cleanup;
- partial outage tests for Cognee down, Graphiti down, embeddings down;
- latency budget test for prompt-path context building;
- source lineage tests preventing summary/self-reinforcement from increasing
  authority;
- mixed-score rerank test proving raw Cognee/Graphiti/Qdrant scores do not
  directly order final context;
- projection rebuild test from canonical data after deleting one derived index;
- session-to-permanent promotion test proving session memory is not silently
  promoted to shared memory;
- benchmark-space isolation tests.

## Decision Options Considered

1. Capability ports + adapters per role.
   🎯 9   🛡️ 9   🧠 7
   Approx changes: 2500-5000 lines for the adapter contracts, no-op adapters,
   Cognee adapter skeleton and contract tests.

2. One generic `MemoryEnginePort`.
   🎯 6   🛡️ 6   🧠 4
   Approx changes: 800-1800 lines. Faster, but hides Cognee/Graphiti strengths
   and creates leaky conditionals.

3. Fork Cognee and make it the platform core.
   🎯 6   🛡️ 6   🧠 9
   Approx changes: 6000-15000 lines plus ongoing fork maintenance. This makes
   Cognee internals part of our domain boundary and increases upgrade risk.

## Consequences

- Memo Stack can use Cognee without becoming Cognee-shaped.
- Memo Stack can use direct Graphiti without rebuilding Cognee's document
  pipeline.
- Adapters stay replaceable and testable.
- Context quality becomes a Memo Stack Core responsibility, not an engine side
  effect.
- The architecture remains ready for future engines, including Zep Cloud,
  self-hosted Graphiti, Cognee, Qdrant, pgvector or another RAG backend.
