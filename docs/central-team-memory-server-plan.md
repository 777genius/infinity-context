# Central Team Memory Server Plan

Status: proposed architecture plan

This document fixes the target architecture for a shared team memory server in
Memo Stack using Clean Architecture, simple DDD, SOLID and port/adapter
boundaries. It is intentionally scoped to architecture and implementation
order. It does not replace the Core Lite plan or ADR-0005. It adds the
team/server layer around the existing canonical memory lifecycle.

## Executive Decision

Build a Central Team Memory Server where the remote server is the canonical
source of truth for team memory. Local agents, MCP plugins, SDK clients and
desktop apps are clients. They may cache safe read results, but they do not own
durable team memory.

Recommended option:

```text
Option A: Central server as source of truth
Confidence: 10/10
Reliability: 9/10
Complexity: 5/10
Approximate implementation size: 2500-6000 LOC for MVP team mode
```

Why:

- fits the current architecture where Postgres is canonical;
- avoids conflict-heavy local-first sync in v1;
- lets Graphiti, Cognee and Qdrant remain replaceable projection adapters;
- gives teams one obvious place for permissions, audit, backup and review;
- can still support local development through the same API.

Alternatives:

```text
Option B: Local-first sync with conflict merge
Confidence: 7/10
Reliability: 6/10
Complexity: 9/10
Approximate implementation size: 8000-18000 LOC
```

Good later for offline-first power users, but not the first team version. It
requires conflict protocols, CRDT-like semantics or explicit merge workflows,
per-agent checkpoints, peer identity, replay protection, quota accounting and
cross-device deletion semantics.

```text
Option C: Git/Markdown/Obsidian export as team sync
Confidence: 7/10
Reliability: 6/10
Complexity: 4/10
Approximate implementation size: 1000-2500 LOC
```

Useful as backup, review and human-readable export. Not sufficient as the
runtime source of truth because permissions, deletes, PII handling, freshness,
outbox state and projection repair become ambiguous.

## Relation To Existing Memo Stack

Existing decisions stay valid:

- Postgres is canonical.
- Graphiti is a temporal fact graph projection.
- Qdrant is a vector/RAG projection.
- Cognee can be a document/session/RAG adapter.
- Context is compiled by Memo Stack Core after canonical hydration and policy
  filtering.
- There must be no generic universal `MemoryEnginePort`.
- Capability-specific ports stay the adapter boundary.

The Central Team Memory Server adds:

- organization/workspace identity;
- memberships and scoped permissions;
- service tokens for agents and integrations;
- shareable memory spaces;
- memory scope grants;
- audit and admin operations;
- remote deployment behavior;
- cache and projection invalidation rules for team use.

It must not move canonical lifecycle into Graphiti, Qdrant, Cognee or an MCP
client.

## Naming And Scope Mapping

Use these domain terms consistently:

```text
Organization
  Top account or tenant boundary. Owns billing, global admins, data residency
  and top-level security policy.

Workspace
  Team/product boundary inside an organization. Owns members, service tokens,
  default policies and memory spaces.

MemorySpace
  Project/repository/product memory namespace. Existing `space_id` remains this
  boundary. A space can be owned by a workspace.

Memory Scope
  Person, role, agent, category or target memory memory scope inside a space.
  Existing `memory_scope_id` remains this boundary.

Thread
  Conversation/session/interview scope. Existing `thread_id` remains optional
  context-local scope.

User
  Human user, service account, agent, automation or internal worker identity.

Membership
  User access to organization/workspace/space.

MemoryScopeGrant
  Fine-grained permission for user access to one or more memory scopes inside a
  space.

ServiceToken
  Revocable secret used by agent plugins, SDKs and CI integrations.

MemoryView
  Named read policy over one or more memory scopes/spaces for context building.
```

Current fields map as:

```text
tenant_id      -> Organization id in team/remote mode
workspace_id   -> Workspace id
space_id       -> MemorySpace id
memory_scope_id     -> Memory scope id
thread_id      -> Thread id
space_slug     -> human slug, unique only inside a workspace
external_ref   -> client-provided stable ref, unique only inside its parent
```

Important invariant: human slugs, tags, categories and external refs are never
global security boundaries.

## Simple DDD Stance

Use DDD where it creates clear boundaries, not ceremony:

- bounded contexts separate identity, team workspace, canonical memory,
  capture, retrieval, projection, audit, import/export and operations;
- aggregates protect invariants such as token revocation, memory scope grants,
  fact version conflicts and audit chain integrity;
- application use cases coordinate aggregates through ports;
- repositories persist aggregates but do not decide business policy;
- adapters translate external protocols into application commands;
- domain objects are intentionally small and explicit value objects are used
  where accidental string mixing would create security bugs.

Do not model every database row as a rich domain aggregate. Projection state,
outbox rows, usage counters and operational diagnostics can be simple records
owned by application/infrastructure services unless they need invariants.

## Bounded Contexts

### 1. Identity And Access

Owns:

- user resolution;
- service token hashing and revocation;
- workspace membership;
- space membership;
- memory scope grants;
- authorization decisions;
- token/session cache invalidation.

Does not own:

- fact lifecycle;
- document ingestion;
- Graphiti/Qdrant projection state;
- context ranking.

### 2. Team Workspace Management

Owns:

- organizations;
- workspaces;
- memory spaces;
- workspace settings;
- default policies;
- invites;
- transfer/ownership rules.

Does not own:

- permission checks for concrete operations after membership is resolved;
- durable memory facts.

### 3. Canonical Memory Lifecycle

Owns:

- facts;
- fact versions;
- suggestions;
- documents;
- chunks;
- episodes;
- tombstones;
- source refs;
- idempotency;
- lifecycle states.

Does not own:

- raw provider SDKs;
- final auth token parsing;
- external engine write APIs.

### 4. Capture And Auto-Memory

Owns:

- hook/event capture;
- transcript-tail ingestion where officially supported;
- classifier/extractor orchestration;
- write admission;
- suggestion generation;
- quarantine;
- review queue input.

Does not own:

- approving writes;
- access control policy;
- direct projection writes outside canonical lifecycle.

### 5. Retrieval And Context Compiler

Owns:

- collecting candidates from canonical facts, Graphiti, Cognee and Qdrant;
- canonical hydration;
- policy filtering;
- dedupe;
- ranking;
- freshness/currency handling;
- token budget packing;
- safe prompt rendering.

Does not own:

- adapter-specific retrieval algorithms;
- membership management.

### 6. Projection Engines

Owns derived indexes only:

- Graphiti/Neo4j temporal fact graph;
- Qdrant vector index;
- Cognee RAG/session pipeline;
- projection state and rebuilds;
- drift detection.

Does not own:

- canonical truth;
- permissions;
- audit truth;
- deletion finality.

### 7. Audit And Compliance

Owns:

- append-only audit records;
- audit chain proofs;
- export records;
- admin/maintenance access records;
- retention and legal hold decisions;
- redaction artifacts.

Does not own:

- business write decisions;
- adapter retrieval.

### 8. Import, Export And Backup

Owns:

- team export bundles;
- import previews;
- backup manifests;
- restore validation;
- Git/Markdown/Obsidian style export lanes.

Does not own:

- realtime team sync in v1;
- bypassing auth policy for export.

### 9. Operations

Owns:

- health;
- capabilities;
- projection lag;
- worker leases;
- migration status;
- quota usage;
- safe diagnostics.

Does not own:

- domain decisions;
- user-facing memory semantics.

## Aggregates And Invariants

### Organization

Fields:

- `organization_id`;
- `slug`;
- `display_name`;
- `status`;
- `owner_principal_id`;
- `data_residency_policy_id`;
- `created_at`;
- `updated_at`;
- `version`.

Invariants:

- organization slug is unique among active organizations;
- owner transfer requires a second active owner or explicit break-glass action;
- suspended organization denies non-admin memory access;
- hard delete is unavailable while legal hold or active backup restore exists.

### Workspace

Fields:

- `workspace_id`;
- `organization_id`;
- `slug`;
- `display_name`;
- `status`;
- `default_memory_policy_id`;
- `created_at`;
- `updated_at`;
- `version`.

Invariants:

- workspace slug is unique only inside organization;
- workspace cannot be active if organization is suspended;
- workspace deletion tombstones dependent spaces, not physical rows.

### MemorySpace

Fields:

- existing `space_id`;
- new `workspace_id`;
- `slug`;
- `display_name`;
- `visibility`;
- `default_memory_scope_id`;
- `status`;
- `version`.

Invariants:

- space slug is unique only inside workspace;
- a space cannot move workspace without explicit migration/audit;
- every fact/document/episode must belong to exactly one space;
- tags/categories do not define space boundaries.

### Memory Scope

Fields:

- existing `memory_scope_id`;
- `space_id`;
- `external_ref`;
- `kind`;
- `display_name`;
- `status`;
- `version`.

Invariants:

- memory scope external ref is unique only inside space;
- memory scope delete is soft delete and hides derived projections after canonical
  lifecycle update;
- cross-memory-scope context requires explicit read grant or memory view.

### User

Fields:

- `user_id`;
- `kind` such as human, service, agent, worker;
- `external_subject`;
- `status`;
- `created_at`;
- `last_seen_at`.

Invariants:

- one external subject maps to one active user per auth provider;
- disabled user cannot refresh tokens;
- internal worker user cannot call public user mutation APIs.

### WorkspaceMembership

Fields:

- `workspace_id`;
- `user_id`;
- `role`;
- `status`;
- `created_by`;
- `created_at`;
- `version`.

Invariants:

- role is deny-by-default outside declared actions;
- a workspace must keep at least one owner/admin;
- membership downgrade invalidates token cache and context cache.

### SpaceMembership

Fields:

- `space_id`;
- `user_id`;
- `role`;
- `status`;
- `created_at`;
- `version`.

Invariants:

- space membership cannot be active if workspace membership is inactive;
- role cannot exceed workspace role ceiling unless explicit admin override;
- removing membership invalidates all context/read caches for the user.

### MemoryScopeGrant

Fields:

- `space_id`;
- `memory_scope_id`;
- `user_id`;
- `actions`;
- `status`;
- `expires_at`;
- `created_at`;
- `version`.

Invariants:

- grant cannot exist for inactive memory scope;
- grant cannot exceed space membership action ceiling;
- grant expiry is enforced by reads and writes, not only UI.

### ServiceToken

Fields:

- `token_id`;
- `workspace_id`;
- `user_id`;
- `token_prefix`;
- `token_hash`;
- `scopes`;
- `default_space_id`;
- `default_memory_scope_id`;
- `expires_at`;
- `revoked_at`;
- `version`.

Invariants:

- raw token is shown only once;
- token hash uses a strong one-way hash with server-side pepper when available;
- token prefix is safe for diagnostics, never sufficient for auth;
- revocation must invalidate active MCP sessions on next operation at minimum;
- token scope cannot exceed owner user access.

### MemoryFact

Uses existing fact aggregate.

Team invariants to add:

- fact write requires `write_fact` or approved suggestion path;
- update/delete requires expected version or explicit conflict override;
- fact cannot move across space/memory scope;
- current-state resolution is canonical, Graphiti is candidate evidence only;
- hard delete is an admin/compliance path with audit and projection forget jobs.

### MemorySuggestion

Uses existing suggestion aggregate.

Team invariants to add:

- suggestion creator can be an agent/service user;
- approval requires a user with `approve_suggestion` on the target memory scope;
- pending duplicate suggestions collapse by scoped candidate fingerprint;
- rejected suggestion remains audit-visible but not context-visible.

### MemoryDocument

Uses existing document/chunk aggregates.

Team invariants to add:

- document visibility follows space/memory scope/thread plus grants;
- chunk recall from Qdrant/Cognee must hydrate through Postgres before display;
- document delete tombstones canonical rows before projection delete;
- import/export preserves source refs and redaction metadata.

### MemoryView

New aggregate for named context scopes.

Fields:

- `memory_view_id`;
- `workspace_id`;
- `name`;
- `allowed_space_ids`;
- `allowed_memory_scope_ids`;
- `default_context_policy`;
- `status`;
- `version`.

Invariants:

- memory view never grants access by itself;
- it can only narrow a user's effective access;
- cross-space view requires explicit workspace-level role;
- view changes invalidate matching context cache.

### AuditEvent And AuditChain

Fields:

- `audit_event_id`;
- `organization_id`;
- `workspace_id`;
- `space_id`;
- `user_id`;
- `action`;
- `target_type`;
- `target_id`;
- `safe_metadata`;
- `occurred_at`;
- `chain_hash`.

Invariants:

- audit metadata is redacted and safe;
- failed access attempts are audited at rate-limited granularity;
- chain verification is independent from normal read APIs;
- maintenance override requires reason, actor, expiry and target scope.

## Permission Model

Authorization pipeline:

```text
request token
  -> TokenAuthenticator
  -> User
  -> WorkspaceMembership
  -> SpaceMembership
  -> MemoryScopeGrant
  -> TeamMemoryPolicy
  -> EffectivePermissionDecision
  -> use case
```

Actions:

```text
read_context
read_fact
read_document
ingest_episode
ingest_document
suggest_memory
approve_suggestion
write_fact
update_fact
forget_memory
export_memory
import_memory
manage_members
manage_tokens
manage_policies
admin_maintenance
```

Rules:

- deny by default;
- no existence leaks across unauthorized scope;
- read and write decisions are separate;
- service tokens inherit a narrowed snapshot of owner permissions;
- thread-scoped write does not imply memory scope-wide write;
- export requires explicit `export_memory`;
- delete/forget requires stronger permission than write;
- context rendering must run auth filtering after every derived recall source.

## Clean Architecture Layers

### Domain Layer

Package target:

```text
memo_stack_core.domain.team
```

Contains:

- entities/value objects;
- aggregate invariants;
- domain errors;
- policy value objects;
- no FastAPI;
- no SQLAlchemy;
- no Pydantic;
- no external SDK types.

Examples:

```python
@dataclass(frozen=True)
class TeamScope:
    organization_id: str
    workspace_id: str
    space_id: str
    memory_scope_id: str | None = None

    def __post_init__(self) -> None:
        if not self.organization_id.strip():
            raise MemoryValidationError("organization_id is required")
        if not self.workspace_id.strip():
            raise MemoryValidationError("workspace_id is required")
        if not self.space_id.strip():
            raise MemoryValidationError("space_id is required")
```

```python
class TeamAction(StrEnum):
    READ_CONTEXT = "read_context"
    SUGGEST_MEMORY = "suggest_memory"
    APPROVE_SUGGESTION = "approve_suggestion"
    WRITE_FACT = "write_fact"
    FORGET_MEMORY = "forget_memory"
    EXPORT_MEMORY = "export_memory"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_TOKENS = "manage_tokens"
```

### Application Layer

Package target:

```text
memo_stack_core.application.team
```

Contains use cases:

- create organization;
- create workspace;
- create memory space;
- invite/add member;
- create/revoke service token;
- create/update memory scope grant;
- resolve effective permission;
- create memory view;
- build team context;
- export/import team memory;
- audit maintenance override.

Use cases depend only on ports:

```python
class CreateServiceTokenUseCase:
    def __init__(
        self,
        tokens: ServiceTokenRepositoryPort,
        memberships: MembershipRepositoryPort,
        hasher: TokenHasherPort,
        audit: AuditPort,
        uow: UnitOfWorkFactoryPort,
    ) -> None:
        self._tokens = tokens
        self._memberships = memberships
        self._hasher = hasher
        self._audit = audit
        self._uow = uow
```

### Port Layer

Package target:

```text
memo_stack_core.ports.team
```

Ports:

```python
class UserResolverPort(Protocol):
    async def resolve(self, token: str | None) -> MemoryUser: ...

class TokenHasherPort(Protocol):
    def hash_token(self, raw_token: str) -> str: ...
    def verify_token(self, raw_token: str, token_hash: str) -> bool: ...

class OrganizationRepositoryPort(Protocol):
    async def create(self, organization: Organization) -> Organization: ...
    async def get_by_id(self, organization_id: str) -> Organization | None: ...
    async def get_by_slug(self, slug: str) -> Organization | None: ...

class WorkspaceRepositoryPort(Protocol):
    async def create(self, workspace: Workspace) -> Workspace: ...
    async def get_by_id(self, workspace_id: str) -> Workspace | None: ...
    async def get_by_slug(
        self, *, organization_id: str, slug: str
    ) -> Workspace | None: ...

class MembershipRepositoryPort(Protocol):
    async def get_workspace_membership(
        self, *, workspace_id: str, user_id: str
    ) -> WorkspaceMembership | None: ...
    async def get_space_membership(
        self, *, space_id: str, user_id: str
    ) -> SpaceMembership | None: ...

class MemoryScopeGrantRepositoryPort(Protocol):
    async def list_effective_grants(
        self, *, space_id: str, user_id: str
    ) -> tuple[MemoryScopeGrant, ...]: ...

class AuthorizationPolicyPort(Protocol):
    async def decide(self, command: AuthorizationCommand) -> AuthorizationDecision: ...

class RepositoryScopePort(Protocol):
    def compile_scope(self, decision: AuthorizationDecision) -> RepositoryScope: ...

class RlsSessionPort(Protocol):
    async def set_scope(self, scope: RepositoryScope) -> None: ...
    async def clear_scope(self) -> None: ...
```

Do not add team auth logic into Graphiti/Qdrant/Cognee adapters. They receive
already-scoped canonical IDs or query DTOs.

### Adapter Layer

Inbound adapters:

- FastAPI REST API;
- MCP server tools;
- CLI;
- Python SDK;
- TypeScript SDK later;
- admin web UI later.

Outbound adapters:

- Postgres repositories;
- optional Postgres RLS session adapter;
- token hasher;
- external auth/JWT adapter later;
- Graphiti/Neo4j adapter;
- Qdrant adapter;
- Cognee adapter;
- object storage adapter;
- audit chain adapter;
- notification/webhook adapter later.

Composition root:

- wires concrete adapters;
- chooses capability routing;
- never leaks provider SDK types into domain/application;
- validates deployment mode:
  - local single-user;
  - team server without RLS;
  - team server with RLS;
  - cloud remote.

## SOLID Checks

Single Responsibility:

- `AuthorizationService` decides access only.
- `ContextCompiler` compiles context only.
- `ProjectionWorker` updates derived engines only.
- `CaptureIngestionUseCase` records captures and suggestions only.
- `ServiceTokenUseCase` owns token lifecycle only.

Open/Closed:

- new auth providers are added through `UserResolverPort`;
- new storage engines are added through capability-specific ports;
- new memory clients are added as inbound adapters;
- new team policies are added as policy implementations, not use-case branches.

Liskov Substitution:

- adapter result DTOs must respect the same semantics;
- degraded adapter returns safe diagnostics and candidates only when allowed;
- adapter delete/forget never claims canonical deletion;
- projection adapters can be swapped without changing use cases.

Interface Segregation:

- keep `DocumentMemoryPort`, `TemporalFactGraphPort`, `VectorRecallPort`,
  `RagRecallPort` and `ProjectionForgetPort` separate;
- team auth ports are separate from memory lifecycle ports;
- admin/maintenance ports do not leak into user read use cases.

Dependency Inversion:

- application services depend on ports;
- FastAPI, SQLAlchemy, Graphiti, Qdrant, Cognee and token libraries stay in
  infrastructure adapters;
- tests can replace repositories and policy ports with fakes.

## REST API Shape

Add team routes without breaking current v1 routes.

Recommended endpoints:

```text
POST   /v1/organizations
GET    /v1/organizations/{organization_id}

POST   /v1/workspaces
GET    /v1/workspaces/{workspace_id}
PATCH  /v1/workspaces/{workspace_id}

POST   /v1/workspaces/{workspace_id}/members
GET    /v1/workspaces/{workspace_id}/members
PATCH  /v1/workspaces/{workspace_id}/members/{user_id}

POST   /v1/workspaces/{workspace_id}/spaces
GET    /v1/workspaces/{workspace_id}/spaces
PATCH  /v1/spaces/{space_id}

POST   /v1/spaces/{space_id}/members
GET    /v1/spaces/{space_id}/members
PATCH  /v1/spaces/{space_id}/members/{user_id}

POST   /v1/spaces/{space_id}/memory-scope-grants
GET    /v1/spaces/{space_id}/memory-scope-grants
PATCH  /v1/memory-scope-grants/{grant_id}

POST   /v1/workspaces/{workspace_id}/service-tokens
GET    /v1/workspaces/{workspace_id}/service-tokens
DELETE /v1/service-tokens/{token_id}

POST   /v1/memory-views
GET    /v1/memory-views
PATCH  /v1/memory-views/{memory_view_id}

GET    /v1/context
POST   /v1/episodes
POST   /v1/documents
POST   /v1/facts
PATCH  /v1/facts/{fact_id}
DELETE /v1/facts/{fact_id}

GET    /v1/suggestions
POST   /v1/suggestions/{suggestion_id}/approve
POST   /v1/suggestions/{suggestion_id}/reject

GET    /v1/audit
POST   /v1/export
POST   /v1/import/preview
POST   /v1/import/apply
GET    /v1/capabilities
GET    /v1/health
```

Compatibility:

- existing local routes may keep default space/memory scope resolution;
- team mode requires workspace/space resolution before memory operations;
- external refs remain allowed but must be resolved inside workspace/space;
- ambiguous external refs return validation error, not first match.

## MCP Behavior For Team Server

The universal agent plugin remains an MCP client of the server.

Environment:

```text
MEMO_STACK_MCP_API_URL
MEMO_STACK_MCP_AUTH_TOKEN
MEMO_STACK_MCP_DEFAULT_WORKSPACE_EXTERNAL_REF
MEMO_STACK_MCP_DEFAULT_SPACE_SLUG
MEMO_STACK_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF
MEMO_STACK_MCP_DEFAULT_THREAD_EXTERNAL_REF
MEMO_STACK_MCP_AGENT_NAME
MEMO_STACK_MCP_WRITE_MODE=suggest
MEMO_STACK_MCP_DELETE_MODE=off
MEMO_STACK_MCP_INGEST_MODE=small_docs
```

Tool policy:

- `memory_status` shows effective workspace/space/memory scope but never token;
- `memory_search` uses `read_context` and hydrates canonical memory;
- `memory_propose` creates suggestions by default;
- `memory_remember` requires `write_fact` and explicit unsafe write mode;
- `memory_forget` is disabled by default and requires `forget_memory`;
- hooks/autocapture create captures/suggestions, not direct facts by default.

Session behavior:

- token is checked on each operation or after a short cache TTL;
- revoked token fails next operation;
- default scope is resolved once for diagnostics but validated per write/read;
- no MCP output contains raw token, OpenAI key or provider secrets.

## Repository Scope Contract

All repository methods that access canonical memory in team mode must receive
or derive a `RepositoryScope`.

Shape:

```python
@dataclass(frozen=True)
class RepositoryScope:
    organization_id: str
    workspace_id: str
    allowed_space_ids: tuple[str, ...]
    allowed_memory_scope_ids: tuple[str, ...]
    user_id: str
    actions: tuple[str, ...]
    reason: str
```

Rules:

- no repository query may rely on caller-supplied tags/categories for security;
- no query may omit space predicate in team mode;
- derived recall candidates must be hydrated under the same scope;
- maintenance override must be explicit, audited, time-limited and reasoned;
- optional Postgres RLS can enforce the same scope in remote/cloud mode.

Implementation order:

1. repository scope contract in application/repositories;
2. integration tests that fail on missing scope;
3. optional RLS smoke tests;
4. full RLS in cloud/remote mode after contract is stable.

## Storage Model Sketch

Add these canonical tables when implementing team mode:

```text
memory_organizations
memory_workspaces
memory_workspace_members
memory_space_members
memory_memory_scope_grants
memory_principals
memory_service_tokens
memory_memory_views
memory_memory_view_memory scopes
memory_repository_scope_proofs
memory_read_access_audit
memory_maintenance_scope_overrides
```

Existing tables should eventually carry or derive:

```text
organization_id
workspace_id
space_id
memory_scope_id
thread_id
```

Migration strategy:

1. create default local organization/workspace for existing installs;
2. backfill spaces into the default workspace;
3. create owner/service user for existing token;
4. keep current local API defaults working;
5. add team mode validation behind config;
6. only then require workspace for remote mode.

## Projection Isolation

Graphiti:

- recommended `group_id` remains `space:{space_id}:memory scope:{memory_scope_id}`;
- if organization/workspace is added to external metadata, it is diagnostic,
  not the security boundary;
- Graphiti search returns candidates only;
- Postgres hydration filters unauthorized/stale/deleted results.

Qdrant:

- payload includes `space_id`, `memory_scope_id`, `thread_id`, `document_id`,
  `chunk_id`, `canonical_status`;
- Qdrant filters are performance hints, not final auth;
- Postgres hydration filters final results.

Cognee:

- dataset/user/node_set maps through an adapter anti-corruption layer;
- Cognee output is never public API identity;
- Cognee session memory is optional derived capability.

Projection forget:

- canonical tombstone first;
- outbox event second;
- adapter forget third;
- context compiler hides deleted canonical rows even if adapter is stale.

## Sync And Remote Mode

V1 team mode:

- central server is canonical;
- local clients are online clients;
- local cache is read-only and TTL-bound;
- write operations go to server as suggestions/facts/documents;
- export/import is explicit and audited.

Do not implement v1 as bidirectional sync.

Future local-first mode requires a separate ADR covering:

- peer identity;
- change-set signing;
- conflict resolution;
- delete semantics;
- offline grants;
- checkpoint repair;
- replay protection;
- projection rebuild after import.

Git/Markdown export:

- useful for backup, review and human-readable memory snapshots;
- not a permission source;
- not an automatic write source unless imported through preview/review.

## Edge Cases

Authorization:

- member removed while MCP session is alive;
- token revoked while long-running request is active;
- role downgraded while suggestions are pending;
- service token owner loses access;
- workspace admin tries to access private memory scope without memory scope grant;
- user guesses a space slug from another workspace;
- external ref collides across workspaces;
- request mixes canonical ids and external refs;
- deleted memory scope referenced by old MCP config;
- organization suspended while workers still process outbox.

Canonical lifecycle:

- two agents update same fact concurrently;
- update arrives after fact was forgotten;
- suggestion approves stale target fact version;
- duplicate facts from auto-memory and manual write;
- fact supersession conflicts across memory scopes;
- old fact remains in Graphiti after canonical delete;
- document delete leaves vector chunks in Qdrant temporarily;
- source ref points to a deleted/redacted document;
- import tries to resurrect tombstoned fact.

Retrieval:

- Graphiti returns high-score but unauthorized candidate;
- Qdrant returns stale chunk from deleted document;
- Cognee returns summary whose source chunk is hidden;
- context cache contains now-revoked memory scope;
- memory view narrows scope but client asks broader memory scope set;
- adapter outage should degrade to canonical search when allowed;
- `require_fresh_projection` should fail when projection lag is too high.

Security and compliance:

- audit metadata accidentally includes secret;
- raw token appears in logs;
- OpenAI/provider key appears in diagnostics;
- embedding created from sensitive text before redaction;
- export includes restricted memory scope by mistake;
- restore into another organization violates residency;
- maintenance override runs without reason/expiry;
- legal hold conflicts with forget request;
- backup snapshot includes stale derived projection but canonical restore differs.

Operations:

- worker crash after canonical commit before projection write;
- outbox duplicate delivery;
- projection rebuild races with active writes;
- RLS session scope leaks across pooled DB connection;
- database migration adds workspace columns but old local mode still runs;
- health endpoint leaks tenant metadata;
- quota reservation stuck after request timeout;
- cache invalidation missed after membership change.

## Phased Implementation

### Phase 0 - Decision And Guardrails

Deliverables:

- this plan;
- ADR update or new ADR for Central Team Server;
- architecture tests planned;
- explicit non-goals for local-first sync and OAuth/billing.

Acceptance:

- team/domain language is consistent;
- no plan says Graphiti/Qdrant/Cognee are canonical;
- existing local mode remains supported.

### Phase 1 - Team Domain And Ports

Deliverables:

- domain value objects/entities for Organization, Workspace, Membership,
  MemoryScopeGrant, ServiceToken, MemoryView;
- port interfaces;
- authorization decision DTOs;
- unit tests for invariants;
- no database dependency in domain tests.

Approximate size: 700-1400 LOC.

### Phase 2 - Postgres Team Repositories

Deliverables:

- migrations;
- repositories for organization/workspace/membership/grants/tokens/views;
- default local organization/workspace backfill;
- token hashing and revocation;
- repository scope proof logging.

Approximate size: 900-1800 LOC.

### Phase 3 - Authorization In Existing Memory Use Cases

Deliverables:

- effective permission resolution before read/write;
- repository methods accept/derive team scope;
- canonical hydration filters after all derived recall;
- tests for no existence leak.

Approximate size: 700-1600 LOC.

### Phase 4 - REST And MCP Team Integration

Deliverables:

- team management REST endpoints;
- MCP default workspace/space/memory scope resolution;
- doctor shows safe effective scope;
- service token creation/revocation flow;
- e2e MCP tests against team server.

Approximate size: 900-2000 LOC.

### Phase 5 - Audit, Export And Backup Minimum

Deliverables:

- audit events for auth, membership, token, memory write, export;
- safe export bundle with policy filtering;
- import preview that creates suggestions, not blind writes;
- backup/restore manifest validation for canonical data.

Approximate size: 800-1800 LOC.

### Phase 6 - RLS And Remote Hardening

Deliverables:

- optional Postgres RLS in team/remote mode;
- DB pool scope reset tests;
- RLS smoke tests;
- maintenance override audit;
- projection/cache invalidation on membership/grant changes.

Approximate size: 700-1600 LOC.

### Phase 7 - Web Admin And Review UX

Deliverables:

- team member management UI;
- token management UI;
- suggestion review queue by space/memory scope;
- audit viewer;
- memory view manager.

Approximate size: 1200-3000 LOC.

## Test Strategy

Unit tests:

- aggregate invariants;
- token hashing/revocation;
- authorization decisions;
- memory view narrowing;
- memory scope grant expiry;
- slug/external ref uniqueness.

Architecture tests:

- domain imports no FastAPI/SQLAlchemy/Pydantic/external SDKs;
- application imports ports, not adapters;
- adapters do not leak SDK types into core DTOs;
- no use case branches on concrete adapter names.

Repository tests:

- all memory queries require scope in team mode;
- no cross-space/memory scope leakage;
- deleted memberships hide memory;
- default local workspace backfill works.

E2E tests:

- create organization/workspace/space/memory scope;
- create service token;
- MCP status resolves default scope;
- agent proposes memory;
- reviewer approves suggestion;
- another unauthorized token cannot read it;
- revoke token and verify next MCP call fails;
- Graphiti/Qdrant candidates hydrate through canonical auth;
- export excludes unauthorized memory scope;
- import preview does not write directly.

Failure tests:

- Graphiti down, canonical context still works when allowed;
- Qdrant stale chunk is filtered;
- token cache invalidated after revoke;
- RLS connection scope reset;
- projection outbox duplicate is idempotent;
- audit logs do not contain token/provider secrets.

## What Not To Build First

Do not build these in the first Central Team Server MVP:

- full OAuth product surface;
- billing and quotas beyond simple internal counters;
- local-first bidirectional sync;
- CRDT conflict merge;
- public SaaS marketplace distribution;
- Graphiti/Qdrant/Cognee as canonical stores;
- Git/Markdown export as runtime sync;
- UI-first implementation before domain/auth ports.

## First Concrete Implementation Slice

Recommended first slice:

```text
1. Add team domain entities and ports.
2. Add Postgres tables for organizations, workspaces, memberships, grants and
   service tokens.
3. Create default local org/workspace migration.
4. Add effective authorization use case.
5. Gate existing /v1/context, /v1/facts, /v1/documents and /v1/suggestions.
6. Add MCP default workspace support and doctor output.
7. Add e2e: two users, two workspaces, same space slug, no leakage.
```

Why this slice:

- proves the hardest security boundary early;
- keeps local mode alive;
- gives agents a real central team server path;
- avoids premature UI and local-first sync complexity;
- directly strengthens the current Memo Stack architecture instead of replacing
  it.

## Open Questions

These should be decided before coding Phase 2:

1. Should `Organization` be visible in local mode, or only a hidden default?
2. Should memory scope grants be allow-list only, or allow inherited defaults from
   space role?
3. Should service tokens be workspace-level only in MVP, or also space-level?
4. Should memory views be API-only in MVP, or exposed through MCP tools?
5. Should RLS be enabled in all team tests from the start, or introduced after
   repository scope contract is stable?

Recommended defaults:

- local mode uses hidden default organization/workspace;
- memory scope grants are allow-list with explicit inherited role ceiling;
- service tokens are workspace-level with narrowed default space/memory scope;
- memory views are API-only in MVP;
- repository scope contract first, RLS after smoke coverage is stable.
