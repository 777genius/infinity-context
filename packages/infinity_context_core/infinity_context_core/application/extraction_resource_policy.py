"""Provider-neutral extraction resource limits."""

from __future__ import annotations

import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath, PureWindowsPath
from zipfile import BadZipFile, ZipFile, is_zipfile

from infinity_context_core.ports.extraction import ExtractionLimits

EXTRACTION_RESOURCE_POLICY_VERSION = "asset-extraction-resource-policy-v1"
EXTRACTION_RESULT_RESOURCE_POLICY_VERSION = "asset-extraction-result-resource-policy-v1"
EXTRACTION_ARCHIVE_RESOURCE_POLICY_VERSION = "asset-extraction-archive-resource-policy-v2"

EXTRACTION_RESOURCE_LIMIT_CAPS = {
    "max_bytes": 500 * 1024 * 1024,
    "max_pages": 10_000,
    "max_media_seconds": 24 * 60 * 60,
    "max_output_chars": 10_000_000,
    "max_tables": 10_000,
    "parser_timeout_seconds": 24 * 60 * 60,
    "subprocess_timeout_seconds": 60 * 60,
    "max_image_pixels": 500_000_000,
    "max_archive_entries": 100_000,
    "max_archive_uncompressed_bytes": 10 * 1024 * 1024 * 1024,
    "max_archive_compression_ratio": 10_000,
}

_DEFAULT_MAX_BYTES = 25 * 1024 * 1024
_DEFAULT_MAX_PAGES = 100
_DEFAULT_MAX_MEDIA_SECONDS = 600
_DEFAULT_MAX_OUTPUT_CHARS = 500_000
_DEFAULT_MAX_TABLES = 100
_DEFAULT_PARSER_TIMEOUT_SECONDS = 300.0
_DEFAULT_SUBPROCESS_TIMEOUT_SECONDS = 60.0
_DEFAULT_MAX_IMAGE_PIXELS = 50_000_000
_DEFAULT_MAX_ARCHIVE_ENTRIES = 2_000
_DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
_DEFAULT_MAX_ARCHIVE_COMPRESSION_RATIO = 100
_ZIP_CONTAINER_TYPES = frozenset(
    {
        "application/zip",
        "application/epub+zip",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)


@dataclass(frozen=True)
class ExtractionResourceDecision:
    limits: ExtractionLimits
    allowed: bool
    code: str | None
    message: str | None
    metadata: dict[str, object]


def normalize_extraction_limits(limits: ExtractionLimits) -> ExtractionLimits:
    """Clamp externally supplied limits before they reach provider adapters."""

    return ExtractionLimits(
        max_bytes=_bounded_int(
            limits.max_bytes,
            minimum=1,
            maximum=EXTRACTION_RESOURCE_LIMIT_CAPS["max_bytes"],
            default=_DEFAULT_MAX_BYTES,
        ),
        max_pages=_bounded_int(
            limits.max_pages,
            minimum=1,
            maximum=EXTRACTION_RESOURCE_LIMIT_CAPS["max_pages"],
            default=_DEFAULT_MAX_PAGES,
        ),
        max_media_seconds=_bounded_int(
            limits.max_media_seconds,
            minimum=1,
            maximum=EXTRACTION_RESOURCE_LIMIT_CAPS["max_media_seconds"],
            default=_DEFAULT_MAX_MEDIA_SECONDS,
        ),
        max_output_chars=_bounded_int(
            limits.max_output_chars,
            minimum=1,
            maximum=EXTRACTION_RESOURCE_LIMIT_CAPS["max_output_chars"],
            default=_DEFAULT_MAX_OUTPUT_CHARS,
        ),
        max_tables=_bounded_int(
            limits.max_tables,
            minimum=0,
            maximum=EXTRACTION_RESOURCE_LIMIT_CAPS["max_tables"],
            default=_DEFAULT_MAX_TABLES,
        ),
        parser_timeout_seconds=_bounded_float(
            limits.parser_timeout_seconds,
            minimum=0.001,
            maximum=EXTRACTION_RESOURCE_LIMIT_CAPS["parser_timeout_seconds"],
            default=_DEFAULT_PARSER_TIMEOUT_SECONDS,
        ),
        subprocess_timeout_seconds=_bounded_float(
            limits.subprocess_timeout_seconds,
            minimum=0.001,
            maximum=EXTRACTION_RESOURCE_LIMIT_CAPS["subprocess_timeout_seconds"],
            default=_DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
        ),
        max_image_pixels=_bounded_int(
            limits.max_image_pixels,
            minimum=1,
            maximum=EXTRACTION_RESOURCE_LIMIT_CAPS["max_image_pixels"],
            default=_DEFAULT_MAX_IMAGE_PIXELS,
        ),
        max_archive_entries=_bounded_int(
            limits.max_archive_entries,
            minimum=1,
            maximum=EXTRACTION_RESOURCE_LIMIT_CAPS["max_archive_entries"],
            default=_DEFAULT_MAX_ARCHIVE_ENTRIES,
        ),
        max_archive_uncompressed_bytes=_bounded_int(
            limits.max_archive_uncompressed_bytes,
            minimum=1,
            maximum=EXTRACTION_RESOURCE_LIMIT_CAPS["max_archive_uncompressed_bytes"],
            default=_DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES,
        ),
        max_archive_compression_ratio=_bounded_int(
            limits.max_archive_compression_ratio,
            minimum=1,
            maximum=EXTRACTION_RESOURCE_LIMIT_CAPS["max_archive_compression_ratio"],
            default=_DEFAULT_MAX_ARCHIVE_COMPRESSION_RATIO,
        ),
        enable_ocr=bool(limits.enable_ocr),
        enable_external_ai=bool(limits.enable_external_ai),
    )


def extraction_limits_metadata(limits: ExtractionLimits) -> dict[str, object]:
    normalized = normalize_extraction_limits(limits)
    clamped_fields = _clamped_limit_fields(raw=limits, normalized=normalized)
    return {
        "extraction_resource_policy_version": EXTRACTION_RESOURCE_POLICY_VERSION,
        "extraction_limits_normalized": bool(clamped_fields),
        "extraction_limits_clamped_fields": clamped_fields,
        "extraction_max_bytes": normalized.max_bytes,
        "extraction_max_pages": normalized.max_pages,
        "extraction_max_media_seconds": normalized.max_media_seconds,
        "extraction_max_output_chars": normalized.max_output_chars,
        "extraction_max_tables": normalized.max_tables,
        "extraction_parser_timeout_seconds": normalized.parser_timeout_seconds,
        "extraction_subprocess_timeout_seconds": normalized.subprocess_timeout_seconds,
        "extraction_max_image_pixels": normalized.max_image_pixels,
        "extraction_max_archive_entries": normalized.max_archive_entries,
        "extraction_max_archive_uncompressed_bytes": (
            normalized.max_archive_uncompressed_bytes
        ),
        "extraction_max_archive_compression_ratio": (
            normalized.max_archive_compression_ratio
        ),
        "extraction_ocr_enabled": normalized.enable_ocr,
        "extraction_external_ai_enabled": normalized.enable_external_ai,
    }


def assess_extraction_resource_limits(
    *,
    asset_byte_size: int,
    limits: ExtractionLimits,
    byte_size_source: str = "asset_metadata",
) -> ExtractionResourceDecision:
    normalized = normalize_extraction_limits(limits)
    safe_byte_size = max(0, _coerce_int(asset_byte_size, default=0))
    metadata = {
        **extraction_limits_metadata(normalized),
        "extraction_asset_byte_size": safe_byte_size,
        "extraction_asset_byte_size_source": byte_size_source[:80],
    }
    if safe_byte_size > normalized.max_bytes:
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=False,
            code="asset_extraction.file_too_large",
            message="Asset exceeds configured extraction size limit",
            metadata={
                **metadata,
                "extraction_resource_limit_exceeded": "max_bytes",
            },
        )
    return ExtractionResourceDecision(
        limits=normalized,
        allowed=True,
        code=None,
        message=None,
        metadata=metadata,
    )


def assess_extraction_archive_resource_limits(
    *,
    filename: str,
    declared_content_type: str,
    detected_content_type: str,
    magic_content_type: str | None,
    content: bytes,
    limits: ExtractionLimits,
) -> ExtractionResourceDecision:
    normalized = normalize_extraction_limits(limits)
    metadata = {
        "extraction_archive_resource_policy_version": (
            EXTRACTION_ARCHIVE_RESOURCE_POLICY_VERSION
        ),
        "extraction_archive_resource_checked": False,
        "extraction_archive_magic_content_type": _safe_content_type(magic_content_type),
        "extraction_archive_detected_content_type": _safe_content_type(detected_content_type),
        "extraction_archive_declared_content_type": _safe_content_type(declared_content_type),
        "extraction_max_archive_entries": normalized.max_archive_entries,
        "extraction_max_archive_uncompressed_bytes": (
            normalized.max_archive_uncompressed_bytes
        ),
        "extraction_max_archive_compression_ratio": (
            normalized.max_archive_compression_ratio
        ),
    }
    if not _should_inspect_zip_container(
        magic_content_type=magic_content_type,
        detected_content_type=detected_content_type,
        declared_content_type=declared_content_type,
        filename=filename,
    ):
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=True,
            code=None,
            message=None,
            metadata=metadata,
        )

    metadata["extraction_archive_resource_checked"] = True
    if not is_zipfile(BytesIO(content)):
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=False,
            code="asset_extraction.archive_parse_failed",
            message="Archive metadata could not be inspected safely",
            metadata={
                **metadata,
                "extraction_resource_limit_exceeded": "archive_parse",
            },
        )

    try:
        with ZipFile(BytesIO(content)) as archive:
            infos = tuple(archive.infolist())
    except (BadZipFile, RuntimeError, OSError):
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=False,
            code="asset_extraction.archive_parse_failed",
            message="Archive metadata could not be inspected safely",
            metadata={
                **metadata,
                "extraction_resource_limit_exceeded": "archive_parse",
            },
        )

    file_infos = tuple(info for info in infos if not info.is_dir())
    total_uncompressed = sum(max(0, int(info.file_size)) for info in file_infos)
    total_compressed = sum(max(0, int(info.compress_size)) for info in file_infos)
    compression_ratio = (
        round(total_uncompressed / max(total_compressed, 1), 4)
        if total_uncompressed
        else 0.0
    )
    unsafe_path_count = sum(1 for info in infos if _unsafe_archive_member_name(info.filename))
    symlink_count = sum(1 for info in file_infos if _archive_member_is_symlink(info))
    special_file_count = sum(1 for info in file_infos if _archive_member_is_special_file(info))
    duplicate_path_count = _archive_duplicate_path_count(info.filename for info in file_infos)
    nested_archive_count = sum(
        1 for info in file_infos if _archive_member_is_nested_archive(info.filename)
    )
    encrypted_count = sum(1 for info in file_infos if bool(info.flag_bits & 0x1))
    metadata.update(
        {
            "extraction_archive_entries": len(infos),
            "extraction_archive_file_entries": len(file_infos),
            "extraction_archive_uncompressed_bytes": total_uncompressed,
            "extraction_archive_compressed_bytes": total_compressed,
            "extraction_archive_compression_ratio": compression_ratio,
            "extraction_archive_unsafe_path_count": unsafe_path_count,
            "extraction_archive_symlink_entry_count": symlink_count,
            "extraction_archive_special_entry_count": special_file_count,
            "extraction_archive_duplicate_path_count": duplicate_path_count,
            "extraction_archive_nested_archive_count": nested_archive_count,
            "extraction_archive_encrypted_entry_count": encrypted_count,
        }
    )

    if unsafe_path_count:
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=False,
            code="asset_extraction.archive_unsafe_path",
            message="Archive contains unsafe member paths",
            metadata={
                **metadata,
                "extraction_resource_limit_exceeded": "archive_unsafe_path",
            },
        )
    if symlink_count:
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=False,
            code="asset_extraction.archive_symlink_entry",
            message="Archive contains symbolic link members",
            metadata={
                **metadata,
                "extraction_resource_limit_exceeded": "archive_symlink_entry",
            },
        )
    if special_file_count:
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=False,
            code="asset_extraction.archive_special_file_entry",
            message="Archive contains special file members",
            metadata={
                **metadata,
                "extraction_resource_limit_exceeded": "archive_special_file_entry",
            },
        )
    if duplicate_path_count:
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=False,
            code="asset_extraction.archive_duplicate_path",
            message="Archive contains duplicate member paths",
            metadata={
                **metadata,
                "extraction_resource_limit_exceeded": "archive_duplicate_path",
            },
        )
    if nested_archive_count:
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=False,
            code="asset_extraction.archive_nested_archive",
            message="Archive contains nested archive members",
            metadata={
                **metadata,
                "extraction_resource_limit_exceeded": "archive_nested_archive",
            },
        )
    if encrypted_count:
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=False,
            code="asset_extraction.archive_encrypted",
            message="Archive contains encrypted members",
            metadata={
                **metadata,
                "extraction_resource_limit_exceeded": "archive_encrypted",
            },
        )
    if len(infos) > normalized.max_archive_entries:
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=False,
            code="asset_extraction.archive_too_many_entries",
            message="Archive contains too many entries",
            metadata={
                **metadata,
                "extraction_resource_limit_exceeded": "max_archive_entries",
            },
        )
    if total_uncompressed > normalized.max_archive_uncompressed_bytes:
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=False,
            code="asset_extraction.archive_uncompressed_too_large",
            message="Archive uncompressed size exceeds extraction resource limit",
            metadata={
                **metadata,
                "extraction_resource_limit_exceeded": (
                    "max_archive_uncompressed_bytes"
                ),
            },
        )
    if (
        compression_ratio > normalized.max_archive_compression_ratio
        and total_uncompressed > normalized.max_bytes
    ):
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=False,
            code="asset_extraction.archive_compression_ratio_too_high",
            message="Archive compression ratio exceeds extraction resource limit",
            metadata={
                **metadata,
                "extraction_resource_limit_exceeded": (
                    "max_archive_compression_ratio"
                ),
            },
        )

    return ExtractionResourceDecision(
        limits=normalized,
        allowed=True,
        code=None,
        message=None,
        metadata=metadata,
    )


def assess_extraction_result_resource_limits(
    *,
    result_metadata: Mapping[str, object],
    limits: ExtractionLimits,
) -> ExtractionResourceDecision:
    """Validate extractor/provider output against global resource limits.

    Adapters should enforce limits locally, but this application boundary is the
    last provider-neutral guard before canonical ingestion.
    """

    normalized = normalize_extraction_limits(limits)
    duration_seconds = _metadata_positive_float(
        result_metadata,
        "usage_media_analysis_seconds_actual",
        "media_analysis_seconds_actual",
        "media_duration_seconds",
        "duration_seconds",
        "estimated_media_seconds",
    )
    duration_ms = _metadata_positive_float(result_metadata, "duration_ms")
    if duration_seconds is None and duration_ms is not None:
        duration_seconds = duration_ms / 1000

    page_count = _metadata_positive_int(
        result_metadata,
        "page_count",
        "pages",
        "num_pages",
    )
    pages_processed = _metadata_positive_int(
        result_metadata,
        "pages_extracted",
        "pages_processed",
        "processed_pages",
    )
    image_pixels = _metadata_positive_int(
        result_metadata,
        "image_pixels",
        "upload_image_pixels",
        "video_frame_pixels",
        "frame_pixels",
    )
    if image_pixels is None:
        image_width = _metadata_positive_int(result_metadata, "image_width", "width")
        image_height = _metadata_positive_int(result_metadata, "image_height", "height")
        if image_width is not None and image_height is not None:
            image_pixels = image_width * image_height
    output_chars = _metadata_positive_int(
        result_metadata,
        "output_chars",
        "text_chars",
        "markdown_chars",
    )

    metadata: dict[str, object] = {
        "extraction_result_resource_policy_version": (EXTRACTION_RESULT_RESOURCE_POLICY_VERSION),
        "extraction_result_resource_checked": True,
        "extraction_max_pages": normalized.max_pages,
        "extraction_max_media_seconds": normalized.max_media_seconds,
        "extraction_max_output_chars": normalized.max_output_chars,
        "extraction_max_image_pixels": normalized.max_image_pixels,
    }
    if duration_seconds is not None:
        metadata["extraction_result_media_seconds"] = duration_seconds
    if page_count is not None:
        metadata["extraction_result_page_count"] = page_count
    if pages_processed is not None:
        metadata["extraction_result_pages_processed"] = pages_processed
    if image_pixels is not None:
        metadata["extraction_result_image_pixels"] = image_pixels
    if output_chars is not None:
        metadata["extraction_result_output_chars"] = output_chars

    if duration_seconds is not None and duration_seconds > normalized.max_media_seconds:
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=False,
            code="asset_extraction.media_too_long",
            message="Media duration exceeds extraction resource limit",
            metadata={
                **metadata,
                "extraction_resource_limit_exceeded": "max_media_seconds",
            },
        )
    if image_pixels is not None and image_pixels > normalized.max_image_pixels:
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=False,
            code="asset_extraction.image_too_large",
            message="Image dimensions exceed extraction resource limit",
            metadata={
                **metadata,
                "extraction_resource_limit_exceeded": "max_image_pixels",
            },
        )
    if pages_processed is not None and pages_processed > normalized.max_pages:
        return ExtractionResourceDecision(
            limits=normalized,
            allowed=False,
            code="asset_extraction.page_limit_breach",
            message="Extractor processed more pages than allowed",
            metadata={
                **metadata,
                "extraction_resource_limit_exceeded": "max_pages",
            },
        )

    applied: list[str] = []
    if page_count is not None and page_count > normalized.max_pages:
        applied.append("max_pages")
        metadata["extraction_result_pages_truncated"] = True
    if output_chars is not None and output_chars > normalized.max_output_chars:
        applied.append("max_output_chars")
        metadata["extraction_result_output_truncation_required"] = True
    if applied:
        metadata["extraction_resource_limits_applied"] = applied

    return ExtractionResourceDecision(
        limits=normalized,
        allowed=True,
        code=None,
        message=None,
        metadata=metadata,
    )


def _bounded_int(value: object, *, minimum: int, maximum: int, default: int) -> int:
    parsed = _coerce_int(value, default=default)
    return min(max(parsed, minimum), maximum)


def _bounded_float(value: object, *, minimum: float, maximum: float, default: float) -> float:
    parsed = _coerce_float(value, default=default)
    return min(max(parsed, minimum), maximum)


def _coerce_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return default
    return default


def _coerce_float(value: object, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _metadata_positive_int(metadata: Mapping[str, object], *keys: str) -> int | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            number = int(value)
            if number > 0:
                return number
            continue
        if isinstance(value, str):
            try:
                number = int(float(value.strip()))
            except ValueError:
                continue
            if number > 0:
                return number
    return None


def _metadata_positive_float(metadata: Mapping[str, object], *keys: str) -> float | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            number = float(value)
            if number > 0:
                return number
            continue
        if isinstance(value, str):
            try:
                number = float(value.strip())
            except ValueError:
                continue
            if number > 0:
                return number
    return None


def _clamped_limit_fields(
    *,
    raw: ExtractionLimits,
    normalized: ExtractionLimits,
) -> list[str]:
    fields = (
        "max_bytes",
        "max_pages",
        "max_media_seconds",
        "max_output_chars",
        "max_tables",
        "parser_timeout_seconds",
        "subprocess_timeout_seconds",
        "max_image_pixels",
        "max_archive_entries",
        "max_archive_uncompressed_bytes",
        "max_archive_compression_ratio",
        "enable_ocr",
        "enable_external_ai",
    )
    return [field for field in fields if getattr(raw, field) != getattr(normalized, field)]


def _should_inspect_zip_container(
    *,
    magic_content_type: str | None,
    detected_content_type: str,
    declared_content_type: str,
    filename: str,
) -> bool:
    if magic_content_type == "application/zip":
        return True
    content_types = {
        _safe_content_type(detected_content_type),
        _safe_content_type(declared_content_type),
    }
    if content_types & _ZIP_CONTAINER_TYPES:
        return True
    extension = filename.rsplit(".", 1)[-1].strip().lower() if "." in filename else ""
    return extension in {"zip", "docx", "pptx", "xlsx", "epub"}


def _unsafe_archive_member_name(name: str) -> bool:
    if not name or "\x00" in name:
        return True
    normalized = name.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(name)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        return True
    return any(part == ".." for part in posix_path.parts)


def _archive_member_is_symlink(info: object) -> bool:
    mode = _archive_member_unix_mode(info)
    return mode is not None and stat.S_ISLNK(mode)


def _archive_member_is_special_file(info: object) -> bool:
    mode = _archive_member_unix_mode(info)
    if mode is None:
        return False
    return any(
        predicate(mode)
        for predicate in (
            stat.S_ISBLK,
            stat.S_ISCHR,
            stat.S_ISFIFO,
            stat.S_ISSOCK,
        )
    )


def _archive_member_unix_mode(info: object) -> int | None:
    external_attr = getattr(info, "external_attr", None)
    if not isinstance(external_attr, int):
        return None
    mode = (external_attr >> 16) & 0xFFFF
    return mode or None


def _archive_duplicate_path_count(names: Iterable[str]) -> int:
    seen: set[str] = set()
    duplicate_count = 0
    for raw_name in names:
        name = _normalized_archive_member_name(raw_name)
        if not name:
            continue
        if name in seen:
            duplicate_count += 1
            continue
        seen.add(name)
    return duplicate_count


def _archive_member_is_nested_archive(name: str) -> bool:
    normalized = _normalized_archive_member_name(name)
    return normalized.endswith(
        (".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".rar", ".7z")
    )


def _normalized_archive_member_name(name: str) -> str:
    normalized = name.replace("\\", "/").strip().casefold()
    parts = [part for part in PurePosixPath(normalized).parts if part not in {"", "."}]
    return "/".join(parts)


def _safe_content_type(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.split(";", 1)[0].strip().lower()
    return text[:160] if text else None
