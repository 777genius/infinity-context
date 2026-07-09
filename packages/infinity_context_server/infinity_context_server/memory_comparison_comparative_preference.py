"""Comparative preference helpers for memory-comparison rerank."""

from __future__ import annotations

import re
from collections.abc import Mapping

from infinity_context_server.memory_comparison_rerank_text import (
    is_preference_query,
    string_sequence,
)


def comparative_option_preference_query(
    question: str,
    profile: Mapping[str, object],
    *,
    current_state_query: bool,
) -> bool:
    """Detect preference questions that choose among named speaker options."""

    if current_state_query or not is_preference_query(profile):
        return False
    if len(string_sequence(profile.get("speaker_surfaces"))) < 2:
        return False
    normalized = re.sub(r"[^0-9a-z]+", " ", str(question or "").casefold()).strip()
    if not normalized:
        return False
    has_choice_surface = bool(re.search(r"\b(?:who|which|whose)\b", normalized))
    has_option_surface = bool(re.search(r"\b(?:or|between|among)\b", normalized))
    has_comparative_surface = bool(
        re.search(
            r"\b(?:more|less|most|least|over|prefer|preferred|favorite|favourite)\b",
            normalized,
        )
    )
    return has_choice_surface and has_option_surface and has_comparative_surface


def without_contrast_requirement(profile: Mapping[str, object]) -> dict[str, object]:
    """Remove old/new contrast requirements from option-choice preference scoring."""

    relation_category_terms = profile.get("relation_category_terms")
    filtered_category_terms = (
        {
            str(category): terms
            for category, terms in relation_category_terms.items()
            if str(category) != "contrast"
        }
        if isinstance(relation_category_terms, Mapping)
        else relation_category_terms
    )
    return {
        **dict(profile),
        "relation_categories": tuple(
            category
            for category in string_sequence(profile.get("relation_categories"))
            if category != "contrast"
        ),
        "relation_category_terms": filtered_category_terms,
        "evidence_need": tuple(
            need
            for need in string_sequence(profile.get("evidence_need"))
            if need != "contrast"
        ),
        "bundle_evidence_roles": tuple(
            role
            for role in string_sequence(profile.get("bundle_evidence_roles"))
            if role != "contrast"
        ),
    }
