# ADR-0011: Locator-only Retrieval boundary

Status: accepted

## Context

The existing `/v1/context` and `/v1/search` contracts return prompt-ready text and
belong to compatibility paths. A consumer that needs only historical candidate
coordinates cannot prove that those responses are text-free, cannot bind a query to
one exact retrieval capability/profile, and currently duplicates generic multi-query
fusion and neighborhood mechanics.

Reusing either legacy route would deepen the layer-first migration debt described by
ADR-0007. Derived Qdrant and Graphiti records also cannot become lifecycle or
authorization authority under ADR-0002 and ADR-0004.

## Decision

Infinity Context defines an additive `context_building` versioned Retrieval contract mounted
as `POST /v1/context/retrieve` when verified service provenance is available. The
provider-neutral core and versioned DTOs remain independent of its server and adapter
implementations. Existing `/v1/context` and `/v1/search` behavior is unchanged.

The response is locator-only. At every depth it excludes text, snippets, rendered
context, quotes, citations, aliases, authorization assertions and arbitrary metadata.
It returns only opaque locator and source/document/chunk identities, canonical
lifecycle/version identity, deterministic retrieval scores/provenance, neighbor
relation/distance, bounded provider outcomes, applied mechanical bounds, and the exact
accepted capability fingerprint/profile.

The request contains:

- the exact `context-retrieval.v2` version, capability fingerprint and profile id;
- exactly one resolved canonical Space/MemoryScope and optional thread;
- one to six explicit normalized query variants with unique ids and bounded optional
  weights;
- an exact sorted `source_generations` array containing `1..100` unique source-key /
  projection-generation pairs, never independent sets or Cartesian matching;
- only registered hard document/kind/category/tag/actor filters and at most one
  absolute UTC or source-relative millisecond time coordinate;
- only typed source/actor preferences and an optional weighted preference using exactly
  one absolute or source-relative time coordinate;
- explicit candidate, result, neighbor, response-byte and deadline bounds.

Unknown fields, enum values, score kinds, reason codes and out-of-range values fail
closed. Request payloads cannot select providers or provider weights.

Canonical JSON enters through a strict UTF-8 raw-byte decoder. Duplicate keys, missing
or extra canonical keys, lone surrogates, invalid controls, non-finite values and
noncanonical timestamp forms are rejected before DTO construction. UTC timestamps use
exactly `YYYY-MM-DDTHH:MM:SS[.fraction]Z`, with one to six fractional digits.

## Ranking and authority

`weighted_rrf_canonical_preferences.v1` is the only cross-provider ranking policy.
Query and provider weights are authoritative integer millionths. For each contribution
(`p = provider_weight_micros`, `q = query_weight_micros`,
`Q = sum(query_weight_micros)`, `K = 60`):

```text
contribution_score_picos =
    round_half_even(p * q * 1000000 / (Q * (K + provider_rank)))
base_score_picos = sum(contribution_score_picos)
```

No floating-point operation participates in authoritative scoring. Legacy float score
and weight fields are informational mirrors of the integer fields. At most one
contribution exists for a
canonical-identity/provider/query tuple. Raw provider scores are optional typed
evidence and never enter cross-provider arithmetic. Preference processing never
changes `base_score_picos`, a contribution, provider/query membership or candidate recall.

After `candidate_limit` is applied to fused provider candidates and preliminary
PostgreSQL hydration has authoritatively reapplied scope, active lifecycle, exact
source-generation membership, canonical version and every hard filter, the application
computes generic preference evidence from only the admitted row's canonical
`source_key`, `actor_keys`, absolute interval and source-relative interval.

All soft-preference weights are exact `weight_micros` integers in
`100000..10000000`; the optional time weight is `time_weight_micros` with the same
bounds. Let `W` be the sum of every requested source, actor and time preference weight,
including preferences the candidate does not match. Let `M` be the sum matched by one
candidate:

- a source preference matches only exact equality with the candidate's one canonical
  `source_key`;
- every requested actor key present in the candidate's canonical actor-key set adds its
  weight, so a multi-actor candidate may match multiple requested actors;
- the time weight is added only for inclusive interval overlap on the one explicitly
  requested coordinate; absolute and relative coordinates never match each other, and
  a missing candidate coordinate is a miss.

No match contributes zero. Requested source and actor keys are unique, so a dimension
cannot duplicate one requested weight. With integer floor division, the response
evidence and rerank score are:

```text
if W == 0:
    preference_score_micros = 0
else:
    preference_score_micros = floor(M * 1000000 / W)

preference_boost_micros = floor(preference_score_micros * 250000 / 1000000)
rerank_score_picos = floor(
    base_score_picos * (1000000 + preference_boost_micros) / 1000000
)
```

`base_score_picos` is the exact sum of pico contributions.
`preference_score_micros` is in `0..1000000` and the multiplicative
boost is in `0..250000`, so preferences can improve a base score by at most 25% and
cannot swamp arbitrary semantic evidence. Implementations use integer arithmetic (and
JavaScript/TypeScript use `BigInt` for intermediate products). Locator-only evidence
includes `base_score_picos`, requested and matched weight micros for source, actor and
time, `preference_score_micros`, `preference_boost_micros`, and
`rerank_score_picos`. It fully reconstructs every score without returning canonical
attributes or provider payload.

Final seed ordering is solely
`(-rerank_score_picos, -base_score_picos, unsigned_UTF8(canonical_identity))`, independent
of provider registration, provider completion, hit input order and hydration row
order. When no preference is requested, the score and boost are zero and
`rerank_score_picos == base_score_picos`, making ordering byte-for-byte equivalent to
the prior base-score ordering semantics.
`result_limit` is applied after this rerank. One final canonical read-session hydration
then reauthorizes those seeds and loads same-source neighbors; it does not recompute or
expand ranking.

Providers return candidate signals only. The application hydrates their canonical
identities, verifies the exact canonical version, reapplies scope, active lifecycle and
all hard filters, selects seeds, and rehydrates selected seeds immediately before
return. Deleted, restricted, expired, wrong-scope and stale-version candidates cannot
return. Derived index filters are optimizations only.

Pair matching is exact tuple membership. A candidate `(source_key,
projection_generation)` must equal one requested pair. Relative millisecond overlap is
evaluated only on the candidate's own source family; it is never a cross-source
chronology or response tie-breaker. Absolute and relative document intervals are
independent evidence and neither is synthesized from the other. Sequence ordinals
remain the sole neighbor ordering authority.

The final seed hydration and neighbor load are one consumer-owned canonical read-session
operation. Every returned seed coordinate and version comes from that exact read.
Mixed snapshot tokens, duplicate canonical identities and malformed hydration rows are
typed canonical-hydration invariant failures; missing or stale rows remain safe drops.

Neighbors load after final seed ranking. They never gain a fused score or alter top-k.
They require the same canonical scope and optional thread, source key, projection
generation and read snapshot, plus an explicit contiguous sequence ordinal at a
distance of at most two. They may cross server-owned document and chunk identities.
No id inference, gap crossing, cross-source attachment or recursive expansion is
allowed.

Composition supplies one immutable trusted capability/profile descriptor. Requests that
do not match it are rejected before provider execution. A positive neighbor radius also
requires an attested neighbor capability and otherwise returns a registered typed
unavailable result.

Core orchestration is deterministic and has no framework, provider, clock or timer
dependency. The request carries an attested deadline bound, while server composition
owns one monotonic timer across parsing, retrieval, hydration and serialization. Core catches `BaseException` only around its task
group so it can cancel and await every child, then immediately re-raises it; cancellation
therefore propagates. Optional ordinary provider exceptions become bounded degradation
codes without exposing exception details; a required provider failure produces no
partial candidates.

## Dependency classification

New source is classified fail-closed in the existing feature-owned model:

```text
context_building/domain/locator_retrieval.py       domain policy and values
context_building/domain/locator_retrieval_filters.py  pair/filter/time policy
context_building/ports/locator_retrieval.py        provider/hydration/neighbor ports
context_building/application/locator_retrieval.py  generic orchestration and fusion
contracts/features/_context_building_retrieval.py  internal versioned JSON DTO implementation
contracts/features/_context_building_retrieval_validation.py  strict DTO parsing helpers
contracts/features/_context_building_retrieval_filters.py     pair/filter/time DTOs
contracts/features/_context_building_retrieval_json.py        duplicate-safe raw JSON seam
contracts/features/_context_building_retrieval_capability.py  capability and fingerprint contract
contracts/features/_context_building_retrieval_response.py    strict response parser
contracts/features/_context_retrieval_errors.py               framework-neutral error envelope
contracts/features/_document_retrieval_projection_v1.py          strict projection DTO
document_ingestion/domain/retrieval_projection.py                generic projection value
document_ingestion/ports/projection_ownership.py                  canonical ownership seam
context_building/domain/retrieval_capability.py                trusted capability values
```

The domain depends only on the Python standard library. Ports depend only on their own
domain. Application depends only on its own domain and ports. Contracts do not import
core, FastAPI, Pydantic or provider/infrastructure packages. The architecture test
enumerates every new module with explicit standard-library and own-feature allowlists,
and enforces inward layer dependency direction.

## Generic ingestion projection

Document ingestion accepts an optional `document-retrieval-projection.v1` descriptor.
Absence preserves legacy ingestion and does not make the document eligible for
The versioned Retrieval contract. Presence requires exactly one canonical chunk and supplies a caller-owned
locator, stable source family, generation, ordinal, actor keys, optional ordered UTC
interval, optional ordered source-relative millisecond interval, kind, category and
tags. Neither interval is fabricated, and a non-temporal projection may carry neither.
Canonical versions, document/chunk identities,
provider identity, text, citations, aliases and authorization remain server-owned or
outside this contract.

The locator is never derived from canonical Infinity identities. Permanent locator
ownership is scoped by space, memory scope and locator; active ordinal ownership also
includes optional thread, source key, generation and ordinal. Exact projection, scope,
content-hash and idempotency retries are idempotent. Locator, ordinal and idempotency
drift use stable typed conflicts. Equal content with a different locator remains a
distinct projected document. PostgreSQL ownership and atomicity are deferred to the
canonical adapter implementation.

## Mechanical bounds

- query variants: `1..6`; normalized query length: `1..512` characters;
- registered providers: `1..4`; provider rank: `1..1000`;
- source-generation pairs: `1..100`, sorted with unique source keys;
- candidate limit: `1..1000`; result limit: `1..50`;
- neighbor radius: `0..2`;
- response-byte limit: `16384..1048576`; the minimum holds every mandatory envelope,
  and every normal or fallback response is checked against its actual encoded size;
- deadline attestation: `1..2000` milliseconds;
- separate 40-hex service and compatible official SDK source revisions;
- query weights: `0.1..10`;
- provider and soft-preference `weight_micros`: `100000..10000000`.

Trusted core provider registration, capability lanes and request-controlled soft
preferences and query variants store only exact integer `weight_micros` values in
`100000..10000000`. Arbitrary query, provider or soft-preference weight floats are not
valid authoritative inputs.

Every canonical version and relative millisecond endpoint is an integer in the
lossless JSON range through `9007199254740991`; booleans are not integers. Capability
fingerprints never hash floating-point JSON numbers. Attested weights use exact integer
millionths (`weight_micros`, `100000..10000000`), allowing Python and JavaScript to hash
the same recursively key-sorted compact UTF-8 JSON bytes for every allowed value.
Every opaque string collection and JSON object key is ordered lexicographically by
its unsigned UTF-8 byte sequence. TypeScript/JavaScript implementations must compare
`Buffer.from(value, "utf8")` bytewise (for example with `Buffer.compare`) and must not
use the runtime's default UTF-16 string sort.

The capability fingerprint binds the policy, `K`, weight/preference/pico scales, 25%
boost cap, contribution `round_half_even`, preference `floor`, and canonical
exact-key/inclusive-interval-overlap match policy. The server maps every attested value
explicitly into core. No layer may silently default or clamp an unsupported request.

## Consequences and follow-up

This slice establishes reusable mechanics without a third generic retrieval package and
without modifying legacy `context_ranking.py`. The server/adapters integration supplies
canonical Postgres hydration and ownership, lexical/Qdrant providers, capability
attestation, bounded HTTP mapping, and durable projection repair. TypeScript SDK
delivery remains separately owned; this worktree provides exact shared fixtures for
that owner. Context-eval/performance qualification remains separate work. Graphiti
remains optional derived evidence.

## Server/adapters source classification

The concrete integration keeps provider dependencies outside the core and classifies
the added production seams as follows:

```text
infinity_context_server/features/context_building/retrieval_service.py       application composition/attestation
infinity_context_server/features/context_building/retrieval_mappers.py       contract boundary mapping
infinity_context_server/retrieval_profile_composition.py                    provider composition
infinity_context_server/retrieval_profile_outbox.py                         outbox application coordination
infinity_context_server/api/v1/context_retrieval.py                          HTTP adapter
infinity_context_adapters/postgres/locator_retrieval.py                      canonical read/lexical adapter
infinity_context_adapters/postgres/projected_document_ingestion.py           canonical write adapter
infinity_context_adapters/postgres/locator_models.py                         canonical persistence model
infinity_context_adapters/postgres/retrieval_projection_mapping.py           fail-closed projection mapper
infinity_context_adapters/postgres/locator_index_maintenance.py              derived-index repair state
infinity_context_adapters/postgres/migrations/0039_locator_retrieval_attributes.sql canonical schema migration
infinity_context_adapters/qdrant/locator_profile.py                          derived payload/schema adapter
infinity_context_adapters/qdrant/locator_runtime.py                          derived runtime adapter
```

`RetrieveLocators` remains the sole generic fusion, ranking, hydration and neighbor
orchestrator. PostgreSQL remains lifecycle authority; Qdrant exposes candidate signals
only.

## Profile lifecycle vertical slice

Migration `0040_locator_profile_lifecycle` adds the production lifecycle without
changing published migration `0039`. PostgreSQL owns immutable profile/generation/
digest/collection identity and permits at most one `building` and one `active` profile;
prior active profiles become `retained` rollback targets. With no canonical active
profile, composition keeps the pre-lifecycle Retrieval target, so rollout remains
inactive by default and legacy routes are unchanged.

The rebuild use case reads bounded canonical eligible-chunk pages in byte-stable
identity order, persists a resume cursor and canonical commit watermark, and records
per-profile projection receipts. Activation recomputes expected and projected count
and SHA-256 stream digests from canonical rows and receipts. It rechecks those values,
dead jobs, oldest queue lag, required-lane health/profile qualification and every
retained-profile tombstone inside the same transaction that promotes the building
profile. The same gated promotion can restore a retained profile for rollback. There
is no override path.

Every activation or retained-profile rollback transition carries a fresh operation/lease
identity. A retry of that same operation replays its consumed transition audit, while a
later transition receives a different identity; profile generation or digest must never
be reused as a deterministic lease. Strict-admin create, rebuild, attest and activate
also persist an exact-result receipt keyed by idempotency key and a canonical request
fingerprint. The same key and request replay without advancing lifecycle state, and key
reuse for a different request is a conflict.

The lease also binds the exact PostgreSQL evidence aggregate version and the final
inactive derived-mutation epoch. Issuance and promotion compare both under the stable
maintenance/evidence/profile lock order, reject every active mutation row, and use
PostgreSQL time for expiry. An evidence ABA, stale caller clock, or mutation begun after
the physical scan therefore makes promotion fail closed.

Qdrant attestation checkpoints are provisional until a complete incremental validation
pass authenticates their content-addressed per-page manifest. Scan and validation work
both enforce explicit page, encoded-byte and monotonic-deadline bounds, so profiles above
16,384 points resume without retaining or replaying an unbounded prefix in one process.
Corrupt, missing or drifted page evidence fails closed. Exact-version stale-write cleanup
is part of the consumer-owned projection port and cannot be weakened by adapter
substitution.

Profile tombstone cleanup observes the deterministic point id before choosing a
generation to delete. A generation at or below the revalidated canonical tombstone
fence is deleted with an exact-version filter and read back; a newer generation is
preserved and cannot complete the older tombstone. PostgreSQL persists the actual
deleted generation, provider-observation time and completion only after the same
canonical fence is revalidated. Missing receipts, crashed upserts and historical
completion therefore never authorize an inferred `N-1` generation.

Every composed Qdrant mutation durably opens and closes a PostgreSQL-owned provider
mutation epoch and heartbeats its exact operation/epoch while bounded provider I/O is
in flight. Heartbeat expiry is diagnostic only: it never deletes or steals the durable
fence, so an ambiguous timeout or crash remains fail closed until explicit recovery
can prove that no provider operation is live. A scan authenticates the same inactive
epoch before and after every physical page and across every restart; an active, stale,
or changed mutation fence fails closed, including when the changed page was validated
in an earlier slice. Locator search validates collection and payload-index schema but
never creates or repairs either on a read path.
Each bounded page also proves deterministic point-id retrievability and a present,
finite dense vector of the configured dimension while retaining only locator identity,
canonical version and payload digest evidence.

The projection worker renews the active profile's short lease before expiry by running
the same bounded physical reconciliation. Its operation id is derived from the prior
durable lease, remains stable across process restarts while pages are incomplete, and
rotates after every success or drift so completed evidence is never reused as a fresh
observation. The operation durably records the exact predecessor lease id, generation,
evidence digest, issue/expiry times and drift state. Completion compares-and-swaps that
whole predecessor. Two workers may replay one exact winning result, but replay never
extends its expiry and any superseded worker cannot alter or renew the active lease.
Missed renewal and physical drift leave the route fail closed. Strict-admin
rebuild pages first persist a recoverable bounded plan; projection receipts, the backfill
checkpoint, and the exact response receipt then commit atomically, so a crash after the
provider upsert can replay the plan without advancing another page. Attestation page
manifests retain every in-progress recovery page. After success they compact to one
minimal checkpoint receipt plus the current reconciliation receipt and one predecessor
audit receipt. With 256-point pages a
16,385-point renewal therefore uses at most 67 checkpoint/page rows while active and
one checkpoint row after completion, independent of renewal count. Retirement
atomically enters the retired generation and advances the provider epoch, which rejects
every new mutation while existing exact writers drain. Only then does PostgreSQL issue
one immutable delete token bound to that epoch. Physical absence is verified before the
same token advances cleanup; stale writers therefore cannot recreate the collection.
PostgreSQL cleanup follows physical deletion and removes the final receipt and all
remaining recovery evidence.

Profile-aware retrieval also opens a PostgreSQL-owned reader row bound to the exact
current activation lease before provider execution. That row remains through final
canonical hydration and is released by exact operation and lease identity. Activation,
retirement and collection-delete authorization reject while any such reader exists.
Reader deadlines are diagnostic only, so a crashed or ambiguous reader fails closed
instead of allowing a delete/query race.

Query admission returns exactly `no_profile`, `admitted`, or `unavailable` while holding
the maintenance/evidence gate and all routable profile rows in one transaction. Only
`no_profile` permits the pre-profile target. A configured building, retained, drifted,
expired, transitioning, or otherwise unfenceable registry is `unavailable`; it never
falls through to an unfenced target. Exact reader close mismatch is a stable observable
failure.

Every reader and provider-mutation row is owned by a durably registered runtime instance
and restart generation. Deadlines never steal those rows. Recovery first opens a durable
maintenance generation, which blocks query, provider mutation, activation, retirement,
delete and trigger-bearing writer admission. Every registered live incarnation must
drain and acknowledge that generation; an incarnation that cannot acknowledge requires
an append-only strict-operator dead-owner seal. Only then may the strict-admin
`retrieval-profile-recover` command or `/internal/retrieval-profiles/recoveries` API
release one exact owner/operation/lease-or-epoch. The exact stale deadline remains part
of target identity, never liveness authority. Recovery uses a normalized reason,
idempotency key, and create-only receipt. Provider-mutation recovery additionally consumes
a provider-produced observation receipt bound to collection, profile identity and
generation, maintenance generation, evidence epoch, observed count/digest and provider
state; it records only release for fresh
attestation, never provider success. Changed/new owners, partial selection, conflicts,
and ambiguous provider state fail closed.

Activation and reconciliation gates serialize on a PostgreSQL aggregate evidence
version. Canonical chunks, profile lanes, profile outbox rows, projection receipts and
tombstones advance that version and immediately expire any active evidence lease. An
adverse commit either precedes the gate and is observed, or follows it and invalidates
the result; it cannot commit invisibly across the gate CAS.

Canonical chunk triggers enqueue versioned upserts or deletes for every building,
active and retained profile. Qdrant deletes carry the exact canonical version; stale
jobs cannot delete newer points or complete newer tombstones. A stale backfill write
cannot advance its receipt and must retry from canonical state. The active registry
entry selects the request target; Qdrant collections remain derived and disposable.

Diagnostics are keyed only by bounded profile id and registered event/reason names.
They expose request outcome/latency, capability and lane failures, coverage/backfill,
queue retry/dead/oldest lag, tombstone progress and activation rejection counts. Raw
queries, canonical text and locators are never metric labels or diagnostic values.

The official TypeScript and synchronous Python HTTP clients expose the same strict
locator-only call and share the repository fixtures as their compatibility oracle.
Both validate request, capability/profile/fingerprint, response and typed error
envelopes; TypeScript compares unsigned UTF-8 identity bytes and uses `BigInt` for
scoring products. One absolute deadline covers validation, transport reads and retries;
blocked reads are interruptible. Python owns an async HTTP exchange behind its synchronous
facade: timeout/cancellation aborts the socket task and awaits task/client cleanup before
returning; normal callers and callers already inside an event loop use the same joined,
non-daemon owned-loop thread lifecycle. Cancellable calls accept only a default async transport,
an explicit `async_transport`, or a dual-protocol transport such as HTTPX `MockTransport`.
A sync-only custom transport is rejected with `memory.transport_capability_invalid` before I/O;
it is never moved to a worker thread or represented as killable. The ordinary synchronous SDK
surface receives only a sync transport and falls back to its default sync transport when the
legacy `transport` argument is async-only. Both SDKs expose the shared retrieval outcomes
`context_retrieval_deadline_exceeded`, `context_retrieval_cancelled` and
`context_retrieval_unavailable`; transport misconfiguration is a typed local capability error.

Abandoned runtime recovery is not an operator assertion. Production startup loads a
canonical public supervisor registry from a deployment-owned, non-substitutable path and
matches its exact SHA-256 digest, generation and required key ID against deployment pins.
The server identity may neither own nor write the file or a substitutable ancestor; root
server execution therefore fails closed. Embedded launch keys are evidence only and must
equal the independently loaded registry key. Private signing material remains in the
external launcher/supervisor process.

The registry also pins the exact installed release identity: immutable service revision,
source-tree digest, complete installed-distribution digest and the independently measured
repository runtime-module digest. Server and canary Qdrant composition recompute the
installed build before accepting the registry. The signed launch and death payloads,
runtime incarnation, transition/operator/provider/recovery receipts and qualification
output all use `retrieval-lifecycle-proof-identity.v1`; a mismatch in revision, source,
distribution, runtime modules, registry release or persisted identity fails closed.

The first admitted operation durably binds an exact runtime generation to the pinned
trust-root digest and registry generation, supervisor-signed launch token, PID and
Linux process-birth identity, executable path/digest, and Ed25519 key. Registration checks
those fields against the process executing the PostgreSQL admission, so copying a supervised
child's owner into a live parent cannot create authority. Server composition consumes an
external launch identity and reports the root digest, registry generation and key ID in
operator qualification/provenance output; without the trust binding both server and canary
Qdrant startup refuse to start. Only a signed,
scoped, unique proof emitted after that supervisor observes the same process exit can seal
the incarnation; trust root/generation, launch identity, exit observation, maintenance
generation, proof id and signature are checked against the same pinned public registry
before the recovery CAS. Provider reconciliation is likewise a
capability boundary: only the Qdrant adapter can persist a receipt, after live collection
readback, and the receipt binds profile/generation, collection, maintenance generation,
evidence epoch, exact mutation operation/owner/epoch/deadline, count, digest, provider state
and observation time. Recovery locks and consumes that receipt in the fence-removal CAS;
the durable unique reference prevents one physical observation from recovering two fences.

Migrations 0046-0047 are a drain boundary, not rolling-compatible with older binaries: every
pre-0046 process must stop before upgrade because it does not register readers. The
upgrade invalidates older leases while preserving profiles, in-flight fence evidence,
checkpoints and cleanup state. Downgrade to a pre-0046 binary is unsupported after the
migration; restore requires a canonical database backup and a compatible immutable
runtime, not DDL reversal.

Migration 0048 is the corresponding release-identity drain boundary. Its DDL is applied in
the migration runner transaction, so a failed forward application rolls back atomically.
Rollback after a successful application means restoring a canonical pre-0048 backup with
the pre-0048 binary; destructive down-migration is intentionally unsupported.

Migration 0049 enforces one unretired, unsealed generation per stable runtime instance. Its
read-only preflight reports every competing instance and all of its generations without locks,
DDL, mutation, or winner selection. On a populated 0048 database, operators must quiesce and
drain each listed process and use the 0048-compatible signed supervisor death-seal protocol for
each generation proved no longer live; 0048 has no canonical clean-retirement column. Only a
`ready` rerun permits upgrade. After 0049, a clean process drains its exact readers and writers
before setting `retired_at`; a crash still requires the authoritative death seal.

The Unix path check rejects runtime ownership of the registry file and every ancestor even
when mode bits are read-only, rejects runtime-owned sticky directories, and rejects symlink
components. A separately owned read-only layout is accepted. This check cannot infer POSIX
ACL grants, Linux capabilities, user-namespace or mount-policy substitution, overlayfs
behavior, or host/container immutable-mount guarantees. Deployments must enforce and audit
those controls outside the process; mode/UID checks are not represented as proof of them.

The mandatory 16,385-item acceptance starts each interpreter through the recoverable
launcher contract with no inherited registry, private key or adapter objects. Process A
writes a deliberately incomplete durable paged-attestation
checkpoint and exits; distinct process B reloads that checkpoint and completes it. Another builds a
separate successor Qdrant collection and its own PostgreSQL projection receipts, attests
that collection, activates it, then proves predecessor retirement, physical collection
deletion and residual PostgreSQL absence. Each child verifies the separately owned public
registry and source artifact after dropping OS identity; the parent supervisor signs its
launch, observes exit, and persists the integrated trust-root/release-bound completion proof.
