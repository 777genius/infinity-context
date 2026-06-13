# Content Extraction Clean Architecture Plan

Date: 2026-06-11

## Goal

Implement file, document, audio and video extraction as a reliable Memo Stack
capability without breaking Clean Architecture, SOLID, DDD or the current
Postgres-canonical model.

This plan builds on:

- `docs/content-extraction-parser-library-research.md`;
- `docs/memo-stack-core-lite-plan.md`;
- current `MemoryAsset`, `MemoryDocument`, `MemoryChunk`, outbox and UoW code.

## Current-state evidence

The repository already has the right primitives:

- `MemoryAsset` stores uploaded file metadata and a `BlobStoragePort` key.
- `CreateAssetUseCase` writes blob bytes and canonical asset metadata.
- `IngestDocumentUseCase` ingests already-extracted text into documents and chunks.
- `MemoryOutboxRow` and `OutboxWorker` already provide durable async side effects.
- `OutboxWorker` already uses PostgreSQL `FOR UPDATE SKIP LOCKED`.

The missing bounded capability is:

```text
MemoryAsset -> AssetExtractionJob -> ExtractionResult -> MemoryDocument/MemoryChunk
```

## External best-practice constraints

The architecture should explicitly follow these constraints:

- Microsoft DDD guidance separates domain events and integration events. Domain
  events are domain-significant, integration events should be asynchronous after
  commit.
- AWS transactional outbox guidance exists to avoid the dual-write problem when
  a database write initiates a message/event.
- PostgreSQL documents `SKIP LOCKED` as suitable for queue-like tables with
  multiple consumers, while warning that it gives an inconsistent view and should
  not be used as a general query pattern.
- OWASP file upload guidance says not to trust `Content-Type`, to limit file
  size/name, store files outside webroot, validate signatures, and run sandbox or
  antivirus/CDR where applicable.

Primary sources:

- https://learn.microsoft.com/en-us/azure/architecture/microservices/model/tactical-domain-driven-design
- https://learn.microsoft.com/en-us/dotnet/architecture/microservices/microservice-ddd-cqrs-patterns/domain-events-design-implementation
- https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html
- https://www.postgresql.org/docs/current/sql-select.html
- https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html

## Top architecture options

### Option A - Extraction Router inside current service boundary

🎯 9   🛡️ 9   🧠 7
Approx changes: `2500-4500` lines for robust MVP.

Add a clean extraction capability to current packages:

```text
memo_stack_core
  domain/extraction.py
  ports/extraction.py
  application/use_cases/request_asset_extraction.py
  application/use_cases/run_asset_extraction.py

memo_stack_adapters
  extraction/router.py
  extraction/engines/docling.py
  extraction/engines/unstructured.py
  extraction/engines/tika.py
  extraction/engines/media.py
  postgres extraction repositories + migrations

memo_stack_server
  API endpoints
  composition wiring
  outbox worker handler
```

Recommended. It fits the current architecture, keeps Postgres canonical, and
does not require new infrastructure before the product proves the flow.

### Option B - Separate extraction worker service

🎯 8   🛡️ 9   🧠 9
Approx changes: `5000-9000` lines.

Create a separate service/process that owns parser dependencies, queues,
containers and GPU/cloud integrations. Memo Stack core still owns canonical
state and jobs.

Use this when extraction becomes heavy enough that API/server deploys should not
carry parser dependencies at all. This is the enterprise path, but too large for
the first implementation.

### Option C - Inline parser in upload API

🎯 4   🛡️ 4   🧠 3
Approx changes: `600-1200` lines.

Parse during `POST /assets`. This is not recommended. It breaks API latency,
mixes upload and parser responsibilities, makes retries hard, and risks
corrupting user experience on parser failures.

## Recommendation

Choose Option A now, while keeping the adapter boundary compatible with Option B.

The implementation should make extraction a durable asynchronous capability:

```text
Upload asset
  -> CreateAssetUseCase stores blob + MemoryAsset
  -> RequestAssetExtractionUseCase creates AssetExtractionJob + outbox event
  -> OutboxWorker handles asset.extract
  -> RunAssetExtractionUseCase reads blob and calls ContentExtractionPort
  -> adapters normalize parser output to core DTOs
  -> use case stores artifacts and ingests document/chunks
  -> existing vector/cognee/graph outbox projections run after canonical commit
```

## Bounded contexts and language

Use these names consistently:

| Concept | Meaning |
| --- | --- |
| `MemoryAsset` | Canonical uploaded blob metadata and storage key |
| `AssetExtractionJob` | Durable attempt to extract searchable content from an asset |
| `ExtractionProfile` | Policy/profile choosing parser chain and limits |
| `ExtractionResult` | Provider-neutral output from parser adapters |
| `ExtractionArtifact` | Stored extracted JSON/Markdown/transcript/table/keyframe side artifact |
| `ExtractedElement` | Text/table/image/transcript/frame item with provenance |
| `MemoryDocument` | Canonical extracted text document visible to memory retrieval |
| `MemoryChunk` | Canonical retrieval unit with page/time/bbox metadata |

Do not call parser output a `MemoryDocument` until it is committed through the
canonical document/chunk lifecycle.

## Domain model

Add `packages/memo_stack_core/memo_stack_core/domain/extraction.py`.

### Entities

```python
AssetExtractionJob
  id: AssetExtractionJobId
  asset_id: MemoryAssetId
  space_id: SpaceId
  memory_scope_id: MemoryScopeId
  thread_id: ThreadId | None
  parser_profile: str
  parser_config_hash: str
  source_sha256_hex: str
  status: pending | running | succeeded | failed | unsupported | canceled | stale
  attempt_count: int
  safe_error_code: str | None
  safe_error_message: str | None
  result_document_ids: tuple[str, ...]
  metadata: Mapping[str, object]
  created_at: datetime
  updated_at: datetime
  started_at: datetime | None
  finished_at: datetime | None
```

```python
ExtractionArtifact
  id: ExtractionArtifactId
  job_id: AssetExtractionJobId
  asset_id: MemoryAssetId
  artifact_type: extracted_json | markdown | transcript | keyframe | table_html
  storage_backend: str
  storage_key: str
  sha256_hex: str
  byte_size: int
  metadata: Mapping[str, object]
  created_at: datetime
```

### Domain invariants

- A job belongs to exactly one asset.
- A job cannot move from `succeeded` to `running`.
- A job can retry only from `failed`, `unsupported` if profile changed, or
  `stale`.
- `safe_error_message` must be sanitized and short.
- `parser_profile`, `parser_config_hash` and `source_sha256_hex` are part of
  idempotency.
- A `succeeded` job must have at least one artifact or at least one linked
  document.
- `metadata` stores only primitives and safe short values.

Keep parser objects out of domain entities.

## Core ports

Add `packages/memo_stack_core/memo_stack_core/ports/extraction.py`.

### Extraction DTOs

```python
ExtractionRequest
  job_id
  asset_id
  filename
  declared_content_type
  detected_content_type
  byte_size
  sha256_hex
  content
  parser_profile
  limits

ExtractionLimits
  max_bytes
  max_pages
  max_media_seconds
  max_output_chars
  max_tables
  enable_ocr
  enable_external_ai

ExtractionResult
  normalized_content_type
  title
  language
  elements
  markdown
  chunk_candidates
  artifacts
  technical_metadata
  diagnostics
  parser_name
  parser_version
  model_version
```

```python
ExtractedElement
  kind: text | heading | table | image | transcript | frame_ocr | metadata_only
  text
  page_number
  time_start_ms
  time_end_ms
  bbox
  confidence
  metadata
```

### Ports

```python
class FileTypeDetectorPort(Protocol):
    async def detect(self, request: FileTypeDetectionRequest) -> FileTypeDetectionResult:
        ...

class ContentExtractionPort(Protocol):
    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        ...

class AssetExtractionRepositoryPort(Protocol):
    async def create(self, job: AssetExtractionJob) -> AssetExtractionJob:
        ...
    async def get_by_id(self, job_id: str) -> AssetExtractionJob | None:
        ...
    async def find_active_for_asset_profile(...) -> AssetExtractionJob | None:
        ...
    async def save(self, job: AssetExtractionJob) -> AssetExtractionJob:
        ...
    async def create_artifact(self, artifact: ExtractionArtifact) -> ExtractionArtifact:
        ...
    async def list_for_asset(...) -> list[AssetExtractionJob]:
        ...
```

Why split `FileTypeDetectorPort` from `ContentExtractionPort`:

- SRP: detection changes for security and routing reasons; parsing changes for
  quality reasons.
- ISP: tests can fake detection without faking a full parser.
- Security: detection runs before parser selection and before enabling expensive
  or dangerous behavior.

## Application use cases

### `RequestAssetExtractionUseCase`

Responsibility:

- load asset;
- validate scope and status;
- choose default `parser_profile` if none is provided;
- compute `parser_config_hash`;
- create or return existing active job;
- enqueue outbox event `asset.extract`.

It must not call any parser.

Outbox event:

```python
OutboxEvent(
    event_type="asset.extract",
    aggregate_type="asset_extraction_job",
    aggregate_id=str(job.id),
    workload_class="extraction",
    fairness_key=f"{asset.space_id}:{asset.memory_scope_id}",
    payload={
        "job_id": str(job.id),
        "asset_id": str(asset.id),
        "parser_profile": job.parser_profile,
    },
)
```

### `RunAssetExtractionUseCase`

Responsibility:

- load job and asset;
- mark job running in a short transaction;
- read blob;
- detect file type;
- call `ContentExtractionPort`;
- sanitize metadata;
- store extracted artifact blobs;
- commit artifacts, document/chunks and job state;
- enqueue existing derived projection outbox events through document/chunk ingest.

It should not know Docling, Unstructured, Tika, Marker, MinerU, NVIDIA or cloud
SDK classes.

Important transaction rule:

```text
DB transaction A: mark running
outside transaction: read blob + parse
DB transaction B: persist result + enqueue derived events
DB transaction C on failure: mark failed/unsupported
```

Do not hold a DB transaction while OCR/video parsing is running.

### `ListAssetExtractionsUseCase`

Read-side only:

- list jobs for an asset or scope;
- include latest status, parser profile, safe error, document ids and artifact
  summaries;
- no blob reads.

### `RetryAssetExtractionUseCase`

Responsibility:

- validate previous job is retryable or stale;
- create a new job when parser profile/config changes;
- otherwise re-enqueue the same job if not running;
- never duplicate documents if extraction output did not change.

## Document ingest strategy

Use a two-phase strategy.

### Phase 1 - reuse `IngestDocumentUseCase`

Convert `ExtractionResult.markdown` or deterministic element text to a canonical
text body:

```text
source_type = "asset_extraction"
source_external_id = asset_extraction_job_id
title = extraction_result.title or asset.filename
idempotency_key = "asset_extraction:{job_id}:{extracted_content_hash}"
```

Store rich parser output as `ExtractionArtifact` so we can improve chunking later
without reparsing the original file.

### Phase 2 - add `IngestExtractedDocumentUseCase`

Once we need high-quality page/time/table provenance, create chunks directly
from `ExtractedElement` or `chunk_candidates`.

Chunk metadata should include:

```text
asset_id
asset_extraction_job_id
parser_profile
parser_name
parser_version
page_number
time_start_ms
time_end_ms
bbox
element_kind
confidence
table_id
image_id
```

Do not make a whole giant table one vector chunk. Large tables should be split by
caption, header and row groups with the table HTML stored as an artifact.

## Adapter design

All parser dependencies live under `memo_stack_adapters`.

```text
memo_stack_adapters/extraction/
  router.py
  metadata.py
  sanitizer.py
  engines/
    docling_adapter.py
    unstructured_adapter.py
    tika_adapter.py
    media_adapter.py
    marker_sidecar_adapter.py
    mineru_sidecar_adapter.py
    nvidia_retriever_adapter.py
    llamaparse_adapter.py
```

### Router

The router implements `ContentExtractionPort`.

It should use a registry:

```python
class ExtractionEngine(Protocol):
    name: str
    async def supports(self, request: ExtractionRequest) -> SupportDecision:
        ...
    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        ...
```

No giant `if provider == ...` use case. New engines are added by registering new
adapters in the composition root.

### Profiles

```text
standard_local
  Docling primary
  Unstructured fallback
  Tika fallback
  metadata-only final fallback

quality_local
  Docling primary
  Marker/MinerU sidecar after license review
  Unstructured fallback
  Tika fallback

media_local
  ffprobe/MediaInfo metadata
  faster-whisper transcript
  PySceneDetect keyframes
  optional frame OCR

enterprise_gpu
  NVIDIA NeMo Retriever sidecar/container
  Docling/Tika fallback

cloud_opt_in
  LlamaParse/Mistral/Google/Azure/AWS
  only if external processing policy allows it
```

### Optional dependencies

Add extras instead of making all installs heavy:

```toml
[project.optional-dependencies]
extraction-standard = [
  "docling>=2.101.0,<3.0.0",
  "unstructured>=0.23.0,<1.0.0",
  "tika>=3.1.0,<4.0.0",
  "python-magic>=0.4.27,<1.0.0",
]
extraction-media = [
  "faster-whisper>=1.2.1,<2.0.0",
  "pymediainfo>=7.0.1,<8.0.0",
  "av>=17.1.0,<18.0.0",
  "scenedetect>=0.7,<1.0.0",
]
extraction-cloud = [
  "llama-parse>=0.6.94,<1.0.0",
  "llama-cloud>=2.9.0,<3.0.0",
  "google-cloud-documentai>=3.15.0,<4.0.0",
  "azure-ai-documentintelligence>=1.0.2,<2.0.0",
  "mistralai>=2.4.9,<3.0.0",
]
```

Do not add `marker-pdf`, `mineru` or `pymupdf4llm` as default dependencies until
license review. Prefer sidecar adapters for them.

## Persistence design

Add migration `0011_asset_extraction_jobs.sql`.

### Tables

```sql
memory_asset_extraction_jobs
  id varchar(80) primary key
  asset_id varchar(80) not null
  space_id varchar(80) not null
  memory_scope_id varchar(80) not null
  thread_id varchar(80) null
  parser_profile varchar(80) not null
  parser_config_hash varchar(80) not null
  source_sha256_hex varchar(80) not null
  parser_name varchar(120) null
  parser_version varchar(120) null
  model_version varchar(120) null
  status varchar(40) not null
  attempt_count integer not null
  safe_error_code varchar(120) null
  safe_error_message varchar(500) null
  result_document_ids_json json not null
  metadata_json json not null
  created_at timestamp with time zone not null
  updated_at timestamp with time zone not null
  started_at timestamp with time zone null
  finished_at timestamp with time zone null
```

Indexes:

```text
ix_extraction_jobs_asset_status(asset_id, status, created_at)
ix_extraction_jobs_scope_status(space_id, memory_scope_id, status, updated_at)
uq_extraction_job_active(asset_id, parser_profile, parser_config_hash, source_sha256_hex)
```

The unique index should only apply to active lifecycle statuses where supported:
`pending`, `running`, `succeeded`.

```sql
memory_asset_extraction_artifacts
  id varchar(80) primary key
  job_id varchar(80) not null
  asset_id varchar(80) not null
  artifact_type varchar(80) not null
  storage_backend varchar(80) not null
  storage_key varchar(500) not null
  sha256_hex varchar(80) not null
  byte_size integer not null
  metadata_json json not null
  created_at timestamp with time zone not null
```

Indexes:

```text
ix_extraction_artifacts_job(job_id, artifact_type)
ix_extraction_artifacts_asset(asset_id, created_at)
```

## API design

Add routes:

```text
POST /v1/assets/{asset_id}/extractions
GET  /v1/assets/{asset_id}/extractions
GET  /v1/asset-extractions/{job_id}
POST /v1/asset-extractions/{job_id}/retry
```

Add upload convenience:

```text
POST /v1/assets?extract=true&parser_profile=standard_local&estimated_media_seconds=600
```

The convenience flag should call `CreateAssetUseCase` and then
`RequestAssetExtractionUseCase`. If extraction request fails after asset upload,
return the asset and a safe extraction error. Asset storage must remain valid.
For audio/video assets, clients should pass `estimated_media_seconds` when known
so product-plan admission can reserve media analysis quota before enqueueing
expensive extraction work. If the client cannot know duration yet, Memo Stack
reserves `MEMORY_EXTRACTION_MAX_MEDIA_SECONDS` as the conservative unknown-media
estimate and can later reconcile against extractor metadata.

Response shape:

```json
{
  "data": {
    "extraction": {
      "job_id": "extract_...",
      "status": "pending",
      "parser_profile": "standard_local",
      "progress": {
        "stage": "queued",
        "percent": 0,
        "message": "Waiting for extraction worker",
        "terminal": false
      },
      "usage": {
        "plan_tier": "free",
        "media_analysis_seconds_requested": 600,
        "media_analysis_seconds_limit": 36000
      }
    }
  }
}
```

Usage API for frontend plan meters:

```text
GET /v1/usage?space_slug=team
```

The initial product-plan governance is space-scoped. `UsageSubjectType.USER`
exists in the core domain so a future User identity can become the billing
subject without changing extraction use cases.

## Worker design

Extend `OutboxWorker`:

```python
elif job.event_type == "asset.extract":
    await self._container.run_asset_extraction.execute(
        RunAssetExtractionCommand(job_id=str(job.payload_json["job_id"]))
    )
```

Required settings:

```text
MEMORY_EXTRACTION_ENABLED
MEMORY_EXTRACTION_DEFAULT_PROFILE
MEMORY_EXTRACTION_EXTERNAL_AI_ENABLED
MEMORY_EXTRACTION_MAX_BYTES
MEMORY_EXTRACTION_MAX_PAGES
MEMORY_EXTRACTION_MAX_MEDIA_SECONDS
MEMORY_EXTRACTION_MAX_OUTPUT_CHARS
MEMORY_EXTRACTION_VISION_MODEL
MEMORY_EXTRACTION_VISION_DETAIL
MEMORY_EXTRACTION_ASR_MODEL
MEMORY_EXTRACTION_ASR_DEVICE
MEMORY_EXTRACTION_ASR_COMPUTE_TYPE
MEMORY_PRODUCT_PLAN_TIER
MEMORY_PLAN_MEDIA_ANALYSIS_SECONDS_PER_MONTH
MEMORY_EXTRACTION_WORKER_LIMIT
MEMORY_EXTRACTION_LEASE_TIMEOUT_SECONDS
```

Parser profiles:

```text
standard_local
  Lightweight default. Uses local deterministic extractors: text, pypdf,
  Pillow/tesseract metadata/OCR hooks, ffprobe/ffmpeg media metadata/keyframes.

standard_docling
  Optional high-fidelity document path. Install `memo-stack[docling]` and use
  this profile to try Docling first for PDF/Office/HTML/images, with fallback
  to `standard_local` engines when Docling is unavailable or fails.

standard_vision
  Optional external image understanding path. Install `memo-stack[openai]`, set
  `MEMORY_OPENAI_API_KEY`, and enable `MEMORY_EXTRACTION_EXTERNAL_AI_ENABLED`.
  Uses the Responses API with image input to extract screenshot/photo meaning as
  evidence, with fallback to OCR/image metadata when egress is disabled,
  unconfigured or unavailable.

standard_asr
  Optional local speech-to-text path. Install `memo-stack[asr]` and use this
  profile for audio/video transcript extraction through faster-whisper, with
  fallback to media metadata/keyframes when ASR is unavailable or fails.

standard_full
  Enables optional provider paths: Docling for documents, OpenAI vision for
  images and faster-whisper for media, while preserving local fallbacks.
```

Current outbox worker has one lease timeout. Extraction should eventually get
separate timeout/backoff because video/OCR jobs are much slower than vector
projection. MVP can reuse the outbox row status if `RUNNING_LEASE_TIMEOUT` is
made configurable by workload class.

## Security and safety

Minimum MVP:

- keep existing max upload size;
- detect MIME independently of `Content-Type`;
- never execute macros or embedded scripts;
- no recursive archive extraction by default;
- metadata-only status for unsupported files;
- safe filename already generated by application;
- artifact blobs stored under generated storage keys;
- safe error messages only;
- parser prompt-injection text remains evidence, never instruction.

Next hardening:

- sandbox parser processes;
- antivirus/CDR hook port;
- per-profile page/time/cost budgets;
- archive manifest scanner with recursion and expansion ratio limits;
- quarantine status;
- external processing policy per MemoryScope/Space.

## Metadata policy

Do not store all metadata blindly.

Safe searchable metadata:

```text
mime_declared
mime_detected
parser_profile
parser_name
parser_version
model_version
page_count
duration_ms
width
height
fps
codec
language
ocr_used
table_count
element_count
time_start_ms
time_end_ms
page_number
bbox
confidence
```

Sensitive by default:

```text
gps
device_serial
camera_model
author
creator
producer
local_file_path
hidden_office_metadata
raw_exif
```

Sensitive metadata should be dropped unless a future explicit retention policy
enables it.

## Idempotency and reprocessing

Use three hashes:

```text
asset.sha256_hex
parser_config_hash
extracted_content_hash
```

Rules:

- same asset hash + same parser profile + same config hash returns existing job;
- same extracted content hash returns existing document/chunks;
- parser version changes can mark old jobs `stale`;
- reprocess creates a new job if profile/config changed;
- derived indexes are rebuilt from canonical documents/chunks, never from parser
  provider state.

## SOLID/DRY rules

### SRP

- `MemoryAsset` owns file metadata, not parsing.
- `AssetExtractionJob` owns extraction lifecycle, not document retrieval.
- `ContentExtractionPort` owns parser output, not persistence.
- `RunAssetExtractionUseCase` orchestrates, but does not parse.
- `IngestDocumentUseCase` owns canonical text/chunk persistence.

### OCP

Add a parser by adding an `ExtractionEngine` adapter and registering it.

Do not modify core use cases when adding:

- Marker;
- MinerU;
- NVIDIA NeMo Retriever;
- LlamaParse;
- Mistral OCR;
- a future in-house parser.

### LSP

Every extraction adapter must obey:

- returns provider-neutral `ExtractionResult`;
- reports unsupported as structured diagnostics, not random exceptions;
- honors limits;
- never mutates canonical state;
- does not return unsafe giant metadata values.

### ISP

Avoid a huge `DocumentProcessingProvider`.

Small interfaces:

- `FileTypeDetectorPort`;
- `ContentExtractionPort`;
- `AssetExtractionRepositoryPort`;
- `BlobStoragePort`;
- existing `DocumentRepositoryPort`;
- existing `OutboxPort`.

### DIP

Core use cases depend on ports. Server composition wires:

```text
ExtractionRouter(ContentExtractionPort)
  -> DoclingEngine
  -> UnstructuredEngine
  -> TikaEngine
  -> MediaEngine
```

`memo_stack_core` must not import parser libraries.

### DRY

Centralize:

- metadata sanitizer;
- parser diagnostics mapping;
- content hash generation;
- artifact storage key generation;
- `ExtractionResult -> IngestDocumentCommand` mapping;
- error classification.

Do not duplicate per-parser persistence code.

## Optimization plan

MVP optimizations:

- do MIME sniffing before expensive parsing;
- skip duplicate jobs using `asset.sha256_hex` and parser profile;
- store extracted normalized JSON artifact so document/chunk rebuilds do not
  require reparsing;
- enforce output char/page/media limits;
- queue extraction separately from vector projection via `workload_class`;
- use `fairness_key` by `space_id:memory_scope_id` to avoid one scope starving
  the worker.

Later optimizations:

- parser sidecar pool for heavy OCR;
- GPU worker profile for NVIDIA/MinerU/Marker;
- streaming upload/session API for large media;
- thumbnail/keyframe cache;
- table-specific chunking;
- batch extraction with priority.

## Testing strategy

Unit tests:

- `AssetExtractionJob` state transitions;
- idempotent job request;
- metadata sanitizer;
- parser router selection;
- fake extraction adapter success/failure/unsupported;
- mapping `ExtractionResult` to ingest command.

Integration tests:

- upload asset then request extraction creates job and outbox event;
- worker handles `asset.extract` with fake adapter;
- successful extraction creates document/chunks and vector outbox events;
- parser failure marks job failed with safe error;
- unsupported file creates metadata-only/unsupported job;
- duplicate request returns same job.

Security tests:

- spoofed `Content-Type` does not override detected MIME;
- zip/archive defaults to manifest-only or unsupported;
- huge parser output is truncated/rejected;
- metadata PII is dropped.

Architecture tests:

- `memo_stack_core` imports no Docling, Unstructured, Tika, ffmpeg, Whisper,
  Marker, MinerU, NVIDIA, cloud SDKs, FastAPI or SQLAlchemy;
- parser adapters import core ports, not the other way around.

Golden/E2E:

- small PDF text -> searchable memory chunk;
- scanned/image document -> OCR text when profile enables OCR;
- audio/video sample -> transcript chunks with timecodes;
- delete document hides chunks immediately and derived indexes are cleaned by
  existing outbox path.

## Implementation phases

### Phase 1 - Canonical extraction job skeleton

🎯 9   🛡️ 9   🧠 5
Approx changes: `900-1400` lines.

- domain entities;
- ports and DTOs;
- Postgres rows/repository/migration;
- request/list/retry use cases;
- API endpoints;
- outbox event creation;
- fake/noop extractor.

### Phase 2 - Worker and normalized ingest

🎯 9   🛡️ 8   🧠 6
Approx changes: `900-1600` lines.

- `RunAssetExtractionUseCase`;
- worker handler;
- artifact storage;
- `ExtractionResult -> IngestDocumentCommand`;
- tests with fake extractor.

### Phase 3 - Standard local parser profile

🎯 8   🛡️ 8   🧠 7
Approx changes: `900-1800` lines.

- Docling adapter;
- Unstructured fallback;
- Tika fallback;
- file type detector;
- parser settings and capability reporting.

### Phase 4 - Media profile

🎯 8   🛡️ 7   🧠 8
Approx changes: `1200-2400` lines.

- ffprobe/MediaInfo metadata;
- faster-whisper transcript;
- timecoded chunks;
- optional keyframe extraction.

### Phase 5 - Quality and enterprise profiles

🎯 7   🛡️ 8   🧠 9
Approx changes: `2000-5000` lines.

- Marker/MinerU sidecar after license review;
- NVIDIA NeMo Retriever sidecar;
- LlamaParse/cloud Document AI opt-in;
- tenant policy controls and cost/budget accounting.

## Final shape

The final dependency direction:

```text
memo_stack_core.domain
  AssetExtractionJob, ExtractionArtifact

memo_stack_core.ports
  FileTypeDetectorPort, ContentExtractionPort, AssetExtractionRepositoryPort

memo_stack_core.application
  RequestAssetExtractionUseCase
  RunAssetExtractionUseCase
  ListAssetExtractionsUseCase
  RetryAssetExtractionUseCase

memo_stack_adapters
  Postgres extraction repositories
  Local artifact storage via BlobStoragePort
  Parser engines and router

memo_stack_server
  API, settings, worker event handler, composition root
```

This keeps Memo Stack aligned with the main invariant:

```text
Postgres is canonical.
Parsers, Qdrant, Graphiti and cloud services are derived/provider layers.
```
