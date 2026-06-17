"""OpenAI implementation of the speech transcription port."""

from __future__ import annotations

import inspect
from io import BytesIO
from typing import Any

from memo_stack_core.ports.transcription import (
    SpeechTranscriptionPort,
    SpeechTranscriptionRequest,
    SpeechTranscriptionResult,
    SpeechTranscriptSegment,
    SpeechTranscriptWord,
)

_SUPPORTED_CONTENT_TYPES = {
    "audio/flac",
    "audio/m4a",
    "audio/mpeg",
    "audio/mpga",
    "audio/mp4",
    "audio/ogg",
    "audio/vnd.wave",
    "audio/wav",
    "audio/x-wav",
    "audio/x-m4a",
    "audio/webm",
    "video/mp4",
    "video/webm",
}
OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class OpenAISpeechTranscriptionAdapter(SpeechTranscriptionPort):
    provider_name = "openai_transcription"
    provider_version = "audio-transcriptions-api"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "gpt-4o-mini-transcribe",
        client_factory: Any | None = None,
        prompt: str | None = None,
        max_upload_bytes: int = OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client_factory = client_factory
        self._prompt = prompt
        self._max_upload_bytes = max(1, int(max_upload_bytes))

    async def transcribe(
        self,
        request: SpeechTranscriptionRequest,
    ) -> SpeechTranscriptionResult:
        if request.content_type not in _SUPPORTED_CONTENT_TYPES:
            return self._unsupported(
                code="asset_extraction.transcription_unsupported_content_type",
                message="Transcription provider does not support this media type",
                diagnostics={"content_type": request.content_type},
            )
        if not self._api_key and self._client_factory is None:
            return self._unsupported(
                code="asset_extraction.transcription_missing_api_key",
                message="OpenAI API key is missing for speech transcription",
            )
        if request.byte_size > self._max_upload_bytes:
            return self._unsupported(
                code="asset_extraction.transcription_file_too_large",
                message="Media exceeds OpenAI speech transcription upload limit",
                diagnostics={
                    "byte_size": request.byte_size,
                    "max_provider_upload_bytes": self._max_upload_bytes,
                },
            )

        client = None
        try:
            client = self._client()
            response = await client.audio.transcriptions.create(
                **self._request_kwargs(request),
            )
            text = _response_text(response)[: request.max_output_chars]
        except Exception:
            return self._unsupported(
                code="asset_extraction.transcription_provider_error",
                message="OpenAI speech transcription failed",
            )
        finally:
            await _close_client(client)

        if not text.strip():
            return self._unsupported(
                code="asset_extraction.transcription_empty_output",
                message="OpenAI speech transcription returned no text",
            )

        return SpeechTranscriptionResult(
            status="succeeded",
            text=text,
            segments=_response_segments(response),
            words=_response_words(response),
            language=_response_language(response),
            duration_seconds=_response_duration_seconds(response),
            provider_name=self.provider_name,
            provider_model=self._model,
            provider_version=self.provider_version,
            diagnostics={
                **_request_diagnostics(self._model),
                **_response_diagnostics(response),
            },
        )

    def _request_kwargs(self, request: SpeechTranscriptionRequest) -> dict[str, object]:
        file_obj = BytesIO(request.content)
        file_obj.name = _safe_filename(request.filename, request.content_type)
        kwargs: dict[str, object] = {
            "model": self._model,
            "file": file_obj,
            "response_format": _response_format_for_model(self._model),
        }
        if _supports_segment_timestamps(self._model):
            kwargs["timestamp_granularities"] = ["segment"]
        if _requires_chunking_strategy(self._model):
            kwargs["chunking_strategy"] = "auto"
        prompt = request.prompt or self._prompt
        if prompt and not _requires_chunking_strategy(self._model):
            kwargs["prompt"] = prompt[:2000]
        return kwargs

    def _client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=self._api_key)

    def _unsupported(
        self,
        *,
        code: str,
        message: str,
        diagnostics: dict[str, object] | None = None,
    ) -> SpeechTranscriptionResult:
        return SpeechTranscriptionResult(
            status="unsupported",
            provider_name=self.provider_name,
            provider_model=self._model,
            provider_version=self.provider_version,
            diagnostics=diagnostics or {},
            safe_error_code=code,
            safe_error_message=message,
        )


def _safe_filename(filename: str, content_type: str) -> str:
    clean = (filename or "").strip().replace("/", "_").replace("\\", "_")
    if "." in clean:
        return clean
    extension = {
        "audio/flac": ".flac",
        "audio/m4a": ".m4a",
        "audio/mpeg": ".mp3",
        "audio/mpga": ".mpga",
        "audio/mp4": ".m4a",
        "audio/ogg": ".ogg",
        "audio/vnd.wave": ".wav",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/x-m4a": ".m4a",
        "audio/webm": ".webm",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
    }.get(content_type, ".bin")
    return f"{clean or 'media'}{extension}"


def _response_text(response: Any) -> str:
    if isinstance(response, str):
        return response.strip()
    if isinstance(response, dict):
        value = response.get("text") or response.get("output_text")
        return value.strip() if isinstance(value, str) else ""
    value = getattr(response, "text", None)
    if isinstance(value, str):
        return value.strip()
    value = getattr(response, "output_text", None)
    if isinstance(value, str):
        return value.strip()
    return ""


def _response_segments(response: Any) -> tuple[SpeechTranscriptSegment, ...]:
    raw_segments = _raw_segments(response)
    segments: list[SpeechTranscriptSegment] = []
    for raw in raw_segments:
        text = _raw_value(raw, "text")
        if not isinstance(text, str) or not text.strip():
            continue
        start_ms = _seconds_to_ms(_raw_value(raw, "start"))
        end_ms = _seconds_to_ms(_raw_value(raw, "end"))
        speaker = _raw_value(raw, "speaker")
        confidence = _confidence_from_segment(raw)
        segments.append(
            SpeechTranscriptSegment(
                text=text.strip(),
                start_ms=start_ms,
                end_ms=end_ms,
                confidence=confidence,
                speaker=speaker if isinstance(speaker, str) else None,
                metadata={
                    "source": "provider_segment",
                    **_segment_metadata(raw),
                },
            )
        )
    return tuple(segments)


def _response_words(response: Any) -> tuple[SpeechTranscriptWord, ...]:
    raw_words = _raw_words(response)
    words: list[SpeechTranscriptWord] = []
    for raw in raw_words:
        word = _raw_value(raw, "word")
        if not isinstance(word, str) or not word.strip():
            continue
        speaker = _raw_value(raw, "speaker")
        words.append(
            SpeechTranscriptWord(
                word=word.strip(),
                start_ms=_seconds_to_ms(_raw_value(raw, "start")),
                end_ms=_seconds_to_ms(_raw_value(raw, "end")),
                confidence=_confidence_from_segment(raw),
                speaker=speaker if isinstance(speaker, str) else None,
                metadata={"source": "provider_word"},
            )
        )
    return tuple(words)


def _raw_segments(response: Any) -> list[object]:
    if isinstance(response, dict):
        value = response.get("segments")
        return value if isinstance(value, list) else []
    value = getattr(response, "segments", None)
    return value if isinstance(value, list) else []


def _raw_words(response: Any) -> list[object]:
    if isinstance(response, dict):
        value = response.get("words")
        return value if isinstance(value, list) else []
    value = getattr(response, "words", None)
    return value if isinstance(value, list) else []


def _response_language(response: Any) -> str | None:
    value = _raw_value(response, "language")
    return value if isinstance(value, str) and value.strip() else None


def _response_duration_seconds(response: Any) -> float | None:
    value = _raw_value(response, "duration")
    if isinstance(value, int | float) and value > 0:
        return float(value)
    return None


def _response_format_for_model(model: str) -> str:
    normalized = model.strip().lower()
    if "diarize" in normalized:
        return "diarized_json"
    if normalized == "whisper-1":
        return "verbose_json"
    return "json"


def _supports_segment_timestamps(model: str) -> bool:
    return model.strip().lower() == "whisper-1"


def _requires_chunking_strategy(model: str) -> bool:
    return "diarize" in model.strip().lower()


def _request_diagnostics(model: str) -> dict[str, object]:
    diagnostics: dict[str, object] = {"response_format": _response_format_for_model(model)}
    if _supports_segment_timestamps(model):
        diagnostics["timestamp_granularities"] = ["segment"]
    if _requires_chunking_strategy(model):
        diagnostics["chunking_strategy"] = "auto"
    return diagnostics


def _response_diagnostics(response: Any) -> dict[str, object]:
    usage = _raw_value(response, "usage")
    return {"usage": usage} if isinstance(usage, dict) else {}


def _confidence_from_segment(raw: Any) -> float | None:
    avg_logprob = _raw_value(raw, "avg_logprob")
    if isinstance(avg_logprob, int | float):
        return max(0.0, min(1.0, 1.0 + (float(avg_logprob) / 10.0)))
    no_speech_prob = _raw_value(raw, "no_speech_prob")
    if isinstance(no_speech_prob, int | float):
        return max(0.0, min(1.0, 1.0 - float(no_speech_prob)))
    return None


def _segment_metadata(raw: Any) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for key in ("id", "seek", "temperature", "avg_logprob", "compression_ratio", "no_speech_prob"):
        value = _raw_value(raw, key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            metadata[key] = value
    return metadata


def _raw_value(raw: Any, key: str) -> object:
    if isinstance(raw, dict):
        return raw.get(key)
    return getattr(raw, key, None)


def _seconds_to_ms(value: object) -> int | None:
    if not isinstance(value, int | float):
        return None
    if value < 0:
        return None
    return int(round(float(value) * 1000))


async def _close_client(client: object | None) -> None:
    if client is None:
        return
    for method_name in ("aclose", "close"):
        close = getattr(client, method_name, None)
        if not callable(close):
            continue
        result = close()
        if inspect.isawaitable(result):
            await result
        return
