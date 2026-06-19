import stat
import zipfile
from io import BytesIO

import pytest
from infinity_context_core.application.asset_upload_policy import (
    UPLOAD_POLICY_VERSION,
    assess_asset_upload,
    detect_magic_content_type,
)
from infinity_context_core.domain.errors import MemoryIngressLimitError


def test_upload_policy_detects_magic_content_types() -> None:
    assert detect_magic_content_type(b"%PDF-1.7\n") == "application/pdf"
    assert detect_magic_content_type(b"\x89PNG\r\n\x1a\npayload") == "image/png"
    assert detect_magic_content_type(b"RIFF\x10\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert detect_magic_content_type(b"RIFF\x24\x00\x00\x00WAVEfmt ") == "audio/wav"
    assert detect_magic_content_type(b"fLaC\x00\x00\x00\x22") == "audio/flac"
    assert detect_magic_content_type(b"OggS\x00\x02audio") == "audio/ogg"
    assert detect_magic_content_type(b"\x00\x00\x00\x18ftypmp42") == "video/mp4"
    assert detect_magic_content_type(b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00") == "audio/mp4"
    assert detect_magic_content_type(b"\x00\x00\x00\x18ftypqt  \x00\x00\x00\x00") == (
        "video/quicktime"
    )
    assert detect_magic_content_type(b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00") == (
        "image/avif"
    )
    assert detect_magic_content_type(b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00") == (
        "image/heic"
    )
    assert detect_magic_content_type(b"\x1a\x45\xdf\xa3\x00\x00webm") == "video/webm"
    assert detect_magic_content_type(b"plain text body") == "text/plain"
    assert detect_magic_content_type(b"MZ\x90\x00renamed exe") == "application/x-msdownload"
    assert detect_magic_content_type(b"\x7fELF\x02\x01\x01") == "application/x-elf"
    assert detect_magic_content_type(b"\xcf\xfa\xed\xfe\x07\x00\x00\x01") == (
        "application/x-mach-binary"
    )


def test_upload_policy_reports_declared_and_extension_mismatch() -> None:
    result = assess_asset_upload(
        filename="screenshot.png",
        declared_content_type="image/png",
        content=b"plain text body",
    )

    assert result.metadata["upload_policy_version"] == UPLOAD_POLICY_VERSION
    assert result.metadata["upload_extension_content_type"] == "image/png"
    assert result.metadata["upload_magic_content_type"] == "text/plain"
    assert result.metadata["upload_content_type_mismatch"] is True
    assert result.metadata["upload_extension_mismatch"] is True
    assert result.metadata["upload_mime_review_required"] is True
    assert result.metadata["upload_mime_review_reason"] == "declared_and_extension_mismatch"


def test_upload_policy_rejects_binary_signature_spoofed_as_image() -> None:
    with pytest.raises(MemoryIngressLimitError, match="extension_signature_mismatch"):
        assess_asset_upload(
            filename="screenshot.png",
            declared_content_type="image/png",
            content=b"%PDF-1.7\nnot a png",
        )


def test_upload_policy_marks_unverified_strict_binary_extension_for_review() -> None:
    result = assess_asset_upload(
        filename="screenshot.png",
        declared_content_type="application/octet-stream",
        content=b"\x00\x01\x02\x03unknown binary payload",
    )

    assert result.magic_content_type == "application/octet-stream"
    assert result.metadata["upload_signature_unverified"] is True
    assert result.metadata["upload_mime_review_required"] is True
    assert result.metadata["upload_mime_review_reason"] == "extension_signature_unverified"


def test_upload_policy_maps_flac_extension_to_audio_content_type() -> None:
    result = assess_asset_upload(
        filename="voice-note.flac",
        declared_content_type="application/octet-stream",
        content=b"fLaC\x00\x00\x00\x22",
    )

    assert result.metadata["upload_extension_content_type"] == "audio/flac"
    assert result.metadata["upload_magic_content_type"] == "audio/flac"
    assert result.extension_content_type == "audio/flac"
    assert result.magic_content_type == "audio/flac"


@pytest.mark.parametrize(
    "content",
    [
        b"MZ\x90\x00renamed exe",
        b"\x7fELF\x02\x01\x01",
        b"\xcf\xfa\xed\xfe\x07\x00\x00\x01",
    ],
)
def test_upload_policy_rejects_binary_executable_magic(content: bytes) -> None:
    with pytest.raises(MemoryIngressLimitError, match="binary executable"):
        assess_asset_upload(
            filename="meeting-notes.txt",
            declared_content_type="text/plain",
            content=content,
        )


def test_upload_policy_records_image_dimensions_without_decoding() -> None:
    result = assess_asset_upload(
        filename="screenshot.png",
        declared_content_type="image/png",
        content=_png_bytes(width=320, height=200),
    )

    assert result.metadata["upload_image_detected"] is True
    assert result.metadata["upload_image_inspection_status"] == "ok"
    assert result.metadata["upload_image_width"] == 320
    assert result.metadata["upload_image_height"] == 200
    assert result.metadata["upload_image_pixels"] == 64_000
    assert result.metadata["upload_image_max_pixels"] == 50_000_000


def test_upload_policy_rejects_image_pixel_bomb() -> None:
    with pytest.raises(MemoryIngressLimitError, match="pixel count"):
        assess_asset_upload(
            filename="huge-screenshot.png",
            declared_content_type="image/png",
            content=_png_bytes(width=100_000, height=100_000),
            max_image_pixels=50_000_000,
        )


def test_upload_policy_rejects_corrupted_magic_image_header() -> None:
    with pytest.raises(MemoryIngressLimitError, match="dimensions"):
        assess_asset_upload(
            filename="broken-screenshot.png",
            declared_content_type="image/png",
            content=b"\x89PNG\r\n\x1a\ntruncated",
        )


@pytest.mark.parametrize(
    ("filename", "kind", "expected_width", "expected_height"),
    [
        ("photo.jpg", "jpeg", 640, 480),
        ("animation.gif", "gif", 32, 24),
        ("capture.webp", "webp", 1024, 768),
    ],
)
def test_upload_policy_reads_common_image_dimensions(
    filename: str,
    kind: str,
    expected_width: int,
    expected_height: int,
) -> None:
    content = {
        "jpeg": _jpeg_bytes,
        "gif": _gif_bytes,
        "webp": _webp_vp8x_bytes,
    }[kind](width=expected_width, height=expected_height)

    result = assess_asset_upload(
        filename=filename,
        declared_content_type="application/octet-stream",
        content=content,
    )

    assert result.metadata["upload_image_inspection_status"] == "ok"
    assert result.metadata["upload_image_width"] == expected_width
    assert result.metadata["upload_image_height"] == expected_height


def test_upload_policy_marks_non_document_zip_archive_for_review() -> None:
    result = assess_asset_upload(
        filename="payload.zip",
        declared_content_type="application/zip",
        content=_zip_bytes({"notes.txt": b"hello"}),
    )

    assert result.metadata["upload_magic_content_type"] == "application/zip"
    assert result.metadata["upload_archive_detected"] is True
    assert result.metadata["upload_archive_review_required"] is True
    assert result.metadata["upload_archive_review_reason"] == "zip_archive_not_structured_document"
    assert result.metadata["upload_archive_inspection_status"] == "ok"
    assert result.metadata["upload_archive_entry_count"] == 1
    assert result.metadata["upload_archive_uncompressed_bytes"] == 5


def test_upload_policy_keeps_office_zip_container_without_archive_review() -> None:
    result = assess_asset_upload(
        filename="meeting-notes.docx",
        declared_content_type="application/octet-stream",
        content=_zip_bytes({"[Content_Types].xml": b"<Types />", "word/document.xml": b"<w />"}),
    )

    assert result.metadata["upload_magic_content_type"] == "application/zip"
    assert result.metadata["upload_archive_detected"] is True
    assert result.metadata["upload_archive_review_required"] is False
    assert result.metadata["upload_archive_inspection_status"] == "ok"


def test_upload_policy_marks_invalid_zip_for_review_without_crashing() -> None:
    result = assess_asset_upload(
        filename="meeting-notes.docx",
        declared_content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=b"PK\x03\x04not actually a valid zip central directory",
    )

    assert result.metadata["upload_archive_detected"] is True
    assert result.metadata["upload_archive_inspection_status"] == "invalid"
    assert result.metadata["upload_archive_review_required"] is True
    assert result.metadata["upload_archive_review_reason"] == "zip_archive_invalid"


def test_upload_policy_rejects_archive_path_traversal() -> None:
    with pytest.raises(MemoryIngressLimitError, match="unsafe paths"):
        assess_asset_upload(
            filename="payload.zip",
            declared_content_type="application/zip",
            content=_zip_bytes({"../escape.txt": b"nope"}),
        )


def test_upload_policy_rejects_archive_symlink_entries() -> None:
    with pytest.raises(MemoryIngressLimitError, match="symbolic links"):
        assess_asset_upload(
            filename="payload.zip",
            declared_content_type="application/zip",
            content=_zip_with_unix_mode("safe-name.txt", b"/etc/passwd", stat.S_IFLNK | 0o777),
        )


def test_upload_policy_rejects_archive_special_file_entries() -> None:
    with pytest.raises(MemoryIngressLimitError, match="special file"):
        assess_asset_upload(
            filename="payload.zip",
            declared_content_type="application/zip",
            content=_zip_with_unix_mode("safe-name.txt", b"", stat.S_IFIFO | 0o644),
        )


def test_upload_policy_rejects_archive_compression_bomb_ratio() -> None:
    with pytest.raises(MemoryIngressLimitError, match="compression ratio"):
        assess_asset_upload(
            filename="payload.zip",
            declared_content_type="application/zip",
            content=_zip_bytes({"huge.txt": b"0" * (2 * 1024 * 1024)}),
            max_archive_compression_ratio=10,
        )


def test_upload_policy_rejects_archive_uncompressed_size_limit() -> None:
    with pytest.raises(MemoryIngressLimitError, match="uncompressed size"):
        assess_asset_upload(
            filename="payload.zip",
            declared_content_type="application/zip",
            content=_zip_bytes({"huge.txt": b"x" * 1024}),
            max_archive_uncompressed_bytes=512,
        )


def test_upload_policy_marks_duplicate_archive_paths_for_review() -> None:
    result = assess_asset_upload(
        filename="payload.zip",
        declared_content_type="application/zip",
        content=_zip_bytes(
            {
                "notes/summary.txt": b"first",
                "notes\\SUMMARY.txt": b"second",
            }
        ),
    )

    assert result.metadata["upload_archive_review_required"] is True
    assert result.metadata["upload_archive_review_reason"] == "zip_archive_contains_duplicate_paths"
    assert result.metadata["upload_archive_duplicate_path_count"] == 1


@pytest.mark.parametrize("filename", ["../secret.txt", "nested/secret.txt", "run.exe"])
def test_upload_policy_blocks_dangerous_filenames(filename: str) -> None:
    with pytest.raises(MemoryIngressLimitError):
        assess_asset_upload(
            filename=filename,
            declared_content_type="text/plain",
            content=b"hello",
        )


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _zip_with_unix_mode(filename: str, content: bytes, mode: int) -> bytes:
    info = zipfile.ZipInfo(filename)
    info.external_attr = mode << 16
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(info, content)
    return buffer.getvalue()


def _png_bytes(*, width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\r"
        b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )


def _jpeg_bytes(*, width: int, height: int) -> bytes:
    return (
        b"\xff\xd8"
        b"\xff\xc0"
        b"\x00\x11"
        b"\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
        b"\xff\xd9"
    )


def _gif_bytes(*, width: int, height: int) -> bytes:
    return (
        b"GIF89a"
        + width.to_bytes(2, "little")
        + height.to_bytes(2, "little")
        + b"\x00\x00\x00"
    )


def _webp_vp8x_bytes(*, width: int, height: int) -> bytes:
    payload = (
        b"\x00\x00\x00\x00"
        + (width - 1).to_bytes(3, "little")
        + (height - 1).to_bytes(3, "little")
    )
    chunk = b"VP8X" + len(payload).to_bytes(4, "little") + payload
    return b"RIFF" + (4 + len(chunk)).to_bytes(4, "little") + b"WEBP" + chunk
