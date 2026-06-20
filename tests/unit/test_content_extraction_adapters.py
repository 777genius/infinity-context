import asyncio
import base64
import json
import subprocess
import time
from dataclasses import dataclass

import pytest
from infinity_context_adapters.extraction import media_tools
from infinity_context_adapters.extraction import (
    transcription_engine as transcription_engine_module,
)
from infinity_context_adapters.extraction.content import (
    ExtractionEngine,
    ImageMetadataExtractionEngine,
    PdfTextExtractionEngine,
    SimpleFileTypeDetector,
    StandardExtractionRouter,
    SupportDecision,
)
from infinity_context_adapters.extraction.docling_engine import DoclingDocumentExtractionEngine
from infinity_context_adapters.extraction.image_evidence import parse_tesseract_tsv
from infinity_context_adapters.extraction.openai_vision import OpenAIVisionImageExtractionEngine
from infinity_context_adapters.extraction.transcription.openai_adapter import (
    OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES,
    OpenAISpeechTranscriptionAdapter,
)
from infinity_context_adapters.extraction.transcription_engine import (
    SpeechTranscriptionExtractionEngine,
)
from infinity_context_adapters.extraction.whisper_engine import FasterWhisperTranscriptionEngine
from infinity_context_core.ports.extraction import (
    ExtractedElement,
    ExtractionLimits,
    ExtractionRequest,
    ExtractionResult,
    FileTypeDetectionRequest,
)
from infinity_context_core.ports.transcription import (
    SpeechTranscriptionRequest,
    SpeechTranscriptionResult,
    SpeechTranscriptSegment,
    SpeechTranscriptWord,
)


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
    assert result.diagnostics["mime_detector_reason"] == "extension_overrides_zip_magic"
    assert result.diagnostics["mime_archive_detected"] is True
    assert result.diagnostics["mime_archive_review_required"] is False


def test_file_type_detector_marks_raw_zip_archive_for_review() -> None:
    result = asyncio.run(
        SimpleFileTypeDetector().detect(
            FileTypeDetectionRequest(
                filename="payload.zip",
                declared_content_type="application/zip",
                content=b"PK\x03\x04fake archive",
            )
        )
    )

    assert result.content_type == "application/zip"
    assert result.diagnostics["mime_magic_content_type"] == "application/zip"
    assert result.diagnostics["mime_archive_detected"] is True
    assert result.diagnostics["mime_archive_review_required"] is True
    assert result.diagnostics["mime_archive_review_reason"] == "zip_archive_not_structured_document"


def test_file_type_detector_prefers_text_magic_over_spoofed_image_metadata() -> None:
    result = asyncio.run(
        SimpleFileTypeDetector().detect(
            FileTypeDetectionRequest(
                filename="screenshot.png",
                declared_content_type="image/png",
                content=b"This is actually a plain text note, not a png.",
            )
        )
    )

    assert result.content_type == "text/plain"
    assert result.confidence == "high"
    assert result.diagnostics["mime_declared_content_type"] == "image/png"
    assert result.diagnostics["mime_extension_content_type"] == "image/png"
    assert result.diagnostics["mime_magic_content_type"] == "text/plain"
    assert result.diagnostics["mime_content_type_mismatch"] is True
    assert result.diagnostics["mime_extension_mismatch"] is True
    assert result.diagnostics["mime_detector_reason"] == "magic"


def test_file_type_detector_keeps_textual_subtype_for_plain_text_magic() -> None:
    result = asyncio.run(
        SimpleFileTypeDetector().detect(
            FileTypeDetectionRequest(
                filename="capture.md",
                declared_content_type="application/octet-stream",
                content=b"# Memory Scope\n\nQuick capture note.",
            )
        )
    )

    assert result.content_type == "text/markdown"
    assert result.diagnostics["mime_detector_reason"] == "extension_overrides_magic"


def test_file_type_detector_recognizes_modern_multimodal_magic_types() -> None:
    cases = [
        ("image.webp", "application/octet-stream", b"RIFF\x10\x00\x00\x00WEBPVP8 ", "image/webp"),
        ("voice.flac", "application/octet-stream", b"fLaC\x00\x00\x00\x22", "audio/flac"),
        ("voice.ogg", "application/octet-stream", b"OggS\x00\x02audio", "audio/ogg"),
        (
            "voice.m4a",
            "application/octet-stream",
            b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00",
            "audio/mp4",
        ),
        (
            "clip.mov",
            "application/octet-stream",
            b"\x00\x00\x00\x18ftypqt  \x00\x00\x00\x00",
            "video/quicktime",
        ),
        (
            "screen.avif",
            "application/octet-stream",
            b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00",
            "image/avif",
        ),
        (
            "screen.heic",
            "application/octet-stream",
            b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00",
            "image/heic",
        ),
        ("clip.webm", "application/octet-stream", b"\x1a\x45\xdf\xa3\x00\x00webm", "video/webm"),
    ]

    for filename, declared_content_type, content, expected_content_type in cases:
        result = asyncio.run(
            SimpleFileTypeDetector().detect(
                FileTypeDetectionRequest(
                    filename=filename,
                    declared_content_type=declared_content_type,
                    content=content,
                )
            )
        )

        assert result.content_type == expected_content_type
        assert result.confidence == "high"
        assert result.diagnostics["mime_detector_reason"] == "magic"


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


def test_docling_engine_bounds_large_element_evidence() -> None:
    engine = DoclingDocumentExtractionEngine(converter_factory=lambda: _HugeDoclingConverter())
    request = _request(
        parser_profile="standard_docling",
        detected_content_type="application/pdf",
        content=b"%PDF fake bytes",
        max_output_chars=128,
    )

    result = asyncio.run(engine.extract(request))

    assert result.status == "succeeded"
    assert result.markdown == "short docling markdown"
    assert len(result.elements) == 1
    assert sum(len(element.text) for element in result.elements) == 128
    assert result.technical_metadata["docling_element_count_total"] == 600
    assert result.technical_metadata["docling_elements_truncated"] is True
    assert result.technical_metadata["docling_element_text_truncated_count"] == 1
    assert result.technical_metadata["docling_element_text_chars"] == 128


def test_docling_engine_bounds_table_html_artifact() -> None:
    engine = DoclingDocumentExtractionEngine(converter_factory=lambda: _HugeTableDoclingConverter())
    request = _request(
        parser_profile="standard_docling",
        detected_content_type="application/pdf",
        content=b"%PDF fake bytes",
        max_output_chars=2_048,
    )

    result = asyncio.run(engine.extract(request))

    table_artifact = next(item for item in result.artifacts if item.artifact_type == "table_html")
    assert len(table_artifact.content.decode("utf-8")) == 2_048
    assert table_artifact.metadata["table_html_truncated"] is True
    assert table_artifact.metadata["table_html_char_limit"] == 2_048


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


def test_standard_router_rejects_files_over_extraction_byte_limit() -> None:
    engine = _CountingExtractionEngine()
    router = StandardExtractionRouter((engine,))
    request = _request(
        parser_profile="standard_local",
        detected_content_type="text/plain",
        content=b"large text payload",
        filename="large.txt",
        max_bytes=4,
    )

    result = asyncio.run(router.extract(request))

    assert result.status == "unsupported"
    assert result.safe_error_code == "asset_extraction.file_too_large"
    assert result.safe_error_message == "Asset exceeds configured extraction size limit"
    assert result.technical_metadata["byte_size"] == len(b"large text payload")
    assert result.technical_metadata["max_bytes"] == 4
    assert result.diagnostics["reason"] == "file_too_large"
    assert engine.support_calls == 0
    assert engine.extract_calls == 0


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


def test_openai_vision_engine_bounds_provider_payload_before_artifacts() -> None:
    engine = OpenAIVisionImageExtractionEngine(
        api_key=None,
        model="gpt-4.1-mini",
        detail="high",
        client_factory=lambda: _LargeVisionClient(),
    )
    request = _request(
        parser_profile="standard_vision",
        detected_content_type="image/png",
        content=_sample_png_bytes(),
        filename="memory-screenshot.png",
        enable_external_ai=True,
    )

    result = asyncio.run(engine.extract(request))

    assert result.status == "succeeded"
    assert result.technical_metadata["visible_text_count"] == 50
    assert result.technical_metadata["suggested_tag_count"] == 20
    assert result.technical_metadata["vision_region_count"] == 50
    assert result.technical_metadata["screenshot_ui_summary_chars"] == 4000
    assert result.diagnostics["payload_bounded"] is True
    vision_json = next(
        artifact for artifact in result.artifacts if artifact.artifact_type == "vision_json"
    )
    payload = json.loads(vision_json.content.decode("utf-8"))
    assert len(payload["summary"]) == 4000
    assert len(payload["visible_text"]) == 50
    assert all(len(item) == 1000 for item in payload["visible_text"])
    assert len(payload["suggested_tags"]) == 20
    assert all(len(item) == 80 for item in payload["suggested_tags"])
    assert len(payload["regions"]) == 50
    assert all(len(item["text"]) == 1000 for item in payload["regions"])


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
    assert result.technical_metadata["transcript_features"] == ["segments", "time_ranges"]
    assert result.technical_metadata["has_time_ranges"] is True
    assert result.technical_metadata["has_speaker_labels"] is False
    assert result.technical_metadata["has_word_timestamps"] is False
    assert {artifact.artifact_type for artifact in result.artifacts} == {
        "media_manifest",
        "transcript",
        "transcript_json",
    }
    transcript_json = next(
        artifact for artifact in result.artifacts if artifact.artifact_type == "transcript_json"
    )
    payload = json.loads(transcript_json.content.decode("utf-8"))
    assert payload["features"] == {
        "transcript_features": ["segments", "time_ranges"],
        "transcript_feature_names": "segments,time_ranges",
        "has_time_ranges": True,
        "has_speaker_labels": False,
        "has_word_timestamps": False,
        "segments_truncated": False,
        "words_truncated": False,
    }
    assert "00:00:00.000 --> 00:00:02.000" in (result.markdown or "")


def test_speech_transcription_engine_bounds_transcript_manifest_payload() -> None:
    engine = SpeechTranscriptionExtractionEngine(transcription=_LargeTranscriptPort())
    request = _request(
        parser_profile="media_api",
        detected_content_type="audio/wav",
        content=b"RIFF0000WAVEfake wav bytes",
        filename="voice-note.wav",
        enable_external_ai=True,
        max_output_chars=80,
    )

    result = asyncio.run(engine.extract(request))

    assert result.status == "succeeded"
    assert result.technical_metadata["segments_truncated"] is True
    assert result.technical_metadata["transcript_words_truncated"] is True
    assert result.technical_metadata["segment_count"] == 1
    assert result.technical_metadata["transcript_word_count"] == 1
    transcript_json = next(
        artifact for artifact in result.artifacts if artifact.artifact_type == "transcript_json"
    )
    payload = json.loads(transcript_json.content.decode("utf-8"))
    assert payload["features"]["segments_truncated"] is True
    assert payload["features"]["words_truncated"] is True
    assert payload["text"] == "A" * 80
    assert len(payload["segments"]) == 1
    assert payload["segments"][0]["text"] == "S" * 80
    assert payload["words"][0]["word"] == "W" * 200
    assert "TAIL" not in transcript_json.content.decode("utf-8")


def test_speech_transcription_engine_marks_diarized_transcript_features() -> None:
    engine = SpeechTranscriptionExtractionEngine(
        transcription=OpenAISpeechTranscriptionAdapter(
            api_key=None,
            model="gpt-4o-transcribe-diarize",
            client_factory=lambda: _FakeDiarizedTranscriptionClient(),
        )
    )
    request = _request(
        parser_profile="media_api",
        detected_content_type="audio/mpeg",
        content=b"fake mp3 bytes",
        filename="call.mp3",
        enable_external_ai=True,
    )

    result = asyncio.run(engine.extract(request))

    assert result.status == "succeeded"
    assert result.technical_metadata["transcript_features"] == [
        "segments",
        "time_ranges",
        "speaker_labels",
    ]
    assert result.technical_metadata["transcript_feature_names"] == (
        "segments,time_ranges,speaker_labels"
    )
    assert result.technical_metadata["has_speaker_labels"] is True
    assert result.technical_metadata["has_word_timestamps"] is False
    transcript_json = next(
        artifact for artifact in result.artifacts if artifact.artifact_type == "transcript_json"
    )
    payload = json.loads(transcript_json.content.decode("utf-8"))
    assert payload["features"]["has_speaker_labels"] is True
    assert payload["segments"][0]["speaker"] == "agent"


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

    assert result.parser_name == "fallback_media"
    assert result.diagnostics["speech_transcription_fallback"] is True
    metadata = result.technical_metadata
    assert metadata["transcript_status"] == "disabled"
    assert metadata["transcript_error_code"].endswith("transcription_external_ai_disabled")


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
        max_bytes=OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES + 2,
    )

    result = asyncio.run(router.extract(request))

    assert provider_called is False
    assert result.parser_name == "fallback_media"
    assert result.diagnostics["speech_transcription_fallback"] is True
    assert result.diagnostics["speech_transcription_support"] is True
    metadata = result.technical_metadata
    assert metadata["transcript_status"] == "skipped"
    assert metadata["transcript_error_code"] == "asset_extraction.transcription_file_too_large"


def test_media_probe_timeout_metadata_is_bounded_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        args: list[str],
        *,
        request: ExtractionRequest,
    ) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(
            cmd=args,
            timeout=request.limits.subprocess_timeout_seconds,
            output=b"stdout sk-proj-timeoutsecretvalue123456",
            stderr=b"stderr Bearer timeoutsecretvalue123456",
        )

    monkeypatch.setattr(media_tools.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(media_tools, "_run_media_subprocess", fake_run)
    request = _request(
        parser_profile="media_api",
        detected_content_type="video/mp4",
        content=b"\x00\x00\x00\x18ftypmp42fake video bytes",
        filename="timeout-video.mp4",
        subprocess_timeout_seconds=1,
    )

    result = media_tools.probe_media_with_ffprobe(request)

    assert result.status == "failed"
    assert result.metadata is not None
    assert result.metadata["probe_status"] == "timeout"
    assert result.metadata["probe_failure_reason"] == "subprocess_timeout"
    assert result.metadata["probe_timed_out_after_seconds"] == 1
    assert result.metadata["protocol_whitelist"] == "file"
    payload = json.dumps(result.metadata, sort_keys=True)
    assert "sk-proj-" not in payload
    assert "Bearer timeout" not in payload
    assert "[redacted]" in payload


def test_video_transcription_skips_provider_when_probe_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcription = _CountingTranscriptionPort()
    engine = SpeechTranscriptionExtractionEngine(transcription=transcription)

    monkeypatch.setattr(
        transcription_engine_module,
        "probe_media_with_ffprobe",
        lambda request: media_tools.MediaProbeResult(
            status="failed",
            metadata={
                "probe_status": "timeout",
                "probe_failure_reason": "subprocess_timeout",
                "subprocess_timeout_seconds": 1,
            },
        ),
    )
    request = _request(
        parser_profile="media_api",
        detected_content_type="video/mp4",
        content=b"\x00\x00\x00\x18ftypmp42fake video bytes",
        filename="timeout-video.mp4",
        enable_external_ai=True,
        subprocess_timeout_seconds=1,
    )

    result = asyncio.run(engine.extract(request))

    assert transcription.called is False
    assert result.status == "unsupported"
    assert result.safe_error_code == "asset_extraction.transcription_media_probe_timeout"
    assert result.technical_metadata["probe_failure_reason"] == "subprocess_timeout"
    assert result.diagnostics["fallback_allowed"] is True


def test_standard_asr_provider_failure_does_not_fall_back_to_local_asr() -> None:
    local_asr_model_loaded = False

    def local_model_factory(model: str, device: str, compute_type: str) -> _FailingWhisperModel:
        nonlocal local_asr_model_loaded
        local_asr_model_loaded = True
        return _FailingWhisperModel()

    router = StandardExtractionRouter(
        engines=(
            SpeechTranscriptionExtractionEngine(
                transcription=OpenAISpeechTranscriptionAdapter(
                    api_key=None,
                    model="gpt-4o-mini-transcribe",
                    client_factory=lambda: _FakeTranscriptionClient(
                        transcriptions=_FailingAudioTranscriptions()
                    ),
                )
            ),
            FasterWhisperTranscriptionEngine(model_factory=local_model_factory),
            _FallbackMediaEngine(),
        )
    )
    request = _request(
        parser_profile="standard_asr",
        detected_content_type="audio/wav",
        content=b"RIFF0000WAVEfake wav bytes",
        filename="voice-note.wav",
        enable_external_ai=True,
    )

    result = asyncio.run(router.extract(request))

    assert result.parser_name == "fallback_media"
    assert local_asr_model_loaded is False
    assert result.diagnostics["speech_transcription_fallback"] is True
    assert result.diagnostics["faster_whisper_transcript_support"] is False
    assert result.diagnostics["faster_whisper_transcript_reason"] == "parser_profile_not_asr"
    assert result.technical_metadata["transcript_status"] == "failed"
    assert (
        result.technical_metadata["transcript_error_code"]
        == "asset_extraction.transcription_provider_error"
    )


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
    assert result.technical_metadata["transcript_features"] == ["segments", "time_ranges"]
    assert result.technical_metadata["has_time_ranges"] is True
    assert result.technical_metadata["has_speaker_labels"] is False
    assert result.technical_metadata["has_word_timestamps"] is False
    assert {artifact.artifact_type for artifact in result.artifacts} == {
        "media_manifest",
        "transcript",
        "transcript_json",
    }
    transcript_json = next(
        artifact for artifact in result.artifacts if artifact.artifact_type == "transcript_json"
    )
    payload = json.loads(transcript_json.content.decode("utf-8"))
    assert payload["features"] == {
        "transcript_features": ["segments", "time_ranges"],
        "transcript_feature_names": "segments,time_ranges",
        "has_time_ranges": True,
        "has_speaker_labels": False,
        "has_word_timestamps": False,
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
    max_bytes: int = 10_000_000,
    byte_size: int | None = None,
    max_output_chars: int = 500_000,
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
            max_bytes=max_bytes,
            parser_timeout_seconds=parser_timeout_seconds,
            subprocess_timeout_seconds=subprocess_timeout_seconds,
            max_image_pixels=max_image_pixels,
            max_output_chars=max_output_chars,
            enable_external_ai=enable_external_ai,
        ),
    )


class _CountingExtractionEngine(ExtractionEngine):
    name = "counting"

    def __init__(self) -> None:
        self.support_calls = 0
        self.extract_calls = 0

    async def supports(self, request: ExtractionRequest) -> SupportDecision:
        self.support_calls += 1
        return SupportDecision(True)

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        self.extract_calls += 1
        return ExtractionResult(
            status="succeeded",
            normalized_content_type=request.detected_content_type,
            title=request.filename,
            markdown="counting extraction",
            parser_name=self.name,
            parser_version="v1",
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


class _HugeDoclingDocument:
    elements = tuple(
        {"kind": "text", "text": f"oversized docling evidence {index} " + ("x" * 200)}
        for index in range(600)
    )

    def export_to_markdown(self) -> str:
        return "short docling markdown"

    def export_to_dict(self, **kwargs) -> dict[str, object]:
        return {"schema_name": "DoclingDocument", "bounded": True}


class _HugeTableItem:
    kind = "table"
    text = "| huge | table |"

    def export_to_markdown(self, **kwargs) -> str:
        return "| huge | table |\n| --- | --- |\n| value | value |"

    def export_to_html(self, **kwargs) -> str:
        return "<table>" + ("<tr><td>value</td></tr>" * 1_000) + "</table>"


class _HugeTableDoclingDocument:
    elements = (_HugeTableItem(),)

    def export_to_markdown(self) -> str:
        return "| huge | table |\n| --- | --- |\n| value | value |"

    def export_to_dict(self, **kwargs) -> dict[str, object]:
        return {"schema_name": "DoclingDocument", "table": "huge"}


class _FakeDoclingConverter:
    def convert(self, source_path: str, **kwargs) -> _FakeDoclingConversion:
        assert source_path.endswith(".pdf")
        assert kwargs["max_num_pages"] == 100
        assert kwargs["max_file_size"] == 10_000_000
        return _FakeDoclingConversion(document=_FakeDoclingDocument(), errors=[])


class _HugeDoclingConverter:
    def convert(self, source_path: str, **kwargs) -> _FakeDoclingConversion:
        return _FakeDoclingConversion(document=_HugeDoclingDocument(), errors=[])


class _HugeTableDoclingConverter:
    def convert(self, source_path: str, **kwargs) -> _FakeDoclingConversion:
        return _FakeDoclingConversion(document=_HugeTableDoclingDocument(), errors=[])


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


class _LargeVisionResponses:
    async def create(self, **kwargs) -> _FakeVisionResponse:
        long_text = "x" * 5000
        long_tag = "tag-" + ("x" * 120)
        payload = {
            "summary": long_text,
            "visible_text": [long_text for _ in range(80)],
            "screenshot_ui_summary": long_text,
            "suggested_tags": [long_tag for _ in range(40)],
            "regions": [
                {
                    "kind": "visible_text",
                    "text": long_text,
                    "bbox": [0, 0, 1, 1],
                    "confidence": 0.9,
                }
                for _ in range(80)
            ],
        }
        return _FakeVisionResponse(output_text=json.dumps(payload))


class _FakeVisionClient:
    def __init__(self, responses=None) -> None:
        self.responses = responses or _FakeVisionResponses()
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _LargeVisionClient(_FakeVisionClient):
    def __init__(self) -> None:
        super().__init__(responses=_LargeVisionResponses())


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


class _FailingAudioTranscriptions:
    async def create(self, **kwargs) -> object:
        raise RuntimeError("simulated transcription provider outage")


class _LargeTranscriptPort:
    async def transcribe(
        self,
        request: SpeechTranscriptionRequest,
    ) -> SpeechTranscriptionResult:
        assert request.max_output_chars == 80
        return SpeechTranscriptionResult(
            status="succeeded",
            text=("A" * 1000) + "TAIL",
            segments=(
                SpeechTranscriptSegment(
                    text=("S" * 5000) + "TAIL",
                    start_ms=0,
                    end_ms=1000,
                ),
                SpeechTranscriptSegment(
                    text="second segment must be omitted",
                    start_ms=1000,
                    end_ms=2000,
                ),
            ),
            words=(
                SpeechTranscriptWord(
                    word=("W" * 250) + "TAIL",
                    start_ms=0,
                    end_ms=100,
                ),
            ),
            language="en",
            duration_seconds=2.0,
            provider_name="test_transcription",
            provider_model="bounded-test",
        )


class _CountingTranscriptionPort:
    def __init__(self) -> None:
        self.called = False

    async def transcribe(
        self,
        request: SpeechTranscriptionRequest,
    ) -> SpeechTranscriptionResult:
        self.called = True
        return SpeechTranscriptionResult(
            status="succeeded",
            text="provider should not be called",
            provider_name="counting_transcription",
            provider_model="test",
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
