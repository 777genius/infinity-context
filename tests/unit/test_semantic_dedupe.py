from infinity_context_core.application.semantic_dedupe import (
    describe_conflicting_fact_match,
    describe_duplicate_fact_match,
    looks_conflicting_fact,
    looks_equivalent_fact,
    normalize_memory_text,
    recommend_duplicate_fact_merge_review,
    semantic_memory_terms,
)


def test_semantic_dedupe_recognizes_document_vector_paraphrase() -> None:
    assert looks_equivalent_fact(
        "Docs retrieval should use Qdrant vectors.",
        "Qdrant owns document vector retrieval.",
    )
    match = describe_duplicate_fact_match(
        "Docs retrieval should use Qdrant vectors.",
        "Qdrant owns document vector retrieval.",
    )
    assert match is not None
    assert match.match_type == "semantic_token_overlap"
    assert "semantic_duplicate" in match.reason_codes


def test_semantic_dedupe_recognizes_russian_person_project_paraphrase() -> None:
    match = describe_duplicate_fact_match(
        "Алекс согласовал срок по проекту Атлас 7 дней.",
        "От Алекса пришло подтверждение: проект Атлас срок 7 дней.",
    )

    assert match is not None
    assert match.match_type == "semantic_token_overlap"
    assert "semantic_duplicate" in match.reason_codes
    assert "person:aleks" in match.overlap_terms
    assert "project:atlas" in match.overlap_terms


def test_semantic_dedupe_recognizes_russian_document_retrieval_paraphrase() -> None:
    match = describe_duplicate_fact_match(
        "Алекс сказал использовать Qdrant для документов.",
        "От Алекса пришло: документы ищем через Qdrant.",
    )

    assert match is not None
    assert "document" in match.overlap_terms
    assert "person:aleks" in match.overlap_terms
    assert "project:qdrant" in match.overlap_terms


def test_semantic_dedupe_recognizes_cross_script_project_identity() -> None:
    match = describe_duplicate_fact_match(
        "Project Atlas uses Qdrant for documents.",
        "проект Атлас использует Qdrant для документов.",
    )

    assert match is not None
    assert match.match_type == "semantic_token_overlap"
    assert "project:atlas" in match.overlap_terms


def test_semantic_dedupe_uses_explicit_anchor_alias_identity_terms() -> None:
    terms = semantic_memory_terms(
        "Alex aka Alexander Cooper owns Project Atlas aka Atlas Mobile retrieval."
    )
    match = describe_duplicate_fact_match(
        "Alex aka Alexander Cooper owns Project Atlas aka Atlas Mobile retrieval.",
        "Alexander Cooper owns Project Atlas Mobile retrieval notes.",
    )

    assert "person:aleks" in terms
    assert "person:aleksander cooper" in terms
    assert "project:atlas" in terms
    assert "project:atlas mobile" in terms
    assert match is not None
    assert "person:aleksander cooper" in match.overlap_terms
    assert "project:atlas mobile" in match.overlap_terms


def test_semantic_dedupe_recognizes_cross_language_screenshot_paraphrase() -> None:
    match = describe_duplicate_fact_match(
        "Скриншот инвойса Project Atlas показывает владельца Alex.",
        "Project Atlas screenshot invoice shows owner Alex.",
    )

    assert match is not None
    assert match.match_type == "semantic_token_overlap"
    assert "screenshot" in match.overlap_terms
    assert "invoice" in match.overlap_terms
    assert "owner" in match.overlap_terms
    assert "person:aleks" in match.overlap_terms
    assert "project:atlas" in match.overlap_terms


def test_semantic_dedupe_recognizes_cross_language_audio_call_paraphrase() -> None:
    match = describe_duplicate_fact_match(
        "Аудио запись созвона с Алексом по Project Atlas про billing.",
        "Transcript from Alex Project Atlas billing call.",
    )

    assert match is not None
    assert "event_type:call" in match.overlap_terms
    assert "event_participant:aleks" in match.overlap_terms
    assert "billing" in match.overlap_terms
    assert "project:atlas" in match.overlap_terms


def test_semantic_dedupe_recognizes_cross_language_call_summary_identity_overlap() -> None:
    match = describe_duplicate_fact_match(
        "Итоги созвона: Алекс отвечает за поиск документов в Атласе.",
        "Alex owns Atlas document retrieval notes from the call.",
    )

    assert match is not None
    assert match.match_type == "semantic_token_overlap"
    assert "semantic_duplicate" in match.reason_codes
    assert "event_type:call" in match.overlap_terms
    assert "person:aleks" in match.overlap_terms
    assert "project:atlas" in match.overlap_terms
    assert "document" in match.overlap_terms
    assert "owner" in match.overlap_terms
    assert "retrieval" in match.overlap_terms


def test_semantic_terms_do_not_promote_locative_project_as_person() -> None:
    terms = semantic_memory_terms("Итоги созвона: Алекс отвечает за поиск документов в Атласе.")

    assert "person:aleks" in terms
    assert "project:atlas" in terms
    assert "event_project:atlas" in terms
    assert "person:atlas" not in terms


def test_semantic_dedupe_recognizes_cross_language_video_keyframe_paraphrase() -> None:
    match = describe_duplicate_fact_match(
        "Видео фрагмент демо Project Atlas показывает billing dashboard.",
        "Project Atlas video keyframe shows billing dashboard demo.",
    )

    assert match is not None
    assert "video" in match.overlap_terms
    assert "demo" in match.overlap_terms
    assert "billing" in match.overlap_terms
    assert "project:atlas" in match.overlap_terms


def test_semantic_dedupe_rejects_exclusive_engine_mismatch() -> None:
    assert not looks_equivalent_fact(
        "Docs retrieval should use Qdrant vectors.",
        "Postgres owns document vector retrieval.",
    )


def test_semantic_dedupe_rejects_similar_but_different_project() -> None:
    assert not looks_equivalent_fact(
        "Project Atlas uses Qdrant retrieval for documents.",
        "Project Beta uses Qdrant retrieval for documents.",
    )
    assert not looks_conflicting_fact(
        "Project Atlas uses Qdrant retrieval for documents.",
        "Project Beta uses Qdrant retrieval for documents.",
    )
    assert not looks_equivalent_fact(
        "проект Атлас использует Qdrant для документов.",
        "проект Бета использует Qdrant для документов.",
    )


def test_semantic_dedupe_rejects_similar_but_different_person_event() -> None:
    assert not looks_equivalent_fact(
        "Alex call last week covered Project Atlas pricing.",
        "Maria call last week covered Project Atlas pricing.",
    )
    assert not looks_conflicting_fact(
        "Alex call last week covered Project Atlas pricing.",
        "Maria call last week covered Project Atlas pricing.",
    )


def test_semantic_dedupe_rejects_similar_owner_with_different_named_person() -> None:
    assert not looks_equivalent_fact(
        "Maria owns Project Atlas retrieval notes.",
        "Alex owns Project Atlas retrieval notes.",
    )
    assert not looks_equivalent_fact(
        "Итоги созвона: Мария отвечает за поиск документов в Атласе.",
        "Alex owns Atlas document retrieval notes from the call.",
    )


def test_semantic_dedupe_rejects_similar_but_different_event_time() -> None:
    assert not looks_equivalent_fact(
        "Alex call yesterday covered Project Atlas pricing.",
        "Alex call last week covered Project Atlas pricing.",
    )
    assert not looks_conflicting_fact(
        "Alex call yesterday covered Project Atlas pricing.",
        "Alex call last week covered Project Atlas pricing.",
    )
    assert not looks_equivalent_fact(
        "Час назад переписывался с Алексом по Project Atlas pricing.",
        "На прошлой неделе переписывался с Алексом по Project Atlas pricing.",
    )


def test_semantic_dedupe_exposes_structured_event_overlap_terms() -> None:
    terms = semantic_memory_terms("Chat with Alex an hour ago covered Project Atlas pricing.")
    match = describe_duplicate_fact_match(
        "Chat with Alex an hour ago covered Project Atlas pricing.",
        "Chat with Alex hour ago covered Project Atlas pricing.",
    )

    assert "event_type:chat" in terms
    assert "event_participant:aleks" in terms
    assert "event_temporal:hours_ago:1:hour" in terms
    assert match is not None
    assert "event_type:chat" in match.overlap_terms
    assert "event_participant:aleks" in match.overlap_terms
    assert "event_temporal:hours_ago:1:hour" in match.overlap_terms


def test_semantic_dedupe_exposes_structured_event_project_terms() -> None:
    terms = semantic_memory_terms("Call with Alex about Atlas 2 hours ago covered billing.")
    match = describe_duplicate_fact_match(
        "Call with Alex about Atlas 2 hours ago covered billing.",
        "Call with Alex about Atlas 2 hours ago covered billing.",
    )

    assert "event_type:call" in terms
    assert "event_participant:aleks" in terms
    assert "event_project:atlas" in terms
    assert "event_temporal:hours_ago:2:hour" in terms
    assert match is not None
    assert "event_project:atlas" in match.overlap_terms


def test_semantic_dedupe_matches_cross_language_phone_call_event_identity() -> None:
    match = describe_duplicate_fact_match(
        "Позвонил Алексу по Атласу час назад про billing cutoff.",
        "Call with Alex about Atlas an hour ago covered billing cutoff.",
    )

    assert match is not None
    assert match.match_type == "semantic_identity_overlap"
    assert "event_type:call" in match.overlap_terms
    assert "event_participant:aleks" in match.overlap_terms
    assert "event_project:atlas" in match.overlap_terms
    assert "event_temporal:hours_ago:1:hour" in match.overlap_terms
    assert "billing" in match.overlap_terms
    assert "cutoff" in match.overlap_terms


def test_semantic_dedupe_rejects_similar_event_with_different_project() -> None:
    assert not looks_equivalent_fact(
        "Call with Alex about Atlas 2 hours ago covered billing.",
        "Call with Alex about Orion 2 hours ago covered billing.",
    )
    assert not looks_conflicting_fact(
        "Call with Alex about Atlas 2 hours ago covered billing.",
        "Call with Alex about Orion 2 hours ago covered billing.",
    )


def test_semantic_dedupe_rejects_numeric_value_mismatch_as_duplicate() -> None:
    assert not looks_equivalent_fact(
        "Project Atlas keeps billing logs for 7 days.",
        "Project Atlas keeps billing logs for 30 days.",
    )
    assert looks_conflicting_fact(
        "Project Atlas keeps billing logs for 7 days.",
        "Project Atlas keeps billing logs for 30 days.",
    )
    match = describe_conflicting_fact_match(
        "Project Atlas keeps billing logs for 7 days.",
        "Project Atlas keeps billing logs for 30 days.",
    )
    assert match is not None
    assert match.match_type == "numeric_value_mismatch"
    assert "numeric_value_mismatch" in match.reason_codes


def test_semantic_dedupe_rejects_version_value_mismatch_as_duplicate() -> None:
    assert not looks_equivalent_fact(
        "Project Atlas API uses model v2 for routing.",
        "Project Atlas API uses model v3 for routing.",
    )
    assert looks_conflicting_fact(
        "Project Atlas API uses model v2 for routing.",
        "Project Atlas API uses model v3 for routing.",
    )


def test_semantic_dedupe_keeps_exact_numeric_fact_duplicate() -> None:
    match = describe_duplicate_fact_match(
        "Project Atlas keeps 3 Qdrant replicas.",
        "Project Atlas keeps 3 Qdrant replicas.",
    )

    assert match is not None
    assert match.match_type == "exact_normalized_text"


def test_duplicate_merge_recommendation_keeps_exact_match_review_gated() -> None:
    match = describe_duplicate_fact_match(
        "Project Atlas keeps 3 Qdrant replicas.",
        "Project Atlas keeps 3 Qdrant replicas.",
    )

    assert match is not None
    recommendation = recommend_duplicate_fact_merge_review(match)
    payload = recommendation.to_review_payload()
    assert payload["recommended_resolution_action"] == "merge_source_refs"
    assert payload["review_risk"] == "low"
    assert payload["recommendation_confidence"] == "high"
    assert payload["requires_review"] is True
    assert payload["auto_merge_eligible"] is False
    assert "human_review_required" in payload["recommendation_reason_codes"]


def test_duplicate_merge_recommendation_marks_identity_match_as_medium_risk() -> None:
    match = describe_duplicate_fact_match(
        "Позвонил Алексу по Атласу час назад про billing cutoff.",
        "Call with Alex about Atlas an hour ago covered billing cutoff.",
    )

    assert match is not None
    recommendation = recommend_duplicate_fact_merge_review(match)
    assert recommendation.review_risk == "medium"
    assert recommendation.recommendation_confidence == "medium"
    assert recommendation.auto_merge_eligible is False
    assert "structured_identity_overlap" in recommendation.reason_codes


def test_duplicate_merge_recommendation_marks_anchor_overlap_as_high_risk() -> None:
    match = describe_duplicate_fact_match(
        "Qdrant graph memory adapter.",
        "Qdrant graph memory adapter owns canonical temporal truth storage retrieval "
        "dashboard vector document.",
    )

    assert match is not None
    assert match.match_type == "semantic_anchor_overlap"
    recommendation = recommend_duplicate_fact_merge_review(match)
    assert recommendation.review_risk == "high"
    assert recommendation.recommendation_confidence == "low"
    assert recommendation.requires_review is True
    assert recommendation.auto_merge_eligible is False
    assert "keep_separate_available" in recommendation.reason_codes


def test_semantic_dedupe_flags_engine_conflict_without_equivalence() -> None:
    assert looks_conflicting_fact(
        "Docs retrieval should use Qdrant vectors.",
        "Postgres owns document vector retrieval.",
    )
    assert not looks_equivalent_fact(
        "Docs retrieval should use Qdrant vectors.",
        "Postgres owns document vector retrieval.",
    )


def test_semantic_dedupe_flags_negated_decision_conflict() -> None:
    assert looks_conflicting_fact(
        "Use Graphiti for temporal facts.",
        "Do not use Graphiti for temporal facts.",
    )


def test_semantic_dedupe_does_not_flag_equivalent_paraphrase_as_conflict() -> None:
    assert not looks_conflicting_fact(
        "Docs retrieval should use Qdrant vectors.",
        "Qdrant owns document vector retrieval.",
    )


def test_semantic_dedupe_rejects_negation_mismatch() -> None:
    assert not looks_equivalent_fact(
        "Use Graphiti for temporal facts.",
        "Do not use Graphiti for temporal facts.",
    )


def test_semantic_terms_normalize_common_memory_aliases() -> None:
    assert "document" in semantic_memory_terms("Docs should be indexed.")
    assert normalize_memory_text("  Graphiti\r\nTemporal   Graph ") == "graphiti temporal graph"
