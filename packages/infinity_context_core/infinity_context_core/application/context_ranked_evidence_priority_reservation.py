"""Bounded application-evidence reservations for ranked consumers."""

from __future__ import annotations

from collections.abc import Mapping

from infinity_context_core.application.dto import ContextItem

_MAX_RESERVATIONS = 8


def reserve_application_evidence_head(
    items: tuple[ContextItem, ...],
) -> tuple[ContextItem, ...]:
    """Move only producer-vetted application evidence to a stable bounded head."""

    reserved_indices = tuple(
        index for index, item in enumerate(items) if _application_evidence_priority(item) == 1
    )[:_MAX_RESERVATIONS]
    if not reserved_indices:
        return items
    reserved_index_set = set(reserved_indices)
    return (
        *(items[index] for index in reserved_indices),
        *(item for index, item in enumerate(items) if index not in reserved_index_set),
    )


def _application_evidence_priority(item: ContextItem) -> object:
    diagnostics = item.diagnostics or {}
    signals = diagnostics.get("score_signals")
    if not isinstance(signals, Mapping):
        return None
    return signals.get("application_evidence_priority")


__all__ = ("reserve_application_evidence_head",)
