"""Non-executable compatibility contract for legacy managed Platform profiles."""

from __future__ import annotations

from infinity_context_server.memory_comparison_full_profiles import (
    FULL_COMPARISON_PROFILES,
    FullComparisonProfile,
    frozen_full_comparison_profile,
)
from infinity_context_server.memory_comparison_publishable_contracts import (
    FrozenPublishablePayload,
    freeze_publishable_payload,
    validated_publishable_payload,
)

PLATFORM_COMPAT_SCHEMA_VERSION = "memory-comparison-platform-profile-compat.v1"
PLATFORM_COMPAT_CLAIM_SCOPE = "observational_reference_only"
PLATFORM_COMPAT_REFERENCE_BLOCKERS = (
    "not_same_run_pinned_oss",
    "platform_server_revision_unattestable",
)


def platform_profile_compatibility_contract(
    profile: FullComparisonProfile,
) -> FrozenPublishablePayload:
    trusted = frozen_full_comparison_profile(profile)
    return freeze_publishable_payload(
        profile_id=trusted.profile_id,
        payload=_compatibility_payload(trusted.profile_id),
    )


def public_platform_profile_compatibility_contract(
    contract: FrozenPublishablePayload,
) -> dict[str, object]:
    profile_id = _contract_profile_id(contract)
    return validated_publishable_payload(
        contract,
        profile_id=profile_id,
        expected=_compatibility_payload(profile_id),
    )


def _contract_profile_id(contract: FrozenPublishablePayload) -> str:
    if type(contract) is not FrozenPublishablePayload:
        return "invalid"
    profile_id = contract.profile_id
    return profile_id if type(profile_id) is str else "invalid"


def _compatibility_payload(profile_id: str) -> dict[str, object]:
    if profile_id not in FULL_COMPARISON_PROFILES:
        profile_id = "invalid"
    return {
        "schema_version": PLATFORM_COMPAT_SCHEMA_VERSION,
        "profile_id": profile_id,
        "implementation_status": "reference_only",
        "execution_enabled": False,
        "publishable": False,
        "claim_scope": PLATFORM_COMPAT_CLAIM_SCOPE,
        "reference_blockers": list(PLATFORM_COMPAT_REFERENCE_BLOCKERS),
    }


__all__ = (
    "PLATFORM_COMPAT_CLAIM_SCOPE",
    "PLATFORM_COMPAT_SCHEMA_VERSION",
    "PLATFORM_COMPAT_REFERENCE_BLOCKERS",
    "platform_profile_compatibility_contract",
    "public_platform_profile_compatibility_contract",
)
