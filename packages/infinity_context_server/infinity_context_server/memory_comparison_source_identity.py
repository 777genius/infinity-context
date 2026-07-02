"""Source-identity helpers for memory-comparison evidence diagnostics."""

from __future__ import annotations

import re
from collections.abc import Sequence

_TURN_REF_RE = re.compile(r"\bD\d+:\d+\b")


def source_identity_refs_from_dedupe_key(value: object) -> tuple[str, ...]:
    key = str(value or "").strip()
    if not key:
        return ()
    if key.startswith("source_identity:"):
        return source_identity_refs_from_dedupe_key(
            key.removeprefix("source_identity:")
        )
    for prefix in ("source_refs:", "refs:"):
        if key.startswith(prefix):
            return _split_identity_refs(key.removeprefix(prefix))
    for prefix in ("source_turn_refs:", "turn_refs:"):
        if not key.startswith(prefix):
            continue
        return tuple(
            f"source_turn_refs:{ref}"
            for ref in _split_identity_refs(key.removeprefix(prefix))
        )
    return ()


def source_identity_refs_from_text(
    text: str,
    *,
    source_refs: Sequence[str],
) -> tuple[str, ...]:
    if source_refs:
        return ()
    turn_refs = tuple(dict.fromkeys(_TURN_REF_RE.findall(text or "")))
    if not 0 < len(turn_refs) <= 3:
        return ()
    return tuple(f"source_turn_refs:{ref}" for ref in sorted(turn_refs))


def source_identity_refs_from_source_refs(
    source_refs: Sequence[str],
    *,
    include_exact_turn_refs: bool = False,
) -> tuple[str, ...]:
    refs = tuple(str(ref).strip() for ref in source_refs if str(ref).strip())
    turn_refs = tuple(
        dict.fromkeys(
            ref
            for source_ref in refs
            if include_exact_turn_refs or _TURN_REF_RE.fullmatch(source_ref) is None
            for ref in _TURN_REF_RE.findall(source_ref)
        )
    )
    if not 0 < len(turn_refs) <= 3:
        return ()
    return tuple(f"source_turn_refs:{ref}" for ref in sorted(turn_refs))


def _split_identity_refs(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(ref.strip() for ref in value.split("|") if ref.strip())
    )
