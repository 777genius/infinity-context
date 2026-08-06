from __future__ import annotations

import copy
import pickle

import pytest
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_200,
    public_full_comparison_profile,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_platform_profile_compat import (
    PLATFORM_COMPAT_REFERENCE_BLOCKERS,
    platform_profile_compatibility_contract,
    public_platform_profile_compatibility_contract,
)
from infinity_context_server.memory_comparison_publishable_contracts import (
    freeze_publishable_payload,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_METHODOLOGY_ID,
    public_publishable_methodology,
    resolve_publishable_methodology,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError


def test_methodology_is_its_own_sealed_schema_with_required_unobserved_facts() -> None:
    methodology = resolve_publishable_methodology()
    assert methodology is not None
    public = public_publishable_methodology(methodology)

    assert public["schema_version"] == "memory-comparison-publishable-methodology.v2"
    assert public["methodology_id"] == PUBLISHABLE_METHODOLOGY_ID
    assert public["required_provider_kind"] == "subscription-runtime"
    assert public["required_provider_trust"] == "codex_subscription_runtime"
    assert public["required_model"] == "gpt-5.6-sol"
    assert public["required_reasoning_effort"] == "high"
    assert public["required_service_tier"] == "default"
    assert public["required_transport_contract_id"] == (
        "subscription-runtime-openai-codex-bridge.v4"
    )
    assert public["required_system_fingerprint_prefix"] == (
        "subscription-runtime-codex-bridge-v4:"
    )
    assert public["required_runtime_receipt_schema"] == (
        "subscription-runtime-codex-execution-receipt.v2"
    )
    assert public["required_execution_profile"] == "stateless-completion"
    assert public["required_base_instructions_sha256"] == (
        "5c15d6c502d380282a933d4f20a886a06c9d04d3b5d7c918b95df0b0acf33671"
    )
    assert public["required_runtime_source_commit"] == (
        "e904ec95fda4b04c333e5a7613c7729bf7abb125"
    )
    assert public["required_extraction_scope"] == "shared_full_run"
    assert public["required_extraction_binding"] == "run_attested_loopback_route"
    normalization = public["required_judge_response_format_normalization"]
    assert normalization["benchmark"] == "locomo"
    assert normalization["stage"] == "judge"
    assert normalization["source_response_format"] == {"type": "json_object"}
    assert normalization["backend_roles"] == ["infinity-context", "mem0"]
    assert normalization["backend_application"] == "identical"
    assert normalization["canonical_schema_sha256"] == (
        "2461f7a465be82aa67751dc04e0717cde75c69b86e7db54bb306a2e3d1d4d8f0"
    )
    assert normalization["canonical_policy_sha256"] == (
        "9d7bcc89f3e8cc3683a18d83d90d6ffde05cdb02358d1cd055bf273f92a772f1"
    )
    equivalence = public["required_full_run_extraction_equivalence"]
    assert equivalence == {
        "activation_policy": "fail_closed",
        "required": True,
        "required_capacity": "attested_full_run",
        "required_route": "run_attested_loopback_route",
        "required_usage_ledger": "attested_full_run_usage_ledger",
        "current_runtime_capability": "isolated_single_add",
        "current_capability_satisfies_requirement": False,
    }
    assert public["single_pass"] is True
    assert not any(key.startswith("observed_") for key in public)


def test_methodology_keeps_exact_runtime_prompt_and_retrieval_requirements() -> None:
    methodology = resolve_publishable_methodology()
    assert methodology is not None
    public = public_publishable_methodology(methodology)

    assert public["runtime_pin_file_sha256"] == (
        "ae90790753549d621ba4f521a2d64026b4d2de7286fd9e683ad195cf1c85c525"
    )
    assert public["prompt_file_sha256"] == {
        "locomo": "8ebac1ef60e9ab5caf99079fdaac038b85472e81491ed35e2d2655f3927c76c2",
        "longmemeval": "ba8cf60d26f1390ecbef0f07b3e950556fe3bc5a37ba4b5343f28217f18c144f",
    }
    assert public["retrieval_top_k"] == 200
    assert public["answer_cutoff"] == 50
    assert public["gold_blind"] is True
    assert public["judge_evidence"] is False


def test_methodology_verifier_rejects_valid_json_drift() -> None:
    methodology = resolve_publishable_methodology()
    assert methodology is not None
    public = public_publishable_methodology(methodology)
    public["required_model"] = "gpt-drift"
    tampered = freeze_publishable_payload(
        profile_id=PUBLISHABLE_METHODOLOGY_ID,
        payload=public,
    )

    with pytest.raises(BenchmarkValidationError, match="differs from frozen primitives"):
        public_publishable_methodology(tampered)


def test_methodology_copy_is_identity_and_pickle_is_forbidden() -> None:
    methodology = resolve_publishable_methodology()
    assert methodology is not None
    assert copy.copy(methodology) is methodology
    assert copy.deepcopy(methodology) is methodology
    with pytest.raises(TypeError, match="cannot be pickled"):
        pickle.dumps(methodology)


def test_platform_compatibility_is_reference_only_and_blocked() -> None:
    legacy = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_200)
    assert legacy is not None
    before = public_full_comparison_profile(legacy)

    public = public_platform_profile_compatibility_contract(
        platform_profile_compatibility_contract(legacy)
    )

    assert public["implementation_status"] == "reference_only"
    assert public["execution_enabled"] is False
    assert public["publishable"] is False
    assert public["claim_scope"] == "observational_reference_only"
    assert public["reference_blockers"] == list(PLATFORM_COMPAT_REFERENCE_BLOCKERS)
    assert public_full_comparison_profile(legacy) == before


def test_platform_compatibility_contract_is_copy_stable_and_unpicklable() -> None:
    legacy = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_200)
    assert legacy is not None
    contract = platform_profile_compatibility_contract(legacy)

    assert copy.copy(contract) is contract
    assert copy.deepcopy(contract) is contract
    with pytest.raises(TypeError, match="cannot be pickled"):
        pickle.dumps(contract)
