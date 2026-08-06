# ADR-0010: Feature-Owned Temporal Memory Facts

Status: accepted

## Context

Infinity Context currently has two representations of a canonical memory fact:

- the layer-first runtime entity used by the production Postgres path;
- the feature-owned `memory_facts` snapshot and lifecycle skeleton introduced by ADR-0007.

Adding temporal validity to both representations would create two business-policy owners and make
the strangler migration harder to complete. The Core Lite plan is the implementation source of
truth and explicitly defers a complex mutable fact-currency engine. The global architecture plan
still provides useful semantics for validity, conflict review, repository scope and audit.

Facts also express different kinds of time:

- a state can be valid during a real-world interval;
- an event can occur during an interval without becoming false later;
- a timeless claim has no real-world validity interval.

Creation time, update time, validity, confirmation freshness and retention therefore cannot share
one timestamp or one status.

## Decision

### Ownership

`infinity_context_core.features.memory_facts` is the target owner of canonical fact behavior.

- `MemoryFact` is the feature-owned aggregate root.
- `MemoryFactSnapshot` remains the immutable public read and persistence transfer shape.
- layer-first fact modules become compatibility adapters and must eventually delegate to the
  feature public application API.
- new fact behavior is implemented only in the feature-owned domain.

The migration is a strangler migration over the existing canonical Postgres tables. It must not
create a second fact store or dual-write two canonical models.

Existing active state facts are backfilled with `valid_from = created_at` and the explicit
`migrated_legacy` basis. This preserves their pre-migration visibility but does not count as
confirmation: assurance stays `unknown` and `last_confirmed_at` remains empty.

### Independent semantics

The aggregate separates:

- `FactLifecycle`: active, disputed, superseded or deleted;
- `FactTemporalExtent`: observed time and state/event/timeless real-world time;
- `FactFreshness`: explicit confirmation time and basis;
- `FactRetention`: context expiry and optional physical purge boundary;
- `FactEpistemicContext`: world claim, actor perspective or hypothesis;
- `FactQuality`: confidence, trust and classification;
- `FactRevision`: one monotonic aggregate version.

`updated_at` is transaction metadata. It never confirms a fact and never changes currentness.

### Temporal model

State validity uses a half-open interval:

```text
[valid_from, valid_to)
```

Event occurrence uses a separate half-open interval:

```text
[occurred_from, occurred_to)
```

All canonical timestamps are timezone-aware.

`current`, `future`, `historical` and `unknown` are deterministic assessments at a supplied
reference time. They are not mutable canonical rows. The assessment returns bounded reason codes
and the next temporal boundary so caches can expire without a database mutation.

Actual governance actions such as supersede, temporal end, confirmation, dispute and reinstate
are recorded as append-only `FactTemporalDecision` rows with exact idempotency receipts. A future materialized
current-fact view may cache resolver output, but it remains rebuildable and non-canonical.

### Supersession

Supersession is a dedicated application command, not a side effect of a generic relation link.
It must lock affected facts in deterministic ID order and atomically persist:

- both aggregate revisions;
- the closed validity interval where applicable;
- the relation;
- an append-only temporal decision;
- complete version snapshots;
- provider-neutral outbox events.

Rollback creates a compensating decision. It does not delete audit history or unlink a
high-impact relation.

### Repository and project scope

`MemorySpace` remains an authorization/product boundary. `MemoryScope` remains a category inside
the space. `CodeRepository` is a separate identity inside a space and `CodeScope` describes
branch, PR, commit, package or file context.

One space per repository may be an installation default, but is not a domain invariant. Git,
filesystem and local-path discovery stay outside `infinity_context_core` in integration adapters.

`repository_id` is the durable authorization boundary. A repository token may optionally lock one
static `CodeScope`, but normal branch/worktree changes use a short-lived request claim. Enrollment
returns a separate one-time workspace binding grant; only its hash is stored by the server and the
private grant is stored in the mode-0600 local binding file. The local adapter signs claims with
that grant. The server requires the claim for dynamic repository tokens and verifies its age,
repository, signature, active binding version and stable drift state before creating the immutable
authorization context. Dynamic CodeScopes are also canonical, strict-admin registrations scoped
to one repository and space. The server derives their opaque ids from a validated branch/commit
descriptor and accepts only active registrations. Possession of the repository bearer alone cannot
forge a CodeScope, and request bodies or prompts cannot widen the signed context.

The binding grant is a trusted-local-adapter capability, not an independently attested Git
identity. A holder of both the repository bearer and its binding grant can sign a claim, but cannot
introduce an unregistered `code_scope_id`; registration requires the separate strict-admin
authority. The holder can still select among already authorized scopes whose ids it knows, so this
allowlist proves server authorization, not the caller's current Git checkout. Use a statically
CodeScope-locked token where the server must enforce one exact scope. Credential-bearing adapters
never follow HTTP redirects, and unresolved Git HEAD state fails closed instead of inventing a
transient repository-level scope.

Enrollment is explicit: a strict-admin endpoint resolves hashed repository evidence into one
canonical `CodeRepository`, and a local command writes a private trusted-binding file. Raw paths,
remote URLs and credentials are never persisted. The initial CodeScope is registered atomically
with repository enrollment; later branch/commit scopes require an explicit strict-admin call.
Conflicting normalized-remote evidence requires review even when weaker local evidence matches.
Existing dynamic repository-token installations must register their current repository, branch or
commit scope before enabling this policy; static CodeScope-locked tokens remain valid unchanged.
Binding-grant rotation/revocation and CodeScope-authorization revocation are separate
credential-lifecycle follow-ups. Until those APIs exist, issued grants and registrations must be
treated as active credentials and covered by an explicit operational revocation procedure.

Agent capture, direct fact mutation and temporal governance use separate capabilities:
`memory:capture`, `memory:fact_write` and `memory:govern`. Repository-scoped tokens do not inherit
these from the legacy broad `memory:write` permission.

### Derived indexes and context

Postgres remains canonical. Qdrant, Graphiti, summaries and observations are derived.

- derived items depend on canonical fact ID and source fact version;
- cognitive projections validate and lock exact canonical fact versions in the same transaction
  that persists their dependencies;
- stale derived candidates are removed by canonical hydration;
- temporal and scope eligibility is applied before ranking limits and rechecked after hydration;
- providers return candidate signals, not final truth or prompt-ready authority decisions;
- prompt rendering receives backend-resolved evidence labels and does not infer currentness.

Repository-scoped context currently fails closed to canonical facts. Document and chunk evidence
must gain repository identity before it can be merged into this path; unscoped evidence is not
silently mixed to preserve feature parity.

## Consequences

- temporal behavior is testable without Postgres, provider SDKs or an LLM;
- age cannot silently make a fact false or current;
- event occurrence is not confused with state validity;
- facts have one revision clock for content, lifecycle and temporal mutations;
- compatibility DTOs can evolve additively while runtime ownership moves feature by feature;
- Postgres migrations, atomic decisions, project binding and retrieval fusion remain separate
  implementation slices following the repository implementation order.

## Explicit non-goals

- full event sourcing;
- a mutable canonical `FactCurrencyState` table;
- physical database branches or MatrixOne dependency;
- automatic last-write-wins conflict resolution;
- treating skills or procedural memory as fact kinds;
- asking an LLM to decide final prompt eligibility from raw timestamps.
