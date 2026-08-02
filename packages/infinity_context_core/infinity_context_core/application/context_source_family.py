"""Canonical source-family identities for source-diverse reservations."""

from __future__ import annotations

import re
from dataclasses import dataclass

from infinity_context_core.application.context_packer_diagnostics import diagnostic_text
from infinity_context_core.application.dto import ContextItem

_SEPARATOR_RE = re.compile(r"[:_\-\s]+")
_TURN_RE = re.compile(
    r"(?:^|[:_-])D(?P<dialogue>[0-9]{1,6})[:-][0-9]{1,6}(?=$|[:_-])",
    re.IGNORECASE,
)
_GROUP_TRAILER_RE = re.compile(
    r"(?:[:_-])(?:pair|record)(?:[:_-][^:]*)*\Z",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SourceFamilyIdentity:
    """Canonical source base plus optional explicit memory-scope identity."""

    source_type: str
    source_identity: str
    memory_scope_id: str | None

    @property
    def base_key(self) -> str:
        return f"{self.source_type}:{self.source_identity}"

    @property
    def reservation_key(self) -> str:
        scope = self.memory_scope_id or "unknown-memory-scope"
        return f"{scope}:{self.base_key}"


def canonical_source_family(item: ContextItem) -> str:
    """Return one scope-isolated family or an empty value when ambiguous."""

    identity = canonical_source_family_identity(item)
    return identity.reservation_key if identity is not None else ""


def canonical_source_family_identity(item: ContextItem) -> SourceFamilyIdentity | None:
    """Return one structured family and preserve whether scope was explicit."""

    scope = _normalized_identity(diagnostic_text(item, "memory_scope_id")) or None
    families = tuple(
        _source_ref_family(
            source_type=ref.source_type,
            source_id=ref.source_id,
            scope=scope,
        )
        for ref in item.source_refs
    )
    if not families or any(family is None for family in families):
        return None
    first = families[0]
    assert first is not None
    return first if all(family == first for family in families) else None


def _source_ref_family(
    *,
    source_type: str,
    source_id: str,
    scope: str | None,
) -> SourceFamilyIdentity | None:
    normalized_type = _normalized_identity(source_type)
    raw_id = str(source_id or "").strip()
    if not normalized_type or not raw_id:
        return None
    raw_id = _GROUP_TRAILER_RE.sub("", raw_id)
    marker = _TURN_RE.search(raw_id)
    if marker is not None:
        prefix = _normalized_identity(raw_id[: marker.start()])
        source_identity = prefix or f"bare-session-{marker.group('dialogue')}"
    else:
        source_identity = _normalized_identity(raw_id)
    if not source_identity:
        return None
    return SourceFamilyIdentity(
        source_type=normalized_type,
        source_identity=source_identity,
        memory_scope_id=scope,
    )


def _normalized_identity(value: object) -> str:
    return _SEPARATOR_RE.sub("-", str(value or "").strip().casefold()).strip("-")


__all__ = (
    "SourceFamilyIdentity",
    "canonical_source_family",
    "canonical_source_family_identity",
)
