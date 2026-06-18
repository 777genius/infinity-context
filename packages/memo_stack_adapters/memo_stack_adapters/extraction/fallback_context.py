"""Fallback metadata helpers for extraction router degradation."""

from __future__ import annotations

from memo_stack_core.ports.extraction import ExtractionResult


def merge_fallback_context(
    result: ExtractionResult,
    fallback_result: ExtractionResult,
) -> ExtractionResult:
    technical_metadata = {
        **result.technical_metadata,
        "degraded_fallback": True,
        "fallback_parser_name": fallback_result.parser_name,
    }
    if fallback_result.safe_error_code:
        technical_metadata["fallback_safe_error_code"] = fallback_result.safe_error_code
    if fallback_result.safe_error_message:
        technical_metadata["fallback_safe_error_message"] = fallback_result.safe_error_message
    technical_metadata.update(_speech_transcription_fallback_metadata(fallback_result))
    technical_metadata.update(_image_vision_fallback_metadata(fallback_result))
    return ExtractionResult(
        status=result.status,
        normalized_content_type=result.normalized_content_type,
        title=result.title,
        elements=result.elements,
        markdown=result.markdown,
        artifacts=result.artifacts,
        technical_metadata=technical_metadata,
        diagnostics=result.diagnostics,
        language=result.language,
        parser_name=result.parser_name,
        parser_version=result.parser_version,
        model_version=result.model_version,
        safe_error_code=result.safe_error_code,
        safe_error_message=result.safe_error_message,
    )


def _speech_transcription_fallback_metadata(
    fallback_result: ExtractionResult,
) -> dict[str, object]:
    if fallback_result.parser_name != "speech_transcription":
        return {}
    code = fallback_result.safe_error_code or "asset_extraction.transcription_failed"
    metadata: dict[str, object] = {
        "transcript_status": _transcript_fallback_status(code),
        "transcript_error_code": code,
    }
    if fallback_result.safe_error_message:
        metadata["transcript_error_message"] = fallback_result.safe_error_message
    provider = fallback_result.technical_metadata.get("transcription_provider")
    if provider:
        metadata["transcription_provider"] = provider
    model = fallback_result.technical_metadata.get("transcription_model")
    if model:
        metadata["transcription_model"] = model
    metadata.update(
        _provider_fallback_metadata(
            fallback_result,
            prefix="transcript",
        )
    )
    return metadata


def _image_vision_fallback_metadata(
    fallback_result: ExtractionResult,
) -> dict[str, object]:
    if fallback_result.parser_name != "openai_vision_image":
        return {}
    code = fallback_result.safe_error_code or "asset_extraction.vision_failed"
    metadata: dict[str, object] = {
        "vision_status": _vision_fallback_status(code),
        "vision_error_code": code,
    }
    if fallback_result.safe_error_message:
        metadata["vision_error_message"] = fallback_result.safe_error_message
    provider = fallback_result.technical_metadata.get("vision_provider")
    if provider:
        metadata["vision_provider"] = provider
    model = fallback_result.technical_metadata.get("vision_model")
    if model:
        metadata["vision_model"] = model
    metadata.update(_provider_fallback_metadata(fallback_result, prefix="vision"))
    return metadata


def _provider_fallback_metadata(
    fallback_result: ExtractionResult,
    *,
    prefix: str,
) -> dict[str, object]:
    metadata: dict[str, object] = {}
    technical = fallback_result.technical_metadata
    retryable = technical.get("provider_retryable")
    if isinstance(retryable, bool):
        metadata[f"{prefix}_provider_retryable"] = retryable
    error_type = technical.get("provider_error_type")
    if isinstance(error_type, str) and error_type.strip():
        metadata[f"{prefix}_provider_error_type"] = error_type.strip()[:120]
    timeout = technical.get("request_timeout_seconds")
    if isinstance(timeout, int | float) and timeout > 0:
        metadata[f"{prefix}_request_timeout_seconds"] = float(timeout)
    return metadata


def _transcript_fallback_status(code: str) -> str:
    if code == "asset_extraction.transcription_external_ai_disabled":
        return "disabled"
    if code == "asset_extraction.transcription_missing_api_key":
        return "not_configured"
    if code in {
        "asset_extraction.transcription_file_too_large",
        "asset_extraction.transcription_media_too_long",
    }:
        return "skipped"
    if code == "asset_extraction.transcription_unsupported_content_type":
        return "unsupported"
    return "failed"


def _vision_fallback_status(code: str) -> str:
    if code == "asset_extraction.vision_external_ai_disabled":
        return "disabled"
    if code == "asset_extraction.vision_missing_api_key":
        return "not_configured"
    if code == "asset_extraction.vision_image_too_large":
        return "skipped"
    if code == "asset_extraction.vision_empty_output":
        return "empty"
    return "failed"
