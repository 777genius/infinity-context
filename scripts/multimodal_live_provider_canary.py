"""Run a live multimodal provider canary for image vision and transcription."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
import uuid
import zlib
from pathlib import Path

from memo_stack_adapters.extraction.openai_vision import OpenAIImageVisionAdapter
from memo_stack_adapters.extraction.transcription.openai_adapter import (
    OpenAISpeechTranscriptionAdapter,
)
from memo_stack_core.ports.transcription import SpeechTranscriptionRequest
from memo_stack_core.ports.vision import ImageVisionRequest

SUITE = "memo-stack-multimodal-live-provider-canary"
REQUIRED_ENV = "MEMORY_OPENAI_API_KEY or OPENAI_API_KEY"
DEFAULT_VISION_MODEL = "gpt-4.1-mini"
DEFAULT_TRANSCRIPTION_MODEL = "gpt-4o-mini-transcribe"
DEFAULT_VISION_DETAIL = "low"
DEFAULT_TIMEOUT_SECONDS = 60.0
SYNTHETIC_AUDIO_PHRASE = "memo stack live transcription canary"

_CONTENT_TYPES_BY_SUFFIX = {
    ".flac": "audio/flac",
    ".m4a": "audio/m4a",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpga",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}

_FONT_5X7 = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = asyncio.run(run_multimodal_live_provider_canary(args))
    _write_report(report, args.report_out)
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["ok"] is True:
        return 0
    if report["components"]["provider_key"]["status"] == "degraded":
        return 2
    return 1


async def run_multimodal_live_provider_canary(
    args: argparse.Namespace,
) -> dict[str, object]:
    api_key = _provider_api_key()
    report = _base_report(args, has_provider_key=bool(api_key))
    if not api_key:
        report["components"]["provider_key"] = _component(
            "degraded",
            reason="provider_credential_missing",
            message=f"Set {REQUIRED_ENV} before running the live provider canary",
        )
        report["components"]["vision"] = _component(
            "skipped",
            reason="provider_credential_missing",
        )
        report["components"]["transcription"] = _component(
            "skipped",
            reason="provider_credential_missing",
        )
        report["ok"] = False
        return report

    report["components"]["provider_key"] = _component("configured")
    vision = await _run_vision(api_key=api_key, args=args)
    transcription = await _run_transcription(api_key=api_key, args=args)
    report["components"]["vision"] = vision
    report["components"]["transcription"] = transcription
    report["ok"] = vision["status"] == "succeeded" and transcription["status"] == "succeeded"
    return report


async def _run_vision(
    *,
    api_key: str,
    args: argparse.Namespace,
) -> dict[str, object]:
    image = _sample_png_bytes()
    request = ImageVisionRequest(
        job_id=f"live-canary-{uuid.uuid4()}",
        asset_id=f"asset-{uuid.uuid4()}",
        filename="memo-stack-live-vision-canary.png",
        content_type="image/png",
        byte_size=len(image),
        sha256_hex=hashlib.sha256(image).hexdigest(),
        content=image,
        max_output_chars=4000,
    )
    adapter = OpenAIImageVisionAdapter(
        api_key=api_key,
        model=args.vision_model,
        detail=args.vision_detail,
        request_timeout_seconds=args.timeout_seconds,
    )
    result = await adapter.analyze(request)
    if result.status != "succeeded":
        return _component(
            "failed",
            reason=result.safe_error_code or "vision_provider_failed",
            message=result.safe_error_message,
            provider_name=result.provider_name,
            provider_model=result.provider_model,
            provider_version=result.provider_version,
            diagnostics=_safe_diagnostics(result.diagnostics),
        )

    visible_text = result.payload.get("visible_text")
    visible_text_count = len(visible_text) if isinstance(visible_text, list) else 0
    summary = result.payload.get("summary")
    summary_chars = len(summary) if isinstance(summary, str) else 0
    evidence_check = _vision_evidence_check(
        visible_text_count=visible_text_count,
        summary_chars=summary_chars,
    )
    if evidence_check["status"] != "succeeded":
        return _component(
            "failed",
            reason=evidence_check["reason"],
            message=evidence_check["message"],
            provider_name=result.provider_name,
            provider_model=result.provider_model,
            provider_version=result.provider_version,
            payload_status=result.payload_status,
            visible_text_count=visible_text_count,
            summary_chars=summary_chars,
            diagnostics=_safe_diagnostics(result.diagnostics),
        )
    return _component(
        "succeeded",
        provider_name=result.provider_name,
        provider_model=result.provider_model,
        provider_version=result.provider_version,
        payload_status=result.payload_status,
        visible_text_count=visible_text_count,
        summary_chars=summary_chars,
        diagnostics=_safe_diagnostics(result.diagnostics),
    )


async def _run_transcription(
    *,
    api_key: str,
    args: argparse.Namespace,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="memo-stack-live-asr-") as tmp:
        audio_path = _audio_fixture_path(args.audio_fixture, Path(tmp))
        if audio_path is None:
            return _component(
                "degraded",
                reason="audio_fixture_missing",
                message=(
                    "Set MEMORY_MULTIMODAL_PROVIDER_AUDIO_FIXTURE or run on macOS "
                    "with the say command available"
                ),
            )
        content = audio_path.read_bytes()
        content_type = _content_type_for_path(audio_path)
        request = SpeechTranscriptionRequest(
            job_id=f"live-canary-{uuid.uuid4()}",
            asset_id=f"asset-{uuid.uuid4()}",
            filename=audio_path.name,
            content_type=content_type,
            byte_size=len(content),
            sha256_hex=hashlib.sha256(content).hexdigest(),
            content=content,
            max_output_chars=4000,
            prompt="This is a short Memo Stack provider canary.",
        )
        adapter = OpenAISpeechTranscriptionAdapter(
            api_key=api_key,
            model=args.transcription_model,
            request_timeout_seconds=args.timeout_seconds,
        )
        result = await adapter.transcribe(request)

    if result.status != "succeeded":
        return _component(
            "failed",
            reason=result.safe_error_code or "transcription_provider_failed",
            message=result.safe_error_message,
            provider_name=result.provider_name,
            provider_model=result.provider_model,
            provider_version=result.provider_version,
            diagnostics=_safe_diagnostics(result.diagnostics),
        )

    transcript_check = _transcript_check(result.text, audio_path=args.audio_fixture)
    if transcript_check["status"] != "succeeded":
        return _component(
            "failed",
            reason=transcript_check["reason"],
            message=transcript_check["message"],
            provider_name=result.provider_name,
            provider_model=result.provider_model,
            provider_version=result.provider_version,
            transcript_chars=len(result.text),
            segment_count=len(result.segments),
            word_count=len(result.words),
            language=result.language,
            duration_seconds=result.duration_seconds,
            diagnostics=_safe_diagnostics(result.diagnostics),
        )

    return _component(
        "succeeded",
        provider_name=result.provider_name,
        provider_model=result.provider_model,
        provider_version=result.provider_version,
        transcript_chars=len(result.text),
        segment_count=len(result.segments),
        word_count=len(result.words),
        language=result.language,
        duration_seconds=result.duration_seconds,
        diagnostics=_safe_diagnostics(result.diagnostics),
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-out",
        default=os.environ.get("MEMORY_MULTIMODAL_PROVIDER_CANARY_REPORT_OUT"),
        help="Optional path for the JSON canary report.",
    )
    parser.add_argument(
        "--audio-fixture",
        default=os.environ.get("MEMORY_MULTIMODAL_PROVIDER_AUDIO_FIXTURE"),
        help="Optional speech fixture path for OpenAI transcription.",
    )
    parser.add_argument(
        "--vision-model",
        default=os.environ.get("MEMORY_EXTRACTION_VISION_MODEL", DEFAULT_VISION_MODEL),
    )
    parser.add_argument(
        "--vision-detail",
        default=os.environ.get("MEMORY_EXTRACTION_VISION_DETAIL", DEFAULT_VISION_DETAIL),
    )
    parser.add_argument(
        "--transcription-model",
        default=os.environ.get(
            "MEMORY_TRANSCRIPTION_OPENAI_MODEL",
            DEFAULT_TRANSCRIPTION_MODEL,
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(
            os.environ.get(
                "MEMORY_EXTRACTION_PROVIDER_TIMEOUT_SECONDS",
                DEFAULT_TIMEOUT_SECONDS,
            )
        ),
    )
    return parser.parse_args(argv)


def _base_report(
    args: argparse.Namespace,
    *,
    has_provider_key: bool,
) -> dict[str, object]:
    return {
        "suite": SUITE,
        "ok": False,
        "required_env": [REQUIRED_ENV],
        "secrets_redacted": True,
        "provider_key_present": has_provider_key,
        "models": {
            "vision": args.vision_model,
            "transcription": args.transcription_model,
        },
        "components": {
            "provider_key": _component("unknown"),
            "vision": _component("unknown"),
            "transcription": _component("unknown"),
        },
    }


def _provider_api_key() -> str | None:
    value = os.environ.get("MEMORY_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if value and value.strip():
        return value.strip()
    return None


def _component(status: str, **values: object) -> dict[str, object]:
    component = {"status": status}
    for key, value in values.items():
        if value is not None:
            component[key] = value
    component.update(
        _recovery_policy(
            status=status,
            reason=component.get("reason") if isinstance(component.get("reason"), str) else None,
        )
    )
    return component


def _recovery_policy(*, status: str, reason: str | None) -> dict[str, object]:
    if status in {"configured", "succeeded", "unknown"}:
        return {}
    normalized = (reason or status).strip().lower()
    if "missing_api_key" in normalized or "credential_missing" in normalized:
        return {
            "user_retryable": False,
            "operator_action": "configure_provider_credential",
        }
    if "invalid_api_key" in normalized:
        return {
            "user_retryable": False,
            "operator_action": "replace_provider_credential",
        }
    if "quota_exceeded" in normalized or "insufficient_quota" in normalized:
        return {
            "user_retryable": False,
            "operator_action": "check_provider_billing",
        }
    if "rate_limited" in normalized or "timeout" in normalized or "unavailable" in normalized:
        return {
            "user_retryable": True,
            "operator_action": "retry_later",
        }
    if normalized == "audio_fixture_missing":
        return {
            "user_retryable": False,
            "operator_action": "provide_audio_fixture",
        }
    return {
        "user_retryable": False,
        "operator_action": "inspect_provider_canary",
    }


def _write_report(report: dict[str, object], report_out: str | None) -> None:
    if not report_out:
        return
    path = Path(report_out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _audio_fixture_path(configured: str | None, tmp_dir: Path) -> Path | None:
    if configured:
        path = Path(configured).expanduser()
        if path.is_file() and path.stat().st_size > 0:
            return path
        return None
    return _synthesize_audio_fixture(tmp_dir)


def _synthesize_audio_fixture(tmp_dir: Path) -> Path | None:
    say = shutil.which("say")
    if not say:
        return None
    output = tmp_dir / "memo-stack-live-transcription-canary.wav"
    command = [
        say,
        "-o",
        str(output),
        "--file-format=WAVE",
        "--data-format=LEI16@16000",
        SYNTHETIC_AUDIO_PHRASE,
    ]
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    if output.is_file() and output.stat().st_size > 0:
        return output
    return None


def _content_type_for_path(path: Path) -> str:
    return _CONTENT_TYPES_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream")


def _transcript_check(
    transcript: str,
    *,
    audio_path: str | None,
) -> dict[str, object]:
    if not transcript.strip():
        return _component(
            "failed",
            reason="transcription_empty_text",
            message="Provider returned an empty transcript",
        )
    if audio_path:
        return _component("succeeded")
    normalized_terms = set(transcript.lower().replace("-", " ").split())
    expected_terms = {"memo", "stack", "canary"}
    missing_terms = sorted(expected_terms.difference(normalized_terms))
    if missing_terms:
        return _component(
            "failed",
            reason="synthetic_transcript_mismatch",
            message="Synthetic speech transcript missed expected canary terms",
            missing_terms=missing_terms,
        )
    return _component("succeeded")


def _vision_evidence_check(
    *,
    visible_text_count: int,
    summary_chars: int,
) -> dict[str, object]:
    if visible_text_count > 0 or summary_chars > 0:
        return _component("succeeded")
    return _component(
        "failed",
        reason="vision_empty_evidence",
        message="Provider returned no visible text or image summary",
    )


def _safe_diagnostics(diagnostics: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in diagnostics.items():
        normalized_key = key.lower()
        if any(
            marker in normalized_key for marker in ("api_key", "authorization", "token", "secret")
        ):
            continue
        if isinstance(value, str):
            safe[key] = value[:200]
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, list):
            safe[key] = value[:10]
        elif isinstance(value, dict):
            safe[key] = {
                str(child_key): child_value
                for child_key, child_value in list(value.items())[:10]
                if isinstance(child_value, (str, int, float, bool)) or child_value is None
            }
        else:
            safe[key] = value.__class__.__name__
    return safe


def _sample_png_bytes() -> bytes:
    width = 180
    height = 64
    pixels = bytearray([255, 255, 255] * width * height)
    _draw_text(pixels, width, x=14, y=18, text="MEMO STACK 24", scale=3)
    return _encode_png(width, height, bytes(pixels))


def _draw_text(
    pixels: bytearray,
    width: int,
    *,
    x: int,
    y: int,
    text: str,
    scale: int,
) -> None:
    cursor = x
    for char in text:
        glyph = _FONT_5X7.get(char.upper())
        if glyph is None:
            cursor += 6 * scale
            continue
        for row_index, row in enumerate(glyph):
            for column_index, enabled in enumerate(row):
                if enabled != "1":
                    continue
                _fill_rect(
                    pixels,
                    width,
                    x=cursor + column_index * scale,
                    y=y + row_index * scale,
                    size=scale,
                    color=(18, 24, 38),
                )
        cursor += 6 * scale


def _fill_rect(
    pixels: bytearray,
    width: int,
    *,
    x: int,
    y: int,
    size: int,
    color: tuple[int, int, int],
) -> None:
    height = len(pixels) // (width * 3)
    for yy in range(y, min(y + size, height)):
        for xx in range(x, min(x + size, width)):
            offset = (yy * width + xx) * 3
            pixels[offset : offset + 3] = bytes(color)


def _encode_png(width: int, height: int, rgb: bytes) -> bytes:
    raw_rows = []
    row_length = width * 3
    for y in range(height):
        raw_rows.append(b"\x00" + rgb[y * row_length : (y + 1) * row_length])
    raw = b"".join(raw_rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, level=9))
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


if __name__ == "__main__":
    raise SystemExit(main())
