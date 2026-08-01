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

REGISTRATION_SCHEMA_VERSION = "memory-comparison-run-registration-response.v1"
REGISTRY_RUNS_PATH = "v1/internal/memory-comparison/runs"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SPACE_SLUG = re.compile(r"^memory-comparison-[a-z0-9-]{1,80}$")
_CANONICAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_IDEMPOTENCY_KEY = re.compile(r"^[\x21-\x7e]{8,240}$")
_BEARER_TOKEN = re.compile(r"^[\x21-\x7e]+$")
_IDEMPOTENCY_OPERATIONS = frozenset({"register", "begin-cleanup"})


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

    def __post_init__(self) -> None:
        if (
            self.schema_version != REGISTRATION_SCHEMA_VERSION
            or self.authority != "infinity_canonical"
            or self.state != "active"
            or any(
                type(value) is not str or _SHA256.fullmatch(value) is None
                for value in (
                    self.run_id_sha256,
                    self.binding_commitment_sha256,
                    self.infinity_target_identity_sha256,
                )
            )
            or type(self.space_id) is not str
            or _CANONICAL_ID.fullmatch(self.space_id) is None
            or type(self.space_slug) is not str
            or _SPACE_SLUG.fullmatch(self.space_slug) is None
            or type(self.created) is not bool
        ):
            fail("managed_benchmark_registry_registration_response_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedBenchmarkRunRegistration is final")


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


def fail(code: str) -> None:
    raise ManagedBenchmarkRegistryHttpError(code) from None


__all__ = (
    "ManagedBenchmarkCleanupCounts",
    "ManagedBenchmarkCleanupReceipt",
    "ManagedBenchmarkProjectionSeal",
    "ManagedBenchmarkRegistryHttpConfig",
    "ManagedBenchmarkRegistryHttpError",
    "ManagedBenchmarkRunRegistration",
    "REGISTRY_RUNS_PATH",
    "managed_benchmark_registry_idempotency_key",
)
