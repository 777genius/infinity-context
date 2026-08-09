"""Strict provider-free runtime and extraction authority for the micro canary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_contract_binding import (
    ManagedMem0V5ExtractionContractBinding,
    require_managed_mem0_v5_extraction_contract_binding,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_projection import (
    MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256,
    MEM0_V5_EXTRACTION_SCHEMA_SHA256,
    MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
)

from scripts.mem0_v5_live_project_one_unit import OneUnitProjection

AUTHORITY_SCHEMA = "managed-mem0-v5-live-runtime-authority.v3"
RUNTIME_RESPONSE_FORMAT_SHA256 = "812938567c7a81bac6ed3266608adf470dedc57706102e039422f695495322bf"
RUNTIME_RESPONSE_SCHEMA_SHA256 = "2461f7a465be82aa67751dc04e0717cde75c69b86e7db54bb306a2e3d1d4d8f0"
_SHA256_CHARS = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class LiveRuntimeAuthority:
    model: str
    reasoning_effort: str
    service_tier: str
    runtime_source_revision: str
    runtime_source_sha256: str
    runtime_base_sha256: str
    route_binding_sha256: str
    base_instructions_sha256: str
    extraction_system_prompt_sha256: str
    account_binding_hmac_sha256: str
    response_format_type: str
    response_format_sha256: str
    response_schema_sha256: str
    extraction_response_format_sha256: str
    extraction_response_schema_sha256: str
    requested_output_tokens: int

    @classmethod
    def parse(cls, raw: bytes) -> LiveRuntimeAuthority:
        try:
            payload = json.loads(raw, object_pairs_hook=_unique_object)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise ValueError("mem0_v5_live_runtime_authority_invalid") from None
        keys = {"schema_version", *cls.__dataclass_fields__}
        if type(payload) is not dict or set(payload) != keys:
            raise ValueError("mem0_v5_live_runtime_authority_invalid")
        if payload.pop("schema_version") != AUTHORITY_SCHEMA:
            raise ValueError("mem0_v5_live_runtime_authority_invalid")
        try:
            value = cls(**payload)
        except TypeError:
            raise ValueError("mem0_v5_live_runtime_authority_invalid") from None
        value.require_valid()
        return value

    def require_valid(self) -> None:
        text = (
            self.model,
            self.reasoning_effort,
            self.service_tier,
            self.runtime_source_revision,
            self.response_format_type,
        )
        digests = (
            self.runtime_source_sha256,
            self.runtime_base_sha256,
            self.route_binding_sha256,
            self.base_instructions_sha256,
            self.extraction_system_prompt_sha256,
            self.account_binding_hmac_sha256,
            self.response_format_sha256,
            self.response_schema_sha256,
            self.extraction_response_format_sha256,
            self.extraction_response_schema_sha256,
        )
        if (
            any(
                type(item) is not str or not item or item != item.strip() or len(item) > 512
                for item in text
            )
            or any(not _is_sha256(item) for item in digests)
            or self.base_instructions_sha256 != SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256
            or self.extraction_system_prompt_sha256 != MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256
            or self.base_instructions_sha256 == self.extraction_system_prompt_sha256
            or self.response_format_sha256 != RUNTIME_RESPONSE_FORMAT_SHA256
            or self.response_schema_sha256 != RUNTIME_RESPONSE_SCHEMA_SHA256
            or self.extraction_response_format_sha256 != MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256
            or self.extraction_response_schema_sha256 != MEM0_V5_EXTRACTION_SCHEMA_SHA256
            or self.response_format_sha256 == self.extraction_response_format_sha256
            or self.response_schema_sha256 == self.extraction_response_schema_sha256
            or type(self.requested_output_tokens) is not int
            or self.requested_output_tokens != 4096
        ):
            raise ValueError("mem0_v5_live_runtime_authority_invalid")


@dataclass(frozen=True, slots=True)
class MicroCanaryInputs:
    projection: OneUnitProjection
    runtime: LiveRuntimeAuthority
    restore_existing: bool
    orphan_dispatch_claim: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.projection) is not OneUnitProjection
            or type(self.runtime) is not LiveRuntimeAuthority
            or type(self.restore_existing) is not bool
            or type(self.orphan_dispatch_claim) is not bool
            or self.projection.response_format_sha256
            != self.runtime.extraction_response_format_sha256
            or self.projection.response_schema_sha256
            != self.runtime.extraction_response_schema_sha256
            or self.projection.requested_output_tokens != self.runtime.requested_output_tokens
        ):
            raise ValueError("mem0_v5_live_inputs_invalid")


def require_extraction_authority(
    *,
    runtime: LiveRuntimeAuthority,
    contract_file: Path,
    contract_sha256: str,
) -> None:
    """Bind extraction policy independently from subscription runtime instructions."""

    try:
        binding = ManagedMem0V5ExtractionContractBinding(contract_file, contract_sha256)
        require_managed_mem0_v5_extraction_contract_binding(binding)
    except Exception:
        raise ValueError("mem0_v5_live_extraction_authority_invalid") from None
    if (
        runtime.model != binding.model
        or runtime.extraction_system_prompt_sha256 != binding.system_prompt_sha256
        or runtime.extraction_response_format_sha256 != binding.response_format_sha256
        or runtime.extraction_response_schema_sha256 != binding.response_schema_sha256
        or runtime.requested_output_tokens != binding.requested_output_tokens
    ):
        raise ValueError("mem0_v5_live_extraction_authority_differs")


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _SHA256_CHARS


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("mem0_v5_live_runtime_authority_invalid")
        value[key] = item
    return value


__all__ = (
    "AUTHORITY_SCHEMA",
    "LiveRuntimeAuthority",
    "MicroCanaryInputs",
    "RUNTIME_RESPONSE_FORMAT_SHA256",
    "RUNTIME_RESPONSE_SCHEMA_SHA256",
    "require_extraction_authority",
)
