"""Query-integrity diagnostics for memory comparison benchmark retrieval."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_models import BackendSearchResult
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

_QUERY_INTEGRITY_TOKEN_RE = re.compile(r"[0-9a-zA-Z][0-9a-zA-Z+'-]*")
_QUERY_INTEGRITY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "be",
        "been",
        "because",
        "for",
        "had",
        "has",
        "have",
        "her",
        "his",
        "in",
        "is",
        "it",
        "its",
        "of",
        "or",
        "she",
        "that",
        "the",
        "their",
        "them",
        "they",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "who",
        "why",
        "with",
        "would",
    }
)
_QUERY_PROFILE_INTEGRITY_KEYS = (
    "lexical_terms",
    "entities",
    "entity_surfaces",
    "speaker_surfaces",
    "relation_terms",
    "relation_variant_terms",
    "temporal_terms",
    "temporal_surface_terms",
    "visual_terms",
    "multi_hop_markers",
)


def query_integrity_diagnostics(
    case: PublicBenchmarkCase,
    search_result: BackendSearchResult,
) -> dict[str, object]:
    metadata = _mapping(search_result.metadata)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    queries = _retrieval_query_texts(
        metadata=metadata,
        query_decomposition=query_decomposition,
        fallback_query=search_result.query,
    )
    query_tokens = _diagnostic_token_set(" ".join(queries))
    original_question_tokens = _diagnostic_token_set(case.question)
    added_query_tokens = query_tokens - original_question_tokens
    query_profile_tokens = _query_profile_integrity_token_set(
        metadata,
        query_decomposition,
    )
    retrieval_intent_tokens = _retrieval_intent_integrity_token_set(
        metadata,
        query_decomposition,
    )
    added_query_profile_tokens = query_profile_tokens - original_question_tokens
    added_retrieval_intent_tokens = (
        retrieval_intent_tokens - original_question_tokens
    )
    expected_tokens = _query_integrity_expected_answer_token_set(case)
    added_overlap = sorted(added_query_tokens & expected_tokens)
    profile_overlap = sorted(added_query_profile_tokens & expected_tokens)
    intent_overlap = sorted(added_retrieval_intent_tokens & expected_tokens)
    original_overlap = sorted(original_question_tokens & expected_tokens)
    intent_diagnostics = _retrieval_intent_diagnostics(metadata, query_decomposition)
    return {
        "diagnostic_only": True,
        "affects_retrieval": False,
        **intent_diagnostics,
        "query_count": len(queries),
        "query_token_count": len(query_tokens),
        "added_query_token_count": len(added_query_tokens),
        "query_profile_token_count": len(query_profile_tokens),
        "added_query_profile_token_count": len(added_query_profile_tokens),
        "retrieval_intent_token_count": len(retrieval_intent_tokens),
        "added_retrieval_intent_token_count": len(added_retrieval_intent_tokens),
        "expected_token_count": len(expected_tokens),
        "expected_answer_query_overlap_count": len(added_overlap),
        "expected_answer_query_overlap_terms": added_overlap[:20],
        "expected_answer_query_profile_overlap_count": len(profile_overlap),
        "expected_answer_query_profile_overlap_terms": profile_overlap[:20],
        "expected_answer_retrieval_intent_overlap_count": len(intent_overlap),
        "expected_answer_retrieval_intent_overlap_terms": intent_overlap[:20],
        "expected_answer_original_question_overlap_count": len(original_overlap),
        "expected_answer_original_question_overlap_terms": original_overlap[:20],
    }


def _retrieval_query_texts(
    *,
    metadata: Mapping[str, object],
    query_decomposition: Mapping[str, object],
    fallback_query: str,
) -> tuple[str, ...]:
    benchmark_rerank = _mapping(metadata.get("benchmark_rerank"))
    query_expansion = _mapping(metadata.get("query_expansion"))
    values: list[str] = []
    for payload in (query_decomposition, query_expansion, benchmark_rerank):
        values.extend(_str_tuple(payload.get("queries")))
        values.extend(_str_tuple(payload.get("expanded_query")))
        values.extend(_query_plan_selected_queries(_mapping(payload.get("query_plan"))))
    values.extend(_str_tuple(fallback_query))
    return tuple(dict.fromkeys(value for value in values if value.strip()))


def _query_plan_selected_queries(query_plan: Mapping[str, object]) -> tuple[str, ...]:
    queries: list[str] = []
    for item in _sequence(query_plan.get("selected")):
        payload = _mapping(item)
        queries.extend(_str_tuple(payload.get("query")))
    return tuple(queries)


def _query_profile_integrity_token_set(
    metadata: Mapping[str, object],
    query_decomposition: Mapping[str, object],
) -> set[str]:
    tokens: set[str] = set()
    for payload in _diagnostic_query_payloads(metadata, query_decomposition):
        profile = _mapping(payload.get("query_profile"))
        for key in _QUERY_PROFILE_INTEGRITY_KEYS:
            for value in _str_tuple(profile.get(key)):
                tokens.update(_diagnostic_token_set(value))
    return tokens


def _retrieval_intent_integrity_token_set(
    metadata: Mapping[str, object],
    query_decomposition: Mapping[str, object],
) -> set[str]:
    tokens: set[str] = set()
    for payload in _diagnostic_query_payloads(metadata, query_decomposition):
        _collect_intent_tokens(tokens, _mapping(payload.get("retrieval_intent")))
    return tokens


def _collect_intent_tokens(tokens: set[str], intent: Mapping[str, object]) -> None:
    for entity in _sequence(intent.get("entities")):
        entity_payload = _mapping(entity)
        for key in ("canonical", "surfaces", "speaker_surfaces"):
            for value in _str_tuple(entity_payload.get(key)):
                tokens.update(_diagnostic_token_set(value))

    relations = _mapping(intent.get("relations"))
    for key in ("terms", "variant_terms"):
        for value in _str_tuple(relations.get(key)):
            tokens.update(_diagnostic_token_set(value))
    for relation_intent in _sequence(relations.get("intents")):
        relation_payload = _mapping(relation_intent)
        for key in ("terms", "variant_terms"):
            for value in _str_tuple(relation_payload.get(key)):
                tokens.update(_diagnostic_token_set(value))

    time_intent = _mapping(intent.get("time_intent"))
    for key in ("terms", "surface_terms"):
        for value in _str_tuple(time_intent.get(key)):
            tokens.update(_diagnostic_token_set(value))

    for key in ("visual_terms", "multi_hop_markers"):
        for value in _str_tuple(intent.get(key)):
            tokens.update(_diagnostic_token_set(value))


def _retrieval_intent_diagnostics(
    metadata: Mapping[str, object],
    query_decomposition: Mapping[str, object],
) -> dict[str, object]:
    intents = tuple(
        _mapping(payload.get("retrieval_intent"))
        for payload in _diagnostic_query_payloads(metadata, query_decomposition)
    )
    schema_versions = tuple(
        dict.fromkeys(
            str(intent.get("schema_version"))
            for intent in intents
            if intent.get("schema_version")
        )
    )
    evidence_needs = tuple(
        dict.fromkeys(
            value
            for intent in intents
            for value in _str_tuple(intent.get("evidence_need"))
        )
    )
    risk_flags = tuple(
        dict.fromkeys(
            value for intent in intents for value in _str_tuple(intent.get("risk_flags"))
        )
    )
    bundle_evidence_roles = tuple(
        dict.fromkeys(
            value
            for intent in intents
            for value in _str_tuple(intent.get("bundle_evidence_roles"))
        )
    )
    relation_categories = tuple(
        dict.fromkeys(
            category for intent in intents for category in _relation_categories(intent)
        )
    )
    return {
        "retrieval_intent_schema_versions": list(schema_versions),
        "retrieval_intent_evidence_need": list(evidence_needs),
        "retrieval_intent_bundle_evidence_roles": list(bundle_evidence_roles),
        "retrieval_intent_risk_flags": list(risk_flags),
        "retrieval_intent_relation_categories": list(relation_categories),
    }


def _diagnostic_query_payloads(
    metadata: Mapping[str, object],
    query_decomposition: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    return (
        query_decomposition,
        _mapping(metadata.get("query_expansion")),
        _mapping(metadata.get("benchmark_rerank")),
    )


def _relation_categories(intent: Mapping[str, object]) -> tuple[str, ...]:
    relations = _mapping(intent.get("relations"))
    categories: list[str] = []
    for relation_intent in _sequence(relations.get("intents")):
        payload = _mapping(relation_intent)
        category = str(payload.get("category") or "").strip()
        if category:
            categories.append(category)
    return tuple(dict.fromkeys(categories))


def _query_integrity_expected_answer_token_set(
    case: PublicBenchmarkCase,
) -> set[str]:
    metadata = _mapping(case.metadata)
    values: list[str] = [*case.expected_terms]
    for key in ("answer_preview", "answer", "expected_answer", "ground_truth", "gold_answer"):
        values.extend(_str_tuple(metadata.get(key)))
    return _diagnostic_token_set(" ".join(values))


def _diagnostic_token_set(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in _QUERY_INTEGRITY_TOKEN_RE.findall(text.casefold()):
        token = raw.strip("'-")
        if token.endswith("'s"):
            token = token[:-2]
        if len(token) >= 3 and token not in _QUERY_INTEGRITY_STOPWORDS:
            tokens.add(token)
    return tokens


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(value)
    return ()


def _str_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value if str(item).strip())
    return ()
