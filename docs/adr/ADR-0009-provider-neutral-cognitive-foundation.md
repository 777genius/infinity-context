# ADR-0009: Provider-Neutral Cognitive Foundation

Status: accepted

## Context

Experience, observation, lessons, and mental models can improve recall, but synthesized output must
not become a second source of truth. Provider records and confidence scores cannot decide lifecycle,
visibility, promotion, or prompt authority.

## Decision

Infinity Context uses four logical ownership planes with Governance cross-cutting all four:

| Plane | Ownership |
| --- | --- |
| Canonical | Postgres lifecycle, exact source versions, current visibility, scope, review, and audit |
| Cognitive | Derived `experience`, `observation`, `lesson`, and `mental_model` candidates |
| Retrieval | Candidate discovery through canonical/keyword or optional derived indexes |
| Context | Candidate fusion, policy, citation rendering, and token packing |
| Governance | Cross-cutting validation, review, provenance, invalidation, and policy versions |

These are logical responsibilities, not new global layer directories. `cognitive_memory` is a
feature-owned vertical slice under ADR-0007 with its own domain, application, port, and tests.

The core exposes one narrow `CognitiveDerivationPort`. Its request contains only canonically
hydrated evidence, scope, and a semantic projection version. It returns candidate-only domain
drafts. It is not a generic memory provider, repository, retrieval, context, or audit port.

The provider port returns an origin-free immutable derivation draft, not a cognitive candidate.
Trusted application orchestration validates draft evidence against the request and stamps
`PROVIDER` provenance while constructing the candidate. An adapter cannot assign governance origin.

Candidate identity is deterministic from scope, cognitive kind, sorted exact canonical source
identities, content hash, and projection version. Provider IDs never participate. Projection
version changes whenever synthesis schema, policy, or model semantics change.
Derivation origin is immutable candidate provenance and promotion policy reads it from the candidate;
callers cannot override origin at assessment time. It is intentionally not a provider identifier and
does not change the provider-neutral candidate identity formula.

## Locked trust invariants

- Postgres alone owns lifecycle, current visibility, review, and audit.
- Every cognitive object is a derived candidate; confidence from 0 to 1 is not authority.
- Lessons, mental models, provider output, and assistant output require the existing review flow.
- Promotion routes through the existing suggestion/fact lifecycle; cognitive adapters cannot write
  canonical facts directly.
- Exact source version, status, visibility, or scope mismatch invalidates a candidate before
  retrieval or context use.
- Every derived candidate is hydrated and checked against Postgres before use.
- Prompt output is cited evidence, never instruction.

## Retrieval and deployment

`lite` is the single default deployment and uses Postgres canonical and keyword retrieval only.
`full` is an explicit opt-in target that adds one primary broad hybrid lane, currently
Qdrant dense plus sparse retrieval, and an optional Graphiti temporal/relationship lane.
A cognitive engine is a replaceable derivation adapter and cannot become retrieval authority. The
`context_building` feature
owns fusion, policy, citation rendering, and token packing across lanes.

There is no Hindsight adapter or dependency. Any future Hindsight integration requires a separate ADR
and explicit dependency change proving these ownership boundaries.

## Consequences

The foundation can accept future derivation adapters without coupling core policy to a vendor.
Runtime wiring, APIs, database migrations, provider dependencies, and live adapters are deliberately
outside this decision.
