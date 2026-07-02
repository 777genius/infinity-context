"""Exact source-sibling answer-evidence repair helpers."""

from __future__ import annotations

import re
from dataclasses import replace

from infinity_context_core.application.context_activity_duration_rerank import (
    is_activity_duration_evidence_text,
)
from infinity_context_core.application.context_diagnostics import (
    context_rank_key,
    diagnostic_retrieval_sources,
)
from infinity_context_core.application.context_english_lifestyle_inference import (
    english_lifestyle_answer_support_rank,
    english_lifestyle_query_kind,
)
from infinity_context_core.application.context_english_temporal_dates import (
    english_textual_month_year_terms,
)
from infinity_context_core.application.context_packer_inventory_slots import (
    _game_inventory_answer_directness_rank,
)
from infinity_context_core.application.context_recommendation_answer_support import (
    recommendation_list_answer_kind,
    recommendation_list_answer_support_rank,
)
from infinity_context_core.application.context_source_sibling_place_evidence import (
    country_destination_answer_support_rank,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef

_MAX_EXACT_SOURCE_SIBLING_ANSWER_EVIDENCE_REPAIRS = 48
_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_DIALOGUE_MARKER_ONLY_RE = re.compile(r"^(?:D\d+:\d+[\s,;.]*)+$")


def _provenance(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("provenance")
    return dict(value) if isinstance(value, dict) else {}


def _numeric_score_signal(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _restore_exact_source_sibling_answer_evidence_items(
    *,
    candidates: tuple[ContextItem, ...],
    source_items: tuple[ContextItem, ...],
) -> tuple[tuple[ContextItem, ...], dict[str, object]]:
    existing_repair_keys = {
        _exact_source_sibling_answer_evidence_repair_key(item)
        for item in candidates
    }
    existing_exact_source_ids = _exact_turn_source_ids_with_body(candidates)
    repaired_keys: set[tuple[str, str, tuple[str, ...]]] = set()
    repaired_source_ids: set[str] = set()
    repairs: list[ContextItem] = []
    considered = 0
    skipped_existing = 0
    for item in sorted(source_items, key=_exact_source_sibling_answer_evidence_repair_item_key):
        if not (
            _is_exact_source_sibling_answer_evidence_item(item)
            or _is_exact_source_sibling_marker_coverage_item(item)
        ):
            continue
        for ref in sorted(
            _exact_source_sibling_answer_evidence_repair_refs(item),
            key=lambda source_ref: _exact_source_sibling_answer_evidence_repair_ref_key(
                item=item,
                source_id=str(source_ref.source_id),
            ),
        ):
            source_id = str(ref.source_id)
            if not source_id.casefold().endswith(":turn"):
                continue
            considered += 1
            repair_key = (item.item_type, item.item_id, (source_id,))
            if (
                source_id in existing_exact_source_ids
                or source_id in repaired_source_ids
                or repair_key in existing_repair_keys
                or repair_key in repaired_keys
            ):
                skipped_existing += 1
                continue
            repair_item = item
            if len(item.source_refs) != 1 or str(item.source_refs[0].source_id) != source_id:
                repair_text = _exact_source_repair_text(item, source_id=source_id)
                repair_priority = _exact_source_sibling_answer_evidence_repair_marker_priority(
                    item=item,
                    source_id=source_id,
                )
                repair_item = replace(
                    item,
                    item_id=(
                        f"{item.item_id}:exact_source:"
                        f"{_exact_source_repair_item_id_suffix(source_id)}"
                    ),
                    text=repair_text,
                    source_refs=(ref,),
                    diagnostics=_exact_source_repair_diagnostics(
                        item,
                        repair_priority=repair_priority,
                    ),
                )
            repairs.append(repair_item)
            repaired_keys.add(repair_key)
            repaired_source_ids.add(source_id)
            if len(repairs) >= _MAX_EXACT_SOURCE_SIBLING_ANSWER_EVIDENCE_REPAIRS:
                break
        if len(repairs) >= _MAX_EXACT_SOURCE_SIBLING_ANSWER_EVIDENCE_REPAIRS:
            break
    diagnostics = {
        "exact_source_sibling_answer_evidence_repair_candidates": considered,
        "exact_source_sibling_answer_evidence_repair_existing": skipped_existing,
        "exact_source_sibling_answer_evidence_repair_added": len(repairs),
    }
    if not repairs:
        return candidates, diagnostics
    return tuple(sorted((*candidates, *repairs), key=context_rank_key)), diagnostics


def _exact_turn_source_ids_with_body(items: tuple[ContextItem, ...]) -> frozenset[str]:
    source_ids: set[str] = set()
    for item in items:
        for ref in item.source_refs:
            source_id = str(ref.source_id or "")
            if not source_id.casefold().endswith(":turn"):
                continue
            marker = _source_ref_dialogue_marker(ref)
            if marker and _dialogue_turn_marker_text_match(text=item.text, marker=marker):
                source_ids.add(source_id)
    return frozenset(source_ids)


def _exact_source_sibling_answer_evidence_repair_key(
    item: ContextItem,
) -> tuple[str, str, tuple[str, ...]]:
    return (
        item.item_type,
        item.item_id,
        tuple(str(ref.source_id) for ref in item.source_refs),
    )

_PET_ACQUISITION_EXACT_REPAIR_DATE_ANCHOR_RE = re.compile(
    r"\b(?:session_\d+\s+date|date:\s+)",
    re.IGNORECASE | re.DOTALL,
)
_PET_ACQUISITION_EXACT_REPAIR_OBJECT_RE = re.compile(
    r"\b(?:"
    r"adopt(?:ed|ing)?|"
    r"(?:got|get|getting)\s+(?:a\s+|the\s+|this\s+|that\s+|another\s+)?"
    r"(?:new\s+)?(?:pet|dog|puppy|pup|stuffed\s+animal|toy\s+(?:dog|pup))|"
    r"new\s+addition|new\s+pup|puppy|pup|"
    r"gift\s+from|named|stuffed\s+animal|toy\s+(?:dog|pup)"
    r")\b",
    re.IGNORECASE,
)
_EXACT_REPAIR_PET_ADJUSTMENT_RE = re.compile(
    r"\b(?:puppy|pup|dog|little\s+one|pet)\b"
    r"(?=.{0,220}\b(?:doing\s+great|adjust(?:ing|ed)?|"
    r"learning\s+commands?|house\s+training|training|trained|new\s+home)\b)|"
    r"\b(?:doing\s+great|learning\s+commands?|house\s+training|"
    r"adjust(?:ing|ed)?|training|trained)\b"
    r"(?=.{0,220}\b(?:puppy|pup|dog|little\s+one|pet|image\s+caption|"
    r"visual\s+query)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_INFERENCE_NAMED_PREFERENCE_RE = re.compile(
    r"\b(?:favorite|favourite|fav(?:orite)?|love|loves|liked?|enjoys?|fan\s+of)\b"
    r"(?=.{0,180}\b(?:movie|film|book|series|show|game|music|fantasy|"
    r"fiction|places?|locations?|world|universe)\b)|"
    r"\b(?:movie|film|book|series|show|game|music|fantasy|fiction|world|"
    r"universe)\b(?=.{0,180}\b(?:favorite|favourite|fav(?:orite)?|love|"
    r"loves|liked?|enjoys?|fan\s+of)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_INFERENCE_DESTINATION_ANCHOR_RE = re.compile(
    r"\b(?:study\s+abroad|semester|accepted\s+(?:into|to)|applied\s+for|"
    r"off\s+to|going\s+to|headed\s+to|visit(?:ed|ing)?|travel(?:ed|led|ing)?|"
    r"trip|stay(?:ed|ing)?|live\s+in|living\s+in|moved\s+to)\b",
    re.IGNORECASE,
)
_EXACT_REPAIR_INFERENCE_THEMED_LOCATION_RE = re.compile(
    r"\b(?:place|places|locations?|tour|trip|visit(?:ed|ing)?|went)\b"
    r"(?=.{0,260}\b(?:movie|film|book|fantasy|fiction|universe|world|"
    r"real\s+\w+\s+places?)\b)"
    r"(?=.{0,260}\b(?:amazing|love|loved|enjoy|enjoyed|like|liked|"
    r"explore|explored|visit|visited|walking\s+into)\b)|"
    r"\b(?:movie|film|book|fantasy|fiction|universe|world|"
    r"real\s+\w+\s+places?)\b"
    r"(?=.{0,260}\b(?:place|places|locations?|tour|trip|visit(?:ed|ing)?|went)\b)"
    r"(?=.{0,260}\b(?:amazing|love|loved|enjoy|enjoyed|like|liked|"
    r"explore|explored|visit|visited|walking\s+into)\b)",
    re.IGNORECASE | re.DOTALL,
)


def _exact_source_sibling_answer_evidence_repair_item_key(
    item: ContextItem,
) -> tuple[float | int | str, ...]:
    return (
        _exact_source_sibling_answer_evidence_repair_item_priority(item),
        context_rank_key(item),
    )


def _exact_source_sibling_answer_evidence_repair_item_priority(item: ContextItem) -> int:
    if _is_pet_acquisition_exact_repair_scope(item):
        return _pet_acquisition_exact_repair_text_priority(item.text)
    country_destination_rank = _country_destination_exact_repair_rank(
        text=item.text,
        query=_exact_source_repair_query_text(item),
    )
    if country_destination_rank < 5:
        return country_destination_rank
    lifestyle_rank = _english_lifestyle_exact_repair_rank(
        text=item.text,
        query=_exact_source_repair_query_text(item),
    )
    if lifestyle_rank < 5:
        return lifestyle_rank
    reason = _exact_source_repair_query_reason(item)
    if reason in _EXACT_REPAIR_RECOMMENDATION_REASONS:
        return recommendation_list_answer_support_rank(
            text=item.text,
            query_reason=reason,
        )
    return 1


def _exact_source_sibling_answer_evidence_repair_ref_key(
    *,
    item: ContextItem,
    source_id: str,
) -> tuple[int, str]:
    if _is_pet_acquisition_exact_repair_scope(item):
        marker_match = re.search(r"\bD\d+:\d+\b", source_id)
        if marker_match is None or re.search(
            rf"\b{re.escape(marker_match.group(0))}\b",
            item.text,
        ) is None:
            return (1, source_id)
        return (
            _exact_source_sibling_answer_evidence_repair_marker_priority(
                item=item,
                source_id=source_id,
            ),
            source_id,
        )
    country_destination_rank = _country_destination_exact_repair_rank(
        text=_focused_exact_source_repair_text(text=item.text, source_id=source_id),
        query=_exact_source_repair_query_text(item),
    )
    if country_destination_rank < 5:
        return (country_destination_rank, source_id)
    lifestyle_rank = _english_lifestyle_exact_ref_repair_rank(
        item_text=item.text,
        source_id=source_id,
        query=_exact_source_repair_query_text(item),
    )
    if lifestyle_rank < 5:
        return (lifestyle_rank, source_id)
    return (1, source_id)


def _is_pet_acquisition_exact_repair_scope(item: ContextItem) -> bool:
    diagnostics = item.diagnostics or {}
    query_reason = str(diagnostics.get("query_expansion_reason") or "")
    if query_reason == "pet_acquisition_date_bridge":
        return True
    score_signals = diagnostics.get("score_signals")
    if not isinstance(score_signals, dict):
        return False
    return str(score_signals.get("query_expansion_reason") or "") == (
        "pet_acquisition_date_bridge"
    )


def _exact_source_repair_item_id_suffix(source_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", source_id).strip("_")[:160] or "turn"


def _exact_source_repair_text(item: ContextItem, *, source_id: str) -> str:
    focused = _focused_exact_source_repair_text(text=item.text, source_id=source_id)
    query = _exact_source_repair_query_text(item)
    if (
        _country_destination_exact_repair_rank(text=item.text, query=query) == 0
        and 0 < _country_destination_exact_repair_rank(text=focused, query=query) < 5
    ):
        temporal_line = _matching_month_year_context_line(text=item.text, query=query)
        if temporal_line and temporal_line not in focused:
            return f"{temporal_line}\n{focused}"
    return focused


def _matching_month_year_context_line(*, text: str, query: str) -> str:
    query_terms = set(english_textual_month_year_terms(query))
    if not query_terms:
        return ""
    for line in text.splitlines():
        clean = line.strip()
        if not clean:
            continue
        if query_terms.intersection(english_textual_month_year_terms(clean)):
            return clean[:220]
    return ""


def _exact_source_sibling_answer_evidence_repair_refs(
    item: ContextItem,
) -> tuple[SourceRef, ...]:
    refs = list(item.source_refs)
    if not _is_pet_acquisition_exact_repair_scope(item):
        return _filtered_exact_source_sibling_answer_evidence_repair_refs(item, refs=refs)
    marker_priorities = _pet_acquisition_exact_repair_marker_priorities(item)
    if not marker_priorities:
        return ()
    markers = tuple(marker_priorities)
    selected_refs = [
        ref
        for ref in refs
        if _source_ref_dialogue_marker(ref) in markers
    ]
    existing_source_ids = {str(ref.source_id) for ref in selected_refs}
    template_refs = tuple(selected_refs) or tuple(
        ref for ref in refs if re.search(r"\bD\d+:\d+:turn$", str(ref.source_id)) is not None
    )
    if not template_refs:
        return tuple(selected_refs)
    for marker in markers:
        for template_ref in template_refs:
            template_source_id = str(template_ref.source_id)
            marker_match = re.search(r"\bD\d+:\d+(?=:turn$)", template_source_id)
            if marker_match is None:
                continue
            derived_source_id = (
                f"{template_source_id[: marker_match.start()]}"
                f"{marker}"
                f"{template_source_id[marker_match.end():]}"
            )
            if derived_source_id in existing_source_ids:
                continue
            existing_source_ids.add(derived_source_id)
            selected_refs.append(
                replace(
                    template_ref,
                    source_id=derived_source_id,
                )
            )
            break
    return tuple(selected_refs)


_EXACT_REPAIR_ANIMAL_CARE_RE = re.compile(
    r"\b(?:keep(?:ing)?\s+(?:their|the)?\s*(?:area|tank|space|habitat)\s+clean|"
    r"clean\s+(?:area|tank|space|habitat)|feed(?:ing)?\s+(?:them\s+)?properly|"
    r"enough\s+light|care\s+instructions?|kind\s+of\s+fun)\b",
    re.IGNORECASE,
)
_EXACT_REPAIR_ANIMAL_DIET_RE = re.compile(
    r"\b(?:"
    r"(?:eat|eats|ate|diet|food|feed(?:ing)?)\b(?=.{0,120}\b"
    r"(?:vegetables?|fruits?|insects?|greens?|varied\s+diet|turtles?|reptiles?)\b)|"
    r"(?:vegetables?|fruits?|insects?|greens?|varied\s+diet)\b(?=.{0,120}\b"
    r"(?:eat|eats|ate|diet|food|feed(?:ing)?|turtles?|reptiles?)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_ANIMAL_HABITAT_RE = re.compile(
    r"\b(?:new|bigger|large|larger|upgrade(?:d)?)\s+(?:tank|habitat|enclosure)\b|"
    r"\b(?:tank|habitat|enclosure)\b(?=.{0,100}\b(?:new|bigger|large|larger|upgrade))",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_ANIMAL_AFFINITY_RE = re.compile(
    r"\b(?:pet\s+store|bring(?:s)?\s+me\s+(?:joy|peace)|"
    r"joy\s+and\s+peace|best\s+buddies|love\s+most\s+about\s+having)\b",
    re.IGNORECASE,
)
_EXACT_REPAIR_ANIMAL_ACTIVITY_RE = re.compile(
    r"\b(?:feed(?:ing)?|eat(?:ing)?|fruit|strawberries|snacks?|hold(?:ing)?|"
    r"bath|bathe|bathing|walk(?:s|ed|ing)?)\b"
    r"(?=.{0,180}\b(?:turtles?|pets?|animals?|reptiles?)\b)|"
    r"\b(?:turtles?|pets?|animals?|reptiles?)\b"
    r"(?=.{0,180}\b(?:feed(?:ing)?|eat(?:ing)?|fruit|strawberries|snacks?|"
    r"hold(?:ing)?|bath|bathe|bathing|walk(?:s|ed|ing)?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_SUPPORT_ORIGIN_RE = re.compile(
    r"\b(?:support|love|acceptance)\b"
    r"(?=.{0,180}\b(?:journey|pass\s+it\s+on|supportive\s+community|"
    r"hope|understanding|acceptance)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_SUPPORT_CAREER_MOTIVATION_RE = re.compile(
    r"\b(?:made\s+a\s+huge\s+difference|made\s+.*\bdifference|"
    r"counseling\s+and\s+support\s+groups|support\s+groups\s+improved|"
    r"improved\s+my\s+life|now\s+i\s+want\s+to\s+help|"
    r"safe,\s*inviting\s+place)\b",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_CHARITY_BRAND_SPONSORSHIP_RE = re.compile(
    r"\b(?:signed(?:\s+up)?|secure(?:d|s)?|landed|in\s+talks?\s+with|"
    r"sponsor(?:ship|ed|s)?|endorse(?:ment|d|s)?|partner(?:ship|ed|s)?)\b"
    r"(?=.{0,240}\b(?:brand|brands?|company|companies|organization|"
    r"organisations?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?|deal|deals?|"
    r"gear|shoe|shoes|apparel|equipment)\b)|"
    r"\b(?:got|gets?|have|has|had)\b"
    r"(?=.{0,140}\b(?:sponsor(?:ship|s)?|endorse(?:ment|d|s)?|"
    r"partner(?:ship|ed|s)?|deal|deals?)\b)|"
    r"\b(?:always\s+liked|liked|likes|i\s+like|we\s+like|they\s+like|"
    r"he\s+likes|she\s+likes|love|loves|fan\s+of|admire|admires|"
    r"favorite|favourite|dream(?:ed)?)\b"
    r"(?=.{0,180}\b(?:working\s+with\s+(?:them|it)|work\s+with\s+(?:them|it)|"
    r"partner(?:ship|ed|s)?|brand|brands?|company|companies|organization|"
    r"organisations?|deal|deals?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?)\b)|"
    r"\b(?:working\s+with\s+(?:them|it)|work\s+with\s+(?:them|it))\b"
    r"(?=.{0,180}\b(?:cool|great|exciting|stoked|like|liked|likes|love|"
    r"fan|dream|brand|brands?|company|companies|organization|organisations?|"
    r"deal|deals?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?)\b)|"
    r"\b(?:charity|nonprofit|non-profit|foundation|organization|organisation|"
    r"program|initiative)\b"
    r"(?=.{0,220}\b(?:kids?|children|youth|students?|disadvantaged|"
    r"underserved|community|sports?|school|education|help|support|give\s+back|"
    r"make\s+(?:a\s+)?difference)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_CLASSICAL_MUSIC_PREFERENCE_RE = re.compile(
    r"\b(?:fan|enjoys?|likes?|loves?|favorite|favourite|fav(?:orite)?|into)\b"
    r"(?=.{0,180}\b(?:classical|bach|mozart|vivaldi|orchestra|symphony|"
    r"composer|tunes?|songs?|music)\b)|"
    r"\b(?:classical|bach|mozart|vivaldi|orchestra|symphony|composer)\b"
    r"(?=.{0,180}\b(?:fan|enjoys?|likes?|loves?|favorite|favourite|"
    r"fav(?:orite)?|tunes?|songs?|music)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_SENTIMENTAL_REMINDER_RE = re.compile(
    r"\b(?:reminds?|reminder|sentimental\s+value|symboli[sz](?:es|ed)?|"
    r"meaning|means|stands?\s+for)\b(?=.{0,220}\b(?:art|self[-\s]?expression|"
    r"friend|birthday|gift|memory|pattern|colou?rs?|childhood|love|faith|"
    r"strength|roots?|family|keepsake)\b)|"
    r"\b(?:sentimental\s+value|hand[-\s]?painted|keepsake|gift|birthday|"
    r"pattern|colou?rs?)\b(?=.{0,220}\b(?:reminds?|reminder|symbol|meaning|"
    r"self[-\s]?expression)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_COLLECTIBLE_OBJECT_RE = re.compile(
    r"\b(?:signed|autographed|autograph)\b"
    r"(?=.{0,220}\b(?:balls?|basketballs?|jerseys?|photos?|pictures?|cards?|"
    r"posters?|keepsakes?|mementos?|gifts?|presents?|possessions?|"
    r"collectibles?|memorabilia|teammates?|friends?|favorite\s+player)\b)|"
    r"\b(?:prized\s+possession|keepsakes?|mementos?|collectibles?|memorabilia|"
    r"gifts?|presents?)\b"
    r"(?=.{0,220}\b(?:signed|autographed|autograph|balls?|basketballs?|"
    r"jerseys?|photos?|pictures?|reminds?|reminder|bond|friendship|"
    r"appreciation|teammates?|favorite\s+player)\b)|"
    r"\b(?:reminds?|reminder)\b"
    r"(?=.{0,220}\b(?:bond|friendship|appreciation|teammates?|team\s+spirit|"
    r"friends?|signed|autographed|balls?|basketballs?|keepsakes?|mementos?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_OUTDOOR_PREFERENCE_RE = re.compile(
    r"\b(?:look\s+forward|highlight|always\s+remember|favorite|favourite|"
    r"best\s+memory|love|enjoy|special|amazing)\b(?=.{0,240}\b(?:camping|"
    r"campfire|marshmallows?|meteor\s+shower|stars?|sky|universe|nature|"
    r"outdoors?|hikes?|hiking|trail|park)\b)|"
    r"\b(?:camping|campfire|marshmallows?|meteor\s+shower|stars?|sky|universe|"
    r"nature|outdoors?|hikes?|hiking|trail|park)\b(?=.{0,240}\b(?:look\s+forward|"
    r"highlight|always\s+remember|favorite|favourite|best\s+memory|love|enjoy|"
    r"special|amazing|at\s+one\s+with)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_CHILDREN_PREFERENCE_RE = re.compile(
    r"\b(?:kids?|children|child|sons?|daughters?|younger\s+kids?)\b"
    r"(?=.{0,220}\b(?:likes?|loves?|enjoys?|favorite|favourite|stoked|"
    r"excited|blast|into)\b)"
    r"(?=.{0,260}\b(?:dinosaurs?|exhibit|museum|animals?|bones?|nature|"
    r"outdoors?|hikes?|hiking|camping|campfire|marshmallows?|books?|stories|"
    r"learning|pottery|clay|painting|creative|creativity)\b)|"
    r"\b(?:they|them)\b(?=.{0,140}\b(?:were\s+)?(?:stoked|excited)\b)"
    r"(?=.{0,220}\b(?:dinosaurs?|exhibit|museum|animals?|bones?|nature|"
    r"outdoors?|hikes?|hiking|camping|books?|stories|learning)\b)|"
    r"\b(?:they|them)\b(?=.{0,180}\b(?:likes?|loves?|enjoys?|favorite|"
    r"favourite)\b)"
    r"(?=.{0,220}\b(?:dinosaurs?|exhibit|museum|animals?|bones?|nature|"
    r"outdoors?|hikes?|hiking|camping|books?|stories|learning)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_CHILDHOOD_POSSESSION_RE = re.compile(
    r"(?=.*\b(?:childhood|as\s+a\s+kid|as\s+a\s+child|when\s+i\s+was\s+"
    r"(?:a\s+)?kid|when\s+i\s+was\s+(?:a\s+)?child)\b)"
    r"(?=.*\b(?:had|owned|used\s+to\s+have|reminds?\s+me\s+of)\b)"
    r"(?=.*\b(?:dolls?|cameras?|film\s+cameras?|toys?|books?|bikes?|"
    r"bicycles?|keepsakes?|mementos?|stuffed\s+animals?|photos?|pictures?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_VOLUNTEERING_PEOPLE_RE = re.compile(
    r"\b(?:someone|person)\s+named\s+[A-Z][a-z]+\b|"
    r"\bmet\s+(?:this\s+)?(?:amazing\s+)?(?:woman|man|person),\s+[A-Z][a-z]+\b|"
    r"\bresidents?\b(?=.{0,180}\b(?:shelter|letter|wrote|gratitude|"
    r"appreciation|support\s+they\s+receive|heartfelt)\b)|"
    r"\b(?:letter|wrote|gratitude|appreciation|heartfelt)\b"
    r"(?=.{0,180}\b(?:residents?|shelter|support\s+they\s+receive|impact)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_ACTIVITY_PARTICIPATION_RE = re.compile(
    r"\b(?:danc(?:e|ing)|dance\s+studio)\b(?=.{0,220}\b(?:destress|"
    r"de-stress|stress\s+(?:relief|fix)|escape|go-to|"
    r"worries\s+vanish|clear\s+my\s+mind))|"
    r"\b(?:dancers?|dance|festival|perform(?:ing|ance)?|stage)\b"
    r"(?=.{0,240}\b(?:photo|picture|image\s+caption|visual\s+query|"
    r"grace|graceful|skill|practic(?:e|ed|ing)|impress|part\s+of\s+it|"
    r"glad|awesome|excited|memories|grand\s+opening)\b)|"
    r"\b(?:glad\s+to\s+be\s+part\s+of\s+it|part\s+of\s+it)\b|"
    r"\b(?:signed\s+up\s+for|joined|started|went|go(?:ing)?|off\s+to\s+go|"
    r"took|did|finished|made|painted|pottery\s+class|workshop|"
    r"visual\s+query:\s*painting|image\s+caption:.{0,120}\bpainting)\b"
    r"(?=.{0,240}\b(?:pottery|class|camp(?:ing|ed)?|swimm(?:ing)?|swim|"
    r"painting|painted|sunrise|sunset|lake|hiking|hike|trail|workshop|clay|"
    r"creative|kids?|family|fam)\b)|"
    r"\b(?:shooting\s+guard|season\s+opener|scored\s+\d+|recent\s+game|"
    r"basketball\s+game|surf(?:ing|board)?|waves?)\b"
    r"(?=.{0,220}\b(?:team|game|court|basketball|jerseys?|photo|"
    r"image\s+caption|visual\s+query|surfboard|waves?|beach)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_ACTIVITY_PARTICIPATION_REASONS = frozenset(
    {
        "activity-aggregation-bridge",
        "activity-competition-evidence-bridge",
        "activity-visual-selfcare-bridge",
        "decomposition-activity-participation",
        "destress-activity-bridge",
    }
)
_EXACT_REPAIR_RECOMMENDATION_REASONS = frozenset(
    {
        "decomposition-action-role",
        "decomposition-recommendation-source",
        "recommendation-source-bridge",
    }
)
_EXACT_REPAIR_RECOMMENDATION_SETUP_CONTINUATION_RE = re.compile(
    r"\b(?:any\s+(?:pointers?|recommendations?|suggestions?)|"
    r"do\s+you\s+think|how\s+about|should(?:n't)?\s+i|"
    r"what\s+(?:about|should)|would\s+you|could\s+i)\b",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_RECOMMENDATION_ANAPHORIC_CONTEXT_RE = re.compile(
    r"\brecommend(?:ed|ing|s)?\s+it\b(?!\s+as\b)|"
    r"\brecommend(?:ed|ing|s)?\s+that\b|"
    r"\brecommend(?:ed|ing|s)?\s+this\b(?!\s+\w)|"
    r"\b(?:it|that|this)\b(?=.{0,80}\brecommend(?:ed|ing|s)?\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_SHORT_ANAPHORIC_REPLY_RE = re.compile(
    r"\b(?:yes|yeah|yep|no|nope|right|correct|exactly|definitely|"
    r"absolutely|sure)\b"
    r"(?=.{0,120}\b(?:it|that|this|they|them|these|those|one|ones|"
    r"there|he|she)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_TEXT_MARKER_DERIVATION_REASONS = frozenset(
    {
        "activity-competition-evidence-bridge",
        "decomposition-country-destination",
        "decomposition-activity-duration",
    }
)
_EXACT_REPAIR_EXERCISE_COMPANION_RE = re.compile(
    r"(?=.*\b(?:yoga|class(?:es)?|lesson|practice|workout|exercise|fitness|"
    r"training|kickboxing|taekwondo|boxing|running|hiking|camping)\b)"
    r"(?=.*(?:"
    r"\b(?:with|alongside|together\s+with|joined\s+by|accompanied\s+by)\b"
    r".{0,90}\b(?:(?:my|his|her|their|our|a|an|the)\s+|"
    r"one\s+of\s+(?:my|his|her|their|our)\s+)?"
    r"(?:family|kids?|children|friends?|parents?|partner|spouse|team|group|"
    r"colleagues?|co-?workers?|workmates?|classmates?|teammates?|neighbou?rs?)\b|"
    r"\b(?:(?:my|his|her|their|our)\s+)?"
    r"(?:colleagues?|co-?workers?|workmates?|friends?|classmates?|teammates?|"
    r"neighbou?rs?)\b(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39})?"
    r".{0,90}\binvited\b.{0,120}\b(?:me|him|her|them|us)?\s*(?:to|for)\b|"
    r"\binvited\b.{0,120}\b(?:to|for)\b.{0,160}\bby\s+"
    r"(?:(?:my|his|her|their|our)\s+)?"
    r"(?:colleagues?|co-?workers?|workmates?|friends?|classmates?|teammates?|"
    r"neighbou?rs?)\b"
    r"))",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_EXERCISE_TYPE_RE = re.compile(
    r"\b(?:aerial|kundalini|vinyasa|hatha|ashtanga|bikram|yin|restorative|"
    r"power|hot|prenatal|beginner(?:'s)?)\s+yoga\b|"
    r"\b(?:weight|circuit|strength|agility|speed)\s+training\b|"
    r"\b(?:kickboxing|taekwondo|tae\s+kwon\s+do|boxing)\b",
    re.IGNORECASE,
)
_EXACT_REPAIR_OUTDOOR_ACTIVITY_RE = re.compile(
    r"(?=.*\b(?:hiking|hike|mountaineering|waterfall|outdoors?|picnic)\b)"
    r"(?=.*\b(?:colleagues?|co-?workers?|workmates?|friends?|team|group|"
    r"you\s+and\s+(?:your\s+)?friends?|look\s+like\s+(?:a\s+)?"
    r"(?:great\s+)?team)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_BUSINESS_START_REASON_RE = re.compile(
    r"\b(?:"
    r"(?:start(?:ed|ing)?|open(?:ed|ing)?|launch(?:ed|ing)?)\s+"
    r"(?:(?:a|an|my|his|her|their)\s+)?(?:own\s+)?"
    r"(?:business|store|studio|shop|venture)|"
    r"(?:business|store|studio|shop|venture)\b"
    r"(?=.{0,160}\b(?:passion(?:ate)?|love|loved|share|dream(?:ed)?)\b)|"
    r"(?:passion(?:ate)?|love|loved|blend(?:ed)?\s+(?:my\s+)?love|"
    r"fashion\s+trends|unique\s+pieces|perfect\s+match)\b"
    r"(?=.{0,180}\b(?:start(?:ed|ing)?|open(?:ed|ing)?|launch(?:ed|ing)?|"
    r"business|store|studio|shop|venture|fashion|dance)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_PUBLIC_OFFICE_MOTIVATION_RE = re.compile(
    r"\b(?:run(?:ning|s)?|ran)\s+for\s+office\b"
    r"(?=.{0,240}\b(?:impact|community|politics?|positive\s+changes?|"
    r"better\s+future|rewarding|last\s+run|make\s+(?:a\s+)?difference)\b)|"
    r"\b(?:public\s+office|politics?)\b"
    r"(?=.{0,240}\b(?:impact|community|positive\s+changes?|better\s+future|"
    r"rewarding|run(?:ning)?\s+for\s+office|last\s+run)\b)|"
    r"\b(?:impact|positive\s+changes?|better\s+future|"
    r"make\s+(?:a\s+)?difference|rewarding)\b"
    r"(?=.{0,240}\b(?:politics?|public\s+office|run(?:ning)?\s+for\s+office)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_RECOGNITION_AWARD_RE = re.compile(
    r"\b(?:recognition|awards?|medals?|certificates?|honou?rs?|troph(?:y|ies)|"
    r"prizes?)\b"
    r"(?=.{0,200}\b(?:receive|received|got|given|gave|earned|won)\b)|"
    r"\b(?:receive|received|got|given|gave|earned|won)\b"
    r"(?=.{0,160}\b(?:recognition|awards?|medals?|certificates?|"
    r"honou?rs?|troph(?:y|ies)|prizes?)\b)|"
    r"\b(?:image\s+caption|visual\s+query|photo|picture)\b"
    r"(?=.{0,240}\b(?:certificate|certificates|diploma|diplomas)\b)"
    r"(?=.{0,240}\b(?:completion|completed|degree|graduat(?:e|ed|ion)|"
    r"university|college)\b)|"
    r"\b(?:certificate|certificates|diploma|diplomas)\b"
    r"(?=.{0,240}\b(?:image\s+caption|visual\s+query|photo|picture)\b)"
    r"(?=.{0,240}\b(?:completion|completed|degree|graduat(?:e|ed|ion)|"
    r"university|college)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_PLANNING_TOOL_USE_RE = re.compile(
    r"\b(?:clipboard|notepad|notebook|calendar|planner)\b"
    r"(?=.{0,220}\b(?:use|using|stay\s+organized|organized\s+and\s+motivated|"
    r"sets?\s+goals?|tracks?\s+(?:my\s+)?achievements?|areas?\s+to\s+improve|"
    r"improvement|goal\s+setting|progress)\b)|"
    r"\b(?:stay\s+organized|organized\s+and\s+motivated|sets?\s+goals?|"
    r"tracks?\s+(?:my\s+)?achievements?|areas?\s+to\s+improve|"
    r"goal\s+setting|progress)\b"
    r"(?=.{0,220}\b(?:clipboard|notepad|notebook|calendar|planner|"
    r"image\s+caption|visual\s+query)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_CUSTOMER_EXPERIENCE_RE = re.compile(
    r"\b(?:special\s+experience|customer\s+experience|experience\s+for\s+customers?)\b"
    r"(?=.{0,220}\b(?:welcome|coming\s+back|come\s+back|key|space|"
    r"imagining|cozy|inviting)\b)|"
    r"\b(?:feel\s+welcome|welcome\s+and\s+coming\s+back|coming\s+back|"
    r"come\s+back)\b"
    r"(?=.{0,220}\b(?:customers?|special\s+experience|customer\s+experience|"
    r"space|cozy|inviting)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_GRAND_OPENING_SUPPORT_RE = re.compile(
    r"\b(?:right\s+by\s+your\s+side|live\s+it\s+up|so\s+excited|"
    r"can't\s+wait|cannot\s+wait)\b"
    r"(?=.{0,220}\b(?:tomorrow|grand\s+opening|opening|launch|dance\s+studio|"
    r"memories|image\s+caption|visual\s+query)\b)|"
    r"\b(?:grand\s+opening|opening|launch|dance\s+studio)\b"
    r"(?=.{0,220}\b(?:right\s+by\s+your\s+side|live\s+it\s+up|so\s+excited|"
    r"can't\s+wait|cannot\s+wait)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_TRAVEL_COUNTRY_RE = re.compile(
    r"\b(?:england|spain|france|italy|germany|portugal|ireland|sweden|"
    r"europe|european)\b"
    r"(?=.{0,180}\b(?:trip|travel(?:ed|ing)?|visited|vacation|went|been|"
    r"took\s+(?:a\s+)?(?:solo\s+)?trip|road\s+trip|castle|castles|abroad)\b)|"
    r"\b(?:trip|travel(?:ed|ing)?|visited|vacation|went|been|"
    r"took\s+(?:a\s+)?(?:solo\s+)?trip|road\s+trip|abroad)\b"
    r"(?=.{0,180}\b(?:england|spain|france|italy|germany|portugal|ireland|"
    r"sweden|europe|european)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_COMMON_INTEREST_RE = re.compile(
    r"\b(?:"
    r"watch(?:ing)?\s+movies?|movies?|films?|dramas?|romcoms?|"
    r"(?:watched|seen|saw|watches)\s+[\"'][^\"'\n]{2,90}[\"']|"
    r"sci[-\s]?fi|action\s+movies?|"
    r"video\s+games?.{0,80}\bhobb(?:y|ies)\b|"
    r"hobb(?:y|ies)\b.{0,80}\bvideo\s+games?|"
    r"desserts?|baking|bake(?:d|s|r)?|recipes?|dairy[-\s]?free|"
    r"coconut\s+milk|coconut\s+cream|ice\s*cream|icecream|cakes?|"
    r"cupcakes?|frosting|lactose\s+intolerant|"
    r"testing\s+out\s+.*recipes?|revised\s+(?:one\s+of\s+)?(?:my\s+)?old\s+recipes?|"
    r"turtles?|pets?|animals?|reptiles?|slow\s+pace|low[-\s]?maintenance|"
    r"calming|resilien(?:ce|t)|strength|perseverance|"
    r"motivat(?:e|es|ed|ing|ion)|find\s+that\s+inspiring|"
    r"make\s+me\s+think\s+of"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_SCREENPLAY_REJECTION_RE = re.compile(
    r"\b(?:"
    r"(?:rejection|rejected|declined|turned\s+down)\b"
    r"(?=.{0,180}\b(?:scripts?|screenplays?|production\s+company|"
    r"major\s+company|company|letter|feedback)\b)|"
    r"(?:scripts?|screenplays?|production\s+company|major\s+company|"
    r"company|letter)\b"
    r"(?=.{0,180}\b(?:rejection|rejected|declined|turned\s+down)\b)|"
    r"(?:wrote|writing|written|contributed|scripts?|screenplays?|words?)\b"
    r"(?=.{0,180}\b(?:appeared|shown|made\s+it|came\s+alive|big\s+screen)\b)|"
    r"(?:appeared|shown|made\s+it|came\s+alive|big\s+screen)\b"
    r"(?=.{0,180}\b(?:wrote|writing|written|contributed|scripts?|"
    r"screenplays?|words?)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_CREATIVE_WORK_SUBMISSION_RE = re.compile(
    r"\b(?:"
    r"(?:submit|submitted|submitting|submission)\b"
    r"(?=.{0,180}\b(?:work|project|scripts?|screenplays?|film\s+festivals?|"
    r"festivals?|contests?|competitions?|producers?|directors?)\b)|"
    r"(?:work|project|scripts?|screenplays?)\b"
    r"(?=.{0,180}\b(?:submit|submitted|submitting|submission)\b)"
    r"(?=.{0,220}\b(?:film\s+festivals?|festivals?|contests?|competitions?|"
    r"producers?|directors?)\b)|"
    r"(?:film\s+festivals?|festivals?|contests?|competitions?|producers?|"
    r"directors?)\b"
    r"(?=.{0,180}\b(?:submit|submitted|submitting|submission)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_CREATIVE_WRITING_INVENTORY_RE = re.compile(
    r"\b(?:"
    r"(?:screenplays?|scripts?|books?|journal|online\s+blog\s+posts?|"
    r"blog\s+posts?|writing\s+projects?|stories?)\b"
    r"(?=.{0,180}\b(?:writing|wrote|started|finished|printed|made|"
    r"working|projects?|recently|post)\b)|"
    r"(?:writing|wrote|started|finished|printed|made|working)\b"
    r"(?=.{0,180}\b(?:screenplays?|scripts?|books?|journal|"
    r"online\s+blog\s+posts?|blog\s+posts?|stories?)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_REPAIR_CAUSE_EVENT_RE = re.compile(
    r"\b(?:"
    r"(?:homeless\s+shelter|shelter)\b(?=.{0,220}\b(?:food\s+(?:and\s+)?"
    r"supplies|toy\s+drive|kids?\s+in\s+need|give\s+out|gave\s+out|"
    r"organized|events?|made\s+a\s+real\s+difference)\b)|"
    r"(?:community\s+food\s+drive|food\s+drive|unemployment)\b|"
    r"(?:domestic\s+(?:abuse|violence)|victims?\s+of\s+domestic\s+abuse|"
    r"local\s+organization\s+that\s+helps\s+victims)\b|"
    r"(?:veterans?|military)\b(?=.{0,180}\b(?:charity\s+run|5k|funds?|"
    r"families|petition|march|parade|hospital)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_TRIP_DESTINATION_ANSWER_CONTINUATION_QUESTION_RE = re.compile(
    r"\bwhere\s+(?:did|do|does|was|were|is|are)\b"
    r"(?=.{0,100}\b(?:go|went|travel(?:ed|led)?|trip|visit(?:ed)?|place|that)\b)|"
    r"\b(?:which|what)\s+"
    r"(?:city|cities|country|countries|place|places|location|locations|destinations?)\b",
    re.IGNORECASE | re.DOTALL,
)
_TRIP_DESTINATION_ANSWER_CONTINUATION_REASONS = frozenset(
    {
        "decomposition-inventory-list",
        "original-query",
        "trip-destination-bridge",
    }
)
_EN_VISUAL_REFERENT_ANSWER_CONTINUATION_QUESTION_RE = re.compile(
    r"\b(?:are|is)\s+(?:they|these|those|it|that)\s+"
    r"(?:yours?|from|for|at|in)\b"
    r"(?=.{0,140}\b(?:photo|picture|image|caption|visual|festival|stage|"
    r"show|perform(?:ing|ance)?|dancers?|graceful|competition|contest|"
    r"trophy)\b)|"
    r"\b(?:who|what)\s+(?:are|is)\s+(?:they|these|those|it|that)\b"
    r"(?=.{0,140}\b(?:photo|picture|image|caption|visual|festival|stage|"
    r"show|perform(?:ing|ance)?|dancers?|competition|contest|trophy)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EN_VISUAL_REFERENT_ANSWER_CONTINUATION_REASONS = frozenset(
    {
        "activity-competition-evidence-bridge",
    }
)
_EN_ACTIVITY_DURATION_ANSWER_CONTINUATION_QUESTION_RE = re.compile(
    r"\bhow\s+long\s+(?:have|has|had|do|does|did|are|is|was|were)\b"
    r"(?=.{0,180}\b(?:"
    r"volunteer(?:ed|ing|s)?|work(?:ed|ing|s)?|live(?:d|s|ing)?|"
    r"use(?:d|s|ing)?|play(?:ed|ing|s)?|run(?:ning|s)?|"
    r"practice(?:d|s|ing)?|train(?:ed|s|ing)?|"
    r"art|artist|creating|creat(?:e|ed|ing)|paint(?:ed|ing)?|draw(?:ing)?|"
    r"have|has|had|own(?:ed|s)?|keep(?:s|ing)?|pets?|snakes?|dogs?|cats?|puppy"
    r")\b)",
    re.IGNORECASE | re.DOTALL,
)
_EN_ACTIVITY_DURATION_ANSWER_CONTINUATION_REASONS = frozenset(
    {
        "decomposition-activity-duration",
        "original-query",
    }
)


def _filtered_exact_source_sibling_answer_evidence_repair_refs(
    item: ContextItem,
    *,
    refs: list[SourceRef],
) -> tuple[SourceRef, ...]:
    reason = _exact_source_repair_query_reason(item)
    query = _exact_source_repair_query_text(item)
    if english_lifestyle_query_kind(query):
        lifestyle_refs = tuple(
            ref
            for ref in refs
            if str(ref.source_id).casefold().endswith(":turn")
            and _english_lifestyle_exact_ref_repair_rank(
                item_text=item.text,
                source_id=str(ref.source_id),
                query=query,
            )
            < 5
        )
        return lifestyle_refs
    if len(refs) <= 1 and reason not in _EXACT_REPAIR_TEXT_MARKER_DERIVATION_REASONS:
        return tuple(refs)
    if reason not in {
        "animal-activity-inventory-bridge",
        "animal-affinity-pet-store-bridge",
        "animal-care-instruction-bridge",
        "animal-diet-evidence-bridge",
        "animal-habitat-setup-bridge",
        *_EXACT_REPAIR_ACTIVITY_PARTICIPATION_REASONS,
        "board-game-inventory-bridge",
        "business-start-reason-bridge",
        "cause-event-inventory-bridge",
        "charity-brand-sponsorship-bridge",
        "childhood-possession-inventory-bridge",
        "children-preference-bridge",
        "classical-music-preference-bridge",
        "creative-work-submission-bridge",
        "creative-writing-inventory-bridge",
        "customer-experience-bridge",
        "decomposition-collectible-object",
        "decomposition-country-destination",
        "decomposition-inference-support",
        "decomposition-activity-duration",
        "exercise-activity-inventory-bridge",
        "grand-opening-support-bridge",
        "commonality-interest-bridge",
        "hobby-interest-bridge",
        "outdoor-activity-inventory-bridge",
        "outdoor-nature-memory-bridge",
        "outdoor-preference-bridge",
        "pet-adjustment-bridge",
        "planning-tool-use-bridge",
        "public-office-service-bridge",
        "recognition-award-bridge",
        *_EXACT_REPAIR_RECOMMENDATION_REASONS,
        "screenplay-count-bridge",
        "sentimental-reminder-bridge",
        "support-career-motivation-bridge",
        "support-origin-bridge",
        "themed-location-destination-anchor-bridge",
        "themed-location-destination-bridge",
        "travel-country-inventory-bridge",
        "volunteering-people-inventory-bridge",
    }:
        return tuple(refs)
    selected: list[SourceRef] = []
    selected_source_ids: set[str] = set()
    for ref in refs:
        source_id = str(ref.source_id)
        if not source_id.casefold().endswith(":turn"):
            continue
        focused_text = _focused_exact_source_repair_text(text=item.text, source_id=source_id)
        if _exact_source_repair_focused_text_supported(
            reason=reason,
            text=focused_text,
            query=_exact_source_repair_query_text(item),
        ):
            selected.append(ref)
            selected_source_ids.add(source_id)
    if reason in _EXACT_REPAIR_TEXT_MARKER_DERIVATION_REASONS:
        selected.extend(
            _derived_supported_exact_source_repair_refs(
                item,
                refs=refs,
                reason=reason,
                existing_source_ids=selected_source_ids,
            )
        )
    selected.extend(
        _related_turn_exact_source_repair_refs(
            item,
            refs=refs,
            reason=reason,
            existing_source_ids={
                *(str(ref.source_id) for ref in selected),
                *selected_source_ids,
            },
        )
    )
    return tuple(selected)


def _derived_supported_exact_source_repair_refs(
    item: ContextItem,
    *,
    refs: list[SourceRef],
    reason: str,
    existing_source_ids: set[str],
) -> tuple[SourceRef, ...]:
    template_refs = tuple(
        ref
        for ref in refs
        if str(ref.source_id).casefold().endswith(":turn")
        and _source_ref_dialogue_marker(ref)
    )
    if not template_refs:
        return ()
    derived: list[SourceRef] = []
    seen_source_ids = set(existing_source_ids)
    seen_source_ids.update(str(ref.source_id) for ref in refs)
    for marker in dict.fromkeys(_DIALOGUE_MARKER_RE.findall(item.text)):
        focused_text = _focused_exact_source_repair_text(
            text=item.text,
            source_id=f"synthetic:{marker}:turn",
        )
        if not _exact_source_repair_focused_text_supported(
            reason=reason,
            text=focused_text,
            query=_exact_source_repair_query_text(item),
        ):
            continue
        template_ref = _same_dialogue_marker_template_ref(marker, template_refs)
        if template_ref is None:
            continue
        template_source_id = str(template_ref.source_id)
        template_marker_match = _DIALOGUE_MARKER_RE.search(template_source_id)
        if template_marker_match is None:
            continue
        derived_source_id = (
            f"{template_source_id[: template_marker_match.start()]}"
            f"{marker}"
            f"{template_source_id[template_marker_match.end():]}"
        )
        if derived_source_id in seen_source_ids:
            continue
        seen_source_ids.add(derived_source_id)
        derived.append(replace(template_ref, source_id=derived_source_id))
    return tuple(derived)


def _related_turn_exact_source_repair_refs(
    item: ContextItem,
    *,
    refs: list[SourceRef],
    reason: str,
    existing_source_ids: set[str],
) -> tuple[SourceRef, ...]:
    template_refs = tuple(
        ref
        for ref in refs
        if str(ref.source_id).casefold().endswith(":turn")
        and _source_ref_dialogue_marker(ref)
    )
    if not template_refs:
        return ()
    derived: list[SourceRef] = []
    seen_source_ids = set(existing_source_ids)
    for source_id in tuple(existing_source_ids):
        marker_match = _DIALOGUE_MARKER_RE.search(source_id)
        if marker_match is None:
            continue
        marker = marker_match.group(0)
        focused_text = _focused_exact_source_repair_text(text=item.text, source_id=source_id)
        related_markers = (
            *_related_turn_markers(focused_text),
            *_related_turn_markers(_marker_following_text_window(item.text, marker=marker)),
        )
        for related_marker in dict.fromkeys(related_markers):
            if related_marker == marker:
                continue
            template_ref = _same_dialogue_marker_template_ref(related_marker, template_refs)
            if template_ref is None:
                continue
            template_source_id = str(template_ref.source_id)
            template_marker_match = _DIALOGUE_MARKER_RE.search(template_source_id)
            if template_marker_match is None:
                continue
            derived_source_id = (
                f"{template_source_id[: template_marker_match.start()]}"
                f"{related_marker}"
                f"{template_source_id[template_marker_match.end():]}"
            )
            if (
                reason
                in {
                    "decomposition-activity-duration",
                    "decomposition-country-destination",
                }
                and not _exact_source_repair_focused_text_supported(
                    reason=reason,
                    text=_focused_exact_source_repair_text(
                        text=item.text,
                        source_id=derived_source_id,
                    ),
                    query=_exact_source_repair_query_text(item),
                )
            ):
                continue
            if derived_source_id in seen_source_ids:
                continue
            seen_source_ids.add(derived_source_id)
            derived.append(replace(template_ref, source_id=derived_source_id))
    return tuple(derived)


def _marker_following_text_window(text: str, *, marker: str) -> str:
    match = _DIALOGUE_MARKER_RE.search(marker)
    if match is None:
        return ""
    text_match = re.search(rf"\b{re.escape(match.group(0))}\b", text)
    if text_match is None:
        return ""
    return text[text_match.start() : text_match.end() + 360]


def _related_turn_markers(text: str) -> tuple[str, ...]:
    markers: list[str] = []
    for match in re.finditer(
        r"\brelated\s+turns?:\s*([D\d:,\s]+)",
        text,
        re.IGNORECASE,
    ):
        for marker in _DIALOGUE_MARKER_RE.findall(match.group(1)):
            if marker not in markers:
                markers.append(marker)
    return tuple(markers)


def _same_dialogue_marker_template_ref(
    marker: str,
    template_refs: tuple[SourceRef, ...],
) -> SourceRef | None:
    marker_prefix = marker.split(":", 1)[0]
    for ref in template_refs:
        template_marker = _source_ref_dialogue_marker(ref)
        if template_marker.split(":", 1)[0] == marker_prefix:
            return ref
    return None


def _exact_source_repair_query_reason(item: ContextItem) -> str:
    diagnostics = item.diagnostics or {}
    reason = str(diagnostics.get("query_expansion_reason") or "").replace("_", "-")
    if reason:
        return reason
    score_signals = diagnostics.get("score_signals")
    if isinstance(score_signals, dict):
        return str(score_signals.get("query_expansion_reason") or "").replace("_", "-")
    return ""


def _exact_source_repair_query_text(item: ContextItem) -> str:
    diagnostics = item.diagnostics or {}
    score_signals = diagnostics.get("score_signals")
    if isinstance(score_signals, dict):
        query = str(score_signals.get("source_sibling_answer_evidence_query") or "")
        if query:
            return query
    provenance = diagnostics.get("provenance")
    if isinstance(provenance, dict):
        return str(provenance.get("source_sibling_answer_evidence_query") or "")
    return ""


def _country_destination_exact_repair_rank(*, text: str, query: str) -> int:
    if not query:
        return 5
    return country_destination_answer_support_rank(
        expansion_query=query,
        text=text,
        has_exact_turn=True,
    )


def _exact_source_repair_focused_text_supported(
    *,
    reason: str,
    text: str,
    query: str = "",
) -> bool:
    if _DIALOGUE_MARKER_ONLY_RE.fullmatch(text.strip()) is not None:
        return False
    if reason == "animal-care-instruction-bridge":
        return _EXACT_REPAIR_ANIMAL_CARE_RE.search(text) is not None
    if reason == "animal-diet-evidence-bridge":
        return _EXACT_REPAIR_ANIMAL_DIET_RE.search(text) is not None
    if reason == "animal-habitat-setup-bridge":
        return _EXACT_REPAIR_ANIMAL_HABITAT_RE.search(text) is not None
    if reason == "animal-affinity-pet-store-bridge":
        return _EXACT_REPAIR_ANIMAL_AFFINITY_RE.search(text) is not None
    if reason == "animal-activity-inventory-bridge":
        return _EXACT_REPAIR_ANIMAL_ACTIVITY_RE.search(text) is not None
    if reason == "pet-adjustment-bridge":
        return _EXACT_REPAIR_PET_ADJUSTMENT_RE.search(text) is not None
    if reason == "planning-tool-use-bridge":
        return _EXACT_REPAIR_PLANNING_TOOL_USE_RE.search(text) is not None
    if reason == "customer-experience-bridge":
        return _EXACT_REPAIR_CUSTOMER_EXPERIENCE_RE.search(text) is not None
    if reason == "grand-opening-support-bridge":
        return _EXACT_REPAIR_GRAND_OPENING_SUPPORT_RE.search(text) is not None
    if reason == "support-origin-bridge":
        return _EXACT_REPAIR_SUPPORT_ORIGIN_RE.search(text) is not None
    if reason == "support-career-motivation-bridge":
        return _EXACT_REPAIR_SUPPORT_CAREER_MOTIVATION_RE.search(text) is not None
    if reason == "charity-brand-sponsorship-bridge":
        return _EXACT_REPAIR_CHARITY_BRAND_SPONSORSHIP_RE.search(text) is not None
    if reason == "classical-music-preference-bridge":
        return _EXACT_REPAIR_CLASSICAL_MUSIC_PREFERENCE_RE.search(text) is not None
    if reason == "sentimental-reminder-bridge":
        return _EXACT_REPAIR_SENTIMENTAL_REMINDER_RE.search(text) is not None
    if reason == "decomposition-collectible-object":
        return _EXACT_REPAIR_COLLECTIBLE_OBJECT_RE.search(text) is not None
    if reason in {"outdoor-preference-bridge", "outdoor-nature-memory-bridge"}:
        return _EXACT_REPAIR_OUTDOOR_PREFERENCE_RE.search(text) is not None
    if reason == "children-preference-bridge":
        return _EXACT_REPAIR_CHILDREN_PREFERENCE_RE.search(text) is not None
    if reason == "childhood-possession-inventory-bridge":
        return _EXACT_REPAIR_CHILDHOOD_POSSESSION_RE.search(text) is not None
    if reason == "volunteering-people-inventory-bridge":
        return _EXACT_REPAIR_VOLUNTEERING_PEOPLE_RE.search(text) is not None
    if reason == "outdoor-activity-inventory-bridge":
        return _EXACT_REPAIR_OUTDOOR_ACTIVITY_RE.search(text) is not None
    if reason == "exercise-activity-inventory-bridge":
        return (
            _EXACT_REPAIR_EXERCISE_COMPANION_RE.search(text) is not None
            or _EXACT_REPAIR_EXERCISE_TYPE_RE.search(text) is not None
        )
    if reason == "business-start-reason-bridge":
        return _EXACT_REPAIR_BUSINESS_START_REASON_RE.search(text) is not None
    if reason == "public-office-service-bridge":
        return _EXACT_REPAIR_PUBLIC_OFFICE_MOTIVATION_RE.search(text) is not None
    if reason == "recognition-award-bridge":
        return _EXACT_REPAIR_RECOGNITION_AWARD_RE.search(text) is not None
    if reason == "board-game-inventory-bridge":
        return _game_inventory_answer_directness_rank(text) == 0
    if reason == "travel-country-inventory-bridge":
        return _EXACT_REPAIR_TRAVEL_COUNTRY_RE.search(text) is not None
    if reason == "decomposition-country-destination":
        return _country_destination_exact_repair_rank(text=text, query=query) < 5
    if reason in {"commonality-interest-bridge", "hobby-interest-bridge"}:
        return _EXACT_REPAIR_COMMON_INTEREST_RE.search(text) is not None
    if reason == "screenplay-count-bridge":
        return _EXACT_REPAIR_SCREENPLAY_REJECTION_RE.search(text) is not None
    if reason == "creative-work-submission-bridge":
        return _EXACT_REPAIR_CREATIVE_WORK_SUBMISSION_RE.search(text) is not None
    if reason == "creative-writing-inventory-bridge":
        return _EXACT_REPAIR_CREATIVE_WRITING_INVENTORY_RE.search(text) is not None
    if reason == "cause-event-inventory-bridge":
        return _EXACT_REPAIR_CAUSE_EVENT_RE.search(text) is not None
    if reason == "decomposition-activity-duration":
        return is_activity_duration_evidence_text(text)
    if reason in {
        "decomposition-inference-support",
        "themed-location-destination-anchor-bridge",
        "themed-location-destination-bridge",
    }:
        return (
            _EXACT_REPAIR_INFERENCE_NAMED_PREFERENCE_RE.search(text) is not None
            or _EXACT_REPAIR_INFERENCE_DESTINATION_ANCHOR_RE.search(text) is not None
            or _EXACT_REPAIR_INFERENCE_THEMED_LOCATION_RE.search(text) is not None
        )
    if reason in _EXACT_REPAIR_RECOMMENDATION_REASONS:
        return (
            recommendation_list_answer_support_rank(
                text=text,
                query_reason=reason,
            )
            <= 2
        )
    if reason in _EXACT_REPAIR_ACTIVITY_PARTICIPATION_REASONS:
        return _EXACT_REPAIR_ACTIVITY_PARTICIPATION_RE.search(text) is not None
    return True


def _pet_acquisition_exact_repair_markers(item: ContextItem) -> tuple[str, ...]:
    return tuple(_pet_acquisition_exact_repair_marker_priorities(item))


def _pet_acquisition_exact_repair_marker_priorities(item: ContextItem) -> dict[str, int]:
    priorities: dict[str, int] = {}
    marker_speakers = _dialogue_turn_marker_speakers(item.text)
    ordered_markers = tuple(marker_speakers) or tuple(
        dict.fromkeys(_DIALOGUE_MARKER_RE.findall(item.text))
    )
    for marker in ordered_markers:
        focused_text = _focused_exact_source_repair_text(
            text=item.text,
            source_id=f"synthetic:{marker}:turn",
        )
        priority = _pet_acquisition_exact_repair_text_priority(focused_text)
        if priority > 1:
            continue
        priorities[marker] = min(priority, priorities.get(marker, priority))
        if priority == 1:
            previous_marker = _previous_same_speaker_dialogue_marker(
                ordered_markers=ordered_markers,
                marker_speakers=marker_speakers,
                marker=marker,
            )
            if not previous_marker:
                previous_marker = _previous_dialogue_marker(
                    ordered_markers=ordered_markers,
                    marker=marker,
                )
            if not previous_marker:
                continue
            priorities[previous_marker] = min(0, priorities.get(previous_marker, 0))
    return priorities


def _dialogue_turn_marker_speakers(text: str) -> dict[str, str]:
    speakers: dict[str, str] = {}
    for match in re.finditer(r"\b(D\d+:\d+)\b\s+([A-Z][^:\n]{0,40}):", text):
        marker = match.group(1)
        speaker = match.group(2).strip().casefold()
        if marker and speaker and marker not in speakers:
            speakers[marker] = speaker
    return speakers


def _previous_same_speaker_dialogue_marker(
    *,
    ordered_markers: tuple[str, ...],
    marker_speakers: dict[str, str],
    marker: str,
) -> str:
    speaker = marker_speakers.get(marker)
    if not speaker:
        return ""
    previous_markers = ordered_markers[: ordered_markers.index(marker)]
    for previous_marker in reversed(previous_markers):
        if marker_speakers.get(previous_marker) == speaker:
            return previous_marker
    return ""


def _previous_dialogue_marker(
    *,
    ordered_markers: tuple[str, ...],
    marker: str,
) -> str:
    previous_markers = ordered_markers[: ordered_markers.index(marker)]
    return previous_markers[-1] if previous_markers else ""


def _exact_source_sibling_answer_evidence_repair_marker_priority(
    *,
    item: ContextItem,
    source_id: str,
) -> int:
    marker_match = _DIALOGUE_MARKER_RE.search(source_id)
    if marker_match is None or not _is_pet_acquisition_exact_repair_scope(item):
        return 1
    return _pet_acquisition_exact_repair_marker_priorities(item).get(
        marker_match.group(0),
        2,
    )


def _exact_source_repair_diagnostics(
    item: ContextItem,
    *,
    repair_priority: int,
) -> dict[str, object]:
    diagnostics = dict(item.diagnostics or {})
    score_signals = diagnostics.get("score_signals")
    score_signal_dict = dict(score_signals) if isinstance(score_signals, dict) else {}
    score_signal_dict["exact_source_repair"] = 1
    if repair_priority == 0:
        score_signal_dict["exact_source_repair_date_anchor"] = 1
    diagnostics["score_signals"] = score_signal_dict
    return diagnostics


def _pet_acquisition_exact_repair_text_priority(text: str) -> int:
    if _PET_ACQUISITION_EXACT_REPAIR_DATE_ANCHOR_RE.search(text) is not None:
        return 0
    if _PET_ACQUISITION_EXACT_REPAIR_OBJECT_RE.search(text) is not None:
        return 1
    return 2


def _english_lifestyle_exact_repair_rank(*, text: str, query: str) -> int:
    if not english_lifestyle_query_kind(query):
        return 5
    return english_lifestyle_answer_support_rank(text, query=query)


def _english_lifestyle_exact_ref_repair_rank(
    *,
    item_text: str,
    source_id: str,
    query: str,
) -> int:
    marker_match = _DIALOGUE_MARKER_RE.search(source_id)
    if (
        marker_match is not None
        and re.search(rf"\b{re.escape(marker_match.group(0))}\b", item_text) is None
    ):
        return 5
    return _english_lifestyle_exact_repair_rank(
        text=_focused_exact_source_repair_text(text=item_text, source_id=source_id),
        query=query,
    )


def _source_ref_dialogue_marker(ref: SourceRef) -> str:
    match = _DIALOGUE_MARKER_RE.search(str(ref.source_id))
    return match.group(0) if match is not None else ""


def _focused_exact_source_repair_text(*, text: str, source_id: str) -> str:
    marker_match = re.search(r"\bD\d+:\d+\b", source_id)
    if marker_match is None:
        return text
    marker = marker_match.group(0)
    text_match = _dialogue_turn_marker_text_match(text=text, marker=marker)
    if text_match is None:
        return text
    start = _dialogue_marker_run_start(text=text, marker_start=text_match.start())
    boundary = _next_dialogue_boundary_after_marker_run(
        text=text,
        search_start=text_match.end(),
    )
    end = boundary if boundary is not None else len(text)
    if boundary is not None:
        end = _extend_focus_end_for_related_turn_markers(
            text=text,
            start=start,
            end=end,
        )
    focused = text[start:end].strip()
    return focused or text


def _dialogue_marker_run_start(*, text: str, marker_start: int) -> int:
    start = marker_start
    while True:
        previous_matches = tuple(_DIALOGUE_MARKER_RE.finditer(text[:start]))
        if not previous_matches:
            return start
        previous = previous_matches[-1]
        if text[previous.end() : start].strip():
            return start
        start = previous.start()


def _next_dialogue_boundary_after_marker_run(
    *,
    text: str,
    search_start: int,
) -> int | None:
    position = search_start
    while True:
        next_match = _DIALOGUE_MARKER_RE.search(text[position:])
        if next_match is None:
            return None
        absolute_start = position + next_match.start()
        if (
            not text[position:absolute_start].strip()
            and _marker_has_speaker_colon(
                text=text,
                marker_end=position + next_match.end(),
            )
        ):
            position = position + next_match.end()
            continue
        return absolute_start


def _marker_has_speaker_colon(*, text: str, marker_end: int) -> bool:
    following = text[marker_end : marker_end + 48]
    match = re.match(r"\s+[A-Z][^:\n]{0,40}:", following)
    if match is None:
        return False
    speaker_prefix = following[: match.end()]
    if re.match(r"\s*D\d+:", speaker_prefix) is not None:
        return False
    return _DIALOGUE_MARKER_RE.search(speaker_prefix) is None


def _extend_focus_end_for_related_turn_markers(*, text: str, start: int, end: int) -> int:
    focused_prefix = text[start:end]
    if re.search(r"\brelated\s+turns?:\s*$", focused_prefix, re.IGNORECASE) is None:
        return end
    related_marker_match = re.match(
        r"\s*(?:D\d+:\d+[\s,;.]*)+",
        text[end:],
    )
    if related_marker_match is None:
        return end
    return end + related_marker_match.end()


def _dialogue_turn_marker_text_match(
    *,
    text: str,
    marker: str,
) -> re.Match[str] | None:
    matches = tuple(re.finditer(rf"\b{re.escape(marker)}\b", text))
    if not matches:
        return None
    for match in matches:
        if _marker_has_speaker_colon(text=text, marker_end=match.end()):
            return match
    return matches[0]


def _is_exact_source_sibling_answer_evidence_item(item: ContextItem) -> bool:
    if not _score_signal_truthy(item, "source_sibling_answer_evidence"):
        return False
    turn_refs = tuple(
        ref for ref in item.source_refs if str(ref.source_id).casefold().endswith(":turn")
    )
    return bool(turn_refs)


def _source_sibling_answer_continuation_hydration_requests(
    items: tuple[ContextItem, ...],
    *,
    existing_source_ids: frozenset[str],
) -> dict[str, str]:
    requests: dict[str, str] = {}
    existing = _focused_existing_continuation_source_ids(
        items,
        source_ids=existing_source_ids,
    )
    for item in items:
        answer_evidence = _score_signal_truthy(item, "source_sibling_answer_evidence")
        for ref in item.source_refs:
            source_ref_id = str(ref.source_id or "")
            if not source_ref_id:
                continue
            ref_item = _focused_continuation_item(item, source_id=source_ref_id)
            reason = _source_sibling_answer_continuation_reason(
                ref_item,
                answer_evidence=answer_evidence,
            )
            previous_reason = _source_sibling_answer_previous_context_reason(
                ref_item,
                answer_evidence=answer_evidence,
            )
            if not reason and not previous_reason:
                continue
            if previous_reason:
                previous_source_id = _previous_dialogue_turn_source_id(source_ref_id)
                if previous_source_id and previous_source_id not in existing:
                    requests.setdefault(
                        previous_source_id,
                        previous_reason.replace("-", "_"),
                    )
                    existing.add(previous_source_id)
            if reason:
                source_id = _next_dialogue_turn_source_id(source_ref_id)
                if not source_id or source_id in existing:
                    continue
                requests.setdefault(source_id, reason.replace("-", "_"))
                existing.add(source_id)
    return requests


def _focused_continuation_item(item: ContextItem, *, source_id: str) -> ContextItem:
    if not source_id.casefold().endswith(":turn"):
        return item
    focused_text = _focused_exact_source_repair_text(text=item.text, source_id=source_id)
    if focused_text == item.text:
        return item
    return replace(item, text=focused_text)


def _focused_existing_continuation_source_ids(
    items: tuple[ContextItem, ...],
    *,
    source_ids: frozenset[str],
) -> set[str]:
    if not source_ids:
        return set()
    existing: set[str] = set()
    for item in items:
        for ref in item.source_refs:
            source_id = str(ref.source_id or "")
            if source_id not in source_ids:
                continue
            marker = _source_ref_dialogue_marker(ref)
            if marker and _dialogue_turn_marker_text_match(text=item.text, marker=marker):
                existing.add(source_id)
    return existing


def _source_sibling_answer_continuation_reason(
    item: ContextItem,
    *,
    answer_evidence: bool,
) -> str:
    reason = _exact_source_repair_query_reason(item)
    if (
        answer_evidence
        and reason in _TRIP_DESTINATION_ANSWER_CONTINUATION_REASONS
        and _TRIP_DESTINATION_ANSWER_CONTINUATION_QUESTION_RE.search(item.text)
        is not None
    ):
        return reason
    if (
        answer_evidence
        and reason in _EN_VISUAL_REFERENT_ANSWER_CONTINUATION_REASONS
        and _EN_VISUAL_REFERENT_ANSWER_CONTINUATION_QUESTION_RE.search(item.text)
        is not None
    ):
        return reason
    if (
        reason in _EN_ACTIVITY_DURATION_ANSWER_CONTINUATION_REASONS
        and _EN_ACTIVITY_DURATION_ANSWER_CONTINUATION_QUESTION_RE.search(item.text)
        is not None
    ):
        return "decomposition-activity-duration"
    if (
        reason in _EXACT_REPAIR_RECOMMENDATION_REASONS
        and _EXACT_REPAIR_RECOMMENDATION_SETUP_CONTINUATION_RE.search(item.text)
        is not None
    ):
        return reason
    return ""


def _source_sibling_answer_previous_context_reason(
    item: ContextItem,
    *,
    answer_evidence: bool,
) -> str:
    reason = _exact_source_repair_query_reason(item)
    if not answer_evidence:
        return ""
    if _is_short_anaphoric_answer_reply(item.text):
        return reason
    if reason not in _EXACT_REPAIR_RECOMMENDATION_REASONS:
        return ""
    kind = recommendation_list_answer_kind(text=item.text, query_reason=reason)
    if kind == "confirmation":
        return reason
    if (
        kind == "direct"
        and _EXACT_REPAIR_RECOMMENDATION_ANAPHORIC_CONTEXT_RE.search(item.text)
        is not None
    ):
        return reason
    return ""


def _is_short_anaphoric_answer_reply(text: str) -> bool:
    reply = _dialogue_reply_body(text)
    if not reply:
        return False
    if len(re.findall(r"\b[\w']+\b", reply)) > 16:
        return False
    return _EXACT_REPAIR_SHORT_ANAPHORIC_REPLY_RE.search(reply) is not None


def _dialogue_reply_body(text: str) -> str:
    marker_match = re.search(r"\bD\d+:\d+\b", text)
    if marker_match is not None:
        text = text[marker_match.end() :]
    speaker_match = re.match(r"\s*[^:\n]{1,48}:\s*", text)
    if speaker_match is not None:
        text = text[speaker_match.end() :]
    return text.strip()


def _next_dialogue_turn_source_id(source_id: str) -> str:
    marker_match = re.search(r"\bD(?P<session>\d+):(?P<turn>\d+)(?=:turn$)", source_id)
    if marker_match is None:
        return ""
    next_marker = f"D{marker_match.group('session')}:{int(marker_match.group('turn')) + 1}"
    return f"{source_id[: marker_match.start()]}{next_marker}{source_id[marker_match.end():]}"


def _previous_dialogue_turn_source_id(source_id: str) -> str:
    marker_match = re.search(r"\bD(?P<session>\d+):(?P<turn>\d+)(?=:turn$)", source_id)
    if marker_match is None:
        return ""
    turn = int(marker_match.group("turn"))
    if turn <= 1:
        return ""
    previous_marker = f"D{marker_match.group('session')}:{turn - 1}"
    return f"{source_id[: marker_match.start()]}{previous_marker}{source_id[marker_match.end():]}"


def _is_exact_source_sibling_marker_coverage_item(item: ContextItem) -> bool:
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    diagnostics = item.diagnostics or {}
    query_reason = str(diagnostics.get("query_expansion_reason") or "").replace("_", "-")
    if query_reason != "pottery-type-bridge":
        return False
    turn_refs = tuple(
        ref for ref in item.source_refs if str(ref.source_id).casefold().endswith(":turn")
    )
    if len(turn_refs) < 2:
        return False
    score_signals = diagnostics.get("score_signals")
    if not isinstance(score_signals, dict):
        return False
    return _numeric_score_signal(score_signals.get("query_expansion_reason_priority")) >= 3


def _pre_pack_candidate_source_ref_diagnostics(
    items: tuple[ContextItem, ...],
) -> dict[str, object]:
    source_ids: list[str] = []
    dialogue_markers: list[str] = []
    answer_evidence_source_ids: list[str] = []
    answer_evidence_dialogue_markers: list[str] = []
    items_with_source_refs = 0
    for item in items:
        if item.source_refs:
            items_with_source_refs += 1
        source_sibling_answer_evidence = _score_signal_truthy(
            item,
            "source_sibling_answer_evidence",
        )
        for ref in item.source_refs:
            source_id = str(ref.source_id).strip()
            if source_id and source_id not in source_ids:
                source_ids.append(source_id)
            if (
                source_sibling_answer_evidence
                and source_id
                and source_id not in answer_evidence_source_ids
            ):
                answer_evidence_source_ids.append(source_id)
            for marker in _DIALOGUE_MARKER_RE.findall(source_id):
                if marker not in dialogue_markers:
                    dialogue_markers.append(marker)
                if (
                    source_sibling_answer_evidence
                    and marker not in answer_evidence_dialogue_markers
                ):
                    answer_evidence_dialogue_markers.append(marker)
        for marker in _DIALOGUE_MARKER_RE.findall(item.text):
            if marker not in dialogue_markers:
                dialogue_markers.append(marker)
            if source_sibling_answer_evidence and marker not in answer_evidence_dialogue_markers:
                answer_evidence_dialogue_markers.append(marker)
        if (
            len(source_ids) >= 80
            and len(dialogue_markers) >= 80
            and len(answer_evidence_source_ids) >= 40
            and len(answer_evidence_dialogue_markers) >= 40
        ):
            break
    return {
        "pre_pack_candidate_item_count": len(items),
        "pre_pack_items_with_source_refs": items_with_source_refs,
        "pre_pack_source_ref_ids_sample": source_ids[:200],
        "pre_pack_dialogue_markers_sample": dialogue_markers[:200],
        "pre_pack_source_sibling_answer_evidence_source_ref_ids_sample": (
            answer_evidence_source_ids[:40]
        ),
        "pre_pack_source_sibling_answer_evidence_dialogue_markers_sample": (
            answer_evidence_dialogue_markers[:40]
        ),
    }


def _source_sibling_answer_evidence_stage_diagnostics(
    stage: str,
    items: tuple[ContextItem, ...],
) -> dict[str, object]:
    source_ids: list[str] = []
    dialogue_markers: list[str] = []
    sibling_source_ids: list[str] = []
    sibling_dialogue_markers: list[str] = []
    item_count = 0
    sibling_item_count = 0
    for item in items:
        is_sibling = "keyword_source_sibling_chunks" in diagnostic_retrieval_sources(
            item.diagnostics
        )
        is_answer_evidence = _score_signal_truthy(item, "source_sibling_answer_evidence")
        if is_sibling:
            sibling_item_count += 1
        if is_answer_evidence:
            item_count += 1
        for ref in item.source_refs:
            source_id = str(ref.source_id).strip()
            if is_sibling and source_id and source_id not in sibling_source_ids:
                sibling_source_ids.append(source_id)
            if is_answer_evidence and source_id and source_id not in source_ids:
                source_ids.append(source_id)
            for marker in _DIALOGUE_MARKER_RE.findall(source_id):
                if is_sibling and marker not in sibling_dialogue_markers:
                    sibling_dialogue_markers.append(marker)
                if is_answer_evidence and marker not in dialogue_markers:
                    dialogue_markers.append(marker)
        for marker in _DIALOGUE_MARKER_RE.findall(item.text):
            if is_sibling and marker not in sibling_dialogue_markers:
                sibling_dialogue_markers.append(marker)
            if is_answer_evidence and marker not in dialogue_markers:
                dialogue_markers.append(marker)
    return {
        f"{stage}_source_sibling_item_count": sibling_item_count,
        f"{stage}_source_sibling_source_ref_ids_sample": sibling_source_ids[:200],
        f"{stage}_source_sibling_dialogue_markers_sample": sibling_dialogue_markers[:200],
        f"{stage}_source_sibling_answer_evidence_item_count": item_count,
        f"{stage}_source_sibling_answer_evidence_source_ref_ids_sample": source_ids[:200],
        f"{stage}_source_sibling_answer_evidence_dialogue_markers_sample": (
            dialogue_markers[:200]
        ),
    }


def _score_signal_truthy(item: ContextItem, key: str) -> bool:
    diagnostics = _provenance(dict(item.diagnostics or {}))
    score_signals = item.diagnostics.get("score_signals") if item.diagnostics else None
    if isinstance(score_signals, dict):
        value = score_signals.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, int | float):
            return value > 0
        if isinstance(value, str):
            return value.casefold() in {"1", "true", "yes"}
    value = diagnostics.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value > 0
    if isinstance(value, str):
        return value.casefold() in {"1", "true", "yes"}
    return False
