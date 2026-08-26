"""Framework-neutral stable error envelope for Retrieval V2 and projection ingest."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .._json import JsonObject

CONTEXT_RETRIEVAL_ERROR_SPECS_V2 = {
    "memory.context_retrieval_contract_invalid": (400, False),
    "memory.unauthorized": (401, False),
    "memory.forbidden": (403, False),
    "memory.context_retrieval_scope_not_found": (404, False),
    "memory.context_retrieval_capability_mismatch": (409, False),
    "memory.context_retrieval_unsupported": (422, False),
    "memory.context_retrieval_unavailable": (503, True),
    "memory.context_retrieval_deadline_exceeded": (504, True),
    "memory.document_projection_invalid": (400, False),
    "memory.document_projection_locator_conflict": (409, False),
    "memory.document_projection_ordinal_conflict": (409, False),
    "memory.document_projection_idempotency_conflict": (409, False),
}


@dataclass(frozen=True, slots=True)
class ContextRetrievalV2ErrorDto:
    code: str
    message: str
    retryable: bool

    def __post_init__(self) -> None:
        spec = CONTEXT_RETRIEVAL_ERROR_SPECS_V2.get(self.code)
        if spec is None:
            raise ValueError("error.code is unsupported")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("error.message must be a non-blank string")
        if any(
            0xD800 <= ord(character) <= 0xDFFF
            or ord(character) < 0x20
            or 0x7F <= ord(character) <= 0x9F
            for character in self.message
        ):
            raise ValueError("error.message contains invalid Unicode or controls")
        if not isinstance(self.retryable, bool) or self.retryable is not spec[1]:
            raise ValueError("error.retryable does not match error.code")

    def to_dict(self) -> JsonObject:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


@dataclass(frozen=True, slots=True)
class ContextRetrievalV2ErrorEnvelopeDto:
    error: ContextRetrievalV2ErrorDto

    def __post_init__(self) -> None:
        if not isinstance(self.error, ContextRetrievalV2ErrorDto):
            raise ValueError("error must be a ContextRetrievalV2ErrorDto")

    @property
    def http_status(self) -> int:
        return CONTEXT_RETRIEVAL_ERROR_SPECS_V2[self.error.code][0]

    def to_dict(self) -> JsonObject:
        return {"error": self.error.to_dict()}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ContextRetrievalV2ErrorEnvelopeDto:
        if set(payload) != {"error"} or not isinstance(payload.get("error"), Mapping):
            raise ValueError("error envelope must contain exactly error")
        error = payload["error"]
        assert isinstance(error, Mapping)
        if set(error) != {"code", "message", "retryable"}:
            raise ValueError("error fields do not match the canonical envelope")
        return cls(
            ContextRetrievalV2ErrorDto(
                code=_field(error, "code", str),
                message=_field(error, "message", str),
                retryable=_field(error, "retryable", bool),
            )
        )


def _field(payload: Mapping[str, object], name: str, kind: type):
    value = payload.get(name)
    if not isinstance(value, kind):
        raise ValueError(f"error.{name} has an invalid type")
    return value


__all__ = (
    "CONTEXT_RETRIEVAL_ERROR_SPECS_V2",
    "ContextRetrievalV2ErrorDto",
    "ContextRetrievalV2ErrorEnvelopeDto",
)
