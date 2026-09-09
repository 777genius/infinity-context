# ADR-0013: Explicit thread selection for context retrieval

Status: Accepted architecture; implementation in progress.

Base: `723a67720bf5e2c694cfdd96f6194a03c7db4f63`.

## Problem

Historical documents can occupy different meeting threads within one memory
scope. A room-history retrieval must search those partitions together. V2's
nullable scalar thread identifier expresses an exact thread, including the
unthreaded partition; it cannot express all threads. Using the current meeting
would omit historical meetings. Per-thread fanout would multiply budgets and
change global ranking.

## Decision

Add an explicitly negotiated `context-retrieval.v3` boundary with scope:

```json
{
  "spaceId": "authorized-space",
  "memoryScopeId": "authorized-memory-scope",
  "thread": {"mode": "any"}
}
```

The alternative selector is `{"mode":"exact","id":"thread-id"}` or
`{"mode":"exact","id":null}`. Exact null means unthreaded only. Any admits
both threaded and unthreaded partitions, within the exact authorized space and
memory scope and the existing admitted source-generation intersection.

V3 has a separately advertised capability and separate official SDK methods.
Version-specific boundary mapping feeds the same retrieval engine. V2 wire,
capability, response, fixtures and null semantics remain unchanged. An old
server must reject the new request; an SDK must not downgrade it to V2. No
wildcard sentinel, implicit fallback, row migration or consumer-side ranker.

Reject unknown modes, missing exact ids, ids on any, scalar/selector conflicts,
unknown fields and duplicate JSON keys before scope resolution or retrieval
effects. Scope authorization still occurs before and after canonical resolution.

## Canonical and derived filtering

The generic canonical candidate predicate, Postgres provider query and hydration,
and Qdrant query must apply the same selector. Only the thread predicate changes
for any. Space, memory scope, admitted source-generation pairs, exclusions,
classification, lifecycle and profile fences remain mandatory. Postgres remains
canonical; Qdrant remains a derived candidate index.

Neighbor discovery remains anchored to each seed's exact space, memory scope,
thread, source and generation. Any does not permit adjacent chunks from another
thread or source. All lanes participate in one global ranking operation with
the existing byte, candidate, result, neighbor and deadline budgets.

## Ownership and validation

This checkpoint owns Infinity core, contracts, server, Postgres, Qdrant, official
TypeScript/Python SDK source boundaries, focused tests and this ADR. Core stays
free of provider dependencies. New source modules must be classified by the
existing architecture dependency guard. Discord evidence binding and consumer
migration are separate subsequent work.

Synthetic acceptance coverage must include two populated threads and the null
partition in one scope; any must find admitted candidates across all three.
Exact string and exact null must retain their existing isolation. Cross-space,
cross-memory-scope, stale-generation and excluded candidates must be rejected.
Boundary tests must prove invalid selectors cause no effects and V2 fixtures
stay unchanged. Adapter checks must cover SQL hydration and Qdrant predicates,
and neighbor tests must prove seed isolation under any.

No provider calls, deployment, publication or push are authorized. Do not modify
the immutable SDK 0.2.4 archive. Recommend a new SDK version and draft package
build validation in the final handoff; publishing needs separate authorization.

The writer's Git metadata is read-only (lock preflight returned EROFS). Deliver
an exact patch against the base rather than retrying commits. Provider-backed
and heavier validation belongs to main outside this sandbox.

## Implemented boundary layout

V3 uses `POST /v1/context/retrieve-v3` and advertises its descriptor separately at
`GET /v1/context/retrieve-v3/capability`. The existing `/v1/capabilities` V2
retrieval descriptor is unchanged, avoiding assumptions about old strict
validators accepting new descriptor fields. V3 hashes its own version and
endpoint into the capability fingerprint while retaining the same profile,
lanes, readiness snapshot and bounds. Execution verifies that fingerprint
inside the existing profile query fence before invoking the same engine.

V3 scope keys follow the accepted `spaceId`, `memoryScopeId`, `thread` shape;
other request fields retain the existing wire names. Python exposes
`retrieve_context_v3` with DTOs in
`infinity_context_contracts.features.context_retrieval_v3`. TypeScript exposes
`context.retrieveV3` and exports selector input and response types. Both methods
require a V3 attestation and reject V2 responses. They share existing transport
cancellation and byte/deadline checks rather than performing a second request.

The engine's internal request remains its existing contract shape with an
explicit `thread_mode` on the canonical scope. Only the V3 mapper supplies any;
V2 service entry rejects any. Internal contract naming does not negotiate a
wire version. No schema migration or projection rewrite is required.
