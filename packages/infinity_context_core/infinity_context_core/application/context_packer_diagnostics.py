"""Context packer diagnostic access helpers."""

from __future__ import annotations

from infinity_context_core.application.dto import ContextItem


def diagnostic_value(item: ContextItem, key: str) -> object:
    diagnostics = item.diagnostics or {}
    value = diagnostics.get(key)
    if value is None:
        provenance = diagnostics.get("provenance")
        if isinstance(provenance, dict):
            value = provenance.get(key)
    return value


def diagnostic_text(item: ContextItem, key: str) -> str:
    value = diagnostic_value(item, key)
    return str(value).strip() if value is not None else ""


def diagnostic_signal_text(item: ContextItem, key: str) -> str:
    diagnostics = item.diagnostics or {}
    score_signals = diagnostics.get("score_signals")
    if isinstance(score_signals, dict):
        value = score_signals.get(key)
        if value is not None:
            return str(value).strip()
    return diagnostic_text(item, key)


def diagnostic_signal_truthy(item: ContextItem, key: str) -> bool:
    value = diagnostic_signal_text(item, key).casefold()
    return value in {"1", "true", "yes"}


def diagnostic_score_signals(item: ContextItem) -> dict[str, object]:
    diagnostics = item.diagnostics or {}
    score_signals = diagnostics.get("score_signals")
    return score_signals if isinstance(score_signals, dict) else {}


def diagnostic_list(item: ContextItem, key: str) -> tuple[str, ...]:
    values = diagnostic_value(item, key)
    if not isinstance(values, list | tuple):
        return ()
    return tuple(str(value).strip() for value in values if str(value).strip())
