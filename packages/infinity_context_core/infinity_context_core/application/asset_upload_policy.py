"""Provider-neutral asset upload security policy."""

from __future__ import annotations

import stat
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath, PureWindowsPath

from infinity_context_core.application.safe_payload import safe_metadata_text
from infinity_context_core.domain.errors import MemoryIngressLimitError

UPLOAD_POLICY_VERSION = "asset-upload-policy-v1"
_MAX_FILENAME_CHARS = 240
_MAX_CONTENT_TYPE_CHARS = 120
_MAX_ARCHIVE_ENTRIES = 2_000
_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
_MAX_ARCHIVE_SINGLE_ENTRY_BYTES = 100 * 1024 * 1024
_MAX_ARCHIVE_COMPRESSION_RATIO = 100.0
_ARCHIVE_RATIO_MIN_UNCOMPRESSED_BYTES = 1 * 1024 * 1024
_DEFAULT_MAX_IMAGE_PIXELS = 50_000_000
_BLOCKED_EXTENSIONS = {
    ".app",
    ".bat",
    ".cmd",
    ".com",
    ".dmg",
    ".dll",
    ".exe",
    ".msi",
    ".ps1",
    ".scr",
    ".sh",
}
_BLOCKED_MAGIC_CONTENT_TYPES = {
    "application/x-elf",
    "application/x-mach-binary",
    "application/x-msdownload",
}
_UNKNOWN_MAGIC_CONTENT_TYPE = "application/octet-stream"
_NESTED_ARCHIVE_EXTENSIONS = {
    ".7z",
    ".bz2",
    ".gz",
    ".rar",
    ".tar",
    ".tgz",
    ".xz",
    ".zip",
}
_EXTENSION_CONTENT_TYPES = {
    ".csv": "text/csv",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".gif": "image/gif",
    ".avif": "image/avif",
    ".bmp": "image/bmp",
    ".flac": "audio/flac",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".html": "text/html",
    ".htm": "text/html",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".json": "application/json",
    ".m4a": "audio/mp4",
    ".m4v": "video/mp4",
    ".md": "text/markdown",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".mpeg": "video/mpeg",
    ".mpga": "audio/mpeg",
    ".oga": "audio/ogg",
    ".ogg": "audio/ogg",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".srt": "application/x-subrip",
    ".svg": "image/svg+xml",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".txt": "text/plain",
    ".vtt": "text/vtt",
    ".wav": "audio/wav",
    ".webm": "video/webm",
    ".webp": "image/webp",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xml": "application/xml",
    ".xhtml": "application/xhtml+xml",
    ".zip": "application/zip",
}
_ACTIVE_CONTENT_TYPES = {
    "application/xhtml+xml",
    "application/xml",
    "image/svg+xml",
    "text/html",
    "text/xml",
}
_ACTIVE_CONTENT_EXTENSIONS = {".htm", ".html", ".svg", ".xhtml", ".xml"}
_TEXT_BYTES = set(range(32, 127)) | {9, 10, 13}
_IMAGE_DIMENSION_CONTENT_TYPES = {"image/gif", "image/jpeg", "image/png", "image/webp"}
_JPEG_SOF_MARKERS = frozenset(
    {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
)


@dataclass(frozen=True)
class AssetUploadAssessment:
    declared_content_type: str
    extension_content_type: str | None
    magic_content_type: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class _ImageDimensions:
    width: int
    height: int

    @property
    def pixels(self) -> int:
        return self.width * self.height


def assess_asset_upload(
    *,
    filename: str,
    declared_content_type: str,
    content: bytes,
    max_archive_entries: int = _MAX_ARCHIVE_ENTRIES,
    max_archive_uncompressed_bytes: int = _MAX_ARCHIVE_UNCOMPRESSED_BYTES,
    max_archive_single_entry_bytes: int = _MAX_ARCHIVE_SINGLE_ENTRY_BYTES,
    max_archive_compression_ratio: float = _MAX_ARCHIVE_COMPRESSION_RATIO,
    max_image_pixels: int = _DEFAULT_MAX_IMAGE_PIXELS,
) -> AssetUploadAssessment:
    safe_filename = safe_metadata_text(filename.strip(), limit=_MAX_FILENAME_CHARS)
    if not safe_filename:
        raise MemoryIngressLimitError("Asset filename is required")
    if "\x00" in filename or any(ord(char) < 32 for char in filename):
        raise MemoryIngressLimitError("Asset filename contains control characters")
    if _looks_like_path(filename):
        raise MemoryIngressLimitError("Asset filename must not contain path separators")
    extension = _extension(safe_filename)
    if extension in _BLOCKED_EXTENSIONS:
        raise MemoryIngressLimitError("Asset filename extension is blocked")

    declared = _normalize_content_type(declared_content_type)
    extension_content_type = _EXTENSION_CONTENT_TYPES.get(extension)
    magic_content_type = detect_magic_content_type(content)
    if magic_content_type in _BLOCKED_MAGIC_CONTENT_TYPES:
        raise MemoryIngressLimitError("Asset binary executable content is blocked")
    extension_mismatch = bool(
        extension_content_type
        and magic_content_type != "application/octet-stream"
        and not _content_types_compatible(extension_content_type, magic_content_type)
    )
    declared_mismatch = bool(
        declared
        and not _is_generic_content_type(declared)
        and magic_content_type != "application/octet-stream"
        and not _content_types_compatible(declared, magic_content_type)
    )
    extension_signature_unverified = _strict_expected_unverified(
        expected=extension_content_type,
        magic_content_type=magic_content_type,
    )
    declared_signature_unverified = _strict_expected_unverified(
        expected=declared,
        magic_content_type=magic_content_type,
    )
    if block_reason := _blocked_mime_mismatch_reason(
        declared_content_type=declared,
        extension_content_type=extension_content_type,
        magic_content_type=magic_content_type,
        declared_mismatch=declared_mismatch,
        extension_mismatch=extension_mismatch,
    ):
        raise MemoryIngressLimitError(f"Asset file type mismatch is blocked: {block_reason}")
    archive_detected = magic_content_type == "application/zip"
    archive_review_required = archive_detected and not (
        _is_structured_document_content_type(declared)
        or _is_structured_document_content_type(extension_content_type)
    )
    archive_metadata: dict[str, object] = {}
    if archive_detected:
        archive_metadata = _inspect_zip_archive(
            content,
            max_entries=max_archive_entries,
            max_uncompressed_bytes=max_archive_uncompressed_bytes,
            max_single_entry_bytes=max_archive_single_entry_bytes,
            max_compression_ratio=max_archive_compression_ratio,
        )
        archive_review_required = archive_review_required or bool(
            archive_metadata.get("upload_archive_review_required")
        )
    image_metadata = _inspect_image_payload(
        content,
        content_type=magic_content_type,
        max_image_pixels=max_image_pixels,
    )
    active_content_metadata = _active_content_metadata(
        extension=extension,
        declared_content_type=declared,
        extension_content_type=extension_content_type,
        magic_content_type=magic_content_type,
        content=content,
    )
    metadata = {
        "upload_policy_version": UPLOAD_POLICY_VERSION,
        "upload_declared_content_type": declared or "application/octet-stream",
        "upload_extension": extension or None,
        "upload_extension_content_type": extension_content_type,
        "upload_magic_content_type": magic_content_type,
        "upload_content_type_mismatch": declared_mismatch,
        "upload_extension_mismatch": extension_mismatch,
        "upload_signature_unverified": (
            declared_signature_unverified or extension_signature_unverified
        ),
        "upload_mime_review_required": (
            declared_mismatch
            or extension_mismatch
            or declared_signature_unverified
            or extension_signature_unverified
        ),
        "upload_mime_review_reason": _mime_review_reason(
            declared_mismatch=declared_mismatch,
            extension_mismatch=extension_mismatch,
            declared_signature_unverified=declared_signature_unverified,
            extension_signature_unverified=extension_signature_unverified,
        ),
        "upload_archive_detected": archive_detected,
        "upload_archive_review_required": archive_review_required,
        "upload_dangerous_extension_blocked": False,
        **archive_metadata,
        **image_metadata,
        **active_content_metadata,
    }
    metadata["upload_archive_review_reason"] = _archive_review_reason(
        raw_archive_review_required=archive_detected
        and not (
            _is_structured_document_content_type(declared)
            or _is_structured_document_content_type(extension_content_type)
        ),
        archive_metadata=archive_metadata,
    )
    return AssetUploadAssessment(
        declared_content_type=declared or "application/octet-stream",
        extension_content_type=extension_content_type,
        magic_content_type=magic_content_type,
        metadata=metadata,
    )


def detect_magic_content_type(content: bytes) -> str:
    head = content[:512]
    if head.startswith(b"MZ"):
        return "application/x-msdownload"
    if head.startswith(b"\x7fELF"):
        return "application/x-elf"
    if head.startswith(
        (
            b"\xfe\xed\xfa\xce",
            b"\xce\xfa\xed\xfe",
            b"\xfe\xed\xfa\xcf",
            b"\xcf\xfa\xed\xfe",
            b"\xca\xfe\xba\xbe",
            b"\xbe\xba\xfe\xca",
        )
    ):
        return "application/x-mach-binary"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "audio/wav"
    if head.startswith(b"fLaC"):
        return "audio/flac"
    if head.startswith(b"OggS"):
        return "audio/ogg"
    if head.startswith(b"ID3") or _looks_like_mp3_frame(head):
        return "audio/mpeg"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return _ftyp_content_type(content) or "video/mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm" if b"webm" in content[:256].lower() else "video/x-matroska"
    if head.startswith(b"PK\x03\x04"):
        return "application/zip"
    if active_markup_content_type := _detect_active_markup_content_type(content):
        return active_markup_content_type
    if head[:16].lstrip().startswith((b"{", b"[")):
        return "application/json"
    if _looks_like_text(head):
        return "text/plain"
    return "application/octet-stream"


def _active_content_metadata(
    *,
    extension: str,
    declared_content_type: str,
    extension_content_type: str | None,
    magic_content_type: str,
    content: bytes,
) -> dict[str, object]:
    content_signature_type = _detect_active_markup_content_type(content)
    signals: list[str] = []
    if extension in _ACTIVE_CONTENT_EXTENSIONS:
        signals.append("filename_extension")
    if declared_content_type in _ACTIVE_CONTENT_TYPES:
        signals.append("declared_content_type")
    if extension_content_type in _ACTIVE_CONTENT_TYPES:
        signals.append("extension_content_type")
    if magic_content_type in _ACTIVE_CONTENT_TYPES:
        signals.append("magic_content_type")
    if content_signature_type in _ACTIVE_CONTENT_TYPES:
        signals.append("content_signature")
    signals = list(dict.fromkeys(signals))
    content_type = (
        content_signature_type
        if content_signature_type in _ACTIVE_CONTENT_TYPES
        else magic_content_type
        if magic_content_type in _ACTIVE_CONTENT_TYPES
        else extension_content_type
        if extension_content_type in _ACTIVE_CONTENT_TYPES
        else declared_content_type
        if declared_content_type in _ACTIVE_CONTENT_TYPES
        else None
    )
    return {
        "upload_active_content_detected": bool(signals),
        "upload_active_content_review_required": bool(signals),
        "upload_active_content_kind": _active_content_kind(content_type),
        "upload_active_content_content_type": content_type,
        "upload_active_content_signals": signals,
        "upload_active_content_review_reason": (
            "active_markup_content" if signals else None
        ),
    }


def _detect_active_markup_content_type(content: bytes) -> str | None:
    sample = content[:4096].decode("utf-8", errors="ignore").lstrip("\ufeff \t\r\n")
    if not sample:
        return None
    lowered = sample.lower()
    if "<svg" in lowered[:512]:
        return "image/svg+xml"
    if lowered.startswith("<!doctype html") or lowered.startswith("<html") or (
        "<html" in lowered[:512]
    ):
        return "text/html"
    if lowered.startswith("<?xml"):
        return "application/xml"
    return None


def _active_content_kind(content_type: str | None) -> str | None:
    if content_type == "image/svg+xml":
        return "svg"
    if content_type in {"text/html", "application/xhtml+xml"}:
        return "html"
    if content_type in {"application/xml", "text/xml"}:
        return "xml"
    return None


def _inspect_zip_archive(
    content: bytes,
    *,
    max_entries: int,
    max_uncompressed_bytes: int,
    max_single_entry_bytes: int,
    max_compression_ratio: float,
) -> dict[str, object]:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
    except (zipfile.BadZipFile, RuntimeError, OSError):
        return {
            "upload_archive_inspection_status": "invalid",
            "upload_archive_review_required": True,
            "upload_archive_review_reason": "zip_archive_invalid",
        }

    entry_count = len(entries)
    file_entries = [entry for entry in entries if not entry.is_dir()]
    total_uncompressed = sum(max(0, int(entry.file_size)) for entry in file_entries)
    total_compressed = sum(max(0, int(entry.compress_size)) for entry in file_entries)
    max_entry_size = max((max(0, int(entry.file_size)) for entry in file_entries), default=0)
    max_ratio = _max_archive_compression_ratio(file_entries)
    dangerous_paths = tuple(
        entry.filename for entry in entries if _archive_path_is_unsafe(entry.filename)
    )
    nested_entries = tuple(
        entry.filename
        for entry in file_entries
        if _extension(entry.filename) in _NESTED_ARCHIVE_EXTENSIONS
    )
    symlink_entries = tuple(
        entry.filename for entry in file_entries if _archive_entry_is_symlink(entry)
    )
    special_entries = tuple(
        entry.filename for entry in file_entries if _archive_entry_is_special_file(entry)
    )
    encrypted_count = sum(1 for entry in file_entries if entry.flag_bits & 0x1)
    duplicate_path_count = _archive_duplicate_path_count(entry.filename for entry in file_entries)
    metadata = {
        "upload_archive_inspection_status": "ok",
        "upload_archive_entry_count": entry_count,
        "upload_archive_file_count": len(file_entries),
        "upload_archive_directory_count": entry_count - len(file_entries),
        "upload_archive_uncompressed_bytes": total_uncompressed,
        "upload_archive_compressed_bytes": total_compressed,
        "upload_archive_max_entry_uncompressed_bytes": max_entry_size,
        "upload_archive_max_compression_ratio": round(max_ratio, 3),
        "upload_archive_encrypted_entry_count": encrypted_count,
        "upload_archive_nested_archive_count": len(nested_entries),
        "upload_archive_symlink_entry_count": len(symlink_entries),
        "upload_archive_special_entry_count": len(special_entries),
        "upload_archive_unsafe_path_count": len(dangerous_paths),
        "upload_archive_duplicate_path_count": duplicate_path_count,
        "upload_archive_limits": {
            "max_entries": max_entries,
            "max_uncompressed_bytes": max_uncompressed_bytes,
            "max_single_entry_bytes": max_single_entry_bytes,
            "max_compression_ratio": max_compression_ratio,
        },
    }
    if dangerous_paths:
        raise MemoryIngressLimitError("Asset archive contains unsafe paths")
    if symlink_entries:
        raise MemoryIngressLimitError("Asset archive contains symbolic links")
    if special_entries:
        raise MemoryIngressLimitError("Asset archive contains special file entries")
    if entry_count > max_entries:
        raise MemoryIngressLimitError("Asset archive exceeds configured entry limit")
    if max_entry_size > max_single_entry_bytes:
        raise MemoryIngressLimitError("Asset archive entry exceeds configured size limit")
    if total_uncompressed > max_uncompressed_bytes:
        raise MemoryIngressLimitError("Asset archive uncompressed size exceeds configured limit")
    if (
        max_ratio > max_compression_ratio
        and total_uncompressed >= _ARCHIVE_RATIO_MIN_UNCOMPRESSED_BYTES
    ):
        raise MemoryIngressLimitError("Asset archive compression ratio exceeds configured limit")
    if nested_entries or encrypted_count or duplicate_path_count:
        metadata["upload_archive_review_required"] = True
        metadata["upload_archive_review_reason"] = _archive_review_reason_from_flags(
            encrypted_count=encrypted_count,
            nested_archive_count=len(nested_entries),
            duplicate_path_count=duplicate_path_count,
        )
    return metadata


def _inspect_image_payload(
    content: bytes,
    *,
    content_type: str,
    max_image_pixels: int,
) -> dict[str, object]:
    if not content_type.startswith("image/"):
        return {
            "upload_image_detected": False,
            "upload_image_inspection_status": None,
            "upload_image_review_required": False,
        }

    normalized_limit = max(1, int(max_image_pixels))
    metadata: dict[str, object] = {
        "upload_image_detected": True,
        "upload_image_content_type": content_type,
        "upload_image_max_pixels": normalized_limit,
        "upload_image_review_required": False,
    }
    if content_type not in _IMAGE_DIMENSION_CONTENT_TYPES:
        return {
            **metadata,
            "upload_image_inspection_status": "unsupported_content_type",
        }

    dimensions = _image_dimensions(content, content_type=content_type)
    if dimensions is None:
        raise MemoryIngressLimitError("Asset image dimensions could not be read")
    if dimensions.width <= 0 or dimensions.height <= 0:
        raise MemoryIngressLimitError("Asset image dimensions are invalid")
    if dimensions.pixels > normalized_limit:
        raise MemoryIngressLimitError("Asset image pixel count exceeds configured limit")
    return {
        **metadata,
        "upload_image_inspection_status": "ok",
        "upload_image_width": dimensions.width,
        "upload_image_height": dimensions.height,
        "upload_image_pixels": dimensions.pixels,
    }


def _image_dimensions(content: bytes, *, content_type: str) -> _ImageDimensions | None:
    if content_type == "image/png":
        return _png_dimensions(content)
    if content_type == "image/gif":
        return _gif_dimensions(content)
    if content_type == "image/jpeg":
        return _jpeg_dimensions(content)
    if content_type == "image/webp":
        return _webp_dimensions(content)
    return None


def _png_dimensions(content: bytes) -> _ImageDimensions | None:
    if len(content) < 24 or not content.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    if content[12:16] != b"IHDR":
        return None
    return _ImageDimensions(
        width=int.from_bytes(content[16:20], "big"),
        height=int.from_bytes(content[20:24], "big"),
    )


def _gif_dimensions(content: bytes) -> _ImageDimensions | None:
    if len(content) < 10 or not content.startswith((b"GIF87a", b"GIF89a")):
        return None
    return _ImageDimensions(
        width=int.from_bytes(content[6:8], "little"),
        height=int.from_bytes(content[8:10], "little"),
    )


def _jpeg_dimensions(content: bytes) -> _ImageDimensions | None:
    if len(content) < 4 or not content.startswith(b"\xff\xd8"):
        return None
    offset = 2
    while offset < len(content):
        while offset < len(content) and content[offset] == 0xFF:
            offset += 1
        if offset >= len(content):
            return None
        marker = content[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if marker == 0xDA:
            return None
        if offset + 2 > len(content):
            return None
        segment_length = int.from_bytes(content[offset : offset + 2], "big")
        if segment_length < 2:
            return None
        segment_start = offset + 2
        segment_end = offset + segment_length
        if segment_end > len(content):
            return None
        if marker in _JPEG_SOF_MARKERS:
            if segment_length < 7:
                return None
            height = int.from_bytes(content[segment_start + 1 : segment_start + 3], "big")
            width = int.from_bytes(content[segment_start + 3 : segment_start + 5], "big")
            return _ImageDimensions(width=width, height=height)
        offset = segment_end
    return None


def _webp_dimensions(content: bytes) -> _ImageDimensions | None:
    if len(content) < 20 or not (content.startswith(b"RIFF") and content[8:12] == b"WEBP"):
        return None
    offset = 12
    while offset + 8 <= len(content):
        chunk_type = content[offset : offset + 4]
        chunk_size = int.from_bytes(content[offset + 4 : offset + 8], "little")
        chunk_start = offset + 8
        chunk_end = chunk_start + chunk_size
        if chunk_end > len(content):
            return None
        chunk = content[chunk_start:chunk_end]
        if chunk_type == b"VP8X":
            return _webp_vp8x_dimensions(chunk)
        if chunk_type == b"VP8L":
            return _webp_vp8l_dimensions(chunk)
        if chunk_type == b"VP8 ":
            return _webp_vp8_dimensions(chunk)
        offset = chunk_end + (chunk_size % 2)
    return None


def _webp_vp8x_dimensions(chunk: bytes) -> _ImageDimensions | None:
    if len(chunk) < 10:
        return None
    return _ImageDimensions(
        width=int.from_bytes(chunk[4:7], "little") + 1,
        height=int.from_bytes(chunk[7:10], "little") + 1,
    )


def _webp_vp8l_dimensions(chunk: bytes) -> _ImageDimensions | None:
    if len(chunk) < 5 or chunk[0] != 0x2F:
        return None
    b0, b1, b2, b3 = chunk[1], chunk[2], chunk[3], chunk[4]
    width = 1 + (((b1 & 0x3F) << 8) | b0)
    height = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
    return _ImageDimensions(width=width, height=height)


def _webp_vp8_dimensions(chunk: bytes) -> _ImageDimensions | None:
    if len(chunk) < 10 or chunk[3:6] != b"\x9d\x01\x2a":
        return None
    return _ImageDimensions(
        width=int.from_bytes(chunk[6:8], "little") & 0x3FFF,
        height=int.from_bytes(chunk[8:10], "little") & 0x3FFF,
    )


def _looks_like_path(filename: str) -> bool:
    if "/" in filename or "\\" in filename:
        return True
    if PurePosixPath(filename).name != filename:
        return True
    return PureWindowsPath(filename).name != filename


def _extension(filename: str) -> str:
    name = filename.rsplit(".", 1)
    return f".{name[1].lower()}" if len(name) == 2 and name[1] else ""


def _archive_path_is_unsafe(filename: str) -> bool:
    if "\x00" in filename:
        return True
    windows_path = PureWindowsPath(filename)
    if windows_path.drive or windows_path.is_absolute():
        return True
    normalized = filename.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
        return True
    parts = PurePosixPath(normalized).parts
    return any(part in {"", ".", ".."} for part in parts)


def _max_archive_compression_ratio(entries: Iterable[zipfile.ZipInfo]) -> float:
    max_ratio = 0.0
    for entry in entries:
        file_size = max(0, int(entry.file_size))
        compressed_size = max(0, int(entry.compress_size))
        if file_size <= 0:
            continue
        ratio = float("inf") if compressed_size <= 0 else file_size / compressed_size
        max_ratio = max(max_ratio, ratio)
    return max_ratio


def _archive_duplicate_path_count(filenames: Iterable[str]) -> int:
    seen: set[str] = set()
    duplicates = 0
    for filename in filenames:
        normalized = _archive_member_identity(filename)
        if not normalized:
            continue
        if normalized in seen:
            duplicates += 1
            continue
        seen.add(normalized)
    return duplicates


def _archive_entry_is_symlink(entry: zipfile.ZipInfo) -> bool:
    return _archive_entry_unix_file_type(entry) == stat.S_IFLNK


def _archive_entry_is_special_file(entry: zipfile.ZipInfo) -> bool:
    file_type = _archive_entry_unix_file_type(entry)
    if file_type is None:
        return False
    return file_type not in {stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK}


def _archive_entry_unix_file_type(entry: zipfile.ZipInfo) -> int | None:
    mode = (entry.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    return file_type or None


def _archive_member_identity(filename: str) -> str:
    normalized = filename.replace("\\", "/")
    parts = [part for part in PurePosixPath(normalized).parts if part not in {"", "."}]
    return "/".join(parts).casefold()


def _archive_review_reason_from_flags(
    *,
    encrypted_count: int,
    nested_archive_count: int,
    duplicate_path_count: int,
) -> str:
    if encrypted_count:
        return "zip_archive_contains_encrypted_entries"
    if nested_archive_count:
        return "zip_archive_contains_nested_archives"
    if duplicate_path_count:
        return "zip_archive_contains_duplicate_paths"
    return "zip_archive_requires_review"


def _archive_review_reason(
    *,
    raw_archive_review_required: bool,
    archive_metadata: dict[str, object],
) -> str | None:
    if reason := archive_metadata.get("upload_archive_review_reason"):
        return str(reason)
    return "zip_archive_not_structured_document" if raw_archive_review_required else None


def _normalize_content_type(value: str) -> str:
    normalized = value.split(";", 1)[0].strip().lower()
    return safe_metadata_text(normalized, limit=_MAX_CONTENT_TYPE_CHARS)


def _content_types_compatible(expected: str, actual: str) -> bool:
    expected = _normalize_content_type(expected)
    actual = _normalize_content_type(actual)
    if expected == actual:
        return True
    pairs = {
        ("audio/mp4", "video/mp4"),
        ("video/mp4", "audio/mp4"),
        ("video/mp4", "video/quicktime"),
        ("video/quicktime", "video/mp4"),
        ("application/json", "text/plain"),
        ("text/plain", "application/json"),
    }
    if (expected, actual) in pairs:
        return True
    if expected.startswith("text/") and actual == "text/plain":
        return True
    return _is_structured_document_content_type(expected) and actual == "application/zip"


def _blocked_mime_mismatch_reason(
    *,
    declared_content_type: str,
    extension_content_type: str | None,
    magic_content_type: str,
    declared_mismatch: bool,
    extension_mismatch: bool,
) -> str | None:
    if (
        extension_mismatch
        and _is_strict_magic_content_type(extension_content_type)
        and _is_strict_magic_content_type(magic_content_type)
    ):
        return "extension_signature_mismatch"
    if (
        declared_mismatch
        and _is_strict_magic_content_type(declared_content_type)
        and _is_strict_magic_content_type(magic_content_type)
        and not _content_types_compatible(extension_content_type or "", magic_content_type)
    ):
        return "declared_signature_mismatch"
    return None


def _strict_expected_unverified(
    *,
    expected: str | None,
    magic_content_type: str,
) -> bool:
    return bool(
        expected
        and not _is_generic_content_type(expected)
        and _is_strict_magic_content_type(expected)
        and magic_content_type == _UNKNOWN_MAGIC_CONTENT_TYPE
    )


def _is_generic_content_type(value: str | None) -> bool:
    return _normalize_content_type(value or "") == _UNKNOWN_MAGIC_CONTENT_TYPE


def _is_strict_magic_content_type(value: str | None) -> bool:
    content_type = _normalize_content_type(value or "")
    return bool(
        content_type == "application/pdf"
        or content_type == "application/zip"
        or content_type.startswith(("image/", "audio/", "video/"))
        or _is_structured_document_content_type(content_type)
    )


def _mime_review_reason(
    *,
    declared_mismatch: bool,
    extension_mismatch: bool,
    declared_signature_unverified: bool,
    extension_signature_unverified: bool,
) -> str | None:
    if declared_mismatch and extension_mismatch:
        return "declared_and_extension_mismatch"
    if declared_mismatch:
        return "declared_content_type_mismatch"
    if extension_mismatch:
        return "extension_content_type_mismatch"
    if declared_signature_unverified and extension_signature_unverified:
        return "declared_and_extension_signature_unverified"
    if declared_signature_unverified:
        return "declared_signature_unverified"
    if extension_signature_unverified:
        return "extension_signature_unverified"
    return None


def _is_structured_document_content_type(value: str | None) -> bool:
    return value in _STRUCTURED_DOCUMENT_CONTAINER_TYPES


def _looks_like_mp3_frame(head: bytes) -> bool:
    return len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0


def _ftyp_content_type(content: bytes) -> str | None:
    brands = _ftyp_brands(content)
    if not brands:
        return None
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
    if len(content) < 12 or content[4:8] != b"ftyp":
        return set()
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


def _looks_like_text(head: bytes) -> bool:
    if not head:
        return False
    sample = head[:256]
    if b"\x00" in sample:
        return False
    printable = sum(1 for byte in sample if byte in _TEXT_BYTES)
    return printable / len(sample) >= 0.85


_STRUCTURED_DOCUMENT_CONTAINER_TYPES = {
    "application/epub+zip",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "message/rfc822",
}
