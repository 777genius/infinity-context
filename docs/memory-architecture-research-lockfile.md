# Memory Architecture Research Lockfile

Status: locked product rules for Memo Stack memory architecture.

Date: 2026-06-18.

This file is not a brainstorming note. It is the product and architecture
lockfile for memory behavior. Any change that weakens these rules needs a new
ADR, migration notes and eval coverage.

## External Inputs Reviewed

Checked again on 2026-06-18. These sources are used as product signals, not as
implementation authority. Memo Stack rules below are the authority for this
repository.

- [Mem0 memory types](https://docs.mem0.ai/core-concepts/memory-types) and
  [Mem0 add memory](https://docs.mem0.ai/core-concepts/memory-operations/add)
  separate memory layers and treat memory addition as an explicit extraction
  and storage operation over conversation evidence.
- [Zep concepts](https://help.getzep.com/concepts),
  [Zep Graph Overview](https://help.getzep.com/graph-overview) and
  [Graphiti](https://github.com/getzep/graphiti) use a temporal context graph
  where entities, facts and relationships preserve history while invalidating
  outdated facts.
- [Qdrant payload and filtering docs](https://qdrant.tech/documentation/manage-data/payload/)
  treat payloads, filters and payload indexes as retrieval infrastructure.
  Memo Stack uses them only as derived recall aids.
- [OWASP LLM Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)
  identifies instruction/data mixing as the core prompt injection hazard. Memo
  Stack applies this by keeping retrieved memory and extracted files as
  evidence, not hidden instructions.
- [OpenAI agent safety guidance](https://developers.openai.com/api/docs/guides/agent-builder-safety)
  and [OpenAI deep research safety guidance](https://developers.openai.com/api/docs/guides/deep-research)
  treat retrieved text, files, tool output and connector data as untrusted input
  that can contain prompt injection or exfiltration attempts.
- [OpenAI Model Spec](https://model-spec.openai.com/) recommends isolating
  untrusted data from instructions. Memo Stack applies this by rendering memory
  as evidence only.
- [LangMem conceptual guidance](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/)
  treats semantic, episodic and procedural memory as distinct write/retrieval
  patterns.
- [Letta archival memory](https://docs.letta.com/guides/core-concepts/memory/archival-memory/)
  separates long-term searchable memory from always-visible context memory.

### Source-To-Rule Ledger

This is the research lock, not a general bibliography. External systems can
inspire product rules, but cannot override them.

| Source signal | Locked Memo Stack rule |
| --- | --- |
| Mem0 separates memory layers and has an explicit add-memory operation | Memo Stack keeps semantic, episodic, procedural and archival behavior separate at write admission and retrieval time |
| Graphiti/Zep models changing relationships over time with provenance | Postgres stores canonical temporal fields and evidence refs; Graphiti can only project or suggest temporal graph candidates |
| Qdrant relies on payload/filter/index metadata for efficient scoped recall | Qdrant payloads must contain scope/provenance needed for recall, but every hit is rehydrated through Postgres before visibility |
| OWASP frames prompt injection as instruction/data confusion | Retrieved memory, file text, OCR, transcripts and tool output are always rendered as untrusted evidence, never as hidden policy |
| LangMem-style memory patterns split semantic, episodic and procedural behavior | Procedural memory cannot be inferred from ordinary facts or files without explicit review and a separate lifecycle |
| Letta-style archival memory separates long-term search from always-visible context | Archival evidence is searchable and reviewable, but hidden from default prompt context unless selected by current retrieval policy |

### Locked Rule Index

This index exists so implementation PRs can point to the exact rule they are
preserving. If a feature cannot name one of these rules, it is probably adding a
parallel memory model and needs an ADR before implementation.

| Rule id | Locked rule | Primary proof surface |
| --- | --- | --- |
| `memory-type-boundaries` | Semantic, episodic, procedural and archival memory are separate write/retrieval patterns | admission policy, context evals, prompt contract evals |
| `anchors-not-tags` | Canonical anchors represent identity; tags are editable facets for navigation | anchor lifecycle tests, linking evals |
| `temporal-current-by-default` | Normal context is current-state retrieval; stale/disputed/superseded evidence is review/debug only | temporal relation tests, quality-golden cases |
| `review-over-weak-automation` | Weak or ambiguous writes become pending review or deny, not silent mutation | context-link policy tests, semantic-linking-golden |
| `evidence-not-instruction` | Retrieved memory and extracted content are untrusted evidence, never hidden instructions | prompt contract evals, injection golden cases |
| `postgres-canonical` | Postgres owns lifecycle, visibility, audit and compatibility defaults | API/repository tests, migration fixtures |
| `derived-indexes-only` | Qdrant and Graphiti are replayable derived indexes and every hit is rehydrated through Postgres | provider consistency tests, context diagnostics |
| `bounded-provenance` | Context items expose bounded scoring/provenance diagnostics without secrets | SDK/API contract tests, redaction tests |
| `legacy-compatible` | Old payloads and rows map to safe defaults at boundaries, with diagnostics | SDK compatibility tests, transfer preview tests |
| `multimodal-evidence-first` | Documents, images, audio and video produce evidence artifacts before semantic promotion | multimodal extraction tests, review-gated linking tests |

## Locked Product Model

Memo Stack stores memory as canonical evidence plus derived retrieval indexes.
The user experience can look like quick capture, chat, project inbox or review
queue, but the storage model stays the same.

### Memory Types

Semantic memory:

- Stable facts, preferences, relationships, decisions and domain knowledge.
- Stored canonically as facts, anchors and explicit relations.
- Prompt-visible only when active, current, scoped and policy-allowed.

Episodic memory:

- Events, conversations, calls, captures, documents, screenshots, audio/video
  segments and user actions with time and source context.
- Stored as captures, episodes, assets, documents, chunks and extraction
  artifacts.
- Used as evidence for semantic suggestions, not silently converted into truth.

Procedural memory:

- Reusable workflows, policies, review decisions, user-approved behaviors and
  tool usage preferences.
- Stored separately from ordinary facts when it can affect future behavior.
- Requires explicit review before becoming active context.

Archival memory:

- Old, superseded, low-confidence or rarely used evidence kept for audit,
  search, recovery and debug.
- Hidden from default prompt context.
- Available in review/debug modes with stale/superseded/deleted reason codes.

Locked type boundaries:

| Input | Initial canonical type | Promotion target | Promotion rule |
| --- | --- | --- | --- |
| User text capture | episodic evidence | semantic fact, anchor or relation | only after source refs, scope and confidence are known |
| Screenshot or image | episodic evidence | anchor/link/fact suggestion | OCR/vision output is evidence and stays pending when ambiguous |
| Document chunk | archival and episodic evidence | semantic fact or relation | extraction creates suggestions unless the claim is user-confirmed |
| Audio/video transcript segment | episodic evidence | event, person/project anchor or fact suggestion | timestamped source refs are required |
| Assistant output | low-trust episodic evidence | semantic/procedural memory | requires explicit user review |
| User-approved workflow preference | procedural memory | active procedural context | requires review, audit and a separate lifecycle |

No write path may silently promote episodic or archival evidence into active
semantic or procedural memory. Promotion is a domain decision with confidence,
source trust, review state and audit evidence.

### Write Admission Matrix

Write admission runs before ranking, linking or prompt assembly. It decides what
the system is allowed to store as canonical memory and what must remain source
evidence.

| Candidate | Source trust | Default admission | Auto-active allowed? | Required evidence |
| --- | --- | --- | --- | --- |
| Direct user fact | `user_direct` | semantic pending or active according to validation | yes, when no conflict and source refs exist | user source ref, scope, kind, confidence |
| User uploaded file text | `user_uploaded` or `provider_derived` | episodic/archival evidence plus suggestions | no | asset/document/chunk refs, parser status, extraction confidence |
| OCR or vision claim | `provider_derived` | pending suggestion | no | asset id, bbox or page when known, model/parser metadata |
| ASR transcript claim | `provider_derived` | pending suggestion | no | asset id, segment time range, transcript artifact |
| Assistant summary | `assistant_generated` | low-trust evidence or pending suggestion | no | source refs to original evidence plus explicit user review |
| Connector import | `connector_external` | evidence first, suggestion when useful | no by default | connector provenance, scope proof, source ids |
| Procedural behavior preference | `user_direct` only | procedural pending review | no silent write | explicit user approval, audit event, policy version |
| Temporal replacement | any trusted source | pending relation suggestion | only under dedicated relation policy | old target id, new target id, valid/observed time evidence |

Admission outputs are:

```text
source_only
pending_semantic_suggestion
pending_anchor_suggestion
pending_relation_suggestion
pending_procedural_suggestion
active_semantic_memory
deny
```

`active_semantic_memory` is allowed only for direct user facts or explicit user
edits that pass scope, source-ref, conflict and sensitivity checks. All other
promotion paths start as reviewable suggestions.

## Source Trust Tiers

Trust is attached to evidence and suggestions before ranking or review. It is
not a replacement for authorization.

| Tier | Examples | Default behavior |
| --- | --- | --- |
| `user_direct` | user typed note, explicit manual save, user-approved edit | eligible for active memory after normal validation |
| `user_uploaded` | user file, screenshot, image, audio, video | evidence first; extracted claims need review unless deterministic |
| `connector_external` | Slack, GitHub, calendar, email, browser import | evidence first; scope and connector policy required |
| `assistant_generated` | assistant summary, inferred note, model-created title | low trust; cannot create active semantic/procedural memory without review |
| `provider_derived` | OCR, vision, ASR, document parser, classifier output | derived evidence; never authoritative alone |

Promotion gates:

- `assistant_generated` and `provider_derived` cannot be the only evidence for
  auto-approved semantic memory.
- Procedural memory cannot be created from screenshots, documents, transcripts
  or assistant summaries without explicit user approval.
- Restricted or wrong-scope evidence cannot be used for cross-scope linking
  unless the request explicitly asks for review/debug behavior and policy allows
  it.
- When evidence trust conflicts, the lower-trust source determines the default
  review requirement.

## Multimodal Evidence Contract

Uploaded files remain canonical assets. Parser, OCR, vision, ASR and video
outputs are provider-derived evidence stored as documents, chunks and extraction
artifacts. They are not canonical truth until review or another promotion policy
accepts them.

Every structured extraction with page, region, timestamp or media artifact
evidence must expose a normalized `media_manifest` artifact unless the provider
adapter already returned a `media_manifest` for the same extraction result.
Plain text-only extractions may skip the manifest.

Locked manifest schema:

```text
schema_version: memo_stack.multimodal_manifest.v1
asset: id, filename, content_type, normalized_content_type, byte_size, sha256, classification
extraction: job_id, parser_profile, parser_name, parser_version, model_version, language, status
modalities: bounded ordered list of text, document, image, audio, video
evidence_items[]: id, source refs, kind, modality, text_preview, page_number, bbox, time_range, confidence, safe metadata
artifacts[]: artifact_type, filename, content_type, byte_size, sha256, safe metadata
```

Provider rules:

- Docling, local parsers, OpenAI, Gemini, OCR, ASR and ffmpeg-style adapters
  must map provider output into the common `ExtractionResult` element/artifact
  model before storage.
- Core never imports provider SDKs. Provider-specific payloads stay in adapters,
  bounded diagnostics or raw blob storage only when explicitly intended.
- Image evidence should use `bbox` when a region is known.
- Document evidence should use `page_number` when a page is known.
- Audio transcript evidence should use `time_range` in milliseconds.
- Video evidence should split audio-track transcript segments from visual
  keyframes/timelines, both using time ranges.
- Manifest metadata is scalar-only and bounded. It must not include raw provider
  payloads, base64 file data, unrestricted paths, tokens, secrets, prompts,
  stack traces or nested private metadata.

The manifest is retrieval and review evidence. It does not replace canonical
chunk source refs, context-link review, anchor identity checks or temporal
validity.

## Canonical Anchors vs Tags

Canonical anchors are durable entities:

- People, organizations, projects, events, documents and important concepts.
- Have kind, normalized key, aliases, confidence, evidence refs, lifecycle
  status and temporal validity.
- Support merge, split, audit trail and alias conflict checks.
- Can be linked to facts, captures, assets, chunks, suggestions and threads.

Anchor identity conflict rules:

- Conflicts are scoped by space, MemoryScope and anchor kind.
- Same-name anchors across different kinds are allowed when evidence supports
  disambiguation, for example `Alex` as a person and `Alex` as a project.
- Label and alias conflicts must be checked on create, update, merge and split.
- Organization and project anchors must also reject compact brand variants such
  as `OpenAI` vs `Open AI` or `GitHub` vs `Git Hub`.
- Split into an existing anchor must preserve evidence refs, temporal validity
  and audit metadata instead of creating a duplicate.

Tags are lightweight facets:

- User-facing labels for filtering, grouping and quick navigation.
- May be created automatically, but never replace anchors.
- Can be wrong without corrupting the semantic graph.
- Should be editable/removable without changing fact identity.

Locked rule:

```text
Tags help users browse. Anchors help the system reason.
```

If the system needs identity, disambiguation, time validity or relations, it
must use anchors or explicit relations, not tags alone.

### Canonical Anchor Ontology

Anchor kinds are governed. New kinds require a lockfile or ADR update, API/SDK
contract tests and migration notes when persisted.

| Kind | Identity key | Required disambiguation evidence | Examples |
| --- | --- | --- | --- |
| `person` | normalized human name plus scope evidence | source mention, role, contact, thread, meeting or relation | Alex as a teammate |
| `organization` | normalized organization name plus compact variants | source mention or domain-like evidence when available | OpenAI, GitHub, Acme |
| `project` | normalized project/product/workstream name | scope, thread, owner, repo, document or user confirmation | Atlas, Alex as project |
| `event` | normalized title plus time window | observed time or valid time, participants or source event | weekly call with Alex |
| `document` | document id or stable external ref | asset/document source ref | uploaded roadmap PDF |
| `concept` | normalized concept label | repeated evidence or explicit user tag-to-anchor conversion | retrieval policy |

Anchor lifecycle rules:

- `active` anchors can participate in current context and suggestions.
- `merged` anchors remain addressable for audit and import/export remapping.
- `split` creates or reuses a target anchor and records the source anchor id.
- `deleted` anchors are hidden from normal context and cannot receive new links.
- Merge/split must preserve evidence refs and temporal fields.
- Alias conflict detection must run on create, update, merge and split.
- Same label across different kinds is allowed only when the kind is explicit in
  the candidate or review surface.

## Temporal Validity

Every prompt-impacting semantic item must be compatible with bitemporal-lite:

- `observed_at` records when Memo Stack learned or observed the claim.
- `valid_from` records when the claim becomes true in the user's world.
- `valid_to` records when the claim stops being true in the user's world.
- Missing `valid_from` means valid from observation time unless a stronger
  source says otherwise.
- Missing `valid_to` means still current until superseded, disputed, deleted or
  expired.

Default context retrieval:

- Shows active current facts and current relations.
- Hides superseded targets when a current active supersedes relation exists.
- Hides disputed/contradicted facts by default.
- Hides deleted, restricted and out-of-scope items.

Review/debug retrieval:

- May show stale, superseded, disputed and expired items.
- Must include reason codes and relation ids.
- Must not silently mix stale facts into normal active context.

Temporal relation rules:

| Relation | Normal context behavior | Review/debug behavior | Required evidence |
| --- | --- | --- | --- |
| `related_to` | may show both sides when active/current | show relation reason | at least one safe matching signal |
| `supports` | may boost target confidence | show supporting source refs | source evidence or user approval |
| `mentions` | does not imply truth | show mention source refs | source evidence |
| `supersedes` | hides target when source is current | show stale target with reason | explicit temporal/update signal |
| `contradicts` | hides or downranks target by default | show disputed target with reason | explicit correction/conflict signal |
| `duplicates` | dedupe to canonical target | show duplicate mapping | high similarity plus same kind/scope |

High-impact relations are `supersedes`, `contradicts`, `duplicates`,
`merge_candidate` and any relation that changes current prompt visibility.
They require explicit relation-specific evidence and review unless a dedicated
policy allows safe auto-approval for the exact relation.

## Review Gates

Memo Stack must prefer safe review over silent automation.

Auto-link is allowed only when all are true:

- High confidence.
- Strong relation-specific evidence.
- No active duplicate or conflict.
- No ambiguity between same-name anchors.
- No restricted source.
- No prompt-injection or instruction-like source promotion.
- Payload stays within max suggestions and diagnostic limits.

Pending review is required when any are true:

- Medium confidence.
- Multiple plausible targets.
- New anchor creation from weak evidence.
- Temporal phrase is ambiguous.
- Source is AI-generated or low trust.
- Relation can change future behavior.
- Suggested procedural memory.

Deny without suggestion when any are true:

- Score below threshold.
- Only weak lexical overlap.
- Candidate is from wrong scope/thread and not explicitly requested.
- Target is deleted/restricted.
- Candidate reason would expose secrets or raw private payload.
- No candidate is better than a hallucinated candidate.

### Semantic Link Policy Thresholds

These thresholds lock the current `context-link-policy-v1` behavior. Changing
them requires a lockfile or ADR update plus semantic-linking eval evidence.

| Rule | Locked value | Product meaning |
| --- | --- | --- |
| minimum review score | `40.0` | below this, deny without persisted suggestion |
| minimum weak-signal review score | `55.0` | score `40.0..54.99` needs at least one strong reason code |
| high confidence score | `75.0` | candidate can be labeled high confidence, but still requires review |
| auto-approve eligible score | `92.0` | candidate can receive `auto_approve_candidate` policy label |
| independent signals for auto-approve eligibility | `2` | at least two strong reason codes, including `text_match` |
| persisted suggestions per source request | `10` | bounded review queue and public payload |
| candidates considered before policy | `120` | protects ranking and diagnostics from unbounded candidate pools |
| denied candidates sampled in diagnostics | `8` | enough for debug without leaking large private candidate sets |

Strong reason codes are:

```text
text_match
temporal_intent_match
explicit_project_reference
known_project_tool_reference
event_phrase
person_name
organization_reference
rule_signal
```

High-impact relations are `supersedes` and `contradicts`. They require explicit
temporal/update/conflict reason codes and remain review-gated. A high score
alone is never enough for these relations.

### Review Decision Contract

Review decisions must be stable across API, SDK, frontend, CLI and future MCP
surfaces.

| Decision | Meaning | Persistence |
| --- | --- | --- |
| `deny` | do not return or persist a suggestion | bounded diagnostics only |
| `pending_review` | safe enough to ask user, not safe enough to apply | persisted suggestion |
| `auto_approve_candidate` | high-confidence candidate eligible for fast review | persisted suggestion with review gate |
| `approved` | user or trusted service accepted the change | canonical link/fact/relation plus audit |
| `rejected` | user or trusted service rejected the suggestion | rejection record blocks recreation |
| `expired` | suggestion is no longer actionable | audit record with expiration reason |

Locked rule:

```text
auto_approve_candidate is not silent mutation. It is a policy label that can
speed up review, but the review gate remains explicit unless a later ADR creates
a narrowly scoped no-review policy with eval coverage.
```

Required review metadata:

- policy version;
- source type and source id;
- target type and target id when known;
- relation type when applicable;
- confidence and score band;
- reason codes;
- safe human explanation;
- original suggested target when a user overrides it;
- actor id or service token id when available;
- reviewed_at, previous status and new status.

## No Hidden Instruction Memory

Memory is evidence, not instruction.

Locked rules:

- Retrieved memory must be rendered under an evidence header.
- Memory text must never be inserted as developer/system instructions.
- Prompt injection inside documents, screenshots, audio/video transcripts or
  tool output remains quoted evidence.
- Procedural memory that can change behavior requires explicit review and a
  separate lifecycle.
- Source text can be useful while still untrusted.

## Canonical Truth And Derived Indexes

Postgres is canonical:

- Owns lifecycle, status, source refs, temporal fields, review state and audit.
- Delete/forget must hide data from context immediately through canonical
  visibility, even if derived indexes lag.
- Import/export and migrations must preserve canonical ids or remap them with
  explicit conflict reports.

Qdrant is derived:

- Stores chunk vectors for recall.
- Can be stale or unavailable without corrupting canonical truth.
- Every vector result must be rehydrated through canonical visibility.

Graphiti is derived:

- Stores temporal graph projections and graph retrieval hints.
- Cannot be the only proof that a fact, anchor or relation exists.
- Every graph result must be rehydrated through canonical visibility.

Provider adapters are replaceable:

- Provider-specific metadata stays in adapters or bounded diagnostics.
- Core use cases depend on ports, not SDKs.
- Unsupported capabilities are explicit degraded/skipped status, not fake
  success.

Derived index update rules:

- Canonical write succeeds or fails independently from Qdrant/Graphiti updates.
- Derived index writes are idempotent and replayable from Postgres.
- Delete/forget writes canonical tombstones before derived cleanup.
- Retrieval must hydrate derived hits through canonical repositories before
  exposing them to API/SDK/frontend.
- Stale derived hits increment diagnostics counters instead of disappearing
  without explanation.
- Rebuild jobs must be able to reconstruct derived indexes from canonical
  Postgres state and stored blobs/artifacts.

## Scoring And Provenance Schema

Every context item must expose bounded diagnostics with no secrets.

Required item diagnostics:

```text
retrieval_source
retrieval_sources
ranking_reason
score_signals
provenance
memory_scope_id
```

Required bundle diagnostics:

```text
context_assembly_version
consistency_mode
retrieval_sources_used
hybrid_items_used
temporal_replacements_applied
temporal_relations_skipped_by_validity
items_considered
items_used
dropped_by_budget
dropped_by_source_cap
dropped_by_char_cap
diagnostics_truncated
```

Score signals:

- Numeric or enum-like only.
- No raw query terms.
- No auth tokens, URLs with credentials, full source text or raw provider
  payloads.
- Must include enough data to explain ranking without leaking content.

Provenance:

- Source type and source id.
- Chunk/document ids when available.
- Retrieval sources.
- Source ref count.
- Temporal relation ids when temporal replacement happened.
- Sequence or character offsets for chunks when available.

### Context Diagnostics Schema V1

Each prompt-visible `ContextItem` must expose this normalized diagnostics
shape. Missing adapter fields are defaulted in application/API/SDK mapping, not
in UI code.

```text
diagnostics:
  retrieval_source: string | null
  retrieval_sources: string[] max 8 ordered unique
  retrieval_sources_total?: int
  retrieval_sources_returned?: int
  retrieval_sources_truncated?: bool
  ranking_reason: string max 240
  score_signals: map<string, scalar> max 24 keys
  provenance:
    retrieval_sources: string[] max 8
    source_type?: string
    source_id?: string
    document_id?: string
    chunk_id?: string
    source_ref_count?: int
    page_number?: int
    bbox?: number[4]
    time_start_ms?: int
    time_end_ms?: int
    temporal_relation_ids?: string[] max 8
    visibility?: current | review_only | historical
```

Bundle diagnostics must expose:

```text
context_assembly_version
consistency_mode
retrieval_sources_used: string[] max 8
retrieval_sources_total?: int
retrieval_sources_returned?: int
retrieval_sources_truncated?: bool
hybrid_items_used: int
temporal_replacements_applied: int
source_refs_total?: int
source_refs_returned?: int
source_refs_truncated?: bool
multimodal_source_ref_count: int
source_refs_with_page_count: int
source_refs_with_bbox_count: int
source_refs_with_time_range_count: int
stale_*_drop_count: int
*_candidate_count: int
*_hydrated_count: int
```

Forbidden diagnostics:

- raw query text;
- full document/chunk/source text;
- OCR/ASR transcript bodies;
- raw provider payloads;
- stack traces;
- absolute local file paths;
- tokens, keys, passwords, bearer headers, signed URLs or cookies;
- prompt/developer/system text.

The SDK must parse absent optional fields to safe defaults:

| Field | Missing default |
| --- | --- |
| `retrieval_sources` | empty tuple |
| `ranking_reason` | derived from retrieval sources or safe fallback |
| `score_signals` | empty mapping |
| `provenance` | empty mapping |
| bundle counters | `0` |
| nullable temporal/media coordinates | `None` |

Current context-link guardrails:

- Direct suggestion requests clamp effective limit to `1..30`.
- Persisted link suggestions return at most `10` review candidates per source.
- Query term diagnostics keep at most `64` redacted terms.
- Each query term is capped at `80` characters.
- Denied candidate diagnostics keep at most `8` denied candidates.
- Policy reason codes keep at most `12` normalized codes.
- Denied diagnostic target text is capped at `160` characters.
- Public metadata payloads keep bounded dict/list sizes and redact sensitive
  text before API exposure.

Deterministic ordering:

- Primary sort is score.
- Duplicate candidates use the highest score first; tied scores use retrieval
  source priority and then stable source/provenance fields.
- Tie-breakers must use stable source/provenance fields before generated ids.
- Provider return order must not decide which duplicate candidate becomes the
  primary context item.
- Random ids cannot decide which evidence fits into a capped context.

## Multimodal Evidence Rules

Multimodal inputs are evidence first.

| Media | Required canonical evidence | Optional derived evidence | Prompt visibility |
| --- | --- | --- | --- |
| image/screenshot | asset id, mime, dimensions, source refs | OCR blocks, vision summary, UI labels, bbox | quoted evidence or pending suggestions |
| document | asset/document id, pages/chunks, parser status | structured elements, tables, OCR layer | chunk evidence with source refs |
| audio | asset id, duration, stream metadata | transcript segments, speaker labels when available | timestamped transcript evidence |
| video | asset id, duration, streams, resolution | audio transcript, scenes, keyframes, OCR/vision per frame | timestamped evidence with frame refs |

Extractor output requirements:

- Every extracted element has an evidence ref.
- Time-based evidence uses `time_start_ms` and `time_end_ms`.
- Visual evidence uses `bbox` when known.
- Parser/vision/ASR errors are safe public errors and bounded internal
  diagnostics.
- Missing provider credentials produce degraded evidence, not fake extraction.
- Large media jobs must expose queued/processing/succeeded/failed/canceled
  state and retry/cancel behavior.

## API And SDK Contract

Public APIs and SDKs must support:

- List review suggestions with filters.
- Approve/reject with reason.
- Approve with target override.
- Bounded batch review.
- List anchors and evidence.
- Typed context diagnostics.
- No raw provider-specific payloads in public responses.

Compatibility rule:

```text
Adding fields is allowed. Removing or renaming public response fields requires
compatibility tests and migration notes.
```

Compatibility matrix:

| Surface | Backward compatibility requirement |
| --- | --- |
| anchors | old rows without confidence, evidence refs, observed_at or valid windows map to safe defaults |
| relations | old rows without valid_from or valid_to remain readable and current only when policy allows |
| import/export | missing new fields are defaulted at mapper boundaries and reported in preview diagnostics |
| SDK typed DTOs | missing optional diagnostics parse to bounded defaults, not exceptions |
| public API | arrays default to empty arrays, nullable temporal fields stay nullable |
| frontend/review | unknown future metadata is ignored safely and never used as authority |

Legacy default contract:

| Legacy gap | Safe default | Required diagnostic |
| --- | --- | --- |
| anchor `confidence` missing | `medium` | `migration_defaults_applied.anchor_confidence` |
| anchor `evidence_refs` missing | empty list | `migration_defaults_applied.anchor_evidence_refs` |
| anchor `observed_at` missing | `created_at`, then `updated_at`, then import time | `migration_defaults_applied.anchor_observed_at` |
| anchor `valid_from` missing | `None`, interpreted as observed/current by policy | `migration_defaults_applied.anchor_valid_from` |
| anchor `valid_to` missing | `None`, interpreted as current unless status/relation says otherwise | `migration_defaults_applied.anchor_valid_to` |
| relation `observed_at` missing | relation `created_at`, then import time | `migration_defaults_applied.relation_observed_at` |
| relation `valid_from` missing | `None` | `migration_defaults_applied.relation_valid_from` |
| relation `valid_to` missing | `None` | `migration_defaults_applied.relation_valid_to` |
| transfer record missing new metadata | default at import mapper boundary | transfer preview warning |
| SDK payload missing diagnostics | typed empty/default diagnostics | SDK parser regression |

Legacy defaults are compatibility behavior, not truth. They must not increase
confidence, bypass review gates or mark stale evidence as independently
verified.

Breaking changes require:

- migration notes;
- public contract tests;
- SDK compatibility tests;
- import/export legacy fixtures;
- explicit version bump or ADR.

## Observability, Audit And Performance Rules

Production debugging must be possible without leaking private data.

Required bounded counters:

- review actions by status and relation type;
- linking decisions by outcome and deny reason;
- rejected candidate reason counts;
- context assembly items considered/used/dropped;
- stale derived hits dropped during hydration;
- migration defaults applied;
- parser/extractor attempts, retries, timeout and cancel counts;
- derived index enqueue/retry/dead-letter counts.

Audit requirements:

- Approve, reject, edit, merge, split, expire, transfer import and destructive
  lifecycle changes leave canonical audit evidence.
- Audit payloads store ids, types, status changes, reason codes and timestamps.
- Audit payloads must not store raw provider payloads, full prompt text, full
  document bodies, unrestricted file paths, tokens or stack traces.

Performance guardrails:

- Candidate collection is capped before rerank.
- Evidence refs per context item are capped.
- Diagnostics object size and depth are capped.
- Batch review size is capped.
- Context assembly must avoid N+1 repository calls for temporal relations,
  anchors and source refs.
- Tests must prove bounded payload size for public API/SDK diagnostics.

## Eval Contract

Prompt-impacting changes require deterministic evals for:

- Superseded old fact hidden, new fact shown.
- Disputed/contradicted hidden by default.
- Similar project is not matched.
- Same-name person vs project disambiguation.
- Screenshot or document evidence linked to the right chunk.
- No candidate means no candidate.
- Hybrid retrieval beats single source when both are valid.
- Tail recall in long documents.
- Prompt injection remains evidence only.
- Organization compact-name conflicts, for example `OpenAI` vs `Open AI`.
- Legacy payloads without new fields still parse and render safe defaults.
- Rejected suggestion is not recreated for the same source/target/relation.
- Batch review applies only bounded visible pending items.

Minimum gate before major memory behavior changes:

```bash
.venv/bin/python -m memo_stack_server.eval run --suite quality-golden
.venv/bin/python -m memo_stack_server.eval run --suite semantic-linking-golden
```

## Feature Slice Readiness Gates

Every memory feature slice must pass these gates before implementation is
considered complete. This is intentionally stricter than "route exists" or
"frontend works".

| Slice type | Required before commit | Required tests or evals |
| --- | --- | --- |
| memory type/admission | source trust, admission output and promotion rule are explicit | unit tests for source-only, pending, active and deny paths |
| anchor identity | kind, normalized key, aliases and conflict behavior are explicit | duplicate, alias conflict, same-name cross-kind and merge/split tests |
| temporal visibility | observed/valid windows and stale policy are explicit | normal context hides stale, review/debug explains stale |
| context assembly | ranking reason, score signals, provenance and counters are bounded | API/SDK contract tests plus quality-golden coverage |
| semantic linking | thresholds, deny rules, duplicate suppression and review state are explicit | policy tests plus semantic-linking-golden coverage |
| migration compatibility | old missing fields and public payload defaults are enumerated | legacy row, import/export, API and SDK regression tests |
| multimodal ingestion | artifact model, coordinates and provider degradation are explicit | document/image/audio/video extraction tests with source refs |
| review UX/API/SDK | approve/reject/edit/batch semantics and audit event are explicit | API/SDK tests for filters, target override, bounded batch and audit |
| observability | counters are bounded and redacted | diagnostics size/redaction tests |
| performance guardrail | candidate, evidence, diagnostics and batch caps are explicit | bounded payload and N+1 regression tests where applicable |

Definition of done:

- The feature preserves at least one locked rule from the index above.
- Public payload changes remain additive or include migration notes.
- Any prompt-impacting behavior has deterministic eval coverage.
- Any provider-derived content is evidence-first and review-gated when
  ambiguous.
- `memo_stack_core` still depends only on domain/application ports, not
  provider SDKs or server frameworks.

## Implementation Traceability Matrix

This matrix is the acceptance contract for future memory changes. A feature is
not considered complete just because the API shape exists. It must preserve the
rule, update the implementation surface and keep the listed regression evidence
green.

| Locked rule | Implementation surface | Required regression evidence |
| --- | --- | --- |
| Semantic, episodic, procedural and archival memory stay separate | `memo_stack_core.application`, capture/document/asset ingestion, procedural review policy | extractor, capture consolidation and context tests prove untrusted evidence is not promoted silently |
| Anchors are canonical identity, tags are facets | anchor use cases, context-link suggestions, anchor lifecycle API | anchor lifecycle tests cover duplicate prevention, alias conflicts, merge/split audit and same-name cross-kind anchors |
| Temporal validity controls prompt visibility | fact relation use cases, context assembly, memory digest | context provider tests cover supersedes, future/expired relations, disputed facts and review-only stale evidence |
| Review beats weak automation | context link policy, suggestions API, SDK review flows, frontend review queue | policy tests prove low/medium confidence stays pending or denied, batch review is bounded and rejection reasons are preserved |
| Memory is evidence, not hidden instruction | context packer, prompt contract eval, extraction adapters | prompt injection evals and packer tests prove retrieved memory is quoted evidence and instruction-like items are dropped |
| Postgres is canonical, Qdrant and Graphiti are derived | repositories, hydration, vector/graph adapters, rebuild jobs | provider consistency tests prove stale/deleted/wrong-scope derived hits are rehydrated or dropped through canonical visibility |
| Context diagnostics are bounded, typed and non-sensitive | context diagnostics, public API DTOs, SDK typed context helpers | SDK/API contract tests prove bounded retrieval sources, ranking reason, provenance, counters and redaction |
| Golden evals protect product memory quality | eval catalogs and eval runner | eval runner tests prove diagnostic requirements support exact and lower-bound checks without leaking secrets |
| Multimodal inputs stay evidence-first | extraction use cases, asset/document/transcript/keyframe artifacts, provider adapters | image/audio/video/document tests prove extracted output keeps source refs, time ranges or bbox and stays review-gated when ambiguous |
| API and SDK review flows are equivalent to UI | review use cases, API routes, SDK helpers, frontend review queue | API/SDK tests cover filters, approve/reject reason, target override, bounded batch review and typed diagnostics |
| Observability is bounded and safe | diagnostics builders, audit metadata, migration reports, worker events | tests prove counters exist, sensitive values are redacted and payload budgets are enforced |
| Migration compatibility is preserved | mappers, import/export, API DTOs, SDK DTOs | legacy row/payload fixtures prove safe defaults for missing confidence, evidence refs, temporal windows and diagnostics |

When adding a new memory capability, add or update the row that owns the rule.
If no row owns it, create one before implementation. If a row exists but the
regression evidence is missing, add the test or eval in the same feature slice.

## Change Policy

This lockfile can change only with:

- New ADR or explicit lockfile update commit.
- Regression tests or eval cases for changed behavior.
- Migration/backward compatibility notes when public or stored contracts change.
- Secret-scan clean result.
