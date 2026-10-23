"""Safe source-reference primitives and private-label detection."""

from __future__ import annotations

import re
from collections.abc import (
    Iterable,
)

from infinity_context_core.sensitive_text import (
    contains_sensitive_text,
)

_TURN_REF_PARTS_RE = re.compile(
    r"^D(?P<dialogue>\d+)[:-](?P<turn>\d+)$",
    re.IGNORECASE,
)


_DIALOGUE_REF_PARTS_RE = re.compile(r"^D(?P<dialogue>\d+)$", re.IGNORECASE)


_SAFE_SOURCE_IDENTITY_REF_RE = re.compile(
    r"^(?:(?P<turn_prefix>source_turn_refs):(?P<turn_ref>D\d+[:-]\d+)|"
    r"(?P<session_prefix>source_session_turn_refs):(?P<session>session[-_]\d+):"
    r"(?P<session_turn_ref>D\d+[:-]\d+))$",
    re.IGNORECASE,
)


_MAX_SAFE_SOURCE_IDENTITY_REF_LENGTH = 80


_MAX_SAFE_TURN_REF_LENGTH = 32


_MAX_SAFE_GENERIC_SOURCE_REF_LENGTH = 128


_MAX_SAFE_ITEM_ID_LENGTH = 128


_MAX_SAFE_SOURCE_LABEL_LENGTH = 64


_PRIVATE_PROVIDER_SOURCE_LABEL_PREFIXES = frozenset(
    {
        "backend",
        "graphiti",
        "mem0",
        "openai",
        "provider",
        "qdrant",
    }
)


_PRIVATE_PROVIDER_SOURCE_LABEL_SEPARATORS = (":", "-", "_", ".")


_INSTRUCTION_LIKE_ITEM_ID_RE = re.compile(
    r"\b(?:ignore\s+previous\s+instructions|reveal\s+(?:the\s+)?"
    r"(?:system|developer)\s+prompt|system\s+prompt|developer\s+message)\b",
    re.IGNORECASE,
)


_ABSOLUTE_PATH_REF_RE = re.compile(
    r"^(?:file://|~[/\\]|/|[A-Za-z]:[/\\])",
    re.IGNORECASE,
)


_PRIVATE_PATH_SEGMENTS = frozenset(
    {
        ".aws",
        ".azure",
        ".codex",
        ".config",
        ".gcp",
        ".gnupg",
        ".ssh",
        "private",
        "secrets",
    }
)


_PRIVATE_PATH_BASENAMES = frozenset(
    {
        ".env",
        "api_key",
        "api_key.json",
        "api-key.json",
        "auth.json",
        "credentials",
        "credentials.json",
        "secret",
        "secret.json",
        "secrets.json",
        "token",
        "token.json",
    }
)


_PRIVATE_PATH_NAME_MARKERS = (
    "api-key",
    "api_key",
    "auth",
    "credential",
    "secret",
    "token",
)


def safe_source_identity_ref(value: object) -> str | None:
    ref = str(value or "").strip()
    if not ref or len(ref) > _MAX_SAFE_SOURCE_IDENTITY_REF_LENGTH:
        return None
    match = _SAFE_SOURCE_IDENTITY_REF_RE.fullmatch(ref)
    if match is None:
        return None
    if match.group("turn_ref"):
        turn_ref = safe_turn_ref(match.group("turn_ref"))
        return f"source_turn_refs:{turn_ref}" if turn_ref else None
    session_turn_ref = safe_turn_ref(match.group("session_turn_ref"))
    if not session_turn_ref:
        return None
    return (
        "source_session_turn_refs:"
        f"{_normalized_session_ref(match.group('session'))}:{session_turn_ref}"
    )


def safe_turn_ref(value: object) -> str | None:
    ref = str(value or "").strip()
    if not ref or len(ref) > _MAX_SAFE_TURN_REF_LENGTH:
        return None
    match = _TURN_REF_PARTS_RE.fullmatch(ref)
    if match is None:
        return None
    return f"D{match.group('dialogue')}:{match.group('turn')}"


def safe_source_label_for_output(value: object) -> str | None:
    label = str(value or "").strip()
    if not label or len(label) > _MAX_SAFE_SOURCE_LABEL_LENGTH:
        return None
    if _looks_like_private_provider_source_label(label):
        return None
    return label


def looks_like_raw_source_ref(value: object) -> bool:
    """Return true for provider/private source references that must not be emitted."""
    return _looks_like_raw_ref(str(value or "").strip())


def safe_item_id_for_output(value: object) -> str:
    item_id = str(value or "").strip()
    if not item_id:
        return ""
    if _looks_like_raw_ref(item_id) or _INSTRUCTION_LIKE_ITEM_ID_RE.search(item_id):
        return ""
    if len(item_id) > _MAX_SAFE_ITEM_ID_LENGTH:
        return f"{item_id[: _MAX_SAFE_ITEM_ID_LENGTH - 3]}..."
    return item_id


def _looks_like_raw_ref(value: str) -> bool:
    if contains_sensitive_text(value):
        return True
    text = value.lower()
    if _looks_like_private_path_ref(text):
        return True
    if "locomo:" in text or "conv-private" in text or "turn-secret" in text:
        return True
    if any(
        text.startswith(prefix)
        for prefix in (
            "backend:",
            "graphiti:",
            "mem0:",
            "memory://",
            "openai:",
            "provider:",
            "provider-ref-",
            "qdrant:",
        )
    ):
        return True
    return any(
        marker in text
        for marker in (
            "access-token",
            "access_token",
            "api-key",
            "api_key",
            "auth-private",
            "auth-payload",
            "auth_payload",
            "bearer-token",
            "bearer_token",
            "private-payload",
            "private_payload",
            "private-token",
            "private_token",
            "private-auth",
            "provider-auth",
            "provider-private",
            "provider-secret",
            "provider_payload",
            "provider_private",
            "raw-provider",
            "raw_provider",
            "refresh-token",
            "refresh_token",
        )
    )


def _looks_like_private_provider_source_label(value: str) -> bool:
    if _looks_like_raw_ref(value):
        return True
    label = value.strip().casefold()
    return any(
        label == prefix
        or any(
            label.startswith(f"{prefix}{separator}")
            for separator in _PRIVATE_PROVIDER_SOURCE_LABEL_SEPARATORS
        )
        for prefix in _PRIVATE_PROVIDER_SOURCE_LABEL_PREFIXES
    )


def _looks_like_private_path_ref(value: str) -> bool:
    path = value.strip().replace("\\", "/")
    if not path:
        return False
    if _ABSOLUTE_PATH_REF_RE.search(path):
        return True
    basename = path.rsplit("/", 1)[-1]
    if basename in _PRIVATE_PATH_BASENAMES:
        return True
    if basename.endswith((".env", ".json")) and any(
        marker in basename for marker in _PRIVATE_PATH_NAME_MARKERS
    ):
        return True
    if "/" not in path:
        return False
    parts = tuple(part for part in path.split("/") if part)
    return any(part in _PRIVATE_PATH_SEGMENTS for part in parts)


def _split_identity_refs(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(ref.strip() for ref in value.split("|") if ref.strip())
    )


def _safe_dialogue_ref(value: object) -> str:
    ref = str(value or "").strip()
    if not ref:
        return ""
    match = _DIALOGUE_REF_PARTS_RE.fullmatch(ref)
    return f"D{match.group('dialogue')}" if match else ""


def _positive_int_string(value: object) -> str:
    text = str(value or "").strip()
    if match := re.fullmatch(
        r"(?:turn|utt|utterance|t)[-_:\s#]*(?P<turn>\d+)",
        text,
        re.IGNORECASE,
    ):
        text = match.group("turn")
    if not text.isdigit():
        return ""
    parsed = int(text)
    return str(parsed) if parsed > 0 else ""


def _safe_identity_refs(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            ref
            for raw_ref in values
            for ref in (safe_source_identity_ref(raw_ref),)
            if ref
        )
    )


def _safe_turn_refs(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            ref
            for raw_ref in values
            for ref in (safe_turn_ref(raw_ref),)
            if ref
        )
    )


def _looks_like_source_identity_dedupe_key(value: str) -> bool:
    return value.lower().startswith(
        (
            "refs:",
            "source_identity:",
            "source_refs:",
            "source_session_turn_refs:",
            "source_turn_refs:",
            "turn_refs:",
        )
    )


def _safe_generic_source_ref(value: object) -> str | None:
    ref = str(value or "").strip()
    if not ref:
        return None
    if _looks_like_raw_ref(ref):
        return None
    if len(ref) > _MAX_SAFE_GENERIC_SOURCE_REF_LENGTH:
        return None
    return ref


def _normalized_session_ref(value: object) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(
        r"(?:session|conversation|conv|dialogue|dialog)"
        r"(?:[-_]\s*|\s+#?\s*)(?P<session>\d+)",
        text,
        re.IGNORECASE,
    )
    if match:
        return f"session_{match.group('session')}"
    return ""
