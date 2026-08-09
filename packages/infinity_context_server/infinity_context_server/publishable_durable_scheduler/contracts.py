"""Immutable authorities for the provider-free publishable scheduler v4.

This is a standalone design boundary.  It is not paid-run capable until durable
store and provider-attempt bridge adapters implement the declared semantics.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import final

SCHEDULER_SCHEMA_VERSION = "memory-comparison-publishable-scheduler.v4"
SCHEDULER_CALLS_PER_CASE = 4
SCHEDULER_SHARD_CALL_LIMIT = 256
SCHEDULER_QUERY_LIMIT = 256
SCHEDULER_PAID_GO_READY = False

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


class SchedulerContractError(RuntimeError):
    """Raised when a scheduler authority cannot be proven exactly."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SchedulerBenchmark(StrEnum):
    LOCOMO = "locomo"
    LONGMEMEVAL = "longmemeval"


class SchedulerCallStage(StrEnum):
    ANSWER = "answer"
    JUDGE = "judge"


@final
@dataclass(frozen=True, slots=True)
class SchedulerProfile:
    benchmark: SchedulerBenchmark
    profile_id: str
    case_count: int
    call_count: int
    shard_count: int

    def __post_init__(self) -> None:
        if type(self.benchmark) is not SchedulerBenchmark:
            _fail("scheduler_benchmark_invalid")
        expected = (
            (1540, 6160, 25) if self.benchmark is SchedulerBenchmark.LOCOMO else (500, 2000, 8)
        )
        if (
            type(self.profile_id) is not str
            or not self.profile_id
            or (self.case_count, self.call_count, self.shard_count) != expected
        ):
            _fail("scheduler_profile_invalid")
        _identifier(self.profile_id, "profile_id")


@final
@dataclass(frozen=True, slots=True)
class SchedulerBridgeBootAuthority:
    """One reviewed bridge process boot, before any provider attempt exists."""

    bridge_id: str
    implementation_sha256: str
    runtime_authority_sha256: str
    boot_nonce_sha256: str
    receipt_verifier_policy_sha256: str
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _identifier(self.bridge_id, "bridge_id")
        for value, name in (
            (self.implementation_sha256, "implementation_sha256"),
            (self.runtime_authority_sha256, "runtime_authority_sha256"),
            (self.boot_nonce_sha256, "boot_nonce_sha256"),
            (self.receipt_verifier_policy_sha256, "receipt_verifier_policy_sha256"),
        ):
            _digest(value, name)
        object.__setattr__(
            self,
            "commitment_sha256",
            _commit("bridge-boot", self.material()),
        )

    def material(self) -> dict[str, str]:
        return {
            "boot_nonce_sha256": self.boot_nonce_sha256,
            "bridge_id": self.bridge_id,
            "implementation_sha256": self.implementation_sha256,
            "receipt_verifier_policy_sha256": self.receipt_verifier_policy_sha256,
            "runtime_authority_sha256": self.runtime_authority_sha256,
            "schema_version": SCHEDULER_SCHEMA_VERSION,
        }


@final
@dataclass(frozen=True, slots=True)
class SchedulerBackendAuthority:
    backend_role: str
    target_identity_sha256: str

    def __post_init__(self) -> None:
        _identifier(self.backend_role, "backend_role")
        _digest(self.target_identity_sha256, "target_identity_sha256")

    def material(self) -> dict[str, str]:
        return {
            "backend_role": self.backend_role,
            "target_identity_sha256": self.target_identity_sha256,
        }


@final
@dataclass(frozen=True, slots=True)
class SchedulerDeadlineTokenAuthority:
    """Immutable wall-clock stop and worst-case output-token ceilings."""

    dispatch_not_before_unix_ms: int
    dispatch_deadline_unix_ms: int
    answer_max_output_tokens: int
    judge_max_output_tokens: int
    run_token_ceiling: int
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        integers = (
            self.dispatch_not_before_unix_ms,
            self.dispatch_deadline_unix_ms,
            self.answer_max_output_tokens,
            self.judge_max_output_tokens,
            self.run_token_ceiling,
        )
        if any(type(item) is not int for item in integers):
            _fail("scheduler_deadline_token_authority_invalid")
        if (
            self.dispatch_not_before_unix_ms < 0
            or self.dispatch_deadline_unix_ms <= self.dispatch_not_before_unix_ms
            or self.answer_max_output_tokens < 1
            or self.judge_max_output_tokens < 1
            or self.run_token_ceiling < 1
        ):
            _fail("scheduler_deadline_token_authority_invalid")
        object.__setattr__(
            self,
            "commitment_sha256",
            _commit("deadline-token", self.material()),
        )

    def material(self) -> dict[str, int | str]:
        return {
            "answer_max_output_tokens": self.answer_max_output_tokens,
            "dispatch_deadline_unix_ms": self.dispatch_deadline_unix_ms,
            "dispatch_not_before_unix_ms": self.dispatch_not_before_unix_ms,
            "judge_max_output_tokens": self.judge_max_output_tokens,
            "run_token_ceiling": self.run_token_ceiling,
            "schema_version": SCHEDULER_SCHEMA_VERSION,
        }


@final
@dataclass(frozen=True, slots=True)
class SchedulerRunBinding:
    run_id: str
    profile: SchedulerProfile
    binding_commitment_sha256: str
    dataset_sha256: str
    case_manifest_sha256: str
    backends: tuple[SchedulerBackendAuthority, SchedulerBackendAuthority]
    limits: SchedulerDeadlineTokenAuthority

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        if type(self.profile) is not SchedulerProfile:
            _fail("scheduler_run_profile_invalid")
        for value, name in (
            (self.binding_commitment_sha256, "binding_commitment_sha256"),
            (self.dataset_sha256, "dataset_sha256"),
            (self.case_manifest_sha256, "case_manifest_sha256"),
        ):
            _digest(value, name)
        if (
            type(self.backends) is not tuple
            or len(self.backends) != 2
            or any(type(item) is not SchedulerBackendAuthority for item in self.backends)
            or len({item.backend_role for item in self.backends}) != 2
            or len({item.target_identity_sha256 for item in self.backends}) != 2
            or type(self.limits) is not SchedulerDeadlineTokenAuthority
        ):
            _fail("scheduler_run_binding_invalid")
        expected_ceiling = (
            self.profile.case_count
            * 2
            * (self.limits.answer_max_output_tokens + self.limits.judge_max_output_tokens)
        )
        if self.limits.run_token_ceiling != expected_ceiling:
            _fail("scheduler_run_token_ceiling_invalid")

    def material(self) -> dict[str, object]:
        return {
            "backends": [item.material() for item in self.backends],
            "binding_commitment_sha256": self.binding_commitment_sha256,
            "case_manifest_sha256": self.case_manifest_sha256,
            "dataset_sha256": self.dataset_sha256,
            "limits_commitment_sha256": self.limits.commitment_sha256,
            "profile": {
                "benchmark": self.profile.benchmark.value,
                "call_count": self.profile.call_count,
                "case_count": self.profile.case_count,
                "profile_id": self.profile.profile_id,
                "shard_count": self.profile.shard_count,
            },
            "run_id": self.run_id,
        }


@final
@dataclass(frozen=True, slots=True)
class SchedulerSuiteAuthority:
    """The exact ordered LoCoMo and LongMemEval run slots."""

    suite_id: str
    publication_bundle_sha256: str
    methodology_sha256: str
    source_commit_sha256: str
    bridge_boot: SchedulerBridgeBootAuthority
    ordered_runs: tuple[SchedulerRunBinding, SchedulerRunBinding]
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _identifier(self.suite_id, "suite_id")
        for value, name in (
            (self.publication_bundle_sha256, "publication_bundle_sha256"),
            (self.methodology_sha256, "methodology_sha256"),
            (self.source_commit_sha256, "source_commit_sha256"),
        ):
            _digest(value, name)
        if (
            type(self.bridge_boot) is not SchedulerBridgeBootAuthority
            or type(self.ordered_runs) is not tuple
            or len(self.ordered_runs) != 2
            or any(type(item) is not SchedulerRunBinding for item in self.ordered_runs)
            or tuple(item.profile.benchmark for item in self.ordered_runs)
            != (SchedulerBenchmark.LOCOMO, SchedulerBenchmark.LONGMEMEVAL)
            or len({item.run_id for item in self.ordered_runs}) != 2
            or len({item.binding_commitment_sha256 for item in self.ordered_runs}) != 2
        ):
            _fail("scheduler_suite_runs_invalid")
        object.__setattr__(self, "commitment_sha256", _commit("suite", self.material()))

    def material(self) -> dict[str, object]:
        return {
            "bridge_boot_authority_sha256": self.bridge_boot.commitment_sha256,
            "methodology_sha256": self.methodology_sha256,
            "ordered_runs": [item.material() for item in self.ordered_runs],
            "publication_bundle_sha256": self.publication_bundle_sha256,
            "schema_version": SCHEDULER_SCHEMA_VERSION,
            "source_commit_sha256": self.source_commit_sha256,
            "suite_id": self.suite_id,
        }


@final
@dataclass(frozen=True, slots=True)
class SchedulerRunAuthority:
    suite_authority_sha256: str
    suite_id: str
    run_index: int
    binding: SchedulerRunBinding
    bridge_boot_authority_sha256: str
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _digest(self.suite_authority_sha256, "suite_authority_sha256")
        _identifier(self.suite_id, "suite_id")
        _digest(self.bridge_boot_authority_sha256, "bridge_boot_authority_sha256")
        if type(self.run_index) is not int or self.run_index not in (0, 1):
            _fail("scheduler_run_index_invalid")
        if type(self.binding) is not SchedulerRunBinding:
            _fail("scheduler_run_binding_invalid")
        object.__setattr__(self, "commitment_sha256", _commit("run", self.material()))

    def material(self) -> dict[str, object]:
        return {
            "bridge_boot_authority_sha256": self.bridge_boot_authority_sha256,
            "run_binding": self.binding.material(),
            "run_index": self.run_index,
            "schema_version": SCHEDULER_SCHEMA_VERSION,
            "suite_authority_sha256": self.suite_authority_sha256,
            "suite_id": self.suite_id,
        }


def run_authority_from_suite(
    suite: SchedulerSuiteAuthority, *, run_index: int
) -> SchedulerRunAuthority:
    if type(suite) is not SchedulerSuiteAuthority or type(run_index) is not int:
        _fail("scheduler_suite_run_selection_invalid")
    try:
        binding = suite.ordered_runs[run_index]
    except IndexError as error:
        raise SchedulerContractError("scheduler_suite_run_selection_invalid") from error
    return SchedulerRunAuthority(
        suite_authority_sha256=suite.commitment_sha256,
        suite_id=suite.suite_id,
        run_index=run_index,
        binding=binding,
        bridge_boot_authority_sha256=suite.bridge_boot.commitment_sha256,
    )


def require_run_authority(
    suite: SchedulerSuiteAuthority, authority: SchedulerRunAuthority
) -> SchedulerRunAuthority:
    if (
        type(suite) is not SchedulerSuiteAuthority
        or type(authority) is not SchedulerRunAuthority
        or authority != run_authority_from_suite(suite, run_index=authority.run_index)
    ):
        _fail("scheduler_suite_run_authority_binding_invalid")
    return authority


def canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SchedulerContractError("scheduler_material_not_canonical") from error


def commitment(domain: str, value: object) -> str:
    return _commit(domain, value)


def _commit(domain: str, value: object) -> str:
    _identifier(domain, "commitment_domain")
    return hashlib.sha256(
        b"memory-comparison/scheduler/v4/" + domain.encode("ascii") + b"\0" + canonical_json(value)
    ).hexdigest()


def _identifier(value: object, name: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _fail(f"scheduler_{name}_invalid")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(f"scheduler_{name}_invalid")
    return value


def _fail(code: str) -> None:
    raise SchedulerContractError(code)


LOCOMO_PROFILE = SchedulerProfile(SchedulerBenchmark.LOCOMO, "mem0-locomo-top50-v1", 1540, 6160, 25)
LONGMEMEVAL_PROFILE = SchedulerProfile(
    SchedulerBenchmark.LONGMEMEVAL, "mem0-longmemeval-top50-v1", 500, 2000, 8
)


__all__ = (
    "LOCOMO_PROFILE",
    "LONGMEMEVAL_PROFILE",
    "SCHEDULER_CALLS_PER_CASE",
    "SCHEDULER_PAID_GO_READY",
    "SCHEDULER_QUERY_LIMIT",
    "SCHEDULER_SCHEMA_VERSION",
    "SCHEDULER_SHARD_CALL_LIMIT",
    "SchedulerBackendAuthority",
    "SchedulerBenchmark",
    "SchedulerBridgeBootAuthority",
    "SchedulerCallStage",
    "SchedulerContractError",
    "SchedulerDeadlineTokenAuthority",
    "SchedulerProfile",
    "SchedulerRunAuthority",
    "SchedulerRunBinding",
    "SchedulerSuiteAuthority",
    "canonical_json",
    "commitment",
    "require_run_authority",
    "run_authority_from_suite",
)
