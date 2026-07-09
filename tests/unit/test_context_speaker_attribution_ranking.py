from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import (
    apply_deterministic_rerank_adjustments,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_deterministic_rerank_uses_according_to_speaker_attribution() -> None:
    query = "According to Melanie, what traits does Caroline have?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    melanie_turn = _item(
        "melanie_trait",
        score=0.7,
        text="D16:18 Melanie: Caroline is thoughtful and patient.",
    )
    caroline_self_report = _item(
        "caroline_self_report",
        score=0.73,
        text="D16:9 Caroline: I try to be thoughtful and patient.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (melanie_turn, caroline_self_report),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "speaker_attribution_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "speaker_attribution_subject_self_report"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_uses_russian_according_to_speaker_attribution() -> None:
    query = "По словам Мелани, какие черты есть у Кэролайн?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    melanie_turn = _item(
        "melanie_trait",
        score=0.7,
        text="D16:18 Мелани: Кэролайн внимательная и терпеливая.",
    )
    caroline_self_report = _item(
        "caroline_self_report",
        score=0.73,
        text="D16:9 Кэролайн: Я стараюсь быть внимательной и терпеливой.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (melanie_turn, caroline_self_report),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "speaker_attribution_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "speaker_attribution_subject_self_report"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_matches_full_name_speaker_alias() -> None:
    query = "According to Melanie Chen, what traits does Caroline White have?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    melanie_turn = _item(
        "melanie_trait",
        score=0.7,
        text="D16:18 Melanie: Caroline is thoughtful and patient.",
    )
    caroline_self_report = _item(
        "caroline_self_report",
        score=0.73,
        text="D16:9 Caroline: I try to be thoughtful and patient.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (melanie_turn, caroline_self_report),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "speaker_attribution_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "speaker_attribution_subject_self_report"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_exact_full_name_over_wrong_full_name() -> None:
    query = "According to Melanie Chen, what traits does Caroline White have?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    exact_speaker_turn = _item(
        "melanie_chen_trait",
        score=0.7,
        text="D16:18 Melanie Chen: Caroline is thoughtful and patient.",
    )
    wrong_speaker_turn = _item(
        "melanie_smith_trait",
        score=0.73,
        text="D16:19 Melanie Smith: Caroline is organized and direct.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (wrong_speaker_turn, exact_speaker_turn),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["melanie_chen_trait"].score > by_id["melanie_smith_trait"].score
    assert (
        "speaker_attribution_match"
        in by_id["melanie_chen_trait"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "speaker_attribution_other_speaker"
        in by_id["melanie_smith_trait"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_demotes_given_name_alias_when_exact_full_name_exists() -> None:
    query = "According to Melanie Chen, what traits does Caroline White have?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    exact_speaker_turn = _item(
        "melanie_chen_trait",
        score=0.7,
        text="D16:18 Melanie Chen: Caroline is thoughtful and patient.",
    )
    ambiguous_alias_turn = _item(
        "melanie_alias_trait",
        score=0.73,
        text="D16:19 Melanie: Caroline is organized and direct.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (ambiguous_alias_turn, exact_speaker_turn),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["melanie_chen_trait"].score > by_id["melanie_alias_trait"].score
    assert (
        "speaker_attribution_alias_shadowed_by_exact_name"
        in by_id["melanie_alias_trait"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_who_told_directional_evidence() -> None:
    query = "Who told Alex about the Project Atlas delay?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    directed_turn = _item(
        "maria_told_alex",
        score=0.7,
        text="D3:4 Maria: I told Alex about the Project Atlas delay yesterday.",
    )
    name_only_turn = _item(
        "alex_name_only",
        score=0.73,
        text="D3:5 Alex: Project Atlas had an invoice delay yesterday.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (name_only_turn, directed_turn),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["maria_told_alex"].score > by_id["alex_name_only"].score
    assert (
        "communication_direction_grounded"
        in by_id["maria_told_alex"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "communication_direction_ungrounded"
        in by_id["alex_name_only"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def _item(item_id: str, *, score: float, text: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="document", source_id="doc"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {"base_score": score},
            "provenance": {"retrieval_sources": ["keyword_chunks"]},
        },
    )
