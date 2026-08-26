# ADR-0012: Exact document reconciliation and visibility

Status: Accepted

## Context

Consumers need to recover safely after an ambiguous document ingest, process, or delete
outcome. Listing the first 100 documents cannot prove presence or absence, and canonical
acceptance does not prove that a derived retrieval profile is queryable. Consumer-specific
identity, authorization, retry policy, and local evidence do not belong in Infinity Context.

## Decision

Infinity Context exposes the additive `document-reconciliation.v1` read-only contract at
`POST /v1/documents/reconcile-exact`. The request carries one canonical space, memory scope,
and exact optional thread plus opaque `source_type` and `source_external_id`. Optional
projection and retrieval-profile generations are hard filters. The official SDK requires a
matching capability attestation, propagates cancellation, applies a bounded deadline, limits
response bytes, validates runtime types and never includes opaque values in validation errors.

The application returns only `present`, `processing`, `indexed`,
`deleted_or_proven_absent`, `conflict`, or `unavailable`. `indexed` uses the same read-only
canonical queryability predicate as real query admission: the profile is active, its lease is
unexpired according to database time, its evidence version is positive, its binding is not
drifted, no maintenance or provider mutation is active, its activation/provider epochs match,
and every required provider lane remains healthy and qualified. It additionally requires a
current-version projection receipt for every active, eligible chunk. Pending, retry-pending,
or running outbox work is `processing`; canonical acceptance without that proof is `present`.
Deleted and superseded documents are never queryable. Zero exact rows proves absence; two rows
prove ambiguity and return `conflict`. The Postgres query reads at most two exact rows and does
not depend on list pagination.

The operation performs no mutation, provider call, retry, or second write. A consumer may use
it before deciding whether to replay its original operation with the same idempotency key.
Infinity does not choose that policy.

No schema migration is required: canonical document scope/source identity, chunk projection
generation, retrieval profile generation, current chunk version, and profile projection
receipts already exist. The existing scope/status access path supplies a bounded-deadline
lookup; a future performance-only index may be added without changing this contract.

## Dependency and source classification

```text
document_ingestion/domain/reconciliation.py            deterministic domain policy/value objects
document_ingestion/ports/reconciliation.py             narrow canonical observation port
document_ingestion/application/reconciliation.py       read-only application use case
contracts/features/document_ingestion.py               versioned provider-neutral JSON DTOs
adapters/postgres/document_reconciliation.py            canonical persistence/read adapter
server/features/document_ingestion/contracts.py         bounded HTTP request adapter
server/api/v1/documents.py                              authenticated HTTP composition
sdk/document_reconciliation.py                          official Python validation adapter
ts-sdk/document-reconciliation.ts                       official TypeScript validation adapter
```

Core imports no FastAPI, SQLAlchemy, Qdrant, Graphiti, OpenAI, SDK, or consumer application
code. Contracts import no core or framework code. Provider state is not lifecycle authority;
only canonical Postgres receipts may prove indexed visibility.

Every server, worker, and lifecycle-admin process explicitly registers its runtime owner before
it may admit work. Clean shutdown first drains owned query and mutation rows, then retires only
the exact registered generation. A crashed generation remains fenced until the existing signed
death-seal recovery protocol proves its death; restart never inherits or overwrites that owner.

## Consequences

Consumers can reconcile an exact identity even when more than 100 other documents exist and
can distinguish accepted work from queryable work. Unknown status, duplicate identity,
profile ambiguity, binding drift, timeout, cancellation, and malformed responses fail closed.
This ADR adds no consumer lifecycle, meeting, chat, voice, speaker, summary, or correction
model and no new package.
