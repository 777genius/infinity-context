"""Candidate fusion for multi-query benchmark retrieval."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_source_identity import (
    source_identity_refs_from_dedupe_key,
    source_identity_refs_from_source_refs,
    source_identity_refs_from_text,
)


@dataclass(frozen=True)
class CandidateFusionConfig:
    """Bounded fusion weights for query fanout candidates."""

    rrf_k: int = 60
    max_multi_query_boost: float = 0.12
    max_rrf_boost: float = 0.035
    max_source_diversity_boost: float = 0.02


DEFAULT_CANDIDATE_FUSION_CONFIG = CandidateFusionConfig()
_TURN_REF_RE = re.compile(r"\bD\d+:\d+\b")
_SOURCE_SESSION_TURN_RE = re.compile(
    r"(?:^|:)session_(?P<session>\d+):(?P<turn_ref>D\d+:\d+):"
    r"(?:turn|chunk|fact)(?:[-_][^:]*)?$",
    re.IGNORECASE,
)
_BROAD_SUMMARY_SURFACE_RE = re.compile(
    r"\b(?:conversation summary|memory summary|observations|related turns|"
    r"events date|summari[sz]ed turns|summary of)\b|\bsummary\s*:",
    re.IGNORECASE,
)
_EVIDENCE_SELECTION_SCORE_BAND = 0.025
_FOCUSED_QUERY_ROLE_SCORES = {
    "action_support": 0.05,
    "compact_relation": 0.04,
    "contrast_support": 0.05,
    "location_support": 0.05,
    "communication_support": 0.05,
    "emotion_response_support": 0.05,
    "event_support": 0.05,
    "exchange_support": 0.05,
    "symbolic_meaning_support": 0.05,
    "preference_support": 0.045,
    "favorite_support": 0.045,
    "causal_support": 0.04,
    "inference_support": 0.04,
    "visual_support": 0.05,
    "visual_temporal_support": 0.05,
    "multi_hop_bridge": 0.05,
    "multi_hop_support": 0.04,
    "duration_temporal_support": 0.04,
    "explicit_temporal_support": 0.04,
    "relative_temporal_support": 0.04,
    "temporal_sequence_support": 0.04,
    "temporal_support": 0.04,
    "expanded_focus": 0.02,
}


@dataclass(frozen=True)
class _CandidateOccurrence:
    query_index: int
    query_role: str
    rank: int
    memory: RetrievedMemory


def fuse_query_results(
    query_results: Sequence[tuple[str, Sequence[RetrievedMemory]]],
    *,
    query_roles: Sequence[str] = (),
    config: CandidateFusionConfig = DEFAULT_CANDIDATE_FUSION_CONFIG,
) -> tuple[list[RetrievedMemory], dict[str, object]]:
    """Fuse repeated candidates from bounded query fanout."""

    occurrences_by_key: dict[str, list[_CandidateOccurrence]] = defaultdict(list)
    key_to_group: dict[str, str] = {}
    group_keys: dict[str, set[str]] = {}
    raw_result_count = 0
    for query_index, (_query, memories) in enumerate(query_results, start=1):
        query_role = _query_role(query_roles, query_index)
        for ordinal, memory in enumerate(memories, start=1):
            raw_result_count += 1
            rank = memory.rank if memory.rank > 0 else ordinal
            occurrence = _CandidateOccurrence(
                query_index=query_index,
                query_role=query_role,
                rank=rank,
                memory=memory,
            )
            group_key = _candidate_group_key(
                memory,
                occurrences_by_key=occurrences_by_key,
                key_to_group=key_to_group,
                group_keys=group_keys,
            )
            occurrences_by_key[group_key].append(occurrence)

    fused: list[RetrievedMemory] = []
    match_counts: list[int] = []
    rrf_scores: list[float] = []
    source_diversity_counts: list[int] = []
    query_role_counts: Counter[str] = Counter()
    score_winner_query_role_counts: Counter[str] = Counter()
    selected_evidence_query_role_counts: Counter[str] = Counter()
    focused_query_evidence_selection_role_counts: Counter[str] = Counter()
    evidence_selection_reason_counts: Counter[str] = Counter()
    evidence_selection_samples: list[dict[str, object]] = []
    bridge_query_hit_count = 0
    lower_score_evidence_selection_count = 0
    source_type_evidence_selection_count = 0
    focused_query_evidence_selection_count = 0
    for key, occurrences in occurrences_by_key.items():
        fused_memory, fusion = _fuse_candidate(key, occurrences, config=config)
        fused.append(fused_memory)
        match_counts.append(int(fusion["query_match_count"]))
        rrf_scores.append(float(fusion["rrf_score"]))
        source_diversity_counts.append(int(fusion["source_diversity_count"]))
        query_role_counts.update(_string_sequence(fusion.get("query_roles")))
        score_winner_query_role = str(fusion.get("score_winner_query_role") or "")
        selected_evidence_query_role = str(
            fusion.get("selected_evidence_query_role") or ""
        )
        if score_winner_query_role:
            score_winner_query_role_counts[score_winner_query_role] += 1
        if selected_evidence_query_role:
            selected_evidence_query_role_counts[selected_evidence_query_role] += 1
        if fusion.get("bridge_query_hit") is True:
            bridge_query_hit_count += 1
        if float(fusion.get("selected_evidence_score") or 0.0) < float(
            fusion.get("winner_score") or 0.0
        ):
            lower_score_evidence_selection_count += 1
        if fusion.get("selected_evidence_source_type") != fusion.get(
            "score_winner_source_type"
        ):
            source_type_evidence_selection_count += 1
        if fusion.get("selected_evidence_query_role") != fusion.get(
            "score_winner_query_role"
        ):
            focused_query_evidence_selection_count += 1
            if selected_evidence_query_role:
                focused_query_evidence_selection_role_counts[
                    selected_evidence_query_role
                ] += 1
        reason_codes = _string_sequence(fusion.get("evidence_selection_reason_codes"))
        evidence_selection_reason_counts.update(reason_codes)
        if (
            len(evidence_selection_samples) < 10
            and reason_codes
            and reason_codes != ("score_winner",)
        ):
            evidence_selection_samples.append(_evidence_selection_sample(fusion))

    fused.sort(key=lambda memory: (-memory.score, memory.rank))
    reranked = [
        replace(memory, rank=index)
        for index, memory in enumerate(fused, start=1)
    ]
    return reranked, {
        "schema_version": "candidate_fusion.v1",
        "query_count": len(query_results),
        "raw_result_count": raw_result_count,
        "unique_result_count": len(reranked),
        "duplicate_result_count": max(0, raw_result_count - len(reranked)),
        "multi_query_hit_count": sum(1 for count in match_counts if count > 1),
        "query_role_counts": dict(sorted(query_role_counts.items())),
        "score_winner_query_role_counts": dict(
            sorted(score_winner_query_role_counts.items())
        ),
        "selected_evidence_query_role_counts": dict(
            sorted(selected_evidence_query_role_counts.items())
        ),
        "bridge_query_hit_count": bridge_query_hit_count,
        "lower_score_evidence_selection_count": lower_score_evidence_selection_count,
        "source_type_evidence_selection_count": source_type_evidence_selection_count,
        "focused_query_evidence_selection_count": (
            focused_query_evidence_selection_count
        ),
        "focused_query_evidence_selection_role_counts": dict(
            sorted(focused_query_evidence_selection_role_counts.items())
        ),
        "evidence_selection_reason_counts": dict(
            sorted(evidence_selection_reason_counts.items())
        ),
        "evidence_selection_samples": evidence_selection_samples,
        "max_query_match_count": max(match_counts, default=0),
        "max_rrf_score": round(max(rrf_scores, default=0.0), 6),
        "max_source_diversity_count": max(source_diversity_counts, default=0),
    }


def _fuse_candidate(
    key: str,
    occurrences: Sequence[_CandidateOccurrence],
    *,
    config: CandidateFusionConfig,
) -> tuple[RetrievedMemory, dict[str, object]]:
    score_winner = max(occurrences, key=_score_winner_key)
    evidence_winner = _select_evidence_winner(
        occurrences,
        score_winner=score_winner,
    )
    query_indices = tuple(
        sorted({occurrence.query_index for occurrence in occurrences})
    )
    query_roles = tuple(
        dict.fromkeys(
            occurrence.query_role for occurrence in occurrences if occurrence.query_role
        )
    )
    query_role_counts = Counter(
        occurrence.query_role for occurrence in occurrences if occurrence.query_role
    )
    query_ranks = tuple(occurrence.rank for occurrence in occurrences)
    rrf_score = sum(
        1.0 / (config.rrf_k + max(1, occurrence.rank))
        for occurrence in occurrences
    )
    max_possible_rrf = len(query_indices) / (config.rrf_k + 1)
    normalized_rrf = min(1.0, rrf_score / max_possible_rrf) if max_possible_rrf else 0.0
    source_refs = _source_refs(evidence_winner.memory, occurrences)
    source_types = _source_types(occurrences)
    retrieval_sources = _retrieval_sources(occurrences)
    source_diversity_count = len(tuple(dict.fromkeys((*source_types, *retrieval_sources))))
    multi_query_boost = _multi_query_boost(
        len(query_indices),
        config=config,
    )
    extra_fusion_eligible = len(query_indices) >= 3
    rrf_boost = (
        round(config.max_rrf_boost * normalized_rrf, 6)
        if extra_fusion_eligible
        else 0.0
    )
    source_diversity_boost = (
        min(config.max_source_diversity_boost, 0.01 * max(0, source_diversity_count - 1))
        if extra_fusion_eligible
        else 0.0
    )
    total_boost = round(multi_query_boost + rrf_boost + source_diversity_boost, 6)
    evidence_selection_reason_codes = _evidence_selection_reason_codes(
        score_winner,
        evidence_winner,
    )
    fusion = {
        "schema_version": "candidate_fusion.v1",
        "dedupe_key": key,
        "query_match_count": len(query_indices),
        "query_indices": list(query_indices),
        "query_roles": list(query_roles),
        "query_role_counts": dict(sorted(query_role_counts.items())),
        "bridge_query_hit": "multi_hop_bridge" in query_roles,
        "query_ranks": list(query_ranks),
        "rrf_score": round(rrf_score, 6),
        "normalized_rrf_score": round(normalized_rrf, 6),
        "source_refs": list(source_refs),
        "source_types": list(source_types),
        "retrieval_sources": list(retrieval_sources),
        "source_diversity_count": source_diversity_count,
        "extra_fusion_eligible": extra_fusion_eligible,
        "winner_score": round(score_winner.memory.score, 6),
        "score_winner_item_id": score_winner.memory.item_id,
        "score_winner_query_role": score_winner.query_role,
        "score_winner_source_type": _source_type(score_winner.memory),
        "selected_evidence_item_id": evidence_winner.memory.item_id,
        "selected_evidence_query_role": evidence_winner.query_role,
        "selected_evidence_score": round(evidence_winner.memory.score, 6),
        "selected_evidence_source_type": _source_type(evidence_winner.memory),
        "selected_evidence_quality_score": round(
            _evidence_quality_score(evidence_winner.memory),
            6,
        ),
        "evidence_selection_reason_codes": list(evidence_selection_reason_codes),
        "occurrence_scores": [
            round(occurrence.memory.score, 6) for occurrence in occurrences
        ],
        "multi_query_boost": round(multi_query_boost, 6),
        "rrf_boost": round(rrf_boost, 6),
        "source_diversity_boost": round(source_diversity_boost, 6),
        "total_boost": total_boost,
    }
    selected_memory = replace(
        evidence_winner.memory,
        rank=min(occurrence.rank for occurrence in occurrences),
        score=score_winner.memory.score,
    )
    return _with_candidate_fusion_metadata(selected_memory, fusion), fusion


def _score_winner_key(occurrence: _CandidateOccurrence) -> tuple[float, int]:
    return (occurrence.memory.score, -occurrence.rank)


def _select_evidence_winner(
    occurrences: Sequence[_CandidateOccurrence],
    *,
    score_winner: _CandidateOccurrence,
) -> _CandidateOccurrence:
    score_floor = score_winner.memory.score - _EVIDENCE_SELECTION_SCORE_BAND
    eligible = tuple(
        occurrence
        for occurrence in occurrences
        if occurrence.memory.score >= score_floor
    )
    return max(eligible or occurrences, key=_evidence_winner_key)


def _evidence_winner_key(
    occurrence: _CandidateOccurrence,
) -> tuple[float, float, float, int]:
    return (
        _evidence_quality_score(occurrence.memory),
        _query_role_focus_score(occurrence.query_role),
        occurrence.memory.score,
        -occurrence.rank,
    )


def _evidence_selection_reason_codes(
    score_winner: _CandidateOccurrence,
    evidence_winner: _CandidateOccurrence,
) -> tuple[str, ...]:
    if evidence_winner is score_winner:
        return ("score_winner",)

    reason_codes: list[str] = []
    if evidence_winner.memory.score < score_winner.memory.score:
        reason_codes.append("lower_score_within_band")
    if _source_type(evidence_winner.memory) != _source_type(score_winner.memory):
        reason_codes.append("different_source_type")
    if (
        evidence_winner.query_role != score_winner.query_role
        and _query_role_focus_score(evidence_winner.query_role)
        > _query_role_focus_score(score_winner.query_role)
    ):
        reason_codes.append("focused_query_role")
    if _evidence_quality_score(evidence_winner.memory) > _evidence_quality_score(
        score_winner.memory
    ):
        reason_codes.append("higher_evidence_quality")
    if not reason_codes:
        reason_codes.append("alternate_evidence_surface")
    return tuple(reason_codes)


def _evidence_selection_sample(fusion: Mapping[str, object]) -> dict[str, object]:
    return {
        "dedupe_key": str(fusion.get("dedupe_key") or ""),
        "reason_codes": list(
            _string_sequence(fusion.get("evidence_selection_reason_codes"))[:6]
        ),
        "query_match_count": int(fusion.get("query_match_count") or 0),
        "score_winner_item_id": str(fusion.get("score_winner_item_id") or ""),
        "score_winner_query_role": str(fusion.get("score_winner_query_role") or ""),
        "score_winner_source_type": str(fusion.get("score_winner_source_type") or ""),
        "winner_score": round(float(fusion.get("winner_score") or 0.0), 6),
        "selected_evidence_item_id": str(
            fusion.get("selected_evidence_item_id") or ""
        ),
        "selected_evidence_query_role": str(
            fusion.get("selected_evidence_query_role") or ""
        ),
        "selected_evidence_source_type": str(
            fusion.get("selected_evidence_source_type") or ""
        ),
        "selected_evidence_score": round(
            float(fusion.get("selected_evidence_score") or 0.0),
            6,
        ),
        "selected_evidence_quality_score": round(
            float(fusion.get("selected_evidence_quality_score") or 0.0),
            6,
        ),
        "source_ref_count": len(_string_sequence(fusion.get("source_refs"))),
        "source_refs_sample": list(_string_sequence(fusion.get("source_refs"))[:6]),
    }


def _query_role_focus_score(role: str) -> float:
    return _FOCUSED_QUERY_ROLE_SCORES.get(role, 0.0)


def _evidence_quality_score(memory: RetrievedMemory) -> float:
    source_refs = tuple(str(ref) for ref in memory.source_refs if str(ref).strip())
    turn_refs = tuple(
        dict.fromkeys(
            (
                *_TURN_REF_RE.findall(memory.text or ""),
                *(
                    ref
                    for source_ref in source_refs
                    for ref in _TURN_REF_RE.findall(source_ref)
                ),
            )
        )
    )
    score = 0.0
    source_type = _source_type(memory)
    if source_type == "raw_turn":
        score += 0.12
    elif source_type == "chunk":
        score += 0.06
    elif source_type == "fact":
        score += 0.04
    if 0 < len(turn_refs) <= 2:
        score += 0.12
    elif 0 < len(turn_refs) <= 3:
        score += 0.08
    elif len(turn_refs) > 3:
        score -= 0.04
    if source_refs:
        score += 0.03
    if len(memory.text or "") <= 500:
        score += 0.02
    elif len(memory.text or "") > 1200:
        score -= 0.03
    if _BROAD_SUMMARY_SURFACE_RE.search(memory.text or ""):
        score -= 0.14
    return score


def _with_candidate_fusion_metadata(
    memory: RetrievedMemory,
    fusion: Mapping[str, object],
) -> RetrievedMemory:
    query_match_count = int(fusion["query_match_count"])
    has_query_role_provenance = bool(_string_sequence(fusion.get("query_roles")))
    if query_match_count <= 1 and not has_query_role_provenance:
        return memory
    total_boost = float(fusion["total_boost"])
    diagnostics = (
        dict(memory.metadata.get("diagnostics"))
        if isinstance(memory.metadata.get("diagnostics"), Mapping)
        else {}
    )
    score_signals = (
        dict(diagnostics.get("score_signals"))
        if isinstance(diagnostics.get("score_signals"), Mapping)
        else {}
    )
    if query_match_count > 1:
        score_signals["benchmark_multi_query_match_boost"] = round(
            float(fusion["multi_query_boost"]),
            6,
        )
        score_signals["benchmark_rrf_fusion_boost"] = round(
            float(fusion["rrf_boost"]),
            6,
        )
        score_signals["benchmark_source_diversity_boost"] = round(
            float(fusion["source_diversity_boost"]),
            6,
        )
        score_signals["benchmark_candidate_fusion_boost"] = round(total_boost, 6)
        score_signals["benchmark_rrf_score"] = fusion["rrf_score"]
        score_signals["benchmark_normalized_rrf_score"] = fusion["normalized_rrf_score"]
    diagnostics["score_signals"] = score_signals
    diagnostics["benchmark_query_match_count"] = query_match_count
    diagnostics["benchmark_query_indices"] = list(fusion["query_indices"])
    diagnostics["benchmark_query_roles"] = list(fusion["query_roles"])
    diagnostics["benchmark_bridge_query_hit"] = bool(fusion["bridge_query_hit"])
    diagnostics["benchmark_query_ranks"] = list(fusion["query_ranks"])
    diagnostics["benchmark_candidate_fusion"] = dict(fusion)
    source_refs = _selected_memory_source_refs(memory, fusion)
    compacted_source_refs = len(source_refs) < len(
        _string_sequence(fusion.get("source_refs"))
    )
    if compacted_source_refs:
        diagnostics["benchmark_compacted_selected_source_refs"] = True
        diagnostics["benchmark_compacted_source_ref_count"] = len(source_refs)
    return replace(
        memory,
        score=round(memory.score + total_boost, 6),
        source_refs=source_refs,
        metadata={**dict(memory.metadata), "diagnostics": diagnostics},
    )


def _selected_memory_source_refs(
    memory: RetrievedMemory,
    fusion: Mapping[str, object],
) -> tuple[str, ...]:
    selected_refs = tuple(
        dict.fromkeys(str(ref) for ref in memory.source_refs if str(ref).strip())
    )
    merged_refs = tuple(
        dict.fromkeys((*selected_refs, *_string_sequence(fusion.get("source_refs"))))
    )
    if not selected_refs:
        return merged_refs
    if not _should_keep_selected_source_refs_compact(
        selected_refs=selected_refs,
        merged_refs=merged_refs,
        fusion=fusion,
    ):
        return merged_refs
    return selected_refs


def _should_keep_selected_source_refs_compact(
    *,
    selected_refs: Sequence[str],
    merged_refs: Sequence[str],
    fusion: Mapping[str, object],
) -> bool:
    if len(merged_refs) <= len(selected_refs):
        return False
    selected_turn_refs = _turn_refs_from_values(selected_refs)
    merged_turn_refs = _turn_refs_from_values(merged_refs)
    if not selected_turn_refs or len(selected_turn_refs) > 2:
        return False
    if len(merged_turn_refs) <= 3:
        return False
    selected_type = str(fusion.get("selected_evidence_source_type") or "")
    winner_type = str(fusion.get("score_winner_source_type") or "")
    if selected_type not in {"raw_turn", "chunk"}:
        return False
    return selected_type != winner_type or _selected_evidence_quality_score(fusion) > 0


def _selected_evidence_quality_score(fusion: Mapping[str, object]) -> float:
    try:
        selected_quality = float(fusion.get("selected_evidence_quality_score") or 0.0)
    except (TypeError, ValueError):
        selected_quality = 0.0
    return selected_quality


def _turn_refs_from_values(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            ref
            for value in values
            for ref in _TURN_REF_RE.findall(str(value))
        )
    )


def _query_role(query_roles: Sequence[str], query_index: int) -> str:
    role_index = query_index - 1
    if role_index < 0 or role_index >= len(query_roles):
        return ""
    return str(query_roles[role_index] or "").strip()


def _string_sequence(value: object) -> tuple[str, ...]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def _multi_query_boost(
    query_match_count: int,
    *,
    config: CandidateFusionConfig,
) -> float:
    if query_match_count <= 1:
        return 0.0
    return min(config.max_multi_query_boost, 0.03 * (query_match_count - 1))


def _candidate_group_key(
    memory: RetrievedMemory,
    *,
    occurrences_by_key: dict[str, list[_CandidateOccurrence]],
    key_to_group: dict[str, str],
    group_keys: dict[str, set[str]],
) -> str:
    keys = _memory_merge_keys(memory)
    existing_groups = tuple(
        dict.fromkeys(
            group
            for key in keys
            if (group := key_to_group.get(key)) is not None
            and _merge_key_sets_are_compatible(keys, group_keys.get(group, set()))
        )
    )
    if not existing_groups:
        existing_groups = _session_turn_fallback_groups(keys, group_keys)
    if not existing_groups:
        group_key = keys[0]
        group_keys[group_key] = set(keys)
        for key in keys:
            key_to_group[key] = group_key
        return group_key

    group_key = existing_groups[0]
    for other_group in existing_groups[1:]:
        if other_group == group_key:
            continue
        occurrences_by_key[group_key].extend(occurrences_by_key.pop(other_group, ()))
        group_keys[group_key].update(group_keys.pop(other_group, set()))
    group_keys[group_key].update(keys)
    for key in group_keys[group_key]:
        key_to_group[key] = group_key
    return group_key


def _memory_merge_keys(memory: RetrievedMemory) -> tuple[str, ...]:
    keys: list[str] = []
    precise_source_key = _precise_source_ref_merge_key(memory.source_refs)
    if precise_source_key:
        keys.append(precise_source_key)
    keys.extend(
        f"source_identity:{source_ref}"
        for source_ref in _source_identity_refs(memory)
    )
    if memory.item_id:
        keys.append(f"id:{memory.item_id}")
    if memory.source_refs:
        refs = tuple(sorted(dict.fromkeys(str(ref) for ref in memory.source_refs if ref)))
        keys.append(f"refs:{'|'.join(refs)}")
    keys.append(f"text:{' '.join(memory.text.casefold().split())[:240]}")
    return tuple(dict.fromkeys(keys))


def _precise_source_ref_merge_key(source_refs: Sequence[str]) -> str:
    session_turn_refs = _session_turn_refs_from_source_refs(source_refs)
    turn_refs = tuple(
        dict.fromkeys(
            ref
            for source_ref in source_refs
            for ref in _TURN_REF_RE.findall(str(source_ref))
        )
    )
    if session_turn_refs:
        if len(session_turn_refs) <= 3 and _turn_ref_count(session_turn_refs) == len(
            turn_refs
        ):
            return "source_session_turn_refs:" + "|".join(sorted(session_turn_refs))
        return ""
    if not turn_refs or len(turn_refs) > 3:
        return ""
    return "turn_refs:" + "|".join(sorted(turn_refs))


def _source_identity_refs(memory: RetrievedMemory) -> tuple[str, ...]:
    diagnostics = memory.metadata.get("diagnostics")
    diagnostics = diagnostics if isinstance(diagnostics, Mapping) else {}
    features = diagnostics.get("benchmark_candidate_features")
    features = features if isinstance(features, Mapping) else {}
    fusion = diagnostics.get("benchmark_candidate_fusion")
    fusion = fusion if isinstance(fusion, Mapping) else {}
    direct_refs = tuple(
        str(ref).strip() for ref in memory.source_refs if str(ref).strip()
    )
    refs = tuple(
        dict.fromkeys(
            (
                *source_identity_refs_from_dedupe_key(
                    features.get("source_ref_dedupe_key")
                ),
                *source_identity_refs_from_dedupe_key(fusion.get("dedupe_key")),
                *source_identity_refs_from_source_refs(
                    direct_refs,
                    include_exact_turn_refs=True,
                ),
                *source_identity_refs_from_text(memory.text, source_refs=direct_refs),
            )
        )
    )
    session_turn_refs = _session_turn_refs_from_source_refs(direct_refs)
    if not session_turn_refs:
        return refs
    session_unqualified_refs = _unqualified_turn_refs_from_session_refs(
        session_turn_refs
    )
    return tuple(
        ref
        for ref in refs
        if not (
            ref.startswith("source_turn_refs:")
            and ref in session_unqualified_refs
        )
    )


def _merge_key_sets_are_compatible(
    candidate_keys: Sequence[str],
    existing_keys: set[str],
) -> bool:
    candidate_sessions = _session_turn_refs_from_merge_keys(candidate_keys)
    existing_sessions = _session_turn_refs_from_merge_keys(existing_keys)
    if not candidate_sessions or not existing_sessions:
        return True
    return bool(set(candidate_sessions).intersection(existing_sessions))


def _session_turn_fallback_groups(
    candidate_keys: Sequence[str],
    group_keys: Mapping[str, set[str]],
) -> tuple[str, ...]:
    candidate_sessions = _session_turn_refs_from_merge_keys(candidate_keys)
    candidate_turn_refs = _unqualified_turn_refs_from_merge_keys(candidate_keys)
    groups: list[str] = []
    for group, keys in group_keys.items():
        existing_sessions = _session_turn_refs_from_merge_keys(keys)
        existing_turn_refs = _unqualified_turn_refs_from_merge_keys(keys)
        if candidate_sessions and existing_sessions:
            continue
        if candidate_sessions:
            candidate_unqualified = _unqualified_turn_refs_from_session_refs(
                candidate_sessions
            )
            if candidate_unqualified.intersection(existing_turn_refs):
                groups.append(group)
        elif existing_sessions:
            existing_unqualified = _unqualified_turn_refs_from_session_refs(
                existing_sessions
            )
            if candidate_turn_refs.intersection(existing_unqualified):
                groups.append(group)
    groups = list(dict.fromkeys(groups))
    if len(groups) != 1:
        return ()
    return (groups[0],)


def _session_turn_refs_from_source_refs(source_refs: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            f"session_{match.group('session')}:{match.group('turn_ref')}"
            for source_ref in source_refs
            if (match := _SOURCE_SESSION_TURN_RE.search(str(source_ref)))
        )
    )


def _session_turn_refs_from_merge_keys(keys: Sequence[str]) -> tuple[str, ...]:
    refs: list[str] = []
    for key in keys:
        value = str(key)
        if value.startswith("source_identity:"):
            value = value.removeprefix("source_identity:")
        if not value.startswith("source_session_turn_refs:"):
            continue
        refs.extend(
            ref
            for ref in value.removeprefix("source_session_turn_refs:").split("|")
            if ref
        )
    return tuple(dict.fromkeys(refs))


def _unqualified_turn_refs_from_merge_keys(keys: Sequence[str]) -> set[str]:
    refs: set[str] = set()
    for key in keys:
        value = str(key)
        if value.startswith("source_identity:"):
            value = value.removeprefix("source_identity:")
        if value.startswith(("source_turn_refs:", "turn_refs:")):
            refs.update(
                f"source_turn_refs:{ref}"
                for ref in value.split(":", maxsplit=1)[1].split("|")
                if ref
            )
    return refs


def _unqualified_turn_refs_from_session_refs(session_refs: Sequence[str]) -> set[str]:
    refs: set[str] = set()
    for ref in session_refs:
        match = _TURN_REF_RE.search(str(ref))
        if match is not None:
            refs.add(f"source_turn_refs:{match.group(0)}")
    return refs


def _turn_ref_count(values: Sequence[str]) -> int:
    return sum(1 for value in values if _TURN_REF_RE.search(str(value)))


def _source_refs(
    winner: RetrievedMemory,
    occurrences: Sequence[_CandidateOccurrence],
) -> tuple[str, ...]:
    values = [str(ref) for ref in winner.source_refs if str(ref).strip()]
    for occurrence in occurrences:
        values.extend(
            str(ref)
            for ref in occurrence.memory.source_refs
            if str(ref).strip()
        )
    return tuple(dict.fromkeys(values))


def _source_types(occurrences: Sequence[_CandidateOccurrence]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            _source_type(occurrence.memory)
            for occurrence in occurrences
        )
    )


def _source_type(memory: RetrievedMemory) -> str:
    value = memory.metadata.get("item_type")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "unknown"


def _retrieval_sources(occurrences: Sequence[_CandidateOccurrence]) -> tuple[str, ...]:
    values: list[str] = []
    for occurrence in occurrences:
        diagnostics = occurrence.memory.metadata.get("diagnostics")
        if not isinstance(diagnostics, Mapping):
            continue
        raw_sources = diagnostics.get("retrieval_sources")
        if not isinstance(raw_sources, Sequence) or isinstance(raw_sources, str | bytes):
            continue
        values.extend(str(source) for source in raw_sources if str(source).strip())
    return tuple(dict.fromkeys(values))
