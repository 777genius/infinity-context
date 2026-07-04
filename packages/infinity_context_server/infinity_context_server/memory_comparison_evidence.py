"""Evidence coverage helpers for memory comparison benchmark reports."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_bundle_planner import (
    EvidenceBundleCandidate,
    EvidenceBundlePlanner,
)
from infinity_context_server.memory_comparison_candidate_risks import (
    candidate_features as _candidate_feature_diagnostics,
)
from infinity_context_server.memory_comparison_candidate_risks import (
    memory_has_broad_summary,
    memory_has_conflict_or_stale,
)
from infinity_context_server.memory_comparison_intent import infer_bundle_evidence_roles
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_rerank import (
    query_retrieval_intent,
    query_support_terms,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

_TURN_REF_RE = re.compile(r"\bD\d+:\d+\b")
_BROAD_EVIDENCE_SURFACE_RE = re.compile(
    r"^\s*session_\d+\s+(?:date|observations|events)\b",
    re.IGNORECASE,
)
_DURATION_EVIDENCE_RE = re.compile(
    r"\b(?:(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s*"
    r"(?:days?|weeks?|months?|years?|decades?)|"
    r"for\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"a|an|few|a\s+few|several|many|a\s+couple\s+of|couple\s+of)\s*"
    r"(?:days?|weeks?|months?|years?|decades?)|"
    r"since\s+(?:(?:19|20)\d{2}|last\s+"
    r"(?:year|month|week|spring|summer|fall|autumn|winter)))\b",
    re.IGNORECASE,
)
_TEMPORAL_EVIDENCE_RE = re.compile(
    r"\b(?:date:|session[_\s-]?\d+|today|yesterday|tomorrow|ago|"
    r"tonight|last|next|before|beforehand|after|afterward|afterwards|"
    r"earlier|later|"
    r"morning|afternoon|evening|weekend|quarter|month|year|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
_RELATIVE_TEMPORAL_EVIDENCE_RE = re.compile(
    r"\b(?:today|yesterday|tomorrow|ago|recently|recent|lately|tonight|"
    r"earlier\s+today|"
    r"(?:today|tomorrow|yesterday)\s+(?:morning|afternoon|evening)|"
    r"(?:last|next|this|previous)\s+"
    r"(?:night|morning|afternoon|evening|week|weekend|month|quarter|year)|"
    r"last|next|previously|previous|earlier|later|back then|these days)\b",
    re.IGNORECASE,
)


def retrieval_quality(
    case: PublicBenchmarkCase,
    memories: Sequence[RetrievedMemory],
) -> dict[str, object]:
    text_corpus = _normalize_text(" ".join(memory.text for memory in memories))
    covered_terms = tuple(
        term
        for term in case.expected_terms
        if _normalized_phrase_in_text(text_corpus, term)
    )
    missing_terms = tuple(term for term in case.expected_terms if term not in covered_terms)
    quality: dict[str, object] = {
        "expected_term_count": len(case.expected_terms),
        "covered_expected_term_count": len(covered_terms),
        "expected_term_recall": _ratio(len(covered_terms), len(case.expected_terms)),
        "covered_terms": list(covered_terms),
        "missing_terms": list(missing_terms),
    }
    evidence_terms = _metadata_terms(case, "evidence_terms")
    if evidence_terms:
        evidence_ref_corpus = _normalize_text(
            " ".join(_memory_evidence_surface(memory) for memory in memories)
        )
        covered_evidence_terms = tuple(
            term
            for term in evidence_terms
            if _normalized_phrase_in_text(evidence_ref_corpus, term)
        )
        quality.update(
            {
                "evidence_term_count": len(evidence_terms),
                "covered_evidence_term_count": len(covered_evidence_terms),
                "evidence_term_recall": _ratio(
                    len(covered_evidence_terms),
                    len(evidence_terms),
                ),
                "covered_evidence_terms": list(covered_evidence_terms),
                "missing_evidence_terms": [
                    term for term in evidence_terms if term not in covered_evidence_terms
                ],
            }
        )
    return quality


def evidence_bundle(
    case: PublicBenchmarkCase,
    memories: Sequence[RetrievedMemory],
) -> dict[str, object]:
    evidence_terms = _metadata_terms(case, "evidence_terms")
    support_terms = query_support_terms(case)
    candidates: list[EvidenceBundleCandidate] = []
    covered_expected_terms: set[str] = set()
    covered_evidence_terms: set[str] = set()
    covered_support_terms: set[str] = set()
    case_group = _case_group(case)
    required_roles = _required_bundle_roles(case, case_group=case_group)
    temporal_role_required = "temporal_support" in required_roles

    for retrieval_order, memory in enumerate(memories, 1):
        text = _normalize_text(memory.text)
        evidence_ref_text = _normalize_text(_memory_evidence_surface(memory))
        expected_hits = tuple(
            term
            for term in case.expected_terms
            if _normalized_phrase_in_text(text, term)
        )
        evidence_hits = tuple(
            term
            for term in evidence_terms
            if _normalized_phrase_in_text(evidence_ref_text, term)
        )
        support_hits = tuple(
            term for term in support_terms if _support_phrase_in_text(text, term)
        )
        features = _candidate_feature_diagnostics(memory)
        temporal_text_features = (
            _temporal_text_features(memory.text) if temporal_role_required else {}
        )
        eligibility_reason_codes = _bundle_candidate_eligibility_reasons(
            support_hits,
            features,
        )
        if not eligibility_reason_codes:
            continue
        strength_score = _bundle_item_strength(support_hits)
        focused_evidence_score = _focused_evidence_score(memory)
        candidates.append(
            EvidenceBundleCandidate(
                rank=memory.rank,
                retrieval_order=retrieval_order,
                item_id=_memory_identifier(memory),
                covered_expected_terms=expected_hits,
                covered_evidence_terms=evidence_hits,
                query_support_terms=support_hits,
                query_support_score=_ratio(len(support_hits), len(support_terms)),
                bundle_strength_score=float(strength_score),
                focused_evidence_score=max(
                    float(focused_evidence_score),
                    _float_value(features.get("focused_turn_score")),
                ),
                primary_signal=_primary_signal(
                    support_hits,
                    features,
                    expected_hits=expected_hits,
                    evidence_hits=evidence_hits,
                ),
                dedupe_key=_candidate_dedupe_key(memory, features),
                source_refs=tuple(str(ref) for ref in memory.source_refs if ref),
                source_type=_source_type(memory, features),
                source_types=_string_sequence(features.get("source_types")),
                retrieval_sources=_string_sequence(features.get("retrieval_sources")),
                direct_speaker_turn=_bool_value(features.get("direct_speaker_turn")),
                broad_summary=memory_has_broad_summary(memory, features),
                time_intent_kind=str(features.get("time_intent_kind") or ""),
                has_temporal_surface=(
                    _bool_value(features.get("has_temporal_surface"))
                    or _bool_value(temporal_text_features.get("has_temporal_surface"))
                ),
                has_sequence_surface=(
                    _bool_value(features.get("has_sequence_surface"))
                    or _bool_value(temporal_text_features.get("has_sequence_surface"))
                ),
                has_duration_surface=_bool_value(
                    features.get("has_duration_surface")
                )
                or _bool_value(temporal_text_features.get("has_duration_surface")),
                has_relative_time_surface=_bool_value(
                    features.get("has_relative_time_surface")
                )
                or _bool_value(
                    temporal_text_features.get("has_relative_time_surface")
                ),
                has_explicit_time_surface=_bool_value(
                    features.get("has_explicit_time_surface")
                ),
                has_explicit_time_content_surface=_bool_value(
                    features.get("has_explicit_time_content_surface")
                ),
                has_temporal_sequence_surface=_bool_value(
                    features.get("has_temporal_sequence_surface")
                ),
                conflict_or_stale=memory_has_conflict_or_stale(memory, features),
                negation_surface=_bool_value(features.get("negation_surface")),
                currentness_surface=_bool_value(features.get("currentness_surface")),
                stale_surface=_bool_value(features.get("stale_surface")),
                contrast_surface=_bool_value(features.get("contrast_surface")),
                answerability_score=_float_value(features.get("answerability_score")),
                answerability_reason_codes=_string_sequence(
                    features.get("answerability_reason_codes")
                ),
                source_locality_score=_float_value(
                    features.get("source_locality_score")
                ),
                relation_hits=_string_sequence(features.get("relation_hits")),
                relation_categories=_string_sequence(
                    features.get("relation_categories")
                ),
                relation_category_hits=_string_sequence(
                    features.get("relation_category_hits")
                ),
                covered_answer_unit_shapes=_string_sequence(
                    features.get("covered_answer_unit_shapes")
                ),
                exact_count_evidence=_bool_value(features.get("exact_count_evidence")),
                list_item_count=_int_value(features.get("list_item_count")),
                entity_hits=_string_sequence(features.get("entity_hits")),
                speaker_hits=_string_sequence(features.get("speaker_hits")),
                query_has_entities=_bool_value(features.get("query_has_entities")),
                has_preference_evidence=_bool_value(
                    features.get("has_preference_evidence")
                ),
                has_visual_evidence=_bool_value(features.get("has_visual_evidence")),
                query_roles=_string_sequence(features.get("query_roles")),
                bridge_query_hit=_bool_value(features.get("bridge_query_hit")),
                eligibility_reason_codes=eligibility_reason_codes,
            )
        )

    plan = EvidenceBundlePlanner().plan(
        candidates,
        case_group=case_group,
        required_roles=required_roles,
    )
    items = [item.to_payload() for item in plan.items]
    for item in plan.items:
        covered_expected_terms.update(item.candidate.covered_expected_terms)
        covered_evidence_terms.update(item.candidate.covered_evidence_terms)
        covered_support_terms.update(item.candidate.query_support_terms)
    primary_count = sum(1 for item in items if item["role"] == "primary")
    supporting_count = max(0, len(items) - primary_count)
    required_evidence_terms = min(2, len(evidence_terms)) if evidence_terms else 0
    evidence_bundle_complete = (
        len(covered_evidence_terms) >= required_evidence_terms
        if required_evidence_terms
        else bool(covered_expected_terms) and supporting_count > 0
    )
    evidence_bundle_complete = (
        evidence_bundle_complete and plan.role_requirement_complete
    )
    return {
        "kind": "multi_hop_evidence_bundle"
        if case_group == "multi-hop"
        else "single_evidence_bundle",
        "item_count": len(items),
        "candidate_item_count": plan.candidate_count,
        "deduplicated_item_count": plan.deduplicated_item_count,
        "primary_evidence_count": primary_count,
        "supporting_evidence_count": supporting_count,
        "bundle_planner": plan.to_diagnostics(),
        "required_roles": list(plan.required_roles),
        "satisfied_required_roles": list(plan.satisfied_required_roles),
        "missing_required_roles": list(plan.missing_required_roles),
        "role_requirement_complete": plan.role_requirement_complete,
        "covered_expected_terms": sorted(covered_expected_terms),
        "covered_evidence_terms": sorted(covered_evidence_terms),
        "query_support_terms": sorted(covered_support_terms),
        "query_support_term_count": len(support_terms),
        "query_support_term_recall": _ratio(len(covered_support_terms), len(support_terms)),
        "expected_term_recall": _ratio(len(covered_expected_terms), len(case.expected_terms)),
        "evidence_term_recall": _ratio(len(covered_evidence_terms), len(evidence_terms)),
        "evidence_term_count": len(evidence_terms),
        "required_evidence_terms_for_bundle": required_evidence_terms,
        "bundle_complete": evidence_bundle_complete,
        "items": items,
    }


def _bundle_candidate_eligibility_reasons(
    support_hits: Sequence[str],
    features: Mapping[str, object],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if len(support_hits) >= 2:
        reasons.append("query_support_terms")
    feature_reasons = _feature_backed_bundle_candidate_reasons(features)
    if feature_reasons:
        reasons.append("feature_backed")
        reasons.extend(feature_reasons)
    return tuple(dict.fromkeys(reasons))


def _primary_signal(
    support_hits: Sequence[str],
    features: Mapping[str, object],
    *,
    expected_hits: Sequence[str] = (),
    evidence_hits: Sequence[str] = (),
) -> bool:
    if len(support_hits) >= 2:
        return True
    answerability_score = _float_value(features.get("answerability_score"))
    source_locality_score = _float_value(features.get("source_locality_score"))
    if answerability_score > 0 and answerability_score < 0.75:
        return False
    if _is_measured_weak_source_locality(source_locality_score):
        return False
    relation_grounded = bool(
        _string_sequence(features.get("relation_hits"))
        or _string_sequence(features.get("relation_category_hits"))
        or _string_sequence(features.get("covered_answer_unit_shapes"))
    )
    entity_grounded = bool(
        _string_sequence(features.get("entity_hits"))
        or _string_sequence(features.get("speaker_hits"))
    )
    measured_primary = answerability_score >= 0.75
    unmeasured_but_evidence_grounded = (
        answerability_score <= 0
        and bool(expected_hits or evidence_hits)
        and relation_grounded
        and entity_grounded
    )
    return (measured_primary or unmeasured_but_evidence_grounded) and (
        relation_grounded and entity_grounded
    )


def _feature_backed_bundle_candidate_reasons(
    features: Mapping[str, object],
) -> tuple[str, ...]:
    if not features:
        return ()
    answerability_score = _float_value(features.get("answerability_score"))
    source_locality_score = _float_value(features.get("source_locality_score"))
    if _is_measured_low_answerability(answerability_score):
        return ()
    if _is_measured_weak_source_locality(source_locality_score):
        return ()

    entity_grounded = bool(
        _string_sequence(features.get("entity_hits"))
        or _string_sequence(features.get("speaker_hits"))
    )
    relation_grounded = bool(
        _string_sequence(features.get("relation_hits"))
        or _string_sequence(features.get("relation_category_hits"))
    )
    temporal_grounded = bool(
        _bool_value(features.get("has_temporal_surface"))
        or _bool_value(features.get("has_sequence_surface"))
        or _bool_value(features.get("has_duration_surface"))
        or _bool_value(features.get("has_relative_time_surface"))
        or _bool_value(features.get("has_explicit_time_content_surface"))
        or _bool_value(features.get("has_temporal_sequence_surface"))
        or _bool_value(features.get("currentness_surface"))
    )
    contrast_grounded = bool(
        _bool_value(features.get("contrast_surface"))
        or _bool_value(features.get("negation_surface"))
        or _bool_value(features.get("stale_surface"))
    )
    visual_grounded = _bool_value(features.get("has_visual_evidence"))
    answer_unit_grounded = bool(
        _string_sequence(features.get("covered_answer_unit_shapes"))
    )
    reasons: list[str] = [
        _answerability_feature_reason(answerability_score),
        _source_locality_feature_reason(source_locality_score),
    ]
    if _bool_value(features.get("direct_speaker_turn")) and (
        entity_grounded or relation_grounded
    ):
        reasons.append("direct_speaker_grounding")
    if relation_grounded and entity_grounded:
        reasons.append("entity_relation_grounding")
    if temporal_grounded and (entity_grounded or relation_grounded):
        reasons.append("temporal_grounding")
    if contrast_grounded and (entity_grounded or relation_grounded):
        reasons.append("contrast_grounding")
    if visual_grounded and (entity_grounded or relation_grounded):
        reasons.append("visual_grounding")
    if answer_unit_grounded and (entity_grounded or relation_grounded):
        reasons.append("answer_unit_grounding")
    if (
        _bool_value(features.get("bridge_query_hit"))
        and relation_grounded
        and entity_grounded
    ):
        reasons.append("bridge_grounding")
    if len(reasons) == 2:
        return ()
    return tuple(reasons)


def _is_measured_low_answerability(score: float) -> bool:
    return 0 < score < 0.55


def _is_measured_weak_source_locality(score: float) -> bool:
    return 0 < score < 0.45


def _answerability_feature_reason(score: float) -> str:
    if score <= 0:
        return "answerability_unmeasured"
    return "answerability_feature"


def _source_locality_feature_reason(score: float) -> str:
    if score <= 0:
        return "source_locality_unmeasured"
    return "source_locality_feature"


def _required_bundle_roles(
    case: PublicBenchmarkCase,
    *,
    case_group: str,
) -> tuple[str, ...]:
    intent = query_retrieval_intent(case)
    metadata_evidence_need = _metadata_string_sequence(case.metadata.get("evidence_need"))
    roles = list(intent.bundle_evidence_roles)
    if _has_structured_support_need(metadata_evidence_need):
        roles = [role for role in roles if role != "inference_support"]
    roles.extend(
        infer_bundle_evidence_roles(
            evidence_need=metadata_evidence_need,
            benchmark_category=None,
        )
    )
    roles.extend(_metadata_string_sequence(case.metadata.get("required_roles")))
    if case_group == "multi-hop" and "bridge" not in roles:
        roles.append("bridge")
    if case_group == "temporal" and "temporal_support" not in roles:
        roles.append("temporal_support")
    return _suppress_ambiguous_required_roles(tuple(dict.fromkeys(roles)))


def _suppress_ambiguous_required_roles(roles: tuple[str, ...]) -> tuple[str, ...]:
    role_set = set(roles)
    suppressed: set[str] = set()
    if "visual_support" in role_set:
        suppressed.add("activity_support")
    if "contrast" in role_set:
        suppressed.add("support_goal_support")
    if not suppressed:
        return roles
    return tuple(role for role in roles if role not in suppressed)


def _has_structured_support_need(evidence_need: Sequence[str]) -> bool:
    return bool(
        {
            "causal_support",
            "contrast",
            "location_support",
            "multi_hop",
            "temporal_sequence",
            "temporal_support",
        }
        & set(evidence_need)
    )


def _temporal_text_features(text: str) -> dict[str, bool]:
    return {
        "has_temporal_surface": bool(_TEMPORAL_EVIDENCE_RE.search(text)),
        "has_relative_time_surface": bool(
            _RELATIVE_TEMPORAL_EVIDENCE_RE.search(text)
        ),
        "has_sequence_surface": bool(
            re.search(r"\b(?:date:|session[_\s-]?\d+)\b", text, re.IGNORECASE)
        ),
        "has_duration_surface": bool(_DURATION_EVIDENCE_RE.search(text)),
    }


def _bundle_item_strength(
    support_hits: Sequence[str],
) -> int:
    return len(support_hits)


def _bundle_dedupe_key(memory: RetrievedMemory) -> str:
    if memory.source_refs:
        refs = tuple(sorted(dict.fromkeys(str(ref) for ref in memory.source_refs if ref)))
        return f"refs:{'|'.join(refs)}"
    turn_refs = tuple(dict.fromkeys(_TURN_REF_RE.findall(memory.text or "")))
    if 0 < len(turn_refs) <= 3:
        return "source_turn_refs:" + "|".join(sorted(turn_refs))
    return f"text:{_normalize_text(memory.text)[:240]}"


def _candidate_dedupe_key(
    memory: RetrievedMemory,
    features: Mapping[str, object],
) -> str:
    source_ref_dedupe_key = features.get("source_ref_dedupe_key")
    if isinstance(source_ref_dedupe_key, str) and source_ref_dedupe_key.strip():
        return source_ref_dedupe_key.strip()
    duplicate_key = features.get("duplicate_key")
    if isinstance(duplicate_key, str) and duplicate_key.strip():
        return duplicate_key.strip()
    return _bundle_dedupe_key(memory)


def _focused_evidence_score(memory: RetrievedMemory) -> int:
    text = memory.text or ""
    if _BROAD_EVIDENCE_SURFACE_RE.search(text):
        return 0
    turn_refs = tuple(dict.fromkeys(_TURN_REF_RE.findall(text)))
    if 0 < len(turn_refs) <= 2:
        return 1
    source_turn_refs = tuple(
        ref for ref in memory.source_refs if _TURN_REF_RE.search(str(ref))
    )
    return 1 if source_turn_refs and len(memory.source_refs) <= 3 else 0


def _memory_evidence_surface(memory: RetrievedMemory) -> str:
    return " ".join((memory.text, *memory.source_refs))


def _source_type(memory: RetrievedMemory, features: Mapping[str, object]) -> str:
    feature_source_type = features.get("source_type")
    if isinstance(feature_source_type, str) and feature_source_type.strip():
        return feature_source_type.strip()
    metadata_source_type = memory.metadata.get("item_type")
    if isinstance(metadata_source_type, str) and metadata_source_type.strip():
        return metadata_source_type.strip()
    return "unknown"


def _normalized_phrase_in_text(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return False
    return bool(re.search(rf"(?:^| ){re.escape(normalized_phrase)}(?:$| )", normalized_text))


def _support_phrase_in_text(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return False
    if _normalized_phrase_in_text(normalized_text, normalized_phrase):
        return True
    return any(
        _normalized_phrase_in_text(normalized_text, variant)
        for variant in _support_phrase_variants(normalized_phrase)
    )


def _support_phrase_variants(normalized_phrase: str) -> tuple[str, ...]:
    if " " in normalized_phrase or len(normalized_phrase) < 4:
        return ()
    variants = {
        f"{normalized_phrase}s",
        f"{normalized_phrase}ed",
        f"{normalized_phrase}ing",
    }
    if normalized_phrase.endswith("e"):
        variants.add(f"{normalized_phrase}d")
        variants.add(f"{normalized_phrase[:-1]}ing")
    if normalized_phrase.endswith("y"):
        variants.add(f"{normalized_phrase[:-1]}ies")
    return tuple(sorted(variants))


def _metadata_terms(case: PublicBenchmarkCase, key: str) -> tuple[str, ...]:
    return tuple(
        str(term).strip()
        for term in case.metadata.get(key, ())
        if str(term).strip()
    )


def _metadata_string_sequence(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, Sequence):
        values = value
    else:
        values = ()
    return tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _memory_identifier(memory: RetrievedMemory) -> str:
    if memory.item_id:
        return memory.item_id
    if memory.source_refs:
        return memory.source_refs[0]
    return f"rank:{memory.rank}"


def _case_group(case: PublicBenchmarkCase) -> str:
    category = _optional_int(case.metadata.get("category"))
    if case.benchmark == "locomo" and category == 1:
        return "multi-hop"
    if case.benchmark == "locomo" and category == 2:
        return "temporal"
    if case.benchmark == "locomo" and category == 3:
        return "open-domain"
    if case.benchmark == "locomo" and category == 4:
        return "single-hop"
    return str(case.metadata.get("capability") or "unknown")


def _normalize_text(value: str) -> str:
    normalized = re.sub(r"[^0-9a-z]+", " ", str(value or "").casefold())
    return " ".join(normalized.split())


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _numeric_value(value: object) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _float_value(value: object) -> float:
    return _numeric_value(value)


def _int_value(value: object) -> int:
    return int(_numeric_value(value))


def _bool_value(value: object) -> bool:
    return value is True


def _string_sequence(value: object) -> tuple[str, ...]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
