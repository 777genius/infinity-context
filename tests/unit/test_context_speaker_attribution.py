from __future__ import annotations

from infinity_context_core.application.context_speaker_attribution import (
    speaker_attribution_signal,
)


def test_speaker_attribution_strips_question_lead_words_from_speaker() -> None:
    assert speaker_attribution_signal(
        query="What did Alex say about Project Atlas?",
        text="D3:4 Alex: Project Atlas should wait until the invoice check passes.",
    ) == (0.024, 0.0, "speaker_attribution_match")


def test_speaker_attribution_keeps_subject_for_self_report_penalty() -> None:
    assert speaker_attribution_signal(
        query="What personality traits might Melanie say Caroline has?",
        text="D16:9 Caroline: Painting helped me express myself.",
    ) == (0.0, 0.034, "speaker_attribution_subject_self_report")


def test_speaker_attribution_does_not_match_different_full_name_speaker() -> None:
    assert speaker_attribution_signal(
        query="According to Melanie Chen, what traits does Caroline White have?",
        text="D16:18 Melanie Smith: Caroline is thoughtful and patient.",
    ) == (0.0, 0.024, "speaker_attribution_other_speaker")


def test_speaker_attribution_keeps_full_name_to_given_name_alias() -> None:
    assert speaker_attribution_signal(
        query="According to Melanie Chen, what traits does Caroline White have?",
        text="D16:18 Melanie: Caroline is thoughtful and patient.",
    ) == (0.024, 0.0, "speaker_attribution_match")
