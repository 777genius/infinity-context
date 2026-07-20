import infinity_context_core.application.context_relevance as context_relevance_module
from infinity_context_core.application.context_lexical import (
    query_terms,
    text_variant_counts,
    text_variant_profile,
    text_variant_sequence,
    text_variant_stats,
)
from infinity_context_core.application.context_relevance import (
    has_project_identity_mismatch,
    is_chunk_candidate_relevance_sufficient,
    is_fact_candidate_relevance_sufficient,
    is_query_relevance_specific_enough,
    is_query_relevance_sufficient,
    score_query_relevance,
    score_query_relevance_against_profile,
    score_query_terms_relevance_against_profile,
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


def test_text_variant_stats_matches_legacy_count_and_sequence_semantics() -> None:
    text = "Atlas_launch moved on 2026-08-15. Алекс обсуждал Atlas launch."

    profile_counts, sequence = text_variant_profile(text)
    counts, sequence_length = text_variant_stats(text)

    assert profile_counts == counts
    assert sequence == text_variant_sequence(text)
    assert counts == text_variant_counts(text)
    assert sequence_length == len(sequence)
    assert counts["atlas"] >= 2
    assert counts["date_2026_08_15"] == 1


def test_score_query_relevance_uses_single_text_variant_profile(monkeypatch) -> None:
    real_text_variant_profile = context_relevance_module.text_variant_profile
    calls: list[str] = []

    def counting_text_variant_profile(text: str, *, min_chars: int = 2):
        calls.append(text)
        return real_text_variant_profile(text, min_chars=min_chars)

    monkeypatch.setattr(
        context_relevance_module,
        "text_variant_profile",
        counting_text_variant_profile,
    )

    relevance = score_query_relevance(
        query="Alex Atlas launch",
        text="Alex moved the Atlas launch deadline after the call.",
    )

    assert calls == ["Alex moved the Atlas launch deadline after the call."]
    assert relevance.unique_term_hits == 3
    assert relevance.phrase_bigram_hits == 1


def test_profile_aware_query_relevance_matches_public_scoring() -> None:
    query = "Alex Atlas launch"
    text = "Alex moved the Atlas launch deadline after the call."
    counts, variants = text_variant_profile(text)

    assert score_query_relevance_against_profile(
        query=query,
        text_counts=counts,
        text_variants=variants,
    ) == score_query_relevance(query=query, text=text)


def test_terms_aware_query_relevance_matches_public_scoring() -> None:
    query = "Alex Atlas launch"
    text = "Alex moved the Atlas launch deadline after the call."
    counts, variants = text_variant_profile(text)

    assert score_query_terms_relevance_against_profile(
        terms=query_terms(query),
        text_counts=counts,
        text_variants=variants,
    ) == score_query_relevance(query=query, text=text)


def test_query_relevance_matches_cross_language_relative_event_terms() -> None:
    russian_query = "Что Алекс сказал час назад по проекту Атлас?"
    english_text = "Alex said one hour ago that Project Atlas billing was approved."
    english_query = "What did Alex say one hour ago about Project Atlas?"
    russian_text = "Алекс сказал час назад, что проект Атлас согласован."
    variants_by_raw = {term.raw: set(term.variants) for term in query_terms(russian_query)}

    assert {"said", "told", "mentioned"}.issubset(variants_by_raw["сказал"])
    assert "hour" in variants_by_raw["час"]
    assert "ago" in variants_by_raw["назад"]
    assert "project" in variants_by_raw["проекту"]

    russian_to_english = score_query_relevance(
        query=russian_query,
        text=english_text,
    )
    english_to_russian = score_query_relevance(
        query=english_query,
        text=russian_text,
    )

    assert russian_to_english.unique_term_hits >= 6
    assert russian_to_english.hit_ratio >= 0.8
    assert english_to_russian.unique_term_hits >= 6
    assert english_to_russian.hit_ratio >= 0.8


def test_query_relevance_matches_english_plural_and_progressive_forms() -> None:
    relevance = score_query_relevance(
        query="renewal meetings approved",
        text="The renewal meeting approval was saved after Alex approved the plan.",
    )

    assert relevance.unique_term_hits == 3
    assert relevance.capped_frequency_hits >= 3
    assert relevance.score_boost == 0.12


def test_query_terms_include_cyrillic_name_case_variants() -> None:
    variants_by_raw = {
        term.raw: set(term.variants)
        for term in query_terms("Что Мария обсуждала с Сергеем и Даной?")
    }
    relevance = score_query_relevance(
        query="Что Мария обсуждала с Сергеем?",
        text="Мария и Сергей обсуждали проект Атлас.",
    )
    cross_script_relevance = score_query_relevance(
        query="Что Мария обсуждала с Сергеем?",
        text="Maria and Sergey discussed Project Atlas.",
    )

    assert "сергей" in variants_by_raw["сергеем"]
    assert "sergey" in variants_by_raw["сергеем"]
    assert "дана" in variants_by_raw["даной"]
    assert "dana" in variants_by_raw["даной"]
    assert relevance.unique_term_hits >= 3
    assert cross_script_relevance.unique_term_hits >= 3


def test_query_terms_include_russian_mention_and_write_aliases() -> None:
    variants_by_raw = {
        term.raw: set(term.variants) for term in query_terms("Что Мария упоминала и писала Сергею?")
    }
    mention_relevance = score_query_relevance(
        query="Что Мария упоминала про Atlas?",
        text="Maria mentioned Project Atlas in the chat.",
    )
    wrote_relevance = score_query_relevance(
        query="Что Мария писала Сергею?",
        text="Maria wrote Sergey about Project Atlas.",
    )

    assert "mentioned" in variants_by_raw["упоминала"]
    assert "wrote" in variants_by_raw["писала"]
    assert mention_relevance.unique_term_hits >= 2
    assert wrote_relevance.unique_term_hits >= 3


def test_query_terms_drop_question_stopwords_before_retrieval() -> None:
    terms = query_terms("What fields would Caroline likely pursue in her educaton?")

    assert tuple(term.raw for term in terms) == (
        "fields",
        "caroline",
        "pursue",
        "educaton",
    )


def test_query_terms_drop_command_stopwords_before_retrieval() -> None:
    terms = query_terms("Пожалуйста найди вложение с документом по Project Atlas")
    variants_by_raw = {term.raw: set(term.variants) for term in terms}

    assert "пожалуйста" not in variants_by_raw
    assert "найди" not in variants_by_raw
    assert {"attachment", "file", "document", "artifact"}.issubset(variants_by_raw["вложение"])
    assert "document" in variants_by_raw["документом"]
    assert "project" in variants_by_raw["project"]


def test_query_relevance_normalizes_absolute_date_tokens() -> None:
    terms = query_terms("When is the Atlas deadline on 2026-08-15?")
    variants_by_raw = {term.raw: set(term.variants) for term in terms}

    correct = score_query_relevance(
        query="Atlas launch deadline 2026-08-15",
        text="Meeting notes: Atlas launch deadline is 2026-08-15.",
    )
    wrong_date = score_query_relevance(
        query="Atlas launch deadline 2026-08-15",
        text="Meeting notes: Atlas launch deadline is 2026-09-15.",
    )
    local_format = score_query_relevance(
        query="Atlas launch deadline 2026-08-15",
        text="Meeting notes: Atlas launch deadline is 15.08.2026.",
    )

    assert "date_2026_08_15" in variants_by_raw
    assert correct.unique_term_hits > wrong_date.unique_term_hits
    assert local_format.unique_term_hits == correct.unique_term_hits


def test_query_relevance_expands_personal_identity_terms() -> None:
    relevance = score_query_relevance(
        query="What is Caroline's identity?",
        text="D1:5 Caroline: The transgender stories were inspiring.",
    )

    assert relevance.unique_term_hits == 2
    assert relevance.distinctive_term_hits == 2
    assert is_query_relevance_sufficient(relevance) is True


def test_query_relevance_specific_enough_rejects_identity_only_match() -> None:
    query = "What kind of art does Caroline make?"
    identity_only = "D12:1 Caroline: A hiking comment upset her."
    art_evidence = "D11:8 Caroline: Inclusivity and diversity in my art is important."

    identity_relevance = score_query_relevance(query=query, text=identity_only)
    art_relevance = score_query_relevance(query=query, text=art_evidence)

    assert is_query_relevance_sufficient(identity_relevance) is True
    assert (
        is_query_relevance_specific_enough(
            query=query,
            text=identity_only,
            relevance=identity_relevance,
        )
        is False
    )
    assert (
        is_query_relevance_specific_enough(
            query=query,
            text=art_evidence,
            relevance=art_relevance,
        )
        is True
    )


def test_query_relevance_specific_enough_rejects_lowercase_identity_only_match() -> None:
    query = "what kind of art does caroline make?"
    identity_only = "D12:1 Caroline: A hiking comment upset her."
    art_evidence = "D11:8 Caroline: Inclusivity and diversity in my art is important."

    identity_relevance = score_query_relevance(query=query, text=identity_only)
    art_relevance = score_query_relevance(query=query, text=art_evidence)

    assert (
        is_query_relevance_specific_enough(
            query=query,
            text=identity_only,
            relevance=identity_relevance,
        )
        is False
    )
    assert (
        is_query_relevance_specific_enough(
            query=query,
            text=art_evidence,
            relevance=art_relevance,
        )
        is True
    )


def test_chunk_candidate_relevance_accepts_exact_technical_marker_match() -> None:
    query = "Что сказано про V1_DOCUMENT_SCOPE_MARKER?"
    text = "V1_DOCUMENT_SCOPE_MARKER: импорт документа должен читаться из thread context."

    relevance = score_query_relevance(query=query, text=text)

    assert relevance.distinctive_term_hits == 1
    assert (
        is_chunk_candidate_relevance_sufficient(
            query=query,
            text=text,
            relevance=relevance,
        )
        is True
    )


def test_chunk_candidate_relevance_rejects_single_hit_long_no_candidate_query() -> None:
    query = "unrelated yakutsk cooking recipe quantum aquarium warranty"
    text = "Warranty renewal paperwork was archived for Project Atlas."

    relevance = score_query_relevance(query=query, text=text)

    assert is_query_relevance_sufficient(relevance) is True
    assert relevance.distinctive_term_hits == 1
    assert (
        is_chunk_candidate_relevance_sufficient(
            query=query,
            text=text,
            relevance=relevance,
        )
        is False
    )


def test_chunk_candidate_relevance_keeps_multi_hit_long_query_evidence() -> None:
    query = "full provider canary MCP smoke agent install doctor memory gates"
    text = "Provider canary MCP smoke verified agent install doctor memory gates."

    relevance = score_query_relevance(query=query, text=text)

    assert relevance.distinctive_term_hits >= 2
    assert (
        is_chunk_candidate_relevance_sufficient(
            query=query,
            text=text,
            relevance=relevance,
        )
        is True
    )


def test_chunk_candidate_relevance_keeps_marriage_duration_evidence() -> None:
    query = "Mel married husband wife spouse wedding anniversary years already time flies dress"
    text = (
        "D3:16 Melanie: 5 years already! Time flies - feels like just yesterday "
        "I put this dress on. image caption: a bride in a wedding dress."
    )

    relevance = score_query_relevance(query=query, text=text)

    assert relevance.distinctive_term_hits >= 4
    assert (
        is_chunk_candidate_relevance_sufficient(
            query=query,
            text=text,
            relevance=relevance,
        )
        is True
    )


def test_chunk_candidate_relevance_rejects_generic_family_duration_decoy() -> None:
    query = "Mel married husband wife spouse wedding anniversary years already time flies dress"
    text = (
        "D10:12 Melanie: Every year we go to the beach with my family and make "
        "summer memories with the kids."
    )

    relevance = score_query_relevance(query=query, text=text)

    assert relevance.distinctive_term_hits >= 1
    assert (
        is_chunk_candidate_relevance_sufficient(
            query=query,
            text=text,
            relevance=relevance,
        )
        is False
    )


def test_query_relevance_expands_relationship_context_terms() -> None:
    relevance = score_query_relevance(
        query="What is Caroline's relationship status?",
        text=("D2:14 Caroline: She is excited to adopt as a single parent after a tough breakup."),
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


def test_query_relevance_expands_career_intent_to_jobs_and_counseling() -> None:
    terms = query_terms("Would Caroline pursue writing as a career option?")
    variants_by_raw = {term.raw: set(term.variants) for term in terms}
    relevance = score_query_relevance(
        query="Would Caroline pursue writing as a career option?",
        text=(
            "D7:5 D7:9 Caroline: Caroline is looking into counseling and mental "
            "health jobs after talking about education options."
        ),
    )

    assert {"consider", "explore", "looking"}.issubset(variants_by_raw["pursue"])
    assert {"job", "jobs", "work", "counseling"}.issubset(variants_by_raw["career"])
    assert relevance.unique_term_hits >= 3
    assert relevance.distinctive_term_hits >= 3
    assert is_query_relevance_sufficient(relevance) is True


def test_query_relevance_expands_relocation_intent_to_home_country_context() -> None:
    relevance = score_query_relevance(
        query="Where did Caroline move from 4 years ago?",
        text=(
            "D4:3 Caroline: This necklace was a gift from my grandma in my home "
            "country, Sweden, and reminds me of my roots."
        ),
    )

    assert relevance.unique_term_hits >= 2
    assert relevance.distinctive_term_hits >= 2
    assert is_query_relevance_sufficient(relevance) is True


def test_query_relevance_expands_outdoor_preference_to_camping_context() -> None:
    relevance = score_query_relevance(
        query="Would Melanie be more interested in going to a national park or a theme park?",
        text=(
            "D10:12 Melanie: We planned a camping trip with marshmallows around "
            "the campfire and watched the meteor shower in nature."
        ),
    )

    assert relevance.unique_term_hits >= 2
    assert relevance.distinctive_term_hits >= 2
    assert is_query_relevance_sufficient(relevance) is True


def test_query_relevance_expands_adoption_intent_to_family_support() -> None:
    relevance = score_query_relevance(
        query="What does Melanie think about Caroline's decision to adopt?",
        text=(
            "D2:15 Melanie: Creating a family for those kids is lovely. You'll be an awesome mom."
        ),
    )

    assert relevance.unique_term_hits >= 2
    assert relevance.distinctive_term_hits >= 2
    assert is_query_relevance_sufficient(relevance) is True


def test_query_relevance_expands_religious_and_political_inference_terms() -> None:
    political = score_query_relevance(
        query="What would Caroline's political leaning likely be?",
        text=(
            "D12:1 Caroline: Religious conservatives made an unwelcoming comment "
            "about her transition and LGBTQ rights."
        ),
    )
    religious = score_query_relevance(
        query="Would Caroline be considered religious?",
        text="D14:19 Caroline: She wrote to a local church about faith and acceptance.",
    )

    assert political.unique_term_hits >= 3
    assert political.distinctive_term_hits >= 2
    assert is_query_relevance_sufficient(political) is True
    assert religious.unique_term_hits >= 2
    assert religious.distinctive_term_hits >= 2
    assert is_query_relevance_sufficient(religious) is True


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


def test_chunk_candidate_relevance_keeps_before_and_now_role_state_evidence() -> None:
    query = (
        "How many engineers do I lead when I just started my new role as "
        "Senior Software Engineer? How many engineers do I lead now?"
    )
    before_text = "Taylor: I had just started the role and led a team of 4 engineers."
    now_text = "Taylor: I now lead a team of five engineers."

    before_relevance = score_query_relevance(query=query, text=before_text)
    now_relevance = score_query_relevance(query=query, text=now_text)

    assert before_relevance.distinctive_term_hits >= 4
    assert now_relevance.distinctive_term_hits >= 4
    assert (
        is_chunk_candidate_relevance_sufficient(
            query=query,
            text=before_text,
            relevance=before_relevance,
        )
        is True
    )
    assert (
        is_chunk_candidate_relevance_sufficient(
            query=query,
            text=now_text,
            relevance=now_relevance,
        )
        is True
    )


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


def test_fact_candidate_relevance_rejects_long_query_with_single_weak_hit() -> None:
    relevance = score_query_relevance(
        query="unrelated yakutsk cooking recipe quantum aquarium warranty",
        text="Billing warranty terms are tracked separately from project memories.",
    )

    assert relevance.query_term_count >= 6
    assert relevance.unique_term_hits == 1
    assert relevance.distinctive_term_hits == 1
    assert is_query_relevance_sufficient(relevance) is True
    assert is_fact_candidate_relevance_sufficient(relevance) is False


def test_fact_candidate_relevance_keeps_strong_long_query_match() -> None:
    relevance = score_query_relevance(
        query="primary runtime temporal fact engine Graphiti Obsidian 3D graph",
        text="LONGMEM_DECISION_GRAPHITI: Graphiti remains the temporal fact engine.",
    )

    assert relevance.query_term_count >= 6
    assert relevance.distinctive_term_hits >= 2
    assert is_fact_candidate_relevance_sufficient(relevance) is True


def test_fact_candidate_relevance_keeps_current_temporal_fact_for_old_query() -> None:
    relevance = score_query_relevance(
        query="legacy documents pgvector graph search disabled provider",
        text=(
            "LONGMEM_PROVIDER_CURRENT: documents use Qdrant RAG while Graphiti "
            "handles temporal facts."
        ),
    )

    assert relevance.unique_term_hits >= 2
    assert relevance.distinctive_term_hits >= 1
    assert is_fact_candidate_relevance_sufficient(relevance) is True


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
