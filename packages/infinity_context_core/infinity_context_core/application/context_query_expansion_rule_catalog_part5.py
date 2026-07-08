"""Static query expansion rule catalog part 5."""

from __future__ import annotations

from infinity_context_core.application import context_query_expansion_rule_terms as _terms
from infinity_context_core.application.context_query_workflow_expansions import (
    WORKFLOW_EXPANSION_RULES,
)

EXPANSION_RULES_PART_5: tuple[tuple[frozenset[str], str, str], ...] = (
    (
            frozenset({"говорила"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"общалась"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"общались"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"встреча"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"встрече"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"разговор"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"разговоре"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"чате"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"meeting"}),
            "transcript notes discussed decision decisions action items follow up meeting",
            "meeting_evidence_bridge",
        ),
    *WORKFLOW_EXPANSION_RULES,
    (
            frozenset({"source"}),
            (
                "source citation evidence quote reference provenance origin document "
                "artifact transcript ocr"
            ),
            "source_evidence_bridge",
        ),
    (
            frozenset({"citation"}),
            (
                "source citation evidence quote reference provenance origin document "
                "artifact transcript ocr"
            ),
            "source_evidence_bridge",
        ),
    (
            frozenset({"evidence"}),
            (
                "source citation evidence quote reference provenance origin document "
                "artifact transcript ocr"
            ),
            "source_evidence_bridge",
        ),
    (
            frozenset({"proof"}),
            (
                "source citation evidence quote reference provenance origin document "
                "artifact transcript ocr"
            ),
            "source_evidence_bridge",
        ),
    (
            frozenset({"видео"}),
            "транскрипт сказал сказала обсудили упомянул упомянула кадр видео аудио",
            "video_transcript_evidence_bridge",
        ),
    (
            frozenset({"ролик"}),
            "транскрипт сказал сказала обсудили упомянул упомянула кадр видео аудио",
            "video_transcript_evidence_bridge",
        ),
    (
            frozenset({"ролике"}),
            "транскрипт сказал сказала обсудили упомянул упомянула кадр видео аудио",
            "video_transcript_evidence_bridge",
        ),
    (
            frozenset({"видеозапись"}),
            "транскрипт сказал сказала обсудили упомянул упомянула кадр видео аудио",
            "video_transcript_evidence_bridge",
        ),
    (
            frozenset({"видеозаписи"}),
            "транскрипт сказал сказала обсудили упомянул упомянула кадр видео аудио",
            "video_transcript_evidence_bridge",
        ),
    (
            frozenset({"аудио"}),
            "транскрипт речь голос сказал сказала обсудили аудио",
            "audio_transcript_evidence_bridge",
        ),
    (
            frozenset({"аудиозапись"}),
            "транскрипт речь голос сказал сказала обсудили аудио",
            "audio_transcript_evidence_bridge",
        ),
    (
            frozenset({"аудиозаписи"}),
            "транскрипт речь голос сказал сказала обсудили аудио",
            "audio_transcript_evidence_bridge",
        ),
    (
            frozenset({"голосовое"}),
            "транскрипт речь голос сказал сказала обсудили аудио",
            "audio_transcript_evidence_bridge",
        ),
    (
            frozenset({"голосовом"}),
            "транскрипт речь голос сказал сказала обсудили аудио",
            "audio_transcript_evidence_bridge",
        ),
    (
            frozenset({"скриншот"}),
            "ocr текст написано надпись экран изображение визуальный",
            "visual_text_evidence_bridge",
        ),
    (
            frozenset({"скрин"}),
            "ocr текст написано надпись экран изображение визуальный",
            "visual_text_evidence_bridge",
        ),
    (
            frozenset({"скрине"}),
            "ocr текст написано надпись экран изображение визуальный",
            "visual_text_evidence_bridge",
        ),
    (
            frozenset({"картинка"}),
            "ocr текст написано надпись экран изображение визуальный",
            "visual_text_evidence_bridge",
        ),
    (
            frozenset({"картинке"}),
            "ocr текст написано надпись экран изображение визуальный",
            "visual_text_evidence_bridge",
        ),
    (
            frozenset({"источник"}),
            (
                "источник ссылка доказательство цитата откуда документ артефакт "
                "транскрипт ocr source citation"
            ),
            "source_evidence_bridge",
        ),
    (
            frozenset({"ссылка"}),
            (
                "источник ссылка доказательство цитата откуда документ артефакт "
                "транскрипт ocr source citation"
            ),
            "source_evidence_bridge",
        ),
    (
            frozenset({"доказательство"}),
            (
                "источник ссылка доказательство цитата откуда документ артефакт "
                "транскрипт ocr source citation"
            ),
            "source_evidence_bridge",
        ),
    (
            frozenset({"latest"}),
            (
                "latest current active newest recent updated now valid not stale "
                "актуальный текущий последний"
            ),
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"current"}),
            (
                "latest current active newest recent updated now valid not stale "
                "актуальный текущий последний"
            ),
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"currently"}),
            (
                "currently current active latest recent updated now right now "
                "valid not stale актуальный текущий сейчас"
            ),
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"recent"}),
            (
                "most recent latest current active newest updated now valid not stale "
                "актуальный текущий последний"
            ),
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"still", "valid"}),
            (
                "still valid remains current active latest selected chosen recommended "
                "not stale not outdated актуальный текущий действует"
            ),
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"still", "use"}),
            (
                "still use still using current active selected chosen recommended "
                "provider tool model option not stale not outdated"
            ),
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"remains"}),
            (
                "remains valid current active latest recommended selected chosen "
                "not stale not outdated"
            ),
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"final", "decision"}),
            _terms._CURRENT_DECISION_EXPANSION,
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"final", "provider"}),
            _terms._CURRENT_DECISION_EXPANSION,
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"source", "truth"}),
            _terms._CURRENT_DECISION_EXPANSION,
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"canonical"}),
            _terms._CURRENT_DECISION_EXPANSION,
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"selected", "provider"}),
            _terms._CURRENT_DECISION_EXPANSION,
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"chosen", "provider"}),
            _terms._CURRENT_DECISION_EXPANSION,
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"should", "use"}),
            _terms._CURRENT_RECOMMENDATION_EXPANSION,
            "current_recommendation_bridge",
        ),
    (
            frozenset({"recommended", "provider"}),
            _terms._CURRENT_RECOMMENDATION_EXPANSION,
            "current_recommendation_bridge",
        ),
    (
            frozenset({"preferred", "provider"}),
            _terms._CURRENT_RECOMMENDATION_EXPANSION,
            "current_recommendation_bridge",
        ),
    (
            frozenset({"best", "provider"}),
            _terms._CURRENT_RECOMMENDATION_EXPANSION,
            "current_recommendation_bridge",
        ),
    (
            frozenset({"decided", "provider"}),
            _terms._CURRENT_RECOMMENDATION_EXPANSION,
            "current_recommendation_bridge",
        ),
    (
            frozenset({"choose", "provider"}),
            _terms._CURRENT_RECOMMENDATION_EXPANSION,
            "current_recommendation_bridge",
        ),
    (
            frozenset({"chosen", "provider"}),
            _terms._CURRENT_RECOMMENDATION_EXPANSION,
            "current_recommendation_bridge",
        ),
    (
            frozenset({"selected", "provider"}),
            _terms._CURRENT_RECOMMENDATION_EXPANSION,
            "current_recommendation_bridge",
        ),
    (
            frozenset({"chose", "provider"}),
            _terms._CURRENT_RECOMMENDATION_EXPANSION,
            "current_recommendation_bridge",
        ),
    (
            frozenset({"decided", "use"}),
            _terms._CURRENT_RECOMMENDATION_EXPANSION,
            "current_recommendation_bridge",
        ),
    (
            frozenset({"choose", "use"}),
            _terms._CURRENT_RECOMMENDATION_EXPANSION,
            "current_recommendation_bridge",
        ),
    (
            frozenset({"chose", "use"}),
            _terms._CURRENT_RECOMMENDATION_EXPANSION,
            "current_recommendation_bridge",
        ),
    (
            frozenset({"state_transition_request"}),
            _terms._STATE_TRANSITION_EXPANSION,
            "state_transition_bridge",
        ),
    (
            frozenset({"changed"}),
            (
                "changed change updated now before after previous current old new "
                "superseded replaced difference"
            ),
            "change_over_time_bridge",
        ),
    (
            frozenset({"change"}),
            (
                "changed change updated now before after previous current old new "
                "superseded replaced difference"
            ),
            "change_over_time_bridge",
        ),
    (
            frozenset({"updated"}),
            "changed change updated latest current previous superseded replaced difference",
            "change_over_time_bridge",
        ),
    (
            frozenset({"after"}),
            "after later following post meeting call decision follow up next",
            "after_event_temporal_bridge",
        ),
    (
            frozenset({"before"}),
            "before earlier prior previous previous state old initial",
            "before_event_temporal_bridge",
        ),
    (
            frozenset({"stale"}),
            "stale outdated old superseded replaced previous not current invalid expired review",
            "stale_state_temporal_bridge",
        ),
    (
            frozenset({"outdated"}),
            "stale outdated old superseded replaced previous not current invalid expired review",
            "stale_state_temporal_bridge",
        ),
    (
            frozenset({"obsolete"}),
            (
                "stale obsolete deprecated outdated old superseded replaced previous "
                "not current review"
            ),
            "stale_state_temporal_bridge",
        ),
    (
            frozenset({"deprecated"}),
            "deprecated obsolete stale outdated superseded replaced previous not current review",
            "stale_state_temporal_bridge",
        ),
    (
            frozenset({"expired"}),
            (
                "expired stale outdated superseded replaced previous no longer valid "
                "not current review"
            ),
            "stale_state_temporal_bridge",
        ),
    (
            frozenset({"longer", "valid"}),
            (
                "no longer valid stale outdated superseded replaced previous old "
                "not current invalid deprecated review"
            ),
            "stale_state_temporal_bridge",
        ),
    (
            frozenset({"longer", "use"}),
            (
                "no longer use no longer using stale outdated superseded replaced "
                "previous old not current invalid deprecated review"
            ),
            "stale_state_temporal_bridge",
        ),
    (
            frozenset({"anymore", "valid"}),
            (
                "not valid anymore no longer valid stale outdated superseded replaced "
                "previous old not current invalid review"
            ),
            "stale_state_temporal_bridge",
        ),
    (
            frozenset({"stopped"}),
            (
                "stopped using no longer use stale outdated superseded replaced "
                "previous old not current review"
            ),
            "stale_state_temporal_bridge",
        ),
    (
            frozenset({"not", "current"}),
            "not current stale outdated superseded replaced previous old invalid review",
            "stale_state_temporal_bridge",
        ),
    (
            frozenset({"актуал"}),
            "актуальный текущий последний сейчас обновлен действует не устаревший latest current",
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"актуален"}),
            "актуальный текущий последний сейчас обновлен действует не устаревший latest current",
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"актуальн"}),
            "актуальный текущий последний сейчас обновлен действует не устаревший latest current",
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"последн"}),
            "последний актуальный текущий сейчас обновлен latest current recent",
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"финальн", "решение"}),
            _terms._CURRENT_DECISION_EXPANSION,
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"решение", "выбранный"}),
            _terms._CURRENT_DECISION_EXPANSION,
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"провайдер", "выбранный"}),
            _terms._CURRENT_DECISION_EXPANSION,
            "current_state_temporal_bridge",
        ),
    (
            frozenset({"обновлен"}),
            "изменилось обновилось последний текущий предыдущий старый новый replaced superseded",
            "change_over_time_bridge",
        ),
    (
            frozenset({"изменилось"}),
            (
                "изменилось изменили сменился сменили заменили стало раньше сейчас "
                "до после с на предыдущий текущий старый новый replaced from to"
            ),
            "change_over_time_bridge",
        ),
    (
            frozenset({"после"}),
            "после позже затем встреча созвон решение follow up next after",
            "after_event_temporal_bridge",
        ),
    (
            frozenset({"до"}),
            "до раньше перед предыдущий начальный старый before prior previous",
            "before_event_temporal_bridge",
        ),
    (
            frozenset({"устаревш"}),
            "устаревший старый superseded replaced previous not current актуальный текущий",
            "stale_state_temporal_bridge",
        ),
    (
            frozenset({"больше", "использовать"}),
            (
                "больше не использовать устаревший старый заменен предыдущий "
                "не актуальный not current stale superseded"
            ),
            "stale_state_temporal_bridge",
        ),
    (
            frozenset({"больше", "актуал"}),
            (
                "больше не актуальный устаревший старый заменен предыдущий "
                "не текущий stale superseded"
            ),
            "stale_state_temporal_bridge",
        ),
)
