"""English food/recipe exact-turn candidates for inventory answer support."""

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
_EN_FOOD_INVENTORY_QUERY_RE = re.compile(
    r"\b(?:desserts?|recipes?|foods?|dishes?|meals?|sweet\s+treats?|"
    r"flavou?rs?|favorites?|favourites?|made|make|baked|cooked|prepared)\b",
    re.IGNORECASE,
)
_EN_FOOD_SHARING_QUERY_RE = re.compile(
    r"\b(?:share|shared|sharing|teach|teaching|taught|distribut(?:e|ed|ing)|"
    r"disburs(?:e|ed|ing)|spread|send|sent|give|gave)\b"
    r"(?=.{0,180}\b(?:recipes?|foods?|dishes?|desserts?|ice\s*cream|icecream)\b)|"
    r"\b(?:recipes?|foods?|dishes?|desserts?|ice\s*cream|icecream)\b"
    r"(?=.{0,180}\b(?:share|shared|sharing|teach|teaching|taught|"
    r"distribut(?:e|ed|ing)|disburs(?:e|ed|ing)|spread|send|sent|give|gave)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EN_FOOD_INVENTORY_REASONS = frozenset(
    {
        "decomposition-inventory-list",
        "food-recipe-recommendation-bridge",
        "original-query",
        "source-sibling-answer-evidence",
    }
)
_EN_FOOD_MADE_QUERY_RE = re.compile(
    r"\b(?:made|make|makes|baked|bake|cooked|prepared|whipped|"
    r"recipes?\s+(?:has|have|did|does)|what\s+recipes?)\b",
    re.IGNORECASE,
)
_EN_FOOD_CONCRETE_OBJECT_RE = re.compile(
    r"\b(?:desserts?|sweet\s+treats?|ice\s*cream|icecream|cakes?|mousse|"
    r"tarts?|pies?|cobblers?|sundaes?|cookies?|brownies?|puddings?|"
    r"pastr(?:y|ies)|treats?|chocolate|berries|berry|coconut\s+milk|"
    r"coconut\s+cream|dairy[-\s]?free|almond\s+milk|vanilla|caramel|"
    r"flavou?rs?)\b",
    re.IGNORECASE,
)
_EN_FOOD_SPECIFIC_OBJECT_RE = re.compile(
    r"\b(?:ice\s*cream|icecream|cakes?|mousse|tarts?|pies?|cobblers?|"
    r"sundaes?|cookies?|brownies?|puddings?|pastr(?:y|ies)|treats?|chocolate|"
    r"berries|berry|coconut\s+milk|coconut\s+cream|almond\s+milk|"
    r"vanilla|caramel)\b",
    re.IGNORECASE,
)
_EN_FOOD_DIRECT_PREP_RE = re.compile(
    r"\b(?:i|we)\b"
    r"(?=.{0,180}\b(?:made|make|baked|bake|whipped|cooked|prepared|"
    r"discovered|tried|trying|gave\s+it\s+a\s+try|testing|tested|"
    r"working\s+on|revis(?:e|ed|ing))\b)"
    r"(?=.{0,240}\b(?:desserts?|recipes?|sweet\s+treats?|ice\s*cream|"
    r"icecream|cakes?|mousse|tarts?|pies?|cobblers?|sundaes?|cookies?|"
    r"brownies?|chocolate|berries|berry|coconut\s+milk|dairy[-\s]?free|"
    r"flavou?rs?)\b)|"
    r"\b(?:made|baked|whipped|cooked|prepared|discovered|testing|tested|"
    r"working\s+on|revis(?:e|ed|ing))\b"
    r"(?=.{0,220}\b(?:desserts?|recipes?|sweet\s+treats?|ice\s*cream|"
    r"icecream|cakes?|mousse|tarts?|pies?|cobblers?|sundaes?|cookies?|"
    r"brownies?|chocolate|berries|berry|coconut\s+milk|dairy[-\s]?free|"
    r"flavou?rs?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EN_FOOD_SELF_SPECIFIC_PREP_RE = re.compile(
    r"\b(?:i|we|my|our)\b"
    r"(?=.{0,180}\b(?:made|make|baked|bake|whipped|cooked|prepared|"
    r"discovered|tried|trying|gave\s+it\s+a\s+try|testing|tested|"
    r"working\s+on|revis(?:e|ed|ing))\b)"
    r"(?=.{0,220}\b(?:ice\s*cream|icecream|cakes?|mousse|tarts?|pies?|"
    r"cobblers?|sundaes?|cookies?|brownies?|chocolate|berries|berry|"
    r"coconut\s+milk|vanilla|caramel)\b)|"
    r"\b(?:made|make|baked|whipped|cooked|prepared|discovered|tried|"
    r"gave\s+it\s+a\s+try|testing|tested|working\s+on|revis(?:e|ed|ing))\b"
    r"(?=.{0,120}\b(?:ice\s*cream|icecream|cakes?|mousse|tarts?|pies?|"
    r"cobblers?|sundaes?|cookies?|brownies?|chocolate|berries|berry|"
    r"coconut\s+milk|vanilla|caramel)\b)"
    r"(?=.{0,220}\b(?:i|we|my|our)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EN_FOOD_FIRST_PERSON_PREP_ACTION_RE = re.compile(
    r"\b(?:i|we)(?:'ve|'m| am| have| had| just| recently| also| even)?\s+"
    r"(?:[\w'-]+\s+){0,3}?"
    r"(?:made|make|baked|bake|whipped|cooked|prepared|discovered|tried|"
    r"trying|testing|tested|revis(?:e|ed|ing)|working\s+on)\b",
    re.IGNORECASE,
)
_EN_FOOD_DIRECT_PREFERENCE_RE = re.compile(
    r"\b(?:i|we)\b"
    r"(?=.{0,140}\b(?:favorites?|favourites?|love|loved|like|liked|"
    r"enjoy|enjoyed|prefer|preferred)\b)"
    r"(?=.{0,220}\b(?:desserts?|sweet\s+treats?|flavou?rs?|ice\s*cream|"
    r"icecream|cakes?|mousse|tarts?|pies?|cobblers?|sundaes?|cookies?|"
    r"brownies?|chocolate|berries|berry|coconut\s+milk|dairy[-\s]?free|"
    r"vanilla|caramel)\b)|"
    r"\b(?:favorites?|favourites?|love|loved|like|liked|enjoy|enjoyed|"
    r"prefer|preferred)\b"
    r"(?=.{0,180}\b(?:desserts?|sweet\s+treats?|flavou?rs?|ice\s*cream|"
    r"icecream|cakes?|mousse|tarts?|pies?|cobblers?|sundaes?|cookies?|"
    r"brownies?|chocolate|berries|berry|coconut\s+milk|dairy[-\s]?free|"
    r"vanilla|caramel)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EN_FOOD_SELF_SPECIFIC_PREFERENCE_RE = re.compile(
    r"\b(?:i|we|my|mine|our)\b"
    r"(?=.{0,160}\b(?:favorites?|favourites?|love|loved|like|liked|"
    r"enjoy|enjoyed|prefer|preferred)\b)"
    r"(?=.{0,220}\b(?:ice\s*cream|icecream|cakes?|mousse|tarts?|pies?|"
    r"cobblers?|sundaes?|cookies?|brownies?|chocolate|berries|berry|"
    r"coconut\s+milk|vanilla|caramel)\b)|"
    r"\b(?:favorites?|favourites?|love|loved|like|liked|enjoy|enjoyed|"
    r"prefer|preferred)\b"
    r"(?=.{0,180}\b(?:ice\s*cream|icecream|cakes?|mousse|tarts?|pies?|"
    r"cobblers?|sundaes?|cookies?|brownies?|chocolate|berries|berry|"
    r"coconut\s+milk|vanilla|caramel)\b)"
    r"(?=.{0,220}\b(?:i|we|my|mine|our)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EN_FOOD_FUTURE_OR_OFFER_RE = re.compile(
    r"\b(?:looking\s+forward|would\s+love|want\s+to|wanna|going\s+to|"
    r"planning\s+to|interested\s+in\s+trying|want\s+to\s+try|wanna\s+try|"
    r"going\s+to\s+try|let\s+me\s+know|want\s+me\s+to|would\s+you|could\s+you)\b",
    re.IGNORECASE,
)
_EN_FOOD_HYPOTHETICAL_PREP_RE = re.compile(
    r"\b(?:wish\s+(?:i|we)\s+could|if\s+(?:i|we)\s+could|"
    r"(?:i|we)\s+wish\s+(?:i|we)\s+could)\b",
    re.IGNORECASE,
)
_EN_FOOD_SELF_SHARING_RE = re.compile(
    r"\b(?:i|we|my|our)\b"
    r"(?=.{0,180}\b(?:teach|teaching|taught|share|sharing|shared|"
    r"distribut(?:e|ed|ing)|spread|send|sent|give|gave)\b)"
    r"(?=.{0,240}\b(?:recipes?|desserts?|sweet\s+treats?|ice\s*cream|"
    r"icecream|dairy[-\s]?free|coconut\s+milk|how\s+to\s+make|make\s+this)\b)|"
    r"\b(?:teach|teaching|taught|share|sharing|shared|distribut(?:e|ed|ing)|"
    r"spread|send|sent|give|gave)\b"
    r"(?=.{0,180}\b(?:recipes?|desserts?|sweet\s+treats?|ice\s*cream|"
    r"icecream|dairy[-\s]?free|coconut\s+milk|how\s+to\s+make|make\s+this)\b)"
    r"(?=.{0,220}\b(?:i|we|my|our)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EN_FOOD_ADDRESSEE_PREP_RE = re.compile(
    r"\b(?:you|your)\b"
    r"(?=.{0,180}\b(?:make|made|bake|baked|cook|cooked|prepare|prepared|"
    r"whip|whipped|recipe|recipes|desserts?|ice\s*cream|icecream|cakes?)\b)|"
    r"\b(?:make|made|bake|baked|cook|cooked|prepare|prepared|whip|whipped|"
    r"recipe|recipes|desserts?|ice\s*cream|icecream|cakes?)\b"
    r"(?=.{0,180}\b(?:you|your)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EN_FOOD_PROMPT_RE = re.compile(
    r"\b(?:got\s+any|do\s+you\s+have|what(?:'s| is| are)?\s+your|"
    r"what(?:'s| is)?\s+been\s+your|any\s+(?:more\s+)?|want\s+me\s+to|"
    r"should\s+i|could\s+you|would\s+you)\b"
    r"(?=.{0,180}\b(?:favorites?|favourites?|favs?|desserts?|recipes?|"
    r"sweet\s+treats?|flavou?rs?|ice\s*cream|icecream|cakes?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EN_FOOD_SETUP_PROMPT_RE = re.compile(
    r"\b(?:making|baking|cooking|made|make|bake|cook)\s+"
    r"(?:anything|something|anything\s+cool|something\s+cool|anything\s+yummy)\b|"
    r"\b(?:anything|something)\s+(?:cool|yummy)\b",
    re.IGNORECASE,
)
_EN_FOOD_RECIPE_DETAIL_RE = re.compile(
    r"\b(?:it'?s|it\s+is|it\s+has|this\s+(?:is|has)|made\s+with|with)\b"
    r"(?=.{0,220}\b(?:dairy[-\s]?free|vanilla|strawberry|strawberries|"
    r"filling|frosting|coconut\s+cream|coconut\s+milk|almond\s+flour|"
    r"gluten[-\s]?free|crust|ganache|raspberries|blueberries|chocolate)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EN_FOOD_SELF_EVIDENCE_RE = re.compile(r"\b(?:i|we|my|mine|our)\b", re.IGNORECASE)
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
_MAX_EXACT_FOOD_INVENTORY_TURNS = 12


def exact_food_inventory_turn_candidates(
    items: Iterable[ContextItem],
    *,
    query: str,
    limit: int = _MAX_EXACT_FOOD_INVENTORY_TURNS,
) -> tuple[ContextItem, ...]:
    """Return exact food/recipe turns that directly answer inventory queries."""

    if limit <= 0 or _EN_FOOD_INVENTORY_QUERY_RE.search(query) is None:
        return ()
    ranked_by_source_id: dict[str, tuple[tuple[object, ...], ContextItem]] = {}
    for item in items:
        query_reason = _food_inventory_query_reason(item)
        if not _is_food_inventory_reason(query_reason):
            continue
        for turn in _focused_food_inventory_turns(item, query_reason=query_reason):
            answer_rank = food_inventory_answer_support_rank(
                text=turn.text,
                query=query,
                query_reason=query_reason,
                has_exact_turn=True,
            )
            if answer_rank > 1:
                continue
            role_rank = food_inventory_role_alignment_rank(
                text=turn.text,
                query=query,
                query_reason=query_reason,
            )
            if role_rank > 1:
                continue
            source_id = _primary_exact_turn_source_id(turn)
            rank_key = (
                role_rank,
                answer_rank,
                0 if len(turn.source_refs) == 1 else 1,
                _turn_source_order_rank(source_id, query=query),
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


def food_inventory_answer_support_rank(
    *,
    text: str,
    query: str,
    query_reason: str,
    has_exact_turn: bool,
) -> int:
    """Rank English food/recipe answer evidence for inventory-list queries."""

    if not _is_food_inventory_reason(query_reason):
        return 0
    if query and _EN_FOOD_INVENTORY_QUERY_RE.search(query) is None:
        return 0
    has_direct = (
        _EN_FOOD_DIRECT_PREP_RE.search(text) is not None
        or _EN_FOOD_DIRECT_PREFERENCE_RE.search(text) is not None
    )
    if _is_prompt_only_food_turn(text, has_direct=has_direct):
        return 6
    has_concrete_object = _EN_FOOD_CONCRETE_OBJECT_RE.search(text) is not None
    made_query = _EN_FOOD_MADE_QUERY_RE.search(query) is not None
    if (
        made_query
        and has_exact_turn
        and _EN_FOOD_SETUP_PROMPT_RE.search(text) is not None
    ):
        return 0
    if made_query and _EN_FOOD_HYPOTHETICAL_PREP_RE.search(text) is not None:
        return 6
    if made_query and _EN_FOOD_FUTURE_OR_OFFER_RE.search(text) is not None:
        return 5
    if (
        made_query
        and _EN_FOOD_ADDRESSEE_PREP_RE.search(text) is not None
        and _EN_FOOD_FIRST_PERSON_PREP_ACTION_RE.search(text) is None
    ):
        return 6
    has_self_specific_answer = (
        _EN_FOOD_SELF_SPECIFIC_PREP_RE.search(text) is not None
        or _EN_FOOD_SELF_SPECIFIC_PREFERENCE_RE.search(text) is not None
    )
    sharing_query = _EN_FOOD_SHARING_QUERY_RE.search(query) is not None
    if sharing_query:
        if has_exact_turn and _EN_FOOD_SELF_SHARING_RE.search(text) is not None:
            return 0
        if has_exact_turn and has_direct:
            return 3
        return 6
    if has_exact_turn and has_self_specific_answer:
        return 0
    if (
        made_query
        and has_exact_turn
        and _EN_FOOD_RECIPE_DETAIL_RE.search(text) is not None
        and has_concrete_object
    ):
        return 1
    if _EN_FOOD_FUTURE_OR_OFFER_RE.search(text) is not None:
        return 4
    if has_exact_turn and has_direct and _EN_FOOD_SPECIFIC_OBJECT_RE.search(text) is not None:
        return 1
    if has_exact_turn and has_direct:
        return 2
    if has_direct and has_concrete_object:
        return 3
    if has_concrete_object:
        return 4
    return 6


def food_inventory_answer_support_applies(
    *,
    query: str,
    query_reason: str,
) -> bool:
    """Return true when English food/recipe ranking should influence ordering."""

    return (
        bool(query)
        and _EN_FOOD_INVENTORY_QUERY_RE.search(query) is not None
        and _is_food_inventory_reason(query_reason)
    )


def food_inventory_role_alignment_rank(
    *,
    text: str,
    query: str,
    query_reason: str,
) -> int:
    if not _is_food_inventory_reason(query_reason):
        return 0
    query_person = _query_subject_name(query)
    if not query_person:
        return 0
    speakers = _speaker_names(text)
    if not speakers:
        return 1
    return 0 if query_person in speakers else 3


def _focused_food_inventory_turns(
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
                    f"{item.item_id}:food_inventory_exact:"
                    f"{_safe_source_id_suffix(str(ref.source_id))}"
                ),
                text=focused_text,
                source_refs=(ref,),
                diagnostics=_food_inventory_exact_turn_diagnostics(
                    item,
                    query_reason=query_reason,
                ),
            )
        )
    return tuple(focused)


def _is_prompt_only_food_turn(text: str, *, has_direct: bool) -> bool:
    if _EN_FOOD_PROMPT_RE.search(text) is None:
        return False
    return not (has_direct and _EN_FOOD_SELF_EVIDENCE_RE.search(text) is not None)


def _is_food_inventory_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") in _EN_FOOD_INVENTORY_REASONS


def _food_inventory_query_reason(item: ContextItem) -> str:
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


def _speaker_names(text: str) -> frozenset[str]:
    return frozenset(match.group("speaker").casefold() for match in _SPEAKER_RE.finditer(text))


def _turn_source_order_rank(source_id: str, *, query: str) -> tuple[int, int]:
    if re.search(
        r"\b(?:current|currently|latest|last|newest|recent|recently|now|today)\b",
        query,
        re.IGNORECASE,
    ):
        return (999_999, 999_999)
    match = _TURN_SOURCE_ORDER_RE.search(source_id)
    if match is None:
        return (999_999, 999_999)
    return (int(match.group(1)), int(match.group(2)))


def _safe_source_id_suffix(source_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", source_id).strip("_").casefold()


def _food_inventory_exact_turn_diagnostics(
    item: ContextItem,
    *,
    query_reason: str,
) -> dict[str, object]:
    diagnostics = dict(item.diagnostics or {})
    score_signals = diagnostics.get("score_signals")
    score_signal_dict = dict(score_signals) if isinstance(score_signals, dict) else {}
    score_signal_dict["query_expansion_reason"] = query_reason
    score_signal_dict["food_inventory_exact_turn"] = 1
    diagnostics["score_signals"] = score_signal_dict
    return diagnostics
