"""Typed contracts for the managed benchmark registry HTTP boundary."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, final

import httpx

from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)

REGISTRATION_SCHEMA_VERSION = "memory-comparison-run-registration-response.v2"
FINALIZE_CLEANUP_REQUEST_SCHEMA_VERSION = "memory-comparison-run-cleanup-finalize.v2"
FINALIZE_CLEANUP_RESPONSE_SCHEMA_VERSION = "memory-comparison-run-cleanup-finalize-response.v1"
FINALIZE_ABORT_REQUEST_SCHEMA_VERSION = "memory-comparison-run-abort-finalize.v2"
FINALIZE_ABORT_RESPONSE_SCHEMA_VERSION = "memory-comparison-run-abort-finalize-response.v2"
REGISTRY_RUNS_PATH = "v1/internal/memory-comparison/runs"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SPACE_SLUG = re.compile(r"^memory-comparison-[a-z0-9-]{1,80}$")
_CANONICAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_IDEMPOTENCY_KEY = re.compile(r"^[\x21-\x7e]{8,240}$")
_BEARER_TOKEN = re.compile(r"^[\x21-\x7e]+$")
_IDEMPOTENCY_OPERATIONS = frozenset(
    {"register", "begin-cleanup", "finalize-cleanup", "finalize-abort"}
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ManagedBenchmarkRegistryHttpError(RuntimeError):
    """Stable secret-free adapter failure."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkRegistryHttpConfig:
    """Exact target, credential, and bounded synchronous I/O windows.

    ``benchmark_deadline`` admits initial registration and manifest sealing. Each
    safety-critical cleanup or identical recovery call receives a fresh bounded
    ``cleanup_recovery_timeout_seconds`` window, so a missed window never disables
    later recovery. Deadlines are checked around each synchronous HTTP phase;
    neither timeout claims wall-clock cancellation of an already-blocking call.
    """

    base_url: str
    admin_bearer_token: str = field(repr=False)
    target_identity_sha256: str
    timeout_seconds: float
    benchmark_deadline: datetime
    cleanup_recovery_timeout_seconds: float
    transport: httpx.MockTransport | None = field(default=None, repr=False, compare=False)
    clock: Callable[[], datetime] = field(default=_utc_now, repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            expected_target = managed_backend_target_identity_sha256(
                backend_role="infinity-context",
                base_url=self.base_url,
            )
        except Exception:
            fail("managed_benchmark_registry_config_invalid")
        if (
            type(self.base_url) is not str
            or not self.base_url
            or self.base_url != self.base_url.strip()
            or expected_target != self.target_identity_sha256
            or type(self.admin_bearer_token) is not str
            or not self.admin_bearer_token
            or self.admin_bearer_token != self.admin_bearer_token.strip()
            or _BEARER_TOKEN.fullmatch(self.admin_bearer_token) is None
            or len(self.admin_bearer_token.encode("utf-8")) > 4096
            or type(self.timeout_seconds) not in {int, float}
            or not math.isfinite(float(self.timeout_seconds))
            or float(self.timeout_seconds) <= 0
            or type(self.benchmark_deadline) is not datetime
            or self.benchmark_deadline.tzinfo is None
            or self.benchmark_deadline.utcoffset() is None
            or type(self.cleanup_recovery_timeout_seconds) not in {int, float}
            or not math.isfinite(float(self.cleanup_recovery_timeout_seconds))
            or float(self.cleanup_recovery_timeout_seconds) <= 0
            or (self.transport is not None and type(self.transport) is not httpx.MockTransport)
            or not callable(self.clock)
        ):
            fail("managed_benchmark_registry_config_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedBenchmarkRegistryHttpConfig is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkRunRegistration:
    """Exact canonical registration shared by the adapter and manifest builder."""

    schema_version: str
    authority: str
    run_id_sha256: str
    binding_commitment_sha256: str
    infinity_target_identity_sha256: str
    space_id: str
    space_slug: str
    state: str
    created: bool
    cleanup_plan_sha256: str
    cleanup_plan_state: Literal["sealed"]

    def __post_init__(self) -> None:
        if (
            self.schema_version != REGISTRATION_SCHEMA_VERSION
            or self.authority != "infinity_canonical"
            or self.state
            not in {
                "active",
                "cleanup_pending",
                "cleanup_complete",
                "cleanup_aborted",
            }
            or any(
                type(value) is not str or _SHA256.fullmatch(value) is None
                for value in (
                    self.run_id_sha256,
                    self.binding_commitment_sha256,
                    self.infinity_target_identity_sha256,
                    self.cleanup_plan_sha256,
                )
            )
            or type(self.space_id) is not str
            or _CANONICAL_ID.fullmatch(self.space_id) is None
            or type(self.space_slug) is not str
            or _SPACE_SLUG.fullmatch(self.space_slug) is None
            or type(self.created) is not bool
            or self.cleanup_plan_state != "sealed"
        ):
            fail("managed_benchmark_registry_registration_response_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedBenchmarkRunRegistration is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkRecoveryAuthorityTransfer:
    """Non-secret authority transfer receipt, including transport-close disposition."""

    schema_version: str
    run_id_sha256: str
    binding_commitment_sha256: str
    infinity_target_identity_sha256: str
    space_slug: str
    cleanup_plan_sha256: str
    prior_phase: str
    transport_close_confirmed: bool
    transport_close_warning: str | None

    def __post_init__(self) -> None:
        if (
            self.schema_version != "memory-comparison-benchmark-recovery-authority-transfer.v2"
            or any(
                type(value) is not str or _SHA256.fullmatch(value) is None
                for value in (
                    self.run_id_sha256,
                    self.binding_commitment_sha256,
                    self.infinity_target_identity_sha256,
                    self.cleanup_plan_sha256,
                )
            )
            or type(self.space_slug) is not str
            or _SPACE_SLUG.fullmatch(self.space_slug) is None
            or self.prior_phase
            not in {
                "registered",
                "registration_outcome_unknown",
                "sealed",
                "seal_outcome_unknown",
                "cleanup_outcome_unknown",
                "pending",
                "finalize_outcome_unknown",
                "recovery_required",
                "recovery_outcome_unknown",
            }
            or type(self.transport_close_confirmed) is not bool
            or (
                self.transport_close_warning
                not in {None, "managed_benchmark_registry_transport_close_unconfirmed"}
            )
            or (self.transport_close_confirmed != (self.transport_close_warning is None))
        ):
            fail("managed_benchmark_registry_recovery_transfer_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkProjectionSeal:
    run_id_sha256: str
    binding_commitment_sha256: str
    infinity_target_identity_sha256: str
    projection_manifest_sha256: str
    replayed: bool

    def __post_init__(self) -> None:
        digests = (
            self.run_id_sha256,
            self.binding_commitment_sha256,
            self.infinity_target_identity_sha256,
            self.projection_manifest_sha256,
        )
        if (
            any(type(value) is not str or _SHA256.fullmatch(value) is None for value in digests)
            or type(self.replayed) is not bool
        ):
            fail("managed_benchmark_registry_manifest_response_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkCleanupCounts:
    facts: int
    documents: int
    chunks: int
    episodes: int
    threads: int
    memory_scopes: int
    obsolete_upsert_jobs: int
    vector_delete_jobs: int
    graph_delete_jobs: int
    cognee_delete_jobs: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (
                self.facts,
                self.documents,
                self.chunks,
                self.episodes,
                self.threads,
                self.memory_scopes,
                self.obsolete_upsert_jobs,
                self.vector_delete_jobs,
                self.graph_delete_jobs,
                self.cognee_delete_jobs,
            )
        ):
            fail("managed_benchmark_registry_cleanup_response_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkCleanupReceipt:
    run_id_sha256: str
    space_id: str
    space_slug: str
    projection_cleanup: Literal["pending", "blocked"]
    counts: ManagedBenchmarkCleanupCounts
    vector_delete_outbox_ids: tuple[int, ...]
    graph_delete_outbox_ids: tuple[int, ...]
    cognee_delete_outbox_ids: tuple[int, ...]
    receipt_sha256: str
    replayed: bool

    def __post_init__(self) -> None:
        lanes = (
            self.vector_delete_outbox_ids,
            self.graph_delete_outbox_ids,
            self.cognee_delete_outbox_ids,
        )
        flattened = tuple(item for lane in lanes for item in lane)
        if (
            type(self.run_id_sha256) is not str
            or _SHA256.fullmatch(self.run_id_sha256) is None
            or type(self.space_id) is not str
            or _CANONICAL_ID.fullmatch(self.space_id) is None
            or type(self.space_slug) is not str
            or _SPACE_SLUG.fullmatch(self.space_slug) is None
            or self.projection_cleanup not in {"pending", "blocked"}
            or type(self.counts) is not ManagedBenchmarkCleanupCounts
            or any(
                type(lane) is not tuple or any(type(item) is not int or item <= 0 for item in lane)
                for lane in lanes
            )
            or len(flattened) != len(set(flattened))
            or self.counts.vector_delete_jobs != len(lanes[0])
            or self.counts.graph_delete_jobs != len(lanes[1])
            or self.counts.cognee_delete_jobs != len(lanes[2])
            or type(self.receipt_sha256) is not str
            or _SHA256.fullmatch(self.receipt_sha256) is None
            or type(self.replayed) is not bool
        ):
            fail("managed_benchmark_registry_cleanup_response_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkCleanupCompletionReceipt:
    """Canonical proof that every registered projection is absent."""

    schema_version: str
    authority: str
    run_id_sha256: str
    space_id: str
    space_slug: str
    state: Literal["cleanup_complete"]
    disposition: Literal["cleanup_complete"]
    projection_cleanup: Literal["complete"]
    projection_manifest_sha256: str
    cleanup_initiation_receipt_sha256: str
    projection_absence_proof_sha256: str
    completed_at: str
    receipt_sha256: str
    replayed: bool

    def __post_init__(self) -> None:
        if (
            self.schema_version != FINALIZE_CLEANUP_RESPONSE_SCHEMA_VERSION
            or self.authority != "infinity_canonical"
            or type(self.run_id_sha256) is not str
            or _SHA256.fullmatch(self.run_id_sha256) is None
            or type(self.space_id) is not str
            or _CANONICAL_ID.fullmatch(self.space_id) is None
            or type(self.space_slug) is not str
            or _SPACE_SLUG.fullmatch(self.space_slug) is None
            or self.state != "cleanup_complete"
            or self.disposition != "cleanup_complete"
            or self.projection_cleanup != "complete"
            or any(
                type(value) is not str or _SHA256.fullmatch(value) is None
                for value in (
                    self.projection_manifest_sha256,
                    self.cleanup_initiation_receipt_sha256,
                    self.projection_absence_proof_sha256,
                    self.receipt_sha256,
                )
            )
            or utc_timestamp(
                self.completed_at,
                "managed_benchmark_registry_finalize_response_invalid",
            )
            != self.completed_at
            or type(self.replayed) is not bool
        ):
            fail("managed_benchmark_registry_finalize_response_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedBenchmarkCleanupCompletionReceipt is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkAbortCompletionReceipt:
    schema_version: str
    authority: str
    run_id_sha256: str
    binding_commitment_sha256: str
    infinity_target_identity_sha256: str
    space_id: str
    space_slug: str
    state: Literal["cleanup_aborted"]
    disposition: Literal["abort_complete"]
    projection_cleanup: Literal["unsealed_abort_complete"]
    cleanup_initiation_receipt_sha256: str
    cleanup_plan_sha256: str
    projection_absence_proof_sha256: str
    completed_at: str
    receipt_sha256: str
    replayed: bool

    def __post_init__(self) -> None:
        if (
            self.schema_version != FINALIZE_ABORT_RESPONSE_SCHEMA_VERSION
            or self.authority != "infinity_canonical"
            or self.state != "cleanup_aborted"
            or self.disposition != "abort_complete"
            or self.projection_cleanup != "unsealed_abort_complete"
            or any(
                type(value) is not str or _SHA256.fullmatch(value) is None
                for value in (
                    self.run_id_sha256,
                    self.binding_commitment_sha256,
                    self.infinity_target_identity_sha256,
                    self.cleanup_initiation_receipt_sha256,
                    self.cleanup_plan_sha256,
                    self.projection_absence_proof_sha256,
                    self.receipt_sha256,
                )
            )
            or type(self.space_id) is not str
            or _CANONICAL_ID.fullmatch(self.space_id) is None
            or type(self.space_slug) is not str
            or _SPACE_SLUG.fullmatch(self.space_slug) is None
            or utc_timestamp(
                self.completed_at,
                "managed_benchmark_registry_abort_response_invalid",
            )
            != self.completed_at
            or type(self.replayed) is not bool
        ):
            fail("managed_benchmark_registry_abort_response_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkPersistedCleanupReceipt:
    """Canonical cleanup-initiation receipt persisted by server authority."""

    run_id_sha256: str
    space_id: str
    space_slug: str
    disposition: Literal["cleanup_pending"]
    projection_cleanup: Literal["pending", "blocked"]
    counts: ManagedBenchmarkCleanupCounts
    vector_delete_outbox_ids: tuple[int, ...]
    graph_delete_outbox_ids: tuple[int, ...]
    cognee_delete_outbox_ids: tuple[int, ...]
    receipt_sha256: str

    def __post_init__(self) -> None:
        lanes = (
            self.vector_delete_outbox_ids,
            self.graph_delete_outbox_ids,
            self.cognee_delete_outbox_ids,
        )
        flattened = tuple(item for lane in lanes for item in lane)
        if (
            type(self.run_id_sha256) is not str
            or _SHA256.fullmatch(self.run_id_sha256) is None
            or type(self.space_id) is not str
            or _CANONICAL_ID.fullmatch(self.space_id) is None
            or type(self.space_slug) is not str
            or _SPACE_SLUG.fullmatch(self.space_slug) is None
            or self.disposition != "cleanup_pending"
            or self.projection_cleanup not in {"pending", "blocked"}
            or type(self.counts) is not ManagedBenchmarkCleanupCounts
            or any(
                type(lane) is not tuple or any(type(item) is not int or item <= 0 for item in lane)
                for lane in lanes
            )
            or len(flattened) != len(set(flattened))
            or self.counts.vector_delete_jobs != len(lanes[0])
            or self.counts.graph_delete_jobs != len(lanes[1])
            or self.counts.cognee_delete_jobs != len(lanes[2])
            or type(self.receipt_sha256) is not str
            or _SHA256.fullmatch(self.receipt_sha256) is None
        ):
            fail("managed_benchmark_registry_lifecycle_response_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkPersistedCompletionReceipt:
    """Canonical terminal cleanup receipt persisted by server authority."""

    run_id_sha256: str
    space_id: str
    space_slug: str
    disposition: Literal["cleanup_complete"]
    projection_cleanup: Literal["complete"]
    projection_manifest_sha256: str
    cleanup_initiation_receipt_sha256: str
    projection_absence_proof_sha256: str
    completed_at: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.run_id_sha256) is not str
            or _SHA256.fullmatch(self.run_id_sha256) is None
            or type(self.space_id) is not str
            or _CANONICAL_ID.fullmatch(self.space_id) is None
            or type(self.space_slug) is not str
            or _SPACE_SLUG.fullmatch(self.space_slug) is None
            or self.disposition != "cleanup_complete"
            or self.projection_cleanup != "complete"
            or any(
                type(value) is not str or _SHA256.fullmatch(value) is None
                for value in (
                    self.projection_manifest_sha256,
                    self.cleanup_initiation_receipt_sha256,
                    self.projection_absence_proof_sha256,
                    self.receipt_sha256,
                )
            )
            or utc_timestamp(
                self.completed_at,
                "managed_benchmark_registry_lifecycle_response_invalid",
            )
            != self.completed_at
        ):
            fail("managed_benchmark_registry_lifecycle_response_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkPersistedAbortReceipt:
    run_id_sha256: str
    binding_commitment_sha256: str
    infinity_target_identity_sha256: str
    space_id: str
    space_slug: str
    disposition: Literal["abort_complete"]
    projection_cleanup: Literal["unsealed_abort_complete"]
    cleanup_initiation_receipt_sha256: str
    cleanup_plan_sha256: str
    projection_absence_proof_sha256: str
    completed_at: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        if (
            self.disposition != "abort_complete"
            or self.projection_cleanup != "unsealed_abort_complete"
            or any(
                type(value) is not str or _SHA256.fullmatch(value) is None
                for value in (
                    self.run_id_sha256,
                    self.binding_commitment_sha256,
                    self.infinity_target_identity_sha256,
                    self.cleanup_initiation_receipt_sha256,
                    self.cleanup_plan_sha256,
                    self.projection_absence_proof_sha256,
                    self.receipt_sha256,
                )
            )
            or type(self.space_id) is not str
            or _CANONICAL_ID.fullmatch(self.space_id) is None
            or type(self.space_slug) is not str
            or _SPACE_SLUG.fullmatch(self.space_slug) is None
            or utc_timestamp(
                self.completed_at,
                "managed_benchmark_registry_lifecycle_response_invalid",
            )
            != self.completed_at
        ):
            fail("managed_benchmark_registry_lifecycle_response_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkRunLifecycleSnapshot:
    """Strict canonical lifecycle used to recover a fresh process."""

    schema_version: str
    authority: str
    run_id_sha256: str
    binding_commitment_sha256: str
    infinity_target_identity_sha256: str
    space_id: str
    space_slug: str
    state: Literal["active", "cleanup_pending", "cleanup_complete", "cleanup_aborted"]
    projection_cleanup_state: Literal[
        "unsealed",
        "sealed",
        "blocked",
        "pending",
        "complete",
        "unsealed_abort_complete",
    ]
    projection_manifest_sha256: str | None
    cleanup_plan_sha256: str
    cleanup_plan_state: Literal["sealed"]
    cleanup_receipt: ManagedBenchmarkPersistedCleanupReceipt | None
    completion_receipt: (
        ManagedBenchmarkPersistedCompletionReceipt | ManagedBenchmarkPersistedAbortReceipt | None
    )

    def __post_init__(self) -> None:
        if (
            self.schema_version != "memory-comparison-run-lifecycle-response.v2"
            or self.authority != "infinity_canonical"
            or any(
                type(value) is not str or _SHA256.fullmatch(value) is None
                for value in (
                    self.run_id_sha256,
                    self.binding_commitment_sha256,
                    self.infinity_target_identity_sha256,
                    self.cleanup_plan_sha256,
                )
            )
            or type(self.space_id) is not str
            or _CANONICAL_ID.fullmatch(self.space_id) is None
            or type(self.space_slug) is not str
            or _SPACE_SLUG.fullmatch(self.space_slug) is None
            or self.cleanup_plan_state != "sealed"
            or not self._valid_combination()
        ):
            fail("managed_benchmark_registry_lifecycle_response_invalid")

    def _valid_combination(self) -> bool:
        cleanup = self.cleanup_receipt
        completion = self.completion_receipt
        manifest = self.projection_manifest_sha256
        if manifest is not None and (
            type(manifest) is not str or _SHA256.fullmatch(manifest) is None
        ):
            return False
        if self.state == "active":
            return (
                self.projection_cleanup_state in {"unsealed", "sealed"}
                and (manifest is not None) == (self.projection_cleanup_state == "sealed")
                and cleanup is None
                and completion is None
            )
        if type(cleanup) is not ManagedBenchmarkPersistedCleanupReceipt:
            return False
        if (
            cleanup.run_id_sha256 != self.run_id_sha256
            or cleanup.space_id != self.space_id
            or cleanup.space_slug != self.space_slug
        ):
            return False
        if self.state == "cleanup_pending":
            legacy_blocked_pending_receipt = (
                self.projection_cleanup_state == "blocked"
                and cleanup.projection_cleanup == "pending"
            )
            return (
                self.projection_cleanup_state in {"pending", "blocked"}
                and (
                    cleanup.projection_cleanup == self.projection_cleanup_state
                    or legacy_blocked_pending_receipt
                )
                and (manifest is not None) == (self.projection_cleanup_state == "pending")
                and completion is None
            )
        if self.state == "cleanup_complete":
            return (
                self.projection_cleanup_state == "complete"
                and manifest is not None
                and cleanup.projection_cleanup == "pending"
                and type(completion) is ManagedBenchmarkPersistedCompletionReceipt
                and completion.run_id_sha256 == self.run_id_sha256
                and completion.space_id == self.space_id
                and completion.space_slug == self.space_slug
                and completion.projection_manifest_sha256 == manifest
                and completion.cleanup_initiation_receipt_sha256 == cleanup.receipt_sha256
            )
        return (
            self.state == "cleanup_aborted"
            and self.projection_cleanup_state == "unsealed_abort_complete"
            and manifest is None
            and cleanup.projection_cleanup == "blocked"
            and type(completion) is ManagedBenchmarkPersistedAbortReceipt
            and completion.run_id_sha256 == self.run_id_sha256
            and completion.binding_commitment_sha256 == self.binding_commitment_sha256
            and completion.infinity_target_identity_sha256 == self.infinity_target_identity_sha256
            and completion.space_id == self.space_id
            and completion.space_slug == self.space_slug
            and completion.cleanup_initiation_receipt_sha256 == cleanup.receipt_sha256
        )


def managed_benchmark_registry_idempotency_key(
    operation: str,
    *,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    target_identity_sha256: str,
) -> str:
    """Build one deterministic header value without exposing raw run identity."""

    if type(operation) is not str or operation not in _IDEMPOTENCY_OPERATIONS:
        fail("managed_benchmark_registry_idempotency_invalid")
    material = "\n".join(
        (
            "managed-benchmark-registry-idempotency.v1",
            operation,
            digest(run_id_sha256, "managed_benchmark_registry_idempotency_invalid"),
            digest(
                binding_commitment_sha256,
                "managed_benchmark_registry_idempotency_invalid",
            ),
            digest(target_identity_sha256, "managed_benchmark_registry_idempotency_invalid"),
        )
    ).encode()
    return f"managed-benchmark-{operation}-v1-{hashlib.sha256(material).hexdigest()}"


def idempotency_key(
    value: str | None,
    *,
    operation: str,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    target_identity_sha256: str,
) -> str:
    key = (
        managed_benchmark_registry_idempotency_key(
            operation,
            run_id_sha256=run_id_sha256,
            binding_commitment_sha256=binding_commitment_sha256,
            target_identity_sha256=target_identity_sha256,
        )
        if value is None
        else value
    )
    if type(key) is not str or key != key.strip() or _IDEMPOTENCY_KEY.fullmatch(key) is None:
        fail("managed_benchmark_registry_idempotency_invalid")
    return key


def digest(value: object, code: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        fail(code)
    return value


def space_slug(value: object, code: str) -> str:
    if type(value) is not str or _SPACE_SLUG.fullmatch(value) is None:
        fail(code)
    return value


def canonical_id(value: object, code: str) -> str:
    if type(value) is not str or _CANONICAL_ID.fullmatch(value) is None:
        fail(code)
    return value


def utc_timestamp(value: object, code: str) -> str:
    if type(value) is not str or not value.endswith("Z"):
        fail(code)
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError:
        fail(code)
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset() != UTC.utcoffset(parsed)
        or parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z") != value
    ):
        fail(code)
    return value


def fail(code: str) -> None:
    raise ManagedBenchmarkRegistryHttpError(code) from None


__all__ = (
    "FINALIZE_ABORT_REQUEST_SCHEMA_VERSION",
    "FINALIZE_ABORT_RESPONSE_SCHEMA_VERSION",
    "FINALIZE_CLEANUP_REQUEST_SCHEMA_VERSION",
    "FINALIZE_CLEANUP_RESPONSE_SCHEMA_VERSION",
    "ManagedBenchmarkCleanupCompletionReceipt",
    "ManagedBenchmarkAbortCompletionReceipt",
    "ManagedBenchmarkCleanupCounts",
    "ManagedBenchmarkCleanupReceipt",
    "ManagedBenchmarkPersistedCleanupReceipt",
    "ManagedBenchmarkPersistedCompletionReceipt",
    "ManagedBenchmarkPersistedAbortReceipt",
    "ManagedBenchmarkProjectionSeal",
    "ManagedBenchmarkRecoveryAuthorityTransfer",
    "ManagedBenchmarkRunLifecycleSnapshot",
    "ManagedBenchmarkRegistryHttpConfig",
    "ManagedBenchmarkRegistryHttpError",
    "ManagedBenchmarkRunRegistration",
    "REGISTRY_RUNS_PATH",
    "managed_benchmark_registry_idempotency_key",
)
