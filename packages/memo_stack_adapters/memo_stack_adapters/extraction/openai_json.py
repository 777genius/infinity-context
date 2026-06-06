"""OpenAI JSON-schema memory extractor adapter."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from datetime import datetime
from importlib.resources import files
from typing import Any

from memo_stack_core.domain.entities import Confidence, MemoryKind, SourceRef
from memo_stack_core.domain.errors import MemoryInfrastructureError, MemoryValidationError
from memo_stack_core.ports.auto_memory import (
    ALLOWED_TTL_POLICIES,
    CandidateOperation,
    MemoryCandidate,
    MemoryExtractorPort,
    SourceProvenance,
)

PROMPT_VERSION = "semantic-memory-v1"
SCHEMA_VERSION = "semantic-memory-schema-v1"
EXTRACTOR_VERSION = "openai-json-memory-extractor-v1"
MAX_CANDIDATES = 20
MAX_TAGS = 10
MAX_TAG_CHARS = 48
MAX_TEXT_CHARS = 1200
MAX_SAFE_REASON_CHARS = 240
_RESPONSE_KEYS = {"candidates"}
_CANDIDATE_KEYS = {
    "text",
    "kind",
    "confidence",
    "safe_reason",
    "operation",
    "evidence_quote",
    "category",
    "tags",
    "ttl_policy",
    "target_fact_id",
    "target_fact_version",
    "target_hint",
    "valid_from",
    "valid_until",
    "expires_at",
}


class OpenAIJsonMemoryExtractor(MemoryExtractorPort):
    version = EXTRACTOR_VERSION
    prompt_version = PROMPT_VERSION
    requires_external_ai = True

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        client_factory: Callable[[], Any] | None = None,
        max_output_tokens: int = 1200,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client_factory = client_factory
        self._max_output_tokens = max_output_tokens

    async def extract_facts(
        self,
        *,
        text: str,
        source: SourceProvenance,
    ) -> tuple[MemoryCandidate, ...]:
        if not self._api_key and self._client_factory is None:
            raise MemoryInfrastructureError("extractor.openai.missing_api_key")

        client = None
        try:
            client = self._client()
            response = await client.responses.create(
                model=self._model,
                instructions=_prompt_text(),
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": text,
                            }
                        ],
                    }
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "semantic_memory_extraction",
                        "schema": _schema_json(),
                        "strict": True,
                    }
                },
                max_output_tokens=self._max_output_tokens,
                store=False,
            )
        except MemoryValidationError:
            raise
        except Exception as exc:
            raise MemoryInfrastructureError("extractor.openai.provider_error") from exc
        finally:
            await _close_client(client)

        return _parse_response(response=response, source=source, source_text=text)

    def _client(self):
        if self._client_factory is not None:
            return self._client_factory()
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=self._api_key)


def _parse_response(
    *,
    response: Any,
    source: SourceProvenance,
    source_text: str,
) -> tuple[MemoryCandidate, ...]:
    raw_text = _response_output_text(response)
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise MemoryValidationError("extractor.openai.invalid_json") from exc
    if not isinstance(payload, dict):
        raise MemoryValidationError("extractor.openai.response_not_object")
    _reject_unknown_keys(payload, _RESPONSE_KEYS, "extractor.openai.response_unknown_field")
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        raise MemoryValidationError("extractor.openai.candidates_not_array")
    if len(raw_candidates) > MAX_CANDIDATES:
        raise MemoryValidationError("extractor.openai.too_many_candidates")
    return tuple(
        _candidate_from_payload(candidate, source=source, source_text=source_text)
        for candidate in raw_candidates
    )


def _candidate_from_payload(
    payload: Any,
    *,
    source: SourceProvenance,
    source_text: str,
) -> MemoryCandidate:
    if not isinstance(payload, dict):
        raise MemoryValidationError("extractor.openai.candidate_not_object")
    _reject_unknown_keys(payload, _CANDIDATE_KEYS, "extractor.openai.candidate_unknown_field")

    operation = _enum_value(
        CandidateOperation,
        _required_str(payload, "operation", max_chars=32),
        "extractor.openai.invalid_operation",
    )
    evidence_quote = _optional_str(payload.get("evidence_quote"), max_chars=240)
    _validate_evidence_quote(
        operation=operation,
        evidence_quote=evidence_quote,
        source_text=source_text,
    )
    return MemoryCandidate(
        text=_required_str(payload, "text", max_chars=MAX_TEXT_CHARS),
        kind=_enum_value(
            MemoryKind,
            _required_str(payload, "kind", max_chars=80),
            "extractor.openai.invalid_kind",
        ),
        confidence=_enum_value(
            Confidence,
            _required_str(payload, "confidence", max_chars=16),
            "extractor.openai.invalid_confidence",
        ),
        source_refs=_source_refs(source=source, evidence_quote=evidence_quote),
        safe_reason=_required_str(payload, "safe_reason", max_chars=MAX_SAFE_REASON_CHARS),
        operation_hint=operation,
        category=_optional_str(payload.get("category"), max_chars=80),
        tags=_tags(payload.get("tags")),
        ttl_policy=_optional_ttl_policy(payload.get("ttl_policy")),
        target_fact_id=_optional_str(payload.get("target_fact_id"), max_chars=80),
        target_fact_version=_optional_int(payload.get("target_fact_version")),
        target_hint=_optional_str(payload.get("target_hint"), max_chars=240),
        valid_from=_optional_datetime(payload.get("valid_from"), field="valid_from"),
        valid_until=_optional_datetime(payload.get("valid_until"), field="valid_until"),
        expires_at=_optional_datetime(payload.get("expires_at"), field="expires_at"),
    )


def _source_refs(
    *,
    source: SourceProvenance,
    evidence_quote: str | None,
) -> tuple[SourceRef, ...]:
    if not evidence_quote:
        return ()
    return (
        SourceRef(
            source_type=source.source_type,
            source_id=source.source_id,
            chunk_id=source.chunk_id,
            quote_preview=evidence_quote,
        ),
    )


def _validate_evidence_quote(
    *,
    operation: CandidateOperation,
    evidence_quote: str | None,
    source_text: str,
) -> None:
    if operation == CandidateOperation.NOOP:
        return
    if not evidence_quote:
        raise MemoryValidationError("extractor.openai.evidence_quote_required")
    if _normalize_evidence(evidence_quote) not in _normalize_evidence(source_text):
        raise MemoryValidationError("extractor.openai.evidence_quote_not_found")


def _normalize_evidence(value: str) -> str:
    return " ".join(value.casefold().split())


def _reject_unknown_keys(payload: dict[str, Any], allowed: set[str], code: str) -> None:
    if set(payload) - allowed:
        raise MemoryValidationError(code)


def _required_str(payload: dict[str, Any], field: str, *, max_chars: int) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise MemoryValidationError(f"extractor.openai.{field}_required")
    return value.strip()[:max_chars]


def _optional_str(value: Any, *, max_chars: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MemoryValidationError("extractor.openai.invalid_string")
    normalized = value.strip()
    return normalized[:max_chars] or None


def _optional_ttl_policy(value: Any) -> str | None:
    ttl_policy = _optional_str(value, max_chars=80)
    if ttl_policy is None:
        return None
    if ttl_policy not in ALLOWED_TTL_POLICIES:
        raise MemoryValidationError("extractor.openai.invalid_ttl_policy")
    return ttl_policy


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or value < 1:
        raise MemoryValidationError("extractor.openai.invalid_integer")
    return value


def _optional_datetime(value: Any, *, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MemoryValidationError(f"extractor.openai.{field}_invalid")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MemoryValidationError(f"extractor.openai.{field}_invalid") from exc


def _tags(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise MemoryValidationError("extractor.openai.tags_not_array")
    tags: list[str] = []
    for item in value[:MAX_TAGS]:
        if not isinstance(item, str):
            raise MemoryValidationError("extractor.openai.invalid_tag")
        tag = item.strip()
        if tag:
            tags.append(tag[:MAX_TAG_CHARS])
    return tuple(tags)


def _enum_value(enum_type, value: str, code: str):
    try:
        return enum_type(value)
    except ValueError as exc:
        raise MemoryValidationError(code) from exc


def _response_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    if isinstance(response, dict):
        output_text = response.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text
    raise MemoryValidationError("extractor.openai.empty_output")


def _prompt_text() -> str:
    return files("memo_stack_adapters.extraction.prompts").joinpath(
        "semantic_memory_v1.md"
    ).read_text(encoding="utf-8")


def _schema_json() -> dict[str, Any]:
    raw = files("memo_stack_adapters.extraction.schemas").joinpath(
        "semantic_memory_v1.json"
    ).read_text(encoding="utf-8")
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise MemoryValidationError("extractor.openai.schema_invalid")
    return loaded


async def _close_client(client: object | None) -> None:
    if client is None:
        return
    for method_name in ("aclose", "close"):
        close = getattr(client, method_name, None)
        if not callable(close):
            continue
        result = close()
        if inspect.isawaitable(result):
            await result
        return
