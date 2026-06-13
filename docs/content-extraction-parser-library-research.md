# Content extraction and parser library research

Date: 2026-06-11

## Goal

Find a scalable, clean-architecture friendly way to parse uploaded files before
they become canonical memory documents and chunks.

The current implementation already has:

- binary asset storage through `MemoryAsset` and `BlobStoragePort`;
- text-only document ingest through `IngestDocumentUseCase`;
- derived vector and external memory indexing through outbox events.

The missing part is a first-class extraction layer:

```text
MemoryAsset -> AssetExtractionJob -> ExtractedContent -> MemoryDocument -> MemoryChunk
```

The extraction layer must stay outside `memo_stack_core` provider dependencies.
Core should only know neutral DTOs and ports. Docling, Unstructured, Tika,
ffmpeg, ASR and OCR libraries should live in adapters or a separate worker.

## Dependency snapshot

Checked PyPI on 2026-06-11.

| Package | Version | Python | License | Role |
| --- | ---: | --- | --- | --- |
| `docling` | 2.101.0 | >=3.10,<4.0 | MIT | Primary structured document parser |
| `unstructured` | 0.23.0 | >=3.11,<3.14 | Apache-2.0 | Fallback parser and OCR/table extraction |
| `tika` | 3.1.0 | not declared | Apache-2.0 | Broad text/metadata fallback through Apache Tika |
| `markitdown` | 0.1.6 | >=3.10 | MIT | Lightweight Markdown conversion |
| `llama-index` | 0.14.22 | >=3.10,<4.0 | MIT | RAG ingestion orchestration, not canonical parser |
| `haystack-ai` | 2.30.1 | >=3.10 | Apache-2.0 | RAG pipelines/converters, not canonical parser |
| `faster-whisper` | 1.2.1 | >=3.9 | MIT | Local ASR for audio/video transcript |
| `pymediainfo` | 7.0.1 | >=3.9 | MIT | Media technical metadata |
| `av` | 17.1.0 | >=3.10 | BSD-3-Clause | Python FFmpeg bindings |
| `scenedetect` | 0.7 | >=3.10 | BSD-3-Clause | Video scene boundaries/keyframes |
| `python-magic` | 0.4.27 | broad | MIT | libmagic MIME sniffing |
| `openai-whisper` | 20250625 | >=3.8 | MIT | Alternative local ASR |
| `marker-pdf` | 1.10.2 | >=3.10,<4.0 | GPL-3.0-or-later | High-quality doc-to-Markdown/JSON/chunks, license-sensitive |
| `mineru` | 3.3.1 | >=3.10,<3.14 | MinerU Open Source License | High-quality PDF/Office/image parser, license-sensitive |
| `llama-parse` | 0.6.94 | >=3.9,<4.0 | MIT client | Managed/self-hosted LlamaParse client |
| `llama-cloud` | 2.9.0 | >=3.9 | MIT client | LlamaCloud platform client |
| `paddleocr` | 3.7.0 | >=3.8 | Apache-2.0 | OCR/layout/table engine |
| `surya-ocr` | 0.20.0 | >=3.10,<4 | Apache-2.0 | OCR/layout/table recognition |
| `camelot-py` | 2.0.0 | >=3.10 | MIT | Rule-based PDF table extraction |
| `pdfplumber` | 0.11.9 | >=3.8 | unknown on PyPI | PDF text/layout/table inspection |
| `pymupdf4llm` | 1.27.2.3 | >=3.10 | AGPL/commercial | Fast PDF-to-Markdown helper, license-sensitive |
| `nv-ingest` | 26.3.0 | not declared | Apache-2.0 | NVIDIA extraction package |
| `nemo-retriever` | 26.5.0 | >=3.12,<3.13 | Apache-2.0 | NVIDIA NeMo Retriever extraction library |
| `google-cloud-documentai` | 3.15.0 | >=3.10 | Apache-2.0 | Google Document AI client |
| `azure-ai-documentintelligence` | 1.0.2 | >=3.8 | MIT | Azure Document Intelligence client |
| `mistralai` | 2.4.9 | >=3.10 | not declared | Mistral OCR/API client |

## Source findings

### Docling

Official docs describe Docling as a document conversion toolkit that handles
PDF, DOCX, PPTX, XLSX, HTML, EPUB, audio, WebVTT, images, emails, LaTeX and
plain text, with a unified `DoclingDocument` representation and exports to
Markdown, HTML, JSON, WebVTT, DocTags and DocLang.

Strengths:

- strong PDF layout, reading order, table structure, formulas and image handling;
- local execution, useful for private memory data;
- unified document model fits our canonical extraction DTOs;
- built-in chunking abstractions with metadata;
- integrations with LangChain, LlamaIndex, Haystack and other RAG tools.

Important caveat:

- title/authors/references/language metadata extraction is still listed by
  Docling as coming soon, so do not rely on Docling alone for metadata.

Primary sources:

- https://docling-project.github.io/docling/
- https://docling-project.github.io/docling/usage/supported_formats/
- https://docling-project.github.io/docling/concepts/chunking/
- https://github.com/docling-project/docling

### Unstructured

Unstructured's open-source partitioning API auto-detects document types and
routes to format-specific partitioners. Its PDF and image partitioners support
strategies such as `fast`, `hi_res`, `ocr_only` and `auto`, plus table structure
inference and OCR options.

Strengths:

- very pragmatic ETL-style parser for many document types;
- good fallback for OCR, tables and messy enterprise documents;
- element-level metadata includes fields such as page number, coordinates,
  languages and HTML representation for tables;
- usable locally or through the Unstructured API.

Weaknesses:

- dependency footprint can be heavy;
- hosted API may be undesirable for private memory unless opt-in;
- output should be normalized before becoming canonical memory.

Primary sources:

- https://docs.unstructured.io/open-source/core-functionality/partitioning
- https://docs.unstructured.io/open-source/concepts/document-elements
- https://github.com/Unstructured-IO/unstructured

### Apache Tika

Apache Tika is a mature content analysis toolkit for text and metadata
extraction from a very broad set of file formats. It is especially useful as a
fallback service for unknown formats and metadata extraction.

Strengths:

- mature, battle-tested, broad format coverage;
- good MIME detection and metadata extraction;
- can run as a separate Tika Server, which fits adapter/process isolation.

Weaknesses:

- weaker semantic structure than Docling/Unstructured for RAG-quality chunks;
- Java service adds operational overhead;
- layout/table fidelity is usually not the main strength.

Primary sources:

- https://tika.apache.org/
- https://cwiki.apache.org/confluence/display/TIKA/TikaServer

### MarkItDown

Microsoft MarkItDown converts files to Markdown and supports formats such as
PDF, PowerPoint, Word, Excel, images, audio, HTML, text-based formats and ZIPs.

Strengths:

- simple API and fast "make it Markdown" path;
- useful for quick import paths and CLI tooling;
- can use plugins and optional LLM image description.

Weaknesses:

- too lossy as canonical extraction for memory;
- metadata, coordinates, page regions and parser diagnostics are not rich enough
  for our main ingest pipeline.

Primary sources:

- https://github.com/microsoft/markitdown
- https://pypi.org/project/markitdown/

### Marker

Marker is a stronger candidate than MarkItDown for high-quality document
understanding. It converts PDF, images, PPTX, DOCX, XLSX, HTML and EPUB to
Markdown, JSON, chunks and HTML. It formats tables, forms, equations, inline
math, links, references and code blocks, extracts images, removes headers and
footers, and can optionally use LLMs to improve accuracy.

Strengths:

- high-quality local parsing for complex documents;
- JSON and chunk renderers map well to `ExtractionResult`;
- supports GPU, CPU and Apple MPS;
- useful as a high-accuracy profile when documents are messy.

Weaknesses:

- `marker-pdf` is GPL-3.0-or-later on PyPI, so it should not be added as a
  normal runtime dependency without license review;
- LLM boost can increase cost, latency and nondeterminism;
- best used behind an optional sidecar boundary.

Primary sources:

- https://github.com/datalab-to/marker
- https://pypi.org/project/marker-pdf/

### MinerU

MinerU is a high-quality document parser that targets PDF, image, DOCX, PPTX and
XLSX inputs and outputs Markdown and JSON. It focuses on reading order,
scientific documents, formulas, tables, OCR and rich intermediate artifacts.

Strengths:

- strong fit for academic/scientific PDFs, formulas and complex layouts;
- supports table-to-HTML and formula-to-LaTeX conversion;
- supports OCR detection/recognition for 109 languages;
- can run through CLI, local API or remote API modes.

Weaknesses:

- license is a custom MinerU Open Source License based on Apache 2.0 with extra
  conditions, so it needs legal/product review before bundling;
- heavier ML/runtime footprint than Docling;
- page-level output and stable chunk provenance should be tested before using it
  as a default parser.

Primary sources:

- https://github.com/opendatalab/MinerU
- https://opendatalab.github.io/MinerU/
- https://pypi.org/project/mineru/

### LlamaParse and LlamaCloud

LlamaParse is an enterprise document processing platform for LLM pipelines. It
offers Parse, Extract, Classify, Split, Sheets and Index. Parse is layout-aware
agentic OCR for PDFs, scans, tables and charts, returning Markdown, text or JSON.
The SDK supports processing options such as OCR languages and output options such
as tables as Markdown and saved screenshots.

Strengths:

- high-quality managed path for complex enterprise documents;
- structured extraction from schemas and classification are useful for memory
  candidate suggestions;
- self-hosting architecture exists for enterprise deployments.

Weaknesses:

- cloud/API path is not local-first and must be explicit opt-in;
- cost, data retention and tenant privacy need policy controls;
- output must still be normalized into our canonical DTOs.

Primary sources:

- https://developers.llamaindex.ai/llamaparse/
- https://developers.llamaindex.ai/llamaparse/parse/
- https://developers.llamaindex.ai/llamaparse/self_hosting/architecture/

### NVIDIA NeMo Retriever / nv-ingest

NVIDIA NeMo Retriever extraction, formerly NVIDIA Ingest in some materials, is a
scalable framework for content and metadata extraction from PDFs, HTML, Word,
PowerPoint, audio, video and image files. It classifies sub-page content such as
text, tables, charts and infographics, extracts content into a standard schema,
and can also compute embeddings and write to LanceDB.

Strengths:

- closest match to an enterprise-grade multimodal extraction service;
- designed for parallel extraction, metadata and downstream RAG;
- supports text, tables, charts, infographics and transcripts;
- Apache-2.0 packages are more product-friendly than GPL/custom parser stacks.

Weaknesses:

- operationally heavy and GPU/NIM oriented;
- `nemo-retriever` currently requires Python >=3.12,<3.13, while this project is
  Python >=3.11, so it should be a separate worker/container, not an in-process
  dependency;
- likely overkill for local desktop MVP.

Primary sources:

- https://docs.nvidia.com/nemo/retriever/latest/extraction/overview/
- https://docs.nvidia.com/nemo/retriever/latest/extraction/nv-ingest-python-api/
- https://docs.nvidia.com/nemo/retriever/latest/extraction/content-metadata/
- https://github.com/NVIDIA/NeMo-Retriever

### Cloud Document AI services

Google Document AI, Amazon Textract, Azure Document Intelligence and Mistral OCR
are serious production options for opt-in cloud extraction.

Strengths:

- very strong OCR/forms/tables/layout coverage;
- managed scaling and lower local operational burden;
- useful as tenant-configured enterprise fallback.

Weaknesses:

- not local-first;
- external data processing and retention must be explicit;
- vendor lock-in and per-page costs;
- different schemas require normalization.

Primary sources:

- https://cloud.google.com/document-ai
- https://docs.cloud.google.com/document-ai/docs/processors-list
- https://aws.amazon.com/textract/
- https://docs.aws.amazon.com/textract/latest/dg/how-it-works-analyzing.html
- https://azure.microsoft.com/en-us/products/ai-foundry/tools/document-intelligence
- https://docs.mistral.ai/studio-api/document-processing/basic_ocr

### OCR and table specialists

PaddleOCR, Surya, Camelot and pdfplumber are useful specialist adapters, not a
complete memory ingestion layer.

Use them when:

- a table is known to be important and the general parser failed;
- scanned/image-heavy documents need OCR fallback;
- a user requests a table-specific extraction;
- we need diagnostics and visual debugging for parser quality.

Primary sources:

- https://github.com/PaddlePaddle/PaddleOCR
- https://github.com/datalab-to/surya
- https://camelot-py.readthedocs.io/
- https://github.com/jsvine/pdfplumber

### LlamaIndex and Haystack

These are useful RAG/LLM orchestration frameworks. They include loaders,
converters, ingestion pipelines, transformations and splitters. They should not
be the canonical parser boundary for Memo Stack.

Use them only if they save adapter work around optional pipelines. Keep our own
`ContentExtractionPort` and our own canonical DTOs.

Primary sources:

- https://developers.llamaindex.ai/python/framework/module_guides/loading/ingestion_pipeline/
- https://docs.llamaindex.ai/en/stable/module_guides/loading/simpledirectoryreader/
- https://docs.haystack.deepset.ai/docs/converters

### Media pipeline

Video and audio should not go through a document parser.

Recommended stack:

- `ffprobe` or MediaInfo for streams, duration, codecs, dimensions, frame rate,
  language tags and container metadata;
- `faster-whisper` for local speech-to-text;
- optional WhisperX if word-level timestamps and diarization become important;
- PySceneDetect and ffmpeg frame extraction for keyframes;
- OCR selected keyframes through Docling/Unstructured/Tesseract only when useful.

Primary sources:

- https://ffmpeg.org/ffprobe.html
- https://mediaarea.net/en/MediaInfo
- https://github.com/SYSTRAN/faster-whisper
- https://www.scenedetect.com/docs/latest/
- https://exiftool.org/

## Recommended architecture

### Core ports and DTOs

Add provider-neutral core contracts:

```python
class ContentExtractionPort(Protocol):
    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        ...
```

Core DTOs should not expose Docling, Unstructured or Tika objects:

```text
ExtractionRequest
  asset_id
  storage_key
  filename
  declared_content_type
  byte_size
  sha256_hex
  parser_profile
  limits

ExtractionResult
  normalized_content_type
  title
  language
  documents[]
  elements[]
  chunk_candidates[]
  technical_metadata
  diagnostics

ExtractedElement
  kind: text | heading | table | image | transcript | frame_ocr | metadata_only
  text
  page
  time_start_ms
  time_end_ms
  bbox
  confidence
  metadata
```

### Canonical tables

Add Postgres canonical lifecycle for extraction:

```text
asset_extraction_jobs
  id
  asset_id
  space_id
  memory_scope_id
  thread_id
  parser_profile
  parser_version
  status: pending | running | succeeded | failed | unsupported | stale
  attempts
  safe_error_code
  safe_error_message
  started_at
  finished_at
  created_at
  updated_at

asset_extraction_artifacts
  id
  job_id
  asset_id
  artifact_type: extracted_json | markdown | transcript | keyframe | table_html
  storage_backend
  storage_key
  sha256_hex
  metadata
```

Keep Postgres canonical. Qdrant, Graphiti and Cognee stay derived indexes.

### Adapter routing

```text
Upload asset
  -> store MemoryAsset + blob
  -> enqueue asset.extract
  -> worker reads blob
  -> MIME sniffing with libmagic/Tika/ffprobe
  -> route parser
  -> normalize output to ExtractionResult
  -> create MemoryDocument + MemoryChunk
  -> enqueue vector.upsert_chunk and optional graph/cognee projections
```

Routing:

| Input | Primary | Fallback |
| --- | --- | --- |
| PDF/DOCX/PPTX/XLSX/HTML/images/email/text | Docling | Unstructured, then Tika |
| scanned PDF/images | Docling OCR | Unstructured `hi_res`/`ocr_only` |
| unknown office/document | Tika | metadata-only |
| audio | faster-whisper | metadata-only |
| video | ffprobe + faster-whisper + PySceneDetect | metadata-only |
| ZIP/archive | safe manifest only first | explicit opt-in recursive extraction |

### Parser profiles

Do not hard-code one parser. Add a profile-based router:

```text
standard_local
  Docling primary
  Unstructured OCR/table fallback
  Tika metadata/text fallback

quality_local
  Docling primary
  Marker or MinerU sidecar for hard PDFs, after license review
  Unstructured/Tika fallback

enterprise_gpu
  NVIDIA NeMo Retriever sidecar/container
  Docling/Tika fallback for local/simple docs

cloud_opt_in
  LlamaParse, Mistral OCR, Google Document AI, Azure Document Intelligence or AWS Textract
  only when tenant policy allows external processing

media_local
  ffprobe/MediaInfo metadata
  faster-whisper transcript
  PySceneDetect keyframes
  optional OCR/captioning for selected frames
```

Profile choice should be persisted on `asset_extraction_jobs.parser_profile`.
Parser versions, model versions and output hashes must also be persisted so we
can reprocess assets safely after upgrades.

## Top options

### Decision matrix

Scale: 10 is best, except implementation complexity where 10 is hardest.

| Option | Extraction quality | Product reliability | Local privacy | License safety | Ops simplicity | Scale potential | Memo Stack fit | Complexity |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Extraction Router, Docling default plus profiles | 9 | 9 | 9 | 8 | 7 | 9 | 10 | 8 |
| NVIDIA NeMo Retriever service | 9 | 8 | 7 | 8 | 4 | 10 | 8 | 9 |
| Managed cloud Document AI profile | 9 | 8 | 4 | 9 | 8 | 9 | 7 | 6 |
| Docling-only | 7 | 8 | 10 | 10 | 9 | 7 | 8 | 4 |
| Unstructured-only | 7 | 7 | 8 | 9 | 6 | 7 | 7 | 5 |
| Marker/MinerU as bundled dependency | 9 | 6 | 9 | 4 | 5 | 7 | 6 | 7 |
| Tika-first | 5 | 9 | 9 | 10 | 6 | 8 | 6 | 5 |

Reading:

- The best product choice is the Extraction Router, not because every parser is
  perfect, but because failures, licenses, costs and privacy policies become
  configurable instead of hard-coded.
- Marker/MinerU look very strong technically, but their licenses/runtime
  footprints make them better as optional sidecars than default dependencies.
- NVIDIA is the most enterprise-scale path, but too heavy for the first local
  product iteration.
- Cloud Document AI is excellent when the tenant explicitly allows external
  processing.

### Option 1: Extraction Router with Docling default and optional high-quality profiles

Use a stable `ContentExtractionPort` plus parser registry. Default to Docling,
fallback to Unstructured and Tika, and add Marker/MinerU/NVIDIA/LlamaParse/cloud
Document AI as opt-in profiles.

Best fit for Memo Stack because it avoids betting canonical memory on one
vendor/library while still allowing high-quality parsing when needed.

Approx implementation size:

- MVP docs/images: 1600-2600 changed lines;
- with audio/video and profile router: 3200-5200 changed lines.

### Option 2: NVIDIA NeMo Retriever / nv-ingest as extraction service

Use NVIDIA NeMo Retriever as a separate extraction service for documents and
media, with Docling/Tika fallback and our own canonical DTO normalization.

This is the most powerful enterprise-style path, especially for GPU-backed
multimodal extraction at scale. It is not the best local-first MVP.

Approx implementation size:

- service integration MVP: 1800-3200 changed lines;
- production deployment and observability: 4000-7000 changed lines.

### Option 3: Managed cloud document AI fallback

Use LlamaParse/Mistral OCR/Google Document AI/Azure/AWS Textract as an opt-in
provider profile when tenant policy allows external document processing.

This gives high quality and low ops, but privacy, cost and vendor lock-in are
the main tradeoffs.

Approx implementation size:

- cloud adapter MVP: 1200-2200 changed lines;
- policy, billing and tenant controls: 2500-4500 changed lines.

## Edge cases to design up front

Security and safety:

- file extension lies about MIME type;
- password-protected PDFs and Office files;
- macro-enabled Office files;
- zip bombs and recursive archives;
- parser crashes or hangs;
- documents with prompt-injection text;
- EXIF GPS, device serials, usernames and local paths leaking PII;
- untrusted HTML with scripts or external resources.

Quality:

- scanned PDFs with no text layer;
- bad OCR, mixed languages, rotated pages;
- multi-column pages and reading-order errors;
- large tables that should not become a single vector chunk;
- duplicate pages, appendices and boilerplate;
- chart/image content that needs captioning but should not hallucinate facts;
- video with no audio;
- long videos with timestamp drift;
- multiple speakers and diarization uncertainty.

Lifecycle:

- parser version changes chunk hashes;
- reprocessing creates duplicate documents unless idempotency includes parser
  profile and extracted-content hash;
- asset deleted while extraction is queued;
- extraction succeeds but document ingest fails;
- unsupported files still need metadata-only records;
- Qdrant/Graphiti rebuild must be possible from Postgres and blobs.

## Metadata policy

Store safe searchable metadata in Postgres:

```text
mime_detected
parser_profile
parser_version
page_count
duration_ms
width
height
fps
codec
audio_stream_count
video_stream_count
language
ocr_used
table_count
page_number
time_start_ms
time_end_ms
bbox
confidence
```

Do not store raw EXIF GPS, local file paths, device identifiers or author names
as normal searchable metadata by default. Put sensitive raw metadata behind an
explicit retention/privacy policy, or drop it.

## Recommendation

Choose the Extraction Router.

The ideal solution for this project is not a single parser. It is a stable,
provider-neutral extraction boundary with profiles.

Default profile:

```text
Docling -> Unstructured -> Tika -> metadata-only
```

High-quality optional profiles:

```text
Marker/MinerU sidecar for difficult PDFs
NVIDIA NeMo Retriever for GPU/enterprise multimodal extraction
LlamaParse or cloud Document AI for tenant-approved managed extraction
```

This gives us the best balance:

- structured document model for high-quality memory chunks;
- local-first privacy;
- fallback coverage from Unstructured and Tika;
- room for stronger engines without licensing/dependency lock-in;
- clean separation between canonical memory and parser-specific output;
- a clear route to video/audio without forcing document parsers to handle media.

MVP order:

1. Add `ContentExtractionPort`, neutral DTOs and `AssetExtractionJob`.
2. Add async worker command for `asset.extract`.
3. Add parser registry and persisted `parser_profile`.
4. Implement MIME sniffing and metadata-only extraction first.
5. Add Docling adapter for PDF/DOCX/PPTX/XLSX/HTML/image/text.
6. Add Unstructured fallback for OCR-heavy/scanned/table cases.
7. Add Tika fallback for unknown formats.
8. Add media metadata with ffprobe/MediaInfo.
9. Add audio transcript with faster-whisper.
10. Add video keyframes and optional OCR later.
11. Add Marker/MinerU sidecar only after license review and quality tests.
12. Add cloud/NVIDIA profile only when deployment actually needs it.
