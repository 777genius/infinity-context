"""Bounded session identities for ranked-evidence benchmark source refs."""

from __future__ import annotations

import re
from dataclasses import dataclass

_LOCOMO_TURN_REF_RE = re.compile(
    r"(?<![a-z0-9])D(?P<session>[1-9]\d{0,5}):[1-9]\d{0,6}(?!\d)",
    re.IGNORECASE,
)
_LOCOMO_SESSION_REF_RE = re.compile(
    r"(?<![a-z0-9])session_(?P<session>[1-9]\d{0,5})(?!\d)",
    re.IGNORECASE,
)
_LONGMEMEVAL_SESSION_REF_RE = re.compile(
    r"(?<![a-z0-9])session-(?P<session>\d{4})(?!\d)",
    re.IGNORECASE,
)
_LONGMEMEVAL_CANONICAL_SOURCE_REF_RE = re.compile(
    r"^longmemeval:(?P<case>[a-z0-9][a-z0-9._-]{0,159}):"
    r"session:(?P<session>[1-9]\d{0,3})"
    r"(?::pair:(?P<pair>[1-9]\d{0,6})"
    r"(?::message:(?P<message>[1-9]\d{0,6}))?)?$",
    re.IGNORECASE,
)
_LONGMEMEVAL_SCOPED_SESSION_REF_RE = re.compile(
    r"^longmemeval:(?P<case>[a-z0-9][a-z0-9._-]{0,159}):"
    r"session-(?P<session>\d{4})"
    r"(?::pair:(?P<pair>[1-9]\d{0,6})"
    r"(?::message:(?P<message>[1-9]\d{0,6}))?)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class LongMemEvalSourceIdentity:
    """Validated case-scoped LongMemEval session identity."""

    case_id: str
    session_key: str


def longmemeval_source_identity(source_ref: str) -> LongMemEvalSourceIdentity | None:
    """Parse one complete canonical or scoped LongMemEval session ref."""

    match = _LONGMEMEVAL_CANONICAL_SOURCE_REF_RE.fullmatch(source_ref)
    if match is None:
        match = _LONGMEMEVAL_SCOPED_SESSION_REF_RE.fullmatch(source_ref)
    if match is None:
        return None
    return LongMemEvalSourceIdentity(
        case_id=match.group("case"),
        session_key=f"longmemeval:session-{int(match.group('session')):04d}",
    )


def source_ref_session_keys(source_ref: str) -> frozenset[str] | None:
    """Return one validated benchmark session key, or ``None`` when malformed."""

    sessions = {
        f"locomo:{int(match.group('session'))}"
        for pattern in (_LOCOMO_TURN_REF_RE, _LOCOMO_SESSION_REF_RE)
        for match in pattern.finditer(source_ref)
    }
    is_scoped_longmemeval = source_ref.casefold().startswith("longmemeval:")
    identity = longmemeval_source_identity(source_ref)
    if is_scoped_longmemeval:
        if identity is None:
            return None
        sessions.add(identity.session_key)
    else:
        sessions.update(
            f"longmemeval:session-{match.group('session')}"
            for match in _LONGMEMEVAL_SESSION_REF_RE.finditer(source_ref)
        )
    if len(sessions) > 1:
        return None
    return frozenset(sessions)


def longmemeval_official_session_aliases(
    source_ref: str,
    *,
    case_id: str,
) -> tuple[str, ...]:
    """Return aliases only when a validated source ref belongs to the active case."""

    identity = longmemeval_source_identity(source_ref)
    if identity is None or identity.case_id != case_id:
        return ()
    return (identity.session_key.removeprefix("longmemeval:"),)


__all__ = (
    "LongMemEvalSourceIdentity",
    "longmemeval_official_session_aliases",
    "longmemeval_source_identity",
    "source_ref_session_keys",
)
