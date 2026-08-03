"""Stable typed role memberships retained across ranked-evidence transforms."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

PAIRED_EVIDENCE_ROLE_MEMBERSHIPS_KEY = "paired_evidence_role_memberships"
_MAX_ROLE_MEMBERSHIPS = 4
_TYPED_ENDPOINT_ROLE_RE = re.compile(
    r"^decomposition_temporal(?:_interval)?_endpoint_[12]$"
)


def paired_evidence_role_memberships(signals: Mapping[str, object]) -> tuple[str, ...]:
    """Return bounded typed endpoint roles without trusting arbitrary diagnostics."""

    raw_values = signals.get(PAIRED_EVIDENCE_ROLE_MEMBERSHIPS_KEY)
    values = (
        raw_values
        if isinstance(raw_values, Sequence) and not isinstance(raw_values, str | bytes)
        else ()
    )
    candidates = (*values, signals.get("query_expansion_reason"))
    seen: set[str] = set()
    memberships: list[str] = []
    for value in candidates:
        normalized = str(value).strip()
        if not _is_typed_endpoint_role(normalized) or normalized in seen:
            continue
        seen.add(normalized)
        memberships.append(normalized)
        if len(memberships) >= _MAX_ROLE_MEMBERSHIPS:
            break
    return tuple(memberships)


def merge_paired_evidence_role_memberships(
    *signals: Mapping[str, object],
) -> tuple[str, ...]:
    """Union role memberships in deterministic caller-priority order."""

    seen: set[str] = set()
    memberships: list[str] = []
    for mapping in signals:
        for membership in paired_evidence_role_memberships(mapping):
            if membership in seen:
                continue
            seen.add(membership)
            memberships.append(membership)
            if len(memberships) >= _MAX_ROLE_MEMBERSHIPS:
                return tuple(memberships)
    return tuple(memberships)


def _is_typed_endpoint_role(value: str) -> bool:
    return bool(_TYPED_ENDPOINT_ROLE_RE.fullmatch(value))


__all__ = (
    "PAIRED_EVIDENCE_ROLE_MEMBERSHIPS_KEY",
    "merge_paired_evidence_role_memberships",
    "paired_evidence_role_memberships",
)
