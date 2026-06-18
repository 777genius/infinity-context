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
  [Mem0 long-term memory overview](https://mem0.ai/blog/long-term-memory-ai-agents)
  separate factual, episodic and semantic memory, with procedural memory used
  for behavior and reusable workflows.
- [Zep concepts](https://help.getzep.com/concepts),
  [Zep Graph Overview](https://help.getzep.com/graph-overview) and
  [Graphiti](https://github.com/getzep/graphiti) use a temporal context graph
  where entities, facts and relationships preserve history while invalidating
  outdated facts.
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
