"""Source-identity helpers for memory-comparison evidence diagnostics."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

_TURN_REF_RE = re.compile(r"\bD\d+:\d+\b", re.IGNORECASE)
_SOURCE_SESSION_TURN_RE = re.compile(
    r"(?:^|:)session_(?P<session>\d+):(?P<turn_ref>D\d+:\d+):"
    r"(?:turn|chunk|fact)(?:[-_][^:]*)?$",
    re.IGNORECASE,
)
_TEXT_SESSION_TURN_RE = re.compile(
    r"\bsession_(?P<session>\d+)\s+(?:turn\s+)?(?P<turn_ref>D\d+:\d+)\b",
    re.IGNORECASE,
)
_TEXT_SESSION_DATE_TURN_RE = re.compile(
    r"\bsession_(?P<session>\d+)\s+date:\s*[^.\n]{0,80}?\s"
    r"(?P<turn_ref>D\d+:\d+)\b",
    re.IGNORECASE,
)
_SAFE_SOURCE_IDENTITY_REF_RE = re.compile(
    r"^(?:(?P<turn_prefix>source_turn_refs):(?P<turn_ref>D\d+:\d+)|"
    r"(?P<session_prefix>source_session_turn_refs):(?P<session>session_\d+):"
    r"(?P<session_turn_ref>D\d+:\d+))$",
    re.IGNORECASE,
)
_MAX_SAFE_SOURCE_IDENTITY_REF_LENGTH = 80
_MAX_SAFE_TURN_REF_LENGTH = 32
_MAX_SAFE_GENERIC_SOURCE_REF_LENGTH = 128
_MAX_SAFE_ITEM_ID_LENGTH = 128
_INSTRUCTION_LIKE_ITEM_ID_RE = re.compile(
    r"\b(?:ignore\s+previous\s+instructions|reveal\s+(?:the\s+)?"
    r"(?:system|developer)\s+prompt|system\s+prompt|developer\s+message)\b",
    re.IGNORECASE,
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
        f"{match.group('session').lower()}:{session_turn_ref}"
    )


def safe_turn_ref(value: object) -> str | None:
    ref = str(value or "").strip()
    if not ref or len(ref) > _MAX_SAFE_TURN_REF_LENGTH:
        return None
    if _TURN_REF_RE.fullmatch(ref.upper()) is None:
        return None
    return ref.upper()


def safe_source_refs_for_output(source_refs: Sequence[str]) -> tuple[str, ...]:
    refs: list[str] = []
    for raw_ref in source_refs:
        for ref in _safe_source_refs_for_output_value(raw_ref):
            if ref and ref not in refs:
                refs.append(ref)
    return tuple(refs)


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


def source_identity_refs_from_dedupe_key(value: object) -> tuple[str, ...]:
    key = str(value or "").strip()
    if not key:
        return ()
    key_lower = key.lower()
    if key_lower.startswith("source_identity:"):
        return source_identity_refs_from_dedupe_key(
            key[len("source_identity:") :]
        )
    for prefix in ("source_refs:", "refs:"):
        if key_lower.startswith(prefix):
            return _identity_refs_from_source_ref_values(
                _split_identity_refs(key[len(prefix) :])
            )
    for prefix in ("source_turn_refs:", "turn_refs:"):
        if not key_lower.startswith(prefix):
            continue
        return _safe_identity_refs(
            f"source_turn_refs:{ref}"
            for ref in _split_identity_refs(key[len(prefix) :])
        )
    if key_lower.startswith("source_session_turn_refs:"):
        return _safe_identity_refs(
            f"source_session_turn_refs:{ref}"
            for ref in _split_identity_refs(
                key[len("source_session_turn_refs:") :]
            )
        )
    return ()


def _safe_source_refs_for_output_value(value: object) -> tuple[str, ...]:
    text = str(value or "").strip()
    if not text:
        return ()
    identity_ref = safe_source_identity_ref(text)
    if identity_ref:
        return (identity_ref,)
    turn_ref = safe_turn_ref(text)
    if turn_ref:
        return (turn_ref,)
    identity_refs = source_identity_refs_from_source_refs(
        (text,),
        include_exact_turn_refs=True,
    )
    if identity_refs:
        return identity_refs
    if _TURN_REF_RE.search(text):
        return ()
    generic_ref = _safe_generic_source_ref(text)
    if generic_ref:
        return (generic_ref,)
    return ()


def _looks_like_raw_ref(value: str) -> bool:
    text = value.lower()
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
            "private-token",
            "private_token",
            "private-auth",
            "provider-auth",
            "provider-secret",
            "provider_payload",
            "raw_provider",
            "refresh-token",
            "refresh_token",
        )
    )


def source_identity_refs_from_text(
    text: str,
    *,
    source_refs: Sequence[str],
) -> tuple[str, ...]:
    if source_refs:
        return ()
    session_turn_refs = _session_turn_refs_from_text(text)
    if 0 < len(session_turn_refs) <= 3:
        return _session_identity_refs(session_turn_refs)
    turn_refs = _safe_turn_refs(_TURN_REF_RE.findall(text or ""))
    if not 0 < len(turn_refs) <= 3:
        return ()
    return tuple(f"source_turn_refs:{ref}" for ref in sorted(turn_refs))


def source_identity_refs_from_source_refs(
    source_refs: Sequence[str],
    *,
    include_exact_turn_refs: bool = False,
) -> tuple[str, ...]:
    refs = tuple(str(ref).strip() for ref in source_refs if str(ref).strip())
    session_turn_refs = _source_session_turn_refs(refs)
    turn_refs = _source_turn_refs(
        refs,
        include_exact_turn_refs=include_exact_turn_refs,
    )
    if 0 < len(session_turn_refs) <= 3:
        identity_refs = list(_session_identity_refs(session_turn_refs))
        session_turn_values = _turn_refs_from_session_turn_refs(session_turn_refs)
        extra_turn_refs = tuple(
            ref for ref in sorted(turn_refs) if ref not in session_turn_values
        )
        if len(session_turn_refs) + len(extra_turn_refs) <= 3:
            identity_refs.extend(f"source_turn_refs:{ref}" for ref in extra_turn_refs)
        return tuple(dict.fromkeys(identity_refs))
    if not 0 < len(turn_refs) <= 3:
        return ()
    return tuple(f"source_turn_refs:{ref}" for ref in sorted(turn_refs))


def source_identity_audit_gap_codes(
    *,
    source_refs: Sequence[str],
    text: str,
) -> tuple[str, ...]:
    refs = tuple(str(ref).strip() for ref in source_refs if str(ref).strip())
    source_turn_refs = _source_turn_refs(refs, include_exact_turn_refs=True)
    source_session_turn_refs = _source_session_turn_refs(refs)
    text_session_turn_refs = _session_turn_refs_from_text(text)
    text_turn_refs = _safe_turn_refs(_TURN_REF_RE.findall(text or ""))
    has_text_turn_identity = bool(text_session_turn_refs or text_turn_refs)

    gap_codes: list[str] = []
    if not refs:
        gap_codes.append(
            "missing_source_refs_with_text_turn_identity"
            if has_text_turn_identity
            else "missing_source_refs"
        )
    elif not source_turn_refs:
        gap_codes.append(
            "generic_source_refs_with_text_turn_identity"
            if has_text_turn_identity
            else "source_refs_without_turn_identity"
        )
    if len(source_turn_refs) > 3:
        gap_codes.append("broad_source_turn_identity")
    elif not source_turn_refs and len(text_turn_refs) > 3:
        gap_codes.append("broad_text_turn_identity")
    if (
        source_session_turn_refs
        and text_session_turn_refs
        and not set(source_session_turn_refs).intersection(text_session_turn_refs)
    ):
        gap_codes.append("source_text_session_turn_mismatch")
    elif (
        source_turn_refs
        and text_turn_refs
        and not set(source_turn_refs).intersection(text_turn_refs)
    ):
        gap_codes.append("source_text_turn_mismatch")
    if _session_count(source_session_turn_refs) > 1:
        gap_codes.append("cross_session_source_identity")
    elif not source_session_turn_refs and _session_count(text_session_turn_refs) > 1:
        gap_codes.append("cross_session_text_identity")
    return tuple(dict.fromkeys(gap_codes))


def _split_identity_refs(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(ref.strip() for ref in value.split("|") if ref.strip())
    )


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


def _identity_refs_from_source_ref_values(values: Iterable[object]) -> tuple[str, ...]:
    refs: list[str] = []
    for raw_ref in values:
        source_ref = str(raw_ref or "").strip()
        if not source_ref:
            continue
        identity_refs = source_identity_refs_from_source_refs(
            (source_ref,),
            include_exact_turn_refs=True,
        )
        if identity_refs:
            refs.extend(identity_refs)
            continue
        generic_ref = _safe_generic_source_ref(source_ref)
        if generic_ref:
            refs.append(generic_ref)
    return tuple(dict.fromkeys(refs))


def _safe_generic_source_ref(value: object) -> str | None:
    ref = str(value or "").strip()
    if not ref:
        return None
    if _looks_like_raw_ref(ref):
        return None
    if len(ref) > _MAX_SAFE_GENERIC_SOURCE_REF_LENGTH:
        return None
    return ref


def _source_turn_refs(
    source_refs: Sequence[str],
    *,
    include_exact_turn_refs: bool,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            ref
            for source_ref in source_refs
            if include_exact_turn_refs or _TURN_REF_RE.fullmatch(source_ref) is None
            for ref in _safe_turn_refs(_TURN_REF_RE.findall(source_ref))
        )
    )


def _source_session_turn_refs(source_refs: Sequence[str]) -> tuple[str, ...]:
    refs: list[str] = []
    for source_ref in source_refs:
        safe_ref = safe_source_identity_ref(source_ref)
        if safe_ref and safe_ref.startswith("source_session_turn_refs:"):
            refs.append(safe_ref.removeprefix("source_session_turn_refs:"))
            continue
        match = _SOURCE_SESSION_TURN_RE.search(source_ref)
        if match is None:
            continue
        turn_ref = safe_turn_ref(match.group("turn_ref"))
        if turn_ref:
            refs.append(f"session_{match.group('session')}:{turn_ref}")
    return tuple(dict.fromkeys(refs))


def _session_turn_refs_from_text(text: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            f"session_{match.group('session')}:{turn_ref}"
            for pattern in (_TEXT_SESSION_TURN_RE, _TEXT_SESSION_DATE_TURN_RE)
            for match in pattern.finditer(text or "")
            for turn_ref in (safe_turn_ref(match.group("turn_ref")),)
            if turn_ref
        )
    )


def _session_identity_refs(session_turn_refs: Sequence[str]) -> tuple[str, ...]:
    qualified = tuple(
        f"source_session_turn_refs:{ref}" for ref in sorted(session_turn_refs)
    )
    if _session_count(session_turn_refs) != 1:
        return qualified
    turn_refs: list[str] = []
    for session_ref in session_turn_refs:
        match = _TURN_REF_RE.search(session_ref)
        if match is not None:
            turn_ref = safe_turn_ref(match.group(0))
            if turn_ref:
                turn_refs.append(turn_ref)
    unqualified = tuple(
        f"source_turn_refs:{ref}"
        for ref in sorted(dict.fromkeys(turn_refs))
    )
    return (*qualified, *unqualified)


def _turn_refs_from_session_turn_refs(session_turn_refs: Sequence[str]) -> tuple[str, ...]:
    return _safe_turn_refs(
        match.group(0)
        for session_ref in session_turn_refs
        for match in (_TURN_REF_RE.search(session_ref),)
        if match is not None
    )


def _session_count(session_turn_refs: Sequence[str]) -> int:
    return len(
        {
            match.group("session")
            for ref in session_turn_refs
            if (
                match := re.search(
                    r"\bsession_(?P<session>\d+):D\d+:\d+\b",
                    ref,
                    re.IGNORECASE,
                )
            )
        }
    )
