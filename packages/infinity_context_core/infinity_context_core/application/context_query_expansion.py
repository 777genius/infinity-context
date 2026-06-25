"""Deterministic query decomposition for evidence-oriented retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.application.context_query_decomposition import (
    QueryDecompositionPlan,
    build_query_decomposition_plan,
)
from infinity_context_core.application.context_query_expansion_rules import (
    EXPANSION_RULES as _EXPANSION_RULES,
)
from infinity_context_core.application.context_query_expansion_rules import (
    MAX_QUERY_EXPANSIONS as _MAX_QUERY_EXPANSIONS,
)
from infinity_context_core.application.context_query_expansion_selection import (
    identity_terms_for_expansion as _identity_terms_for_expansion,
)
from infinity_context_core.application.context_query_expansion_selection import (
    query_expansion_variant_set as _query_variant_set,
)
from infinity_context_core.application.context_query_expansion_selection import (
    should_skip_expansion_rule as _should_skip_expansion_rule,
)
from infinity_context_core.application.context_query_identity_terms import (
    capitalized_identity_terms as _capitalized_identity_terms,
)
from infinity_context_core.application.context_query_identity_terms import (
    raw_query_tokens as _raw_query_tokens,
)
from infinity_context_core.application.context_query_identity_terms import (
    with_identity_terms as _with_identity_terms,
)
from infinity_context_core.application.context_query_personal_fact_expansions import (
    personal_fact_query_variants,
)
from infinity_context_core.application.context_query_project_summary_expansions import (
    project_summary_query_variants,
)
from infinity_context_core.application.context_query_state_transition import (
    state_transition_query_variants,
)
from infinity_context_core.application.context_query_support_role import (
    support_role_query_variants,
)
from infinity_context_core.application.context_query_workflow_intent import (
    gotcha_failure_query_variants,
    workflow_commitment_query_variants,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    QUERY_REASON_PRIORITY as _QUERY_REASON_PRIORITY,
)


@dataclass(frozen=True)
class QueryExpansion:
    query: str
    reason: str


@dataclass(frozen=True)
class QueryExpansionPlan:
    original_query: str
    expansions: tuple[QueryExpansion, ...]
    decompositions: tuple[QueryExpansion, ...] = ()

    @property
    def retrieval_queries(self) -> tuple[QueryExpansion, ...]:
        return (
            QueryExpansion(query=self.original_query, reason="original_query"),
            *self.decompositions,
            *self.expansions,
        )

    def diagnostics(self) -> dict[str, object]:
        return {
            "query_expansion_status": "available" if self.expansions else "empty",
            "query_expansion_count": len(self.expansions),
            "query_expansion_reasons": [item.reason for item in self.expansions],
            "query_decomposition_status": ("available" if self.decompositions else "empty"),
            "query_decomposition_count": len(self.decompositions),
            "query_decomposition_reasons": [item.reason for item in self.decompositions],
        }


def build_query_expansion_plan(
    query: str,
    *,
    decomposition_plan: QueryDecompositionPlan | None = None,
) -> QueryExpansionPlan:
    decomposition_plan = decomposition_plan or build_query_decomposition_plan(query)
    query_term_variants = set(_query_variant_set(query))
    query_term_variants.update(gotcha_failure_query_variants(query))
    query_term_variants.update(state_transition_query_variants(query))
    query_term_variants.update(support_role_query_variants(query))
    query_term_variants.update(workflow_commitment_query_variants(query))
    query_term_variants.update(personal_fact_query_variants(query))
    query_term_variants.update(project_summary_query_variants(query))
    raw_tokens = set(_raw_query_tokens(query))
    identity_terms = _capitalized_identity_terms(query)
    expansion_candidates: list[tuple[int, int, QueryExpansion]] = []
    seen_queries = {query.strip().casefold()}
    for rule_index, (required_terms, expansion, reason) in enumerate(_EXPANSION_RULES):
        if _should_skip_expansion_rule(reason, query=query, raw_tokens=raw_tokens):
            continue
        if not required_terms.issubset(query_term_variants):
            continue
        expanded_query = _with_identity_terms(
            _identity_terms_for_expansion(
                reason=reason,
                query=query,
                identity_terms=identity_terms,
            ),
            expansion,
        )
        normalized_expanded_query = expanded_query.casefold()
        if normalized_expanded_query in seen_queries:
            continue
        expansion_candidates.append(
            (
                rule_index,
                len(required_terms),
                QueryExpansion(query=expanded_query, reason=reason),
            )
        )

    expansions: list[QueryExpansion] = []
    selected_queries = set(seen_queries)
    selected_reasons: set[str] = set()
    for _, _, expansion in sorted(
        expansion_candidates,
        key=_expansion_candidate_selection_key,
    ):
        normalized_expanded_query = expansion.query.casefold()
        if expansion.reason in selected_reasons or normalized_expanded_query in selected_queries:
            continue
        expansions.append(expansion)
        selected_queries.add(normalized_expanded_query)
        selected_reasons.add(expansion.reason)
        if len(expansions) >= _MAX_QUERY_EXPANSIONS:
            break
    return QueryExpansionPlan(
        original_query=query,
        expansions=tuple(expansions),
        decompositions=tuple(
            QueryExpansion(query=item.query, reason=item.reason)
            for item in decomposition_plan.decompositions
        ),
    )


def _expansion_candidate_selection_key(
    item: tuple[int, int, QueryExpansion],
) -> tuple[int, int, int]:
    rule_index, specificity, expansion = item
    return (
        -_QUERY_REASON_PRIORITY.get(expansion.reason, 0),
        -specificity,
        rule_index,
    )
