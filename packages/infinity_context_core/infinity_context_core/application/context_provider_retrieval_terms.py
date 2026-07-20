"""Pure keyword-term policy for named-provider aggregation retrieval.

Semantic candidate retrieval remains owned by context collectors. This module
only supplies bounded lexical, entity-kind, category, and temporal keyword
groups; none of those groups establishes or merges provider identity.
"""

from __future__ import annotations

from dataclasses import dataclass

_PROVIDER_ENTITY_TERMS = ("app", "platform", "provider", "service", "vendor")
_IMPLICIT_RELATION_TERMS = ("all", "about", "rely", "relying", "relied")
_ACTION_RELATION_ALIASES = {
    "buy": ("order", "ordered", "through", "via"),
    "own": ("rely", "relying", "relied", "through", "via"),
    "try": ("try", "tried", "through", "via"),
    "use": ("use", "used", "using", "through", "via"),
}
_RECENT_TERMS = ("recent", "recently", "lately")
_CURRENT_TERMS = ("current", "currently", "now", "still")
_MAX_TERMS_PER_GROUP = 12


@dataclass(frozen=True)
class ProviderRetrievalTermPolicy:
    """Separated keyword boosts for one named-provider retrieval request."""

    lexical_terms: tuple[str, ...]
    entity_terms: tuple[str, ...]
    category_terms: tuple[str, ...]
    temporal_terms: tuple[str, ...]

    def keyword_groups(self) -> tuple[tuple[str, ...], ...]:
        """Return non-empty groups without combining their ranking signals."""

        return tuple(
            group
            for group in (
                self.lexical_terms,
                self.entity_terms,
                self.category_terms,
                self.temporal_terms,
            )
            if group
        )


def provider_retrieval_term_policy(
    *,
    target_terms: tuple[str, ...],
    action_terms: tuple[str, ...],
    current_only: bool,
    recent: bool,
) -> ProviderRetrievalTermPolicy:
    """Derive generic provider term groups only from the parsed request."""

    normalized_targets = _bounded_unique(target_terms)
    normalized_actions = _bounded_unique(action_terms)
    lexical_terms = _bounded_unique(
        (
            *_IMPLICIT_RELATION_TERMS,
            *(
                alias
                for action in normalized_actions
                for alias in _ACTION_RELATION_ALIASES.get(action, ())
            ),
        )
    )
    category_terms = _bounded_unique(
        tuple(term for term in normalized_targets if term not in _PROVIDER_ENTITY_TERMS)
    )
    temporal_terms = _bounded_unique(
        _CURRENT_TERMS if current_only else (_RECENT_TERMS if recent else ())
    )
    return ProviderRetrievalTermPolicy(
        lexical_terms=lexical_terms,
        entity_terms=_PROVIDER_ENTITY_TERMS,
        category_terms=category_terms,
        temporal_terms=temporal_terms,
    )


def _bounded_unique(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = " ".join(str(raw_value).split()).casefold()
        if not value or value in seen:
            continue
        seen.add(value)
        selected.append(value)
        if len(selected) >= _MAX_TERMS_PER_GROUP:
            break
    return tuple(selected)
