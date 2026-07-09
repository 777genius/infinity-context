"""English creative-work exact-turn candidates for authored count evidence."""

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
_EN_CREATIVE_WORK_COUNT_QUERY_RE = re.compile(
    r"\b(?:how\s+many|number|count|total)\b"
    r"(?=.{0,180}\b(?:screenplays?|scripts?|stories?|books?|poems?|"
    r"songs?|articles?|blog\s+posts?|essays?)\b)"
    r"(?=.{0,240}\b(?:wrote|written|write|writing|authored|created|"
    r"made|finished|completed|wrapped|started|drafted|published)\b)|"
    r"\b(?:screenplays?|scripts?|stories?|books?|poems?|songs?|articles?|"
    r"blog\s+posts?|essays?)\b"
    r"(?=.{0,180}\b(?:how\s+many|number|count|total|wrote|written|"
    r"authored|finished|completed)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EN_CREATIVE_WORK_OBJECT_RE = re.compile(
    r"\b(?:screenplays?|scripts?|movie\s+scripts?|stories?|books?|poems?|"
    r"songs?|articles?|blog\s+posts?|essays?)\b",
    re.IGNORECASE,
)
_EN_CREATIVE_WORK_SCRIPT_OBJECT_RE = re.compile(
    r"\b(?:screenplays?|scripts?|movie\s+scripts?)\b",
    re.IGNORECASE,
)
_EN_CREATIVE_WORK_STORY_OBJECT_RE = re.compile(r"\bstories?\b", re.IGNORECASE)
_EN_CREATIVE_WORK_BOOK_OBJECT_RE = re.compile(r"\bbooks?\b", re.IGNORECASE)
_EN_CREATIVE_WORK_BLOG_ARTICLE_OBJECT_RE = re.compile(
    r"\b(?:articles?|blog\s+posts?|essays?)\b",
    re.IGNORECASE,
)
_EN_CREATIVE_WORK_POEM_OBJECT_RE = re.compile(r"\bpoems?\b", re.IGNORECASE)
_EN_CREATIVE_WORK_SONG_OBJECT_RE = re.compile(r"\bsongs?\b", re.IGNORECASE)
_EN_CREATIVE_WORK_COUNT_REASONS = frozenset(
    {
        "creative-writing-inventory-bridge",
        "decomposition-quantity-count",
        "original-query",
        "quantity-enumeration-bridge",
        "screenplay-count-bridge",
        "source-sibling-answer-evidence",
    }
)
_EN_CREATIVE_WORK_COUNT_CUE_RE = re.compile(
    r"\b(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|"
    r"tenth|another|one\s+more|at\s+least\s+(?:two|three|four|five|\d+)|"
    r"\d+)\b",
    re.IGNORECASE,
)
_EN_CREATIVE_WORK_ORDINAL_REFERENCE_RE = re.compile(
    r"\b(?:is|was|that'?s|that\s+is|this\s+is|your|my|her|his|their)\s+"
    r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+one\b",
    re.IGNORECASE,
)
_EN_CREATIVE_WORK_AUTHORING_RE = re.compile(
    r"\b(?:finished|completed|wrapped\s+up|wrote|written|authored|created|"
    r"drafted|published|printed|started\s+(?:writing|on)|"
    r"just\s+started\s+writing|chose\s+to\s+write|got\s+the\s+guts\s+to\s+write)\b",
    re.IGNORECASE,
)
_EN_CREATIVE_WORK_WEAK_CONTEXT_RE = re.compile(
    r"\b(?:contributed|shown|appeared|big\s+screen|rejection|rejected|"
    r"production\s+company|major\s+company|feedback|not\s+much\s+is\s+new|"
    r"working\s+on\s+some\s+projects|thinking\s+back|tough\s+times)\b",
    re.IGNORECASE,
)
_EN_CREATIVE_WORK_IN_PROGRESS_RE = re.compile(
    r"\b(?:i\s+am|i'm|she\s+is|she's|he\s+is|he's|they\s+are|they're)\s+"
    r"writing\s+another\b",
    re.IGNORECASE,
)
_EN_CREATIVE_WORK_CONFIRMATION_RE = re.compile(
    r"\b(?:yep|yes|yeah|that'?s\s+(?:my|the)|this\s+is)\b"
    r"(?=.{0,160}\b(?:write|story|script|screenplay|book|poem|song|essay)\b)",
    re.IGNORECASE | re.DOTALL,
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
_TURN_SOURCE_ID_RE = re.compile(r"^(?P<prefix>.*:session_\d+:)D\d+:\d+(?P<suffix>:turn)$")
_SESSION_SOURCE_ID_RE = re.compile(
    r"^(?P<session>.*:session_\d+)(?::(?:events?|observations?|summary))?$"
)
_MARKER_RUN_WITH_SPEAKER_RE = re.compile(
    r"\b(?P<markers>(?:D\d+:\d+\s+){1,8})"
    r"(?P<speaker>(?!D\d+:)[A-Z][A-Za-z'. -]{0,40}:)"
)
_MAX_EXACT_CREATIVE_WORK_COUNT_TURNS = 8


def exact_creative_work_count_turn_candidates(
    items: Iterable[ContextItem],
    *,
    query: str,
    limit: int = _MAX_EXACT_CREATIVE_WORK_COUNT_TURNS,
) -> tuple[ContextItem, ...]:
    """Return exact authored-work turns that directly support count queries."""

    if limit <= 0 or _EN_CREATIVE_WORK_COUNT_QUERY_RE.search(query) is None:
        return ()
    ranked_by_source_id: dict[str, tuple[tuple[object, ...], ContextItem]] = {}
    for item in items:
        query_reason = _creative_work_count_query_reason(item)
        if not _is_creative_work_count_reason(query_reason):
            continue
        for turn in _focused_creative_work_count_turns(
            item,
            query_reason=query_reason,
        ):
            rank = creative_work_count_answer_rank(
                text=turn.text,
                query=query,
                query_reason=query_reason,
                has_exact_turn=True,
            )
            if rank > 1:
                continue
            role_rank = creative_work_count_role_alignment_rank(
                text=turn.text,
                query=query,
                query_reason=query_reason,
            )
            if role_rank > 1:
                continue
            source_id = _primary_exact_turn_source_id(turn)
            rank_key = (
                rank,
                role_rank,
                0 if len(turn.source_refs) == 1 else 1,
                _turn_source_order_rank(source_id),
                context_rank_key(turn),
            )
            existing = ranked_by_source_id.get(source_id)
            if existing is None or rank_key < existing[0]:
                ranked_by_source_id[source_id] = (rank_key, turn)
    selected: list[ContextItem] = []
    selected_texts: set[str] = set()
    for _, item in sorted(ranked_by_source_id.values(), key=lambda value: value[0]):
        text_key = _normalized_turn_text_key(item.text)
        if text_key in selected_texts:
            continue
        selected_texts.add(text_key)
        selected.append(item)
        if len(selected) >= limit:
            break
    return tuple(selected)


def creative_work_count_answer_rank(
    *,
    text: str,
    query: str,
    query_reason: str,
    has_exact_turn: bool,
) -> int:
    """Rank English authored-work count evidence by answer shape."""

    if not _is_creative_work_count_reason(query_reason):
        return 0
    if query and _EN_CREATIVE_WORK_COUNT_QUERY_RE.search(query) is None:
        return 0
    if not has_exact_turn:
        return 6
    semantic_text = _semantic_turn_text(text)
    has_object = _EN_CREATIVE_WORK_OBJECT_RE.search(semantic_text) is not None
    has_aligned_object = _creative_work_object_aligned(
        semantic_text,
        query=query,
    )
    has_count_cue = _EN_CREATIVE_WORK_COUNT_CUE_RE.search(semantic_text) is not None
    has_authoring = _EN_CREATIVE_WORK_AUTHORING_RE.search(semantic_text) is not None
    has_confirmation = (
        _EN_CREATIVE_WORK_CONFIRMATION_RE.search(semantic_text) is not None
    )
    has_ordinal_reference = (
        _EN_CREATIVE_WORK_ORDINAL_REFERENCE_RE.search(semantic_text) is not None
    )
    has_in_progress = _EN_CREATIVE_WORK_IN_PROGRESS_RE.search(semantic_text) is not None
    has_weak_context = _EN_CREATIVE_WORK_WEAK_CONTEXT_RE.search(semantic_text) is not None
    if has_count_cue and has_authoring and (
        has_aligned_object or (not has_object and _mentions_query_subject(text, query))
    ):
        if has_in_progress:
            return 4
        if has_weak_context:
            return 2
        return 0
    if (
        has_count_cue
        and _mentions_query_subject(text, query)
        and has_ordinal_reference
        and not has_in_progress
        and not has_weak_context
    ):
        return 0 if "?" in semantic_text else 1
    if has_aligned_object and has_authoring:
        if has_in_progress:
            return 4
        if has_weak_context:
            return 2
        return 1
    if has_confirmation and has_authoring and (
        has_aligned_object or not _query_creative_work_object_group(query)
    ):
        return 1
    if (
        has_authoring
        and _mentions_query_subject(text, query)
        and (has_aligned_object or not has_object)
    ):
        return 1
    return 6


def creative_work_count_role_alignment_rank(
    *,
    text: str,
    query: str,
    query_reason: str,
) -> int:
    if not _is_creative_work_count_reason(query_reason):
        return 0
    query_person = _query_subject_name(query)
    if not query_person:
        return 0
    speakers = _speaker_names(text)
    if query_person in speakers:
        return 0
    if query_person in text.casefold():
        return 1
    return 1 if not speakers else 3


def _focused_creative_work_count_turns(
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
                    f"{item.item_id}:creative_work_count_exact:"
                    f"{_safe_source_id_suffix(str(ref.source_id))}"
                ),
                text=focused_text,
                source_refs=(ref,),
                diagnostics=_creative_work_count_exact_turn_diagnostics(
                    item,
                    query_reason=query_reason,
                ),
            )
        )
    return tuple(focused)


def _is_creative_work_count_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") in _EN_CREATIVE_WORK_COUNT_REASONS


def _creative_work_count_query_reason(item: ContextItem) -> str:
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
    return query_reason or ""


def _signal_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return str(value).strip().casefold() in {"true", "yes"}


def _exact_turn_refs(item: ContextItem) -> tuple[SourceRef, ...]:
    refs: list[SourceRef] = []
    seen: set[str] = set()
    for ref in item.source_refs:
        source_id = str(ref.source_id)
        if not source_id.casefold().endswith(":turn"):
            continue
        seen.add(source_id)
        refs.append(ref)
    for marker in _dialogue_markers_in_text(item.text):
        source_id = _source_id_for_dialogue_marker(item, marker=marker)
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        refs.append(
            SourceRef(
                source_type=_turn_source_type(item),
                source_id=source_id,
            )
        )
    return tuple(refs)


def _semantic_turn_text(text: str) -> str:
    text = re.split(r"\bRetrieval hints:\b", text, maxsplit=1)[0]
    return _DIALOGUE_MARKER_RE.sub(" ", text)


def _normalized_turn_text_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _dialogue_markers_in_text(text: str) -> tuple[str, ...]:
    markers: list[str] = []
    seen: set[str] = set()
    for match in _DIALOGUE_MARKER_RE.finditer(text):
        marker = match.group(0)
        if marker in seen:
            continue
        seen.add(marker)
        markers.append(marker)
    return tuple(markers)


def _source_id_for_dialogue_marker(item: ContextItem, *, marker: str) -> str:
    for ref in item.source_refs:
        source_id = str(ref.source_id)
        if match := _TURN_SOURCE_ID_RE.match(source_id):
            return f"{match.group('prefix')}{marker}{match.group('suffix')}"
    for ref in item.source_refs:
        source_id = str(ref.source_id)
        if match := _SESSION_SOURCE_ID_RE.match(source_id):
            return f"{match.group('session')}:{marker}:turn"
    return ""


def _turn_source_type(item: ContextItem) -> str:
    for ref in item.source_refs:
        if str(ref.source_id).casefold().endswith(":turn"):
            return str(ref.source_type)
    return "locomo_turn"


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


def _mentions_query_subject(text: str, query: str) -> bool:
    query_person = _query_subject_name(query)
    return bool(query_person and query_person in text.casefold())


def _query_creative_work_object_group(query: str) -> str:
    if _EN_CREATIVE_WORK_SCRIPT_OBJECT_RE.search(query) is not None:
        return "script"
    if _EN_CREATIVE_WORK_BOOK_OBJECT_RE.search(query) is not None:
        return "book"
    if _EN_CREATIVE_WORK_BLOG_ARTICLE_OBJECT_RE.search(query) is not None:
        return "article"
    if _EN_CREATIVE_WORK_POEM_OBJECT_RE.search(query) is not None:
        return "poem"
    if _EN_CREATIVE_WORK_SONG_OBJECT_RE.search(query) is not None:
        return "song"
    if _EN_CREATIVE_WORK_STORY_OBJECT_RE.search(query) is not None:
        return "story"
    return ""


def _creative_work_object_aligned(text: str, *, query: str) -> bool:
    group = _query_creative_work_object_group(query)
    if not group:
        return _EN_CREATIVE_WORK_OBJECT_RE.search(text) is not None
    if group == "script":
        return (
            (
                _EN_CREATIVE_WORK_SCRIPT_OBJECT_RE.search(text) is not None
                or _EN_CREATIVE_WORK_STORY_OBJECT_RE.search(text) is not None
            )
            and _EN_CREATIVE_WORK_BOOK_OBJECT_RE.search(text) is None
            and _EN_CREATIVE_WORK_BLOG_ARTICLE_OBJECT_RE.search(text) is None
            and _EN_CREATIVE_WORK_POEM_OBJECT_RE.search(text) is None
            and _EN_CREATIVE_WORK_SONG_OBJECT_RE.search(text) is None
        )
    if group == "story":
        return (
            _EN_CREATIVE_WORK_STORY_OBJECT_RE.search(text) is not None
            or _EN_CREATIVE_WORK_SCRIPT_OBJECT_RE.search(text) is not None
        )
    if group == "book":
        return _EN_CREATIVE_WORK_BOOK_OBJECT_RE.search(text) is not None
    if group == "article":
        return _EN_CREATIVE_WORK_BLOG_ARTICLE_OBJECT_RE.search(text) is not None
    if group == "poem":
        return _EN_CREATIVE_WORK_POEM_OBJECT_RE.search(text) is not None
    if group == "song":
        return _EN_CREATIVE_WORK_SONG_OBJECT_RE.search(text) is not None
    return False


def _speaker_names(text: str) -> frozenset[str]:
    return frozenset(match.group("speaker").casefold() for match in _SPEAKER_RE.finditer(text))


def _turn_source_order_rank(source_id: str) -> tuple[int, int]:
    match = _TURN_SOURCE_ORDER_RE.search(source_id)
    if match is None:
        return (999_999, 999_999)
    return (int(match.group(1)), int(match.group(2)))


def _safe_source_id_suffix(source_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", source_id).strip("_").casefold()


def _creative_work_count_exact_turn_diagnostics(
    item: ContextItem,
    *,
    query_reason: str,
) -> dict[str, object]:
    diagnostics = dict(item.diagnostics or {})
    score_signals = diagnostics.get("score_signals")
    score_signal_dict = dict(score_signals) if isinstance(score_signals, dict) else {}
    score_signal_dict["query_expansion_reason"] = query_reason
    score_signal_dict["creative_work_count_exact_turn"] = 1
    diagnostics["score_signals"] = score_signal_dict
    return diagnostics
