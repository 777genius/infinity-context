"""Shared weak-candidate risk detection for memory comparison retrieval."""

from __future__ import annotations

import re
from collections.abc import Mapping

from infinity_context_server.memory_comparison_models import RetrievedMemory

_BROAD_SUMMARY_SURFACE_RE = re.compile(
    r"\b(?:conversation summary|memory summary|observations|related turns|"
    r"events date|summari[sz]ed turns|summary of)\b|\bsummary\s*:",
    re.IGNORECASE,
)


def candidate_features(memory: RetrievedMemory) -> Mapping[str, object]:
    diagnostics = _mapping(memory.metadata.get("diagnostics"))
    return _mapping(diagnostics.get("benchmark_candidate_features"))


def memory_has_broad_summary(
    memory: RetrievedMemory,
    features: Mapping[str, object] | None = None,
) -> bool:
    candidate_features = features if features is not None else {}
    return candidate_features.get("broad_summary") is True or bool(
        _BROAD_SUMMARY_SURFACE_RE.search(memory.text or "")
    )


def memory_has_conflict_or_stale(
    memory: RetrievedMemory,
    features: Mapping[str, object] | None = None,
) -> bool:
    candidate_features = features if features is not None else {}
    if candidate_features.get("conflict_or_stale") is True:
        return True
    diagnostics = _mapping(memory.metadata.get("diagnostics"))
    stale_reason = diagnostics.get("stale_reason") or memory.metadata.get(
        "stale_reason"
    )
    conflict_count = diagnostics.get("conflict_count") or memory.metadata.get(
        "conflict_count"
    )
    return bool(stale_reason) or bool(_positive_int(conflict_count))


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}
