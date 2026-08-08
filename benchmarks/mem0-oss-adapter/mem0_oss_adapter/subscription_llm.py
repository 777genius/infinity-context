"""A narrow, bounded OpenAI-compatible bridge used only for Mem0 extraction."""

from __future__ import annotations

import asyncio
import contextvars
import ipaddress
import json
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from mem0.configs.llms.base import BaseLlmConfig
from mem0.llms.base import LLMBase

from mem0_oss_adapter.usage import (
    FIXED_EXTRACTION_MODEL,
    MAX_USAGE_OPERATIONS,
    RunUsageAggregate,
    UsageEvidenceError,
)

_MODEL = FIXED_EXTRACTION_MODEL
_MODE = Literal["raw_passthrough", "subscription_llm"]
_MEM0_JSON_OBJECT_RESPONSE_FORMAT = {"type": "json_object"}
_SUBSCRIPTION_BRIDGE_TIMEOUT_SECONDS = 180.0


class SubscriptionBridgeError(RuntimeError):
    """A sanitized bridge failure that never embeds upstream response content."""


class ExtractionCallLimitError(SubscriptionBridgeError):
    """Raised before a second extraction request can leave the adapter."""


@dataclass(frozen=True, slots=True)
class UsageLedgerEntry:
    run_id: str
    operation: str
    mode: str
    extraction_calls: int
    request_bytes: int
    response_bytes: int
    model: str
    created_at: str


@dataclass(slots=True)
class _UsageOperation:
    run_id: str
    operation: str
    mode: _MODE
    max_calls: int
    request_max_bytes: int
    response_max_bytes: int
    created_at: str
    extraction_calls: int = 0
    request_bytes: int = 0
    response_bytes: int = 0


class UsageLedger:
    """Request-local accounting with a hard pre-flight extraction budget."""

    def __init__(self, *, model: str = _MODEL) -> None:
        if model != _MODEL:
            raise ValueError("subscription model must be gpt-5.6-sol")
        self._model = model
        self._entries: list[UsageLedgerEntry] = []
        self._entries_lock = threading.RLock()
        self._current: contextvars.ContextVar[_UsageOperation | None] = contextvars.ContextVar(
            "mem0_oss_usage_operation",
            default=None,
        )

    @contextmanager
    def operation(
        self,
        *,
        run_id: str,
        mode: _MODE,
        max_calls: int,
        request_max_bytes: int,
        response_max_bytes: int,
    ) -> Iterator[None]:
        if mode not in {"raw_passthrough", "subscription_llm"}:
            raise ValueError("unsupported extraction mode")
        expected_max_calls = 1 if mode == "subscription_llm" else 0
        if max_calls != expected_max_calls:
            raise ValueError("extraction mode has an invalid call budget")
        if not run_id or request_max_bytes < 1 or response_max_bytes < 1:
            raise ValueError("usage operation has invalid bounds")
        if self._current.get() is not None:
            raise RuntimeError("nested Mem0 extraction operations are not allowed")
        with self._entries_lock:
            if len(self._entries) >= MAX_USAGE_OPERATIONS:
                raise UsageEvidenceError("usage ledger exceeds the verified operation bound")
        state = _UsageOperation(
            run_id=run_id,
            operation="add",
            mode=mode,
            max_calls=max_calls,
            request_max_bytes=request_max_bytes,
            response_max_bytes=response_max_bytes,
            created_at=_utc_now(),
        )
        token = self._current.set(state)
        try:
            yield
        finally:
            try:
                with self._entries_lock:
                    if len(self._entries) >= MAX_USAGE_OPERATIONS:
                        raise UsageEvidenceError(
                            "usage ledger exceeds the verified operation bound"
                        )
                    self._entries.append(
                        UsageLedgerEntry(
                            run_id=state.run_id,
                            operation=state.operation,
                            mode=state.mode,
                            extraction_calls=state.extraction_calls,
                            request_bytes=state.request_bytes,
                            response_bytes=state.response_bytes,
                            model=self._model,
                            created_at=state.created_at,
                        )
                    )
            finally:
                self._current.reset(token)

    @property
    def entries(self) -> tuple[UsageLedgerEntry, ...]:
        with self._entries_lock:
            return tuple(self._entries)

    def aggregate_for_run(self, *, run_id: str) -> RunUsageAggregate:
        if not isinstance(run_id, str) or not run_id or len(run_id) > 128:
            raise UsageEvidenceError("usage run identifier is invalid")
        with self._entries_lock:
            entries = tuple(entry for entry in self._entries if entry.run_id == run_id)
        if not entries:
            raise UsageEvidenceError("usage evidence is unavailable for the exact run")
        if any(entry.operation != "add" or entry.model != self._model for entry in entries):
            raise UsageEvidenceError("usage ledger contains an unsupported operation")
        modes = {entry.mode for entry in entries}
        if len(modes) != 1:
            raise UsageEvidenceError("usage ledger contains mixed extraction modes")
        return RunUsageAggregate(
            mode=entries[0].mode,
            operation_count=len(entries),
            extraction_calls=sum(entry.extraction_calls for entry in entries),
            request_bytes=sum(entry.request_bytes for entry in entries),
            response_bytes=sum(entry.response_bytes for entry in entries),
            model=self._model,
            first_operation_at=min(entry.created_at for entry in entries),
            last_operation_at=max(entry.created_at for entry in entries),
        )

    def reserve_call(self, *, request_bytes: int) -> None:
        state = self._require_current()
        if state.mode != "subscription_llm" or state.extraction_calls >= state.max_calls:
            raise ExtractionCallLimitError("extraction call budget exceeded")
        if request_bytes > state.request_max_bytes:
            raise SubscriptionBridgeError("extraction request exceeds byte cap")
        state.extraction_calls += 1
        state.request_bytes += request_bytes

    def record_response(self, *, response_bytes: int) -> None:
        state = self._require_current()
        if response_bytes > state.response_max_bytes:
            state.response_bytes += state.response_max_bytes + 1
            raise SubscriptionBridgeError("extraction response exceeds byte cap")
        state.response_bytes += response_bytes

    def _require_current(self) -> _UsageOperation:
        state = self._current.get()
        if state is None:
            raise SubscriptionBridgeError("extraction request is outside an add operation")
        return state


class SubscriptionBridgeConfig(BaseLlmConfig):
    """Configuration deliberately independent from OpenAI environment variables."""

    def __init__(
        self,
        *,
        bridge_url: str | None,
        bearer_token: str | None,
        mode: _MODE,
        usage_ledger: UsageLedger,
        request_max_bytes: int,
        response_max_bytes: int,
        model: str = _MODEL,
        max_tokens: int = 512,
        **_: Any,
    ) -> None:
        if model != _MODEL:
            raise ValueError("subscription model must be gpt-5.6-sol")
        if mode not in {"raw_passthrough", "subscription_llm"}:
            raise ValueError("unsupported extraction mode")
        if request_max_bytes < 1 or response_max_bytes < 1 or max_tokens < 1:
            raise ValueError("subscription limits must be positive")
        if mode == "subscription_llm":
            if (
                not isinstance(bearer_token, str)
                or not bearer_token
                or bearer_token != bearer_token.strip()
            ):
                raise ValueError("subscription bearer token is required")
            bridge_url = validate_loopback_bridge_url(bridge_url)
        elif bridge_url is not None or bearer_token is not None:
            raise ValueError("raw passthrough does not accept a subscription bridge")
        super().__init__(
            model=model,
            api_key=None,
            max_tokens=max_tokens,
            temperature=0.0,
            top_p=1.0,
        )
        self.bridge_url = bridge_url
        self.bearer_token = bearer_token
        self.mode = mode
        self.usage_ledger = usage_ledger
        self.request_max_bytes = request_max_bytes
        self.response_max_bytes = response_max_bytes


class SubscriptionOpenAICompatibleLlm(LLMBase):
    """Minimal chat-completions client with no OpenAI SDK or ambient-env fallback."""

    def __init__(self, config: SubscriptionBridgeConfig | Mapping[str, Any] | None = None) -> None:
        if isinstance(config, Mapping):
            config = SubscriptionBridgeConfig(**dict(config))
        if not isinstance(config, SubscriptionBridgeConfig):
            raise ValueError("subscription bridge configuration is required")
        super().__init__(config)
        self.config: SubscriptionBridgeConfig = config
        self._transport: httpx.AsyncBaseTransport | None = None

    def generate_response(
        self,
        messages: Sequence[Mapping[str, str]],
        response_format: Mapping[str, str] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        **_: Any,
    ) -> str:
        if self.config.mode != "subscription_llm":
            raise ExtractionCallLimitError("raw passthrough forbids extraction")
        if tools:
            raise SubscriptionBridgeError("tool calls are not permitted for extraction")
        strict_response_format = _strict_response_format(response_format)
        normalized_messages = _normalize_messages(messages)
        request_payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": normalized_messages,
            "max_completion_tokens": self.config.max_tokens,
        }
        if strict_response_format is not None:
            request_payload["response_format"] = strict_response_format
        encoded = json.dumps(
            request_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.config.usage_ledger.reserve_call(request_bytes=len(encoded))
        raw_response = self._post_and_read(encoded)
        self.config.usage_ledger.record_response(response_bytes=len(raw_response))
        try:
            payload = json.loads(raw_response.decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
        except (
            KeyError,
            IndexError,
            TypeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise SubscriptionBridgeError(
                "subscription bridge returned an invalid completion"
            ) from exc
        if not isinstance(content, str) or not content:
            raise SubscriptionBridgeError("subscription bridge returned an empty completion")
        if len(content.encode("utf-8")) > self.config.response_max_bytes:
            raise SubscriptionBridgeError("extraction completion exceeds byte cap")
        return content

    def close(self) -> None:
        return None

    def _post_and_read(self, encoded: bytes) -> bytes:
        try:
            return asyncio.run(self._post_and_read_async(encoded))
        except TimeoutError:
            raise SubscriptionBridgeError("subscription bridge deadline exceeded") from None

    async def _post_and_read_async(self, encoded: bytes) -> bytes:
        assert self.config.bridge_url is not None
        assert self.config.bearer_token is not None
        headers = {
            "Authorization": f"Bearer {self.config.bearer_token}",
            "Content-Type": "application/json",
        }
        endpoint = f"{self.config.bridge_url}/chat/completions"
        collected = bytearray()
        try:
            async with asyncio.timeout(_SUBSCRIPTION_BRIDGE_TIMEOUT_SECONDS):
                async with httpx.AsyncClient(
                    timeout=_SUBSCRIPTION_BRIDGE_TIMEOUT_SECONDS,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self._transport,
                ) as client:
                    async with client.stream(
                        "POST",
                        endpoint,
                        content=encoded,
                        headers=headers,
                    ) as response:
                        if response.status_code < 200 or response.status_code >= 300:
                            raise SubscriptionBridgeError("subscription bridge rejected extraction")
                        async for chunk in response.aiter_bytes():
                            if len(collected) + len(chunk) > self.config.response_max_bytes:
                                self.config.usage_ledger.record_response(
                                    response_bytes=self.config.response_max_bytes + 1
                                )
                            collected.extend(chunk)
        except httpx.HTTPError as exc:
            raise SubscriptionBridgeError("subscription bridge transport failed") from exc
        return bytes(collected)


def _strict_response_format(
    response_format: Mapping[str, str] | None,
) -> dict[str, object] | None:
    if response_format is None:
        return None
    if response_format != _MEM0_JSON_OBJECT_RESPONSE_FORMAT:
        raise SubscriptionBridgeError("unsupported extraction response format")
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "mem0_isolated_add_extraction",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "memory": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "text": {"type": "string"},
                            },
                            "required": ["id", "text"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["memory"],
                "additionalProperties": False,
            },
        },
    }


def validate_loopback_bridge_url(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("subscription bridge URL is required")
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/", "/v1", "/v1/"}
    ):
        raise ValueError("subscription bridge must be an http loopback OpenAI endpoint")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError("subscription bridge hostname must be a loopback IP address") from exc
    if not address.is_loopback:
        raise ValueError("subscription bridge must use a loopback address")
    if parsed.port is not None and not 1 <= parsed.port <= 65_535:
        raise ValueError("subscription bridge port is invalid")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return f"{origin}/v1"


def _normalize_messages(messages: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role") if isinstance(message, Mapping) else None
        content = message.get("content") if isinstance(message, Mapping) else None
        if (
            role not in {"system", "user", "assistant"}
            or not isinstance(content, str)
            or not content
        ):
            raise SubscriptionBridgeError("extraction messages are invalid")
        normalized.append({"role": role, "content": content})
    if not normalized:
        raise SubscriptionBridgeError("extraction messages are empty")
    return normalized


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
