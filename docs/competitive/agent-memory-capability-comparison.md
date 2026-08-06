# Agent memory capability comparison: 10 systems

**A source-backed architecture audit of ten open agent-memory systems for teams
choosing a durable memory contract. Comparison date: 2026-08-05.**

## Contents

- [Bottom line](#bottom-line)
- [Scope and method](#scope-and-method)
- [Category leaders](#category-leaders)
- [Ten-system comparison](#ten-system-comparison)
- [Product strengths and limits](#product-strengths-and-limits)
- [Infinity Context and Hindsight](#infinity-context-and-hindsight)
- [Expected fit by scenario](#expected-fit-by-scenario)
- [Benchmarks and evidence boundaries](#benchmarks-and-evidence-boundaries)
- [Memory poisoning](#memory-poisoning)
- [Implications for Infinity Context](#implications-for-infinity-context)
- [Sources](#sources)

## Bottom line

There is no universal winner. These products optimize for different jobs:
cognitive learning, a unified coding-agent context, wide memory types, local
files, integration speed, or governed shared project state.

Under this audit's explicitly trust-weighted coding-agent rubric, **Infinity
Context is the strongest fit for governed current-state project memory**. For
governed shared project state, it has the clearest explicit trust contract in
this audited set: canonical versions, version-bound provenance, scoped
visibility, review-gated promotion, and derived-hit revalidation.

That is an architecture-fit conclusion, not a claim that Infinity Context is
best at every kind of memory or a substitute for a matched benchmark.

## Scope and method

This revision audits public documentation and code at pinned repository
snapshots, alongside local Infinity Context architecture. Research date:
**2026-08-05**. It is not a procurement recommendation, security
certification, or measured ten-way performance benchmark.

The rubric intentionally gives high weight to the risks that matter in
long-lived coding-agent projects:

- canonical write and change lifecycle;
- provenance, review, and retrieval-time trust boundaries;
- scoped visibility, versions, and deletion;
- retrieval usefulness without treating a search result as authority;
- architecture, operability, and open-source completeness.

### Score transparency

The research scores below are a source-audited, project-weighted architecture
assessment out of 100, not measured product performance. The same published
rubric was applied to every system, with no Infinity-specific bonus. It excludes
popularity, company size, and managed-only features. A separate source-check
review pass checked claims against pinned public code, documentation, and
current issues. This process is designed to reduce bias, not to claim that a
project-authored comparison is bias-free. Each criterion is rated on a 0-10
scale; the weighted result is scaled to 100.

| Criterion | Weight |
| --- | ---: |
| Memory model | 12% |
| Write and lifecycle | 20% |
| Retrieval | 17% |
| Trust and provenance | 16% |
| Scope, version, and delete | 10% |
| Agent usefulness | 10% |
| Architecture | 10% |
| OSS completeness | 5% |

<details>
<summary>Full 0-10 scoring matrix</summary>

| Product | Model | Lifecycle | Retrieval | Trust | Scope | Agent | Architecture | OSS | Total / 100 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Infinity Context | 8.8 | 9.8 | 8.8 | 10.0 | 9.8 | 9.3 | 9.4 | 8.5 | **93.9** |
| Hindsight | 10.0 | 8.8 | 9.8 | 8.6 | 8.8 | 9.3 | 9.0 | 8.8 | 91.5 |
| OpenViking | 9.8 | 8.6 | 9.3 | 8.6 | 9.3 | 9.8 | 9.1 | 8.0 | 90.7 |
| MemOS | 10.0 | 7.9 | 9.1 | 7.7 | 8.8 | 9.5 | 8.5 | 7.7 | 86.2 |
| MatrixOrigin Memoria | 8.5 | 7.3 | 8.5 | 8.4 | 9.9 | 8.6 | 9.3 | 8.0 | 84.5 |
| MemMachine | 8.8 | 7.4 | 8.6 | 9.0 | 8.4 | 8.7 | 8.8 | 8.0 | 84.3 |
| Honcho | 9.4 | 7.1 | 9.2 | 7.8 | 8.8 | 9.0 | 9.0 | 7.0 | 83.9 |
| EverOS | 9.0 | 6.5 | 8.7 | 8.5 | 8.8 | 8.8 | 9.3 | 8.0 | 83.1 |
| Memora | 8.0 | 8.1 | 8.3 | 7.4 | 8.0 | 9.0 | 7.3 | 8.0 | 80.1 |
| Mem0 OSS | 7.8 | 5.5 | 8.0 | 6.3 | 8.2 | 9.5 | 8.8 | 7.7 | 74.4 |

The total is the weighted average of the 0-10 criterion scores, scaled to 100.
These criterion scores are documented audit judgments, not measured product
performance.

</details>

Readers can inspect the pinned sources below, apply the published weights, and
recalculate the assessment. Estimated uncertainty is plus or minus three
points; differences within three points should be read as the same
technical class rather than a decisive product gap.

Terms used here:

- **Canonical lifecycle** is an explicit system of record for current state,
  versions, visibility, provenance, and deletion.
- **Cognitive memory** synthesizes beyond stored facts, for example
  observations, mental models, and reflection over experience.
- **Review gate** is a proposed-or-pending workflow before promotion. Direct
  editing or later curation is not the same thing.
- **Provenance** records where a memory came from. It does not prove truth.
- **Derived index** helps find candidates. It is not automatically authorized
  to decide what is current or visible.

## Category leaders

| Need | Audited standout | Why it stands out |
| --- | --- | --- |
| Governed shared current state | [Infinity Context](https://github.com/777genius/infinity-context) | Canonical Postgres lifecycle, source-bound versions, scopes, review, and revalidation before prompt use |
| Cognitive memory and reflection | [Hindsight](https://github.com/vectorize-io/hindsight) | Evidence-grounded observations, maintained mental models, broad recall, and Reflect |
| Unified coding-agent context | [OpenViking](https://github.com/volcengine/OpenViking) | One context layer for memories, resources, and skills with layered retrieval and trajectories |
| Broad Memory OS surface | [MemOS](https://github.com/MemTensor/MemOS) | MemCubes, multi-cube routing, schedulers, providers, and many memory forms |
| Branches and recoverable alternatives | [MatrixOrigin Memoria](https://github.com/matrixorigin/Memoria) | Snapshots, branches, checkout, merge, diff, and rollback |
| Source-linked conversation memory | [MemMachine](https://github.com/MemMachine/MemMachine) | Episodic records and profile facts that point back to source episodes |
| Peer and user modeling | [Honcho](https://github.com/plastic-labs/honcho) | Explicit, deductive, inductive, and contradiction-aware conclusions |
| Readable local memory files | [EverOS](https://github.com/EverMind-AI/EverOS) | Markdown is canonical for memory content, with local derived indexes |
| Lightweight local MCP memory | [Memora](https://github.com/agentic-box/memora) | Local-first MCP, typed lineage, documents, and graph interaction |
| Fast product integration | [Mem0 OSS](https://github.com/mem0ai/mem0) | SDK and provider ecosystem with user, agent, and run addressing |

## Ten-system comparison

| Rank | Product | Research score / 100 | Memory shape | Strongest advantage | Current-state or adoption caveat |
| --- | --- | ---: | --- | --- | --- |
| 1 | [Infinity Context](https://github.com/777genius/infinity-context) | **93.9** | Postgres-canonical facts, documents, sources, versions, scopes, and review state | Explicit trust contract for changing project knowledge | Cognitive layer and broad scale evidence remain limited |
| 2 | [Hindsight](https://github.com/vectorize-io/hindsight) | 91.5 | Facts, observations, mental models, recall, and reflection | Deepest cognitive-memory pipeline in this set | Strong after-the-fact curation, but no mandatory pre-canonical review gate |
| 3 | [OpenViking](https://github.com/volcengine/OpenViking) | 90.7 | viking:// context filesystem for memories, resources, and skills | L0/L1/L2 context layers, retrieval trajectories, and snapshot history with forward-commit restore | Version history is not by itself a semantic current-state or review contract |
| 4 | [MemOS](https://github.com/MemTensor/MemOS) | 86.2 | MemCubes, multi-cube routing, scheduler, multi-type memory, and providers | Broadest Memory OS surface | Evaluate lifecycle guarantees separately for each memory type and integration |
| 5 | [MatrixOrigin Memoria](https://github.com/matrixorigin/Memoria) | 84.5 | Branchable memory with snapshots, diff, merge, and rollback | Strongest explicit branching workflow | A branch system does not automatically resolve semantic contradictions |
| 6 | [MemMachine](https://github.com/MemMachine/MemMachine) | 84.3 | Episodic, profile, and working memory with source-linked episodes | Source-linked conversational recall | A citation links to an episode, not to truth; retrieval agents use selected stores |
| 7 | [Honcho](https://github.com/plastic-labs/honcho) | 83.9 | Peer and user models with explicit and inferred conclusions | Modeling a person's evolving knowledge and preferences | Operational setup and project-state governance need separate evaluation |
| 8 | [EverOS](https://github.com/EverMind-AI/EverOS) | 83.1 | Markdown memory content, SQLite operational state, and LanceDB derived indexes | Transparent local files and Git-friendly inspection | Derived retrieval is eventually consistent and has no automatic Markdown grep fallback |
| 9 | [Memora](https://github.com/agentic-box/memora) | 80.1 | Local MCP memory with smart absorb, lineage, documents, and graph interaction | Inspectable local workflow | Review-gated distributed project governance is not its main design center |
| 10 | [Mem0 OSS](https://github.com/mem0ai/mem0) | 74.4 | Portable personalization memory and integration layer | Fast SDK-led adoption and provider choice | Application code owns review, current-state policy, and product-specific lifecycle |

## Product strengths and limits

### Infinity Context

Infinity Context is designed for the case where people, agents, and
applications must agree on what a project currently knows. Postgres owns
facts, documents, sources, versions, scope, visibility, review state, and the
outbox. Qdrant and Graphiti are optional derived projections.

Its trust boundary is intentionally concrete:

- A fact version binds its source and lifecycle state to the current claim.
- Scoped visibility, expected versions, deletion, and reviewable suggestions
  control what may become canonical.
- A transactional outbox drives derived projections instead of making a vector
  or graph index authoritative.
- Qdrant and Graphiti can find a candidate. Only current, visible Postgres
  state can enter the prompt after rehydration and validation.
- Prompt memory is rendered as cited evidence, not as an instruction for a
  model to obey.

This directly targets stale, false, out-of-scope, and silently promoted project
state. It is why Infinity Context leads this audit's governed-current-state
category.

Important limits are material:

- It has no wired or persisted cognitive pipeline comparable to Hindsight.
  Current `main` contains only provider-neutral cognitive candidate types and
  derivation policy for experiences, observations, lessons, and mental models.
- The Graphiti adapter is intentionally narrow. It represents current-state
  projection and does not expose Graphiti's complete source-reference,
  ontology, or version-history surface.
- Cognee is disabled by default and its ingest, update, and exact-forget
  lifecycle is incomplete.
- Retrieval includes deterministic prepasses shaped by current evaluation
  domains. This is not ground-truth leakage, but transfer to unseen
  coding-agent workloads needs independent evidence.
- Existing load and chaos tests use a limited corpus. They do not yet prove
  behavior at 100,000+ memories or across dozens of concurrent agents.

### Hindsight

Hindsight has the broadest cognitive-memory pipeline in this set. Retention
creates world and experience facts. Observations consolidate evidence while
preserving supporting memory IDs, quotes, proof counts, history, and freshness.
Mental models are versioned and can refresh in the background. Recall combines
semantic, lexical, graph, and temporal paths; Reflect adds an agentic reasoning
loop.

Its lifecycle model differs from Infinity Context. Extracted facts become
active without a mandatory human approval boundary. Reversible curation can
invalidate raw facts and reconsolidate affected observations, which is strong
after-the-fact governance but not the same as review-gated promotion.

### OpenViking

OpenViking treats context as a viking:// virtual filesystem that unifies
memories, resources, and skills. Its L0/L1/L2 representations, intent-aware
retrieval, and debug retrieval trajectories make it particularly compelling for
coding agents that need to navigate a large context surface. Commit, log, show,
diff, and restore operations provide snapshot history. Restore records a new
commit on the current history rather than rewinding it or creating a branch.

That model is not the same as an explicit semantic current-state contract with
version-bound provenance and promotion review. Also, [issue #3273](https://github.com/volcengine/OpenViking/issues/3273)
is an open report of a v0.4.5 concurrency risk during LLM extraction. It should
be treated as a reported version-specific risk, not as proof of current behavior
in every deployment.

### MemOS

MemOS is the broadest Memory OS in the comparison: MemCubes, multi-cube
routing, scheduling, feedback, providers, and diverse memory forms give it a
large experimentation surface. It is a strong candidate when a product needs
to route across several memory types rather than enforce one narrow project
state model.

Breadth creates a verification cost. Lifecycle, conflict, retention, and
retrieval guarantees should be checked per MemoryCube and integration. Some
parametric or LoRA-oriented work is marked Coming Soon and is not counted here
as shipped capability. Historical [issue #1333](https://github.com/MemTensor/MemOS/issues/1333)
is closed, so it is not evidence for a current full-text-search degradation
claim.

### MatrixOrigin Memoria

MatrixOrigin Memoria provides a strong recoverability model: snapshots,
branches, checkout, merge, diff, rollback, and copy-on-write storage support
alternative memory timelines. It also combines semantic, profile, procedural,
working, and tool-result memory with hybrid retrieval.

Branches are useful when teams need to inspect or restore a previous state, but
they do not by themselves decide which conflicting claim is semantically
current. [Issue #88](https://github.com/matrixorigin/Memoria/issues/88) is an
open example of an obvious contradiction that was not automatically
consolidated. Treat it as a concrete behavior gap to evaluate, not a general
security verdict.

### MemMachine

MemMachine organizes raw conversations into episodic memory, profile or
semantic memory, and working memory. Profile facts can cite their source
episodes, which makes it a strong option for source-linked conversational
memory and inspectable assistant recall.

Source linkage is provenance, not truth. Its retrieval agents do not all use
every memory type, so real fit depends on the chosen agent and retrieval path.
Its public HotpotQA examples are useful product evidence, but a
vendor-controlled example should not be generalized to arbitrary project
memory, latency, or precision workloads.

### Honcho

Honcho is aimed at peer and user models rather than a canonical shared project
database. Its Deriver, Dialectic, and Dreamer reasoning surfaces support
explicit, deductive, inductive, and contradiction-related conclusions about a
person's evolving knowledge, preferences, and reasoning.

That is a useful differentiated shape for assistants that need to understand a
user. It is not automatically a governed project-state layer. [Issue #494](https://github.com/plastic-labs/honcho/issues/494)
reports an operational/configuration concern around the worker surface; it is a
deployment-specific caveat to validate, not a universal product defect.

### EverOS

EverOS makes Markdown the canonical representation for memory content, while
SQLite holds operational state such as audit and queue data. LanceDB provides a
derived hybrid retrieval index. This makes local memory readable, grepable by
a person, and friendly to Git-oriented workflows.

The tradeoff is that derived retrieval is eventually consistent and does not
automatically fall back to Markdown grep. [Issue #133](https://github.com/EverMind-AI/EverOS/issues/133)
is a feature proposal, not an independently reproduced consolidation defect.
The product should be evaluated for its local transparency and workflow, not
penalized for an unproven bug claim.

### Mem0 OSS

Mem0 OSS is well suited to teams embedding memory inside an existing product.
It supports user, agent, and run addressing, explicit update/delete/history
operations, pluggable LLM and embedding providers, and many vector-store and
framework integrations. The current v3 extraction path is ADD-only and uses
semantic, BM25, and entity matching with an optional reranker.

Keep its open-source and managed offerings separate:

- Graph memory was removed from OSS v3 and is Platform-only.
- Temporal reasoning, memory decay, and custom timestamp support are Platform
  features, not claims for the OSS package.
- Managed benchmark results cannot be assigned to Mem0 OSS.

Applications that need review, canonical project versions, or contradiction
policy must add those contracts themselves.

### Memora

Memora provides a practical local agent-memory experience. Smart absorb can
classify new input as duplicate, update, contradiction, or related memory.
Typed lineage, documents, action history, graph interaction, query rewriting,
multi-query retrieval, and latest or full-history modes make memory easy to
inspect and manipulate through MCP.

SQLite provides FTS5 locally; D1 does not have that FTS5 path. For large or
distributed deployments, semantic search scans stored embeddings, a complete
cross-reference rebuild compares all pairs, and related cross-references may be
stale after an update until rebuilt. Native review-gated project governance and
distributed scope policy are not the product's main design center.

## Infinity Context and Hindsight

These systems start from different questions:

| Question | Infinity Context | Hindsight |
| --- | --- | --- |
| First design concern | What shared project state is current, visible, and reviewable? | What can an agent retain, learn, recall, and reflect on? |
| Primary boundary | Space, memory scope, and optional thread | Memory bank plus tenant and metadata boundaries |
| Change model | Explicit versioned canonical state and reviewable proposals | Active extracted facts plus reversible curation and reconsolidation |
| Higher-order memory | Suggestions, relations, and packed evidence | Evidence-grounded observations, mental models, and Reflect |
| Retrieval authority | Derived candidates must pass canonical hydration | Hindsight's bank owns retrieval and cognitive representations |

Hindsight exposes the more complete cognitive-memory pipeline. Infinity Context
exposes the stronger explicit project-memory governance contract. They could be
combined in principle, but no Hindsight adapter ships today. Any future adapter
would need clear canonical ownership, update, deletion, provenance, and failure
semantics.

## Expected fit by scenario

This is an engineering-fit guide, not measured ordering.

| Scenario | Capability to prioritize | Expected starting point |
| --- | --- | --- |
| Long-lived Claude or Codex project with shared changing decisions | Current-state truth, scope, review, and stale-hit rejection | Infinity Context, then OpenViking when unified context matters most |
| One layer for memories, project resources, and skills | Unified context hierarchy and coding-agent navigation | OpenViking, then MemOS |
| Personal assistant that learns a person's knowledge and preferences | Cognitive synthesis or peer modeling | Hindsight, then Honcho |
| Product needs many memory types and routing policies | Multi-type Memory OS surface | MemOS, then OpenViking |
| Assistant must cite conversation evidence | Source-linked episodes and inspectable recall | MemMachine, then Hindsight |
| Workflow needs branches, snapshots, and rollback | Alternative timelines and recovery | MatrixOrigin Memoria |
| Developer wants readable local files | Markdown-first content and local transparency | EverOS, then Memora |
| Minimal-infrastructure coding-agent memory | Lightweight local storage and MCP | Memora, then EverOS |
| Product needs the fastest integration start | SDK ecosystem and application-owned policy | Mem0 OSS, then Memora |
| Cost of false current state is high | Canonical lifecycle, provenance, review, and revalidation | Infinity Context, then Hindsight for cognitive evidence |
| High-risk production workflow | Threat model, representative load, access control, retention, and adversarial evaluation | Evaluate every deployment beyond this table |

Run a proof on representative data, updates, deletes, permission boundaries,
poisoned inputs, provider outages, and realistic concurrency before choosing.

## Benchmarks and evidence boundaries

Product benchmarks are not directly comparable:

- Infinity Context's [Mem0 engineering runner](../memory-comparison-benchmark.md)
  is a small project-authored canary. It does not evaluate the other systems,
  and benchmark-shaped production heuristics reduce its external validity.
- Hindsight publishes vendor benchmark results and methodology. They are useful
  product evidence, not an independent matched comparison.
- MemMachine's public HotpotQA examples are vendor evidence, not a universal
  benchmark for every memory shape in this document.
- Mem0 managed benchmark claims include proprietary optimizations and cannot be
  assigned to Mem0 OSS.
- The historical [direct Memora smoke](memora-agent-memory-comparison.md)
  proves one local TF-IDF/SQLite MCP contract, not general retrieval or scale.

Recent independent preprints show why recall alone is insufficient:

- [MemoryArena](https://arxiv.org/abs/2602.16313) reports that systems strong on
  conversational-memory benchmarks can still struggle with interdependent,
  multi-session agent tasks.
- [Mem2ActBench](https://arxiv.org/abs/2601.19935) evaluates whether remembered
  knowledge improves tool selection and parameter grounding, not just recall.
- [LongMemEval-V2](https://arxiv.org/abs/2605.12493) focuses on environment
  experience and operational gotchas in long-running agents.

These papers do not benchmark the ten products here. They explain why a
product's architecture or recall score should not be read as a deployment
guarantee.

## Memory poisoning

Canonical hydration and review reduce exposure, but they do not prove safety.
An approved source can still be malicious, a reviewer can miss a delayed
payload, and later retrieval can activate behavior that looked harmless at
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

The audit supports the current trust-first direction and identifies concrete
roadmap work:

1. Complete and wire the existing provider-neutral cognitive foundation to
   persistence, public APIs, and review-aware promotion while preserving
   evidence from experiences through observations, lessons, and mental models.
2. Make the Graphiti projection version-aware instead of representing only the
   current canonical episode.
3. Complete or remove the incomplete Cognee ingest, update, and exact-forget
   lifecycle.
4. Separate generic coding-agent ranking from domain-shaped retrieval
   heuristics and measure both independently.
5. Build a hidden evaluation that includes tool use, poisoning, stale indexes,
   provider failures, dozens of agents, and 100,000+ memories.
6. Consider Hindsight as a future experiential adapter only after canonical
   ownership, provenance, update, deletion, and failure semantics are explicit.

## Sources

Pinned public repository snapshots audited for this revision:

- [Infinity Context architecture and trust model](../architecture-and-trust-model.md)
- [Hindsight at 59d3f078](https://github.com/vectorize-io/hindsight/tree/59d3f078cd8b32fe6cec67a533a33f2146dbdfcc)
- [Mem0 OSS at 12c47f52](https://github.com/mem0ai/mem0/tree/12c47f524935692e27ad48d829f35fa1e4417181)
- [Memora at bc64ff74](https://github.com/agentic-box/memora/tree/bc64ff745a9b2c0e6245e0137654f041fba0c155)
- [OpenViking at 674f5e60](https://github.com/volcengine/OpenViking/tree/674f5e6039bab1d35b822d2c3dc29fcecf9bab5b)
- [MemOS at 19bd86de](https://github.com/MemTensor/MemOS/tree/19bd86dec5dc64d093c562bb8fd6e11a42db60f9)
- [MatrixOrigin Memoria at 54c9114f](https://github.com/matrixorigin/Memoria/tree/54c9114fd6888e11821edc2ee9acd570c17c5ee3)
- [MemMachine at a681abf9](https://github.com/MemMachine/MemMachine/tree/a681abf9623299bba8ad931e5d9af02fb6ef0997)
- [Honcho at e6d4d78b](https://github.com/plastic-labs/honcho/tree/e6d4d78ba16f4138c2b07f2c4beb32174ef6295d)
- [EverOS at 72c1facd](https://github.com/EverMind-AI/EverOS/tree/72c1facdbfa3c07d97d29db106482cf643ae8231)

Primary capability and public-issue references:

- [Hindsight observations and evidence](https://github.com/vectorize-io/hindsight/blob/59d3f078cd8b32fe6cec67a533a33f2146dbdfcc/hindsight-docs/blog/2026-07-13-inside-retain-agent-memory.md)
- [Hindsight reversible curation and Memory Defense](https://github.com/vectorize-io/hindsight/blob/59d3f078cd8b32fe6cec67a533a33f2146dbdfcc/hindsight-docs/blog/2026-06-12-version-0-8-2.md)
- [Mem0 OSS v2 to v3 migration](https://github.com/mem0ai/mem0/blob/12c47f524935692e27ad48d829f35fa1e4417181/docs/migration/oss-v2-to-v3.mdx)
- [Mem0 Platform temporal reasoning](https://github.com/mem0ai/mem0/blob/12c47f524935692e27ad48d829f35fa1e4417181/docs/platform/features/temporal-reasoning.mdx)
- [Memora storage and retrieval implementation](https://github.com/agentic-box/memora/blob/bc64ff745a9b2c0e6245e0137654f041fba0c155/memora/storage.py)
- [OpenViking issue #3273](https://github.com/volcengine/OpenViking/issues/3273)
- [MemOS issue #1333](https://github.com/MemTensor/MemOS/issues/1333)
- [MatrixOrigin Memoria issue #88](https://github.com/matrixorigin/Memoria/issues/88)
- [MemMachine issue #1246](https://github.com/MemMachine/MemMachine/issues/1246)
- [Honcho issue #403](https://github.com/plastic-labs/honcho/issues/403)
- [Honcho issue #494](https://github.com/plastic-labs/honcho/issues/494)
- [EverOS issue #133](https://github.com/EverMind-AI/EverOS/issues/133)
