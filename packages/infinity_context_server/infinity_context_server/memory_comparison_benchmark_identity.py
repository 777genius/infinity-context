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


def mem0_benchmark_corpus_user_id(run_id: str, corpus_key: str) -> str:
    """Return a non-reversible Mem0 entity identity for one exact corpus.

    Mem0's supported entity filters are ``user_id`` and ``run_id``.  A
    run-wide user_id would let one selected corpus retrieve another corpus's
    memories, so the corpus participates in the entity identity itself.
    """

    if not valid_benchmark_run_id(run_id):
        raise ValueError("run_id must match the managed adapter SafeIdentifier contract")
    if (
        type(corpus_key) is not str
        or not corpus_key
        or len(corpus_key) > 4_096
        or not any(not character.isspace() for character in corpus_key)
    ):
        raise ValueError("corpus_key must be a non-empty bounded identifier")
    digest = hashlib.sha256(f"{run_id}\0{corpus_key}".encode("utf-8")).hexdigest()
    return f"memo-stack-comparison-corpus-{digest}"


__all__ = (
    "mem0_benchmark_corpus_user_id",
    "mem0_benchmark_user_id",
    "valid_benchmark_run_id",
)
