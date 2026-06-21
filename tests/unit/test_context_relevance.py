from infinity_context_core.application.context_lexical import query_terms
from infinity_context_core.application.context_relevance import (
    has_project_identity_mismatch,
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


def test_query_terms_drop_question_stopwords_before_retrieval() -> None:
    terms = query_terms("What fields would Caroline likely pursue in her educaton?")

    assert tuple(term.raw for term in terms) == (
        "fields",
        "caroline",
        "pursue",
        "educaton",
    )


def test_query_relevance_expands_personal_identity_terms() -> None:
    relevance = score_query_relevance(
        query="What is Caroline's identity?",
        text="D1:5 Caroline: The transgender stories were inspiring.",
    )

    assert relevance.unique_term_hits == 2
    assert relevance.distinctive_term_hits == 2
    assert is_query_relevance_sufficient(relevance) is True


def test_query_relevance_expands_relationship_context_terms() -> None:
    relevance = score_query_relevance(
        query="What is Caroline's relationship status?",
        text=(
            "D2:14 Caroline: She is excited to adopt as a single parent after a "
            "tough breakup."
        ),
    )

    assert relevance.unique_term_hits >= 2
    assert relevance.distinctive_term_hits >= 2
    assert is_query_relevance_sufficient(relevance) is True


def test_query_relevance_expands_activity_category_intent() -> None:
    relevance = score_query_relevance(
        query="What activities has Melanie done with her family?",
        text="D8:4 Melanie: The kids made pottery pieces from clay.",
    )

    assert relevance.unique_term_hits >= 3
    assert relevance.distinctive_term_hits >= 3
    assert is_query_relevance_sufficient(relevance) is True


def test_query_relevance_expands_lgbtq_participation_intent() -> None:
    relevance = score_query_relevance(
        query="What LGBTQ events did Caroline participate in?",
        text="D8:17 Caroline: A special memory was the pride parade march.",
    )

    assert relevance.unique_term_hits >= 3
    assert relevance.distinctive_term_hits >= 3
    assert is_query_relevance_sufficient(relevance) is True


def test_query_relevance_expands_preference_intent() -> None:
    relevance = score_query_relevance(
        query="What do Melanie's kids like?",
        text="D6:6 Melanie: They love learning about animals and dinosaur bones.",
    )

    assert relevance.unique_term_hits >= 2
    assert relevance.distinctive_term_hits >= 2
    assert is_query_relevance_sufficient(relevance) is True


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


def test_query_relevance_matches_safe_underscore_identifier_prefix() -> None:
    relevance = score_query_relevance(
        query="CANONICAL_ONLY",
        text="CANONICAL_ONLY_CHUNK_MARKER comes only from keyword chunks.",
    )

    assert relevance.query_term_count == 1
    assert relevance.unique_term_hits == 1
    assert relevance.hit_ratio == 1.0
    assert is_query_relevance_sufficient(relevance) is True


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


def test_project_identity_mismatch_detects_shared_generic_terms() -> None:
    assert has_project_identity_mismatch(
        query="Alex Project Apollo billing one hour ago",
        text="Alex discussed Project Atlas billing one hour ago.",
    )
    assert has_project_identity_mismatch(
        query="Алексом проект Аполло billing час назад",
        text="Алекс обсуждал проект Атлас billing час назад.",
    )
    assert not has_project_identity_mismatch(
        query="Alex Project Atlas billing one hour ago",
        text="Alex discussed Project Atlas billing one hour ago.",
    )
    assert not has_project_identity_mismatch(
        query="Alex billing one hour ago",
        text="Alex discussed Project Atlas billing one hour ago.",
    )


def test_project_identity_mismatch_ignores_descriptive_project_memory_phrases() -> None:
    assert not has_project_identity_mismatch(
        query="shared project memory coding agents dev teams Codex Claude Cursor Slack",
        text=(
            "Long memory benchmark project notes LONGMEM_DOC_PROJECT_SCOPE: "
            "Infinity Context is shared project memory for coding agents and dev teams."
        ),
    )


def test_query_relevance_ignores_generic_retrieval_plumbing_terms() -> None:
    relevance = score_query_relevance(
        query="SHARDED_INDEX tenant scoped retrieval citations chunk recall",
        text=(
            "Billing dashboard copy should mention invoices and seats. "
            "Retrieval hints: title: irrelevant; node kind: section_chunk"
        ),
    )
    target = score_query_relevance(
        query="SHARDED_INDEX tenant scoped retrieval citations chunk recall",
        text="SHARDED_INDEX memory design requires tenant scoped retrieval and citations.",
    )

    assert relevance.unique_term_hits > 0
    assert relevance.distinctive_term_hits == 0
    assert is_query_relevance_sufficient(relevance) is False
    assert target.distinctive_term_hits >= 2
    assert is_query_relevance_sufficient(target) is True


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
