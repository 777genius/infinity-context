"""Static fail-closed authority for paid publishable-comparison execution.

The active profile, methodology, and production composition remain independent
authorities.  This policy admits execution only when one code-reviewed binding
pins all three commitments and every pre-execution readiness fact is true.
Publication is deliberately not granted here; that requires a later
authenticated terminal result.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import final

from infinity_context_server.memory_comparison_publishable_contracts import (
    FrozenPublishablePayload,
    canonical_payload_sha256,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_SCHEMA_VERSION,
    public_publishable_methodology,
    publishable_priority_methodology_v4,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
    PUBLISHABLE_PRIORITY_PROFILE_V4_SCHEMA_VERSION,
    public_publishable_comparison_profile,
    publishable_priority_comparison_profile_v4,
)

PUBLISHABLE_EXECUTION_POLICY_SCHEMA_VERSION = "memory-comparison-publishable-execution-policy.v1"
PUBLISHABLE_EXECUTION_REVIEW_SCHEMA_VERSION = "memory-comparison-publishable-execution-review.v1"
PUBLISHABLE_PRODUCTION_ORCHESTRATION_SCHEMA_VERSION = (
    "memory-comparison-publishable-production-composition.v2"
)
PUBLISHABLE_EXECUTABLE_IMPLEMENTATION_STATUS = "executable"

# Independently pinned to the current production-composition facts.  Those
# facts intentionally include three false paid-go authorities, so the matching
# active v4 candidate is authenticated but cannot be admitted.
PUBLISHABLE_REVIEWED_ORCHESTRATION_COMMITMENT_SHA256 = (
    "56bcf9a672ea1820d19da197bbca0d970a3cf4f43c80847f86f3efaeda5be09f"
)

_TOKEN = object()
_SHA256_LENGTH = 64
_EXPECTED_BENCHMARKS = ("locomo", "longmemeval")


class PublishableExecutionPolicyError(RuntimeError):
    """Stable secret-free rejection from the static execution policy."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class PublishableExecutionProfileAuthority:
    """Authenticated execution-relevant projection of one frozen profile."""

    schema_version: str
    profile_id: str
    commitment_sha256: str
    implementation_status: str
    execution_enabled: bool
    publishable: bool
    activation_blockers: tuple[str, ...]
    benchmark_execution_enabled: tuple[tuple[str, bool], ...]
    methodology_schema_version: str
    methodology_id: str
    methodology_commitment_sha256: str
    methodology_observed: bool
    source_payload: FrozenPublishablePayload = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            not _identifier(self.schema_version)
            or not _identifier(self.profile_id)
            or not _digest(self.commitment_sha256)
            or not _identifier(self.implementation_status)
            or type(self.execution_enabled) is not bool
            or type(self.publishable) is not bool
            or not _string_tuple(self.activation_blockers)
            or len(set(self.activation_blockers)) != len(self.activation_blockers)
            or type(self.benchmark_execution_enabled) is not tuple
            or not self.benchmark_execution_enabled
            or any(
                type(item) is not tuple
                or len(item) != 2
                or not _identifier(item[0])
                or type(item[1]) is not bool
                for item in self.benchmark_execution_enabled
            )
            or len({item[0] for item in self.benchmark_execution_enabled})
            != len(self.benchmark_execution_enabled)
            or not _identifier(self.methodology_schema_version)
            or not _identifier(self.methodology_id)
            or not _digest(self.methodology_commitment_sha256)
            or type(self.methodology_observed) is not bool
            or type(self.source_payload) is not FrozenPublishablePayload
            or self.source_payload.profile_id != self.profile_id
            or self.source_payload.commitment_sha256 != self.commitment_sha256
        ):
            _fail("publishable_execution_profile_authority_invalid")


@final
@dataclass(frozen=True, slots=True)
class PublishableExecutionMethodologyAuthority:
    """Authenticated required-capability projection of one methodology."""

    schema_version: str
    methodology_id: str
    commitment_sha256: str
    equivalence_activation_policy: str
    equivalence_required: bool
    required_capacity: str
    current_runtime_capability: str
    current_capability_satisfies_requirement: bool
    source_payload: FrozenPublishablePayload = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            not _identifier(self.schema_version)
            or not _identifier(self.methodology_id)
            or not _digest(self.commitment_sha256)
            or not _identifier(self.equivalence_activation_policy)
            or type(self.equivalence_required) is not bool
            or not _identifier(self.required_capacity)
            or not _identifier(self.current_runtime_capability)
            or type(self.current_capability_satisfies_requirement) is not bool
            or type(self.source_payload) is not FrozenPublishablePayload
            or self.source_payload.profile_id != self.methodology_id
            or self.source_payload.commitment_sha256 != self.commitment_sha256
        ):
            _fail("publishable_execution_methodology_authority_invalid")


@final
@dataclass(frozen=True, slots=True)
class PublishableExecutionOrchestrationAuthority:
    """Committed production-composition facts consumed by the pure policy."""

    schema_version: str
    profile_id: str
    profile_commitment_sha256: str
    methodology_id: str
    methodology_commitment_sha256: str
    scheduler_paid_go_ready: bool
    runner_paid_go_ready: bool
    durable_store_paid_go_ready: bool
    production_bridge_adapter_ready: bool
    publishable: bool
    readiness_blockers: tuple[str, ...]
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            not _identifier(self.schema_version)
            or not _identifier(self.profile_id)
            or not _digest(self.profile_commitment_sha256)
            or not _identifier(self.methodology_id)
            or not _digest(self.methodology_commitment_sha256)
            or any(
                type(value) is not bool
                for value in (
                    self.scheduler_paid_go_ready,
                    self.runner_paid_go_ready,
                    self.durable_store_paid_go_ready,
                    self.production_bridge_adapter_ready,
                    self.publishable,
                )
            )
            or not _string_tuple(self.readiness_blockers)
            or len(set(self.readiness_blockers)) != len(self.readiness_blockers)
        ):
            _fail("publishable_execution_orchestration_authority_invalid")
        expected = canonical_payload_sha256(self.material())
        observed = getattr(self, "commitment_sha256", None)
        if observed is not None and not hmac.compare_digest(observed, expected):
            _fail("publishable_execution_orchestration_authority_invalid")
        object.__setattr__(self, "commitment_sha256", expected)

    def material(self) -> dict[str, object]:
        return {
            "durable_store_paid_go_ready": self.durable_store_paid_go_ready,
            "methodology_commitment_sha256": self.methodology_commitment_sha256,
            "methodology_id": self.methodology_id,
            "production_bridge_adapter_ready": self.production_bridge_adapter_ready,
            "profile_commitment_sha256": self.profile_commitment_sha256,
            "profile_id": self.profile_id,
            "publishable": self.publishable,
            "readiness_blockers": list(self.readiness_blockers),
            "runner_paid_go_ready": self.runner_paid_go_ready,
            "scheduler_paid_go_ready": self.scheduler_paid_go_ready,
            "schema_version": self.schema_version,
        }


@final
@dataclass(frozen=True, slots=True)
class PublishableExecutionReview:
    """Independent code-review pin for profile, methodology, and composition."""

    profile_schema_version: str
    profile_id: str
    profile_commitment_sha256: str
    methodology_schema_version: str
    methodology_id: str
    methodology_commitment_sha256: str
    orchestration_schema_version: str
    orchestration_commitment_sha256: str
    commitment_sha256: str = field(init=False)
    schema_version: str = PUBLISHABLE_EXECUTION_REVIEW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            self.schema_version != PUBLISHABLE_EXECUTION_REVIEW_SCHEMA_VERSION
            or not _identifier(self.profile_schema_version)
            or not _identifier(self.profile_id)
            or not _digest(self.profile_commitment_sha256)
            or not _identifier(self.methodology_schema_version)
            or not _identifier(self.methodology_id)
            or not _digest(self.methodology_commitment_sha256)
            or not _identifier(self.orchestration_schema_version)
            or not _digest(self.orchestration_commitment_sha256)
        ):
            _fail("publishable_execution_review_invalid")
        expected = canonical_payload_sha256(self.material())
        observed = getattr(self, "commitment_sha256", None)
        if observed is not None and not hmac.compare_digest(observed, expected):
            _fail("publishable_execution_review_invalid")
        object.__setattr__(self, "commitment_sha256", expected)

    def material(self) -> dict[str, str]:
        return {
            "methodology_commitment_sha256": self.methodology_commitment_sha256,
            "methodology_id": self.methodology_id,
            "methodology_schema_version": self.methodology_schema_version,
            "orchestration_commitment_sha256": self.orchestration_commitment_sha256,
            "orchestration_schema_version": self.orchestration_schema_version,
            "profile_commitment_sha256": self.profile_commitment_sha256,
            "profile_id": self.profile_id,
            "profile_schema_version": self.profile_schema_version,
            "schema_version": self.schema_version,
        }


@final
class PublishableExecutionAuthority:
    """Opaque static admission; never a publication authority."""

    __slots__ = ("__commitment_sha256", "__material", "__token")

    def __init__(self, *, material: dict[str, str], _token: object) -> None:
        if _token is not _TOKEN:
            _fail("publishable_execution_authority_invalid")
        self.__material = material
        self.__commitment_sha256 = canonical_payload_sha256(material)
        self.__token = _TOKEN

    @property
    def commitment_sha256(self) -> str:
        return self.__commitment_sha256

    def __repr__(self) -> str:
        return "PublishableExecutionAuthority(<static-reviewed>)"

    def __copy__(self) -> PublishableExecutionAuthority:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> PublishableExecutionAuthority:
        memo[id(self)] = self
        return self

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("PublishableExecutionAuthority cannot be pickled")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("PublishableExecutionAuthority is final")


def publishable_execution_profile_authority(
    profile: FrozenPublishablePayload,
) -> PublishableExecutionProfileAuthority:
    """Authenticate and project execution facts from any frozen profile."""

    payload = _authenticated_payload(profile, "publishable_execution_profile_invalid")
    try:
        methodology = payload["methodology"]
        benchmarks = payload["benchmarks"]
        if type(methodology) is not dict or type(benchmarks) is not dict:
            raise TypeError
        if set(benchmarks) != set(_EXPECTED_BENCHMARKS):
            raise ValueError
        return PublishableExecutionProfileAuthority(
            schema_version=payload["schema_version"],
            profile_id=payload["profile_id"],
            commitment_sha256=profile.commitment_sha256,
            implementation_status=payload["implementation_status"],
            execution_enabled=payload["execution_enabled"],
            publishable=payload["publishable"],
            activation_blockers=tuple(payload["activation_blockers"]),
            benchmark_execution_enabled=tuple(
                (benchmark, benchmarks[benchmark]["execution_enabled"])
                for benchmark in _EXPECTED_BENCHMARKS
            ),
            methodology_schema_version=methodology["schema_version"],
            methodology_id=methodology["methodology_id"],
            methodology_commitment_sha256=methodology["commitment_sha256"],
            methodology_observed=methodology["observed"],
            source_payload=profile,
        )
    except PublishableExecutionPolicyError:
        raise
    except Exception:
        _fail("publishable_execution_profile_invalid")


def publishable_execution_methodology_authority(
    methodology: FrozenPublishablePayload,
) -> PublishableExecutionMethodologyAuthority:
    """Authenticate and project required capability facts from a methodology."""

    payload = _authenticated_payload(methodology, "publishable_execution_methodology_invalid")
    try:
        equivalence = payload["required_full_run_extraction_equivalence"]
        if type(equivalence) is not dict:
            raise TypeError
        return PublishableExecutionMethodologyAuthority(
            schema_version=payload["schema_version"],
            methodology_id=payload["methodology_id"],
            commitment_sha256=methodology.commitment_sha256,
            equivalence_activation_policy=equivalence["activation_policy"],
            equivalence_required=equivalence["required"],
            required_capacity=equivalence["required_capacity"],
            current_runtime_capability=equivalence["current_runtime_capability"],
            current_capability_satisfies_requirement=(
                equivalence["current_capability_satisfies_requirement"]
            ),
            source_payload=methodology,
        )
    except PublishableExecutionPolicyError:
        raise
    except Exception:
        _fail("publishable_execution_methodology_invalid")


def active_publishable_execution_authorities() -> tuple[
    PublishableExecutionProfileAuthority,
    PublishableExecutionMethodologyAuthority,
]:
    """Load the exact active frozen v4 candidate and methodology authorities."""

    try:
        profile = publishable_priority_comparison_profile_v4()
        methodology = publishable_priority_methodology_v4()
        public_publishable_comparison_profile(profile)
        public_publishable_methodology(methodology)
        return (
            publishable_execution_profile_authority(profile),
            publishable_execution_methodology_authority(methodology),
        )
    except PublishableExecutionPolicyError:
        raise
    except Exception:
        _fail("publishable_execution_active_authority_invalid")


def reviewed_publishable_execution_binding() -> PublishableExecutionReview:
    """Return the independently pinned review for the active production candidate."""

    return PublishableExecutionReview(
        profile_schema_version=PUBLISHABLE_PRIORITY_PROFILE_V4_SCHEMA_VERSION,
        profile_id=PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
        profile_commitment_sha256=PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
        methodology_schema_version=PUBLISHABLE_PRIORITY_METHODOLOGY_V4_SCHEMA_VERSION,
        methodology_id=PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
        methodology_commitment_sha256=(PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256),
        orchestration_schema_version=PUBLISHABLE_PRODUCTION_ORCHESTRATION_SCHEMA_VERSION,
        orchestration_commitment_sha256=(PUBLISHABLE_REVIEWED_ORCHESTRATION_COMMITMENT_SHA256),
    )


def require_publishable_execution_authority(
    *,
    profile: PublishableExecutionProfileAuthority,
    methodology: PublishableExecutionMethodologyAuthority,
    orchestration: PublishableExecutionOrchestrationAuthority,
    review: PublishableExecutionReview,
) -> PublishableExecutionAuthority:
    """Issue an opaque admission only for one exact reviewed executable binding."""

    _revalidate_inputs(profile, methodology, orchestration, review)
    if (
        profile.schema_version != review.profile_schema_version
        or profile.profile_id != review.profile_id
    ):
        _fail("publishable_execution_profile_stale")
    if (
        profile.commitment_sha256 != review.profile_commitment_sha256
        or methodology.schema_version != review.methodology_schema_version
        or methodology.methodology_id != review.methodology_id
        or methodology.commitment_sha256 != review.methodology_commitment_sha256
        or orchestration.schema_version != review.orchestration_schema_version
        or orchestration.commitment_sha256 != review.orchestration_commitment_sha256
        or profile.methodology_schema_version != methodology.schema_version
        or profile.methodology_id != methodology.methodology_id
        or profile.methodology_commitment_sha256 != methodology.commitment_sha256
        or orchestration.profile_id != profile.profile_id
        or orchestration.profile_commitment_sha256 != profile.commitment_sha256
        or orchestration.methodology_id != methodology.methodology_id
        or orchestration.methodology_commitment_sha256 != methodology.commitment_sha256
    ):
        _fail("publishable_execution_commitment_drift")
    if not _all_readiness_facts_true(profile, methodology, orchestration):
        _fail("publishable_execution_not_ready")
    return PublishableExecutionAuthority(
        material=_authority_material(review=review, orchestration=orchestration),
        _token=_TOKEN,
    )


def require_active_publishable_execution_authority(
    orchestration: PublishableExecutionOrchestrationAuthority,
) -> PublishableExecutionAuthority:
    """Apply the non-injectable active production review."""

    profile, methodology = active_publishable_execution_authorities()
    return require_publishable_execution_authority(
        profile=profile,
        methodology=methodology,
        orchestration=orchestration,
        review=reviewed_publishable_execution_binding(),
    )


def require_publishable_execution_authority_binding(
    authority: PublishableExecutionAuthority,
    *,
    orchestration: PublishableExecutionOrchestrationAuthority,
    review: PublishableExecutionReview,
    suite_methodology_sha256: str,
) -> None:
    """Revalidate an admission against the exact composition and suite."""

    try:
        PublishableExecutionOrchestrationAuthority.__post_init__(orchestration)
        PublishableExecutionReview.__post_init__(review)
        expected = _authority_material(review=review, orchestration=orchestration)
        expected_commitment = canonical_payload_sha256(expected)
        if (
            type(authority) is not PublishableExecutionAuthority
            or authority._PublishableExecutionAuthority__token is not _TOKEN
            or authority._PublishableExecutionAuthority__material != expected
            or not hmac.compare_digest(authority.commitment_sha256, expected_commitment)
            or not _digest(suite_methodology_sha256)
            or not hmac.compare_digest(
                suite_methodology_sha256,
                review.methodology_commitment_sha256,
            )
        ):
            _fail("publishable_execution_authority_binding_invalid")
    except PublishableExecutionPolicyError:
        raise
    except Exception:
        _fail("publishable_execution_authority_binding_invalid")


def _all_readiness_facts_true(
    profile: PublishableExecutionProfileAuthority,
    methodology: PublishableExecutionMethodologyAuthority,
    orchestration: PublishableExecutionOrchestrationAuthority,
) -> bool:
    return bool(
        profile.implementation_status == PUBLISHABLE_EXECUTABLE_IMPLEMENTATION_STATUS
        and profile.execution_enabled is True
        and profile.publishable is False
        and profile.activation_blockers == ()
        and profile.benchmark_execution_enabled == (("locomo", True), ("longmemeval", True))
        and profile.methodology_observed is True
        and methodology.equivalence_activation_policy == "fail_closed"
        and methodology.equivalence_required is True
        and methodology.current_capability_satisfies_requirement is True
        and methodology.current_runtime_capability == methodology.required_capacity
        and orchestration.scheduler_paid_go_ready is True
        and orchestration.runner_paid_go_ready is True
        and orchestration.durable_store_paid_go_ready is True
        and orchestration.production_bridge_adapter_ready is True
        and orchestration.publishable is False
        and orchestration.readiness_blockers == ()
    )


def _revalidate_inputs(
    profile: PublishableExecutionProfileAuthority,
    methodology: PublishableExecutionMethodologyAuthority,
    orchestration: PublishableExecutionOrchestrationAuthority,
    review: PublishableExecutionReview,
) -> None:
    try:
        if (
            type(profile) is not PublishableExecutionProfileAuthority
            or type(methodology) is not PublishableExecutionMethodologyAuthority
            or type(orchestration) is not PublishableExecutionOrchestrationAuthority
            or type(review) is not PublishableExecutionReview
        ):
            raise TypeError
        PublishableExecutionProfileAuthority.__post_init__(profile)
        PublishableExecutionMethodologyAuthority.__post_init__(methodology)
        if (
            publishable_execution_profile_authority(profile.source_payload) != profile
            or publishable_execution_methodology_authority(methodology.source_payload)
            != methodology
        ):
            raise TypeError
        PublishableExecutionOrchestrationAuthority.__post_init__(orchestration)
        PublishableExecutionReview.__post_init__(review)
    except PublishableExecutionPolicyError:
        raise
    except Exception:
        _fail("publishable_execution_authorities_invalid")


def _authority_material(
    *,
    review: PublishableExecutionReview,
    orchestration: PublishableExecutionOrchestrationAuthority,
) -> dict[str, str]:
    return {
        "methodology_commitment_sha256": review.methodology_commitment_sha256,
        "orchestration_commitment_sha256": orchestration.commitment_sha256,
        "policy_schema_version": PUBLISHABLE_EXECUTION_POLICY_SCHEMA_VERSION,
        "profile_commitment_sha256": review.profile_commitment_sha256,
        "review_commitment_sha256": review.commitment_sha256,
    }


def _authenticated_payload(
    value: FrozenPublishablePayload,
    code: str,
) -> dict[str, object]:
    try:
        if type(value) is not FrozenPublishablePayload:
            raise TypeError
        payload = _thaw(value)
        if (
            type(payload) is not dict
            or payload.get("profile_id", payload.get("methodology_id")) != value.profile_id
            or not hmac.compare_digest(
                canonical_payload_sha256(payload),
                value.commitment_sha256,
            )
        ):
            raise ValueError
        return payload
    except Exception:
        _fail(code)


def _thaw(value: object) -> object:
    if type(value) is FrozenPublishablePayload or isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) in {tuple, list}:
        return [_thaw(item) for item in value]
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise TypeError


def _identifier(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and all(31 < ord(character) < 127 for character in value)
    )


def _digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _string_tuple(value: object) -> bool:
    return type(value) is tuple and all(_identifier(item) for item in value)


def _fail(code: str) -> None:
    raise PublishableExecutionPolicyError(code) from None


__all__ = (
    "PUBLISHABLE_EXECUTABLE_IMPLEMENTATION_STATUS",
    "PUBLISHABLE_EXECUTION_POLICY_SCHEMA_VERSION",
    "PUBLISHABLE_EXECUTION_REVIEW_SCHEMA_VERSION",
    "PUBLISHABLE_PRODUCTION_ORCHESTRATION_SCHEMA_VERSION",
    "PUBLISHABLE_REVIEWED_ORCHESTRATION_COMMITMENT_SHA256",
    "PublishableExecutionAuthority",
    "PublishableExecutionMethodologyAuthority",
    "PublishableExecutionOrchestrationAuthority",
    "PublishableExecutionPolicyError",
    "PublishableExecutionProfileAuthority",
    "PublishableExecutionReview",
    "active_publishable_execution_authorities",
    "publishable_execution_methodology_authority",
    "publishable_execution_profile_authority",
    "require_active_publishable_execution_authority",
    "require_publishable_execution_authority",
    "require_publishable_execution_authority_binding",
    "reviewed_publishable_execution_binding",
)
