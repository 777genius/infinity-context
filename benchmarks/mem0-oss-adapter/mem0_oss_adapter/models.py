"""Strict HTTP and adapter-neutral data contracts."""

from __future__ import annotations

import json
import math
import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

_SAFE_SCOPE_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$"
_SAFE_SOURCE_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$"
SafeIdentifier = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=160, pattern=_SAFE_SCOPE_IDENTIFIER),
]
SafeSourceIdentifier = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=160, pattern=_SAFE_SOURCE_IDENTIFIER),
]
_SAFE_SOURCE_ID = re.compile(_SAFE_SOURCE_IDENTIFIER)
_LOWERCASE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEARCH_SCOPE_KEYS = frozenset({"user_id", "run_id"})
_REJECTED_FILTER_OPERATORS = frozenset({"and", "or", "not"})
_SAFE_IDENTIFIER_ADAPTER = TypeAdapter(SafeIdentifier)
MAX_REQUEST_BODY_BYTES = 65_536
MAX_MESSAGE_COUNT = 100
MAX_MESSAGE_CONTENT_BYTES = 16_384
MAX_METADATA_BYTES = 16_384
MAX_METADATA_DEPTH = 4
MAX_QUERY_BYTES = 8_192


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(StrictModel):
    role: Literal["user", "assistant", "system"]
    content: Annotated[str, Field(min_length=1)]

    @field_validator("content")
    @classmethod
    def bound_content_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_MESSAGE_CONTENT_BYTES:
            raise ValueError("message content exceeds the UTF-8 byte cap")
        return value


class AddRequest(StrictModel):
    messages: Annotated[list[Message], Field(min_length=1, max_length=MAX_MESSAGE_COUNT)]
    user_id: SafeIdentifier
    agent_id: SafeIdentifier | None = None
    run_id: SafeIdentifier
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: Annotated[int, Field(ge=0)]

    @field_validator("metadata")
    @classmethod
    def bound_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_metadata_value(value, depth=0)
        try:
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be a finite JSON object") from exc
        if len(encoded) > MAX_METADATA_BYTES:
            raise ValueError("metadata exceeds the UTF-8 byte cap")
        return value

    @model_validator(mode="after")
    def require_persisted_source_identity(self) -> AddRequest:
        source_id = self.metadata.get("source_id")
        if not isinstance(source_id, str) or _SAFE_SOURCE_ID.fullmatch(source_id) is None:
            raise ValueError("metadata.source_id must be a safe identifier")
        source_sha256 = self.metadata.get("source_sha256")
        if not isinstance(source_sha256, str) or _LOWERCASE_SHA256.fullmatch(source_sha256) is None:
            raise ValueError("metadata.source_sha256 must be lowercase sha256")
        return self


class SearchRequest(StrictModel):
    query: Annotated[str, Field(min_length=1)]
    filters: dict[str, Any]
    limit: Annotated[int, Field(ge=1, le=1000)]

    @field_validator("query")
    @classmethod
    def bound_query_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_QUERY_BYTES:
            raise ValueError("query exceeds the UTF-8 byte cap")
        return value

    @field_validator("filters")
    @classmethod
    def require_exact_run_scope(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_exact_search_scope(value)
        return value


class HealthResponse(StrictModel):
    status: Literal["ok", "not_ready", "unconfigured"]
    runtime_mode: Literal["oss"] = "oss"
    configured: bool
    ready: bool
    attestation_status: Literal["not_run", "passed", "failed"]
    ingress_auth_configured: bool


class BenchmarkAttestationRefreshRequest(StrictModel):
    run_id: SafeIdentifier
    probe_nonce: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    target_identity_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class BenchmarkAuthChallengeRequest(StrictModel):
    nonce: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class BenchmarkAuthChallengeResponse(StrictModel):
    schema_version: Literal["mem0-benchmark-auth-challenge.v1"]
    nonce_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    signature: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PersistedSourceMetadata(StrictModel):
    source_id: SafeSourceIdentifier
    source_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PersistedMemoryIdentity(StrictModel):
    id: SafeIdentifier
    event: Literal["ADD"] = "ADD"
    metadata: PersistedSourceMetadata


class AddResponse(StrictModel):
    request_id: SafeIdentifier
    results: list[PersistedMemoryIdentity]


class SearchResponse(StrictModel):
    results: list[dict[str, Any]]


class DeleteResponse(StrictModel):
    deleted: Literal[True]
    verified_absent: Literal[True]


class TimestampAttestation(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["not_run", "passed", "failed"] = "not_run"
    checked_at: str | None = None
    metadata_created_at_roundtrip_attested: bool = False
    cleanup_succeeded: bool | None = None


def _validate_exact_search_scope(value: dict[str, Any]) -> None:
    if not value:
        raise ValueError("filters must be a non-empty exact user/run scope")
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError("filter keys must be non-empty strings")
        normalized_key = key.casefold()
        if normalized_key in _REJECTED_FILTER_OPERATORS:
            raise ValueError(f"filter operator {key} is not permitted")
        if isinstance(item, dict | list) or item is None:
            raise ValueError(f"filters.{key} must be a scalar constraint")
        if key in _SEARCH_SCOPE_KEYS:
            try:
                _SAFE_IDENTIFIER_ADAPTER.validate_python(item)
            except ValidationError:
                raise ValueError(f"filters.{key} must be a non-empty string identifier") from None
    if not _SEARCH_SCOPE_KEYS.issubset(value):
        raise ValueError("filters must contain exact user_id and run_id")


def _validate_metadata_value(value: object, *, depth: int) -> None:
    if isinstance(value, dict):
        if depth > MAX_METADATA_DEPTH:
            raise ValueError("metadata exceeds the nesting-depth cap")
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("metadata keys must be strings")
            _validate_metadata_value(item, depth=depth + 1)
        return
    if isinstance(value, list):
        if depth > MAX_METADATA_DEPTH:
            raise ValueError("metadata exceeds the nesting-depth cap")
        for item in value:
            _validate_metadata_value(item, depth=depth + 1)
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("metadata numbers must be finite")
    if value is None or isinstance(value, str | int | float | bool):
        return
    raise ValueError("metadata must contain JSON values only")
