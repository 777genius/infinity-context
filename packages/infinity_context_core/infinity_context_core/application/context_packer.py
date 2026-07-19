"""Prompt-safe context packing facade."""

from __future__ import annotations

from infinity_context_core.application.context_book_author_preference_exact_turns import (
    exact_book_author_preference_turn_candidates,
)
from infinity_context_core.application.context_competition_count_exact_turns import (
    exact_competition_count_turn_candidates,
)
from infinity_context_core.application.context_creative_work_count_exact_turns import (
    exact_creative_work_count_turn_candidates,
)
from infinity_context_core.application.context_diagnostics import (
    context_rank_key,
    normalize_context_item_diagnostics,
)
from infinity_context_core.application.context_english_activity_displacement_answer_support import (
    english_activity_displacement_turn_candidates,
)
from infinity_context_core.application.context_english_lifestyle_inference_answer_support import (
    english_lifestyle_inference_turn_candidates,
)
from infinity_context_core.application.context_food_inventory_exact_turns import (
    exact_food_inventory_turn_candidates,
)
from infinity_context_core.application.context_packer_answer_support import (
    _answer_object_rank,  # noqa: F401 - compatibility re-export
    _answer_support_diversity_candidates,
    _answer_support_diversity_family,
    _answer_support_family_item_key,  # noqa: F401 - compatibility re-export
    _answer_support_family_item_key_for_query,  # noqa: F401 - compatibility re-export
    _answer_support_item_limit,
    _answer_support_query_reason,
    _answer_support_selected_families_sample,
    _answer_support_selected_source_ref_ids_sample,
    _answer_support_source_group_limit,
    _answer_support_source_group_reason_key,
    _answer_support_source_ref_ids_sample,
    _book_reading_answer_content_rank,
    _diversity_candidates,
    _diversity_family,
    _is_activity_participation_answer_reason,
    _is_common_interest_answer_reason,
    _is_exact_animal_evidence_answer_family,
    _is_exact_conversational_support_family,
    _is_exact_precise_content_answer_support_item,
    _is_exact_temporal_query_object_family,
    _is_inventory_list_reason,
    _is_relationship_status_direct_answer_support_item,
    _is_temporal_answer_support_item,
    _ordered_answer_support_families,  # noqa: F401 - compatibility re-export
    _ordered_answer_support_families_for_query,
    _ordered_diversity_families,
    _precise_answer_content_rank,  # noqa: F401 - compatibility re-export
    _precise_turn_answer_support_rank,
)
from infinity_context_core.application.context_packer_answer_support_patterns import (
    _MAX_PRECISE_ANSWER_SUPPORT_DIVERSITY_ITEMS,
    _TEMPORAL_ANSWER_SUPPORT_QUERY_RE,
)
from infinity_context_core.application.context_packer_exact_prepasses import (
    _is_redundant_book_reading_source_group_item,
    _select_exact_activity_competition_turn_items,
    _select_exact_book_reading_turn_items,
    _select_exact_common_interest_turn_items,
    _select_exact_country_destination_turn_items,
    _select_exact_literal_turn_items,
    _select_exact_meteor_feeling_turn_items,
    _select_exact_place_area_state_turn_items,
    _select_exact_precise_content_turn_items,
    _select_exact_query_object_turn_items,
    _select_exact_shared_volunteering_turn_items,
    _select_exact_state_visit_turn_items,
)
from infinity_context_core.application.context_packer_inventory_prepasses import (
    _is_exact_inventory_answer_family,
    _select_exact_cause_inventory_turn_items,
    _select_exact_game_inventory_turn_items,
    _select_exact_pet_acquisition_turn_items,
    _select_gift_joy_source_group_items,
)
from infinity_context_core.application.context_packer_marker_coverage import (
    _select_related_marker_coverage_turn_items,
)
from infinity_context_core.application.context_packer_rendering import (
    CONTEXT_PACKER_HEADER_LINES as _HEADER_LINES,
)
from infinity_context_core.application.context_packer_rendering import (
    citation_labels as _citation_labels,
)
from infinity_context_core.application.context_packer_rendering import (
    citation_quote_preview_count as _citation_quote_preview_count,
)
from infinity_context_core.application.context_packer_rendering import (
    redact_context_item_text as _redact_context_item_text,
)
from infinity_context_core.application.context_packer_rendering import (
    render_context_lines as _render_lines,
)
from infinity_context_core.application.context_packer_rendering import (
    sensitive_citation_quote_skip_count as _sensitive_citation_quote_skip_count,
)
from infinity_context_core.application.context_packer_rendering import (
    sensitive_source_identity_part_count as _sensitive_source_identity_part_count,
)
from infinity_context_core.application.context_packer_rendering import (
    source_group_key as _source_group_key,
)
from infinity_context_core.application.context_packer_rendering import (
    source_key as _source_key,
)
from infinity_context_core.application.context_packer_rendering import (
    unsafe_source_identity_part_count as _unsafe_source_identity_part_count,
)
from infinity_context_core.application.context_packer_selection import (
    PackResult,
    _adds_answer_support_source_coverage,
    _context_render_rank_key,
    _item_type_counts,
    _rendered_char_count,
    _select_item,
    _SelectionState,
    _try_select_item,
    reserve_coverage_items,
)
from infinity_context_core.application.context_packer_source_policy import (
    MAX_ITEMS_PER_SOURCE as _MAX_ITEMS_PER_SOURCE,
)
from infinity_context_core.application.context_packer_source_policy import (
    chunk_source_counts as _chunk_source_counts,
)
from infinity_context_core.application.context_packer_source_policy import (
    selection_key as _selection_key,
)
from infinity_context_core.application.context_packer_source_policy import (
    source_cap_applies as _source_cap_applies,
)
from infinity_context_core.application.context_packer_source_policy import (
    source_capped_source_counts as _source_capped_source_counts,
)
from infinity_context_core.application.context_packer_source_policy import (
    source_diversified_order as _source_diversified_order,
)
from infinity_context_core.application.context_packer_source_policy import (
    source_diversity_reordered_chunk_count as _source_diversity_reordered_chunk_count,
)
from infinity_context_core.application.context_packer_source_policy import (
    source_group_cap as _source_group_cap,
)
from infinity_context_core.application.context_person_activity_exact_turns import (
    exact_person_activity_turn_candidates,
)
from infinity_context_core.application.context_recommendation_exact_turns import (
    exact_recommendation_list_turn_candidates,
)
from infinity_context_core.application.dto import ContextBundle, ContextItem
from infinity_context_core.application.normalize import estimate_tokens

_DEFAULT_MAX_RENDERED_CHARS = 18000


class ContextPacker:
    """Renders memory as evidence, never as instructions."""

    def pack(
        self,
        *,
        bundle_id: str,
        items: tuple[ContextItem, ...],
        token_budget: int,
        query: str = "",
        max_rendered_chars: int = _DEFAULT_MAX_RENDERED_CHARS,
    ) -> PackResult:
        budget = max(64, token_budget)
        char_budget = max(len("\n".join(_HEADER_LINES)), max_rendered_chars)
        normalized_items = tuple(normalize_context_item_diagnostics(item) for item in items)
        ordered_items = sorted(normalized_items, key=context_rank_key)
        selectable_items: list[ContextItem] = []
        dropped_by_instruction_flag = 0
        dropped_by_source_cap = 0
        dropped_by_source_group_cap = 0
        dropped_by_budget = 0
        dropped_by_char_cap = 0
        redacted_item_keys: set[tuple[str, str]] = set()
        for item in ordered_items:
            if item.is_instruction:
                dropped_by_instruction_flag += 1
                continue
            item, item_text_redacted = _redact_context_item_text(item)
            if item_text_redacted:
                redacted_item_keys.add(_selection_key(item))
            selectable_items.append(item)

        state = _SelectionState(
            selected=[],
            selected_keys=set(),
            selected_answer_support_families=set(),
            selected_chunks_by_source={},
            selected_source_capped_items_by_source={},
            selected_art_style_items_by_source_group={},
        )
        coverage_reservation = reserve_coverage_items(
            state,
            items=selectable_items,
            budget=budget,
            char_budget=char_budget,
        )
        coverage_reserved_keys = frozenset(state.selected_keys)
        answer_support_families = _answer_support_diversity_candidates(
            selectable_items, query=query
        )
        ordered_answer_support_families = _ordered_answer_support_families_for_query(
            answer_support_families,
            query=query,
        )
        answer_support_item_limit = _answer_support_item_limit(answer_support_families)
        query_allows_temporal_answer_support = (
            _TEMPORAL_ANSWER_SUPPORT_QUERY_RE.search(query) is not None
        )
        answer_support_items_used = 0
        answer_support_source_group_items_by_reason: dict[str, int] = {}
        for item in exact_competition_count_turn_candidates(
            selectable_items,
            query=query,
            limit=answer_support_item_limit - answer_support_items_used,
        ):
            if _try_select_item(
                state,
                item=item,
                budget=budget,
                char_budget=char_budget,
                ignore_source_cap=True,
            ):
                answer_support_items_used += 1
        for item in exact_creative_work_count_turn_candidates(
            selectable_items,
            query=query,
            limit=answer_support_item_limit - answer_support_items_used,
        ):
            if _try_select_item(
                state,
                item=item,
                budget=budget,
                char_budget=char_budget,
                ignore_source_cap=True,
            ):
                answer_support_items_used += 1
        exact_food_inventory_candidates = exact_food_inventory_turn_candidates(
            selectable_items,
            query=query,
            limit=answer_support_item_limit - answer_support_items_used,
        )
        for item in exact_food_inventory_candidates:
            if _try_select_item(
                state,
                item=item,
                budget=budget,
                char_budget=char_budget,
                ignore_source_cap=True,
            ):
                answer_support_items_used += 1
        for item in exact_person_activity_turn_candidates(
            selectable_items,
            query=query,
            limit=answer_support_item_limit - answer_support_items_used,
        ):
            if _try_select_item(
                state,
                item=item,
                budget=budget,
                char_budget=char_budget,
                ignore_source_cap=True,
            ):
                answer_support_items_used += 1
        for item in english_lifestyle_inference_turn_candidates(
            selectable_items,
            query=query,
            limit=6,
        ):
            if _try_select_item(
                state,
                item=item,
                budget=budget,
                char_budget=char_budget,
                ignore_source_cap=True,
            ):
                answer_support_items_used += 1
        for item in english_activity_displacement_turn_candidates(
            selectable_items,
            query=query,
            limit=answer_support_item_limit - answer_support_items_used,
        ):
            if _try_select_item(
                state,
                item=item,
                budget=budget,
                char_budget=char_budget,
                ignore_source_cap=True,
            ):
                answer_support_items_used += 1
        answer_support_items_used += _select_exact_country_destination_turn_items(
            state,
            items=selectable_items,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )
        answer_support_items_used += _select_exact_literal_turn_items(
            state,
            items=selectable_items,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )
        answer_support_items_used += _select_exact_cause_inventory_turn_items(
            state,
            answer_support_families=answer_support_families,
            query=query,
            budget=budget,
            char_budget=char_budget,
            source_group_items_by_reason=answer_support_source_group_items_by_reason,
        )
        answer_support_items_used += _select_exact_game_inventory_turn_items(
            state,
            items=selectable_items,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )
        answer_support_items_used += _select_exact_pet_acquisition_turn_items(
            state,
            items=selectable_items,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )
        answer_support_items_used += _select_gift_joy_source_group_items(
            state,
            items=selectable_items,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )
        answer_support_items_used += _select_exact_place_area_state_turn_items(
            state,
            items=selectable_items,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )
        answer_support_items_used += _select_exact_common_interest_turn_items(
            state,
            items=selectable_items,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )
        answer_support_items_used += _select_exact_shared_volunteering_turn_items(
            state,
            items=selectable_items,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )
        for item in exact_book_author_preference_turn_candidates(
            selectable_items,
            query=query,
            limit=answer_support_item_limit - answer_support_items_used,
        ):
            if _try_select_item(
                state,
                item=item,
                budget=budget,
                char_budget=char_budget,
                ignore_source_cap=True,
            ):
                answer_support_items_used += 1
        answer_support_items_used += _select_exact_book_reading_turn_items(
            state,
            items=selectable_items,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )
        answer_support_items_used += _select_exact_precise_content_turn_items(
            state,
            items=selectable_items,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )
        answer_support_items_used += _select_exact_activity_competition_turn_items(
            state,
            items=selectable_items,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )
        answer_support_items_used += _select_exact_meteor_feeling_turn_items(
            state,
            items=selectable_items,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )
        answer_support_items_used += _select_exact_state_visit_turn_items(
            state,
            items=selectable_items,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )
        exact_query_object_turn_items_used = _select_exact_query_object_turn_items(
            state,
            items=selectable_items,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )
        for item in exact_recommendation_list_turn_candidates(
            answer_support_families,
            query=query,
            ordered_families=ordered_answer_support_families,
            limit=answer_support_item_limit - answer_support_items_used,
        ):
            if _try_select_item(state, item=item, budget=budget, char_budget=char_budget):
                answer_support_items_used += 1
        for family in ordered_answer_support_families:
            item = answer_support_families[family]
            if not (
                _is_exact_conversational_support_family(family, item=item)
                or _is_exact_inventory_answer_family(item)
                or _is_exact_animal_evidence_answer_family(family, item=item)
                or _is_exact_temporal_query_object_family(
                    family,
                    item=item,
                    query=query,
                )
            ):
                continue
            if _is_redundant_book_reading_source_group_item(state, item):
                continue
            if _try_select_item(
                state,
                item=item,
                budget=budget,
                char_budget=char_budget,
                ignore_source_cap=True,
            ):
                answer_support_items_used += 1
                source_group_reason = _answer_support_source_group_reason_key(family)
                if source_group_reason:
                    answer_support_source_group_items_by_reason[source_group_reason] = (
                        answer_support_source_group_items_by_reason.get(source_group_reason, 0) + 1
                    )
            if answer_support_items_used >= min(6, answer_support_item_limit):
                break
        for family in ordered_answer_support_families:
            item = answer_support_families[family]
            if _selection_key(item) in state.selected_keys:
                continue
            query_reason = _answer_support_query_reason(item)
            if not (
                query_reason
                in {
                    "career_intent_bridge",
                    "career_path_bridge",
                    "book_reading_list_bridge",
                    "children_name_inventory_bridge",
                    "childhood_possession_inventory_bridge",
                    "decomposition_inventory_list",
                    "family_hardship_support_bridge",
                    "music_artist_answer_bridge",
                    "negative_experience_support_bridge",
                    "repeated_test_attempt_bridge",
                    "support_career_motivation_bridge",
                    "support_network_bridge",
                    "support_origin_bridge",
                }
                or _is_inventory_list_reason(query_reason)
                or _is_activity_participation_answer_reason(query_reason)
                or _is_common_interest_answer_reason(query_reason)
                or _is_exact_precise_content_answer_support_item(item)
                or _is_relationship_status_direct_answer_support_item(
                    item,
                    query=query,
                )
                or (
                    query_allows_temporal_answer_support
                    and _is_temporal_answer_support_item(
                        item,
                        query_reason=query_reason,
                    )
                )
            ):
                continue
            if (
                query_reason == "decomposition_inventory_list"
                and _book_reading_answer_content_rank(item.text) > 1
            ):
                continue
            if (
                _precise_turn_answer_support_rank(item, query_reason=query_reason) != 0
                and not _is_exact_precise_content_answer_support_item(item)
                and not _is_relationship_status_direct_answer_support_item(
                    item,
                    query=query,
                )
            ):
                continue
            if _is_redundant_book_reading_source_group_item(state, item):
                continue
            if _try_select_item(
                state,
                item=item,
                budget=budget,
                char_budget=char_budget,
                ignore_source_cap=True,
            ):
                answer_support_items_used += 1
                source_group_reason = _answer_support_source_group_reason_key(family)
                if source_group_reason:
                    answer_support_source_group_items_by_reason[source_group_reason] = (
                        answer_support_source_group_items_by_reason.get(source_group_reason, 0) + 1
                    )
                _select_related_marker_coverage_turn_items(
                    state,
                    answer_support_families=answer_support_families,
                    ordered_answer_support_families=ordered_answer_support_families,
                    query=query,
                    budget=budget,
                    char_budget=char_budget,
                )
            if answer_support_items_used >= min(
                max(_MAX_PRECISE_ANSWER_SUPPORT_DIVERSITY_ITEMS, answer_support_item_limit),
                answer_support_item_limit,
            ):
                break
        answer_support_items_used += _select_related_marker_coverage_turn_items(
            state,
            answer_support_families=answer_support_families,
            ordered_answer_support_families=ordered_answer_support_families,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )

        diversity_items_used = 0
        diversity_families = _diversity_candidates(selectable_items)
        for family in _ordered_diversity_families(diversity_families):
            item = diversity_families[family]
            if _selection_key(item) in coverage_reserved_keys:
                diversity_items_used += 1
                continue
            if _try_select_item(
                state,
                item=item,
                budget=budget,
                char_budget=char_budget,
                mark_answer_support_family=False,
            ):
                diversity_items_used += 1

        for family in ordered_answer_support_families:
            if answer_support_items_used >= answer_support_item_limit:
                break
            item = answer_support_families[family]
            if _selection_key(item) in state.selected_keys:
                continue
            source_group_reason = _answer_support_source_group_reason_key(family)
            if source_group_reason and answer_support_source_group_items_by_reason.get(
                source_group_reason, 0
            ) >= _answer_support_source_group_limit(
                source_group_reason,
                family=family,
                item=item,
            ):
                continue
            if _is_redundant_book_reading_source_group_item(state, item):
                continue
            if _try_select_item(
                state,
                item=item,
                budget=budget,
                char_budget=char_budget,
            ):
                answer_support_items_used += 1
                if source_group_reason:
                    answer_support_source_group_items_by_reason[source_group_reason] = (
                        answer_support_source_group_items_by_reason.get(source_group_reason, 0) + 1
                    )
                _select_related_marker_coverage_turn_items(
                    state,
                    answer_support_families=answer_support_families,
                    ordered_answer_support_families=ordered_answer_support_families,
                    query=query,
                    budget=budget,
                    char_budget=char_budget,
                )

        answer_support_items_used += _select_related_marker_coverage_turn_items(
            state,
            answer_support_families=answer_support_families,
            ordered_answer_support_families=ordered_answer_support_families,
            query=query,
            budget=budget,
            char_budget=char_budget,
        )

        selection_items = _source_diversified_order(selectable_items)
        source_diversity_chunks_reordered = _source_diversity_reordered_chunk_count(
            selectable_items,
            selection_items,
        )
        dropped_by_answer_support_family_duplicate = 0
        for item in selection_items:
            key = _selection_key(item)
            if key in state.selected_keys:
                continue
            answer_support_family = _answer_support_diversity_family(item)
            if (
                answer_support_family
                and answer_support_family in state.selected_answer_support_families
                and not _adds_answer_support_source_coverage(
                    state.selected,
                    item=item,
                    answer_support_family=answer_support_family,
                )
            ):
                dropped_by_answer_support_family_duplicate += 1
                continue
            if _source_cap_applies(item):
                source_key = _source_key(item)
                source_count = state.selected_source_capped_items_by_source.get(source_key, 0)
                if source_count >= _MAX_ITEMS_PER_SOURCE:
                    dropped_by_source_cap += 1
                    continue
                source_group_cap = _source_group_cap(item)
                if source_group_cap is not None:
                    source_group_key = _source_group_key(item)
                    source_group_count = state.selected_art_style_items_by_source_group.get(
                        source_group_key,
                        0,
                    )
                    if source_group_count >= source_group_cap:
                        dropped_by_source_group_cap += 1
                        continue
            item_tokens = estimate_tokens(item.text) + 16
            if state.used_tokens + item_tokens > budget:
                dropped_by_budget += 1
                continue
            if _rendered_char_count((*state.selected, item)) > char_budget:
                dropped_by_char_cap += 1
                continue
            _select_item(state, item=item, item_tokens=item_tokens)

        selected = tuple(sorted(state.selected, key=_context_render_rank_key))
        lines = _render_lines(selected)
        dropped_count = len(normalized_items) - len(selected)
        rendered_text = "\n".join(lines).strip()
        selected_keys = {_selection_key(item) for item in selected}
        return PackResult(
            bundle=ContextBundle(
                bundle_id=bundle_id,
                rendered_text=rendered_text,
                items=selected,
                token_estimate=state.used_tokens,
                diagnostics={
                    "items_considered": len(items),
                    "items_used": len(selected),
                    "coverage_obligations_considered": (
                        coverage_reservation.obligations_considered
                    ),
                    "coverage_eligible_obligation_ids": (
                        coverage_reservation.eligible_obligation_ids
                    ),
                    "coverage_claims_considered": coverage_reservation.claims_considered,
                    "coverage_reservations_selected": (coverage_reservation.reservations_selected),
                    "coverage_selected_obligation_ids": (
                        coverage_reservation.selected_obligation_ids
                    ),
                    "diversity_families_considered": len(diversity_families),
                    "diversity_families_used": len({_diversity_family(item) for item in selected}),
                    "diversity_items_used": diversity_items_used,
                    "answer_support_families_considered": len(answer_support_families),
                    "answer_support_families_used": len(
                        {
                            family
                            for item in selected
                            if (family := _answer_support_diversity_family(item))
                        }
                    ),
                    "answer_support_items_used": answer_support_items_used,
                    "exact_query_object_turn_items_used": (exact_query_object_turn_items_used),
                    "answer_support_candidate_families_sample": (
                        ordered_answer_support_families[:40]
                    ),
                    "answer_support_selected_families_sample": (
                        _answer_support_selected_families_sample(selected)
                    ),
                    "answer_support_candidate_source_ref_ids_sample": (
                        _answer_support_source_ref_ids_sample(
                            ordered_answer_support_families,
                            answer_support_families,
                        )
                    ),
                    "answer_support_selected_source_ref_ids_sample": (
                        _answer_support_selected_source_ref_ids_sample(selected)
                    ),
                    "item_type_counts": _item_type_counts(selected),
                    "chunk_sources_considered": len(_chunk_source_counts(selectable_items)),
                    "chunk_sources_used": len(_chunk_source_counts(selected)),
                    "max_chunks_used_per_source": max(
                        _chunk_source_counts(selected).values(),
                        default=0,
                    ),
                    "source_capped_sources_considered": len(
                        _source_capped_source_counts(selectable_items)
                    ),
                    "source_capped_sources_used": len(_source_capped_source_counts(selected)),
                    "max_source_capped_items_used_per_source": max(
                        _source_capped_source_counts(selected).values(),
                        default=0,
                    ),
                    "source_diversity_chunks_reordered": source_diversity_chunks_reordered,
                    "dropped_by_instruction_flag": dropped_by_instruction_flag,
                    "dropped_by_budget": dropped_by_budget,
                    "dropped_by_source_cap": dropped_by_source_cap,
                    "dropped_by_source_group_cap": dropped_by_source_group_cap,
                    "dropped_by_char_cap": dropped_by_char_cap,
                    "dropped_by_answer_support_family_duplicate": (
                        dropped_by_answer_support_family_duplicate
                    ),
                    "citations_rendered": sum(len(_citation_labels(item)) for item in selected),
                    "citation_quote_previews_rendered": sum(
                        _citation_quote_preview_count(item) for item in selected
                    ),
                    "sensitive_citation_quote_previews_skipped": (
                        sum(_sensitive_citation_quote_skip_count(item) for item in selected)
                    ),
                    "sensitive_source_identity_parts_redacted": (
                        sum(_sensitive_source_identity_part_count(item) for item in selected)
                    ),
                    "unsafe_source_identity_parts_sanitized": (
                        sum(_unsafe_source_identity_part_count(item) for item in selected)
                    ),
                    "sensitive_item_text_redacted": len(selected_keys & redacted_item_keys),
                    "rendered_chars": len(rendered_text),
                    "max_rendered_chars": char_budget,
                },
            ),
            dropped_count=dropped_count,
        )
