"""Provider-neutral benchmark identities accepted by the managed mem0 adapter."""

from __future__ import annotations

import hashlib
import re

_SAFE_IDENTIFIER_MAX_LENGTH = 160
_READABLE_SLUG_MAX_LENGTH = 73
_NON_ALNUM_RUN = re.compile(r"-+")


def valid_benchmark_run_id(value: object) -> bool:
    """Match the adapter SafeIdentifier: exact string, <=160, with non-whitespace."""

    return bool(
        type(value) is str
        and 0 < len(value) <= _SAFE_IDENTIFIER_MAX_LENGTH
        and any(not character.isspace() for character in value)
    )


def mem0_benchmark_user_id(run_id: str) -> str:
    """Return a readable collision-resistant managed-adapter user identity."""

    if not valid_benchmark_run_id(run_id):
        raise ValueError("run_id must match the managed adapter SafeIdentifier contract")
    readable = "".join(
        character.lower()
        if character.isascii() and (character.isalnum() or character == "-")
        else "-"
        for character in run_id
    )
    readable = _NON_ALNUM_RUN.sub("-", readable).strip("-") or "run"
    readable = readable[:_READABLE_SLUG_MAX_LENGTH].rstrip("-") or "run"
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
    return f"memo-stack-comparison-{readable}-{digest}"


__all__ = ("mem0_benchmark_user_id", "valid_benchmark_run_id")
