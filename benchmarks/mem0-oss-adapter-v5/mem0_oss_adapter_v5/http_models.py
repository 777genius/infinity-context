"""Strict, endpoint-specific HTTP models for the v5 benchmark adapter."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
Sha256 = Annotated[StrictStr, Field(pattern=SHA256_PATTERN.pattern)]
PositiveOperationCount = Annotated[StrictInt, Field(ge=1, le=10_000)]
OperationSequence = Annotated[StrictInt, Field(ge=0, lt=10_000)]


class _ExactModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
    )


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


EmptySha256 = Literal["e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"]


class CleanStateCorpusScope(_ExactModel):
    corpus_identity_sha256: Sha256
    scope_identity_sha256: Sha256
    source_scope_count: Annotated[StrictInt, Field(ge=1, le=10_000)]
    residual_record_count: Literal[0]
    residual_root_sha256: EmptySha256


class CleanStateRequest(_ExactModel):
    schema_version: Literal["mem0-oss-adapter-v5.clean-state-request.v1"]
    admission_commitment_sha256: Sha256
    run_id_sha256: Sha256
    authority_commitment_sha256: Sha256
    manifest_case_count: Annotated[StrictInt, Field(ge=1, le=10_000)]
    credential_binding_sha256: Sha256
    runtime_source_revision: SafeRuntimeText
    runtime_source_sha256: Sha256
    runtime_base_sha256: Sha256
    runtime_binding_commitment_sha256: Sha256
    scopes: Annotated[tuple[CleanStateCorpusScope, ...], Field(min_length=1, max_length=10_000)]

    @field_validator("scopes", mode="before")
    @classmethod
    def scopes_are_a_json_array(cls, value: object) -> object:
        return tuple(value) if type(value) is list else value

    @model_validator(mode="after")
    def corpus_inventory_is_unique(self) -> CleanStateRequest:
        identities = tuple(item.corpus_identity_sha256 for item in self.scopes)
        if len(set(identities)) != len(identities):
            raise ValueError("clean_state_request_invalid")
        return self


class CleanStateResponse(_ExactModel):
    schema_version: Literal["mem0-oss-adapter-v5.clean-state.v1"]
    admission_commitment_sha256: Sha256
    run_id_sha256: Sha256
    authority_commitment_sha256: Sha256
    ingestion_manifest_sha256: Sha256
    ingestion_root_sha256: Sha256
    runtime_binding_commitment_sha256: Sha256
    request_commitment_sha256: Sha256
    request_id_sha256: Sha256
    scope_count: Annotated[StrictInt, Field(ge=1, le=10_000)]
    scope_inventory_root_sha256: Sha256
    scopes: Annotated[tuple[CleanStateCorpusScope, ...], Field(min_length=1, max_length=10_000)]
    evidence_commitment_sha256: Sha256
    clean_state_hmac_sha256: Sha256

    @field_validator("scopes", mode="before")
    @classmethod
    def scopes_are_a_json_array(cls, value: object) -> object:
        return tuple(value) if type(value) is list else value

    @model_validator(mode="after")
    def scope_count_is_exact(self) -> CleanStateResponse:
        identities = tuple(item.corpus_identity_sha256 for item in self.scopes)
        if self.scope_count != len(self.scopes) or len(set(identities)) != len(identities):
            raise ValueError("clean_state_response_invalid")
        return self


EvidenceText = Annotated[StrictStr, Field(min_length=1, max_length=512)]
SearchMemory = Annotated[StrictStr, Field(min_length=1, max_length=16_384)]
SearchLimit = Annotated[StrictInt, Field(ge=1, le=200)]
EvidenceCount = Annotated[StrictInt, Field(ge=0, le=10_000)]


class StorageObservationRequest(_ExactModel):
    admission_commitment_sha256: Sha256
    operation_id_sha256: Sha256


class StorageObservationRecord(_ExactModel):
    record_id: EvidenceText
    extraction_memory_id: EvidenceText
    source_id: EvidenceText
    source_sha256: Sha256
    memory_sha256: Sha256

    @field_validator("record_id", "extraction_memory_id", "source_id")
    @classmethod
    def evidence_text_is_trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("storage_observation_invalid")
        return value


class StorageObservationResponse(_ExactModel):
    schema_version: Literal["mem0-oss-adapter-v5.storage-observation.v1"]
    admission_commitment_sha256: Sha256
    operation_id_sha256: Sha256
    scope_sha256: Sha256
    source_id: EvidenceText
    source_sha256: Sha256
    storage_commitment_sha256: Sha256
    record_count: EvidenceCount
    record_root_sha256: Sha256
    records: tuple[StorageObservationRecord, ...]
    observation_hmac_sha256: Sha256

    @model_validator(mode="after")
    def record_count_is_exact(self) -> StorageObservationResponse:
        if self.source_id != self.source_id.strip() or self.record_count != len(self.records):
            raise ValueError("storage_observation_invalid")
        return self


class ScopedSearchRequest(_ExactModel):
    admission_commitment_sha256: Sha256
    corpus_id: EvidenceText
    query: SearchMemory
    limit: SearchLimit

    @field_validator("corpus_id", "query")
    @classmethod
    def search_text_is_trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("search_request_invalid")
        return value


class ScopedSearchResult(_ExactModel):
    rank: Annotated[StrictInt, Field(ge=0, le=199)]
    record_id: EvidenceText
    memory: SearchMemory
    memory_sha256: Sha256
    source_id: EvidenceText
    source_sha256: Sha256
    score: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]

    @field_validator("record_id", "memory", "source_id")
    @classmethod
    def result_text_is_trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("search_result_invalid")
        return value


class ScopedSearchResponse(_ExactModel):
    schema_version: Literal["mem0-oss-adapter-v5.scoped-search.v1"]
    admission_commitment_sha256: Sha256
    corpus_id: EvidenceText
    query_commitment_sha256: Sha256
    limit: SearchLimit
    result_count: Annotated[StrictInt, Field(ge=0, le=200)]
    result_root_sha256: Sha256
    results: tuple[ScopedSearchResult, ...]
    search_hmac_sha256: Sha256

    @model_validator(mode="after")
    def ranking_is_exact(self) -> ScopedSearchResponse:
        if (
            self.corpus_id != self.corpus_id.strip()
            or self.result_count != len(self.results)
            or self.result_count > self.limit
            or tuple(item.rank for item in self.results) != tuple(range(len(self.results)))
        ):
            raise ValueError("search_result_invalid")
        return self


class HealthResponse(_ExactModel):
    ok: StrictBool
    service: Annotated[StrictStr, Field(pattern=r"^mem0-oss-adapter-v5$")]
    provider_calls: Annotated[StrictStr, Field(pattern=r"^dispatch_only$")]


class ErrorResponse(_ExactModel):
    detail: Annotated[StrictStr, Field(pattern=r"^[a-z0-9_]{1,96}$")]
