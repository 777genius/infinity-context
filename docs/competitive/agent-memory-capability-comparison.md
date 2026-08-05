# Agent memory capability comparison

**A source-backed comparison of Infinity Context, Hindsight, Mem0 OSS, and
Memora for teams choosing an agent-memory contract.**

## Contents

- [Bottom line](#bottom-line)
- [Scope and method](#scope-and-method)
- [Technical comparison](#technical-comparison)
- [Product strengths and limits](#product-strengths-and-limits)
- [Infinity Context and Hindsight](#infinity-context-and-hindsight)
- [Expected fit by scenario](#expected-fit-by-scenario)
- [Benchmarks and evidence boundaries](#benchmarks-and-evidence-boundaries)
- [Memory poisoning](#memory-poisoning)
- [Implications for Infinity Context](#implications-for-infinity-context)
- [Sources](#sources)

## Bottom line

There is no responsible single winner without a matched benchmark and a defined
workload. The most useful distinction is between two axes:

| Axis | Current standout | Why |
| --- | --- | --- |
| Cognitive memory | Hindsight | Rich retention, evidence-grounded observations, maintained mental models, broad multi-strategy recall, and an agentic Reflect loop |
| Governed shared project memory | Infinity Context | Canonical versioned state, version-bound provenance, scopes, reviewable promotion, and revalidation of derived candidates |

Mem0 OSS is a portable application-memory foundation with broad integrations.
Memora is an inspectable, local-first MCP memory workflow with smart absorb,
typed lineage, documents, action history, and graph-oriented UX.

These are different product shapes, not a measured quality order.

## Scope and method

Comparison date: **2026-08-05**.

This revision is based on a code-and-documentation audit of pinned public
repository snapshots plus local Infinity Context code. It is not a procurement
recommendation, security certification, or four-way performance benchmark.

An earlier internal comparison leaned too far toward Infinity Context. It
overweighted project governance, treated adapter potential as shipped provider
depth, under-penalized benchmark-shaped retrieval logic, and understated
Hindsight's observation and mental-model layers. This revision separates
verified capability from expected fit and future potential.

The comparison excludes popularity and community size. It also separates Mem0
OSS from Mem0 Platform: a managed feature or benchmark result is not evidence
for the open-source package.

Terms used here:

- **Canonical lifecycle** is an explicit system of record for current state,
  versions, visibility, provenance, and deletion.
- **Cognitive memory** is synthesis beyond stored facts, such as observations,
  evolving mental models, and reflection over experience.
- **Review** is a proposed-or-pending workflow. Direct editing or later curation
  is not the same as approval before promotion.
- **Provenance** records where a memory came from. It does not prove truth.
- **Isolation** describes documented addressing and policy boundaries, not a
  complete security guarantee.

## Technical comparison

| Capability | [Infinity Context](https://github.com/777genius/infinity-context) | [Hindsight](https://github.com/vectorize-io/hindsight) | [Mem0 OSS](https://github.com/mem0ai/mem0) | [Memora](https://github.com/agentic-box/memora) |
| --- | --- | --- | --- | --- |
| Primary shape | Governed current-state control plane for shared project memory | Cognitive memory system for agents that retain, recall, and reflect | Portable personalization memory and integration layer | Local-first MCP memory with graph interaction |
| Stored lifecycle | Postgres facts, documents, source refs, versions, scopes, review state, and tombstone-style deletion | Extracted world and experience facts, evidence-grounded observations, and versioned mental models | Current v3 extraction path is ADD-only; explicit update, delete, and history APIs remain application-driven | Smart absorb classifies duplicate, update, contradiction, or related memories; direct CRUD, merge, lineage, documents, and action history |
| Retrieval | Canonical queries plus optional Qdrant and narrower Graphiti candidates; final Postgres hydration | Semantic, BM25, graph, and temporal strategies with fusion, reranking, and Reflect | Semantic, BM25, and entity matching with optional reranking | FTS5, semantic, hybrid, date, tag, multi-query, and cross-reference retrieval with reciprocal-rank fusion |
| Synthesis | Rule/provider-based capture suggestions and context packing; no native observation, mental-model, or Reflect equivalent | Observations consolidate supporting memories; mental models are maintained over time; Reflect performs an agentic reasoning loop | Extraction and application memory; no equivalent cognitive pipeline asserted here | Absorb and relationship management, but no equivalent maintained mental-model layer asserted here |
| Change and contradiction | Expected versions, source-bound versions, lifecycle state, and reviewable fact or relation suggestions | Raw facts support reversible edit, invalidation, and restoration; affected observations are removed and reconsolidated from remaining facts | Manual CRUD/history; graph memory, temporal reasoning, decay, and custom timestamps are Platform capabilities | Typed contradiction and lineage, `active`, `latest`, and `full_history` retrieval modes |
| Provenance and review | Source refs attach to fact versions; suggestions and relations can be approved, rejected, or expired before canonical promotion | Observations retain source memories, exact supporting quotes, proof counts, history, and freshness; extracted facts are active before any mandatory approval gate | Metadata plus application-owned policy; no built-in pending review queue claimed | Source IDs, metadata, lineage, and direct actions; no separate approval queue claimed |
| Isolation | Spaces, memory scopes, threads, and scoped service tokens | Banks, tenant-aware storage paths, and metadata filtering | User, agent, and run identifiers | Configured stores, tags, hierarchy, and per-project MCP conventions |
| Deployment | Self-hosted lite stack; optional full profile adds Qdrant, Neo4j, and providers | Docker, Python/bare-metal, embedded options, worker and tenant controls | Library or self-hosted server with pluggable providers and vector stores | Local MCP server with SQLite; optional D1, S3, or R2 storage |
| Important limit | Early version; cognitive layer absent; provider adapters vary in depth; external scale evidence is limited | Model-heavy retention and reflection; no mandatory pre-canonical approval workflow | Do not attribute managed graph, temporal, decay, or benchmark claims to OSS | Vector search scans embeddings; cross-reference rebuild is all-pairs; distributed governance is application-owned |

## Product strengths and limits

### Infinity Context

Infinity Context is strongest where multiple agents and applications must agree
on current project state. Postgres owns versions, source references, scopes,
visibility, review state, and the outbox. Qdrant and Graphiti candidates are
rehydrated through canonical state before prompt rendering.

Its current limits are material:

- It has no native equivalent of Hindsight observations, maintained mental
  models, or Reflect.
- Graphiti is a real derived write, search, and delete adapter, but a narrow one:
  an update deletes the previous episode before adding the current episode. It
  primarily exchanges canonical IDs and does not expose complete Graphiti
  source-reference, ontology, or version-history semantics.
- Cognee is disabled by default and recall-oriented. Its ingest, update, and
  exact-forget lifecycle is not complete.
- Production retrieval contains deterministic prepasses shaped by domains used
  in current evaluations, including people, relationships, books, food, and
  event patterns. This is not ground-truth leakage, but it weakens evidence of
  transfer to unseen coding-agent workloads.
- Existing load and chaos tests use a limited corpus. They do not prove behavior
  at 100,000+ memories or with dozens of concurrent agents.

### Hindsight

Hindsight currently exposes the broadest cognitive-memory pipeline in this
group. Retention creates world and experience facts. Observations consolidate
evidence across memories while preserving supporting memory IDs, exact quotes,
proof counts, history, and freshness. Mental models are versioned and can be
refreshed in the background. Recall combines semantic, lexical, graph, and
temporal paths; Reflect adds an agentic reasoning loop.

Recent public changes also add reversible curation, tenant-aware worker
coordination, and a per-bank Memory Defense feature. Memory Defense is off by
default, so its presence should not be read as a default security guarantee.

The governance model differs from Infinity Context: extracted world and
experience facts become active without a mandatory pre-canonical human approval
step. Reversible curation acts on the supporting raw facts; affected
observations are then removed or reconsolidated. This is strong after-the-fact
curation, but not the same promotion boundary.

### Mem0 OSS

Mem0 OSS is well suited to teams embedding memory inside an existing product.
It supports user, agent, and run addressing, explicit update/delete/history
operations, pluggable LLM and embedding providers, and many vector-store and
framework integrations. The current v3 extraction path is intentionally
ADD-only and uses semantic, BM25, and entity matching with an optional reranker.

Important product separation:

- graph memory was removed from OSS v3 and is Platform-only;
- temporal reasoning and memory decay are Platform features;
- custom timestamp support is not an OSS capability;
- managed benchmark results must not be presented as Mem0 OSS results.

Applications that need review, canonical project versions, or contradiction
policy must add those contracts rather than infer them from managed features.

### Memora

Memora provides a practical local agent-memory experience. Smart absorb can
classify new input as duplicate, update, contradiction, or related memory.
Typed lineage, documents, action history, graph interaction, query rewriting,
multi-query retrieval, and `latest` or `full_history` modes make memory easy to
inspect and manipulate through MCP.

Its storage options deserve a balanced reading. SQLite provides FTS5 locally;
D1 does not have that FTS5 path. S3 and R2 integrations include local locking,
ETag conflict detection, and retry/backoff rather than being naive file writes.

For large or distributed deployments, the current algorithms impose limits:
semantic search scans stored embeddings, a complete cross-reference rebuild
compares all pairs, and related cross-references may be stale after an update
until rebuilt. Some relatedness behavior also relies on project-specific tag
heuristics. Native review-gated project governance and distributed scope policy
are not the product's main design center.

## Infinity Context and Hindsight

These systems start from different questions:

| Question | Infinity Context | Hindsight |
| --- | --- | --- |
| First design concern | What shared project state is current, visible, and reviewable? | What can an agent retain, learn, recall, and reflect on? |
| Primary boundary | Space, memory scope, and optional thread | Memory bank plus tenant and metadata boundaries |
| Change model | Explicit versioned canonical state and reviewable proposals | Active extracted facts plus reversible curation and reconsolidation |
| Higher-order memory | Suggestions, relations, and packed evidence | Evidence-grounded observations, mental models, and Reflect |
| Retrieval authority | Derived candidates must pass canonical hydration | Hindsight's bank owns retrieval and cognitive representations |

Hindsight currently exposes the more complete cognitive-memory pipeline.
Infinity Context exposes the stronger explicit project-memory governance
contract. Neither advantage establishes overall superiority without a shared
benchmark.

They could be combined in principle, but no Hindsight adapter ships today. A
future adapter would need to keep Infinity Context canonical state separate from
Hindsight experiential and cognitive representations, including clear update,
deletion, provenance, and failure semantics.

## Expected fit by scenario

This is an engineering-fit guide, not measured ordering.

| Scenario | Capability to prioritize | Expected starting point |
| --- | --- | --- |
| Several agents and applications need the same current architecture decision | Source-bound versions, scoped visibility, review, and stale-hit rejection | Infinity Context |
| An autonomous agent should consolidate experience and reason over learned patterns | Observations, mental models, multi-strategy recall, and reflection | Hindsight |
| A product needs portable user or agent personalization through SDKs and integrations | Simple addressing, application-owned lifecycle, and provider choice | Mem0 OSS |
| One developer wants local MCP actions, lineage, history, documents, and a visual graph | Inspectable local storage and graph-oriented interaction | Memora |
| A high-risk workflow needs evidence of security or scale | Threat model, representative load test, adversarial evaluation, access control, retention, and audit | Evaluate every deployment beyond this table |

Run a proof on representative data, updates, deletes, permission boundaries,
poisoned inputs, provider outages, and realistic concurrency before choosing.

## Benchmarks and evidence boundaries

Product benchmarks are not directly comparable here:

- Infinity Context's [Mem0 engineering runner](../memory-comparison-benchmark.md)
  is a small, project-authored canary. It does not evaluate Hindsight or Memora,
  and benchmark-shaped production heuristics reduce its external validity.
- Hindsight publishes vendor benchmark results and methodology. They are useful
  product evidence, not an independent matched test of these four systems.
- Mem0 managed benchmark claims include proprietary optimizations and cannot be
  assigned to Mem0 OSS.
- The historical [direct Memora smoke](memora-agent-memory-comparison.md) proves
  one local TF-IDF/SQLite MCP contract, not general retrieval or scale.

Recent independent preprints expose broader blind spots:

- [MemoryArena](https://arxiv.org/abs/2602.16313) reports that systems strong on
  conversational-memory benchmarks can still struggle with interdependent,
  multi-session agent tasks.
- [Mem2ActBench](https://arxiv.org/abs/2601.19935) evaluates whether remembered
  knowledge actually improves tool selection and parameter grounding, not just
  recall.
- [LongMemEval-V2](https://arxiv.org/abs/2605.12493) focuses on environment
  experience and operational gotchas in long-running agents; its results also
  highlight latency and retrieval-design tradeoffs.

These papers do not benchmark the four products in this table. They show why
recall scores alone are insufficient for an agent-memory claim.

## Memory poisoning

Canonical hydration and review reduce exposure, but they do not prove safety.
An approved source can still be malicious, a reviewer can miss a delayed
payload, and later retrieval can activate behavior that was harmless-looking at
ingest time.

Two recent preprints demonstrate the risk:

- [Hidden in Memory: Sleeper Memory Poisoning](https://arxiv.org/abs/2605.15338)
  studies poisoned memories that trigger attacker-intended behavior when later
  retrieved.
- [Hijacking Agent Memory](https://arxiv.org/abs/2605.29960) studies attacks that
  survive selective extraction and rewriting defenses.

For sensitive deployments, evaluate ingestion policy, review UX, source trust,
retrieval-time scanning, least-privilege tools, deletion propagation, and
adversarial tests together. No product here should be called secure from its
memory architecture alone.

## Implications for Infinity Context

The research suggests the following priorities. They are roadmap directions,
not shipped capabilities:

1. Add a review-aware cognitive layer from episodes and experiences to
   observations, mental models, and lessons, with evidence preserved through
   every promotion.
2. Make the Graphiti projection version-aware instead of representing only the
   current canonical episode.
3. Complete or remove the incomplete Cognee ingest, update, and exact-forget
   lifecycle.
4. Separate generic coding-agent ranking from benchmark- or domain-specific
   heuristics and measure both independently.
5. Build a hidden evaluation that includes tool use, poisoning, stale indexes,
   provider failures, dozens of agents, and 100,000+ memories.
6. Consider Hindsight as a future experiential adapter only after canonical
   ownership, provenance, update, and deletion semantics are explicit.

## Sources

Repository snapshots audited for this revision:

- [Hindsight at `59d3f078`](https://github.com/vectorize-io/hindsight/tree/59d3f078cd8b32fe6cec67a533a33f2146dbdfcc)
- [Mem0 at `3f717e54`](https://github.com/mem0ai/mem0/tree/3f717e5459f5311f02ea8ba49d58fe0ada08779f)
- [Memora at `bc64ff74`](https://github.com/agentic-box/memora/tree/bc64ff745a9b2c0e6245e0137654f041fba0c155)
- [Infinity Context architecture and trust model](../architecture-and-trust-model.md)

Primary capability references:

- [Hindsight observations and evidence](https://github.com/vectorize-io/hindsight/blob/59d3f078cd8b32fe6cec67a533a33f2146dbdfcc/hindsight-docs/blog/2026-07-13-inside-retain-agent-memory.md)
- [Hindsight reversible curation and Memory Defense](https://github.com/vectorize-io/hindsight/blob/59d3f078cd8b32fe6cec67a533a33f2146dbdfcc/hindsight-docs/blog/2026-06-12-version-0-8-2.md)
- [Hindsight paper](https://arxiv.org/abs/2512.12818)
- [Mem0 OSS v2 to v3 migration](https://github.com/mem0ai/mem0/blob/3f717e5459f5311f02ea8ba49d58fe0ada08779f/docs/migration/oss-v2-to-v3.mdx)
- [Mem0 Platform temporal reasoning](https://github.com/mem0ai/mem0/blob/3f717e5459f5311f02ea8ba49d58fe0ada08779f/docs/platform/features/temporal-reasoning.mdx)
- [Memora storage and retrieval implementation](https://github.com/agentic-box/memora/blob/bc64ff745a9b2c0e6245e0137654f041fba0c155/memora/storage.py)
