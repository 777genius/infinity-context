"""Provider-neutral content extraction adapters."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from io import BytesIO

from infinity_context_core.ports.extraction import (
    ContentExtractionPort,
    ExtractedElement,
    ExtractionArtifactCandidate,
    ExtractionRequest,
    ExtractionResult,
)

from infinity_context_adapters.extraction.fallback_context import merge_fallback_context
from infinity_context_adapters.extraction.file_detection import (
    _AUDIO_TYPES,
    _GENERIC_CONTENT_TYPES,
    _IMAGE_TYPES,
    _MEDIA_TYPES,
    _PDF_TYPES,
    _STRUCTURED_DOCUMENT_TYPES,
    _TEXT_HEURISTIC_TYPES,
    _TEXT_MAGIC_OVERRIDE_TYPES,
    _TEXT_TYPES,
    _TIMED_TEXT_TYPES,
    _VIDEO_TYPES,
    SimpleFileTypeDetector,
    _choose_detected_content_type,
    _ContentTypeChoice,
    _declared_should_override_magic,
    _detection_confidence,
    _detection_diagnostics,
    _extension,
    _extension_content_type,
    _extension_should_override_magic,
    _ftyp_brands,
    _ftyp_content_type,
    _is_structured_archive_choice,
    _looks_like_utf8_text,
    _magic_content_type,
    _normalize_content_type,
)
from infinity_context_adapters.extraction.image_evidence import (
    extract_tesseract_ocr_blocks,
    full_image_region,
    image_regions_artifact,
    read_image_metadata,
)
from infinity_context_adapters.extraction.media_tools import (
    extract_selected_video_keyframes,
    media_manifest_artifact,
    probe_media_with_ffprobe,
    video_frame_pixel_limit_decision,
    video_keyframe_status,
)
from infinity_context_adapters.extraction.video_evidence import analyze_video_keyframes

__all__ = [
    "ExtractionEngine",
    "ImageMetadataExtractionEngine",
    "MediaMetadataExtractionEngine",
    "PdfTextExtractionEngine",
    "SimpleFileTypeDetector",
    "SimpleTextExtractionEngine",
    "StandardExtractionRouter",
    "SupportDecision",
    "TimedTextTranscriptExtractionEngine",
    "_AUDIO_TYPES",
    "_ContentTypeChoice",
    "_GENERIC_CONTENT_TYPES",
    "_IMAGE_TYPES",
    "_MEDIA_TYPES",
    "_PDF_TYPES",
    "_STRUCTURED_DOCUMENT_TYPES",
    "_TEXT_HEURISTIC_TYPES",
    "_TEXT_MAGIC_OVERRIDE_TYPES",
    "_TEXT_TYPES",
    "_TIMED_TEXT_TYPES",
    "_VIDEO_TYPES",
    "_choose_detected_content_type",
    "_clean_caption_text",
    "_decode_text",
    "_declared_should_override_magic",
    "_detection_confidence",
    "_detection_diagnostics",
    "_extension",
    "_extension_content_type",
    "_extension_should_override_magic",
    "_format_duration_seconds",
    "_format_timestamp_ms",
    "_ftyp_brands",
    "_ftyp_content_type",
    "_is_structured_archive_choice",
    "_json_to_text",
    "_limit_text",
    "_looks_like_utf8_text",
    "_magic_content_type",
    "_merge_diagnostics",
    "_normalize_content_type",
    "_parse_timed_text_segments",
    "_positive_float",
    "_result_allows_fallback",
    "_safe_suffix",
    "_timestamp_to_ms",
    "_unsupported",
]
_SUBTITLE_TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
)


@dataclass(frozen=True)
class SupportDecision:
    supported: bool
    reason: str | None = None


class ExtractionEngine:
    name = "base"

    async def supports(self, request: ExtractionRequest) -> SupportDecision:
        raise NotImplementedError

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        raise NotImplementedError


class StandardExtractionRouter(ContentExtractionPort):
    def __init__(self, engines: tuple[ExtractionEngine, ...]) -> None:
        self._engines = engines

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        diagnostics: dict[str, object] = {"parser_profile": request.parser_profile}
        if request.byte_size > request.limits.max_bytes:
            return ExtractionResult(
                status="unsupported",
                normalized_content_type=request.detected_content_type,
                title=request.filename,
                technical_metadata={
                    "byte_size": request.byte_size,
                    "max_bytes": request.limits.max_bytes,
                    "mime_detected": request.detected_content_type,
                },
                diagnostics={
                    **diagnostics,
                    "engine": "standard-router",
                    "reason": "file_too_large",
                },
                parser_name="standard-router",
                parser_version="v1",
                safe_error_code="asset_extraction.file_too_large",
                safe_error_message="Asset exceeds configured extraction size limit",
            )
        fallback_result: ExtractionResult | None = None
        for engine in self._engines:
            decision = await engine.supports(request)
            diagnostics[f"{engine.name}_support"] = decision.supported
            if decision.reason:
                diagnostics[f"{engine.name}_reason"] = decision.reason
            if not decision.supported:
                continue
            result = await engine.extract(request)
            if _result_allows_fallback(result):
                fallback_result = _merge_diagnostics(result, diagnostics)
                diagnostics[f"{engine.name}_fallback"] = True
                continue
            if fallback_result is not None and result.status == "succeeded":
                result = merge_fallback_context(result, fallback_result)
            return _merge_diagnostics(result, diagnostics)
        if fallback_result is not None:
            return fallback_result
        return ExtractionResult(
            status="unsupported",
            normalized_content_type=request.detected_content_type,
            title=request.filename,
            technical_metadata={
                "byte_size": request.byte_size,
                "mime_detected": request.detected_content_type,
            },
            diagnostics=diagnostics,
            parser_name="standard-router",
            parser_version="v1",
            safe_error_code="asset_extraction.unsupported_content_type",
            safe_error_message="No extraction engine supports this asset type",
        )


class SimpleTextExtractionEngine(ExtractionEngine):
    name = "simple_text"
    version = "v1"

    async def supports(self, request: ExtractionRequest) -> SupportDecision:
        if request.detected_content_type in _TEXT_TYPES:
            return SupportDecision(True)
        if request.detected_content_type in _TEXT_HEURISTIC_TYPES and _looks_like_utf8_text(
            request.content
        ):
            return SupportDecision(True, reason="utf8_text_heuristic")
        return SupportDecision(False, reason="not_text")

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        text = _decode_text(request.content)
        if request.detected_content_type == "application/json":
            text = _json_to_text(text)
        text = _limit_text(text, request.limits.max_output_chars)
        title = request.filename.strip() or "asset"
        return ExtractionResult(
            status="succeeded",
            normalized_content_type=request.detected_content_type,
            title=title,
            markdown=text,
            elements=(
                ExtractedElement(
                    kind="text",
                    text=text,
                    metadata={"source": "simple_text"},
                ),
            ),
            technical_metadata={
                "byte_size": request.byte_size,
                "mime_detected": request.detected_content_type,
                "output_chars": len(text),
            },
            diagnostics={"engine": self.name},
            parser_name=self.name,
            parser_version=self.version,
        )


class PdfTextExtractionEngine(ExtractionEngine):
    name = "pypdf_text"
    version = "v1"

    async def supports(self, request: ExtractionRequest) -> SupportDecision:
        if request.detected_content_type in _PDF_TYPES:
            return SupportDecision(True)
        return SupportDecision(False, reason="not_pdf")

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        return await asyncio.to_thread(self._extract_sync, request)

    def _extract_sync(self, request: ExtractionRequest) -> ExtractionResult:
        try:
            from pypdf import PdfReader
        except ImportError:
            return _unsupported(
                request,
                parser_name=self.name,
                parser_version=self.version,
                code="asset_extraction.pdf_dependency_missing",
                message="PDF text extraction dependency is not installed",
            )

        try:
            reader = PdfReader(BytesIO(request.content), strict=False)
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception:
                    return _unsupported(
                        request,
                        parser_name=self.name,
                        parser_version=self.version,
                        code="asset_extraction.pdf_encrypted",
                        message="Encrypted PDF cannot be extracted locally",
                    )
            page_count = len(reader.pages)
            pages_to_extract = min(page_count, request.limits.max_pages)
            elements: list[ExtractedElement] = []
            markdown_parts = [f"# {request.filename.strip() or 'PDF document'}"]
            for index in range(pages_to_extract):
                raw_text = reader.pages[index].extract_text() or ""
                page_text = _limit_text(raw_text, request.limits.max_output_chars).strip()
                if not page_text:
                    continue
                page_number = index + 1
                markdown_parts.extend((f"## Page {page_number}", page_text))
                elements.append(
                    ExtractedElement(
                        kind="page_text",
                        text=page_text,
                        page_number=page_number,
                        metadata={"source": self.name},
                    )
                )
        except Exception:
            return _unsupported(
                request,
                parser_name=self.name,
                parser_version=self.version,
                code="asset_extraction.pdf_parse_failed",
                message="PDF text extraction failed",
            )

        markdown = _limit_text("\n\n".join(markdown_parts), request.limits.max_output_chars)
        if not elements:
            return _unsupported(
                request,
                parser_name=self.name,
                parser_version=self.version,
                code="asset_extraction.pdf_no_text",
                message="PDF has no locally extractable text",
                metadata={
                    "byte_size": request.byte_size,
                    "mime_detected": request.detected_content_type,
                    "page_count": page_count,
                    "pages_extracted": pages_to_extract,
                    "ocr_required": True,
                },
            )

        return ExtractionResult(
            status="succeeded",
            normalized_content_type="application/pdf",
            title=request.filename.strip() or "PDF document",
            markdown=markdown,
            elements=tuple(elements),
            technical_metadata={
                "byte_size": request.byte_size,
                "mime_detected": request.detected_content_type,
                "page_count": page_count,
                "pages_extracted": pages_to_extract,
                "truncated_pages": page_count > pages_to_extract,
                "output_chars": len(markdown),
            },
            diagnostics={"engine": self.name},
            parser_name=self.name,
            parser_version=self.version,
        )


class ImageMetadataExtractionEngine(ExtractionEngine):
    name = "image_metadata"
    version = "v1"

    async def supports(self, request: ExtractionRequest) -> SupportDecision:
        if request.detected_content_type in _IMAGE_TYPES:
            return SupportDecision(True)
        return SupportDecision(False, reason="not_image")

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        return await asyncio.to_thread(self._extract_sync, request)

    def _extract_sync(self, request: ExtractionRequest) -> ExtractionResult:
        image = read_image_metadata(request.content)
        if image is None:
            return _unsupported(
                request,
                parser_name=self.name,
                parser_version=self.version,
                code="asset_extraction.image_parse_failed",
                message="Image could not be read locally",
            )
        if image.width * image.height > request.limits.max_image_pixels:
            return _unsupported(
                request,
                parser_name=self.name,
                parser_version=self.version,
                code="asset_extraction.image_too_large",
                message="Image pixel count exceeds extraction limit",
                metadata={
                    "image_width": image.width,
                    "image_height": image.height,
                    "image_pixels": image.width * image.height,
                    "max_image_pixels": request.limits.max_image_pixels,
                },
            )

        ocr_result = None
        if request.limits.enable_ocr:
            ocr_result = extract_tesseract_ocr_blocks(
                content=request.content,
                extension=_extension(request.filename),
                timeout_seconds=request.limits.subprocess_timeout_seconds,
            )
        ocr_status = ocr_result.status if ocr_result is not None else "disabled"
        ocr_regions = ocr_result.regions if ocr_result is not None else ()

        lines = [
            f"# {request.filename.strip() or 'Image asset'}",
            "Image asset evidence",
            f"- Content type: {request.detected_content_type}",
            f"- Dimensions: {image.width}x{image.height}",
            f"- Format: {image.image_format or 'unknown'}",
            f"- OCR status: {ocr_status}",
            f"- OCR blocks: {len(ocr_regions)}",
        ]
        image_region = full_image_region(
            metadata=image,
            parser_name=self.name,
            text=(
                f"Image asset {request.filename} "
                f"({request.detected_content_type}, {image.width}x{image.height})"
            ),
        )
        elements = [image_region.to_element(parser_name=self.name)]
        if ocr_result is not None and ocr_result.text.strip():
            limited_ocr_text = _limit_text(
                ocr_result.text,
                request.limits.max_output_chars,
            )
            lines.extend(("## OCR Text", limited_ocr_text))
            elements.extend(region.to_element(parser_name=self.name) for region in ocr_regions)

        markdown = _limit_text("\n".join(lines), request.limits.max_output_chars)
        regions = (image_region, *ocr_regions)
        return ExtractionResult(
            status="succeeded",
            normalized_content_type=request.detected_content_type,
            title=request.filename.strip() or "Image asset",
            markdown=markdown,
            elements=tuple(elements),
            artifacts=(
                image_regions_artifact(
                    filename="image-regions.json",
                    parser_name=self.name,
                    image=image,
                    regions=regions,
                    metadata={
                        "ocr_status": ocr_status,
                        "ocr_block_count": len(ocr_regions),
                    },
                ),
            ),
            technical_metadata={
                "byte_size": request.byte_size,
                "mime_detected": request.detected_content_type,
                **image.as_metadata(),
                "ocr_status": ocr_status,
                "ocr_block_count": len(ocr_regions),
                "image_region_count": len(regions),
                "image_artifact_count": 1,
                "output_chars": len(markdown),
            },
            diagnostics={"engine": self.name},
            parser_name=self.name,
            parser_version=self.version,
        )


class TimedTextTranscriptExtractionEngine(ExtractionEngine):
    name = "timed_text_transcript"
    version = "v1"

    async def supports(self, request: ExtractionRequest) -> SupportDecision:
        if request.detected_content_type in _TIMED_TEXT_TYPES:
            return SupportDecision(True)
        return SupportDecision(False, reason="not_timed_text")

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        text = _decode_text(request.content)
        segments = _parse_timed_text_segments(text)
        if not segments:
            return _unsupported(
                request,
                parser_name=self.name,
                parser_version=self.version,
                code="asset_extraction.transcript_parse_failed",
                message="Timed transcript contains no readable segments",
            )

        lines = [f"# {request.filename.strip() or 'Transcript'}", "## Transcript"]
        elements: list[ExtractedElement] = []
        for segment in segments:
            start_ms, end_ms, segment_text = segment
            if not segment_text:
                continue
            lines.append(
                f"[{_format_timestamp_ms(start_ms)} - {_format_timestamp_ms(end_ms)}] "
                f"{segment_text}"
            )
            elements.append(
                ExtractedElement(
                    kind="transcript_segment",
                    text=segment_text,
                    time_start_ms=start_ms,
                    time_end_ms=end_ms,
                    metadata={"source": self.name},
                )
            )

        markdown = _limit_text("\n".join(lines), request.limits.max_output_chars)
        transcript_text = "\n".join(
            f"{_format_timestamp_ms(item[0])} --> {_format_timestamp_ms(item[1])}\n{item[2]}"
            for item in segments
        )
        return ExtractionResult(
            status="succeeded",
            normalized_content_type=request.detected_content_type,
            title=request.filename.strip() or "Transcript",
            markdown=markdown,
            elements=tuple(elements),
            artifacts=(
                ExtractionArtifactCandidate(
                    artifact_type="transcript",
                    filename="transcript.txt",
                    content_type="text/plain",
                    content=transcript_text.encode("utf-8"),
                    metadata={"parser": self.name, "segment_count": len(elements)},
                ),
            ),
            technical_metadata={
                "byte_size": request.byte_size,
                "mime_detected": request.detected_content_type,
                "segment_count": len(elements),
                "duration_ms": max((segment[1] for segment in segments), default=0),
                "output_chars": len(markdown),
            },
            diagnostics={"engine": self.name},
            parser_name=self.name,
            parser_version=self.version,
        )


class MediaMetadataExtractionEngine(ExtractionEngine):
    name = "media_metadata"
    version = "v1"

    async def supports(self, request: ExtractionRequest) -> SupportDecision:
        if request.detected_content_type in _MEDIA_TYPES:
            return SupportDecision(True)
        if request.detected_content_type.startswith(("audio/", "video/")):
            return SupportDecision(True, reason="media_prefix")
        return SupportDecision(False, reason="not_media")

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        return await asyncio.to_thread(self._extract_sync, request)

    def _extract_sync(self, request: ExtractionRequest) -> ExtractionResult:
        probe = probe_media_with_ffprobe(request)
        if probe.status == "unavailable":
            return _unsupported(
                request,
                parser_name=self.name,
                parser_version=self.version,
                code="asset_extraction.media_probe_unavailable",
                message="Local media probing is not available",
                metadata={
                    "byte_size": request.byte_size,
                    "mime_detected": request.detected_content_type,
                    **(probe.metadata or {}),
                },
            )
        if probe.status == "failed":
            probe_metadata = probe.metadata or {}
            probe_timed_out = probe_metadata.get("probe_failure_reason") == "subprocess_timeout"
            return _unsupported(
                request,
                parser_name=self.name,
                parser_version=self.version,
                code=(
                    "asset_extraction.media_probe_timeout"
                    if probe_timed_out
                    else "asset_extraction.media_probe_failed"
                ),
                message=(
                    "Media probing timed out locally"
                    if probe_timed_out
                    else "Media file could not be probed locally"
                ),
                metadata={
                    "byte_size": request.byte_size,
                    "mime_detected": request.detected_content_type,
                    **probe_metadata,
                },
            )
        if probe.duration_seconds and probe.duration_seconds > request.limits.max_media_seconds:
            return _unsupported(
                request,
                parser_name=self.name,
                parser_version=self.version,
                code="asset_extraction.media_too_long",
                message="Media duration exceeds local extraction limit",
                metadata={
                    "byte_size": request.byte_size,
                    "mime_detected": request.detected_content_type,
                    "duration_seconds": probe.duration_seconds,
                    "max_media_seconds": request.limits.max_media_seconds,
                },
            )

        keyframes = ()
        frame_evidence = None
        frame_limit = video_frame_pixel_limit_decision(
            probe,
            max_pixels=request.limits.max_image_pixels,
        )
        is_video = request.detected_content_type.startswith("video/")
        if is_video and frame_limit.allowed:
            keyframes = extract_selected_video_keyframes(
                request,
                duration_seconds=probe.duration_seconds,
                max_frames=3,
            )
            if keyframes:
                frame_evidence = analyze_video_keyframes(
                    frames=keyframes,
                    parser_name=self.name,
                    enable_ocr=request.limits.enable_ocr,
                    ocr_timeout_seconds=request.limits.subprocess_timeout_seconds,
                )

        lines = [
            f"# {request.filename.strip() or 'Media asset'}",
            "Media asset evidence",
            f"- Content type: {request.detected_content_type}",
            f"- Duration: {_format_duration_seconds(probe.duration_seconds)}",
            f"- Streams: {', '.join(probe.stream_summaries) or 'unknown'}",
            "- Transcript status: not configured in local extractor",
        ]
        if keyframes:
            lines.append(f"- Keyframes: {len(keyframes)} extracted")
        elif is_video and not frame_limit.allowed:
            lines.append("- Keyframes: skipped because video frame pixels exceed limit")
        markdown = _limit_text("\n".join(lines), request.limits.max_output_chars)
        artifacts = (
            media_manifest_artifact(
                request=request,
                probe=probe,
                parser_name=self.name,
            ),
            *(frame.to_artifact() for frame in keyframes),
            *((frame_evidence.timeline_artifact,) if frame_evidence is not None else ()),
        )
        elements = [
            ExtractedElement(
                kind="media_metadata",
                text=(
                    f"Media asset {request.filename} "
                    f"({request.detected_content_type}, "
                    f"{_format_duration_seconds(probe.duration_seconds)})"
                ),
                metadata={"source": self.name, **(probe.metadata or {})},
            ),
            *((frame_evidence.elements) if frame_evidence is not None else ()),
        ]
        return ExtractionResult(
            status="succeeded",
            normalized_content_type=request.detected_content_type,
            title=request.filename.strip() or "Media asset",
            markdown=markdown,
            elements=tuple(elements),
            artifacts=artifacts,
            technical_metadata={
                "byte_size": request.byte_size,
                "mime_detected": request.detected_content_type,
                "duration_seconds": probe.duration_seconds,
                "stream_count": len(probe.stream_summaries),
                "transcript_status": "not_configured",
                "keyframe_status": video_keyframe_status(
                    content_type=request.detected_content_type,
                    keyframes_extracted=bool(keyframes),
                    frame_limit_allowed=frame_limit.allowed,
                ),
                "output_chars": len(markdown),
                **(
                    frame_limit.metadata
                    if is_video
                    else {}
                ),
                **(frame_evidence.metadata if frame_evidence is not None else {}),
                **(probe.metadata or {}),
            },
            diagnostics={"engine": self.name},
            parser_name=self.name,
            parser_version=self.version,
        )


def _decode_text(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace")


def _json_to_text(text: str) -> str:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _limit_text(text: str, max_chars: int) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[:max_chars].rstrip()


def _merge_diagnostics(
    result: ExtractionResult,
    diagnostics: dict[str, object],
) -> ExtractionResult:
    merged = {**diagnostics, **result.diagnostics}
    return ExtractionResult(
        status=result.status,
        normalized_content_type=result.normalized_content_type,
        title=result.title,
        elements=result.elements,
        markdown=result.markdown,
        artifacts=result.artifacts,
        technical_metadata=result.technical_metadata,
        diagnostics=merged,
        language=result.language,
        parser_name=result.parser_name,
        parser_version=result.parser_version,
        model_version=result.model_version,
        safe_error_code=result.safe_error_code,
        safe_error_message=result.safe_error_message,
    )


def _result_allows_fallback(result: ExtractionResult) -> bool:
    return result.status == "unsupported" and result.diagnostics.get("fallback_allowed") is True


def _unsupported(
    request: ExtractionRequest,
    *,
    parser_name: str,
    parser_version: str | None,
    code: str,
    message: str,
    metadata: dict[str, object] | None = None,
) -> ExtractionResult:
    return ExtractionResult(
        status="unsupported",
        normalized_content_type=request.detected_content_type,
        title=request.filename,
        technical_metadata={
            "byte_size": request.byte_size,
            "mime_detected": request.detected_content_type,
            **(metadata or {}),
        },
        diagnostics={"engine": parser_name},
        parser_name=parser_name,
        parser_version=parser_version,
        safe_error_code=code,
        safe_error_message=message,
    )


def _parse_timed_text_segments(text: str) -> list[tuple[int, int, str]]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", normalized)
    segments: list[tuple[int, int, str]] = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        if lines[0].upper().startswith("WEBVTT"):
            continue
        timestamp_index = next(
            (index for index, line in enumerate(lines) if _SUBTITLE_TIMESTAMP_RE.search(line)),
            None,
        )
        if timestamp_index is None:
            continue
        match = _SUBTITLE_TIMESTAMP_RE.search(lines[timestamp_index])
        if match is None:
            continue
        caption_lines = lines[timestamp_index + 1 :]
        segment_text = _clean_caption_text(" ".join(caption_lines))
        if not segment_text:
            continue
        segments.append(
            (
                _timestamp_to_ms(match.group("start")),
                _timestamp_to_ms(match.group("end")),
                segment_text,
            )
        )
    return segments


def _clean_caption_text(text: str) -> str:
    without_tags = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", without_tags).strip()


def _timestamp_to_ms(value: str) -> int:
    parts = value.replace(",", ".").split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return int(round(((hours * 60 + minutes) * 60 + seconds) * 1000))


def _format_timestamp_ms(value: int) -> str:
    milliseconds = value % 1000
    total_seconds = value // 1000
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"


def _safe_suffix(filename: str) -> str:
    extension = _extension(filename)
    if not extension:
        return ".bin"
    safe = "".join(ch for ch in extension if ch.isalnum())[:16]
    return f".{safe or 'bin'}"


def _positive_float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _format_duration_seconds(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.2f}s"
