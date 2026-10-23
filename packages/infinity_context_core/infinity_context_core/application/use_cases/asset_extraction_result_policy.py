"""Safe result metadata and output resource policy for extraction workflows."""

from __future__ import annotations

from dataclasses import replace

from infinity_context_core.application.asset_upload_policy import (
    UPLOAD_POLICY_VERSION,
    detect_magic_content_type,
)
from infinity_context_core.application.safe_payload import safe_metadata, safe_metadata_text
from infinity_context_core.domain.assets import MemoryAsset
from infinity_context_core.ports.extraction import (
    ExtractionLimits,
    ExtractionResult,
    FileTypeDetectionResult,
)


def _file_type_detection_metadata(
    detection: FileTypeDetectionResult,
) -> dict[str, object]:
    return {
        "detected_content_type": safe_metadata_text(detection.content_type),
        "detector_confidence": safe_metadata_text(detection.confidence),
        **safe_metadata(detection.diagnostics),
    }


def _resource_limit_result(
    *,
    asset: MemoryAsset,
    code: str | None,
    message: str | None,
    metadata: dict[str, object],
) -> ExtractionResult:
    return ExtractionResult(
        status="unsupported",
        normalized_content_type=safe_metadata_text(asset.content_type),
        title=asset.filename,
        parser_name="resource_policy",
        parser_version=metadata.get("extraction_resource_policy_version")
        if isinstance(metadata.get("extraction_resource_policy_version"), str)
        else None,
        safe_error_code=code or "asset_extraction.resource_limit",
        safe_error_message=message or "Asset exceeds extraction resource policy",
        technical_metadata=metadata,
    )


def _apply_extracted_text_limit(
    *,
    result: ExtractionResult,
    extracted_text_value: str,
    limits: ExtractionLimits,
) -> tuple[ExtractionResult, str]:
    max_chars = max(1, int(limits.max_output_chars))
    if len(extracted_text_value) <= max_chars:
        return result, extracted_text_value

    notice = "\n\n[Extraction output truncated by resource policy]"
    if max_chars > len(notice) + 32:
        text = extracted_text_value[: max_chars - len(notice)].rstrip() + notice
    else:
        text = extracted_text_value[:max_chars]
    metadata = {
        **dict(result.technical_metadata),
        "extraction_output_truncated": True,
        "extraction_output_chars_original": len(extracted_text_value),
        "extraction_output_chars_stored": len(text),
        "extraction_max_output_chars": max_chars,
        "extraction_resource_limits_applied": _append_limit_applied(
            result.technical_metadata.get("extraction_resource_limits_applied"),
            "max_output_chars",
        ),
    }
    return replace(result, markdown=text, technical_metadata=metadata), text


def _append_limit_applied(value: object, item: str) -> list[str]:
    existing: list[str] = []
    if isinstance(value, list | tuple):
        existing = [str(raw)[:80] for raw in value if str(raw).strip()]
    if item not in existing:
        existing.append(item)
    return existing


def _upload_policy_revalidation_metadata(metadata: dict[str, object]) -> dict[str, object]:
    return {
        "extraction_upload_policy_revalidated": True,
        "extraction_upload_policy_status": "allowed",
        **safe_metadata(metadata),
    }


def _upload_policy_rejection_result(
    *,
    asset: MemoryAsset,
    content: bytes,
    message: str,
) -> ExtractionResult:
    metadata = {
        "upload_policy_version": UPLOAD_POLICY_VERSION,
        "extraction_upload_policy_revalidated": True,
        "extraction_upload_policy_status": "rejected",
        "extraction_upload_policy_rejection": safe_metadata_text(message),
        "extraction_upload_magic_content_type": safe_metadata_text(
            detect_magic_content_type(content)
        ),
        "extraction_asset_byte_size": len(content),
    }
    return ExtractionResult(
        status="unsupported",
        normalized_content_type=safe_metadata_text(asset.content_type),
        title=asset.filename,
        parser_name="upload_policy",
        parser_version=UPLOAD_POLICY_VERSION,
        safe_error_code="asset_extraction.upload_policy_rejected",
        safe_error_message="Asset violates upload security policy",
        technical_metadata=metadata,
    )
