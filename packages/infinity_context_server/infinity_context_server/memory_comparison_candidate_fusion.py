"""Candidate fusion for multi-query benchmark retrieval."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from infinity_context_server.memory_comparison_models import RetrievedMemory


@dataclass(frozen=True)
class CandidateFusionConfig:
    """Bounded fusion weights for query fanout candidates."""

    rrf_k: int = 60
    max_multi_query_boost: float = 0.12
    max_rrf_boost: float = 0.035
    max_source_diversity_boost: float = 0.02


DEFAULT_CANDIDATE_FUSION_CONFIG = CandidateFusionConfig()
_TURN_REF_RE = re.compile(r"\bD\d+:\d+\b")
_EVIDENCE_SELECTION_SCORE_BAND = 0.025


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
    bridge_query_hit_count = 0
    for key, occurrences in occurrences_by_key.items():
        fused_memory, fusion = _fuse_candidate(key, occurrences, config=config)
        fused.append(fused_memory)
        match_counts.append(int(fusion["query_match_count"]))
        rrf_scores.append(float(fusion["rrf_score"]))
        source_diversity_counts.append(int(fusion["source_diversity_count"]))
        query_role_counts.update(_string_sequence(fusion.get("query_roles")))
        if fusion.get("bridge_query_hit") is True:
            bridge_query_hit_count += 1

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
        "bridge_query_hit_count": bridge_query_hit_count,
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
        "score_winner_source_type": _source_type(score_winner.memory),
        "selected_evidence_item_id": evidence_winner.memory.item_id,
        "selected_evidence_score": round(evidence_winner.memory.score, 6),
        "selected_evidence_source_type": _source_type(evidence_winner.memory),
        "selected_evidence_quality_score": round(
            _evidence_quality_score(evidence_winner.memory),
            6,
        ),
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
) -> tuple[float, float, int]:
    return (
        _evidence_quality_score(occurrence.memory),
        occurrence.memory.score,
        -occurrence.rank,
    )


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
    source_refs = tuple(
        dict.fromkeys(
            (
                *(str(ref) for ref in memory.source_refs if str(ref).strip()),
                *_string_sequence(fusion.get("source_refs")),
            )
        )
    )
    return replace(
        memory,
        score=round(memory.score + total_boost, 6),
        source_refs=source_refs,
        metadata={**dict(memory.metadata), "diagnostics": diagnostics},
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
        dict.fromkeys(key_to_group[key] for key in keys if key in key_to_group)
    )
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
    if memory.item_id:
        keys.append(f"id:{memory.item_id}")
    if memory.source_refs:
        refs = tuple(sorted(dict.fromkeys(str(ref) for ref in memory.source_refs if ref)))
        keys.append(f"refs:{'|'.join(refs)}")
    keys.append(f"text:{' '.join(memory.text.casefold().split())[:240]}")
    return tuple(dict.fromkeys(keys))


def _precise_source_ref_merge_key(source_refs: Sequence[str]) -> str:
    turn_refs = tuple(
        dict.fromkeys(
            ref
            for source_ref in source_refs
            for ref in _TURN_REF_RE.findall(str(source_ref))
        )
    )
    if not turn_refs or len(turn_refs) > 3:
        return ""
    return "turn_refs:" + "|".join(sorted(turn_refs))


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
