"""English competition/tournament exact-turn candidates for count evidence."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace

from infinity_context_core.application.context_diagnostics import context_rank_key
from infinity_context_core.application.context_packer_answer_support_utils import (
    _diagnostic_signal_text,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef

_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_EN_COMPETITION_COUNT_QUERY_RE = re.compile(
    r"\b(?:how\s+many|number|count|total|times?)\b"
    r"(?=.{0,160}\b(?:tournaments?|tourneys?|competitions?|contests?|"
    r"championships?|finals?)\b)|"
    r"\b(?:tournaments?|tourneys?|competitions?|contests?|championships?|finals?)\b"
    r"(?=.{0,160}\b(?:how\s+many|number|count|total|times?|won|"
    r"participat(?:e|ed|ing)|competed|competing)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EN_COMPETITION_OBJECT_RE = re.compile(
    r"\b(?:tournaments?|tourneys?|competitions?|contests?|championships?|finals?)\b",
    re.IGNORECASE,
)
_EN_COMPETITION_COUNT_REASONS = frozenset(
    {
        "board-game-inventory-bridge",
        "decomposition-quantity-count",
        "original-query",
        "quantity-enumeration-bridge",
        "source-sibling-answer-evidence",
        "tournament-count-bridge",
    }
)
_EN_COMPETITION_WIN_QUERY_RE = re.compile(
    r"\b(?:won|winning|winner|victor(?:y|ies)|champions?|first\s+place)\b",
    re.IGNORECASE,
)
_EN_COMPETITION_PARTICIPATION_QUERY_RE = re.compile(
    r"\b(?:participat(?:e|ed|ing)|competed|competing|played|joined|entered|"
    r"been\s+in|was\s+in|were\s+in|took\s+part)\b",
    re.IGNORECASE,
)
_EN_COMPETITION_WIN_EVENT_RE = re.compile(
    r"\b(?:i|we)\b"
    r"(?=.{0,180}\b(?:won|wins?|winner|victor(?:y|ies)|champions?|first\s+place)\b)"
    r"(?=.{0,240}\b(?:tournaments?|tourneys?|competitions?|contests?|"
    r"championships?|finals?)\b)|"
    r"\b(?:won|wins?|winner|victor(?:y|ies)|champions?|first\s+place)\b"
    r"(?=.{0,220}\b(?:tournaments?|tourneys?|competitions?|contests?|"
    r"championships?|finals?)\b)"
    r"(?=.{0,240}\b(?:i|we|my|our)\b)|"
    r"\b(?:[A-Z][A-Za-z'.-]{1,40}|he|she|they)\b"
    r"(?=.{0,180}\b(?:won|wins?|winner|victor(?:y|ies)|champions?|first\s+place)\b)"
    r"(?=.{0,240}\b(?:tournaments?|tourneys?|competitions?|contests?|"
    r"championships?|finals?)\b)|"
    r"\b(?:won|wins?|winner|victor(?:y|ies)|champions?|first\s+place)\b"
    r"(?=.{0,220}\b(?:tournaments?|tourneys?|competitions?|contests?|"
    r"championships?|finals?)\b)"
    r"(?=.{0,240}\b(?:[A-Z][A-Za-z'.-]{1,40}|he|she|they|his|her|their)\b)|"
    r"\b(?:finals?)\b(?=.{0,160}\b(?:tournaments?|tourneys?)\b)"
    r"(?=.{0,200}\b(?:i|we)\b(?=.{0,80}\bwon\b))",
    re.IGNORECASE | re.DOTALL,
)
_EN_COMPETITION_PARTICIPATION_EVENT_RE = re.compile(
    r"\b(?:i|we)\b"
    r"(?=.{0,200}\b(?:participat(?:e|ed|ing)|competed|competing|entered|"
    r"played|joined|was\s+in|were\s+in|took\s+part|didn'?t\s+do|"
    r"does(?:n'?t| not)\s+do|faces?\s+a\s+setback|setback|"
    r"letdown|tried\s+(?:my|our)\s+hand)\b)"
    r"(?=.{0,240}\b(?:tournaments?|tourneys?|competitions?|contests?|"
    r"championships?|finals?)\b)|"
    r"\b(?:participat(?:e|ed|ing)|competed|competing|entered|played|joined|"
    r"was\s+in|were\s+in|took\s+part|didn'?t\s+do|"
    r"does(?:n'?t| not)\s+do|faces?\s+a\s+setback|setback|letdown|"
    r"tried\s+(?:my|our)\s+hand)\b"
    r"(?=.{0,220}\b(?:tournaments?|tourneys?|competitions?|contests?|"
    r"championships?|finals?)\b)"
    r"(?=.{0,240}\b(?:i|we|my|our)\b)|"
    r"\b(?:[A-Z][A-Za-z'.-]{1,40}|he|she|they)\b"
    r"(?=.{0,200}\b(?:participat(?:e|ed|ing)|competed|competing|enters?|"
    r"played|joined|was\s+in|were\s+in|took\s+part|"
    r"did(?:n'?t| not)\s+do|does(?:n'?t| not)\s+do|faces?\s+a\s+setback|"
    r"experienced?\s+a\s+letdown|setback|letdown|"
    r"tried\s+(?:his|her|their)\s+hand)\b)"
    r"(?=.{0,240}\b(?:tournaments?|tourneys?|competitions?|contests?|"
    r"championships?|finals?)\b)|"
    r"\b(?:participat(?:e|ed|ing)|competed|competing|enters?|played|joined|"
    r"was\s+in|were\s+in|took\s+part|did(?:n'?t| not)\s+do|"
    r"does(?:n'?t| not)\s+do|faces?\s+a\s+setback|"
    r"experienced?\s+a\s+letdown|setback|letdown|"
    r"tried\s+(?:his|her|their)\s+hand)\b"
    r"(?=.{0,220}\b(?:tournaments?|tourneys?|competitions?|contests?|"
    r"championships?|finals?)\b)"
    r"(?=.{0,240}\b(?:[A-Z][A-Za-z'.-]{1,40}|he|she|they|his|her|their)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EN_COMPETITION_GENERIC_RE = re.compile(
    r"\b(?:when\s+i\s+win|if\s+i\s+win|whenever\s+i\s+win|"
    r"tournament\s+friends?|friends?\s+from\s+other\s+tournaments?)\b",
    re.IGNORECASE,
)
_EN_QUERY_PERSON_PATTERNS = (
    re.compile(r"\b(?P<name>[A-Z][A-Za-z'.-]{1,40})'s\b"),
    re.compile(
        r"\b(?:has|did|does|do|is|was|were|are)\s+"
        r"(?P<name>[A-Z][A-Za-z'.-]{1,40})\b"
    ),
)
_EN_QUERY_NAME_STOPWORDS = frozenset({"what", "which", "where", "when", "why", "how"})
_SPEAKER_RE = re.compile(r"\bD\d+:\d+\s+(?P<speaker>[A-Z][A-Za-z'.-]{1,40}):")
_TURN_SOURCE_ORDER_RE = re.compile(r"(?:^|:)session_(\d+):D\d+:(\d+):turn$")
_MARKER_RUN_WITH_SPEAKER_RE = re.compile(
    r"\b(?P<markers>(?:D\d+:\d+\s+){1,8})"
    r"(?P<speaker>(?!D\d+:)[A-Z][A-Za-z'. -]{0,40}:)"
)
_MAX_EXACT_COMPETITION_COUNT_TURNS = 12


def exact_competition_count_turn_candidates(
    items: Iterable[ContextItem],
    *,
    query: str,
    limit: int = _MAX_EXACT_COMPETITION_COUNT_TURNS,
) -> tuple[ContextItem, ...]:
    """Return exact competition turns that directly support count queries."""

    if limit <= 0 or _EN_COMPETITION_COUNT_QUERY_RE.search(query) is None:
        return ()
    ranked_by_source_id: dict[str, tuple[tuple[object, ...], ContextItem]] = {}
    for item in items:
        query_reason = _competition_count_query_reason(item)
        if not _is_competition_count_reason(query_reason):
            continue
        for turn in _focused_competition_count_turns(
            item,
            query_reason=query_reason,
        ):
            rank = competition_count_answer_rank(
                text=turn.text,
                query=query,
                query_reason=query_reason,
                has_exact_turn=True,
            )
            if rank > 1:
                continue
            role_rank = competition_count_role_alignment_rank(
                text=turn.text,
                query=query,
                query_reason=query_reason,
            )
            if role_rank > 1:
                continue
            source_id = _primary_exact_turn_source_id(turn)
            rank_key = (
                role_rank,
                rank,
                0 if len(turn.source_refs) == 1 else 1,
                _turn_source_order_rank(source_id),
                context_rank_key(turn),
            )
            existing = ranked_by_source_id.get(source_id)
            if existing is None or rank_key < existing[0]:
                ranked_by_source_id[source_id] = (rank_key, turn)
    return tuple(
        item for _, item in sorted(ranked_by_source_id.values(), key=lambda value: value[0])
    )[:limit]


def competition_count_answer_rank(
    *,
    text: str,
    query: str,
    query_reason: str,
    has_exact_turn: bool,
) -> int:
    """Rank English competition count evidence by answer shape."""

    if not _is_competition_count_reason(query_reason):
        return 0
    if query and _EN_COMPETITION_COUNT_QUERY_RE.search(query) is None:
        return 0
    if not has_exact_turn or _EN_COMPETITION_OBJECT_RE.search(text) is None:
        return 6
    if _EN_COMPETITION_GENERIC_RE.search(text) is not None:
        return 6
    has_win = _EN_COMPETITION_WIN_EVENT_RE.search(text) is not None
    has_participation = _EN_COMPETITION_PARTICIPATION_EVENT_RE.search(text) is not None
    win_query = _EN_COMPETITION_WIN_QUERY_RE.search(query) is not None
    participation_query = _EN_COMPETITION_PARTICIPATION_QUERY_RE.search(query) is not None
    if win_query:
        return 0 if has_win else 6
    if participation_query:
        if has_win or has_participation:
            return 0
        return 6
    if has_win:
        return 0
    if has_participation:
        return 1
    return 6


def competition_count_role_alignment_rank(
    *,
    text: str,
    query: str,
    query_reason: str,
) -> int:
    if not _is_competition_count_reason(query_reason):
        return 0
    query_person = _query_subject_name(query)
    if not query_person:
        return 0
    speakers = _speaker_names(text)
    if not speakers:
        return 1
    return 0 if query_person in speakers else 3


def _focused_competition_count_turns(
    item: ContextItem,
    *,
    query_reason: str,
) -> tuple[ContextItem, ...]:
    focused: list[ContextItem] = []
    for ref in _exact_turn_refs(item):
        focused_text = _focused_turn_text(text=item.text, source_id=str(ref.source_id))
        if not focused_text:
            continue
        if (
            len(item.source_refs) == 1
            and str(item.source_refs[0].source_id) == str(ref.source_id)
            and focused_text == item.text
        ):
            focused.append(item)
            continue
        focused.append(
            replace(
                item,
                item_id=(
                    f"{item.item_id}:competition_count_exact:"
                    f"{_safe_source_id_suffix(str(ref.source_id))}"
                ),
                text=focused_text,
                source_refs=(ref,),
                diagnostics=_competition_count_exact_turn_diagnostics(
                    item,
                    query_reason=query_reason,
                ),
            )
        )
    return tuple(focused)


def _is_competition_count_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") in _EN_COMPETITION_COUNT_REASONS


def _competition_count_query_reason(item: ContextItem) -> str:
    query_reason = (
        _diagnostic_signal_text(item, "query_expansion_reason")
        or _diagnostic_signal_text(item, "bm25_lexical_query_reason")
        or _diagnostic_signal_text(item, "deterministic_rerank_query_reason")
    )
    diagnostics = item.diagnostics or {}
    score_signals = diagnostics.get("score_signals")
    if isinstance(score_signals, dict) and _signal_truthy(
        score_signals.get("source_sibling_answer_evidence")
    ) and query_reason.replace("_", "-") in {"", "original-query"}:
        return "source_sibling_answer_evidence"
    if query_reason:
        return query_reason
    return ""


def _signal_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return str(value).strip().casefold() in {"true", "yes"}


def _exact_turn_refs(item: ContextItem) -> tuple[SourceRef, ...]:
    return tuple(
        ref for ref in item.source_refs if str(ref.source_id).casefold().endswith(":turn")
    )


def _primary_exact_turn_source_id(item: ContextItem) -> str:
    for ref in item.source_refs:
        source_id = str(ref.source_id)
        if source_id.casefold().endswith(":turn"):
            return source_id
    return ""


def _focused_turn_text(*, text: str, source_id: str) -> str:
    span = _focused_turn_span(text=text, source_id=source_id)
    if span is None:
        return ""
    start, end = span
    return text[start:end].strip()


def _focused_turn_span(*, text: str, source_id: str) -> tuple[int, int] | None:
    marker_match = _DIALOGUE_MARKER_RE.search(source_id)
    if marker_match is None:
        return (0, len(text)) if text else None
    marker = marker_match.group(0)
    marker_run_span = _marker_run_speaker_segment_span(text=text, marker=marker)
    if marker_run_span is not None:
        return marker_run_span
    matches = tuple(re.finditer(rf"\b{re.escape(marker)}\b", text))
    if not matches:
        return (0, len(text)) if text and _DIALOGUE_MARKER_RE.search(text) is None else None
    text_match = matches[0]
    for match in matches:
        following = text[match.end() : match.end() + 48]
        if re.match(r"\s+(?!D\d+:)[A-Z][A-Za-z'. -]{0,40}:", following):
            text_match = match
            break
    next_match = _DIALOGUE_MARKER_RE.search(text[text_match.end() :])
    end = text_match.end() + next_match.start() if next_match is not None else len(text)
    return (text_match.start(), end)


def _marker_run_speaker_segment_span(*, text: str, marker: str) -> tuple[int, int] | None:
    for match in _MARKER_RUN_WITH_SPEAKER_RE.finditer(text):
        markers = frozenset(_DIALOGUE_MARKER_RE.findall(match.group("markers")))
        if marker not in markers:
            continue
        next_match = _DIALOGUE_MARKER_RE.search(text[match.end() :])
        end = match.end() + next_match.start() if next_match is not None else len(text)
        return (match.start(), end)
    return None


def _query_subject_name(query: str) -> str:
    for pattern in _EN_QUERY_PERSON_PATTERNS:
        match = pattern.search(query)
        if match is None:
            continue
        name = match.group("name").casefold()
        if name not in _EN_QUERY_NAME_STOPWORDS:
            return name
    return ""


def _speaker_names(text: str) -> frozenset[str]:
    return frozenset(match.group("speaker").casefold() for match in _SPEAKER_RE.finditer(text))


def _turn_source_order_rank(source_id: str) -> tuple[int, int]:
    match = _TURN_SOURCE_ORDER_RE.search(source_id)
    if match is None:
        return (999_999, 999_999)
    return (int(match.group(1)), int(match.group(2)))


def _safe_source_id_suffix(source_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", source_id).strip("_").casefold()


def _competition_count_exact_turn_diagnostics(
    item: ContextItem,
    *,
    query_reason: str,
) -> dict[str, object]:
    diagnostics = dict(item.diagnostics or {})
    score_signals = diagnostics.get("score_signals")
    score_signal_dict = dict(score_signals) if isinstance(score_signals, dict) else {}
    score_signal_dict["query_expansion_reason"] = query_reason
    score_signal_dict["competition_count_exact_turn"] = 1
    diagnostics["score_signals"] = score_signal_dict
    return diagnostics
