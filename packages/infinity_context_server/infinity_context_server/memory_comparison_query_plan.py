"""Typed query planning for memory-comparison retrieval."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

_RELATION_COMPACT_SUPPORT_ROLES = frozenset(
    {
        "action_support",
        "activity_support",
        "age_support",
        "alias_support",
        "commitment_support",
        "contact_support",
        "current_goal_support",
        "date_support",
        "diet_support",
        "education_support",
        "employment_support",
        "favorite_support",
        "health_support",
        "identity_support",
        "pet_support",
        "skill_support",
        "status_support",
        "support_goal_support",
        "vehicle_support",
    }
)


@dataclass(frozen=True)
class QueryPlanCandidate:
    """One candidate query before fanout capping and dedupe."""

    role: str
    query: str
    priority: int
    query_type: str
    reason_codes: tuple[str, ...] = ()

    def normalized_query(self) -> str:
        return " ".join(str(self.query or "").split())

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "role": self.role,
            "priority": self.priority,
            "query_type": self.query_type,
            "query": self.query,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class QueryPlan:
    """Final bounded query plan and diagnostics."""

    selected: tuple[QueryPlanCandidate, ...]
    candidates: tuple[QueryPlanCandidate, ...]
    dropped: tuple[QueryPlanCandidate, ...]
    duplicate_roles: tuple[str, ...]
    dropped_type_limit_roles: tuple[str, ...]
    replaced_type_limit_roles: tuple[str, ...]
    type_limit_replacement_roles: tuple[str, ...]
    recommended_role_families: tuple[str, ...]
    empty_query_candidate_count: int
    max_queries: int
    max_queries_per_type: int

    @property
    def queries(self) -> tuple[str, ...]:
        return tuple(candidate.query for candidate in self.selected)

    @property
    def applied(self) -> bool:
        return len(self.selected) > 1

    def to_diagnostics(self) -> dict[str, object]:
        selected_roles = tuple(candidate.role for candidate in self.selected)
        candidate_roles = tuple(candidate.role for candidate in self.candidates)
        selected_role_families = tuple(
            family for role in selected_roles for family in _role_families(role)
        )
        candidate_role_families = tuple(
            family for role in candidate_roles for family in _role_families(role)
        )
        dropped_role_families = tuple(
            family
            for candidate in self.dropped
            for family in _role_families(candidate.role)
        )
        missing_recommended_families = tuple(
            family
            for family in self.recommended_role_families
            if family not in set(selected_role_families)
        )
        return {
            "schema_version": "query_plan.v2",
            "strategy": "question_only_intent_fanout",
            "max_queries": self.max_queries,
            "max_queries_per_type": self.max_queries_per_type,
            "candidate_count": len(self.candidates),
            "selected_query_count": len(self.selected),
            "dropped_query_count": len(self.dropped),
            "selected_roles": list(selected_roles),
            "dropped_roles": [candidate.role for candidate in self.dropped],
            "recommended_role_families": list(self.recommended_role_families),
            "selected_role_families": list(selected_role_families),
            "missing_recommended_role_families": list(
                missing_recommended_families
            ),
            "duplicate_roles": list(self.duplicate_roles),
            "dropped_type_limit_roles": list(self.dropped_type_limit_roles),
            "replaced_type_limit_roles": list(self.replaced_type_limit_roles),
            "type_limit_replacement_roles": list(
                self.type_limit_replacement_roles
            ),
            "role_counts": dict(Counter(candidate_roles)),
            "role_family_counts": dict(Counter(candidate_role_families)),
            "selected_role_family_counts": dict(Counter(selected_role_families)),
            "dropped_role_family_counts": dict(Counter(dropped_role_families)),
            "candidate_type_counts": dict(
                Counter(candidate.query_type for candidate in self.candidates)
            ),
            "selected_type_counts": dict(
                Counter(candidate.query_type for candidate in self.selected)
            ),
            "uses_ground_truth": False,
            "fanout_integrity": {
                "bounded": True,
                "fanout_limit_hit": bool(self.dropped),
                "type_limit_hit": bool(
                    self.dropped_type_limit_roles
                    or self.replaced_type_limit_roles
                ),
                "empty_query_candidate_count": self.empty_query_candidate_count,
                "selected_query_token_counts": [
                    _query_token_count(candidate) for candidate in self.selected
                ],
                "max_selected_query_token_count": max(
                    (
                        _query_token_count(candidate)
                        for candidate in self.selected
                    ),
                    default=0,
                ),
            },
            "leakage_guard": {
                "input_contract": "question_only_retrieval_intent",
                "answer_terms_allowed": False,
            },
            "selected": [
                candidate.to_diagnostics() for candidate in self.selected
            ],
            "candidates": [
                candidate.to_diagnostics() for candidate in self.candidates
            ],
        }


class QueryPlannerV2:
    """Dedupe and cap question-only query candidates."""

    def __init__(self, *, max_queries: int = 3, max_queries_per_type: int = 2) -> None:
        self._max_queries = max(1, max_queries)
        self._max_queries_per_type = max(1, max_queries_per_type)

    def plan(
        self,
        candidates: Sequence[QueryPlanCandidate],
        *,
        fallback_query: str,
        recommended_role_families: Sequence[str] = (),
    ) -> QueryPlan:
        normalized_seen: set[str] = set()
        deduped: list[QueryPlanCandidate] = []
        duplicate_roles: list[str] = []
        empty_query_candidate_count = 0
        for candidate in sorted(candidates, key=_candidate_sort_key):
            normalized_query = candidate.normalized_query()
            if not normalized_query:
                empty_query_candidate_count += 1
                continue
            if normalized_query in normalized_seen:
                duplicate_roles.append(candidate.role)
                continue
            normalized_seen.add(normalized_query)
            deduped.append(candidate)
        if not deduped and fallback_query:
            deduped.append(
                QueryPlanCandidate(
                    role="fallback_original",
                    query=fallback_query,
                    priority=0,
                    query_type="semantic",
                    reason_codes=("fallback_query",),
                )
            )
        normalized_recommended_role_families = tuple(
            dict.fromkeys(
                family
                for family in recommended_role_families
                if str(family).strip()
            )
        )
        (
            selected,
            dropped,
            dropped_type_limit_roles,
            replaced_type_limit_roles,
            type_limit_replacement_roles,
        ) = self._select_diverse(
            deduped,
            recommended_role_families=normalized_recommended_role_families,
        )
        return QueryPlan(
            selected=selected,
            candidates=tuple(deduped),
            dropped=dropped,
            duplicate_roles=tuple(duplicate_roles),
            dropped_type_limit_roles=dropped_type_limit_roles,
            replaced_type_limit_roles=replaced_type_limit_roles,
            type_limit_replacement_roles=type_limit_replacement_roles,
            recommended_role_families=normalized_recommended_role_families,
            empty_query_candidate_count=empty_query_candidate_count,
            max_queries=self._max_queries,
            max_queries_per_type=self._max_queries_per_type,
        )

    def _select_diverse(
        self,
        deduped: Sequence[QueryPlanCandidate],
        *,
        recommended_role_families: Sequence[str] = (),
    ) -> tuple[
        tuple[QueryPlanCandidate, ...],
        tuple[QueryPlanCandidate, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
    ]:
        enforce_type_limit = len({candidate.query_type for candidate in deduped}) > 1
        selected: list[QueryPlanCandidate] = []
        delayed_type_limit: list[QueryPlanCandidate] = []
        replaced_type_limit_roles: list[str] = []
        type_limit_replacement_roles: list[str] = []
        replaced_ids: set[int] = set()
        type_counts: Counter[str] = Counter()
        selected_ids: set[int] = set()

        for family in _ordered_recommended_role_families(recommended_role_families):
            if len(selected) >= self._max_queries:
                break
            if _selected_has_role_family(selected, family):
                continue
            candidate = _best_candidate_for_role_family(
                deduped,
                family=family,
                selected_ids=selected_ids,
            )
            if candidate is None:
                continue
            if not self._type_slot_available(
                candidate,
                type_counts=type_counts,
                enforce_type_limit=enforce_type_limit,
            ):
                replaced = _replace_weaker_type_slot(
                    selected,
                    selected_ids=selected_ids,
                    candidate=candidate,
                    family=family,
                )
                if replaced is not None:
                    replaced_type_limit_roles.append(replaced.role)
                    type_limit_replacement_roles.append(candidate.role)
                    replaced_ids.add(id(replaced))
                    selected_ids.add(id(candidate))
                    continue
                delayed_type_limit.append(candidate)
                continue
            selected.append(candidate)
            selected_ids.add(id(candidate))
            type_counts[candidate.query_type] += 1

        for candidate in deduped:
            if id(candidate) in selected_ids or id(candidate) in replaced_ids:
                continue
            if len(selected) >= self._max_queries:
                continue
            if not self._type_slot_available(
                candidate,
                type_counts=type_counts,
                enforce_type_limit=enforce_type_limit,
            ):
                delayed_type_limit.append(candidate)
                continue
            selected.append(candidate)
            selected_ids.add(id(candidate))
            type_counts[candidate.query_type] += 1
        selected = sorted(selected, key=_candidate_sort_key)
        dropped = tuple(candidate for candidate in deduped if id(candidate) not in selected_ids)
        dropped_type_limit_roles = tuple(
            candidate.role
            for candidate in delayed_type_limit
            if id(candidate) not in selected_ids
        )
        return (
            tuple(selected),
            dropped,
            dropped_type_limit_roles,
            tuple(replaced_type_limit_roles),
            tuple(type_limit_replacement_roles),
        )

    def _type_slot_available(
        self,
        candidate: QueryPlanCandidate,
        *,
        type_counts: Counter[str],
        enforce_type_limit: bool,
    ) -> bool:
        return (
            not enforce_type_limit
            or type_counts[candidate.query_type] < self._max_queries_per_type
        )


def _candidate_sort_key(candidate: QueryPlanCandidate) -> tuple[int, str]:
    return (candidate.priority, candidate.role)


def _ordered_recommended_role_families(
    recommended_role_families: Sequence[str],
) -> tuple[str, ...]:
    indexed = tuple(enumerate(dict.fromkeys(recommended_role_families)))
    return tuple(
        family
        for _, family in sorted(
            indexed,
            key=lambda pair: (_role_family_selection_priority(pair[1]), pair[0]),
        )
    )


def _role_family_selection_priority(family: str) -> int:
    return {
        "base_query": 0,
        "commonality_support": 1,
        "contrast_support": 1,
        "visual_support": 1,
        "count_support": 2,
        "list_support": 2,
        "value_support": 2,
        "relation_compact": 2,
        "preference_support": 2,
        "causal_support": 2,
        "location_support": 2,
        "temporal_support": 3,
        "multi_hop": 4,
        "expanded_focus": 5,
    }.get(family, 5)


def _replace_weaker_type_slot(
    selected: list[QueryPlanCandidate],
    *,
    selected_ids: set[int],
    candidate: QueryPlanCandidate,
    family: str,
) -> QueryPlanCandidate | None:
    replacement_priority = _role_family_replacement_priority(family)
    replacement_index = next(
        (
            index
            for index, selected_candidate in enumerate(selected)
            if selected_candidate.query_type == candidate.query_type
            and _candidate_replacement_priority(selected_candidate)
            > replacement_priority
        ),
        None,
    )
    if replacement_index is None:
        return None
    replaced = selected[replacement_index]
    selected[replacement_index] = candidate
    selected_ids.discard(id(replaced))
    return replaced


def _candidate_replacement_priority(candidate: QueryPlanCandidate) -> int:
    return min(
        (_role_family_replacement_priority(family) for family in _role_families(candidate.role)),
        default=5,
    )


def _role_family_replacement_priority(family: str) -> int:
    if family == "base_query":
        return 0
    if family == "location_support":
        return 1
    if family in {"count_support", "list_support", "value_support"}:
        return 2
    if family == "relation_compact":
        return 2
    if family in {"preference_support", "causal_support"}:
        return 2
    if family == "expanded_focus":
        return 3
    return 4


def _selected_has_role_family(
    selected: Sequence[QueryPlanCandidate],
    family: str,
) -> bool:
    return any(family in _role_families(candidate.role) for candidate in selected)


def _best_candidate_for_role_family(
    candidates: Sequence[QueryPlanCandidate],
    *,
    family: str,
    selected_ids: set[int],
) -> QueryPlanCandidate | None:
    return next(
        (
            candidate
            for candidate in candidates
            if id(candidate) not in selected_ids
            and family in _role_families(candidate.role)
        ),
        None,
    )


def _role_families(role: str) -> tuple[str, ...]:
    if role in {"original_question", "fallback_original"}:
        return ("base_query",)
    if role == "commonality_support":
        return ("commonality_support",)
    if role == "expanded_focus":
        return ("expanded_focus",)
    if role == "compact_relation":
        return ("relation_compact",)
    if role == "causal_support":
        return ("relation_compact", "causal_support")
    if role in {"favorite_support", "preference_support"}:
        return ("relation_compact", "preference_support")
    if role in {
        "communication_support",
        "emotion_response_support",
        "event_support",
        "exchange_support",
        "inference_support",
        "symbolic_meaning_support",
    }:
        return ("relation_compact",)
    if role in _RELATION_COMPACT_SUPPORT_ROLES:
        return ("relation_compact",)
    if role == "location_support":
        return ("relation_compact", "location_support")
    if role == "count_support":
        return ("count_support",)
    if role == "list_support":
        return ("list_support",)
    if role == "value_support":
        return ("value_support",)
    if role == "visual_temporal_support":
        return ("visual_support", "temporal_support")
    if role == "visual_support":
        return ("visual_support",)
    if role in {
        "temporal_support",
        "duration_temporal_support",
        "explicit_temporal_support",
        "relative_temporal_support",
        "temporal_sequence_support",
    }:
        return ("temporal_support",)
    if role == "contrast_support":
        return ("contrast_support",)
    if role.startswith("multi_hop"):
        return ("multi_hop",)
    return (role or "unknown",)


def _query_token_count(candidate: QueryPlanCandidate) -> int:
    return len(candidate.normalized_query().split())
