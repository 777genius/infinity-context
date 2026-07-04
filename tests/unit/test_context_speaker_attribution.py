from __future__ import annotations

from infinity_context_core.application.context_speaker_attribution import (
    communication_direction_signal,
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


def test_communication_direction_signal_boosts_who_told_local_direction() -> None:
    assert communication_direction_signal(
        query="Who told Alex about the Project Atlas delay?",
        text="D3:4 Maria: I told Alex about the Project Atlas delay yesterday.",
    ) == (0.032, 0.0, "communication_direction_grounded")


def test_communication_direction_signal_penalizes_name_without_direction() -> None:
    assert communication_direction_signal(
        query="Who told Alex about the Project Atlas delay?",
        text="D3:4 Alex: Project Atlas had an invoice delay yesterday.",
    ) == (0.0, 0.035, "communication_direction_ungrounded")


def test_communication_direction_signal_boosts_who_did_speaker_tell() -> None:
    assert communication_direction_signal(
        query="Who did Alex tell about the Project Atlas delay?",
        text="D3:4 Alex: I told Maria about the Project Atlas delay yesterday.",
    ) == (0.032, 0.0, "communication_direction_grounded")


def test_communication_direction_signal_covers_reminded_and_warned_queries() -> None:
    assert communication_direction_signal(
        query="Who reminded Alex about the Project Atlas invoice?",
        text="D3:4 Maria: I reminded Alex about the Project Atlas invoice.",
    ) == (0.032, 0.0, "communication_direction_grounded")
    assert communication_direction_signal(
        query="Who did Alex warn about the Project Atlas delay?",
        text="D3:5 Alex: I warned Maria about the Project Atlas delay.",
    ) == (0.032, 0.0, "communication_direction_grounded")
