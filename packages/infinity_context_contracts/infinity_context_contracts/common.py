"""Common public response contract DTOs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ._json import JsonObject, JsonValue, json_compatible


@dataclass(frozen=True, slots=True)
class ErrorDto:
    """Stable public error object."""

    code: str
    message: str
    retryable: bool = False
    details: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.details:
            payload["details"] = json_compatible(self.details)
        return payload


@dataclass(frozen=True, slots=True)
class ErrorResponseDto:
    """Public error response wrapper matching the current API error shape."""

    error: ErrorDto

    def to_dict(self) -> JsonObject:
        return {"error": self.error.to_dict()}


@dataclass(frozen=True, slots=True)
class ResponseEnvelopeDto:
    """Generic response envelope for future stable contract payloads."""

    data: JsonValue = None
    error: ErrorDto | None = None
    meta: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            "data": json_compatible(self.data),
            "error": self.error.to_dict() if self.error is not None else None,
            "meta": json_compatible(self.meta),
        }
