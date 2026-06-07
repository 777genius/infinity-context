"""Deterministic capture admission, redaction and fingerprint helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256

_TOKEN_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b", re.IGNORECASE),
    re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}\b"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"\b[A-Za-z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)"
        r"\s*=\s*['\"]?[^'\"\s]{12,}",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class CaptureAdmissionResult:
    text: str
    accepted: bool
    redacted: bool
    reason: str


class CaptureAdmissionService:
    """Fast deterministic server-side admission guard."""

    def admit(self, text: str) -> CaptureAdmissionResult:
        stripped = text.strip()
        if not stripped:
            return CaptureAdmissionResult("", False, False, "empty_capture")
        redacted = stripped
        did_redact = False
        for pattern in _TOKEN_PATTERNS:
            new_text = pattern.sub("[redacted-secret]", redacted)
            did_redact = did_redact or new_text != redacted
            redacted = new_text
        if "[redacted-secret]" in redacted and len(redacted) <= len("[redacted-secret]") + 10:
            return CaptureAdmissionResult(redacted, False, True, "secret_rejected")
        return CaptureAdmissionResult(
            redacted,
            True,
            did_redact,
            "redacted" if did_redact else "accepted",
        )


def capture_payload_hash(*parts: object) -> str:
    raw = "\u241f".join("" if part is None else str(part) for part in parts)
    return sha256(raw.encode()).hexdigest()


def capture_idempotency_key(
    *,
    source_agent: str,
    source_kind: str,
    event_type: str,
    source_event_id: str | None,
    client_instance_id: str | None,
    text: str,
) -> str:
    if source_event_id:
        raw = (
            f"{source_agent}:{source_kind}:{event_type}:"
            f"{client_instance_id or ''}:{source_event_id}"
        )
    else:
        raw = f"{source_agent}:{source_kind}:{event_type}:{client_instance_id or ''}:{text}"
    return f"capture:{sha256(raw.encode('utf-8')).hexdigest()}"
