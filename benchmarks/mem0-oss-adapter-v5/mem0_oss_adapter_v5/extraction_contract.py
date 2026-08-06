"""Pure Mem0 2.0.15 extraction authority shared by every v5 boundary."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from weakref import ReferenceType, ref

from mem0.configs.prompts import (
    ADDITIVE_EXTRACTION_PROMPT,
    AGENT_CONTEXT_SUFFIX,
    generate_additive_extraction_prompt,
)
from mem0.memory.utils import parse_messages

from .domain import (
    AdapterContractError,
    ExtractionMemory,
    canonical_json_bytes,
    canonical_sha256,
    sha256_bytes,
)

EXTRACTION_MODEL = "gpt-5.6-sol"
EXTRACTION_MAX_TOKENS = 4096
MAX_SOURCE_MESSAGES = 100
MAX_SOURCE_CONTENT_BYTES = 16_384
MAX_EXTRACTION_REQUEST_BYTES = 1_048_576
MAX_EXTRACTION_OUTPUT_BYTES = 262_144
MAX_EXTRACTED_MEMORIES = 128
MAX_EXTRACTED_TEXT_BYTES = 4096
MAX_LINKS_PER_MEMORY = 32
MAX_EXISTING_MEMORIES = 10
MAX_LAST_MESSAGES = 10
MAX_RECENT_MEMORIES = 20
MAX_CONTEXT_TEXT_BYTES = 65_536
MAX_CONTEXT_SEQUENCE_ITEMS = 10_000

_SAFE_MEMORY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_REQUESTS: dict[int, tuple[ReferenceType[object], str]] = {}
_REQUEST_SEAL = object()

_EXTRACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "memory": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "attributed_to": {"type": "string", "enum": ["user", "assistant"]},
                    "linked_memory_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["id", "text", "attributed_to", "linked_memory_ids"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["memory"],
    "additionalProperties": False,
}

_EXTRACTION_RESPONSE_FORMAT: dict[str, object] = {
    "type": "json_schema",
    "json_schema": {
        "name": "mem0_memory_extraction_v5",
        "strict": True,
        "schema": _EXTRACTION_SCHEMA,
    },
}

EXTRACTION_SCHEMA_SHA256 = canonical_sha256(_EXTRACTION_SCHEMA)
EXTRACTION_RESPONSE_FORMAT_SHA256 = canonical_sha256(_EXTRACTION_RESPONSE_FORMAT)
EXTRACTION_SYSTEM_PROMPT_SHA256 = sha256_bytes(ADDITIVE_EXTRACTION_PROMPT.encode("utf-8"))


def extraction_response_format() -> dict[str, object]:
    """Return a defensive copy so callers cannot mutate the authority."""

    return json.loads(canonical_json_bytes(_EXTRACTION_RESPONSE_FORMAT))


@dataclass(frozen=True, slots=True, repr=False, weakref_slot=True, init=False)
class ExtractionRequest:
    body: bytes = field(repr=False)
    request_body_sha256: str
    response_format_sha256: str = EXTRACTION_RESPONSE_FORMAT_SHA256
    response_schema_sha256: str = EXTRACTION_SCHEMA_SHA256
    max_tokens: int = EXTRACTION_MAX_TOKENS
    allowed_existing_memory_ids: tuple[str, ...] = ()

    def __init__(
        self,
        *,
        body: bytes,
        request_body_sha256: str,
        response_format_sha256: str = EXTRACTION_RESPONSE_FORMAT_SHA256,
        response_schema_sha256: str = EXTRACTION_SCHEMA_SHA256,
        max_tokens: int = EXTRACTION_MAX_TOKENS,
        allowed_existing_memory_ids: tuple[str, ...] = (),
        _seal: object | None = None,
    ) -> None:
        if _seal is not _REQUEST_SEAL:
            raise AdapterContractError("mem0_v5_extraction_request_unissued")
        object.__setattr__(self, "body", body)
        object.__setattr__(self, "request_body_sha256", request_body_sha256)
        object.__setattr__(self, "response_format_sha256", response_format_sha256)
        object.__setattr__(self, "response_schema_sha256", response_schema_sha256)
        object.__setattr__(self, "max_tokens", max_tokens)
        object.__setattr__(self, "allowed_existing_memory_ids", allowed_existing_memory_ids)
        if (
            type(self.body) is not bytes
            or not self.body
            or len(self.body) > MAX_EXTRACTION_REQUEST_BYTES
            or sha256_bytes(self.body) != self.request_body_sha256
            or self.response_format_sha256 != EXTRACTION_RESPONSE_FORMAT_SHA256
            or self.response_schema_sha256 != EXTRACTION_SCHEMA_SHA256
            or self.max_tokens != EXTRACTION_MAX_TOKENS
            or type(self.allowed_existing_memory_ids) is not tuple
            or len(self.allowed_existing_memory_ids) > MAX_EXISTING_MEMORIES
            or len(set(self.allowed_existing_memory_ids)) != len(self.allowed_existing_memory_ids)
            or any(
                type(item) is not str or _SAFE_MEMORY_ID.fullmatch(item) is None
                for item in self.allowed_existing_memory_ids
            )
        ):
            raise AdapterContractError("mem0_v5_extraction_request_invalid")
        _validate_request_body(self)
        _register_request(self)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(request_body_sha256={self.request_body_sha256!r}, "
            f"body_bytes={len(self.body)}, max_tokens={self.max_tokens}, "
            f"existing_memory_count={len(self.allowed_existing_memory_ids)})"
        )


def build_extraction_request(
    source_messages: Sequence[Mapping[str, str]],
    *,
    current_date: str,
    timestamp: str,
    existing_memories: Sequence[Mapping[str, str]] = (),
    last_k_messages: Sequence[Mapping[str, str]] = (),
    recently_extracted_memories: Sequence[Mapping[str, str]] = (),
    summary: str | None = None,
    custom_instructions: str | None = None,
    agent_scoped: bool = False,
    use_input_language: bool = False,
    max_tokens: int = EXTRACTION_MAX_TOKENS,
) -> ExtractionRequest:
    """Project the exact pinned Mem0 additive prompt with bounded context."""

    if max_tokens != EXTRACTION_MAX_TOKENS:
        raise AdapterContractError("mem0_v5_extraction_token_limit_invalid")
    normalized = _normalize_source_messages(source_messages)
    normalized_existing = _normalize_memory_context(
        _select_context_window(
            existing_memories,
            limit=MAX_EXISTING_MEMORIES,
            from_end=False,
            code="mem0_v5_memory_context_invalid",
        )
    )
    normalized_recent = _normalize_memory_context(
        _select_context_window(
            recently_extracted_memories,
            limit=MAX_RECENT_MEMORIES,
            from_end=True,
            code="mem0_v5_memory_context_invalid",
        )
    )
    normalized_last = _normalize_history(
        _select_context_window(
            last_k_messages,
            limit=MAX_LAST_MESSAGES,
            from_end=True,
            code="mem0_v5_history_invalid",
        )
    )
    normalized_summary = _bounded_optional_text(summary, "mem0_v5_summary_invalid")
    normalized_instructions = _bounded_optional_text(
        custom_instructions,
        "mem0_v5_custom_instructions_invalid",
    )
    normalized_current_date = _iso_date(current_date, "mem0_v5_current_date_invalid")
    normalized_timestamp = _iso_date(timestamp, "mem0_v5_observation_date_invalid")
    if type(agent_scoped) is not bool or type(use_input_language) is not bool:
        raise AdapterContractError("mem0_v5_extraction_context_invalid")

    system_prompt = ADDITIVE_EXTRACTION_PROMPT
    if agent_scoped:
        system_prompt += AGENT_CONTEXT_SUFFIX
    user_prompt = generate_additive_extraction_prompt(
        summary=normalized_summary,
        recently_extracted_memories=normalized_recent,
        existing_memories=normalized_existing,
        new_messages=parse_messages(normalized),
        last_k_messages=normalized_last,
        current_date=normalized_current_date,
        timestamp=normalized_timestamp,
        custom_instructions=normalized_instructions,
        use_input_language=use_input_language,
    )
    payload: dict[str, object] = {
        "max_tokens": EXTRACTION_MAX_TOKENS,
        "messages": [
            {"content": system_prompt, "role": "system"},
            {"content": user_prompt, "role": "user"},
        ],
        "model": EXTRACTION_MODEL,
        "response_format": extraction_response_format(),
        "temperature": 0,
    }
    body = canonical_json_bytes(payload)
    if len(body) > MAX_EXTRACTION_REQUEST_BYTES:
        raise AdapterContractError("mem0_v5_extraction_request_too_large")
    return ExtractionRequest(
        body=body,
        request_body_sha256=sha256_bytes(body),
        allowed_existing_memory_ids=tuple(item["id"] for item in normalized_existing),
        _seal=_REQUEST_SEAL,
    )


def parse_extraction_output(
    raw_output: str,
    *,
    allowed_existing_memory_ids: Sequence[str] = (),
) -> tuple[ExtractionMemory, ...]:
    """Validate complete output and permit links only to supplied existing memories."""

    if type(raw_output) is not str:
        raise AdapterContractError("mem0_v5_extraction_output_invalid")
    encoded = raw_output.encode("utf-8")
    if not encoded or len(encoded) > MAX_EXTRACTION_OUTPUT_BYTES:
        raise AdapterContractError("mem0_v5_extraction_output_too_large")
    try:
        payload = json.loads(raw_output, object_pairs_hook=_strict_json_object)
    except json.JSONDecodeError:
        raise AdapterContractError("mem0_v5_extraction_output_invalid") from None
    if type(payload) is not dict or set(payload) != {"memory"}:
        raise AdapterContractError("mem0_v5_extraction_output_invalid")
    items = payload["memory"]
    if type(items) is not list or len(items) > MAX_EXTRACTED_MEMORIES:
        raise AdapterContractError("mem0_v5_extraction_output_invalid")
    valid_links = _valid_existing_ids(allowed_existing_memory_ids)

    memories: list[ExtractionMemory] = []
    for index, raw in enumerate(items):
        if type(raw) is not dict or set(raw) != {
            "id",
            "text",
            "attributed_to",
            "linked_memory_ids",
        }:
            raise AdapterContractError("mem0_v5_extraction_output_invalid")
        identifier = raw["id"]
        text = raw["text"]
        attributed_to = raw["attributed_to"]
        links = raw["linked_memory_ids"]
        if (
            identifier != str(index)
            or type(text) is not str
            or not text.strip()
            or text != text.strip()
            or len(text.encode("utf-8")) > MAX_EXTRACTED_TEXT_BYTES
            or type(attributed_to) is not str
            or attributed_to not in {"user", "assistant"}
            or type(links) is not list
            or len(links) > MAX_LINKS_PER_MEMORY
            or any(type(link) is not str for link in links)
            or len(set(links)) != len(links)
            or any(link not in valid_links for link in links)
        ):
            raise AdapterContractError("mem0_v5_extraction_output_invalid")
        memories.append(
            ExtractionMemory(
                id=identifier,
                text=text,
                attributed_to=attributed_to,
                linked_memory_ids=tuple(links),
            )
        )
    return tuple(memories)


def require_authentic_extraction_request(value: object) -> ExtractionRequest:
    if type(value) is not ExtractionRequest:
        raise AdapterContractError("mem0_v5_extraction_request_unauthentic")
    try:
        _validate_request_body(value)
        snapshot = _request_snapshot(value)
    except (AttributeError, TypeError, ValueError, AdapterContractError):
        raise AdapterContractError("mem0_v5_extraction_request_unauthentic") from None
    registered = _REQUESTS.get(id(value))
    if registered is None or registered[0]() is not value or registered[1] != snapshot:
        raise AdapterContractError("mem0_v5_extraction_request_unauthentic")
    return value


def snapshot_authentic_extraction_request(value: object) -> ExtractionRequest:
    """Capture immutable request primitives and bind them to the issued snapshot."""

    if type(value) is not ExtractionRequest:
        raise AdapterContractError("mem0_v5_extraction_request_unauthentic")
    try:
        body = value.body
        request_body_sha256 = value.request_body_sha256
        response_format_sha256 = value.response_format_sha256
        response_schema_sha256 = value.response_schema_sha256
        max_tokens = value.max_tokens
        allowed_existing_memory_ids = value.allowed_existing_memory_ids
        if type(body) is not bytes or type(allowed_existing_memory_ids) is not tuple:
            raise AdapterContractError("mem0_v5_extraction_request_unauthentic")
        copied = ExtractionRequest(
            body=body,
            request_body_sha256=request_body_sha256,
            response_format_sha256=response_format_sha256,
            response_schema_sha256=response_schema_sha256,
            max_tokens=max_tokens,
            allowed_existing_memory_ids=allowed_existing_memory_ids,
            _seal=_REQUEST_SEAL,
        )
        copied_snapshot = _request_snapshot(copied)
    except (AttributeError, TypeError, ValueError, AdapterContractError):
        raise AdapterContractError("mem0_v5_extraction_request_unauthentic") from None
    registered = _REQUESTS.get(id(value))
    if registered is None or registered[0]() is not value or registered[1] != copied_snapshot:
        raise AdapterContractError("mem0_v5_extraction_request_unauthentic")
    return copied


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AdapterContractError("mem0_v5_extraction_output_invalid")
        result[key] = value
    return result


def _normalize_source_messages(
    source_messages: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    if (
        type(source_messages) not in {list, tuple}
        or not 1 <= len(source_messages) <= MAX_SOURCE_MESSAGES
    ):
        raise AdapterContractError("mem0_v5_source_messages_invalid")
    normalized: list[dict[str, str]] = []
    for item in source_messages:
        if type(item) is not dict or set(item) != {"role", "content"}:
            raise AdapterContractError("mem0_v5_source_messages_invalid")
        role = item["role"]
        content = item["content"]
        if (
            type(role) is not str
            or role not in {"user", "assistant"}
            or type(content) is not str
            or not content
            or len(content.encode("utf-8")) > MAX_SOURCE_CONTENT_BYTES
        ):
            raise AdapterContractError("mem0_v5_source_messages_invalid")
        normalized.append({"content": content, "role": role})
    return normalized


def _normalize_memory_context(
    memories: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    if type(memories) not in {list, tuple} or len(memories) > MAX_RECENT_MEMORIES:
        raise AdapterContractError("mem0_v5_memory_context_invalid")
    normalized: list[dict[str, str]] = []
    for item in memories:
        if type(item) is not dict or set(item) != {"id", "text"}:
            raise AdapterContractError("mem0_v5_memory_context_invalid")
        identifier = item["id"]
        text = item["text"]
        if (
            type(identifier) is not str
            or _SAFE_MEMORY_ID.fullmatch(identifier) is None
            or type(text) is not str
            or not text
            or len(text.encode("utf-8")) > MAX_EXTRACTED_TEXT_BYTES
        ):
            raise AdapterContractError("mem0_v5_memory_context_invalid")
        normalized.append({"id": identifier, "text": text})
    if len({item["id"] for item in normalized}) != len(normalized):
        raise AdapterContractError("mem0_v5_memory_context_invalid")
    return normalized


def _normalize_history(
    messages: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    if type(messages) not in {list, tuple} or len(messages) > MAX_LAST_MESSAGES:
        raise AdapterContractError("mem0_v5_history_invalid")
    normalized: list[dict[str, str]] = []
    for item in messages:
        if type(item) is not dict or set(item) != {"role", "content"}:
            raise AdapterContractError("mem0_v5_history_invalid")
        role = item["role"]
        content = item["content"]
        if (
            type(role) is not str
            or role not in {"user", "assistant", "system"}
            or type(content) is not str
            or not content
            or len(content.encode("utf-8")) > MAX_SOURCE_CONTENT_BYTES
        ):
            raise AdapterContractError("mem0_v5_history_invalid")
        normalized.append({"content": content, "role": role})
    return normalized


def _select_context_window(
    values: Sequence[Mapping[str, str]],
    *,
    limit: int,
    from_end: bool,
    code: str,
) -> list[Mapping[str, str]] | tuple[Mapping[str, str], ...]:
    """Slice a bounded built-in sequence before any element normalization."""

    if type(values) not in {list, tuple} or not 0 <= len(values) <= MAX_CONTEXT_SEQUENCE_ITEMS:
        raise AdapterContractError(code)
    return values[-limit:] if from_end else values[:limit]


def _bounded_optional_text(value: str | None, code: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or len(value.encode("utf-8")) > MAX_CONTEXT_TEXT_BYTES:
        raise AdapterContractError(code)
    return value


def _iso_date(value: str, code: str) -> str:
    if type(value) is not str:
        raise AdapterContractError(code)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise AdapterContractError(code) from None
    if parsed.isoformat() != value:
        raise AdapterContractError(code)
    return value


def _valid_existing_ids(values: Sequence[str]) -> set[str]:
    if (
        type(values) not in {tuple, list}
        or len(values) > MAX_EXISTING_MEMORIES
        or len(set(values)) != len(values)
        or any(type(item) is not str or _SAFE_MEMORY_ID.fullmatch(item) is None for item in values)
    ):
        raise AdapterContractError("mem0_v5_existing_memory_links_invalid")
    return set(values)


def _validate_request_body(value: ExtractionRequest) -> None:
    try:
        payload = json.loads(value.body.decode("utf-8"), object_pairs_hook=_strict_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise AdapterContractError("mem0_v5_extraction_request_invalid") from None
    if type(payload) is not dict or set(payload) != {
        "max_tokens",
        "messages",
        "model",
        "response_format",
        "temperature",
    }:
        raise AdapterContractError("mem0_v5_extraction_request_invalid")
    messages = payload["messages"]
    if (
        canonical_json_bytes(payload) != value.body
        or payload["max_tokens"] != EXTRACTION_MAX_TOKENS
        or payload["model"] != EXTRACTION_MODEL
        or payload["response_format"] != extraction_response_format()
        or payload["temperature"] != 0
        or type(messages) is not list
        or len(messages) != 2
        or type(messages[0]) is not dict
        or set(messages[0]) != {"content", "role"}
        or messages[0]["role"] != "system"
        or messages[0]["content"]
        not in {ADDITIVE_EXTRACTION_PROMPT, ADDITIVE_EXTRACTION_PROMPT + AGENT_CONTEXT_SUFFIX}
        or type(messages[1]) is not dict
        or set(messages[1]) != {"content", "role"}
        or messages[1]["role"] != "user"
        or type(messages[1]["content"]) is not str
        or not messages[1]["content"]
    ):
        raise AdapterContractError("mem0_v5_extraction_request_invalid")


def _request_snapshot(value: ExtractionRequest) -> str:
    return canonical_sha256(
        {
            "allowed_existing_memory_ids": list(value.allowed_existing_memory_ids),
            "body_sha256": sha256_bytes(value.body),
            "max_tokens": value.max_tokens,
            "request_body_sha256": value.request_body_sha256,
            "response_format_sha256": value.response_format_sha256,
            "response_schema_sha256": value.response_schema_sha256,
        }
    )


def _register_request(value: ExtractionRequest) -> None:
    identity = id(value)

    def discard(reference: ReferenceType[object]) -> None:
        current = _REQUESTS.get(identity)
        if current is not None and current[0] is reference:
            _REQUESTS.pop(identity, None)

    reference = ref(value, discard)
    _REQUESTS[identity] = (reference, _request_snapshot(value))


__all__ = [
    "EXTRACTION_MAX_TOKENS",
    "EXTRACTION_MODEL",
    "EXTRACTION_RESPONSE_FORMAT_SHA256",
    "EXTRACTION_SCHEMA_SHA256",
    "EXTRACTION_SYSTEM_PROMPT_SHA256",
    "ExtractionRequest",
    "build_extraction_request",
    "extraction_response_format",
    "parse_extraction_output",
    "require_authentic_extraction_request",
    "snapshot_authentic_extraction_request",
]
