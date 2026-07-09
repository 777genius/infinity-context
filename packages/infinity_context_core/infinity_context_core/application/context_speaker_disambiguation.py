"""Competitor-aware speaker disambiguation for deterministic context ranking."""

from __future__ import annotations

from dataclasses import replace

from infinity_context_core.application.context_diagnostics import (
    normalize_context_diagnostics,
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_speaker_attribution import (
    speaker_attribution_match,
)
from infinity_context_core.application.dto import ContextItem

_ALIAS_SHADOWED_BY_EXACT_NAME_PENALTY = 0.05


def apply_attributed_speaker_exact_name_disambiguation(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    max_penalty: float,
) -> tuple[ContextItem, ...]:
    """Demote ambiguous speaker aliases when exact full-name evidence is present."""

    if len(items) < 2 or max_penalty <= 0:
        return items
    matches = tuple(speaker_attribution_match(query=query, text=item.text) for item in items)
    if not any(
        match is not None
        and match.exact_name_match
        and _is_multi_token_person_label(match.attributed_speaker)
        for match in matches
    ):
        return items
    return tuple(
        _with_alias_shadowed_by_exact_name_penalty(
            item,
            max_penalty=max_penalty,
        )
        if match is not None
        and match.alias_only_match
        and _is_multi_token_person_label(match.attributed_speaker)
        else item
        for item, match in zip(items, matches, strict=True)
    )


def _with_alias_shadowed_by_exact_name_penalty(
    item: ContextItem,
    *,
    max_penalty: float,
) -> ContextItem:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    score_signals = safe_score_signals(diagnostics.get("score_signals"))
    existing_penalty = _non_negative_float_signal(
        score_signals.get("deterministic_rerank_penalty")
    )
    available_penalty = max(0.0, max_penalty - existing_penalty)
    penalty = min(available_penalty, _ALIAS_SHADOWED_BY_EXACT_NAME_PENALTY)
    if penalty <= 0:
        return item
    existing_boost = _non_negative_float_signal(
        score_signals.get("deterministic_rerank_boost")
    )
    new_penalty = round(existing_penalty + penalty, 4)
    score_signals.update(
        {
            "deterministic_rerank_boost": round(existing_boost, 4),
            "deterministic_rerank_penalty": new_penalty,
            "deterministic_rerank_net_adjustment": round(existing_boost - new_penalty, 4),
            "speaker_attribution_alias_shadowed_by_exact_name_penalty": round(
                penalty,
                4,
            ),
        }
    )
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    reasons = list(provenance.get("deterministic_rerank_reasons") or ())
    reasons.append("speaker_attribution_alias_shadowed_by_exact_name")
    diagnostics["deterministic_rerank_reason"] = (
        "query-aware deterministic rerank over fused candidates"
    )
    diagnostics["score_signals"] = score_signals
    diagnostics["provenance"] = {
        **provenance,
        "deterministic_rerank_applied": True,
        "deterministic_rerank_reasons": list(dict.fromkeys(reasons))[:8],
    }
    return replace(
        item,
        score=max(0.0, round(item.score - penalty, 4)),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )


def _non_negative_float_signal(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return max(0.0, float(value))
    return 0.0


def _is_multi_token_person_label(label: str) -> bool:
    return len(tuple(token for token in label.split() if token.strip())) > 1
