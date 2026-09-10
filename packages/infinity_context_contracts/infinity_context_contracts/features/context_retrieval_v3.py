"""Explicit opt-in thread selector boundary; V2 validators remain strict."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields

from ._context_building_retrieval import (
    RetrievalScopeDto,
    RetrieveContextRequestDto,
    RetrieveContextResponseDto,
)
from ._context_building_retrieval_capability import (
    CAPABILITY_ENDPOINT,
    RetrievalCapabilityDto,
    capability_fingerprint,
)
from ._context_building_retrieval_json import decode_context_retrieval_json
from ._context_building_retrieval_validation import (
    mapping,
    require_exact,
    validated_opaque,
)

CONTRACT_VERSION = "context-retrieval.v3"
ENDPOINT = "/v1/context/retrieve-v3"


@dataclass(frozen=True, slots=True)
class RetrievalThreadSelectorDto:
    mode: str
    id: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("exact", "any"):
            raise ValueError("thread.mode is unsupported")
        if self.mode == "any" and self.id is not None:
            raise ValueError("thread.id is unsupported for any")
        if self.id is not None:
            validated_opaque(self.id, "thread.id")

    def to_dict(self) -> dict[str, object]:
        return {"mode": "any"} if self.mode == "any" else {"mode": "exact", "id": self.id}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RetrievalThreadSelectorDto:
        mode = payload.get("mode")
        if mode not in ("exact", "any"):
            raise ValueError("thread.mode is unsupported")
        require_exact(payload, {"mode", "id"} if mode == "exact" else {"mode"}, "thread")
        return cls(mode, payload.get("id"))


@dataclass(frozen=True, slots=True)
class RetrievalScopeV3Dto:
    space_id: str
    memory_scope_id: str
    thread: RetrievalThreadSelectorDto

    def __post_init__(self) -> None:
        validated_opaque(self.space_id, "scope.spaceId")
        validated_opaque(self.memory_scope_id, "scope.memoryScopeId")
        if not isinstance(self.thread, RetrievalThreadSelectorDto):
            raise ValueError("scope.thread has an invalid runtime type")
        object.__setattr__(
            self, "thread", RetrievalThreadSelectorDto(self.thread.mode, self.thread.id)
        )

    @property
    def thread_id(self) -> str | None:
        """Exact id for scope authorization/resolution, never a retrieval predicate."""
        return self.thread.id

    def to_dict(self) -> dict[str, object]:
        return {
            "spaceId": self.space_id,
            "memoryScopeId": self.memory_scope_id,
            "thread": self.thread.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RetrievalScopeV3Dto:
        require_exact(payload, {"spaceId", "memoryScopeId", "thread"}, "scope")
        return cls(
            payload["spaceId"],
            payload["memoryScopeId"],
            RetrievalThreadSelectorDto.from_dict(mapping(payload["thread"], "scope.thread")),
        )


@dataclass(frozen=True, slots=True)
class RetrieveContextV3RequestDto(RetrieveContextRequestDto):
    scope: RetrievalScopeV3Dto

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError("contract_version is unsupported")
        if not isinstance(self.scope, RetrievalScopeV3Dto):
            raise ValueError("scope has an invalid runtime type")
        scope = RetrievalScopeV3Dto(
            self.scope.space_id, self.scope.memory_scope_id, self.scope.thread
        )
        # Share validation of all non-selector fields, without relaxing V2 parsing.
        common = RetrieveContextRequestDto(
            "context-retrieval.v2",
            self.capability_fingerprint,
            self.profile_id,
            RetrievalScopeDto(scope.space_id, scope.memory_scope_id, scope.thread_id),
            self.queries,
            self.filters,
            self.soft_preferences,
            self.bounds,
        )
        for item in fields(common):
            if item.name not in ("contract_version", "scope"):
                object.__setattr__(self, item.name, getattr(common, item.name))
        object.__setattr__(self, "scope", scope)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RetrieveContextV3RequestDto:
        if payload.get("contract_version") != CONTRACT_VERSION:
            raise ValueError("contract_version is unsupported")
        scope = RetrievalScopeV3Dto.from_dict(mapping(payload.get("scope"), "scope"))
        common = RetrieveContextRequestDto.from_dict(
            {
                **payload,
                "contract_version": "context-retrieval.v2",
                "scope": RetrievalScopeDto(
                    scope.space_id, scope.memory_scope_id, scope.thread_id
                ).to_dict(),
            }
        )
        return cls(
            CONTRACT_VERSION,
            common.capability_fingerprint,
            common.profile_id,
            scope,
            common.queries,
            common.filters,
            common.soft_preferences,
            common.bounds,
        )


def decode_retrieve_context_v3_request(raw: bytes) -> RetrieveContextV3RequestDto:
    return RetrieveContextV3RequestDto.from_dict(decode_context_retrieval_json(raw))


def retrieval_v3_capability(descriptor: RetrievalCapabilityDto) -> dict[str, object]:
    """Bind V3 negotiation to the same profile/health snapshot and distinct wire."""
    payload = descriptor.to_dict()
    payload.update(endpoint=ENDPOINT, contract_version=CONTRACT_VERSION)
    payload["capability_fingerprint"] = capability_fingerprint(payload)
    return payload


def validate_retrieval_v3_capability(payload: Mapping[str, object]) -> dict[str, object]:
    if payload.get("contract_version") != CONTRACT_VERSION or payload.get("endpoint") != ENDPOINT:
        raise ValueError("V3 capability is unsupported")
    if payload.get("capability_fingerprint") != capability_fingerprint(payload):
        raise ValueError("V3 capability fingerprint does not match payload")
    common = {
        **payload,
        "contract_version": "context-retrieval.v2",
        "endpoint": CAPABILITY_ENDPOINT,
    }
    common["capability_fingerprint"] = capability_fingerprint(common)
    return retrieval_v3_capability(RetrievalCapabilityDto.from_dict(common))


@dataclass(frozen=True, slots=True)
class RetrieveContextV3ResponseDto(RetrieveContextResponseDto):
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError("contract_version is unsupported")
        values = {item.name: getattr(self, item.name) for item in fields(self)}
        values["contract_version"] = "context-retrieval.v2"
        common = RetrieveContextResponseDto(**values)
        for item in fields(common):
            if item.name != "contract_version":
                object.__setattr__(self, item.name, getattr(common, item.name))

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RetrieveContextV3ResponseDto:
        if payload.get("contract_version") != CONTRACT_VERSION:
            raise ValueError("contract_version is unsupported")
        common = RetrieveContextResponseDto.from_dict(
            {
                **payload,
                "contract_version": "context-retrieval.v2",
            }
        )
        values = {item.name: getattr(common, item.name) for item in fields(common)}
        values["contract_version"] = CONTRACT_VERSION
        return cls(**values)


def decode_retrieve_context_v3_response(raw: bytes) -> RetrieveContextV3ResponseDto:
    return RetrieveContextV3ResponseDto.from_dict(decode_context_retrieval_json(raw))
