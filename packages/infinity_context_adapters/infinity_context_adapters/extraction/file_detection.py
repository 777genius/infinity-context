"""File type detection helpers for local content extraction adapters."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.ports.extraction import (
    FileTypeDetectionRequest,
    FileTypeDetectionResult,
    FileTypeDetectorPort,
)

_TEXT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/html",
    "application/json",
}
_TEXT_HEURISTIC_TYPES = {"application/octet-stream"}
_PDF_TYPES = {"application/pdf"}
_STRUCTURED_DOCUMENT_TYPES = {
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/epub+zip",
    "message/rfc822",
}
_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/tiff",
}
_TIMED_TEXT_TYPES = {
    "application/x-subrip",
    "text/vtt",
}
_AUDIO_TYPES = {
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
}
_VIDEO_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-matroska",
}
_MEDIA_TYPES = _AUDIO_TYPES | _VIDEO_TYPES
_GENERIC_CONTENT_TYPES = {
    "",
    "application/octet-stream",
    "binary/octet-stream",
    "application/x-binary",
}
_TEXT_MAGIC_OVERRIDE_TYPES = _TEXT_TYPES | _TIMED_TEXT_TYPES


class SimpleFileTypeDetector(FileTypeDetectorPort):
    async def detect(self, request: FileTypeDetectionRequest) -> FileTypeDetectionResult:
        declared = _normalize_content_type(request.declared_content_type)
        extension = _extension(request.filename)
        magic_type = _magic_content_type(request.content)
        extension_type = _extension_content_type(extension)
        choice = _choose_detected_content_type(
            magic_type=magic_type,
            extension_type=extension_type,
            declared_type=declared,
        )
        confidence = _detection_confidence(
            choice=choice,
            magic_type=magic_type,
            extension_type=extension_type,
            declared_type=declared,
        )
        return FileTypeDetectionResult(
            content_type=choice.content_type or "application/octet-stream",
            extension=extension,
            confidence=confidence,
            diagnostics=_detection_diagnostics(
                choice=choice,
                declared_type=declared,
                extension=extension,
                extension_type=extension_type,
                magic_type=magic_type,
                byte_size=len(request.content),
                confidence=confidence,
            ),
        )


@dataclass(frozen=True)
class _ContentTypeChoice:
    content_type: str
    reason: str


def _normalize_content_type(value: str) -> str:
    return (value or "application/octet-stream").split(";")[0].strip().lower()


def _extension(filename: str) -> str | None:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return suffix or None


def _choose_detected_content_type(
    *,
    magic_type: str | None,
    extension_type: str | None,
    declared_type: str,
) -> _ContentTypeChoice:
    if extension_type and _extension_should_override_magic(
        magic_type=magic_type,
        extension_type=extension_type,
    ):
        reason = (
            "extension_overrides_zip_magic"
            if magic_type == "application/zip"
            else "extension_overrides_magic"
        )
        return _ContentTypeChoice(content_type=extension_type, reason=reason)
    if _declared_should_override_magic(
        magic_type=magic_type,
        declared_type=declared_type,
    ):
        return _ContentTypeChoice(
            content_type=declared_type,
            reason="declared_text_subtype",
        )
    if magic_type:
        return _ContentTypeChoice(content_type=magic_type, reason="magic")
    if extension_type:
        return _ContentTypeChoice(content_type=extension_type, reason="extension")
    return _ContentTypeChoice(content_type=declared_type, reason="declared")


def _declared_should_override_magic(
    *,
    magic_type: str | None,
    declared_type: str,
) -> bool:
    if magic_type != "text/plain":
        return False
    return declared_type in _TEXT_MAGIC_OVERRIDE_TYPES


def _extension_should_override_magic(
    *,
    magic_type: str | None,
    extension_type: str,
) -> bool:
    if magic_type is None:
        return True
    if magic_type == "text/plain" and extension_type in _TEXT_MAGIC_OVERRIDE_TYPES:
        return True
    if magic_type == "application/zip" and extension_type in _STRUCTURED_DOCUMENT_TYPES:
        return True
    return magic_type == "video/mp4" and extension_type == "audio/mp4"


def _detection_confidence(
    *,
    choice: _ContentTypeChoice,
    magic_type: str | None,
    extension_type: str | None,
    declared_type: str,
) -> str:
    if choice.content_type in _GENERIC_CONTENT_TYPES:
        return "low"
    if choice.reason == "magic":
        return "high"
    if choice.reason in {
        "extension_overrides_zip_magic",
        "extension_overrides_magic",
    }:
        return "high" if magic_type is not None else "medium"
    if choice.reason == "declared_text_subtype":
        return "medium"
    if choice.reason == "extension":
        return "medium"
    if declared_type == choice.content_type and declared_type not in _GENERIC_CONTENT_TYPES:
        return "low"
    if extension_type and extension_type == choice.content_type:
        return "medium"
    return "low"


def _detection_diagnostics(
    *,
    choice: _ContentTypeChoice,
    declared_type: str,
    extension: str | None,
    extension_type: str | None,
    magic_type: str | None,
    byte_size: int,
    confidence: str,
) -> dict[str, object]:
    declared_mismatch = (
        declared_type not in _GENERIC_CONTENT_TYPES and declared_type != choice.content_type
    )
    magic_mismatch = magic_type is not None and magic_type != choice.content_type
    extension_mismatch = extension_type is not None and extension_type != choice.content_type
    archive_detected = magic_type == "application/zip"
    archive_review_required = archive_detected and not _is_structured_archive_choice(
        choice=choice,
        declared_type=declared_type,
        extension_type=extension_type,
    )
    diagnostics: dict[str, object] = {
        "mime_declared_content_type": declared_type,
        "mime_detected_content_type": choice.content_type,
        "mime_detector_confidence": confidence,
        "mime_detector_reason": choice.reason,
        "mime_content_type_mismatch": declared_mismatch,
        "mime_magic_mismatch": magic_mismatch,
        "mime_extension_mismatch": extension_mismatch,
        "mime_archive_detected": archive_detected,
        "mime_archive_review_required": archive_review_required,
        "asset_empty_content": byte_size == 0,
    }
    if archive_review_required:
        diagnostics["mime_archive_review_reason"] = "zip_archive_not_structured_document"
    if magic_type is not None:
        diagnostics["mime_magic_content_type"] = magic_type
    if extension is not None:
        diagnostics["mime_filename_extension"] = extension
    if extension_type is not None:
        diagnostics["mime_extension_content_type"] = extension_type
    if declared_mismatch:
        diagnostics["mime_mismatch_kind"] = "declared_vs_detected"
    return diagnostics


def _is_structured_archive_choice(
    *,
    choice: _ContentTypeChoice,
    declared_type: str,
    extension_type: str | None,
) -> bool:
    return (
        choice.content_type in _STRUCTURED_DOCUMENT_TYPES
        or declared_type in _STRUCTURED_DOCUMENT_TYPES
        or extension_type in _STRUCTURED_DOCUMENT_TYPES
    )


def _extension_content_type(extension: str | None) -> str | None:
    return {
        "txt": "text/plain",
        "md": "text/markdown",
        "markdown": "text/markdown",
        "csv": "text/csv",
        "html": "text/html",
        "htm": "text/html",
        "json": "application/json",
        "pdf": "application/pdf",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "ppt": "application/vnd.ms-powerpoint",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "xls": "application/vnd.ms-excel",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "epub": "application/epub+zip",
        "eml": "message/rfc822",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "avif": "image/avif",
        "heic": "image/heic",
        "heif": "image/heif",
        "webp": "image/webp",
        "bmp": "image/bmp",
        "tif": "image/tiff",
        "tiff": "image/tiff",
        "srt": "application/x-subrip",
        "vtt": "text/vtt",
        "mp3": "audio/mpeg",
        "mpeg": "audio/mpeg",
        "mpga": "audio/mpga",
        "m4a": "audio/mp4",
        "wav": "audio/wav",
        "flac": "audio/flac",
        "ogg": "audio/ogg",
        "oga": "audio/ogg",
        "mp4": "video/mp4",
        "m4v": "video/mp4",
        "mov": "video/quicktime",
        "webm": "video/webm",
        "mkv": "video/x-matroska",
    }.get(extension or "")


def _magic_content_type(content: bytes) -> str | None:
    prefix = content[:16]
    if prefix.startswith(b"%PDF"):
        return "application/pdf"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if prefix.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if prefix.startswith(b"GIF87a") or prefix.startswith(b"GIF89a"):
        return "image/gif"
    if content[:12].startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    if content[:12].startswith(b"RIFF") and content[8:12] == b"WAVE":
        return "audio/wav"
    if prefix.startswith(b"fLaC"):
        return "audio/flac"
    if prefix.startswith(b"OggS"):
        return "audio/ogg"
    if prefix.startswith(b"ID3") or prefix[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
        return "audio/mpeg"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        return _ftyp_content_type(content)
    if prefix.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm" if b"webm" in content[:256].lower() else "video/x-matroska"
    if prefix.startswith(b"PK\x03\x04"):
        return "application/zip"
    if _looks_like_utf8_text(content):
        return "text/plain"
    return None


def _looks_like_utf8_text(content: bytes) -> bool:
    if not content:
        return False
    try:
        text = content[:4096].decode("utf-8")
    except UnicodeDecodeError:
        return False
    if "\x00" in text:
        return False
    printable = sum(1 for ch in text if ch.isprintable() or ch.isspace())
    return printable / max(1, len(text)) > 0.92


def _ftyp_content_type(content: bytes) -> str:
    brands = _ftyp_brands(content)
    if brands & {"avif", "avis"}:
        return "image/avif"
    if brands & {"heic", "heix", "hevc", "hevx"}:
        return "image/heic"
    if brands & {"mif1", "msf1"}:
        return "image/heif"
    if brands & {"qt"}:
        return "video/quicktime"
    if brands & {"m4a"}:
        return "audio/mp4"
    return "video/mp4"


def _ftyp_brands(content: bytes) -> set[str]:
    brands: set[str] = set()
    brand_bytes = content[8:32]
    for index in range(0, len(brand_bytes), 4):
        raw = brand_bytes[index : index + 4]
        if len(raw) < 4:
            continue
        brand = raw.decode("ascii", errors="ignore").strip().lower()
        if brand:
            brands.add(brand)
    return brands
