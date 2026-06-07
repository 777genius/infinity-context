"""Stateless helpers for the agent-facing MCP service."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from typing import Any

from memo_stack_mcp.domain.models import (
    MemoryGatewayError,
    MemoryScope,
    MemoryUpdateCandidateInput,
    has_control_characters,
    has_zero_width_characters,
    safe_message,
)


def stable_key(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest[:32]}"


def normalize_candidate(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return " ".join(normalized.strip().casefold().split())


def meaningful_terms(text: str) -> set[str]:
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "use",
        "uses",
        "user",
        "decided",
        "should",
        "memory",
    }
    return {
        token.strip(".,:;!?()[]{}\"'")
        for token in text.split()
        if len(token.strip(".,:;!?()[]{}\"'")) >= 4
        and token.strip(".,:;!?()[]{}\"'") not in stop_words
    }


def looks_equivalent_fact(candidate_text: str, existing_text: str) -> bool:
    candidate_terms = semantic_memory_terms(candidate_text)
    existing_terms = semantic_memory_terms(existing_text)
    if len(candidate_terms) < 3 or len(existing_terms) < 3:
        return False
    if _has_negation_mismatch(candidate_text, existing_text):
        return False
    if _has_exclusive_anchor_mismatch(candidate_terms, existing_terms):
        return False
    overlap = candidate_terms & existing_terms
    if len(overlap) < 3:
        return False
    union = candidate_terms | existing_terms
    if len(overlap) / len(union) >= 0.6:
        return True
    anchors = {
        "adapter",
        "canonical",
        "cognee",
        "database",
        "document",
        "graph",
        "graphiti",
        "memory",
        "mcp",
        "neo4j",
        "postgres",
        "qdrant",
        "rag",
        "temporal",
        "truth",
        "vector",
    }
    return len(overlap & anchors) >= 2 and len(overlap) / min(
        len(candidate_terms),
        len(existing_terms),
    ) >= 0.75


def semantic_memory_terms(text: str) -> set[str]:
    aliases = {
        "docs": "document",
        "doc": "document",
        "documents": "document",
        "graphs": "graph",
        "memories": "memory",
        "notes": "note",
        "retrieves": "retrieval",
        "vectors": "vector",
    }
    terms: set[str] = set()
    for raw_token in normalize_candidate(text).split():
        token = raw_token.strip(".,:;!?()[]{}\"'")
        if not token:
            continue
        token = aliases.get(token, token)
        if token.endswith("s") and len(token) > 5 and token not in {"postgres", "redis"}:
            token = token[:-1]
        if token in {
            "about",
            "again",
            "already",
            "decided",
            "durable",
            "fact",
            "only",
            "should",
            "store",
            "that",
            "this",
            "use",
            "uses",
            "using",
            "with",
        }:
            continue
        if len(token) >= 4:
            terms.add(token)
    return terms


def _has_negation_mismatch(candidate_text: str, existing_text: str) -> bool:
    negation_terms = {"avoid", "disable", "disabled", "except", "never", "not", "without"}
    candidate_has_negation = bool(set(normalize_candidate(candidate_text).split()) & negation_terms)
    existing_has_negation = bool(set(normalize_candidate(existing_text).split()) & negation_terms)
    return candidate_has_negation != existing_has_negation


def _has_exclusive_anchor_mismatch(
    candidate_terms: set[str],
    existing_terms: set[str],
) -> bool:
    engines = {"cognee", "graphiti", "mysql", "neo4j", "postgres", "qdrant", "redis", "sqlite"}
    candidate_engines = candidate_terms & engines
    existing_engines = existing_terms & engines
    return bool(candidate_engines and existing_engines and not candidate_engines & existing_engines)


def looks_conflicting_fact(candidate_text: str, existing_text: str) -> bool:
    candidate_normalized = normalize_candidate(candidate_text)
    existing_normalized = normalize_candidate(existing_text)
    if not candidate_normalized or not existing_normalized:
        return False
    if candidate_normalized == existing_normalized:
        return False
    decision_terms = {
        "adapter",
        "backend",
        "cache",
        "canonical",
        "database",
        "engine",
        "memory",
        "model",
        "provider",
        "storage",
        "truth",
        "vector",
    }
    candidate_terms = meaningful_terms(candidate_normalized)
    existing_terms = meaningful_terms(existing_normalized)
    overlap = candidate_terms & existing_terms
    return len(overlap) >= 2 and bool(overlap & decision_terms)


def payload_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def candidate_fingerprint(
    *,
    scope: MemoryScope,
    candidate: MemoryUpdateCandidateInput,
    source_id: str | None,
) -> str:
    return stable_key(
        "mcp-candidate",
        scope.space_slug,
        scope.profile_external_ref,
        scope.thread_external_ref,
        candidate.operation.value,
        candidate.target_fact_id,
        candidate.expected_version,
        normalize_candidate(candidate.text),
        source_id or "",
    )


def candidate_result(
    candidate_index: int,
    status: str,
    decision_code: str,
    *,
    text: str,
    fact_id: str | None = None,
    suggestion_id: str | None = None,
    duplicate_id: str | None = None,
    target_fact_id: str | None = None,
    retryable: bool = False,
    message: str | None = None,
) -> dict[str, Any]:
    resource_uri = f"memory://fact/{fact_id}" if fact_id else None
    return {
        "candidate_index": candidate_index,
        "status": status,
        "decision_code": decision_code,
        "text": text,
        "fact_id": fact_id,
        "suggestion_id": suggestion_id,
        "duplicate_id": duplicate_id,
        "target_fact_id": target_fact_id,
        "resource_uri": resource_uri,
        "retryable": retryable,
        "message": message,
    }


def resource_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def bounded_resource_value(value: Any, *, max_string_chars: int) -> tuple[Any, bool]:
    if isinstance(value, str):
        if len(value) <= max_string_chars:
            return value, False
        return value[:max_string_chars] + "\n[truncated]", True
    if isinstance(value, list):
        bounded_items: list[Any] = []
        truncated = False
        for item in value:
            bounded_item, item_truncated = bounded_resource_value(
                item,
                max_string_chars=max_string_chars,
            )
            bounded_items.append(bounded_item)
            truncated = truncated or item_truncated
        return bounded_items, truncated
    if isinstance(value, dict):
        bounded_dict: dict[str, Any] = {}
        truncated = False
        for key, item in value.items():
            bounded_item, item_truncated = bounded_resource_value(
                item,
                max_string_chars=max_string_chars,
            )
            bounded_dict[str(key)] = bounded_item
            truncated = truncated or item_truncated
        return bounded_dict, truncated
    return value, False


def generated_at() -> str:
    return datetime.now(UTC).isoformat()


def ensure_choice(field_name: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        raise MemoryGatewayError(
            status_code=400,
            code="memo_stack_mcp.validation.invalid_input",
            message=f"Invalid {field_name}: {safe_message(value)}",
            retryable=False,
        )


def ensure_bool(field_name: str, value: object) -> None:
    if not isinstance(value, bool):
        raise MemoryGatewayError(
            status_code=400,
            code="memo_stack_mcp.validation.invalid_input",
            message=f"{field_name} must be a boolean",
            retryable=False,
        )


def clamp_int(
    *,
    name: str,
    value: int,
    minimum: int,
    maximum: int,
) -> tuple[int, list[str]]:
    if value < minimum:
        return minimum, [f"{name}_clamped_to_min"]
    if value > maximum:
        return maximum, [f"{name}_clamped_to_max"]
    return value, []


def sanitize_source_path(value: str) -> str:
    if has_control_characters(value) or has_zero_width_characters(value):
        raise MemoryGatewayError(
            status_code=400,
            code="memo_stack_mcp.validation.invalid_source_ref",
            message="Source id contains unsafe formatting characters",
            retryable=False,
        )
    if value.startswith(("/Users/", "/home/")) or "\\Users\\" in value:
        return stable_key("mcp-source-path", value)
    return value
