import asyncio
import base64
import time
from dataclasses import dataclass

from memo_stack_adapters.extraction.content import (
    ExtractionEngine,
    ImageMetadataExtractionEngine,
    PdfTextExtractionEngine,
    SimpleFileTypeDetector,
    StandardExtractionRouter,
    SupportDecision,
)
from memo_stack_adapters.extraction.docling_engine import DoclingDocumentExtractionEngine
from memo_stack_adapters.extraction.image_evidence import parse_tesseract_tsv
from memo_stack_adapters.extraction.openai_vision import OpenAIVisionImageExtractionEngine
from memo_stack_adapters.extraction.transcription.openai_adapter import (
    OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES,
    OpenAISpeechTranscriptionAdapter,
)
from memo_stack_adapters.extraction.transcription_engine import SpeechTranscriptionExtractionEngine
from memo_stack_adapters.extraction.whisper_engine import FasterWhisperTranscriptionEngine
from memo_stack_core.ports.extraction import (
    ExtractedElement,
    ExtractionLimits,
    ExtractionRequest,
    ExtractionResult,
    FileTypeDetectionRequest,
)
from memo_stack_core.ports.transcription import SpeechTranscriptionRequest


def test_file_type_detector_prefers_office_extension_over_zip_magic() -> None:
    result = asyncio.run(
        SimpleFileTypeDetector().detect(
            FileTypeDetectionRequest(
                filename="meeting-notes.docx",
                declared_content_type="application/octet-stream",
                content=b"PK\x03\x04fake office zip",
            )
        )
    )

    assert (
        result.content_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_tesseract_tsv_parser_groups_words_into_ocr_blocks() -> None:
    regions = parse_tesseract_tsv(
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t10\t20\t40\t10\t92\tMemory\n"
        "5\t1\t1\t1\t1\t2\t55\t20\t30\t10\t88\tScope\n"
        "5\t1\t1\t1\t2\t1\t10\t40\t45\t12\t95\tFrontend\n"
    )

    assert [region.text for region in regions] == ["Memory Scope", "Frontend"]
    assert regions[0].bbox == (10.0, 20.0, 85.0, 30.0)
    assert regions[0].confidence == 0.9
    assert regions[0].metadata["source"] == "tesseract_cli"


def test_docling_engine_extracts_markdown_when_profile_requests_docling() -> None:
    engine = DoclingDocumentExtractionEngine(converter_factory=lambda: _FakeDoclingConverter())
    request = _request(
        parser_profile="standard_docling",
        detected_content_type="application/pdf",
        content=b"%PDF fake bytes",
    )

    supported = asyncio.run(engine.supports(request))
    result = asyncio.run(engine.extract(request))

    assert supported.supported is True
    assert result.status == "succeeded"
    assert result.parser_name == "docling_document"
    assert "Docling extracted memory scope table" in (result.markdown or "")
    assert result.technical_metadata["page_count"] == 2
    assert result.technical_metadata["docling_element_strategy"] == "docling_items"
    assert result.technical_metadata["docling_element_count"] == 3
    assert result.technical_metadata["docling_table_count"] == 1
    assert result.technical_metadata["docling_bbox_ref_count"] == 2
    assert result.elements[0].kind == "section_heading"
    assert result.elements[0].page_number == 1
    assert result.elements[1].kind == "table"
    assert result.elements[1].bbox == (10.0, 20.0, 300.0, 180.0)
    assert {artifact.artifact_type for artifact in result.artifacts} == {
        "normalized_json",
        "table_html",
    }


def test_docling_engine_ignores_standard_local_profile() -> None:
    engine = DoclingDocumentExtractionEngine(converter_factory=lambda: _FakeDoclingConverter())
    request = _request(
        parser_profile="standard_local",
        detected_content_type="application/pdf",
        content=b"%PDF fake bytes",
    )

    supported = asyncio.run(engine.supports(request))

    assert supported.supported is False
    assert supported.reason == "parser_profile_not_docling"


def test_docling_engine_timeout_returns_safe_unsupported_result() -> None:
    engine = DoclingDocumentExtractionEngine(converter_factory=lambda: _SlowDoclingConverter())
    request = _request(
        parser_profile="standard_docling",
        detected_content_type="application/pdf",
        content=b"%PDF slow fake bytes",
        parser_timeout_seconds=0.001,
    )

    result = asyncio.run(engine.extract(request))

    assert result.status == "unsupported"
    assert result.safe_error_code == "asset_extraction.docling_timeout"
    assert result.technical_metadata["parser_timeout_seconds"] == 0.001


def test_router_falls_back_from_docling_failure_to_pdf_text() -> None:
    router = StandardExtractionRouter(
        engines=(
            DoclingDocumentExtractionEngine(converter_factory=lambda: _FailingDoclingConverter()),
            PdfTextExtractionEngine(),
        )
    )
    request = _request(
        parser_profile="standard_docling",
        detected_content_type="application/pdf",
        content=_sample_pdf_bytes("PDF fallback preserved searchable memory scope evidence"),
    )

    result = asyncio.run(router.extract(request))

    assert result.status == "succeeded"
    assert result.parser_name == "pypdf_text"
    assert result.diagnostics["docling_document_fallback"] is True
    assert "PDF fallback preserved searchable memory scope evidence" in (result.markdown or "")


def test_openai_vision_engine_extracts_image_understanding() -> None:
    engine = OpenAIVisionImageExtractionEngine(
        api_key=None,
        model="gpt-4.1-mini",
        detail="high",
        client_factory=lambda: _FakeVisionClient(),
    )
    request = _request(
        parser_profile="standard_vision",
        detected_content_type="image/png",
        content=_sample_png_bytes(),
        filename="memory-screenshot.png",
        enable_external_ai=True,
    )

    supported = asyncio.run(engine.supports(request))
    result = asyncio.run(engine.extract(request))

    assert supported.supported is True
    assert result.status == "succeeded"
    assert result.parser_name == "openai_vision_image"
    assert result.model_version == "gpt-4.1-mini"
    assert result.technical_metadata["vision_status"] == "extracted"
    assert result.technical_metadata["image_width"] == 1
    assert result.technical_metadata["image_height"] == 1
    assert result.technical_metadata["vision_prompt_policy"] == ("image_text_is_untrusted_evidence")
    assert result.technical_metadata["vision_json_status"] == "parsed"
    assert result.technical_metadata["vision_region_count"] == 1
    assert result.elements[0].bbox == (0.0, 0.0, 1.0, 1.0)
    assert result.elements[0].kind == "screenshot_ui_summary"
    assert result.elements[1].kind == "visible_text"
    assert {artifact.artifact_type for artifact in result.artifacts} == {
        "image_regions",
        "vision_json",
    }
    assert "Quick capture links this screenshot to MemoryScope frontend" in (result.markdown or "")


def test_openai_vision_engine_ignores_standard_local_profile() -> None:
    engine = OpenAIVisionImageExtractionEngine(
        api_key=None,
        model="gpt-4.1-mini",
        client_factory=lambda: _FakeVisionClient(),
    )
    request = _request(
        parser_profile="standard_local",
        detected_content_type="image/png",
        content=_sample_png_bytes(),
        filename="memory-screenshot.png",
        enable_external_ai=True,
    )

    supported = asyncio.run(engine.supports(request))

    assert supported.supported is False
    assert supported.reason == "parser_profile_not_vision"


def test_openai_vision_engine_disabled_egress_allows_local_image_fallback() -> None:
    router = StandardExtractionRouter(
        engines=(
            OpenAIVisionImageExtractionEngine(
                api_key="test-key",
                model="gpt-4.1-mini",
                client_factory=lambda: _FakeVisionClient(),
            ),
            ImageMetadataExtractionEngine(),
        )
    )
    request = _request(
        parser_profile="standard_vision",
        detected_content_type="image/png",
        content=_sample_png_bytes(),
        filename="memory-screenshot.png",
        enable_external_ai=False,
    )

    result = asyncio.run(router.extract(request))

    assert result.status == "succeeded"
    assert result.parser_name == "image_metadata"
    assert result.diagnostics["openai_vision_image_fallback"] is True
    assert result.technical_metadata["image_width"] == 1
    assert result.technical_metadata["image_height"] == 1


def test_openai_vision_engine_missing_key_allows_fallback() -> None:
    engine = OpenAIVisionImageExtractionEngine(
        api_key=None,
        model="gpt-4.1-mini",
        client_factory=None,
    )
    request = _request(
        parser_profile="standard_vision",
        detected_content_type="image/png",
        content=_sample_png_bytes(),
        filename="memory-screenshot.png",
        enable_external_ai=True,
    )

    result = asyncio.run(engine.extract(request))

    assert result.status == "unsupported"
    assert result.safe_error_code == "asset_extraction.vision_missing_api_key"
    assert result.diagnostics["fallback_allowed"] is True


def test_openai_vision_engine_rejects_image_over_pixel_limit() -> None:
    engine = OpenAIVisionImageExtractionEngine(
        api_key=None,
        model="gpt-4.1-mini",
        client_factory=lambda: _FakeVisionClient(),
    )
    request = _request(
        parser_profile="standard_vision",
        detected_content_type="image/png",
        content=_sample_png_bytes(),
        filename="memory-screenshot.png",
        enable_external_ai=True,
        max_image_pixels=0,
    )

    result = asyncio.run(engine.extract(request))

    assert result.status == "unsupported"
    assert result.safe_error_code == "asset_extraction.vision_image_too_large"
    assert result.technical_metadata["max_image_pixels"] == 0


def test_local_image_engine_rejects_image_over_pixel_limit() -> None:
    engine = ImageMetadataExtractionEngine()
    request = _request(
        parser_profile="standard_local",
        detected_content_type="image/png",
        content=_sample_png_bytes(),
        filename="memory-screenshot.png",
        max_image_pixels=0,
    )

    result = asyncio.run(engine.extract(request))

    assert result.status == "unsupported"
    assert result.safe_error_code == "asset_extraction.image_too_large"
    assert result.technical_metadata["max_image_pixels"] == 0


def test_openai_speech_transcription_adapter_transcribes_audio() -> None:
    adapter = OpenAISpeechTranscriptionAdapter(
        api_key=None,
        model="gpt-4o-mini-transcribe",
        client_factory=lambda: _FakeTranscriptionClient(),
    )

    result = asyncio.run(
        adapter.transcribe(
            SpeechTranscriptionRequest(
                job_id="extract_1",
                asset_id="asset_1",
                filename="voice-note.wav",
                content_type="audio/wav",
                byte_size=20,
                sha256_hex="0" * 64,
                content=b"RIFF0000WAVEfake wav bytes",
                max_output_chars=1000,
            )
        )
    )

    assert result.status == "succeeded"
    assert result.provider_name == "openai_transcription"
    assert result.provider_model == "gpt-4o-mini-transcribe"
    assert result.language == "en"
    assert result.duration_seconds == 4.0
    assert result.segments[0].start_ms == 0
    assert result.segments[0].end_ms == 2000
    assert "Alex discussed memory scopes" in result.text
    assert result.diagnostics["response_format"] == "json"


def test_openai_speech_transcription_adapter_rejects_provider_upload_over_limit() -> None:
    provider_called = False

    def client_factory() -> _FakeTranscriptionClient:
        nonlocal provider_called
        provider_called = True
        return _FakeTranscriptionClient()

    adapter = OpenAISpeechTranscriptionAdapter(
        api_key=None,
        model="gpt-4o-mini-transcribe",
        client_factory=client_factory,
        max_upload_bytes=10,
    )

    result = asyncio.run(
        adapter.transcribe(
            SpeechTranscriptionRequest(
                job_id="extract_1",
                asset_id="asset_1",
                filename="voice-note.wav",
                content_type="audio/wav",
                byte_size=11,
                sha256_hex="0" * 64,
                content=b"small test fixture",
                max_output_chars=1000,
            )
        )
    )

    assert provider_called is False
    assert result.status == "unsupported"
    assert result.safe_error_code == "asset_extraction.transcription_file_too_large"
    assert result.diagnostics == {
        "byte_size": 11,
        "max_provider_upload_bytes": 10,
    }


def test_openai_speech_transcription_adapter_requests_whisper_segment_timestamps() -> None:
    adapter = OpenAISpeechTranscriptionAdapter(
        api_key=None,
        model="whisper-1",
        client_factory=lambda: _FakeWhisperTranscriptionClient(),
    )

    result = asyncio.run(
        adapter.transcribe(
            SpeechTranscriptionRequest(
                job_id="extract_1",
                asset_id="asset_1",
                filename="voice-note.wav",
                content_type="audio/wav",
                byte_size=20,
                sha256_hex="0" * 64,
                content=b"RIFF0000WAVEfake wav bytes",
                max_output_chars=1000,
            )
        )
    )

    assert result.status == "succeeded"
    assert result.provider_model == "whisper-1"
    assert result.diagnostics["response_format"] == "verbose_json"
    assert result.diagnostics["timestamp_granularities"] == ["segment"]
    assert result.segments[0].start_ms == 0
    assert result.segments[0].end_ms == 3200
    assert result.words[0].word == "Alex"


def test_openai_speech_transcription_adapter_requests_diarized_json() -> None:
    adapter = OpenAISpeechTranscriptionAdapter(
        api_key=None,
        model="gpt-4o-transcribe-diarize",
        client_factory=lambda: _FakeDiarizedTranscriptionClient(),
        prompt="Should not be sent to diarize model",
    )

    result = asyncio.run(
        adapter.transcribe(
            SpeechTranscriptionRequest(
                job_id="extract_1",
                asset_id="asset_1",
                filename="call.mp3",
                content_type="audio/mpeg",
                byte_size=20,
                sha256_hex="0" * 64,
                content=b"fake mp3 bytes",
                max_output_chars=1000,
            )
        )
    )

    assert result.status == "succeeded"
    assert result.diagnostics["response_format"] == "diarized_json"
    assert result.diagnostics["chunking_strategy"] == "auto"
    assert result.segments[0].speaker == "agent"


def test_speech_transcription_engine_extracts_timecoded_transcript_artifact() -> None:
    engine = SpeechTranscriptionExtractionEngine(
        transcription=OpenAISpeechTranscriptionAdapter(
            api_key=None,
            model="gpt-4o-mini-transcribe",
            client_factory=lambda: _FakeTranscriptionClient(),
        )
    )
    request = _request(
        parser_profile="media_api",
        detected_content_type="audio/wav",
        content=b"RIFF0000WAVEfake wav bytes",
        filename="voice-note.wav",
        enable_external_ai=True,
    )

    supported = asyncio.run(engine.supports(request))
    result = asyncio.run(engine.extract(request))

    assert supported.supported is True
    assert result.status == "succeeded"
    assert result.parser_name == "speech_transcription"
    assert result.model_version == "gpt-4o-mini-transcribe"
    assert result.technical_metadata["transcript_status"] == "extracted"
    assert result.technical_metadata["transcription_provider"] == "openai_transcription"
    assert {artifact.artifact_type for artifact in result.artifacts} == {
        "media_manifest",
        "transcript",
        "transcript_json",
    }
    assert "00:00:00.000 --> 00:00:02.000" in (result.markdown or "")


def test_speech_transcription_engine_disabled_egress_falls_back_to_media_metadata() -> None:
    router = StandardExtractionRouter(
        engines=(
            SpeechTranscriptionExtractionEngine(
                transcription=OpenAISpeechTranscriptionAdapter(
                    api_key="test-key",
                    model="gpt-4o-mini-transcribe",
                    client_factory=lambda: _FakeTranscriptionClient(),
                )
            ),
            _FallbackMediaEngine(),
        )
    )
    request = _request(
        parser_profile="media_api",
        detected_content_type="audio/wav",
        content=b"RIFF0000WAVEfake wav bytes",
        filename="voice-note.wav",
        enable_external_ai=False,
    )

    result = asyncio.run(router.extract(request))

    assert result.status == "succeeded"
    assert result.parser_name == "fallback_media"
    assert result.diagnostics["speech_transcription_fallback"] is True


def test_speech_transcription_router_falls_back_when_provider_upload_is_too_large() -> None:
    provider_called = False

    def client_factory() -> _FakeTranscriptionClient:
        nonlocal provider_called
        provider_called = True
        return _FakeTranscriptionClient()

    router = StandardExtractionRouter(
        engines=(
            SpeechTranscriptionExtractionEngine(
                transcription=OpenAISpeechTranscriptionAdapter(
                    api_key=None,
                    model="gpt-4o-mini-transcribe",
                    client_factory=client_factory,
                )
            ),
            _FallbackMediaEngine(),
        )
    )
    request = _request(
        parser_profile="media_api",
        detected_content_type="audio/wav",
        content=b"RIFF0000WAVEsmall test fixture",
        filename="voice-note.wav",
        enable_external_ai=True,
        byte_size=OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES + 1,
    )

    result = asyncio.run(router.extract(request))

    assert provider_called is False
    assert result.status == "succeeded"
    assert result.parser_name == "fallback_media"
    assert result.diagnostics["speech_transcription_fallback"] is True
    assert result.diagnostics["speech_transcription_support"] is True


def test_faster_whisper_engine_extracts_transcript_artifact() -> None:
    engine = FasterWhisperTranscriptionEngine(
        model_factory=lambda model, device, compute_type: _FakeWhisperModel(
            model=model,
            device=device,
            compute_type=compute_type,
        )
    )
    request = _request(
        parser_profile="asr:tiny",
        detected_content_type="audio/wav",
        content=b"RIFF0000WAVEfake wav bytes",
        filename="voice-note.wav",
    )

    supported = asyncio.run(engine.supports(request))
    result = asyncio.run(engine.extract(request))

    assert supported.supported is True
    assert result.status == "succeeded"
    assert result.parser_name == "faster_whisper_transcript"
    assert result.model_version == "tiny"
    assert result.language == "en"
    assert result.technical_metadata["segment_count"] == 2
    assert result.technical_metadata["asr_model"] == "tiny"
    assert {artifact.artifact_type for artifact in result.artifacts} == {
        "media_manifest",
        "transcript",
        "transcript_json",
    }
    assert "Alex discussed memory scopes" in (result.markdown or "")


def test_faster_whisper_engine_ignores_standard_local_profile() -> None:
    engine = FasterWhisperTranscriptionEngine(
        model_factory=lambda model, device, compute_type: _FakeWhisperModel(
            model=model,
            device=device,
            compute_type=compute_type,
        )
    )
    request = _request(
        parser_profile="standard_local",
        detected_content_type="audio/wav",
        content=b"RIFF0000WAVEfake wav bytes",
        filename="voice-note.wav",
    )

    supported = asyncio.run(engine.supports(request))

    assert supported.supported is False
    assert supported.reason == "parser_profile_not_asr"


def test_faster_whisper_engine_ignores_standard_full_profile() -> None:
    engine = FasterWhisperTranscriptionEngine(
        model_factory=lambda model, device, compute_type: _FakeWhisperModel(
            model=model,
            device=device,
            compute_type=compute_type,
        )
    )
    request = _request(
        parser_profile="standard_full",
        detected_content_type="audio/wav",
        content=b"RIFF0000WAVEfake wav bytes",
        filename="voice-note.wav",
    )

    supported = asyncio.run(engine.supports(request))

    assert supported.supported is False
    assert supported.reason == "parser_profile_not_asr"


def test_faster_whisper_engine_failure_allows_media_metadata_fallback() -> None:
    engine = FasterWhisperTranscriptionEngine(
        model_factory=lambda model, device, compute_type: _FailingWhisperModel()
    )
    request = _request(
        parser_profile="media_local_asr",
        detected_content_type="audio/wav",
        content=b"RIFF0000WAVEfake wav bytes",
        filename="voice-note.wav",
    )

    result = asyncio.run(engine.extract(request))

    assert result.status == "unsupported"
    assert result.safe_error_code == "asset_extraction.asr_transcription_failed"
    assert result.diagnostics["fallback_allowed"] is True


def _request(
    *,
    parser_profile: str,
    detected_content_type: str,
    content: bytes,
    filename: str = "asset.pdf",
    enable_external_ai: bool = False,
    parser_timeout_seconds: float = 300,
    subprocess_timeout_seconds: int = 60,
    max_image_pixels: int = 50_000_000,
    byte_size: int | None = None,
) -> ExtractionRequest:
    return ExtractionRequest(
        job_id="extract_1",
        asset_id="asset_1",
        filename=filename,
        declared_content_type=detected_content_type,
        detected_content_type=detected_content_type,
        byte_size=byte_size or len(content),
        sha256_hex="0" * 64,
        content=content,
        parser_profile=parser_profile,
        limits=ExtractionLimits(
            max_bytes=10_000_000,
            parser_timeout_seconds=parser_timeout_seconds,
            subprocess_timeout_seconds=subprocess_timeout_seconds,
            max_image_pixels=max_image_pixels,
            enable_external_ai=enable_external_ai,
        ),
    )


@dataclass(frozen=True)
class _FakeDoclingConversion:
    document: "_FakeDoclingDocument"
    status: str = "success"
    page_count: int = 2
    errors: list[object] | None = None


class _FakeDoclingDocument:
    elements = (
        {
            "kind": "heading",
            "text": "Docling extracted memory scope table",
            "page_number": 1,
        },
        {
            "kind": "table",
            "text": "| Scope | Evidence |\n| --- | --- |\n| frontend | screenshot |",
            "prov": [
                {
                    "page_no": 1,
                    "bbox": (10, 20, 300, 180),
                }
            ],
        },
        {
            "kind": "text",
            "text": "Memory scopes keep uploaded evidence linked to the right thread.",
            "prov": [
                {
                    "page_no": 2,
                    "bbox": (20, 40, 320, 100),
                }
            ],
        },
    )

    def export_to_markdown(self) -> str:
        return "# Docling extracted memory scope table\n\n| Scope | Evidence |\n| --- | --- |"

    def export_to_dict(self, **kwargs) -> dict[str, object]:
        assert kwargs["mode"] == "json"
        return {"schema_name": "DoclingDocument", "texts": ["memory scope"]}


class _FakeDoclingConverter:
    def convert(self, source_path: str, **kwargs) -> _FakeDoclingConversion:
        assert source_path.endswith(".pdf")
        assert kwargs["max_num_pages"] == 100
        assert kwargs["max_file_size"] == 10_000_000
        return _FakeDoclingConversion(document=_FakeDoclingDocument(), errors=[])


class _FailingDoclingConverter:
    def convert(self, source_path: str) -> object:
        raise RuntimeError("docling failed")


class _SlowDoclingConverter:
    def convert(self, source_path: str, **kwargs) -> object:
        time.sleep(0.05)
        return _FakeDoclingConversion(document=_FakeDoclingDocument(), errors=[])


@dataclass(frozen=True)
class _FakeVisionResponse:
    output_text: str


class _FakeVisionResponses:
    async def create(self, **kwargs) -> _FakeVisionResponse:
        assert kwargs["model"] == "gpt-4.1-mini"
        assert kwargs["store"] is False
        assert kwargs["max_output_tokens"] == 1200
        assert kwargs["text"]["format"]["type"] == "json_schema"
        assert kwargs["text"]["format"]["strict"] is True
        content = kwargs["input"][0]["content"]
        assert content[0]["type"] == "input_text"
        assert "untrusted evidence" in content[0]["text"]
        assert content[1]["type"] == "input_image"
        assert content[1]["detail"] == "high"
        assert content[1]["image_url"].startswith("data:image/png;base64,")
        return _FakeVisionResponse(
            output_text=(
                '{"summary":"Quick capture links this screenshot to MemoryScope frontend.",'
                '"visible_text":["MemoryScope frontend"],'
                '"screenshot_ui_summary":"A compact quick-capture UI is visible.",'
                '"suggested_tags":["frontend","screenshot"],'
                '"regions":[{"kind":"visible_text","text":"MemoryScope frontend",'
                '"bbox":[0,0,1,1],"confidence":0.91}]}'
            )
        )


class _FakeVisionClient:
    def __init__(self) -> None:
        self.responses = _FakeVisionResponses()
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@dataclass(frozen=True)
class _FakeTranscriptionResponse:
    text: str
    language: str = "en"
    duration: float = 4.0
    segments: list[dict[str, object]] | None = None
    words: list[dict[str, object]] | None = None


class _FakeAudioTranscriptions:
    async def create(self, **kwargs) -> _FakeTranscriptionResponse:
        assert kwargs["model"] == "gpt-4o-mini-transcribe"
        assert kwargs["response_format"] == "json"
        assert kwargs["file"].name == "voice-note.wav"
        return _FakeTranscriptionResponse(
            text=("Alex discussed memory scopes. The file should link to existing evidence."),
            segments=[
                {
                    "start": 0.0,
                    "end": 2.0,
                    "text": "Alex discussed memory scopes.",
                },
                {
                    "start": 2.5,
                    "end": 4.0,
                    "text": "The file should link to existing evidence.",
                },
            ],
        )


class _FakeWhisperAudioTranscriptions:
    async def create(self, **kwargs) -> _FakeTranscriptionResponse:
        assert kwargs["model"] == "whisper-1"
        assert kwargs["response_format"] == "verbose_json"
        assert kwargs["timestamp_granularities"] == ["segment"]
        assert kwargs["file"].name == "voice-note.wav"
        response = _FakeTranscriptionResponse(
            text="Alex discussed memory scopes.",
            duration=3.2,
            segments=[
                {
                    "id": 0,
                    "start": 0.0,
                    "end": 3.2,
                    "text": "Alex discussed memory scopes.",
                    "avg_logprob": -0.2,
                }
            ],
            words=[
                {"word": "Alex", "start": 0.0, "end": 0.4},
                {"word": "discussed", "start": 0.4, "end": 1.2},
            ],
        )
        return response


class _FakeDiarizedAudioTranscriptions:
    async def create(self, **kwargs) -> _FakeTranscriptionResponse:
        assert kwargs["model"] == "gpt-4o-transcribe-diarize"
        assert kwargs["response_format"] == "diarized_json"
        assert kwargs["chunking_strategy"] == "auto"
        assert "prompt" not in kwargs
        assert kwargs["file"].name == "call.mp3"
        return _FakeTranscriptionResponse(
            text="Agent: Memory scopes are ready.",
            duration=2.0,
            segments=[
                {
                    "type": "transcript.text.segment",
                    "id": "seg_001",
                    "start": 0.0,
                    "end": 2.0,
                    "text": "Memory scopes are ready.",
                    "speaker": "agent",
                }
            ],
        )


class _FakeAudioClient:
    def __init__(self, transcriptions=None) -> None:
        self.transcriptions = transcriptions or _FakeAudioTranscriptions()


class _FakeTranscriptionClient:
    def __init__(self, transcriptions=None) -> None:
        self.audio = _FakeAudioClient(transcriptions=transcriptions)
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeWhisperTranscriptionClient(_FakeTranscriptionClient):
    def __init__(self) -> None:
        super().__init__(transcriptions=_FakeWhisperAudioTranscriptions())


class _FakeDiarizedTranscriptionClient(_FakeTranscriptionClient):
    def __init__(self) -> None:
        super().__init__(transcriptions=_FakeDiarizedAudioTranscriptions())


class _FallbackMediaEngine(ExtractionEngine):
    name = "fallback_media"

    async def supports(self, request: ExtractionRequest) -> SupportDecision:
        return SupportDecision(request.detected_content_type.startswith(("audio/", "video/")))

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        return ExtractionResult(
            status="succeeded",
            normalized_content_type=request.detected_content_type,
            title=request.filename,
            markdown="Media metadata fallback",
            elements=(
                ExtractedElement(
                    kind="media_metadata",
                    text="Media metadata fallback",
                    metadata={"source": self.name},
                ),
            ),
            technical_metadata={"transcript_status": "not_configured"},
            parser_name=self.name,
            parser_version="test",
        )


@dataclass(frozen=True)
class _FakeWhisperInfo:
    language: str = "en"
    language_probability: float = 0.98
    duration: float = 5.0


@dataclass(frozen=True)
class _FakeWhisperSegment:
    start: float
    end: float
    text: str
    avg_logprob: float = -0.05


class _FakeWhisperModel:
    def __init__(self, *, model: str, device: str, compute_type: str) -> None:
        self._model = model
        self._device = device
        self._compute_type = compute_type

    def transcribe(self, source_path: str) -> tuple[list[_FakeWhisperSegment], _FakeWhisperInfo]:
        assert source_path.endswith(".wav")
        assert self._model == "tiny"
        assert self._device == "auto"
        assert self._compute_type == "default"
        return (
            [
                _FakeWhisperSegment(
                    start=0.0,
                    end=2.0,
                    text="Alex discussed memory scopes.",
                ),
                _FakeWhisperSegment(
                    start=2.5,
                    end=4.0,
                    text="The file should link to existing evidence.",
                ),
            ],
            _FakeWhisperInfo(),
        )


class _FailingWhisperModel:
    def transcribe(self, source_path: str) -> object:
        raise RuntimeError("asr failed")


def _sample_pdf_bytes(text: str) -> bytes:
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
        + f"5 0 obj << /Length {len(stream)} >> stream\n".encode("ascii")
        + stream
        + b"\nendstream endobj\nxref\n0 6\n0000000000 65535 f \n"
        b"0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"0000000241 00000 n \n0000000311 00000 n \n"
        b"trailer << /Root 1 0 R /Size 6 >>\nstartxref\n449\n%%EOF\n"
    )


def _sample_png_bytes() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
