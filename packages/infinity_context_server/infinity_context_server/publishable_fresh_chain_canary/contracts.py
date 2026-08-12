"""Provider-neutral execution contracts for the exact fresh-chain 1+4 canary."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, TypeAlias, final

from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunProviderInputs,
)

from .ledger_models import (
    FRESH_CHAIN_CANARY_KIND,
    FRESH_CHAIN_CASE_ID,
    FRESH_CHAIN_EVALUATION_FAILURE_COMMITMENT_KEYS,
    FRESH_CHAIN_EXPECTED_PHYSICAL_CALL_COUNT,
    FRESH_CHAIN_EXTRACTION_FAILURE_COMMITMENT_KEYS,
    FRESH_CHAIN_LEDGER_AUTHENTICATION,
    FRESH_CHAIN_RUNTIME_TRANSPORT,
    FRESH_CHAIN_STAGES,
    FreshChainFailureDisposition,
    FreshChainStage,
    canonical_sha256,
    fresh_chain_call_failure_sha256,
    provider_disposition_sha256,
)

FRESH_CHAIN_DISPLAY_NAME = FRESH_CHAIN_CANARY_KIND
FRESH_CHAIN_PROVIDER_KIND = FRESH_CHAIN_RUNTIME_TRANSPORT
FRESH_CHAIN_AUTHENTICATION_KIND = FRESH_CHAIN_LEDGER_AUTHENTICATION
FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS = FRESH_CHAIN_EXPECTED_PHYSICAL_CALL_COUNT
FRESH_CHAIN_EVALUATION_STAGES = FRESH_CHAIN_STAGES[1:]
Commitments: TypeAlias = Mapping[str, str] | tuple[tuple[str, str], ...]


class FreshChainCanaryError(RuntimeError):
    """Secret-safe fail-closed error at the fresh-chain application boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class FreshChainLookupDisposition(StrEnum):
    """Authenticated provider state for one exact logical call."""

    AUTHENTICATED_ABSENT = "authenticated_absent"
    TERMINAL = "terminal"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


@final
@dataclass(frozen=True, slots=True)
class FreshChainUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        if (
            any(type(value) is not int or value < 0 for value in self.as_tuple())
            or self.total_tokens != self.prompt_tokens + self.completion_tokens
        ):
            _fail("fresh_chain_usage_invalid")

    def as_tuple(self) -> tuple[int, int, int]:
        return self.prompt_tokens, self.completion_tokens, self.total_tokens

    def payload(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@final
@dataclass(frozen=True, slots=True, repr=False)
class FreshChainCallIntent:
    """Canonical intent for one and only one of the five ordered calls."""

    stage: FreshChainStage
    ordinal: int
    namespace_id: str
    namespace_commitment_sha256: str
    source_commitment_sha256: str
    source_projection_commitment_sha256: str
    input_authority_sha256: str
    canonical_request_body: bytes = field(repr=False)
    retrieval_handoff_sha256: str | None = None
    request_sha256: str = field(init=False)
    intent_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.stage not in FRESH_CHAIN_STAGES
            or type(self.ordinal) is not int
            or self.ordinal != FRESH_CHAIN_STAGES.index(self.stage)
            or not _identifier(self.namespace_id)
            or any(
                not _sha(value)
                for value in (
                    self.namespace_commitment_sha256,
                    self.source_commitment_sha256,
                    self.source_projection_commitment_sha256,
                    self.input_authority_sha256,
                )
            )
            or type(self.canonical_request_body) is not bytes
            or not 1 <= len(self.canonical_request_body) <= 16 * 1024 * 1024
            or (self.stage == "mem0_answer") != (self.retrieval_handoff_sha256 is not None)
            or (
                self.retrieval_handoff_sha256 is not None
                and not _sha(self.retrieval_handoff_sha256)
            )
        ):
            _fail("fresh_chain_intent_invalid")
        request_sha256 = hashlib.sha256(self.canonical_request_body).hexdigest()
        object.__setattr__(self, "request_sha256", request_sha256)
        object.__setattr__(self, "intent_sha256", canonical_sha256(self.material()))

    def material(self) -> dict[str, object]:
        return {
            "case_id": FRESH_CHAIN_CASE_ID,
            "input_authority_sha256": self.input_authority_sha256,
            "namespace_commitment_sha256": self.namespace_commitment_sha256,
            "namespace_id": self.namespace_id,
            "ordinal": self.ordinal,
            "request_sha256": hashlib.sha256(self.canonical_request_body).hexdigest(),
            "retrieval_handoff_sha256": self.retrieval_handoff_sha256,
            "source_commitment_sha256": self.source_commitment_sha256,
            "source_projection_commitment_sha256": (self.source_projection_commitment_sha256),
            "stage": self.stage,
        }


@final
@dataclass(frozen=True, slots=True, repr=False)
class FreshChainCallResult:
    """Authenticated terminal result and unique physical provider receipt."""

    stage: FreshChainStage
    ordinal: int
    intent_sha256: str
    result_sha256: str
    physical_receipt_sha256: str
    receipt_id: str
    usage: FreshChainUsage
    transport_dispatched: bool
    output_text: str = field(default="", repr=False)
    commitments: Commitments = field(default_factory=tuple)

    def __post_init__(self) -> None:
        normalized = _commitments(self.commitments)
        if (
            self.stage not in FRESH_CHAIN_STAGES
            or type(self.ordinal) is not int
            or self.ordinal != FRESH_CHAIN_STAGES.index(self.stage)
            or any(
                not _sha(value)
                for value in (
                    self.intent_sha256,
                    self.result_sha256,
                    self.physical_receipt_sha256,
                )
            )
            or not _identifier(self.receipt_id)
            or type(self.usage) is not FreshChainUsage
            or type(self.transport_dispatched) is not bool
            or type(self.output_text) is not str
            or len(self.output_text.encode("utf-8")) > 16 * 1024 * 1024
        ):
            _fail("fresh_chain_result_invalid")
        object.__setattr__(self, "commitments", normalized)


@final
@dataclass(frozen=True, slots=True, repr=False)
class FreshChainCallFailure:
    """Authenticated known provider failure and its unique physical receipt."""

    stage: FreshChainStage
    ordinal: int
    intent_sha256: str
    physical_receipt_sha256: str
    receipt_id: str
    usage: FreshChainUsage
    provider_disposition: FreshChainFailureDisposition | str
    transport_dispatched: bool
    commitments: Commitments = field(default_factory=tuple)
    failure_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        normalized = _commitments(self.commitments)
        try:
            disposition = FreshChainFailureDisposition(self.provider_disposition)
        except (TypeError, ValueError):
            _fail("fresh_chain_failure_disposition_invalid")
        expected_keys = (
            FRESH_CHAIN_EXTRACTION_FAILURE_COMMITMENT_KEYS
            if self.stage == "mem0_extraction"
            else FRESH_CHAIN_EVALUATION_FAILURE_COMMITMENT_KEYS
        )
        if (
            self.stage not in FRESH_CHAIN_STAGES
            or type(self.ordinal) is not int
            or self.ordinal != FRESH_CHAIN_STAGES.index(self.stage)
            or not _sha(self.intent_sha256)
            or not _sha(self.physical_receipt_sha256)
            or not _identifier(self.receipt_id)
            or type(self.usage) is not FreshChainUsage
            or type(self.transport_dispatched) is not bool
            or set(dict(normalized)) != expected_keys
            or dict(normalized).get("provider_disposition_sha256")
            != provider_disposition_sha256(disposition)
        ):
            _fail("fresh_chain_failure_invalid")
        object.__setattr__(self, "provider_disposition", disposition)
        object.__setattr__(self, "commitments", normalized)
        object.__setattr__(
            self,
            "failure_sha256",
            fresh_chain_call_failure_sha256(
                stage=self.stage,
                intent_sha256=self.intent_sha256,
                provider_disposition=disposition,
                receipt_id=self.receipt_id,
                physical_receipt_sha256=self.physical_receipt_sha256,
                input_tokens=self.usage.prompt_tokens,
                output_tokens=self.usage.completion_tokens,
                total_tokens=self.usage.total_tokens,
                commitments=normalized,
            ),
        )

    def material(self) -> dict[str, object]:
        disposition = self.provider_disposition
        assert type(disposition) is FreshChainFailureDisposition
        return {
            "stage": self.stage,
            "ordinal": self.ordinal,
            "intent_sha256": self.intent_sha256,
            "failure_sha256": self.failure_sha256,
            "provider_disposition": disposition.value,
            "physical_receipt_sha256": self.physical_receipt_sha256,
            "receipt_id": self.receipt_id,
            "usage": self.usage.payload(),
            "transport_dispatched": self.transport_dispatched,
            "commitments": dict(self.commitments),
            "publishable": False,
        }


@final
@dataclass(frozen=True, slots=True)
class FreshChainLookup:
    """Read-only authenticated lookup; only proven absence permits first dispatch."""

    disposition: FreshChainLookupDisposition
    intent_sha256: str
    result: FreshChainCallResult | None = None
    failure: FreshChainCallFailure | None = None
    authenticated_absence_sha256: str | None = None
    ambiguity_sha256: str | None = None

    def __post_init__(self) -> None:
        absent = self.disposition is FreshChainLookupDisposition.AUTHENTICATED_ABSENT
        terminal = self.disposition is FreshChainLookupDisposition.TERMINAL
        ambiguous = self.disposition is FreshChainLookupDisposition.AMBIGUOUS
        failed = self.disposition is FreshChainLookupDisposition.FAILED
        if (
            type(self.disposition) is not FreshChainLookupDisposition
            or not _sha(self.intent_sha256)
            or (terminal != (self.result is not None))
            or (failed != (self.failure is not None))
            or (absent != (self.authenticated_absence_sha256 is not None))
            or (ambiguous != (self.ambiguity_sha256 is not None))
            or (
                self.result is not None
                and (
                    type(self.result) is not FreshChainCallResult
                    or self.result.intent_sha256 != self.intent_sha256
                )
            )
            or (
                self.failure is not None
                and (
                    type(self.failure) is not FreshChainCallFailure
                    or self.failure.intent_sha256 != self.intent_sha256
                )
            )
            or (
                self.authenticated_absence_sha256 is not None
                and not _sha(self.authenticated_absence_sha256)
            )
            or (self.ambiguity_sha256 is not None and not _sha(self.ambiguity_sha256))
            or not (absent or terminal or ambiguous or failed)
        ):
            _fail("fresh_chain_lookup_invalid")


@final
@dataclass(frozen=True, slots=True)
class FreshChainRetrievalHandoff:
    """Extraction-derived memory/retrieval authority consumed by the Mem0 answer."""

    extraction_intent_sha256: str
    extraction_result_sha256: str
    extraction_receipt_sha256: str
    namespace_commitment_sha256: str
    source_commitment_sha256: str
    source_projection_commitment_sha256: str
    memory_authority_sha256: str
    retrieval_authority_sha256: str
    retrieval_material_sha256: str
    memory_count: int
    handoff_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            any(
                not _sha(value)
                for value in (
                    self.extraction_intent_sha256,
                    self.extraction_result_sha256,
                    self.extraction_receipt_sha256,
                    self.namespace_commitment_sha256,
                    self.source_commitment_sha256,
                    self.source_projection_commitment_sha256,
                    self.memory_authority_sha256,
                    self.retrieval_authority_sha256,
                    self.retrieval_material_sha256,
                )
            )
            or type(self.memory_count) is not int
            or self.memory_count < 1
        ):
            _fail("fresh_chain_retrieval_handoff_invalid")
        object.__setattr__(self, "handoff_sha256", canonical_sha256(self.material()))

    def material(self) -> dict[str, object]:
        return {
            "extraction_intent_sha256": self.extraction_intent_sha256,
            "extraction_receipt_sha256": self.extraction_receipt_sha256,
            "extraction_result_sha256": self.extraction_result_sha256,
            "memory_authority_sha256": self.memory_authority_sha256,
            "memory_count": self.memory_count,
            "namespace_commitment_sha256": self.namespace_commitment_sha256,
            "retrieval_authority_sha256": self.retrieval_authority_sha256,
            "retrieval_material_sha256": self.retrieval_material_sha256,
            "source_commitment_sha256": self.source_commitment_sha256,
            "source_projection_commitment_sha256": (self.source_projection_commitment_sha256),
        }


@final
@dataclass(frozen=True, slots=True)
class FreshChainCleanupResult:
    """One exact cleanup operation proving no fresh namespace residue remains."""

    namespace_commitment_sha256: str
    cleanup_authority_sha256: str
    receipt_id: str
    receipt_sha256: str
    outcome_sha256: str
    deleted: bool
    operation_count: int
    residual_count: int
    cleanup_commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            any(
                not _sha(value)
                for value in (
                    self.namespace_commitment_sha256,
                    self.cleanup_authority_sha256,
                    self.receipt_sha256,
                    self.outcome_sha256,
                )
            )
            or not _identifier(self.receipt_id)
            or self.deleted is not True
            or type(self.operation_count) is not int
            or self.operation_count != 1
            or type(self.residual_count) is not int
            or self.residual_count != 0
        ):
            _fail("fresh_chain_cleanup_invalid")
        object.__setattr__(self, "cleanup_commitment_sha256", canonical_sha256(self.material()))

    def material(self) -> dict[str, object]:
        return {
            "cleanup_authority_sha256": self.cleanup_authority_sha256,
            "deleted": self.deleted,
            "namespace_commitment_sha256": self.namespace_commitment_sha256,
            "operation_count": self.operation_count,
            "outcome_sha256": self.outcome_sha256,
            "receipt_id": self.receipt_id,
            "receipt_sha256": self.receipt_sha256,
            "residual_count": self.residual_count,
        }


class FreshChainCanaryRuntimeSession(Protocol):
    """Provider adapter session with separate dispatch and recovery paths."""

    @property
    def namespace_id(self) -> str: ...

    @property
    def namespace_commitment_sha256(self) -> str: ...

    @property
    def source_commitment_sha256(self) -> str: ...

    @property
    def source_projection_commitment_sha256(self) -> str: ...

    @property
    def common_condition_policy_sha256(self) -> str: ...

    def prepare_call(
        self,
        *,
        stage: FreshChainStage,
        prior_results: tuple[FreshChainCallResult, ...],
        retrieval_handoff: FreshChainRetrievalHandoff | None,
    ) -> FreshChainCallIntent: ...

    def lookup(self, intent: FreshChainCallIntent) -> FreshChainLookup: ...

    def dispatch(
        self,
        intent: FreshChainCallIntent,
    ) -> FreshChainCallResult | FreshChainCallFailure: ...

    def recover(self, intent: FreshChainCallIntent) -> FreshChainLookup: ...

    def capture_retrieval(
        self,
        extraction: FreshChainCallResult,
    ) -> FreshChainRetrievalHandoff: ...

    def cleanup(
        self,
        failure: FreshChainCallFailure | None = None,
    ) -> FreshChainCleanupResult: ...

    def close(self) -> None: ...


class FreshChainCanaryDependencyFactoryPort(Protocol):
    """Installed provider root; no generic hosted-job adapter is permitted."""

    def open_fresh_chain_session(
        self,
        *,
        inputs: PublishableRunProviderInputs,
        state_root: Path,
        namespace_id: str,
        namespace_commitment_sha256: str,
        source_commitment_sha256: str,
        resume: bool,
    ) -> FreshChainCanaryRuntimeSession: ...


def call_intent_sha256(intent: FreshChainCallIntent) -> str:
    if type(intent) is not FreshChainCallIntent:
        _fail("fresh_chain_intent_invalid")
    return canonical_sha256(intent.material())


def _commitments(value: object) -> tuple[tuple[str, str], ...]:
    if isinstance(value, Mapping):
        items = tuple(value.items())
    elif type(value) is tuple:
        items = value
    else:
        _fail("fresh_chain_commitments_invalid")
    if any(
        type(item) is not tuple or len(item) != 2 or not _identifier(item[0]) or not _sha(item[1])
        for item in items
    ):
        _fail("fresh_chain_commitments_invalid")
    normalized = tuple(sorted(items))
    if len({key for key, _ in normalized}) != len(normalized):
        _fail("fresh_chain_commitments_invalid")
    return normalized


def _identifier(value: object) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= 512
        and value == value.strip()
        and all(character.isalnum() or character in "._:-" for character in value)
    )


def _sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise FreshChainCanaryError(code) from None


__all__ = (
    "FRESH_CHAIN_AUTHENTICATION_KIND",
    "FRESH_CHAIN_CASE_ID",
    "FRESH_CHAIN_DISPLAY_NAME",
    "FRESH_CHAIN_EVALUATION_STAGES",
    "FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS",
    "FRESH_CHAIN_PROVIDER_KIND",
    "FRESH_CHAIN_STAGES",
    "FreshChainCallFailure",
    "FreshChainCallIntent",
    "FreshChainCallResult",
    "FreshChainCanaryDependencyFactoryPort",
    "FreshChainCanaryError",
    "FreshChainCanaryRuntimeSession",
    "FreshChainCleanupResult",
    "FreshChainFailureDisposition",
    "FreshChainLookup",
    "FreshChainLookupDisposition",
    "FreshChainRetrievalHandoff",
    "FreshChainStage",
    "FreshChainUsage",
    "call_intent_sha256",
    "canonical_sha256",
)
