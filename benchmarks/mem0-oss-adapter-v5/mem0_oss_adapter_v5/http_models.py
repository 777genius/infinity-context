"""Strict, endpoint-specific HTTP models for the v5 benchmark adapter."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
Sha256 = Annotated[StrictStr, Field(pattern=SHA256_PATTERN.pattern)]
PositiveOperationCount = Annotated[StrictInt, Field(ge=1, le=10_000)]
OperationSequence = Annotated[StrictInt, Field(ge=0, lt=10_000)]


class _ExactModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class AdmitRequest(_ExactModel):
    admission_commitment_sha256: Sha256
    ingestion_manifest_sha256: Sha256
    ingestion_root_sha256: Sha256
    expected_operation_count: PositiveOperationCount
    route_sha256: Sha256


class DispatchRequest(_ExactModel):
    admission_commitment_sha256: Sha256
    operation_id_sha256: Sha256
    unit_identity_sha256: Sha256
    unit_sha256: Sha256
    scope_sha256: Sha256
    request_body_sha256: Sha256
    sequence: OperationSequence


class StatusRequest(_ExactModel):
    admission_commitment_sha256: Sha256
    operation_id_sha256: Sha256


class CleanupRequest(_ExactModel):
    admission_commitment_sha256: Sha256
    seal_commitment_sha256: Sha256 | None
    operation_root_sha256: Sha256 | None
    operation_inventory_root_sha256: Sha256
    expected_operation_count: PositiveOperationCount
    aborting: StrictBool


class AdmissionReceipt(_ExactModel):
    admission_commitment_sha256: Sha256
    runtime_binding_commitment_sha256: Sha256
    accepted: StrictBool


SafeRuntimeText = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")]
ProviderTokenCount = Annotated[StrictInt, Field(ge=0, le=1_000_000)]


class PromptTokenDetails(_ExactModel):
    cached_tokens: ProviderTokenCount
    cache_write_tokens: ProviderTokenCount | None = None


class CompletionTokenDetails(_ExactModel):
    reasoning_tokens: ProviderTokenCount


class ReceiptUsage(_ExactModel):
    prompt_tokens: ProviderTokenCount
    completion_tokens: ProviderTokenCount
    total_tokens: ProviderTokenCount
    prompt_tokens_details: PromptTokenDetails | None = None
    completion_tokens_details: CompletionTokenDetails | None = None

    @model_validator(mode="after")
    def totals_are_exact(self) -> ReceiptUsage:
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValueError("runtime_receipt_invalid")
        if self.prompt_tokens_details is not None:
            if self.prompt_tokens_details.cached_tokens > self.prompt_tokens:
                raise ValueError("runtime_receipt_invalid")
            cache_write = self.prompt_tokens_details.cache_write_tokens
            if cache_write is not None and cache_write > self.prompt_tokens:
                raise ValueError("runtime_receipt_invalid")
        if (
            self.completion_tokens_details is not None
            and self.completion_tokens_details.reasoning_tokens > self.completion_tokens
        ):
            raise ValueError("runtime_receipt_invalid")
        return self


class RuntimeSelection(_ExactModel):
    account_binding_hmac_sha256: Sha256
    thread_id: SafeRuntimeText
    turn_id: SafeRuntimeText
    model: Literal["gpt-5.6-sol"]
    model_provider: Literal["openai"]
    reasoning_effort: Literal["high"]
    service_tier: Literal["default"]
    execution_profile: Literal["stateless-completion"]
    base_instructions_sha256: Sha256


class RequestIdentity(_ExactModel):
    public_model: Literal["gpt-5.6-sol"]
    client_requested_model: Literal["gpt-5.6-sol"]
    configured_codex_model: Literal["gpt-5.6-sol"]
    requested_codex_model: Literal["gpt-5.6-sol"]
    request_body_sha256: Sha256
    response_format_type: Literal["json_schema"]
    response_format_sha256: Sha256
    response_schema_sha256: Sha256


class OutputIdentity(_ExactModel):
    output_text_sha256: Sha256
    terminal_status: Literal["completed"]


class OutputTokenLimit(_ExactModel):
    requested_tokens: Annotated[StrictInt, Field(ge=1, le=16_384)]
    enforced: Literal[False]


class ReceiptMetadata(_ExactModel):
    schema_version: Literal[2]
    attestation_level: Literal["provider_receipt"]
    usage_source: Literal["codex_thread_token_usage_updated"]
    runtime_selection: RuntimeSelection
    request_identity: RequestIdentity
    output_identity: OutputIdentity
    output_token_limit: OutputTokenLimit
    receipt_hmac_sha256: Sha256


class RuntimeReceiptV2(_ExactModel):
    metadata: ReceiptMetadata
    usage: ReceiptUsage


class RuntimeReceiptEnvelope(_ExactModel):
    admission_commitment_sha256: Sha256
    operation_id_sha256: Sha256
    runtime_receipt: RuntimeReceiptV2


class CleanupReceipt(_ExactModel):
    admission_commitment_sha256: Sha256
    seal_commitment_sha256: Sha256 | None
    operation_root_sha256: Sha256 | None
    operation_inventory_root_sha256: Sha256
    deleted_operation_count: Annotated[StrictInt, Field(ge=0, le=10_000)]
    residual_record_count: Annotated[StrictInt, Field(ge=0, le=10_000)]
    residual_root_sha256: Sha256


class HealthResponse(_ExactModel):
    ok: StrictBool
    service: Annotated[StrictStr, Field(pattern=r"^mem0-oss-adapter-v5$")]
    provider_calls: Annotated[StrictStr, Field(pattern=r"^dispatch_only$")]


class ErrorResponse(_ExactModel):
    detail: Annotated[StrictStr, Field(pattern=r"^[a-z0-9_]{1,96}$")]
