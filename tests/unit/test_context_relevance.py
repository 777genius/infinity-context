from infinity_context_core.application.context_relevance import (
    is_query_relevance_sufficient,
    score_query_relevance,
)


def test_query_relevance_matches_russian_case_variants() -> None:
    relevance = score_query_relevance(
        query="обсудили встречу с Алексом по проекту Атлас",
        text="Встреча: Алекс согласовал проект Атлас. Следующий звонок завтра.",
    )

    assert relevance.query_term_count == 5
    assert relevance.unique_term_hits >= 4
    assert relevance.hit_ratio >= 0.8
    assert relevance.score_boost > 0.08


def test_query_relevance_matches_english_plural_and_progressive_forms() -> None:
    relevance = score_query_relevance(
        query="renewal meetings approved",
        text="The renewal meeting approval was saved after Alex approved the plan.",
    )

    assert relevance.unique_term_hits == 3
    assert relevance.capped_frequency_hits >= 3
    assert relevance.score_boost == 0.12


def test_query_relevance_matches_underscore_metadata_parts() -> None:
    relevance = score_query_relevance(
        query="api key rotation",
        text="provider_metadata: api_key_rotation_required",
    )

    assert relevance.unique_term_hits == 3
    assert relevance.hit_ratio == 1.0


def test_query_relevance_requires_exact_identifier_token_for_underscore_query() -> None:
    relevance = score_query_relevance(
        query="CONTEXT_SUPERSEDED_SECRET_MARKER",
        text="CONTEXT_SUPERSEDED_REVIEW_MARKER: legacy project Alpha used the old endpoint.",
    )

    assert relevance.query_term_count == 1
    assert relevance.unique_term_hits == 0
    assert relevance.hit_ratio == 0.0


def test_query_relevance_avoids_unrelated_project_match() -> None:
    relevance = score_query_relevance(
        query="project atlas",
        text="Project Apollo has a launch review tomorrow.",
    )

    assert relevance.query_term_count == 2
    assert relevance.unique_term_hits == 1
    assert relevance.hit_ratio == 0.5
    assert relevance.distinctive_term_count == 1
    assert relevance.distinctive_term_hits == 0
    assert is_query_relevance_sufficient(relevance) is False


def test_query_relevance_policy_keeps_entity_partial_match() -> None:
    relevance = score_query_relevance(
        query="Alex meeting",
        text="person: Alex",
    )

    assert relevance.query_term_count == 2
    assert relevance.unique_term_hits == 1
    assert relevance.distinctive_term_count == 1
    assert relevance.distinctive_term_hits == 1
    assert is_query_relevance_sufficient(relevance) is True


def test_query_relevance_phrase_signal_beats_loose_decoy_terms() -> None:
    query = "primary runtime temporal fact engine Graphiti Obsidian 3D graph"
    target = score_query_relevance(
        query=query,
        text="LONGMEM_DECISION_GRAPHITI: Graphiti remains the temporal fact engine.",
        max_boost=0.03,
    )
    decoy = score_query_relevance(
        query=query,
        text="LONGMEM_DECOY_OBSIDIAN: Obsidian 3D graph is the primary runtime engine.",
        max_boost=0.03,
    )

    assert target.unique_term_hits < decoy.unique_term_hits
    assert target.phrase_bigram_hits > decoy.phrase_bigram_hits
    assert target.score_boost > decoy.score_boost
