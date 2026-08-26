"""Static scope and manifest binding for the one-case activation canary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import final

from infinity_context_server.memory_comparison_full_profiles import (
    LOCOMO_OFFICIAL_DATASET_SHA256,
    LONGMEMEVAL_OFFICIAL_DATASET_SHA256,
)
from infinity_context_server.memory_comparison_publishable_canary_methodology import (
    PUBLISHABLE_CANARY_METHODOLOGY_COMMITMENT_SHA256,
    PUBLISHABLE_CANARY_METHODOLOGY_ID,
    publishable_canary_methodology,
)
from infinity_context_server.memory_comparison_publishable_canary_profile import (
    PUBLISHABLE_CANARY_BENCHMARK,
    PUBLISHABLE_CANARY_CASE_ALIAS,
    PUBLISHABLE_CANARY_CASE_ID,
    PUBLISHABLE_CANARY_CASE_INDEX,
    PUBLISHABLE_CANARY_DATASET_SHA256,
    PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT,
    PUBLISHABLE_CANARY_ORDERED_CALL_SHAPES,
    PUBLISHABLE_CANARY_PROFILE_COMMITMENT_SHA256,
    PUBLISHABLE_CANARY_PROFILE_ID,
    PUBLISHABLE_CANARY_RUN_INDEX,
    publishable_canary_profile,
)
from infinity_context_server.memory_comparison_publishable_contracts import (
    canonical_payload_sha256,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
    PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
)

from .contracts import (
    LOCOMO_PROFILE,
    LONGMEMEVAL_PROFILE,
    SchedulerCallStage,
    SchedulerSuiteAuthority,
    commitment,
    run_authority_from_suite,
)
from .manifest import BuiltSchedulerManifest, SchedulerLogicalCall

PUBLISHABLE_CANARY_AUTHORITY_SCHEMA_VERSION = (
    "memory-comparison-publishable-one-case-canary-authority.v1"
)
PUBLISHABLE_CANARY_STATIC_AUTHORITY_SHA256 = (
    "19412a1bb18f9c80c6a8d3470b50c7782be895031a243ba7347d3a19862e13b0"
)


class PublishableCanaryAuthorityError(RuntimeError):
    """Fail-closed rejection of a changed canary or full-suite binding."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableCanaryAuthority:
    """One exact full-manifest prefix, incapable of authorizing a full run."""

    suite_authority_sha256: str
    suite_runtime_provenance_sha256: str
    run_authority_sha256: str
    run_id: str
    run_manifest_authority_sha256: str
    full_case_manifest_sha256: str
    ordered_calls: tuple[
        SchedulerLogicalCall,
        SchedulerLogicalCall,
        SchedulerLogicalCall,
        SchedulerLogicalCall,
    ] = field(repr=False)
    selected_case_authority_sha256: str = field(init=False)
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        values = (
            self.suite_authority_sha256,
            self.suite_runtime_provenance_sha256,
            self.run_authority_sha256,
            self.run_manifest_authority_sha256,
            self.full_case_manifest_sha256,
        )
        if (
            any(not _is_sha256(item) for item in values)
            or type(self.run_id) is not str
            or not self.run_id
            or type(self.ordered_calls) is not tuple
            or len(self.ordered_calls) != PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
            or any(type(item) is not SchedulerLogicalCall for item in self.ordered_calls)
        ):
            _fail("publishable_canary_authority_invalid")
        _require_selected_calls(self.ordered_calls)
        if any(
            call.suite_authority_sha256 != self.suite_authority_sha256
            or call.run_authority_sha256 != self.run_authority_sha256
            or call.run_id != self.run_id
            for call in self.ordered_calls
        ):
            _fail("publishable_canary_authority_crosswired")
        case_authority = commitment(
            "publishable-canary-selected-case",
            {
                "case_alias": PUBLISHABLE_CANARY_CASE_ALIAS,
                "case_id": PUBLISHABLE_CANARY_CASE_ID,
                "case_index": PUBLISHABLE_CANARY_CASE_INDEX,
                "dataset_sha256": PUBLISHABLE_CANARY_DATASET_SHA256,
                "full_case_manifest_sha256": self.full_case_manifest_sha256,
                "run_authority_sha256": self.run_authority_sha256,
            },
        )
        object.__setattr__(self, "selected_case_authority_sha256", case_authority)
        object.__setattr__(
            self,
            "commitment_sha256",
            commitment("publishable-canary-authority", self.material()),
        )

    @property
    def expected_provider_call_count(self) -> int:
        return PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT

    @property
    def ordered_logical_call_ids(self) -> tuple[str, str, str, str]:
        return tuple(call.logical_call_id for call in self.ordered_calls)  # type: ignore[return-value]

    def material(self) -> dict[str, object]:
        return {
            "schema_version": PUBLISHABLE_CANARY_AUTHORITY_SCHEMA_VERSION,
            "static_authority_sha256": PUBLISHABLE_CANARY_STATIC_AUTHORITY_SHA256,
            "canary_profile_id": PUBLISHABLE_CANARY_PROFILE_ID,
            "canary_profile_commitment_sha256": (PUBLISHABLE_CANARY_PROFILE_COMMITMENT_SHA256),
            "canary_methodology_id": PUBLISHABLE_CANARY_METHODOLOGY_ID,
            "canary_methodology_commitment_sha256": (
                PUBLISHABLE_CANARY_METHODOLOGY_COMMITMENT_SHA256
            ),
            "target_full_profile_id": PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
            "target_full_profile_commitment_sha256": (
                PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256
            ),
            "suite_authority_sha256": self.suite_authority_sha256,
            "suite_runtime_provenance_sha256": self.suite_runtime_provenance_sha256,
            "run_authority_sha256": self.run_authority_sha256,
            "run_id": self.run_id,
            "run_manifest_authority_sha256": self.run_manifest_authority_sha256,
            "full_case_manifest_sha256": self.full_case_manifest_sha256,
            "selected_case_authority_sha256": self.selected_case_authority_sha256,
            "ordered_logical_call_ids": list(self.ordered_logical_call_ids),
            "expected_provider_call_count": PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT,
            "publishable": False,
            "full_receipt_eligible": False,
        }


def publishable_canary_static_authority_payload() -> dict[str, object]:
    """Return the caller-independent, reviewed execution scope."""

    return {
        "schema_version": PUBLISHABLE_CANARY_AUTHORITY_SCHEMA_VERSION,
        "profile_id": PUBLISHABLE_CANARY_PROFILE_ID,
        "profile_commitment_sha256": PUBLISHABLE_CANARY_PROFILE_COMMITMENT_SHA256,
        "methodology_id": PUBLISHABLE_CANARY_METHODOLOGY_ID,
        "methodology_commitment_sha256": PUBLISHABLE_CANARY_METHODOLOGY_COMMITMENT_SHA256,
        "target_full_profile_id": PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
        "target_full_profile_commitment_sha256": (
            PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256
        ),
        "target_full_methodology_commitment_sha256": (
            PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
        ),
        "scope": {
            "benchmark": PUBLISHABLE_CANARY_BENCHMARK,
            "dataset_sha256": PUBLISHABLE_CANARY_DATASET_SHA256,
            "run_index": PUBLISHABLE_CANARY_RUN_INDEX,
            "case_index": PUBLISHABLE_CANARY_CASE_INDEX,
            "case_id": PUBLISHABLE_CANARY_CASE_ID,
            "case_alias": PUBLISHABLE_CANARY_CASE_ALIAS,
        },
        "expected_provider_call_count": PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT,
        "ordered_call_shapes": [
            {"backend_role": backend_role, "stage": stage}
            for backend_role, stage in PUBLISHABLE_CANARY_ORDERED_CALL_SHAPES
        ],
        "requested_max_output_tokens_per_call": PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS,
        "caller_scope_or_count_override_allowed": False,
        "activation_evidence_only": True,
        "publishable": False,
        "full_receipt_eligible": False,
        "full_profile_admission": "review_required",
    }


def validate_publishable_canary_static_authority() -> None:
    """Recompute all frozen contracts before any manifest is selected."""

    try:
        publishable_canary_methodology()
        publishable_canary_profile()
        if (
            canonical_payload_sha256(publishable_canary_static_authority_payload())
            != PUBLISHABLE_CANARY_STATIC_AUTHORITY_SHA256
        ):
            raise ValueError
    except Exception:
        _fail("publishable_canary_static_authority_invalid")


def bind_publishable_canary_authority(
    *,
    suite: SchedulerSuiteAuthority,
    manifest: BuiltSchedulerManifest,
) -> PublishableCanaryAuthority:
    """Bind the static canary to the existing production suite manifest prefix."""

    validate_publishable_canary_static_authority()
    if type(suite) is not SchedulerSuiteAuthority:
        _fail("publishable_canary_suite_invalid")
    try:
        run = run_authority_from_suite(suite, run_index=PUBLISHABLE_CANARY_RUN_INDEX)
    except Exception:
        _fail("publishable_canary_suite_invalid")
    if (
        suite.methodology_sha256 != PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
        or tuple(item.profile for item in suite.ordered_runs)
        != (LOCOMO_PROFILE, LONGMEMEVAL_PROFILE)
        or tuple(item.dataset_sha256 for item in suite.ordered_runs)
        != (LOCOMO_OFFICIAL_DATASET_SHA256, LONGMEMEVAL_OFFICIAL_DATASET_SHA256)
        or any(
            item.limits.answer_max_output_tokens != PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS
            or item.limits.judge_max_output_tokens != PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS
            for item in suite.ordered_runs
        )
    ):
        _fail("publishable_canary_suite_invalid")
    if (
        type(manifest) is not BuiltSchedulerManifest
        or manifest.authority.suite_authority_sha256 != suite.commitment_sha256
        or manifest.authority.run_authority_sha256 != run.commitment_sha256
        or manifest.authority.run_id != run.binding.run_id
        or manifest.authority.case_manifest_sha256 != run.binding.case_manifest_sha256
        or manifest.authority.call_count != run.binding.profile.call_count
        or len(manifest.shards) != run.binding.profile.shard_count
        or tuple(item.commitment_sha256 for item in manifest.shards)
        != manifest.authority.ordered_shard_commitments
        or not manifest.shards
    ):
        _fail("publishable_canary_manifest_invalid")
    selected = manifest.shards[0].calls[:PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT]
    _require_selected_calls(selected)
    try:
        return PublishableCanaryAuthority(
            suite_authority_sha256=suite.commitment_sha256,
            suite_runtime_provenance_sha256=suite.runtime_provenance_sha256,
            run_authority_sha256=run.commitment_sha256,
            run_id=run.binding.run_id,
            run_manifest_authority_sha256=manifest.authority.commitment_sha256,
            full_case_manifest_sha256=run.binding.case_manifest_sha256,
            ordered_calls=selected,
        )
    except PublishableCanaryAuthorityError:
        raise
    except Exception:
        _fail("publishable_canary_authority_invalid")


def _require_selected_calls(calls: tuple[SchedulerLogicalCall, ...]) -> None:
    if type(calls) is not tuple or len(calls) != PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT:
        _fail("publishable_canary_selected_case_invalid")
    expected = tuple(
        (
            ordinal,
            backend_role,
            SchedulerCallStage(stage),
        )
        for ordinal, (backend_role, stage) in enumerate(PUBLISHABLE_CANARY_ORDERED_CALL_SHAPES)
    )
    if any(
        type(call) is not SchedulerLogicalCall
        or call.ordinal != ordinal
        or call.case_index != PUBLISHABLE_CANARY_CASE_INDEX
        or call.case_id != PUBLISHABLE_CANARY_CASE_ID
        or call.case_alias != PUBLISHABLE_CANARY_CASE_ALIAS
        or call.backend_role != backend_role
        or call.stage is not stage
        or call.token_ceiling != PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS
        for call, (ordinal, backend_role, stage) in zip(calls, expected, strict=True)
    ):
        _fail("publishable_canary_selected_case_invalid")
    if (
        calls[1].depends_on_logical_call_id != calls[0].logical_call_id
        or calls[3].depends_on_logical_call_id != calls[2].logical_call_id
    ):
        _fail("publishable_canary_selected_case_invalid")


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _fail(code: str) -> None:
    raise PublishableCanaryAuthorityError(code) from None


__all__ = (
    "PUBLISHABLE_CANARY_AUTHORITY_SCHEMA_VERSION",
    "PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT",
    "PUBLISHABLE_CANARY_STATIC_AUTHORITY_SHA256",
    "PublishableCanaryAuthority",
    "PublishableCanaryAuthorityError",
    "bind_publishable_canary_authority",
    "publishable_canary_static_authority_payload",
    "validate_publishable_canary_static_authority",
)
