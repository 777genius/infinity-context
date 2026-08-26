"""Frozen execution authority for exactly one fresh extraction plus four evaluations."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import final

from infinity_context_server.memory_comparison_publishable_canary_profile import (
    PUBLISHABLE_CANARY_BENCHMARK,
    PUBLISHABLE_CANARY_CASE_ALIAS,
    PUBLISHABLE_CANARY_CASE_ID,
    PUBLISHABLE_CANARY_CASE_INDEX,
    PUBLISHABLE_CANARY_DATASET_SHA256,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_contracts import (
    SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT,
)
from infinity_context_server.publishable_durable_scheduler.runner_official_request_renderer import (
    SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
    SCHEDULER_OFFICIAL_REQUEST_MODEL,
    SCHEDULER_OFFICIAL_REQUEST_REASONING_EFFORT,
    SCHEDULER_OFFICIAL_REQUEST_SERVICE_TIER,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
)

from .authorization import FRESH_CHAIN_LIVE_1_PLUS_4_FLAG
from .contracts import (
    FRESH_CHAIN_AUTHENTICATION_KIND,
    FRESH_CHAIN_CASE_ID,
    FRESH_CHAIN_DISPLAY_NAME,
    FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS,
    FRESH_CHAIN_PROVIDER_KIND,
    FRESH_CHAIN_STAGES,
    FreshChainCanaryError,
    canonical_sha256,
)

FRESH_CHAIN_AUTHORITY_SCHEMA = "memory-comparison-publishable-fresh-chain-authority.v1"
FRESH_CHAIN_AUTHORITY_ID = "ic-vs-mem0-fresh-chain-conv-26-1-plus-4-v1"
FRESH_CHAIN_REQUEST_RENDERER_IMPLEMENTATION = "fresh-chain-official-answer-judge-openai-chat.v1"
FRESH_CHAIN_REQUEST_RENDERER_IMPLEMENTATION_SHA256 = hashlib.sha256(
    b"fresh-chain-official-answer-judge-openai-chat.v1\0"
    b"same-pinned-official-prompts-and-request-condition;"
    b"nonce-binds-fresh-namespace-source-stage-prior-results-and-input-authority;"
    b"mem0-answer-requires-same-extraction-retrieval-handoff"
).hexdigest()
# Frozen below; validated against the complete payload before any dependency opens.
FRESH_CHAIN_STATIC_AUTHORITY_SHA256 = (
    "cf929fb9915f5564b209579d26bbcc39c9985f1b1175c67aa155a1dfd30b60d0"
)


@final
@dataclass(frozen=True, slots=True)
class FreshChainCanaryAuthority:
    namespace_commitment_sha256: str
    source_commitment_sha256: str
    static_authority_sha256: str = FRESH_CHAIN_STATIC_AUTHORITY_SHA256
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        validate_fresh_chain_static_authority()
        if (
            any(
                not _sha(value)
                for value in (
                    self.namespace_commitment_sha256,
                    self.source_commitment_sha256,
                    self.static_authority_sha256,
                )
            )
            or self.static_authority_sha256 != FRESH_CHAIN_STATIC_AUTHORITY_SHA256
            or hmac.compare_digest(
                self.namespace_commitment_sha256,
                self.source_commitment_sha256,
            )
        ):
            _fail("fresh_chain_authority_invalid")
        object.__setattr__(self, "commitment_sha256", canonical_sha256(self.material()))

    def material(self) -> dict[str, object]:
        return {
            "authority_id": FRESH_CHAIN_AUTHORITY_ID,
            "namespace_commitment_sha256": self.namespace_commitment_sha256,
            "schema_version": FRESH_CHAIN_AUTHORITY_SCHEMA,
            "source_commitment_sha256": self.source_commitment_sha256,
            "static_authority_sha256": self.static_authority_sha256,
        }


def fresh_chain_static_authority_payload() -> dict[str, object]:
    """Return the reviewed caller-independent 1+4 scope."""

    return {
        "activation_evidence_only": True,
        "authentication": FRESH_CHAIN_AUTHENTICATION_KIND,
        "authorization_flag": FRESH_CHAIN_LIVE_1_PLUS_4_FLAG,
        "caller_scope_or_count_override_allowed": False,
        "case": {
            "benchmark": PUBLISHABLE_CANARY_BENCHMARK,
            "case_alias": PUBLISHABLE_CANARY_CASE_ALIAS,
            "case_id": PUBLISHABLE_CANARY_CASE_ID,
            "case_index": PUBLISHABLE_CANARY_CASE_INDEX,
            "dataset_sha256": PUBLISHABLE_CANARY_DATASET_SHA256,
        },
        "display_name": FRESH_CHAIN_DISPLAY_NAME,
        "evaluation": {
            "call_count": 4,
            "common_condition": {
                "answer_cutoff": SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
                "max_output_tokens": SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
                "methodology_commitment_sha256": (
                    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
                ),
                "model": SCHEDULER_OFFICIAL_REQUEST_MODEL,
                "profile_commitment_sha256": (PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256),
                "reasoning_effort": SCHEDULER_OFFICIAL_REQUEST_REASONING_EFFORT,
                "renderer_implementation_sha256": (
                    FRESH_CHAIN_REQUEST_RENDERER_IMPLEMENTATION_SHA256
                ),
                "retrieval_top_k": SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT,
                "service_tier": SCHEDULER_OFFICIAL_REQUEST_SERVICE_TIER,
                "temperature": 0,
            },
            "ordered_stages": list(FRESH_CHAIN_STAGES[1:]),
        },
        "expected_physical_attempt_count": FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS,
        "extraction": {
            "authenticated_call_required": True,
            "call_count": 1,
            "fresh_isolated_namespace_required": True,
            "retrieval_from_same_extraction_required": True,
            "scope": "isolated_whole_official_corpus_single_add",
            "source_pack_policy": "fresh-chain-whole-corpus-pack-v1",
            "seam": "PublishableExtractionOneShotPort",
            "stage": FRESH_CHAIN_STAGES[0],
        },
        "full_profile_execution_enabled": False,
        "full_publication_gate_satisfied": False,
        "full_receipt_eligible": False,
        "id": FRESH_CHAIN_AUTHORITY_ID,
        "ordered_stages": list(FRESH_CHAIN_STAGES),
        "paid_go_ready": False,
        "provider": FRESH_CHAIN_PROVIDER_KIND,
        "publishable": False,
        "quality_or_superiority_claimed": False,
        "result_2040": False,
        "retrieval_handoff": {
            "mem0_answer_stage": "mem0_answer",
            "same_extraction_memory_authority_required": True,
            "same_extraction_receipt_required": True,
        },
        "schema_version": FRESH_CHAIN_AUTHORITY_SCHEMA,
        "request_renderer": {
            "implementation": FRESH_CHAIN_REQUEST_RENDERER_IMPLEMENTATION,
            "implementation_sha256": (FRESH_CHAIN_REQUEST_RENDERER_IMPLEMENTATION_SHA256),
        },
    }


def validate_fresh_chain_static_authority() -> None:
    if (
        FRESH_CHAIN_CASE_ID != "conv-26:qa:1"
        or PUBLISHABLE_CANARY_CASE_ID != FRESH_CHAIN_CASE_ID
        or canonical_sha256(fresh_chain_static_authority_payload())
        != FRESH_CHAIN_STATIC_AUTHORITY_SHA256
    ):
        _fail("fresh_chain_static_authority_invalid")


def _sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise FreshChainCanaryError(code) from None


__all__ = (
    "FRESH_CHAIN_AUTHORITY_ID",
    "FRESH_CHAIN_AUTHORITY_SCHEMA",
    "FRESH_CHAIN_STATIC_AUTHORITY_SHA256",
    "FRESH_CHAIN_REQUEST_RENDERER_IMPLEMENTATION",
    "FRESH_CHAIN_REQUEST_RENDERER_IMPLEMENTATION_SHA256",
    "FreshChainCanaryAuthority",
    "fresh_chain_static_authority_payload",
    "validate_fresh_chain_static_authority",
)
