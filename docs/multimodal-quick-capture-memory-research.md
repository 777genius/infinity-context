# Multimodal Quick Capture Memory Research

Status: research note for product/architecture decision.

Date: 2026-06-09.

## Question

Can Memo Stack support a fast user workflow where a user opens a frontend, drops a
screenshot/file plus a short note, and AI proposes where to save it, which
existing memory it relates to, or stores it separately for future linking?

Short answer: yes, but only if raw evidence and durable memory remain separate.

Recommended pattern:

```text
User screenshot/file/note
  -> local asset/blob storage
  -> canonical capture/source record
  -> OCR/vision/text extraction
  -> related memory search
  -> candidate resolver
  -> suggestions for user approval
  -> facts, relations and projections after approval or strict auto-apply
```

This aligns with current Memo Stack direction:

- `Capture is not Memory` in `docs/auto-memory-capture-platform-plan.md`.
- Postgres remains canonical truth.
- Qdrant and Graphiti stay derived indexes.
- Current core already has captures, suggestions, facts, fact relations,
  documents/chunks and source refs.
- Missing piece for this product flow is a first-class asset/blob/upload model.

## Research Inputs

External sources checked:

- Mem0 add memory docs: memory ingestion is extraction plus conflict resolution,
  not just raw append.
  - https://docs.mem0.ai/core-concepts/memory-operations/add
- LangMem semantic memory docs: a memory manager can receive messages plus
  existing memories and return inserts, updates or deletes.
  - https://langchain-ai.github.io/langmem/guides/extract_semantic_memories/
  - https://langchain-ai.github.io/langmem/reference/memory/
- Zep/Graphiti docs: temporal graph memory tracks provenance and invalidates
  superseded facts instead of silently overwriting history.
  - https://www.getzep.com/platform/graphiti/
  - https://help.getzep.com/facts
  - https://www.getzep.com/ai-agents/temporal-knowledge-graph/
- Qdrant docs: payloads, filters, named vectors and payload indexes are the
  practical basis for scoped vector retrieval.
  - https://qdrant.tech/documentation/concepts/payload/
  - https://qdrant.tech/documentation/manage-data/indexing/
  - https://qdrant.tech/documentation/concepts/collections/
- OpenAI Responses API docs: image/file input and structured JSON output are
  technically available for screenshot understanding and schema-bound extraction.
  - https://platform.openai.com/docs/api-reference/responses/create?api-mode=responses
  - https://platform.openai.com/docs/guides/structured-outputs
- MCP security best practices and OWASP prompt injection guidance: retrieved
  or uploaded content must be treated as untrusted data, not instructions.
  - https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices
  - https://owasp.org/www-community/attacks/PromptInjection
  - https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html
- Recent memory research warns against blindly rewriting memory after every
  interaction and supports keeping raw episodes as first-class evidence.
  - https://arxiv.org/abs/2605.12978
  - https://arxiv.org/abs/2606.04329
  - https://arxiv.org/abs/2603.07670

## Research Conclusions To Preserve

- Mem0-style writes should be treated as extraction plus conflict resolution,
  not append-only note creation.
- LangMem-style managers are a good conceptual fit: input plus existing memory
  can produce insert, update, delete or no-op decisions.
- Graphiti's strongest lesson for this feature is temporal provenance. A link
  should know why it exists, when it was inferred, and which source supported it.
- Qdrant should support recall, but not become the source of truth. Payload
  filters and named vectors are useful for scope, content type and time windows.
- Structured outputs should be required for AI extraction and linking. Free-form
  model text should not mutate canonical memory directly.
- Uploaded text, screenshots, OCR and retrieved context are untrusted data.
  They are evidence, not instructions.
- Raw source storage and durable memory promotion must stay separate. This is
  the main guardrail against hallucination, prompt injection and taxonomy drift.

## Fit With Current Repo

Already present or planned:

- `CanonicalCapture` supports raw evidence envelopes with trust, authority,
  sensitivity, classification, source refs and consolidation status.
- `ConsolidateCaptureUseCase` already converts captures into suggestions and
  blocks direct auto-write except for strict safe cases.
- `MemorySuggestion` supports inactive review candidates with target fact id,
  operation, category, tags, TTL, review payload and capture origin.
- `MemoryFactRelation` can link saved facts.
- `MemoryDocument` and `MemoryChunk` support text ingestion and source refs.
- `docs/memo-stack-core-lite-plan.md` already defines `BlobStoragePort`.
- `docs/client-integration/interview-memo-stack-clean-architecture-plan.md`
  already says screenshots should use a separate `ImageTextExtractor` port.

Not yet sufficient:

- No public upload API for arbitrary binary screenshots/files.
- No first-class `StorageObject`/`MemoryAsset` aggregate in implemented core.
- Current `/v1/documents` accepts text only.
- Current `/v1/captures` accepts text only and metadata, not actual blobs.
- No image OCR/vision extraction adapter is implemented.
- No explicit asset-to-fact or asset-to-document relation type is implemented.

## Recommended Decision

Use local-first asset storage plus review-gated memory promotion.

Rating:

```text
🎯 9   🛡️ 8   🧠 6
Approx changes: 4500-8500 LOC
```

Why:

- The UX can be very easy: drop screenshot, add note, review suggestions.
- Raw source is saved immediately, so user effort is never lost.
- Durable memory is not polluted by a hallucinated or malicious extraction.
- Local file storage can later become S3/MinIO without changing core use cases.
- Current capture/suggestion/fact lifecycle already supports most of this.

## Product Flow

Fast path:

```text
1. User drops screenshot/file and writes a short note.
2. Frontend uploads asset and creates capture with note + asset refs.
3. Server stores blob locally and canonical metadata in Postgres.
4. Worker extracts OCR/vision/text when policy allows.
5. Worker searches existing facts, documents and chunks.
6. Worker proposes:
   - save as new fact/note;
   - link to existing fact/document/category;
   - update an existing fact;
   - keep source-only for later.
7. User accepts, edits, rejects or ignores suggestions.
8. Approved memory creates/updates facts and relations.
```

Good default UX:

- Save source instantly.
- Show "processing" for AI suggestions.
- Show top 3 target suggestions with evidence and confidence.
- Let user accept all, accept one, edit text, or save source-only.
- Never require the user to choose taxonomy before capture.

## Relationship Suggestion UX

Tags are useful, but they are not enough for a high-volume personal memory
inbox. A user will not only ask "which tag is this?", but also "what does this
belong to?" The answer can be a previous call, a recent chat, a person, a file,
a project, a document, an existing fact, or a loose topic.

The frontend should therefore show relation suggestions as grouped chips:

```text
Likely contexts
  [Call with Alex - last week] [Alex] [Frontend capture UI]

Recent
  [Screenshot from 12 min ago] [Meeting notes from yesterday]

Tags
  [frontend] [ux] [decision]

Action
  [Save source-only] [Create memory] [Link selected]
```

User-facing rules:

- the user should never have to classify the item before saving it;
- top suggestions should be visible immediately after processing;
- the first row should be "likely contexts", not raw tags;
- tags are secondary filters and can be selected in addition to contexts;
- weak matches should be labeled as weak, not hidden;
- if the input is unclear, show recent context suggestions first;
- every suggested link should have a short reason such as `same person`,
  `same file`, `mentioned in last call`, `similar text`, or `recent activity`.

Recommended user actions:

```text
quick save
  stores source-only, no durable fact

save and link
  creates relation suggestions to selected contexts

save as memory
  creates a fact suggestion with tags/category/context links

save as update
  targets an existing fact and shows a diff preview
```

This keeps the UI fast while avoiding silent memory pollution.

## Relationship Suggestion Engine

The system should propose relationships using multiple candidate pools, then
rank them together. Do not rely on tags alone.

Candidate pools:

```text
1. explicit mentions
   people, project names, URLs, filenames, repo names, issue ids

2. source-near items
   same uploaded file, same screenshot batch, same thread, same document chunks

3. semantic matches
   Qdrant/vector matches over extracted text and existing facts/chunks

4. graph/entity matches
   Graphiti/entity relation candidates, hydrated through Postgres

5. temporal matches
   recent captures, recent suggestions, recent facts, active threads/events

6. user-selected history
   contexts the user has recently accepted links for

7. taxonomy matches
   category, tags, kind and TTL hints
```

Ranking signals:

```text
explicit entity mention       +35
same source/file/thread       +30
semantic similarity           +0..30
graph relation candidate      +0..25
recent activity               +0..20
same project/memory scope scope    +15
category/tag overlap          +0..15
user accepted similar link    +0..20
conflict or stale target      hard review
restricted/unauthorized       exclude
```

The exact numbers can change, but the shape matters: the strongest suggestions
come from explicit mentions and source/temporal proximity, not just embeddings.
Embeddings are useful for recall, but they should not be the only reason to
create a relationship.

Suggested tiers:

```text
score >= 85
  show as "likely", preselected only when no conflict exists

score 65-84
  show as "possible", not preselected

score 45-64
  show behind "more matches"

score < 45
  do not show unless the user searches manually
```

## Edge Case Handling Matrix

| Case | Risk | Handling |
| --- | --- | --- |
| screenshot contains malicious prompt | model follows source text as instruction | wrap extracted text as evidence only, use schema output, never let source text override system policy |
| screenshot has private credentials | sensitive data leaks into suggestions or vector index | classify sensitivity before indexing, block auto-apply, redact preview by policy |
| OCR is wrong | bad fact or bad link | keep extraction confidence, show source preview, require review below confidence threshold |
| same item uploaded twice | duplicates and noisy suggestions | content hash dedupe, keep separate source refs if user note differs |
| file is too large | storage abuse or slow processing | enforce size/type limits, store source-only if extraction is deferred |
| unsupported file type | broken processing pipeline | store asset metadata and source-only capture, mark extraction unsupported |
| user writes only a vague note | weak or random links | prefer recent contexts and explicit user selection over semantic guesses |
| many possible matches | overwhelming UI | show top 3 likely contexts, group the rest behind "more matches" |
| old meeting and new meeting look similar | wrong temporal link | include event time, source time and recency scoring, avoid auto-link on semantic score alone |
| person names collide | wrong Alex/project/person | use memory scope scope, recent interactions and evidence reasons; label ambiguity |
| current memory contradicts new capture | silent overwrite | create update suggestion with diff, preserve old fact version |
| target fact was deleted/superseded | stale relationship | exclude deleted targets, show superseded targets only as historical evidence |
| link confidence changes later | stale accepted links | store link status and provenance, allow later re-ranking without changing user-approved canonical relation |
| user rejects a suggestion | model keeps suggesting it | store rejection signal and down-rank similar future links |
| user wants no AI processing | privacy violation | support source-only save and per-capture processing policy |
| asset file is moved to cloud later | broken refs | core stores logical asset id and storage key, adapter owns physical location |
| asset upload succeeds but capture fails | orphaned file | use asset metadata state and cleanup policy for unreferenced assets |
| capture succeeds but AI fails | lost user effort | source remains saved, status becomes failed/retryable |
| vector index is stale | wrong recall | Postgres remains canonical, index rebuild is safe and idempotent |
| Graphiti is unavailable | linking broken if graph required | graph is derived candidate pool, deterministic and vector pools still work |
| user has many categories | sidebar becomes unusable | sidebar should be views over anchors: Inbox, Recent, People, Events, Files, Projects, Tags |
| tags explode | taxonomy noise | tags are suggestions, not primary structure; require normalization and usage counts |
| multi-tenant/memory scope data | privacy leak | every query is scoped by memory scope and space before ranking |
| offline desktop use | failed capture | local-first queue with retryable asset upload and capture creation |
| incomplete upload | corrupt asset | checksum, byte count, state transitions: uploading, stored, failed |

Implementation rule:

```text
source saved does not mean memory accepted
memory accepted does not mean every proposed link accepted
tags are filters
anchors are context objects
relations are evidence-backed decisions
```

Fallback for unclear input:

```text
if extraction confidence is low:
  show latest active contexts first
  include last 5 captures, last 5 accepted links, last 5 edited facts
  ask no blocking question
  default action remains source-only
```

This is important because the user may write "this one", "same as before", or
drop a screenshot without text. The system should still be useful by offering
recent context, but it should not pretend it understood the content.

## Context Anchor Model

For v1, introduce a lightweight canonical anchor model instead of turning tags
into pseudo-identifiers.

```text
MemoryAnchor
  id
  space_id
  memory_scope_id
  type: person | event | thread | asset | document | project | topic | fact
  title
  canonical_ref_id?
  aliases[]
  status
  last_activity_at
  created_at
  updated_at
  metadata

MemoryAnchorLink
  id
  space_id
  memory_scope_id
  source_anchor_id
  target_anchor_id
  relation_type:
    about | mentions | participant_in | from_event | evidence_for |
    related_to | updates | duplicates | contradicts
  confidence
  status: suggested | approved | rejected | deleted
  source_refs[]
  reason
  created_at
  reviewed_at?
```

Mapping to existing aggregates:

```text
fact anchor      -> MemoryFact
document anchor  -> MemoryDocument
asset anchor     -> MemoryAsset
thread anchor    -> MemoryThread
event anchor     -> call/meeting/import/capture group
person anchor    -> resolved entity, not just a tag
topic anchor     -> durable topic/project label
```

Tags remain plain filters:

```text
tags: frontend, ux, qdrant, bug
```

Anchors are identity-bearing objects:

```text
person: Alex
event: Call with Alex, 2026-06-02
asset: screenshot cap_123
document: frontend plan
```

This gives the UI something stable to link to, rename, merge, split and show in
recent context. It also keeps deletion and privacy rules clearer than if
`person:alex` or `event:last_call` were only tags.

## AI Linking Flow

AI should help rank and explain links, but deterministic policy owns the write.

```text
capture created
  -> extract text/entities/time hints/file hints
  -> gather candidate anchors from each pool
  -> rank deterministically
  -> ask LLM reranker only on bounded top candidates
  -> validate output against schema
  -> create relation suggestions
  -> user approves or source remains unlinked
```

LLM input should contain only bounded candidate summaries:

```text
new_item:
  redacted note
  extracted text preview
  asset metadata

candidates:
  id, type, title, preview, last_activity_at, safe evidence reason
```

LLM output should be schema-bound:

```text
[
  {
    "candidate_anchor_id": "anchor_...",
    "relation_type": "about",
    "confidence": "medium",
    "reason": "mentions Alex and frontend capture UI"
  }
]
```

Validation rules:

- output ids must be from supplied candidates;
- no new private text can be invented;
- reason is bounded and safe;
- relation type is allowlisted;
- low confidence never preselects;
- conflicts always require review;
- user rejection trains ranking preferences but does not delete source.

## Sidebar Model

The Flutter sidebar should not be only `Chats`. Better structure:

```text
Inbox
  unprocessed and source-only captures

Recent
  recently active anchors across all types

People
  person anchors

Events
  calls, meetings, chats, capture groups

Files
  assets and documents

Projects
  project/topic anchors

Tags
  plain filters
```

Default screen:

```text
New Capture
  message composer
  attachments
  processing timeline
  relation suggestions
  selected context chips
```

The user should feel like they are dumping information into an inbox, not like
they are maintaining a database.

## Why This Beats Tags-Only

Tags-only:

```text
🎯 7   🛡️ 5   🧠 4
```

It is fast but loses identity. `alex`, `alex-client`, `call-alex`,
`frontend-call` become messy strings. Merge/split/delete becomes unreliable.

Anchors plus tags:

```text
🎯 9   🛡️ 9   🧠 7
```

It gives users easy chips while giving the backend stable identity, lifecycle,
audit, permissions and future graph projection.

## Top 3 Implementation Options

### Option A - Local-first Capture Inbox with Asset Store

🎯 9   🛡️ 8   🧠 6

Approx changes: 4500-8500 LOC.

This is the recommended option. Add a first-class asset/blob layer, upload API,
local filesystem adapter, image text extraction port, and capture consolidation
that can include asset-derived text and candidate target facts.

Core behavior:

- binary goes to `BlobStoragePort`;
- metadata goes to Postgres;
- extracted text becomes document chunks or capture evidence;
- AI creates suggestions, not facts by default;
- approved suggestions create facts and relations;
- Qdrant and Graphiti projections are rebuilt from canonical state.

### Option B - Text/OCR-first MVP

🎯 8   🛡️ 6   🧠 4

Approx changes: 1200-2500 LOC.

Frontend or a thin server adapter extracts text from screenshots and sends the
text into current `/v1/captures` or `/v1/documents`. Store only local file path,
hash and mime type in metadata.

Pros:

- fastest usable prototype;
- exercises existing capture/suggestion lifecycle;
- enough to validate UX.

Cons:

- file lifecycle, deletion and cloud migration are weak;
- local paths can leak private machine structure;
- hard to guarantee asset integrity later;
- likely needs migration into Option A.

### Option C - Full Multimodal Memory Platform

🎯 8   🛡️ 9   🧠 8

Approx changes: 9000-18000 LOC.

Implement `StorageObject`, `UploadSession`, `MemoryAsset`, local + S3-compatible
storage adapters, OCR sandbox, provider vision adapter, image embeddings,
Qdrant named vectors and Graphiti entity/relation projection.

Pros:

- strongest long-term architecture;
- clean cloud path;
- best privacy/deletion/audit story.

Cons:

- too wide for first product validation;
- many provider/security/test gates before it feels usable;
- frontend feedback loop slows down.

## Proposed Domain Additions

Keep this in core as provider-neutral metadata:

```text
MemoryAsset
  id
  space_id
  memory_scope_id
  thread_id?
  source_capture_id?
  title?
  original_filename?
  mime_type
  size_bytes
  content_hash
  blob_ref
  status: pending_upload | active | processing | processed | failed | deleted
  sensitivity
  classification
  created_at
  updated_at
  metadata
```

Ports:

```text
BlobStoragePort
  put/get/delete/exists

ImageTextExtractorPort
  extract_text(asset_ref, options) -> extracted text + regions + confidence

AssetRepositoryPort
  create/get/save/list/delete

RelatedMemorySearchPort
  find facts/documents/chunks/captures related to candidate evidence
```

Do not put these into `MemoryExtractorPort`. Image/OCR extraction has different
privacy, provider, cost, timeout and poisoning risks than semantic memory
extraction.

## Storage Model

Local v1:

```text
~/.memo-stack/assets/{space_id}/{memory_scope_id}/{sha256-prefix}/{asset_id}.blob
```

Rules:

- object keys are generated ids, not filenames;
- original filename is metadata and may be redacted;
- Postgres stores lifecycle metadata and content hash;
- filesystem stores bytes only;
- delete marks DB first, then schedules blob deletion verification;
- missing/corrupt blob makes dependent asset degraded, not silently valid.

Cloud later:

```text
BlobStoragePort -> S3CompatibleBlobAdapter or MinioAdapter
```

No core use case should know if bytes live on local disk or cloud storage.

## Retrieval And Linking

Candidate target search should combine:

- exact source refs and shared source id;
- category/tag/kind overlap;
- keyword search in Postgres;
- vector search in Qdrant for extracted text chunks;
- graph search in Graphiti for entities/relations;
- deterministic reranking in application layer.

Qdrant is useful for recall, but not enough alone. Qdrant docs make payload
filters/indexes central for scoped retrieval; we still must hydrate Qdrant hits
through Postgres before showing or using them.

Graphiti is useful for temporal/entity relationships, but it must remain a
projection. If Graphiti proposes a merge/link, canonical resolver still decides.

## Auto-Link Policy

Suggested thresholds:

```text
score >= 0.92 and same source/document/entity -> allow one-click default
score 0.75-0.92 -> show as suggested relation
score 0.55-0.75 -> show as weak possible relation
score < 0.55 -> save source-only
conflict detected -> review required
secret/sensitive detected -> source-only or local-only review
```

Direct auto-link should require:

- same memory scope/space;
- active target fact/document;
- non-restricted classification;
- no conflict;
- strong evidence quote or shared source;
- deterministic idempotency key;
- not assistant-only source;
- target not stale by version.

## Edge Cases

### Input and Upload

- duplicate screenshot uploaded twice;
- same file with different filename;
- giant image or PDF;
- corrupted file;
- file says PNG but bytes are not image;
- screenshot has no useful text;
- screenshot has multiple languages;
- screenshot includes code/log/table/UI with poor OCR;
- EXIF or metadata contains private path/device info;
- upload succeeds but capture creation fails;
- capture succeeds but blob write fails;
- user closes frontend before processing finishes.

Expected behavior:

- content hash dedupe;
- bounded file size;
- mime sniffing, not trusting extension;
- idempotent upload/capture;
- capture/source can be source-only;
- no active fact until evidence is valid.

### Extraction

- OCR misses critical negation;
- vision model invents text not present in image;
- extracted text contains invisible chars;
- screenshot contains prompt injection text;
- screenshot includes credentials or API keys;
- screenshot is a meme/diagram/photo with little text;
- model returns invalid JSON;
- model produces too many candidates;
- model targets a fact id it was not allowed to see;
- model links to a stale deleted fact.

Expected behavior:

- extracted text is low/medium trust evidence;
- schema validation and evidence quote checks;
- provider egress policy before external OCR/vision;
- restricted/secret input blocks external AI by default;
- candidates become suggestions unless strict safe path passes.

### Linking and Memory Quality

- two existing facts look equally related;
- new evidence contradicts existing memory;
- screenshot belongs to a temporary task, not durable memory;
- relation is useful but fact text is not;
- image should be attached to a document, not a fact;
- same source supports multiple facts;
- user wants to save a raw observation only;
- old weak relation becomes strong after future evidence;
- category is unknown or user invents a new label.

Expected behavior:

- ambiguous target -> top 3 suggestions, no auto-link;
- conflict -> update suggestion with diff preview;
- temporary task -> TTL/current_task;
- raw observation -> source-only or document/chunk;
- future reprocessing can create new suggestions from old source.

### Privacy and Security

- screenshot contains passwords, tokens, personal data;
- local path includes private project/client name;
- prompt injection instructs memory to trust something;
- malicious document tries to become procedural instruction;
- hidden text in image attacks OCR/vision model;
- user asks to delete screenshot but fact remains;
- user deletes fact but source blob remains;
- exported bundle includes raw screenshot accidentally;
- cloud storage migration exposes object keys.

Expected behavior:

- secret scanner before external provider calls;
- memory rendered as evidence, never instruction;
- source refs are safe previews, not raw private paths;
- delete has separate fact, capture and blob lifecycle;
- redacted export omits blob payload;
- object keys treated as secrets.

### Operational

- Qdrant down during processing;
- Graphiti down during relation search;
- provider vision call times out;
- worker crashes after extraction but before suggestion commit;
- two workers process the same capture;
- derived index returns stale chunk;
- local disk full;
- storage object missing on restore;
- embedding model changes dimensions.

Expected behavior:

- canonical capture still saved;
- retry/dead-letter with safe diagnostics;
- worker leases;
- Postgres status wins over projections;
- local disk limits and backpressure;
- rebuild derived indexes from Postgres/assets.

## Reliability Scorecard

Local-first source capture:

```text
🎯 10   🛡️ 9   🧠 5
```

AI extraction accuracy:

```text
🎯 7   🛡️ 6   🧠 6
```

AI target linking:

```text
🎯 8   🛡️ 7   🧠 7
```

Silent auto-apply without review:

```text
🎯 5   🛡️ 4   🧠 5
```

Review-gated suggestions:

```text
🎯 9   🛡️ 8   🧠 6
```

## Suggested V1 Scope

Build Option A in these slices:

1. Asset metadata + local filesystem `BlobStoragePort`.
2. Upload API and SDK method.
3. Capture API can reference asset ids.
4. Local OCR/vision adapter behind `ImageTextExtractorPort`, provider optional.
5. Consolidation uses note + extracted text + existing memory search.
6. Suggestions include target candidates and relation proposal payload.
7. UI inbox shows source, suggestions and top related memories.
8. Delete/export paths respect blob lifecycle.

Do not include in V1:

- image embeddings unless text/OCR recall is not enough;
- automatic cross-memory-scope linking;
- cloud storage adapter before local lifecycle is proven;
- direct procedural memory writes from screenshots;
- storing raw images in Qdrant or Graphiti.

## Acceptance Criteria

- User can upload screenshot/file plus note in one action.
- Source is saved even if AI extraction fails.
- User sees suggested target facts/documents/categories.
- If no target is strong enough, item remains source-only.
- Approved suggestion creates a fact or relation with source refs.
- Deleted fact does not remain visible through Qdrant/Graphiti.
- Deleted asset schedules blob deletion or marks retained by policy.
- External AI is skipped when sensitivity/policy blocks egress.
- Prompt-injection-looking image text never becomes instruction memory.
- Local storage adapter can be swapped for S3-compatible adapter through port.

## Final Recommendation

Do it, but keep the promise precise:

```text
The app makes saving evidence effortless.
AI proposes where it belongs.
User or strict policy decides what becomes durable memory.
```

That is both useful and realistic. The risky version is:

```text
AI sees any screenshot and silently rewrites long-term memory.
```

That version will eventually poison memory, create false links and make deletes
hard to reason about.
