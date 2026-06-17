"""Factory helpers for the standard extraction router."""

from __future__ import annotations

from memo_stack_core.ports.extraction import ContentExtractionPort

from memo_stack_adapters.extraction.content import (
    ImageMetadataExtractionEngine,
    MediaMetadataExtractionEngine,
    PdfTextExtractionEngine,
    SimpleTextExtractionEngine,
    StandardExtractionRouter,
    TimedTextTranscriptExtractionEngine,
)
from memo_stack_adapters.extraction.docling_engine import DoclingDocumentExtractionEngine
from memo_stack_adapters.extraction.openai_vision import OpenAIVisionImageExtractionEngine
from memo_stack_adapters.extraction.transcription.openai_adapter import (
    OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES,
    OpenAISpeechTranscriptionAdapter,
)
from memo_stack_adapters.extraction.transcription_engine import (
    SpeechTranscriptionExtractionEngine,
)
from memo_stack_adapters.extraction.whisper_engine import FasterWhisperTranscriptionEngine


def build_standard_extractor(
    *,
    openai_api_key: str | None = None,
    vision_model: str = "gpt-4.1-mini",
    vision_detail: str = "high",
    transcription_provider: str = "openai",
    transcription_model: str = "gpt-4o-mini-transcribe",
    transcription_max_upload_bytes: int = OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES,
    asr_model: str = "base",
    asr_device: str = "auto",
    asr_compute_type: str = "default",
) -> ContentExtractionPort:
    speech_transcription = SpeechTranscriptionExtractionEngine(
        transcription=OpenAISpeechTranscriptionAdapter(
            api_key=openai_api_key if transcription_provider == "openai" else None,
            model=transcription_model,
            max_upload_bytes=transcription_max_upload_bytes,
        )
    )
    return StandardExtractionRouter(
        engines=(
            OpenAIVisionImageExtractionEngine(
                api_key=openai_api_key,
                model=vision_model,
                detail=vision_detail,
            ),
            DoclingDocumentExtractionEngine(),
            speech_transcription,
            FasterWhisperTranscriptionEngine(
                model_name=asr_model,
                device=asr_device,
                compute_type=asr_compute_type,
            ),
            TimedTextTranscriptExtractionEngine(),
            SimpleTextExtractionEngine(),
            PdfTextExtractionEngine(),
            ImageMetadataExtractionEngine(),
            MediaMetadataExtractionEngine(),
        )
    )
