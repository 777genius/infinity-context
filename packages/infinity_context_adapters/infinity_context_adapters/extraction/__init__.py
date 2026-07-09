"""Extraction adapters for auto-memory candidate generation."""

from infinity_context_adapters.extraction.content import (
    ImageMetadataExtractionEngine,
    MediaMetadataExtractionEngine,
    PdfTextExtractionEngine,
    SimpleFileTypeDetector,
    SimpleTextExtractionEngine,
    StandardExtractionRouter,
    TimedTextTranscriptExtractionEngine,
)
from infinity_context_adapters.extraction.docling_engine import DoclingDocumentExtractionEngine
from infinity_context_adapters.extraction.factory import build_standard_extractor
from infinity_context_adapters.extraction.openai_json import OpenAIJsonMemoryExtractor
from infinity_context_adapters.extraction.openai_vision import (
    OpenAIImageVisionAdapter,
    OpenAIVisionImageExtractionEngine,
)
from infinity_context_adapters.extraction.transcription import OpenAISpeechTranscriptionAdapter
from infinity_context_adapters.extraction.transcription_engine import (
    SpeechTranscriptionExtractionEngine,
)
from infinity_context_adapters.extraction.whisper_engine import FasterWhisperTranscriptionEngine

__all__ = [
    "DoclingDocumentExtractionEngine",
    "FasterWhisperTranscriptionEngine",
    "OpenAIJsonMemoryExtractor",
    "OpenAIImageVisionAdapter",
    "OpenAISpeechTranscriptionAdapter",
    "OpenAIVisionImageExtractionEngine",
    "ImageMetadataExtractionEngine",
    "MediaMetadataExtractionEngine",
    "PdfTextExtractionEngine",
    "SimpleFileTypeDetector",
    "SimpleTextExtractionEngine",
    "SpeechTranscriptionExtractionEngine",
    "StandardExtractionRouter",
    "TimedTextTranscriptExtractionEngine",
    "build_standard_extractor",
]
