"""Neutral LongMemEval session identities at the dataset loader boundary."""

from __future__ import annotations

import re
from collections.abc import Sequence
from hashlib import sha256

LONGMEMEVAL_SESSION_ALIAS_PREFIX = "session-"
LONGMEMEVAL_SESSION_IDENTITY_SCHEMA = "longmemeval_neutral_ordinal_v1"
_LONGMEMEVAL_SESSION_ALIAS_RE = re.compile(r"session-([0-9]{4})")


class LongMemEvalSessionIdentityError(ValueError):
    """Raised when raw LongMemEval session identity is not unambiguous."""


def safe_longmemeval_session_alias(value: object) -> str | None:
    """Return an exact public ordinal alias, never a private or malformed label."""

    if type(value) is not str:
        return None
    match = _LONGMEMEVAL_SESSION_ALIAS_RE.fullmatch(value)
    if match is None or int(match.group(1)) < 1:
        return None
    return value


class LongMemEvalSessionIdentity:
    """Resolve private dataset identifiers to stable ordinal aliases.

    Raw identifiers are retained only as one-way digests. Public attributes and
    representations therefore cannot disclose gold-bearing dataset labels.
    """

    __slots__ = ("_aliases", "_raw_id_digest_to_aliases")

    def __init__(
        self,
        *,
        aliases: tuple[str, ...],
        raw_id_digest_to_aliases: dict[str, tuple[str, ...]],
    ) -> None:
        self._aliases = aliases
        self._raw_id_digest_to_aliases = raw_id_digest_to_aliases

    @property
    def aliases(self) -> tuple[str, ...]:
        """Return public aliases in original session order."""

        return self._aliases

    @property
    def session_count(self) -> int:
        return len(self._aliases)

    def alias_for_index(self, index: int) -> str:
        """Return the alias for a zero-based session index."""

        if isinstance(index, bool) or not isinstance(index, int):
            raise LongMemEvalSessionIdentityError("session index must be an integer")
        if index < 0 or index >= len(self._aliases):
            raise LongMemEvalSessionIdentityError("session index is outside the identity map")
        return self._aliases[index]

    def alias_for_raw_id(self, raw_id: object) -> str:
        """Resolve one private raw identifier without returning that identifier."""

        normalized = _normalized_raw_id(raw_id, field="session identifier")
        aliases = self._raw_id_digest_to_aliases.get(_raw_id_digest(normalized))
        if aliases is None:
            raise LongMemEvalSessionIdentityError("session identifier is missing from identity map")
        if len(aliases) != 1:
            raise LongMemEvalSessionIdentityError("session identifier is ambiguous in identity map")
        return aliases[0]

    def answer_aliases(self, raw_answer_session_ids: object) -> tuple[str, ...]:
        """Resolve answer session identifiers after the neutral map is built."""

        raw_ids = _required_sequence(
            raw_answer_session_ids,
            field="answer session identifiers",
        )
        if not raw_ids:
            raise LongMemEvalSessionIdentityError("answer session identifiers must not be empty")
        aliases: list[str] = []
        seen_digests: set[str] = set()
        for raw_id in raw_ids:
            normalized = _normalized_raw_id(raw_id, field="answer session identifier")
            digest = _raw_id_digest(normalized)
            if digest in seen_digests:
                raise LongMemEvalSessionIdentityError("answer session identifiers must be unique")
            seen_digests.add(digest)
            aliases_for_id = self._raw_id_digest_to_aliases.get(digest)
            if aliases_for_id is None:
                raise LongMemEvalSessionIdentityError(
                    "answer session identifier is missing from identity map"
                )
            if len(aliases_for_id) != 1:
                raise LongMemEvalSessionIdentityError(
                    "answer session identifier is ambiguous in identity map"
                )
            aliases.append(aliases_for_id[0])
        return tuple(aliases)

    def __repr__(self) -> str:
        return f"LongMemEvalSessionIdentity(aliases={self._aliases!r})"


def build_longmemeval_session_identity(
    raw_session_ids: object,
    *,
    session_count: int,
) -> LongMemEvalSessionIdentity:
    """Build a complete, ambiguity-free map from raw IDs to ordinal aliases."""

    if isinstance(session_count, bool) or not isinstance(session_count, int):
        raise LongMemEvalSessionIdentityError("session count must be an integer")
    if session_count < 1:
        raise LongMemEvalSessionIdentityError("session count must be positive")

    raw_ids = _required_sequence(raw_session_ids, field="session identifiers")
    if len(raw_ids) != session_count:
        raise LongMemEvalSessionIdentityError(
            "session identifier count must match the session count"
        )

    aliases = tuple(
        f"{LONGMEMEVAL_SESSION_ALIAS_PREFIX}{ordinal:04d}"
        for ordinal in range(1, session_count + 1)
    )
    digest_to_aliases: dict[str, list[str]] = {}
    for raw_id, alias in zip(raw_ids, aliases, strict=True):
        normalized = _normalized_raw_id(raw_id, field="session identifier")
        if normalized in aliases:
            raise LongMemEvalSessionIdentityError(
                "raw session identifier collides with a public alias"
            )
        digest = _raw_id_digest(normalized)
        digest_to_aliases.setdefault(digest, []).append(alias)

    return LongMemEvalSessionIdentity(
        aliases=aliases,
        raw_id_digest_to_aliases={
            digest: tuple(mapped_aliases) for digest, mapped_aliases in digest_to_aliases.items()
        },
    )


def _required_sequence(value: object, *, field: str) -> tuple[object, ...]:
    if (
        isinstance(value, bool)
        or not isinstance(value, Sequence)
        or isinstance(value, str | bytes | bytearray)
    ):
        raise LongMemEvalSessionIdentityError(f"{field} must be a sequence")
    return tuple(value)


def _normalized_raw_id(value: object, *, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, str) or not value.strip():
        raise LongMemEvalSessionIdentityError(f"{field} must be a non-empty string")
    return value.strip()


def _raw_id_digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
