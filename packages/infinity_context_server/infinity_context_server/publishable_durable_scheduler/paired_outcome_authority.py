"""Reviewed authority mapping and strict judge normalization policy."""

from __future__ import annotations

from infinity_context_server.memory_comparison_publishable_contracts import (
    canonical_payload_sha256,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_METHODOLOGY_COMMITMENT_SHA256,
    PUBLISHABLE_METHODOLOGY_ID,
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
    public_publishable_methodology,
    resolve_publishable_methodology,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
    PUBLISHABLE_PROFILE_COMMITMENT_SHA256,
    PUBLISHABLE_PROFILE_ID,
    public_publishable_comparison_profile,
    resolve_publishable_comparison_profile,
)
from infinity_context_server.memory_comparison_response_format_policy import (
    locomo_judge_response_format_policy_sha256,
)

PAIRED_AUTHORITY_MAPPING_SCHEMA_VERSION = "memory-comparison-paired-authority-mapping.v1"
_ORDERED_BACKEND_ROLES = ("infinity-context", "mem0")


class PairedOutcomeAuthorityError(ValueError):
    """Fail-closed rejection of a changed or invalid authority mapping."""


def paired_authority_mapping_payload() -> dict[str, object]:
    """Bind the reviewed v4 execution to the unchanged v3 statistics authority."""

    return {
        "schema_version": PAIRED_AUTHORITY_MAPPING_SCHEMA_VERSION,
        "scope": "paired_statistics_authority_only",
        "execution": {
            "profile_id": PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
            "profile_commitment_sha256": PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
            "methodology_id": PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
            "methodology_commitment_sha256": (
                PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
            ),
        },
        "frozen_policy_evidence": {
            "profile_id": PUBLISHABLE_PROFILE_ID,
            "profile_commitment_sha256": PUBLISHABLE_PROFILE_COMMITMENT_SHA256,
            "methodology_id": PUBLISHABLE_METHODOLOGY_ID,
            "methodology_commitment_sha256": PUBLISHABLE_METHODOLOGY_COMMITMENT_SHA256,
        },
        "allowed_profile_json_pointer_differences": [
            "/schema_version",
            "/profile_id",
            "/methodology/schema_version",
            "/methodology/methodology_id",
            "/methodology/commitment_sha256",
        ],
        "allowed_methodology_json_pointer_differences": [
            "/schema_version",
            "/methodology_id",
            "/required_service_tier",
        ],
        "required_execution_service_tier": "priority",
        "frozen_policy_evidence_service_tier": "default",
        "same_pairing_categories_prompts_model_and_judge_semantics": True,
    }


PAIRED_AUTHORITY_MAPPING_SHA256 = canonical_payload_sha256(paired_authority_mapping_payload())


def paired_judge_normalization_policy_payload() -> dict[str, object]:
    """Describe the strict binary normalization applied before aggregation."""

    return {
        "schema_version": "memory-comparison-paired-judge-normalization-policy.v1",
        "locomo": {
            "encoding": "utf-8",
            "shape": "exact-json-object-reasoning-and-label",
            "labels": ["CORRECT", "WRONG"],
            "response_format_policy_sha256": locomo_judge_response_format_policy_sha256(),
        },
        "longmemeval": {
            "encoding": "utf-8",
            "verdict_region": "after-final-closing-thinking-tag-or-entire-output",
            "accepted_exact_case_insensitive_verdicts": ["yes", "no"],
        },
        "malformed_or_ambiguous": "terminal_rejected",
        "ordered_backend_roles": list(_ORDERED_BACKEND_ROLES),
    }


PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256 = canonical_payload_sha256(
    paired_judge_normalization_policy_payload()
)


def validate_paired_authority_mapping() -> None:
    """Recheck that v3 and v4 differ only at the reviewed identity/tier paths."""

    try:
        profile_v3 = resolve_publishable_comparison_profile(PUBLISHABLE_PROFILE_ID)
        profile_v4 = resolve_publishable_comparison_profile(PUBLISHABLE_PRIORITY_PROFILE_V4_ID)
        methodology_v3 = resolve_publishable_methodology(PUBLISHABLE_METHODOLOGY_ID)
        methodology_v4 = resolve_publishable_methodology(PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID)
        if any(item is None for item in (profile_v3, profile_v4, methodology_v3, methodology_v4)):
            _fail()
        left_profile = public_publishable_comparison_profile(profile_v3)
        right_profile = public_publishable_comparison_profile(profile_v4)
        left_methodology = public_publishable_methodology(methodology_v3)
        right_methodology = public_publishable_methodology(methodology_v4)
        payload = paired_authority_mapping_payload()
        _mask_paths(
            left_profile,
            right_profile,
            payload["allowed_profile_json_pointer_differences"],
        )
        _mask_paths(
            left_methodology,
            right_methodology,
            payload["allowed_methodology_json_pointer_differences"],
        )
        if left_profile != right_profile or left_methodology != right_methodology:
            _fail()
    except PairedOutcomeAuthorityError:
        raise
    except Exception:
        _fail()


def _mask_paths(left: dict[str, object], right: dict[str, object], paths: object) -> None:
    if type(paths) is not list:
        _fail()
    for path in paths:
        if type(path) is not str or not path.startswith("/"):
            _fail()
        keys = path.removeprefix("/").split("/")
        left_cursor: dict[str, object] = left
        right_cursor: dict[str, object] = right
        for key in keys[:-1]:
            left_value = left_cursor.get(key)
            right_value = right_cursor.get(key)
            if type(left_value) is not dict or type(right_value) is not dict:
                _fail()
            left_cursor = left_value
            right_cursor = right_value
        final = keys[-1]
        if final not in left_cursor or final not in right_cursor:
            _fail()
        left_cursor[final] = "<reviewed-difference>"
        right_cursor[final] = "<reviewed-difference>"


def _fail() -> None:
    raise PairedOutcomeAuthorityError("paired_authority_mapping_invalid") from None


__all__ = (
    "PAIRED_AUTHORITY_MAPPING_SHA256",
    "PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256",
    "PairedOutcomeAuthorityError",
    "paired_authority_mapping_payload",
    "paired_judge_normalization_policy_payload",
    "validate_paired_authority_mapping",
)
