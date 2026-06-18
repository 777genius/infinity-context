"""Extraction engine that turns speech transcription results into memory evidence."""

from __future__ import annotations

import json
from dataclasses import replace

from memo_stack_core.application.safe_payload import safe_metadata, safe_metadata_text
from memo_stack_core.ports.extraction import (
    ExtractedElement,
    ExtractionArtifactCandidate,
    ExtractionRequest,
    ExtractionResult,
)
from memo_stack_core.ports.transcription import (
    SpeechTranscriptionPort,
    SpeechTranscriptionRequest,
    SpeechTranscriptionResult,
    SpeechTranscriptSegment,
    SpeechTranscriptWord,
)

from memo_stack_adapters.extraction.content import (
    _MEDIA_TYPES,
    ExtractionEngine,
    SupportDecision,
    _format_timestamp_ms,
    _limit_text,
    _unsupported,
)
from memo_stack_adapters.extraction.media_tools import (
    extract_selected_video_keyframes,
    media_manifest_artifact,
    probe_media_with_ffprobe,
)
from memo_stack_adapters.extraction.video_evidence import analyze_video_keyframes

_API_TRANSCRIPTION_PROFILES = {
    "media_api",
    "standard_asr",
    "standard_full",
    "full",
}


class SpeechTranscriptionExtractionEngine(ExtractionEngine):
    name = "speech_transcription"
    version = "v1"

    def __init__(self, *, transcription: SpeechTranscriptionPort) -> None:
        self._transcription = transcription

    async def supports(self, request: ExtractionRequest) -> SupportDecision:
        if not _profile_wants_api_transcription(request.parser_profile):
            return SupportDecision(False, reason="parser_profile_not_media_api")
        if not _is_media_content_type(request.detected_content_type):
            return SupportDecision(False, reason="not_audio_or_video")
        return SupportDecision(True)

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        probe = probe_media_with_ffprobe(request)
        if probe.duration_seconds and probe.duration_seconds > request.limits.max_media_seconds:
            return _fallback_unsupported(
                request,
                code="asset_extraction.transcription_media_too_long",
                message="Media duration exceeds transcription limit",
                metadata={
                    "duration_seconds": probe.duration_seconds,
                    "max_media_seconds": request.limits.max_media_seconds,
                },
            )
        if not request.limits.enable_external_ai:
            return _fallback_unsupported(
                request,
                code="asset_extraction.transcription_external_ai_disabled",
                message="External AI speech transcription is disabled",
                metadata=probe.metadata,
            )

        result = await self._transcription.transcribe(
            SpeechTranscriptionRequest(
                job_id=request.job_id,
                asset_id=request.asset_id,
                filename=request.filename,
                content_type=request.detected_content_type,
                byte_size=request.byte_size,
                sha256_hex=request.sha256_hex,
                content=request.content,
                max_output_chars=request.limits.max_output_chars,
            )
        )
        if result.status != "succeeded":
            return _fallback_unsupported(
                request,
                code=result.safe_error_code or "asset_extraction.transcription_failed",
                message=result.safe_error_message or "Speech transcription failed",
                metadata={
                    "transcription_provider": result.provider_name,
                    "transcription_model": result.provider_model,
                    **result.diagnostics,
                    **(probe.metadata or {}),
                },
            )

        text = _limit_text(result.text, request.limits.max_output_chars)
        if not text.strip():
            return _fallback_unsupported(
                request,
                code="asset_extraction.transcription_empty_output",
                message="Speech transcription returned no searchable text",
                metadata={
                    "transcription_provider": result.provider_name,
                    "transcription_model": result.provider_model,
                    **(probe.metadata or {}),
                },
            )

        segments = result.segments or (
            SpeechTranscriptSegment(
                text=text,
                start_ms=0,
                end_ms=_duration_to_ms(result.duration_seconds or probe.duration_seconds),
            ),
        )
        elements = tuple(
            ExtractedElement(
                kind="transcript_segment",
                text=segment.text,
                time_start_ms=segment.start_ms,
                time_end_ms=segment.end_ms,
                confidence=segment.confidence,
                metadata={
                    "source": self.name,
                    "transcription_provider": safe_metadata_text(result.provider_name),
                    "transcription_model": safe_metadata_text(result.provider_model)
                    if result.provider_model
                    else None,
                    **(
                        {"speaker": safe_metadata_text(segment.speaker, limit=120)}
                        if segment.speaker
                        else {}
                    ),
                    **safe_metadata(segment.metadata),
                },
            )
            for segment in segments
            if segment.text.strip()
        )
        duration_seconds = result.duration_seconds or probe.duration_seconds
        keyframes = ()
        frame_evidence = None
        if request.detected_content_type.startswith("video/"):
            keyframes = extract_selected_video_keyframes(
                request,
                duration_seconds=duration_seconds,
                max_frames=3,
            )
            if keyframes:
                frame_evidence = analyze_video_keyframes(
                    frames=keyframes,
                    parser_name=self.name,
                    enable_ocr=request.limits.enable_ocr,
                    ocr_timeout_seconds=request.limits.subprocess_timeout_seconds,
                )
                elements = (*elements, *frame_evidence.elements)
        markdown = _limit_text(
            "\n".join(
                [
                    f"# {request.filename.strip() or 'Media transcript'}",
                    "## Transcript",
                    *_segment_lines(segments),
                ]
            ),
            request.limits.max_output_chars,
        )
        transcript_text = "\n".join(_segment_lines(segments))
        transcript_json = _transcript_json_bytes(
            request=request,
            result=result,
            segments=segments,
            duration_seconds=duration_seconds,
        )
        return ExtractionResult(
            status="succeeded",
            normalized_content_type=request.detected_content_type,
            title=request.filename.strip() or "Media transcript",
            markdown=markdown,
            elements=elements,
            artifacts=(
                media_manifest_artifact(
                    request=request,
                    probe=probe,
                    parser_name=self.name,
                ),
                ExtractionArtifactCandidate(
                    artifact_type="transcript",
                    filename="transcript.txt",
                    content_type="text/plain",
                    content=transcript_text.encode("utf-8"),
                    metadata={
                        "parser": self.name,
                        "segment_count": len(segments),
                        "transcription_provider": safe_metadata_text(result.provider_name),
                        "transcription_model": safe_metadata_text(result.provider_model)
                        if result.provider_model
                        else None,
                    },
                ),
                ExtractionArtifactCandidate(
                    artifact_type="transcript_json",
                    filename="transcript.json",
                    content_type="application/json",
                    content=transcript_json,
                    metadata={
                        "parser": self.name,
                        "segment_count": len(segments),
                        "word_count": len(result.words),
                        "transcription_provider": safe_metadata_text(result.provider_name),
                        "transcription_model": safe_metadata_text(result.provider_model)
                        if result.provider_model
                        else None,
                    },
                ),
                *(frame.to_artifact() for frame in keyframes),
                *((frame_evidence.timeline_artifact,) if frame_evidence is not None else ()),
            ),
            technical_metadata={
                "byte_size": request.byte_size,
                "mime_detected": request.detected_content_type,
                "duration_seconds": duration_seconds,
                "segment_count": len(segments),
                "transcript_status": "extracted",
                "transcription_provider": result.provider_name,
                "transcription_model": result.provider_model,
                "transcription_provider_version": result.provider_version,
                "transcript_json_status": "extracted",
                "transcript_word_count": len(result.words),
                "keyframe_status": "extracted" if keyframes else "not_applicable",
                "output_chars": len(markdown),
                **(frame_evidence.metadata if frame_evidence is not None else {}),
                **(probe.metadata or {}),
            },
            diagnostics={
                "engine": self.name,
                "provider_diagnostics": safe_metadata(result.diagnostics),
            },
            language=result.language,
            parser_name=self.name,
            parser_version=self.version,
            model_version=result.provider_model,
        )


def _profile_wants_api_transcription(parser_profile: str) -> bool:
    normalized = parser_profile.strip().lower()
    return normalized in _API_TRANSCRIPTION_PROFILES or normalized.startswith(
        ("media_api:", "transcribe:", "openai_transcribe:")
    )


def _is_media_content_type(content_type: str) -> bool:
    return content_type in _MEDIA_TYPES or content_type.startswith(("audio/", "video/"))


def _segment_lines(segments: tuple[SpeechTranscriptSegment, ...]) -> list[str]:
    lines: list[str] = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        start = segment.start_ms
        end = segment.end_ms
        if start is None and end is None:
            lines.append(text)
            continue
        lines.append(
            f"{_format_timestamp_ms(start or 0)} --> "
            f"{_format_timestamp_ms(end if end is not None else start or 0)}\n{text}"
        )
    return lines


def _transcript_json_bytes(
    *,
    request: ExtractionRequest,
    result: SpeechTranscriptionResult,
    segments: tuple[SpeechTranscriptSegment, ...],
    duration_seconds: float | None,
) -> bytes:
    payload = {
        "schema_name": "memo_stack.transcript",
        "schema_version": 1,
        "asset_id": safe_metadata_text(request.asset_id, limit=120),
        "filename": safe_metadata_text(request.filename, limit=240),
        "content_type": safe_metadata_text(request.detected_content_type, limit=120),
        "duration_seconds": duration_seconds,
        "language": safe_metadata_text(result.language, limit=80) if result.language else None,
        "provider": {
            "name": safe_metadata_text(result.provider_name, limit=120),
            "model": safe_metadata_text(result.provider_model, limit=120)
            if result.provider_model
            else None,
            "version": safe_metadata_text(result.provider_version, limit=120)
            if result.provider_version
            else None,
            "diagnostics": safe_metadata(result.diagnostics),
        },
        "text": result.text,
        "segments": [_segment_payload(segment) for segment in segments],
        "words": [_word_payload(word) for word in result.words],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _segment_payload(segment: SpeechTranscriptSegment) -> dict[str, object]:
    return {
        "text": segment.text,
        "start_ms": segment.start_ms,
        "end_ms": segment.end_ms,
        "confidence": segment.confidence,
        "speaker": safe_metadata_text(segment.speaker, limit=120) if segment.speaker else None,
        "metadata": safe_metadata(segment.metadata),
    }


def _word_payload(word: SpeechTranscriptWord) -> dict[str, object]:
    return {
        "word": word.word,
        "start_ms": word.start_ms,
        "end_ms": word.end_ms,
        "confidence": word.confidence,
        "speaker": safe_metadata_text(word.speaker, limit=120) if word.speaker else None,
        "metadata": safe_metadata(word.metadata),
    }


def _duration_to_ms(duration_seconds: float | None) -> int | None:
    if duration_seconds is None or duration_seconds <= 0:
        return None
    return int(round(duration_seconds * 1000))


def _fallback_unsupported(
    request: ExtractionRequest,
    *,
    code: str,
    message: str,
    metadata: dict[str, object] | None = None,
) -> ExtractionResult:
    result = _unsupported(
        request,
        parser_name=SpeechTranscriptionExtractionEngine.name,
        parser_version=SpeechTranscriptionExtractionEngine.version,
        code=code,
        message=message,
        metadata=metadata,
    )
    return replace(result, diagnostics={**result.diagnostics, "fallback_allowed": True})
