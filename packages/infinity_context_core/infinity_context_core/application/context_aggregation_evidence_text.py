"""Aggregation evidence text windowing helpers."""

from __future__ import annotations

import re

from infinity_context_core.application.context_lexical import query_terms

_STRICT_QUERY_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")

_AGGREGATION_DIALOGUE_WINDOW_AFTER = 5
_MAX_AGGREGATION_DIALOGUE_WINDOWS = 4
_MAX_AGGREGATION_EVIDENCE_TEXT_CHARS = 2400
_MAX_AGGREGATION_MARKER_COVERAGE_IDS = 24
_StrictQueryTermVariants = tuple[frozenset[str], ...]
_WeightedAggregationQueryVariants = tuple[tuple[frozenset[str], float], ...]
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
