"""Source-identity helpers for memory-comparison evidence diagnostics."""

from __future__ import annotations

import re
from collections.abc import Sequence

_TURN_REF_RE = re.compile(r"\bD\d+:\d+\b")


def source_identity_refs_from_dedupe_key(value: object) -> tuple[str, ...]:
    key = str(value or "").strip()
    if not key:
        return ()
    for prefix in ("source_refs:", "refs:"):
        if key.startswith(prefix):
            return _split_identity_refs(key.removeprefix(prefix))
    if key.startswith("source_turn_refs:"):
        return tuple(
            f"source_turn_refs:{ref}"
            for ref in _split_identity_refs(key.removeprefix("source_turn_refs:"))
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


def _split_identity_refs(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(ref.strip() for ref in value.split("|") if ref.strip())
    )
