"""Strict HTTP and platform-neutral data contracts."""

from __future__ import annotations

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

SafeIdentifier = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=160, pattern=r".*\S.*"),
]
_SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_IDENTITY_FILTER_KEYS = frozenset({"user_id", "agent_id", "app_id", "run_id"})
_REJECTED_FILTER_OPERATORS = frozenset({"or", "not"})
_SAFE_IDENTIFIER_ADAPTER = TypeAdapter(SafeIdentifier)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(StrictModel):
    role: Literal["user", "assistant", "system"]
    content: Annotated[str, Field(min_length=1)]


class AddRequest(StrictModel):
    messages: Annotated[list[Message], Field(min_length=1)]
    user_id: SafeIdentifier | None = None
    agent_id: SafeIdentifier | None = None
    run_id: SafeIdentifier | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def require_scope_and_safe_source_id(self) -> AddRequest:
        if not any((self.user_id, self.agent_id, self.run_id)):
            raise ValueError("at least one entity id is required")
        source_id = self.metadata.get("source_id")
        if not isinstance(source_id, str) or not _SAFE_SOURCE_ID.fullmatch(source_id):
            raise ValueError("metadata.source_id must be a safe identifier")
        return self


class SearchRequest(StrictModel):
    query: Annotated[str, Field(min_length=1)]
    filters: dict[str, Any]
    limit: Annotated[int, Field(ge=1, le=1000)]

    @field_validator("filters")
    @classmethod
    def require_entity_filter(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not _validate_conjunctive_filters(value):
            raise ValueError("filters must contain at least one entity id")
        return value


class HealthResponse(StrictModel):
    status: Literal["ok", "not_ready", "unconfigured"]
    runtime_mode: Literal["managed_platform"] = "managed_platform"
    configured: bool
    ready: bool
    attestation_status: Literal["not_run", "passed", "failed"]


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


class AddResponse(StrictModel):
    results: list[dict[str, Any]]


class SearchResponse(StrictModel):
    results: list[dict[str, Any]]


class DeleteResponse(StrictModel):
    deleted: Literal[True]
    verified_absent: Literal[True]


class EventSnapshot(StrictModel):
    status: str
    results: list[dict[str, Any]] = Field(default_factory=list)


class TimestampAttestation(StrictModel):
    status: Literal["not_run", "passed", "failed"] = "not_run"
    checked_at: str | None = None
    probe_mode: Literal["live_sentinel"] = "live_sentinel"
    input_epoch_seconds: int | None = None
    expected_created_at: str | None = None
    event_terminal_status: str | None = None
    readback_result_count: int = 0
    persisted_created_at: str | None = None
    delta_seconds: float | None = None
    cleanup_succeeded: bool | None = None
    failure_code: str | None = None


def _validate_conjunctive_filters(value: dict[str, Any]) -> bool:
    if not value:
        raise ValueError("filters must be a non-empty conjunctive object")
    found = False
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError("filter keys must be non-empty strings")
        normalized_key = key.casefold()
        if normalized_key in _REJECTED_FILTER_OPERATORS:
            raise ValueError(f"filter operator {key} is not permitted")
        if normalized_key == "and":
            if key != "AND" or not isinstance(item, list) or not item:
                raise ValueError("AND must be an uppercase non-empty list")
            for child in item:
                if not isinstance(child, dict) or not child:
                    raise ValueError("AND children must be non-empty filter objects")
                found = _validate_conjunctive_filters(child) or found
            continue
        if isinstance(item, dict | list) or item is None:
            raise ValueError(f"filters.{key} must be a scalar constraint")
        if key in _IDENTITY_FILTER_KEYS:
            try:
                _SAFE_IDENTIFIER_ADAPTER.validate_python(item)
            except ValidationError:
                raise ValueError(f"filters.{key} must be a non-empty string identifier") from None
            found = True
    return found
