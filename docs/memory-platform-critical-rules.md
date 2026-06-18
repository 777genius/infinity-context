# Memory Platform Critical Rules

This document is the implementation guardrail for advanced memory features:
Context Assembly v2, semantic anchors, temporal invalidation, evals, and review UX.

## Research baseline

Current competitive memory systems converge on the same core ideas:

- Multi-signal retrieval: semantic vectors, keyword/BM25-like matching, graph relations,
  recency, trust, and scope/thread locality.
- Entity-first memory: people, projects, organizations, places, and events are canonical
  anchors, not only free-form tags.
- Temporal memory: facts and relations change over time; retrieval must preserve
  provenance and avoid stale/deleted leakage.
- Evidence-first output: retrieved memory is evidence with source refs, never hidden
  instruction.
- Review gates: uncertain writes, merges, supersedence, and relation suggestions need
  clear approve/reject/edit flows.
- Continuous evals: retrieval quality, linking quality, stale-memory safety, and
  review UX regressions must be measured with golden cases.

Useful references checked during planning:

- Mem0 migration docs emphasize add-only extraction, single-pass extraction, hybrid
  search, graph/entity linking, and multi-signal retrieval.
  Source: https://docs.mem0.ai/migration/oss-v2-to-v3
- Graphiti/Zep emphasize temporal context graphs, custom entities, evolving facts,
  relationship invalidation, and hybrid retrieval over semantic, full-text and graph
  signals. Source: https://help.getzep.com/graphiti/getting-started/overview
- Letta separates always-visible core memory blocks from on-demand archival memory.
  Source: https://docs.letta.com/guides/core-concepts/memory/context-hierarchy
- LangMem documents semantic, episodic and procedural memory patterns, plus memory
  extraction/update flows over long-term stores.
  Source: https://langchain-ai.github.io/langmem/concepts/conceptual_guide/

## Non-negotiable architecture rules

1. `memo_stack_core` must not import FastAPI, SQLAlchemy, Qdrant, Graphiti, OpenAI,
   Docling, browser, Flutter, or app-specific code.
2. Postgres remains the canonical source of truth. Qdrant, Graphiti, and external
   providers are derived indexes/adapters.
3. All provider dependencies enter through ports. Provider failure must degrade or
   produce safe diagnostics instead of leaking exceptions into public API payloads.
4. Retrieval output must be evidence-only. Rendered memory must never contain hidden
   instructions or imply authority beyond source evidence.
5. Deleted, superseded, disputed, restricted, wrong-scope, or stale candidates must be
   filtered before ranking whenever they are not explicitly requested for review/debug.
6. Ranking must be explainable. Every selected context item should expose bounded,
   non-sensitive score signals and source provenance.
7. Canonical anchors must be mergeable/splittable and alias-aware. Tags can assist UI,
   but tags are not a substitute for people/events/projects/organizations.
8. Temporal behavior must be explicit. New facts or relations should support
   `observed_at`, `valid_from`, `valid_to`, `supersedes`, and `contradicts` semantics
   where the domain supports them.
9. Review UX must allow approve, reject, edit target, change relation, and inspect
   reasons/evidence. Batch operations must stay bounded and auditable.
10. Evals are product gates, not optional tests. Every risky memory behavior needs a
    golden case that can fail when relevance, safety, or provenance regresses.

## Product memory taxonomy

These names are product contracts. Code may use existing domain names, but behavior
must map to the taxonomy below.

| Type | Canonical storage | Retrieval behavior | Write policy |
| --- | --- | --- | --- |
| Semantic memory | `MemoryFact`, `MemoryAnchor`, context links | high precision, evidence-backed facts and entities | source refs required, conflict checks required |
| Episodic memory | captures, episodes, document chunks, artifacts | time-ordered evidence and transcript/document recall | keep as evidence unless consolidated into facts |
| Procedural memory | user/team operating rules and preferences | only explicit, high-trust rules may influence prompts | never infer from screenshots or untrusted docs |
| Archival memory | documents, chunks, assets, external records | searched on demand; not always pinned to prompts | provider/storage adapters remain derived or external |

Important distinction: tags help navigation and filtering; anchors represent canonical
things. People, events, projects and organizations must be anchors, not only tags.

## Canonical write rules

1. A memory write must identify scope, source evidence and source trust before it can
   become active canonical memory.
2. Screenshots, files, transcripts and documents are first stored as evidence. Facts,
   anchors and links are derived from that evidence.
3. Weak extraction or weak linking creates pending review items, never silent active
   memory.
4. Imported legacy rows with missing new fields must receive safe defaults at mapper
   boundaries, not inside business logic.
5. User-approved decisions remain auditable even if later evidence changes confidence.

## Context Assembly v2 contract

Every selected `ContextItem` should include bounded diagnostics:

```text
retrieval_source: one selected source string
retrieval_sources: ordered unique list, max 8
ranking_reason: short human-readable explanation, max 240 chars
score_signals: scalar-only non-sensitive score inputs
provenance: non-sensitive source counts, ids and retrieval channels
```

Bundle-level diagnostics should include:

```text
context_assembly_version
consistency_mode
vector_status / graph_status / rag_status
*_candidate_count
*_hydrated_count
stale_*_drop_count
hybrid_items_used
temporal_relations_considered
temporal_replacements_applied
pending_conflict_suggestions_considered
```

Sorting must be deterministic. If scores tie, use stable type/id/update ordering instead
of relying on database or adapter return order.

Diagnostics must never include raw provider payloads, secrets, stack traces, hidden
prompt text, full document bodies, or unrestricted metadata blobs.

## Bounded payload budgets

These limits are product contracts. Implementations may use smaller limits for a
specific route, but must not exceed these values without a new ADR and regression
tests.

| Surface | Hard budget |
| --- | --- |
| `ContextItem.retrieval_sources` | max 8 ordered unique source names |
| public `ContextItem.source_refs` | max 20 refs per API item, with truncation diagnostics |
| diagnostic mapping | max 24 keys per object, depth max 3 |
| diagnostic list value | max 8 items |
| diagnostic key | max 80 chars |
| diagnostic string value | max 240 chars |
| `ranking_reason` | max 240 chars |
| denied link-candidate diagnostics | max 8 sampled denied candidates |
| persisted context-link suggestions per source request | max 10 |
| context-link batch review | max 50 review items |
| review/audit metadata events | max 20 events per metadata list |
| safe batch error text | max 320 chars after redaction |

Payload budgets are safety controls, not presentation preferences. If a provider
or adapter returns more detail, adapter/application code must summarize or drop
it before it reaches public API, SDK, MCP or UI payloads.

## Review and audit event contract

Every approve/reject/edit action for memory suggestions, context-link
suggestions, anchor merges/splits and temporal relation changes must leave a
canonical audit trail. The audit trail can be represented as outbox rows,
domain events, reviewed suggestion rows, context-link metadata or a future
dedicated audit table, but it must preserve these non-sensitive fields:

```text
event_type
space_id
memory_scope_id
actor_user_id or service_token_id when available
source_type / source_id
target_type / target_id when available
action: approve | reject | edit | merge | split | expire
reason or safe_reason
previous_status
new_status
created_at / reviewed_at
policy_version when a policy decision was involved
```

Audit payloads must not store raw provider payloads, prompt text, full document
content, unrestricted file paths, API keys, tokens or stack traces. When a user
edits a suggested target/relation, preserve the original suggested target and
relation as safe ids/types so future debugging can explain why AI was overridden.

## Scoring and provenance policy

Score signals are explanations, not the source of truth. Postgres visibility checks and
authorization always run before ranking. Ranking may boost:

- same exact canonical item found by multiple retrieval sources;
- recent and high-trust evidence;
- approved user review;
- temporal replacement that supersedes a matched stale fact.

Ranking must penalize or exclude:

- stale/deleted/disputed/superseded candidates in normal context;
- provenance-less candidate facts;
- weak entity-only matches without supporting evidence;
- cross-scope/thread matches unless explicitly requested.

## Multimodal evidence policy

Structured document, image, audio and video extraction must preserve bounded
evidence coordinates instead of flattening everything into plain text.

Required normalized evidence:

- documents: page refs;
- images and screenshots: image regions or bbox when known;
- audio: transcript segments with millisecond ranges when known;
- video: keyframe or timeline refs plus audio-track transcript ranges when
  available.

`media_manifest` is the normalized extraction artifact for this evidence. It is
safe review/retrieval metadata, not canonical truth. It must not contain raw
provider payloads, base64 file content, unrestricted paths, prompts, tokens,
stack traces or nested private metadata.

## Semantic linking policy

Context-link suggestions must be explainable and bounded.

Required suggestion metadata:

- `reason`
- `reason_codes`
- `matched_terms`
- `target_preview`
- confidence and score
- source/target type and id

Auto-approve is allowed only when all are true:

- relation type policy allows auto-approval;
- confidence is high;
- at least two independent signals support the link;
- no existing active duplicate link exists;
- no reviewed rejected suggestion exists for the same source/target/relation;
- source and target belong to the requested scope.

Otherwise persist a pending review suggestion. If in doubt, review wins.

## Temporal rules

Normal context retrieval is current-state retrieval. It must hide deleted, disputed,
superseded and expired facts unless a debug/review/as-of query explicitly asks for them.

Temporal fields have these meanings:

- `observed_at`: when the system learned the fact or relation;
- `valid_from`: when the statement starts being true in the real world;
- `valid_to`: when the statement stops being true in the real world;
- `supersedes`: source fact replaces target fact for current context;
- `contradicts`: target fact must not be treated as reliable current context without
  review.

Derived indexes must preserve temporal metadata but cannot decide canonical visibility.

## Review UX gates

Review surfaces must let a user:

- approve, reject and edit target/relation;
- see source and target evidence;
- see why the suggestion exists;
- filter by status, type, relation and target/evidence text;
- run bounded batch actions only over visible pending suggestions;
- avoid optimistic writes; refresh after confirmed API responses.

Every review action should have a reason and be auditable.

## Migration and compatibility rules

New schema fields must be additive until a formal breaking migration is planned.
Compatibility tests should cover:

- old anchor rows without confidence, evidence refs or temporal fields;
- old relation rows without observed/valid windows;
- transfer import/export with missing fields;
- SDK clients receiving old and new payload shapes;
- public API returning empty lists instead of missing arrays when possible.

## Implementation order

1. Strengthen existing `BuildContextUseCase` instead of creating a parallel retrieval
   stack.
2. Normalize ranking signals and provenance in core DTOs.
3. Promote anchors as first-class targets in retrieval and relation suggestions.
4. Add temporal relation metadata and invalidation policies.
5. Expand golden evals around retrieval, anchor linking, stale memory, and review UX.
6. Expose review UX improvements through existing API contracts before adding new UI
   screens.
