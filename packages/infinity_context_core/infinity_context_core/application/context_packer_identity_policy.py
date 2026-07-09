"""Identity and key-building policy for context packing."""

from __future__ import annotations

import infinity_context_core.application.context_packer_diagnostics as _diagnostics
import infinity_context_core.application.context_packer_rendering as _rendering
from infinity_context_core.application.context_diagnostics import diagnostic_retrieval_sources
from infinity_context_core.application.dto import ContextItem


def answer_support_query_reason(item: ContextItem) -> str:
    query_reason = _diagnostics.diagnostic_signal_text(item, "query_expansion_reason")
    deterministic_reason = _diagnostics.diagnostic_signal_text(
        item,
        "deterministic_rerank_query_reason",
    )
    if (
        deterministic_reason
        and deterministic_reason != "original_query"
        and query_reason
        in {
            "decomposition_evidence_reason",
            "decomposition_inference_support",
        }
    ):
        return deterministic_reason
    return (
        query_reason
        or _diagnostics.diagnostic_signal_text(item, "bm25_lexical_query_reason")
        or deterministic_reason
    )


def answer_support_source_group(item: ContextItem) -> str:
    aggregation_source_group = _diagnostics.diagnostic_text(
        item,
        "keyword_aggregation_source_group",
    )
    if aggregation_source_group:
        return aggregation_source_group
    if set(diagnostic_retrieval_sources(item.diagnostics)).intersection(
        {
            "keyword_aggregation_chunks",
            "keyword_source_sibling_chunks",
        }
    ):
        return _rendering.source_group_key(item)
    if has_derived_source_group_ref(item):
        return _rendering.source_group_key(item)
    return ""


def has_derived_source_group_ref(item: ContextItem) -> bool:
    if not item.source_refs:
        return False
    source_group_key = _rendering.source_group_key(item)
    return source_group_key != _rendering.source_key(item)


def has_primary_exact_turn_source_ref(item: ContextItem) -> bool:
    if not item.source_refs:
        return False
    return is_exact_turn_source_id(item.source_refs[0].source_id)


def has_any_exact_turn_source_ref(item: ContextItem) -> bool:
    return bool(primary_exact_turn_source_id(item))


def primary_exact_turn_source_id(item: ContextItem) -> str:
    for ref in item.source_refs:
        source_id = ref.source_id or ""
        if is_exact_turn_source_id(source_id):
            return source_id
    return ""


def is_exact_turn_source_id(source_id: str | None) -> bool:
    parts = (source_id or "").split(":")
    return len(parts) >= 6 and parts[-1] == "turn" and parts[-3].startswith("D")


def diversity_family_base(family: str) -> str:
    return family.split(":", 1)[0]


def typed_diversity_family(base: str, suffix: str) -> str:
    safe_suffix = safe_diversity_suffix(suffix)
    return f"{base}:{safe_suffix}" if safe_suffix else base


def compound_diversity_family(base: str, *suffixes: str) -> str:
    safe_suffixes = tuple(
        safe_suffix
        for suffix in suffixes
        if (safe_suffix := safe_diversity_suffix(suffix))
    )
    return ":".join((base, *safe_suffixes)) if safe_suffixes else base


def numeric_signal(value: object) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def safe_diversity_suffix(value: str) -> str:
    text = value.strip().casefold()
    if not text or "redacted" in text:
        return ""
    chars: list[str] = []
    previous_dash = False
    for char in text[:160]:
        if char.isalnum():
            chars.append(char)
            previous_dash = False
        elif not previous_dash:
            chars.append("-")
            previous_dash = True
    token = "".join(chars).strip("-")
    if len(token) <= 64:
        return token
    return f"{token[:24]}-{token[-39:]}".strip("-")[:64]


def source_ref_modality_hint(item: ContextItem) -> str:
    refs = item.source_refs
    if any(ref.time_start_ms is not None or ref.time_end_ms is not None for ref in refs):
        return "time_range"
    if any(ref.bbox is not None for ref in refs):
        return "image"
    if any(ref.page_number is not None for ref in refs):
        return "document"
    return ""


def artifact_diversity_hint(item: ContextItem) -> str:
    modality = _diagnostics.diagnostic_text(
        item,
        "evidence_modality",
    ) or source_ref_modality_hint(item)
    kind = _diagnostics.diagnostic_text(item, "evidence_kind")
    if modality and kind:
        return f"{modality}-{kind}"
    return modality or kind


def item_type_counts(items: tuple[ContextItem, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.item_type] = counts.get(item.item_type, 0) + 1
    return counts
