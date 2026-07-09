"""Keyword aggregation and relevance-cache policies for build-context."""

from __future__ import annotations

import re
from dataclasses import dataclass

from infinity_context_core.application.context_lexical import query_terms
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import (
    best_query_relevance,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    ACTIVITY_OBSERVATION_SOURCE_REASONS as _ACTIVITY_OBSERVATION_SOURCE_REASONS,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    is_query_relevance_sufficient,
    score_query_relevance,
)
from infinity_context_core.application.context_source_siblings import (
    source_turn_marker as _source_turn_marker,
)
from infinity_context_core.application.context_travel_place_evidence import (
    has_travel_place_inventory_evidence,
)
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.application.use_cases.build_context_item_projection import (
    _chunk_context_item,
    _with_keyword_aggregation_score_signals,
)
from infinity_context_core.domain.entities import MemoryChunk

_MAX_AGGREGATION_KEYWORD_ITEMS = 20
_STRICT_QUERY_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_COUNT_AGGREGATION_QUERY_RE = re.compile(
    r"\b(how many|number of|count|total)\b",
    re.IGNORECASE,
)
_LIST_AGGREGATION_QUERY_RE = re.compile(
    r"\b(?:what|which)\s+"
    r"(?:[\w+.-]+\s+){0,4}"
    r"(?:areas?|causes?|cities|countries|events?|activities?|hobbies|"
    r"instruments?|items?|martial\s+arts|people|places?|shelters?|states?|"
    r"traits?|books?|songs?|artists?|bands?|foods?|pets?|projects?|tasks?|"
    r"types?|kinds?)\b|"
    r"\b(?:has|have|did|does)\s+\w{2,40}\s+"
    r"(?:bought|attended|joined|visited|played|shared|mentioned|done|used)\b|"
    r"\b(?:какие|какие\s+именно|что\s+за)\s+"
    r"(?:вещи|события|активности|занятия|инструменты|черты|места|книги|задачи)\b",
    re.IGNORECASE,
)
_WHERE_LIST_AGGREGATION_QUERY_RE = re.compile(
    r"\bwhere\b(?=.{0,100}\b(?:been|friend|friends|go|gone|made|meet|met|"
    r"vacation(?:ed)?|visited|went)\b)|"
    r"\bгде\b(?=.{0,100}\b(?:друз|ездил|ездила|ездили|посещал|посещала|"
    r"посещали|познакомил|познакомила|познакомили)\b)",
    re.IGNORECASE | re.DOTALL,
)
_AGGREGATION_DIALOGUE_WINDOW_AFTER = 5
_MAX_AGGREGATION_DIALOGUE_WINDOWS = 4
_MAX_AGGREGATION_EVIDENCE_TEXT_CHARS = 2400
_MAX_AGGREGATION_MARKER_COVERAGE_IDS = 24
_MAX_EXTRA_ACTIVITY_PROMPT_KEYWORD_ITEMS = 80
_MAX_EXTRA_INVENTORY_PROMPT_KEYWORD_ITEMS = 16
_MIN_CHUNK_LIMIT_FOR_EXTRA_ACTIVITY_PROMPT_ITEMS = 8
_MIN_CHUNK_LIMIT_FOR_EXTRA_INVENTORY_PROMPT_ITEMS = 8
_MIN_EXTRA_INVENTORY_PROMPT_DISTINCTIVE_HITS = 4
_EXTRA_INVENTORY_PROMPT_REASONS = frozenset(
    {
        "decomposition_inventory_list",
        "friend_place_inventory_bridge",
        "friend_place_shelter_inventory_bridge",
        "friend_place_gym_inventory_bridge",
        "friend_place_church_inventory_bridge",
        "travel_country_inventory_bridge",
        "cause_education_infrastructure_inventory_bridge",
        "cause_veterans_inventory_bridge",
    }
)
_ScoredKeywordPromptItem = tuple[int, int, int, float, float, int, str, ContextItem]
_StrictQueryTermVariants = tuple[frozenset[str], ...]
_WeightedAggregationQueryVariants = tuple[tuple[frozenset[str], float], ...]
_SOURCE_GROUP_SUFFIXES = frozenset({"events", "observation", "summary"})
_LOW_SIGNAL_COUNT_AGGREGATION_TERMS = frozenset(
    {"many", "time", "times", "gone", "go", "going", "went"}
)
_LOW_SIGNAL_INVENTORY_AGGREGATION_TERMS = frozenset(
    {
        "answer",
        "evidence",
        "inventory",
        "list",
        "mention",
        "mentioned",
        "observed",
        "option",
        "options",
    }
)


@dataclass(frozen=True)
class _KeywordAggregationCandidate:
    rank_key: tuple[int, int, int, float, int]
    group: str
    chunk: MemoryChunk
    chunk_text: str
    relevance: QueryRelevance
    strict_hits: int
    aggregation_query: str
    aggregation_reason: str
    query_variant_sets: _WeightedAggregationQueryVariants


def _ranked_keyword_chunk_scores(
    scored_keyword_chunks: list[tuple[int, int, int, float, float, int, MemoryChunk]],
) -> tuple[tuple[int, int, int, float, float, int, MemoryChunk], ...]:
    return tuple(
        sorted(
            scored_keyword_chunks,
            key=lambda item: (
                -item[0],
                -item[1],
                -item[2],
                -item[3],
                -item[4],
                item[5],
            ),
        )
    )


def _context_item_aggregation_source_groups(items: tuple[ContextItem, ...]) -> tuple[str, ...]:
    groups: list[str] = []
    seen: set[str] = set()
    for item in items:
        diagnostics = item.diagnostics or {}
        provenance = diagnostics.get("provenance")
        raw_group = (
            provenance.get("keyword_aggregation_source_group")
            if isinstance(provenance, dict)
            else None
        )
        group = str(raw_group or "").strip()
        if group and group not in seen:
            seen.add(group)
            groups.append(group)
    return tuple(groups)


def _prioritized_chunks_for_source_groups(
    chunks: tuple[MemoryChunk, ...],
    *,
    source_groups: tuple[str, ...],
) -> tuple[MemoryChunk, ...]:
    if not chunks or not source_groups:
        return ()
    source_group_set = set(source_groups)
    return tuple(
        chunk
        for chunk in chunks
        if _aggregation_source_group(chunk) in source_group_set
    )


def _dedupe_chunks_by_id(chunks: tuple[MemoryChunk, ...]) -> tuple[MemoryChunk, ...]:
    selected: list[MemoryChunk] = []
    seen: set[str] = set()
    for chunk in chunks:
        chunk_id = str(chunk.id)
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        selected.append(chunk)
    return tuple(selected)


def _strict_query_term_hits(*, query: str, text: str) -> int:
    return _strict_query_variant_hits(
        query_term_variants=_strict_query_term_variant_sets(query=query),
        text=text,
    )


def _strict_query_term_variant_sets(*, query: str) -> _StrictQueryTermVariants:
    return tuple(frozenset(_strict_token_variants(term.raw)) for term in query_terms(query))


def _strict_query_variant_hits(
    *,
    query_term_variants: _StrictQueryTermVariants,
    text: str,
) -> int:
    if not query_term_variants:
        return 0
    text_variants: set[str] = set()
    for match in _STRICT_QUERY_TOKEN_RE.finditer(text):
        text_variants.update(_strict_token_variants(match.group(0)))
    return sum(
        1
        for term_variants in query_term_variants
        if text_variants.intersection(term_variants)
    )


def _keyword_anchor_conflict_allowed(
    *,
    expansion_reason: str,
    relevance: QueryRelevance,
    text: str,
) -> bool:
    if expansion_reason != "travel_country_inventory_bridge":
        return False
    if relevance.distinctive_term_hits < 3 or relevance.unique_term_hits < 3:
        return False
    return has_travel_place_inventory_evidence(text)


def _selected_keyword_prompt_items(
    scored_items: list[_ScoredKeywordPromptItem],
    *,
    limit: int,
) -> tuple[ContextItem, ...]:
    if limit <= 0 or not scored_items:
        return ()
    ordered = tuple(
        sorted(
            scored_items,
            key=lambda item: (
                -item[0],
                -item[1],
                -item[2],
                -item[3],
                -item[4],
                item[5],
            ),
        )
    )
    selected: list[ContextItem] = []
    selected_keys: set[tuple[str, str]] = set()
    for scored_item in ordered[:limit]:
        item = scored_item[7]
        selected.append(item)
        selected_keys.add((item.item_type, item.item_id))
    if (
        limit < _MIN_CHUNK_LIMIT_FOR_EXTRA_ACTIVITY_PROMPT_ITEMS
        and limit < _MIN_CHUNK_LIMIT_FOR_EXTRA_INVENTORY_PROMPT_ITEMS
    ):
        return tuple(selected)
    if limit >= _MIN_CHUNK_LIMIT_FOR_EXTRA_INVENTORY_PROMPT_ITEMS:
        inventory_extra_count = 0
        inventory_extra_limit = min(limit, _MAX_EXTRA_INVENTORY_PROMPT_KEYWORD_ITEMS)
        for scored_item in ordered[limit:]:
            reason = scored_item[6]
            if reason not in _EXTRA_INVENTORY_PROMPT_REASONS:
                continue
            if scored_item[1] < _MIN_EXTRA_INVENTORY_PROMPT_DISTINCTIVE_HITS:
                continue
            item = scored_item[7]
            key = (item.item_type, item.item_id)
            if key in selected_keys:
                continue
            selected.append(item)
            selected_keys.add(key)
            inventory_extra_count += 1
            if inventory_extra_count >= inventory_extra_limit:
                break
    if limit < _MIN_CHUNK_LIMIT_FOR_EXTRA_ACTIVITY_PROMPT_ITEMS:
        return tuple(selected)
    extra_count = 0
    extra_limit = limit
    if limit >= 32:
        extra_limit = _MAX_EXTRA_ACTIVITY_PROMPT_KEYWORD_ITEMS
    for scored_item in ordered[limit:]:
        reason = scored_item[6]
        if reason not in _ACTIVITY_OBSERVATION_SOURCE_REASONS:
            continue
        item = scored_item[7]
        key = (item.item_type, item.item_id)
        if key in selected_keys:
            continue
        selected.append(item)
        selected_keys.add(key)
        extra_count += 1
        if extra_count >= extra_limit:
            break
    return tuple(selected)


def _strict_token_variants(token: str) -> tuple[str, ...]:
    normalized = token.casefold().replace("ё", "е").strip("_")
    if not normalized:
        return ()
    variants = {normalized}
    if len(normalized) > 5 and normalized.endswith("ing"):
        stem = normalized[:-3]
        variants.add(stem)
        variants.add(f"{stem}e")
        if len(stem) > 3 and stem[-1:] == stem[-2:-1]:
            variants.add(stem[:-1])
    if len(normalized) > 4 and normalized.endswith("ed"):
        variants.add(normalized[:-2])
    if len(normalized) > 4 and normalized.endswith("es"):
        variants.add(normalized[:-2])
    if len(normalized) > 3 and normalized.endswith("s"):
        variants.add(normalized[:-1])
    return tuple(sorted(variant for variant in variants if len(variant) >= 2))


def _keyword_aggregation_chunk_items(
    *,
    query: BuildContextQuery,
    seed_chunks: tuple[MemoryChunk, ...],
    query_plan: QueryExpansionPlan | None = None,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]] | None = None,
) -> tuple[tuple[ContextItem, ...], dict[str, object]]:
    diagnostics = {
        "keyword_aggregation_chunks_considered": 0,
        "keyword_aggregation_chunks_used": 0,
        "keyword_aggregation_chunks_skipped": 0,
        "keyword_aggregation_query_kind": "",
        "keyword_aggregation_relaxed_relevance_used": 0,
    }
    aggregation_kind = _keyword_aggregation_query_kind(query.query)
    diagnostics["keyword_aggregation_query_kind"] = aggregation_kind
    if query.max_chunks <= 0 or not seed_chunks or not aggregation_kind:
        return (), diagnostics

    query_identity_terms = _aggregation_identity_terms(query.query)
    max_items = min(
        _MAX_AGGREGATION_KEYWORD_ITEMS,
        max(4, query.max_chunks // 2),
    )
    candidates: list[_KeywordAggregationCandidate] = []
    skipped = 0
    for order, chunk in enumerate(seed_chunks):
        diagnostics["keyword_aggregation_chunks_considered"] = (
            int(diagnostics["keyword_aggregation_chunks_considered"]) + 1
        )
        chunk_text = document_chunk_retrieval_text(
            text=chunk.text,
            metadata=chunk.metadata,
        )
        aggregation_query, aggregation_reason, relevance = _aggregation_query_relevance(
            query=query.query,
            query_plan=query_plan,
            text=chunk_text,
            query_relevance_cache=query_relevance_cache,
        )
        weighted_query_terms = _weighted_aggregation_query_variant_sets(
            aggregation_query,
            identity_terms=query_identity_terms,
        )
        weighted_hits, _ = _strict_query_window_match_counts(
            text=chunk_text,
            query_variant_sets=weighted_query_terms,
        )
        strict_hits = int(weighted_hits)
        if weighted_hits <= 0:
            skipped += 1
            continue
        if not _is_keyword_aggregation_relevance_acceptable(
            relevance,
            aggregation_kind=aggregation_kind,
            strict_hits=strict_hits,
        ):
            skipped += 1
            continue
        if not is_query_relevance_sufficient(relevance):
            diagnostics["keyword_aggregation_relaxed_relevance_used"] = (
                int(diagnostics["keyword_aggregation_relaxed_relevance_used"]) + 1
            )
        group = _aggregation_source_group(chunk)
        rank_key = (
            -strict_hits,
            _aggregation_source_kind_rank(chunk),
            -relevance.distinctive_term_hits,
            -relevance.hit_ratio,
            order,
        )
        candidates.append(
            _KeywordAggregationCandidate(
                rank_key=rank_key,
                group=group,
                chunk=chunk,
                chunk_text=chunk_text,
                relevance=relevance,
                strict_hits=strict_hits,
                aggregation_query=aggregation_query,
                aggregation_reason=aggregation_reason,
                query_variant_sets=weighted_query_terms,
            )
        )

    items: list[ContextItem] = []
    group_counts: dict[str, int] = {}
    for candidate in sorted(candidates, key=lambda item: item.rank_key):
        if len(items) >= max_items:
            break
        if group_counts.get(candidate.group, 0) >= 3:
            skipped += 1
            continue
        group_counts[candidate.group] = group_counts.get(candidate.group, 0) + 1
        item = _chunk_context_item(
            chunk=candidate.chunk,
            text=_aggregation_evidence_text(
                query=candidate.aggregation_query,
                text=candidate.chunk_text,
                identity_terms=query_identity_terms,
                query_variant_sets=candidate.query_variant_sets,
            ),
            retrieval_source="keyword_aggregation_chunks",
            base_score=0.78,
            score=0.985,
            relevance=candidate.relevance,
            query_text=candidate.aggregation_query,
            query_expansion_reason=candidate.aggregation_reason,
            use_query_snippet=False,
        )
        items.append(
            _with_keyword_aggregation_score_signals(
                item,
                strict_hits=candidate.strict_hits,
                source_group=candidate.group,
            )
        )

    diagnostics["keyword_aggregation_chunks_used"] = len(items)
    diagnostics["keyword_aggregation_chunks_skipped"] = skipped
    return tuple(items), diagnostics


def _keyword_aggregation_query_kind(query: str) -> str:
    if _COUNT_AGGREGATION_QUERY_RE.search(query):
        return "count"
    if _LIST_AGGREGATION_QUERY_RE.search(query) or _WHERE_LIST_AGGREGATION_QUERY_RE.search(query):
        return "list"
    return ""


def _aggregation_identity_terms(query: str) -> frozenset[str]:
    intent = build_query_anchor_intent(query)
    terms: set[str] = set()
    for hint in intent.hints:
        if hint.kind.value != "person":
            continue
        terms.update(term for term in hint.canonical_key.split() if term)
    return frozenset(terms)


def _aggregation_query_relevance(
    *,
    query: str,
    query_plan: QueryExpansionPlan | None,
    text: str,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]] | None = None,
) -> tuple[str, str, QueryRelevance]:
    if query_plan is None:
        return query, "original_query", score_query_relevance(query=query, text=text)
    if query_relevance_cache is None:
        return best_query_relevance(query_plan, text=text)
    return _best_query_relevance_cached(query_plan, text=text, cache=query_relevance_cache)


def _best_query_relevance_cached(
    query_plan: QueryExpansionPlan,
    *,
    text: str,
    cache: dict[str, tuple[str, str, QueryRelevance]],
) -> tuple[str, str, QueryRelevance]:
    cached = cache.get(text)
    if cached is not None:
        return cached
    result = best_query_relevance(query_plan, text=text)
    cache[text] = result
    return result


def _is_keyword_aggregation_relevance_acceptable(
    relevance: QueryRelevance,
    *,
    aggregation_kind: str,
    strict_hits: int,
) -> bool:
    if is_query_relevance_sufficient(relevance):
        return True
    return (
        aggregation_kind == "list"
        and strict_hits > 0
        and relevance.unique_term_hits > 0
    )


def _aggregation_source_group(chunk: MemoryChunk) -> str:
    marker = _source_turn_marker(chunk.source_external_id)
    if marker is not None:
        return marker[0]
    source_id = " ".join(str(chunk.source_external_id).split())
    parts = source_id.split(":")
    if len(parts) >= 4 and parts[-1] in _SOURCE_GROUP_SUFFIXES:
        return ":".join(parts[:-1])
    return source_id or str(chunk.document_id or chunk.id)


def _aggregation_source_kind_rank(chunk: MemoryChunk) -> int:
    if _source_turn_marker(chunk.source_external_id) is not None:
        return 1
    parts = " ".join(str(chunk.source_external_id).split()).split(":")
    if parts and parts[-1] == "observation":
        return 0
    if parts and parts[-1] in {"events", "summary"}:
        return 3
    return 2


def _aggregation_evidence_text(
    *,
    query: str,
    text: str,
    identity_terms: frozenset[str] = frozenset(),
    query_variant_sets: _WeightedAggregationQueryVariants | None = None,
) -> str:
    markers = tuple(_DIALOGUE_MARKER_RE.finditer(text))
    if not markers:
        return text
    weighted_query_variants = (
        query_variant_sets
        if query_variant_sets is not None
        else _weighted_aggregation_query_variant_sets(
            query,
            identity_terms=identity_terms,
        )
    )
    multi_window_text = _multi_window_aggregation_evidence_text(
        query=query,
        text=text,
        markers=markers,
        identity_terms=identity_terms,
        query_variant_sets=weighted_query_variants,
    )
    if multi_window_text:
        return _with_aggregation_marker_coverage(rendered=multi_window_text, full_text=text)
    bounds = _best_aggregation_dialogue_window(
        query=query,
        text=text,
        markers=markers,
        identity_terms=identity_terms,
        query_variant_sets=weighted_query_variants,
    )
    if bounds is None:
        match_start = _first_strict_query_match_start(
            query=query,
            text=text,
            query_variant_sets=weighted_query_variants,
        )
        if match_start is None:
            return text
        marker_index = max(
            (index for index, marker in enumerate(markers) if marker.start() <= match_start),
            default=0,
        )
        start_index = max(0, marker_index - 1)
        end_index = min(len(markers) - 1, marker_index + _AGGREGATION_DIALOGUE_WINDOW_AFTER)
        bounds = (
            markers[start_index].start(),
            markers[end_index + 1].start()
            if end_index + 1 < len(markers)
            else len(text),
        )
    start, end = bounds
    window = text[start:end].strip()
    if start > 0:
        window = f"... {window}"
    if end < len(text):
        window = f"{window} ..."
    return _with_aggregation_marker_coverage(rendered=window or text, full_text=text)


def _with_aggregation_marker_coverage(*, rendered: str, full_text: str) -> str:
    if not rendered or rendered == full_text:
        return rendered
    markers = tuple(
        dict.fromkeys(match.group(0) for match in _DIALOGUE_MARKER_RE.finditer(full_text))
    )
    if not markers:
        return rendered
    missing = tuple(marker for marker in markers if marker not in rendered)
    if not missing:
        return rendered
    coverage = (
        "omitted source evidence markers: "
        + " ".join(missing[:_MAX_AGGREGATION_MARKER_COVERAGE_IDS])
    )
    if len(missing) > _MAX_AGGREGATION_MARKER_COVERAGE_IDS:
        coverage = f"{coverage} ..."
    candidate = f"{rendered}\n{coverage}".strip()
    if len(candidate) > _MAX_AGGREGATION_EVIDENCE_TEXT_CHARS:
        return rendered
    return candidate


def _multi_window_aggregation_evidence_text(
    *,
    query: str,
    text: str,
    markers: tuple[re.Match[str], ...],
    identity_terms: frozenset[str],
    query_variant_sets: _WeightedAggregationQueryVariants | None = None,
) -> str:
    bounds = _aggregation_dialogue_windows(
        query=query,
        text=text,
        markers=markers,
        identity_terms=identity_terms,
        query_variant_sets=query_variant_sets,
    )
    if len(bounds) <= 1:
        return ""
    rendered = _render_aggregation_windows(text=text, bounds=bounds)
    return rendered if rendered and len(rendered) < len(text) else ""


def _aggregation_dialogue_windows(
    *,
    query: str,
    text: str,
    markers: tuple[re.Match[str], ...],
    identity_terms: frozenset[str],
    query_variant_sets: _WeightedAggregationQueryVariants | None = None,
) -> tuple[tuple[int, int], ...]:
    weighted_query_variants = (
        query_variant_sets
        if query_variant_sets is not None
        else _weighted_aggregation_query_variant_sets(
            query,
            identity_terms=identity_terms,
        )
    )
    if not weighted_query_variants:
        return ()

    candidates: list[tuple[tuple[float, float, int, int], int, int]] = []
    for marker_index, _marker in enumerate(markers):
        segment_start = markers[marker_index].start()
        segment_end = (
            markers[marker_index + 1].start() if marker_index + 1 < len(markers) else len(text)
        )
        segment_matched_terms, segment_total_hits = _strict_query_window_match_counts(
            text=text[segment_start:segment_end],
            query_variant_sets=weighted_query_variants,
        )
        if segment_matched_terms <= 0:
            continue
        start_index = marker_index
        end_index = min(len(markers) - 1, marker_index + _AGGREGATION_DIALOGUE_WINDOW_AFTER)
        start = markers[start_index].start()
        end = markers[end_index + 1].start() if end_index + 1 < len(markers) else len(text)
        window_matched_terms, window_total_hits = _strict_query_window_match_counts(
            text=text[start:end],
            query_variant_sets=weighted_query_variants,
        )
        key = (
            window_matched_terms,
            window_total_hits,
            -(end - start),
            -start,
        )
        candidates.append((key, start, end))

    selected: list[tuple[int, int]] = []
    selected_chars = 0
    for _key, start, end in sorted(candidates, key=lambda item: item[0], reverse=True):
        if len(selected) >= _MAX_AGGREGATION_DIALOGUE_WINDOWS:
            break
        if any(
            _bounds_overlap(start, end, selected_start, selected_end)
            for selected_start, selected_end in selected
        ):
            continue
        window_chars = end - start
        if selected_chars + window_chars > _MAX_AGGREGATION_EVIDENCE_TEXT_CHARS:
            continue
        selected.append((start, end))
        selected_chars += window_chars

    return tuple(sorted(selected))


def _bounds_overlap(
    start: int,
    end: int,
    selected_start: int,
    selected_end: int,
) -> bool:
    return start < selected_end and selected_start < end


def _render_aggregation_windows(
    *,
    text: str,
    bounds: tuple[tuple[int, int], ...],
) -> str:
    parts: list[str] = []
    for start, end in bounds:
        window = text[start:end].strip()
        if not window:
            continue
        if start > 0:
            window = f"... {window}"
        if end < len(text):
            window = f"{window} ..."
        parts.append(window)
    rendered = " ".join(parts).strip()
    return rendered[:_MAX_AGGREGATION_EVIDENCE_TEXT_CHARS].strip()


def _best_aggregation_dialogue_window(
    *,
    query: str,
    text: str,
    markers: tuple[re.Match[str], ...],
    identity_terms: frozenset[str],
    query_variant_sets: _WeightedAggregationQueryVariants | None = None,
) -> tuple[int, int] | None:
    weighted_query_variants = (
        query_variant_sets
        if query_variant_sets is not None
        else _weighted_aggregation_query_variant_sets(
            query,
            identity_terms=identity_terms,
        )
    )
    if not weighted_query_variants:
        return None

    best_bounds: tuple[int, int] | None = None
    best_key: tuple[float, float, int, int] = (-1.0, -1.0, 0, 0)
    for marker_index, _marker in enumerate(markers):
        start_index = max(0, marker_index - 1)
        end_index = min(len(markers) - 1, marker_index + _AGGREGATION_DIALOGUE_WINDOW_AFTER)
        start = markers[start_index].start()
        end = markers[end_index + 1].start() if end_index + 1 < len(markers) else len(text)
        matched_terms, total_hits = _strict_query_window_match_counts(
            text=text[start:end],
            query_variant_sets=weighted_query_variants,
        )
        if matched_terms <= 0:
            continue
        start = _first_positive_aggregation_marker_start(
            text=text,
            markers=markers,
            start_index=start_index,
            end_index=end_index,
            query_variant_sets=weighted_query_variants,
        )
        key = (matched_terms, total_hits, -(end - start), -start)
        if key > best_key:
            best_key = key
            best_bounds = (start, end)
    return best_bounds


def _first_positive_aggregation_marker_start(
    *,
    text: str,
    markers: tuple[re.Match[str], ...],
    start_index: int,
    end_index: int,
    query_variant_sets: _WeightedAggregationQueryVariants,
) -> int:
    for index in range(start_index, end_index + 1):
        segment_start = markers[index].start()
        segment_end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        matched_terms, _ = _strict_query_window_match_counts(
            text=text[segment_start:segment_end],
            query_variant_sets=query_variant_sets,
        )
        if matched_terms > 0:
            return segment_start
    return markers[start_index].start()


def _weighted_aggregation_query_variant_sets(
    query: str,
    *,
    identity_terms: frozenset[str] = frozenset(),
) -> _WeightedAggregationQueryVariants:
    identity_terms = {
        match.group(0).casefold()
        for match in _STRICT_QUERY_TOKEN_RE.finditer(query)
        if match.group(0)[:1].isupper() and not match.group(0).isupper()
    }.union(identity_terms)
    weighted: list[tuple[frozenset[str], float]] = []
    for term in query_terms(query):
        variants = frozenset(_strict_token_variants(term.raw))
        if not variants:
            continue
        if (
            term.raw.isdigit()
            or term.raw.casefold() in identity_terms
            or variants.intersection(_LOW_SIGNAL_COUNT_AGGREGATION_TERMS)
            or variants.intersection(_LOW_SIGNAL_INVENTORY_AGGREGATION_TERMS)
        ):
            weight = 0.0
        else:
            weight = 1.0
        weighted.append((variants, weight))
    return tuple(weighted)


def _strict_query_window_match_counts(
    *,
    text: str,
    query_variant_sets: _WeightedAggregationQueryVariants,
) -> tuple[float, float]:
    matched_indexes: set[int] = set()
    matched_score = 0.0
    total_score = 0.0
    for match in _STRICT_QUERY_TOKEN_RE.finditer(text):
        token_variants = set(_strict_token_variants(match.group(0)))
        if not token_variants:
            continue
        for index, (variants, weight) in enumerate(query_variant_sets):
            if token_variants.intersection(variants):
                if index not in matched_indexes:
                    matched_score += weight
                matched_indexes.add(index)
                total_score += weight
                break
    return matched_score, total_score


def _first_strict_query_match_start(
    *,
    query: str,
    text: str,
    query_variant_sets: _WeightedAggregationQueryVariants | None = None,
) -> int | None:
    strict_query_variants = _strict_query_search_variant_sets(
        query=query,
        query_variant_sets=query_variant_sets,
    )
    if not strict_query_variants:
        return None
    for variants in strict_query_variants:
        for match in _STRICT_QUERY_TOKEN_RE.finditer(text):
            token_variants = set(_strict_token_variants(match.group(0)))
            if token_variants.intersection(variants):
                return match.start()
    return None


def _strict_query_search_variant_sets(
    *,
    query: str,
    query_variant_sets: _WeightedAggregationQueryVariants | None = None,
) -> _StrictQueryTermVariants:
    if query_variant_sets is not None:
        query_variants = tuple(variants for variants, _weight in query_variant_sets if variants)
    else:
        query_variants = tuple(
            variants
            for term in query_terms(query)
            if (variants := frozenset(_strict_token_variants(term.raw)))
        )
    return tuple(
        sorted(
            query_variants,
            key=lambda variants: (len(variants) <= 1, sorted(variants)),
        )
    )
