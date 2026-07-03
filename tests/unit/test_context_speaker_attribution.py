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
