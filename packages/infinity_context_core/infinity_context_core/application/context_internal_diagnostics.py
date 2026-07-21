"""Typed reads of internal context diagnostics without public-payload projection."""

from __future__ import annotations

from collections.abc import Mapping

from infinity_context_core.application.dto import ContextItem


def diagnostic_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}


def nested_diagnostic_mapping(
    diagnostics: Mapping[str, object],
    key: str,
) -> Mapping[str, object]:
    value = diagnostics.get(key)
    return value if isinstance(value, dict) else {}


def diagnostic_text(diagnostics: Mapping[str, object], key: str) -> str:
    value = diagnostics.get(key)
    return value.strip() if isinstance(value, str) else ""


def item_score_signal_reason(item: ContextItem) -> str:
    diagnostics = diagnostic_mapping(item.diagnostics)
    return diagnostic_text(
        nested_diagnostic_mapping(diagnostics, "score_signals"),
        "query_expansion_reason",
    )


def item_diagnostic_source_id(item: ContextItem) -> str:
    diagnostics = diagnostic_mapping(item.diagnostics)
    source_id = diagnostic_text(diagnostics, "source_id")
    if source_id:
        return source_id
    return diagnostic_text(
        nested_diagnostic_mapping(diagnostics, "provenance"),
        "source_id",
    )


def provenance_flag_is_true(diagnostics: object, flag: str) -> bool:
    provenance = nested_diagnostic_mapping(
        diagnostic_mapping(diagnostics),
        "provenance",
    )
    return provenance.get(flag) is True


__all__ = (
    "diagnostic_mapping",
    "diagnostic_text",
    "item_diagnostic_source_id",
    "item_score_signal_reason",
    "nested_diagnostic_mapping",
    "provenance_flag_is_true",
)
