"""Gold-blind contracts for materializing official retrieval evidence."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field, replace
from typing import Protocol, final

from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.publishable_durable_scheduler.contracts import (
    LOCOMO_PROFILE,
    LONGMEMEVAL_PROFILE,
    SCHEDULER_ORDERED_BACKEND_ROLES,
    SchedulerBenchmark,
    canonical_json,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerCaseAuthority,
    case_manifest_sha256,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SCHEDULER_RETRIEVAL_PAGE_GROUP_LIMIT,
    SchedulerRetrievalRunScope,
    validate_retrieval_run_scopes,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    PUBLISHABLE_SUITE_CASE_COUNT,
    SchedulerRunnerError,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
    SchedulerOfficialCaseKey,
)

SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT = 200
SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT = PUBLISHABLE_SUITE_CASE_COUNT * 2
SCHEDULER_RETRIEVAL_CAPTURE_PAGE_GROUP_LIMIT = SCHEDULER_RETRIEVAL_PAGE_GROUP_LIMIT
SCHEDULER_RETRIEVAL_CAPTURE_BACKENDS = SCHEDULER_ORDERED_BACKEND_ROLES

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_QUERY_BYTES_LIMIT = 256 * 1024
_SCOPE_REF_BYTES_LIMIT = 4 * 1024


class SchedulerRetrievalCaptureError(SchedulerRunnerError):
    """Secret-safe fail-closed retrieval capture error."""


@final
@dataclass(frozen=True, slots=True)
class SchedulerRetrievalCapturePlan:
    """Exact official coverage and ordered identities for one capture authority."""

    run_scopes: tuple[SchedulerRetrievalRunScope, ...]
    ordered_cases: tuple[tuple[SchedulerCaseAuthority, ...], ...]
    case_authority_root_sha256: str
    capture_identity_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            scopes = validate_retrieval_run_scopes(self.run_scopes)
        except Exception:
            _fail("scheduler_retrieval_capture_plan_invalid")
        expected_runs = (
            (SchedulerBenchmark.LOCOMO, LOCOMO_PROFILE.case_count),
            (SchedulerBenchmark.LONGMEMEVAL, LONGMEMEVAL_PROFILE.case_count),
        )
        if (
            len(scopes) != 2
            or type(self.ordered_cases) is not tuple
            or len(self.ordered_cases) != 2
            or not _is_sha256(self.case_authority_root_sha256)
            or tuple((scope.case_scope.benchmark, scope.case_scope.case_count) for scope in scopes)
            != expected_runs
            or sum(scope.case_scope.case_count for scope in scopes) != PUBLISHABLE_SUITE_CASE_COUNT
            or sum(scope.case_scope.case_count * 2 for scope in scopes)
            != SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT
        ):
            _fail("scheduler_retrieval_capture_plan_invalid")
        expected_targets: tuple[tuple[str, str], ...] | None = None
        for scope, identities in zip(scopes, self.ordered_cases, strict=True):
            targets = tuple(
                (backend.backend_role, backend.target_identity_sha256) for backend in scope.backends
            )
            if (
                type(identities) is not tuple
                or len(identities) != scope.case_scope.case_count
                or any(type(item) is not SchedulerCaseAuthority for item in identities)
                or not _case_manifest_matches(identities, scope.case_scope.case_manifest_sha256)
                or tuple(role for role, _target in targets) != SCHEDULER_RETRIEVAL_CAPTURE_BACKENDS
                or scope.cutoff != SCHEDULER_OFFICIAL_ANSWER_CUTOFF
                or expected_targets is not None
                and targets != expected_targets
            ):
                _fail("scheduler_retrieval_capture_plan_invalid")
            expected_targets = targets
        object.__setattr__(
            self,
            "capture_identity_sha256",
            _digest("scheduler-retrieval-capture-plan.v1", self.identity_material()),
        )

    def identity_material(self) -> dict[str, object]:
        """Return the complete non-secret material bound to resume checkpoints."""

        return {
            "case_authority_root_sha256": self.case_authority_root_sha256,
            "ordered_cases": [
                [{"case_alias": item.case_alias, "case_id": item.case_id} for item in identities]
                for identities in self.ordered_cases
            ],
            "run_scopes": [scope.material() for scope in self.run_scopes],
        }

    @property
    def group_count(self) -> int:
        return SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT

    def group_binding(
        self, sequence: int
    ) -> tuple[SchedulerRetrievalRunScope, SchedulerCaseAuthority, int, int]:
        """Resolve one canonical sequence to run, case, and backend."""

        if type(sequence) is not int or not 0 <= sequence < self.group_count:
            _fail("scheduler_retrieval_capture_sequence_invalid")
        start = 0
        for scope, identities in zip(self.run_scopes, self.ordered_cases, strict=True):
            count = scope.case_scope.case_count * 2
            if sequence < start + count:
                relative = sequence - start
                case_index = relative // 2
                return scope, identities[case_index], case_index, relative % 2
            start += count
        _fail("scheduler_retrieval_capture_sequence_invalid")


@final
@dataclass(frozen=True, slots=True, repr=False)
class SchedulerBackendRetrievalRequest:
    """Gold-blind exact request for one backend/case pair."""

    case_key: SchedulerOfficialCaseKey
    case_material_sha256: str
    backend_index: int
    backend_role: str
    target_identity_sha256: str
    question: str = field(repr=False)
    memory_scope_external_ref: str | None = None
    thread_external_ref: str | None = None
    retrieval_limit: int = SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT
    cutoff: int = SCHEDULER_OFFICIAL_ANSWER_CUTOFF
    query_identity_sha256: str = field(init=False)
    request_identity_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.case_key) is not SchedulerOfficialCaseKey
            or not _is_sha256(self.case_material_sha256)
            or type(self.backend_index) is not int
            or self.backend_index not in (0, 1)
            or self.backend_role != SCHEDULER_RETRIEVAL_CAPTURE_BACKENDS[self.backend_index]
            or not _is_sha256(self.target_identity_sha256)
            or not _bounded_text(self.question, _QUERY_BYTES_LIMIT, allow_empty=False)
            or not _optional_bounded_text(self.memory_scope_external_ref, _SCOPE_REF_BYTES_LIMIT)
            or not _optional_bounded_text(self.thread_external_ref, _SCOPE_REF_BYTES_LIMIT)
            or self.retrieval_limit != SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT
            or self.cutoff != SCHEDULER_OFFICIAL_ANSWER_CUTOFF
        ):
            _fail("scheduler_backend_retrieval_request_invalid")
        query_identity = _digest(
            "scheduler-retrieval-query.v1",
            {
                "case": self.case_key.material(),
                "case_material_sha256": self.case_material_sha256,
                "memory_scope_external_ref": self.memory_scope_external_ref,
                "question": self.question,
                "thread_external_ref": self.thread_external_ref,
            },
        )
        object.__setattr__(self, "query_identity_sha256", query_identity)
        object.__setattr__(
            self,
            "request_identity_sha256",
            _digest("scheduler-retrieval-request.v1", self.identity_material()),
        )

    def identity_material(self) -> dict[str, object]:
        return {
            "backend_index": self.backend_index,
            "backend_role": self.backend_role,
            "case": self.case_key.material(),
            "case_material_sha256": self.case_material_sha256,
            "cutoff": self.cutoff,
            "query_identity_sha256": self.query_identity_sha256,
            "retrieval_limit": self.retrieval_limit,
            "target_identity_sha256": self.target_identity_sha256,
        }

    def __repr__(self) -> str:
        return (
            "SchedulerBackendRetrievalRequest("
            f"run_id={self.case_key.run_id!r}, case_index={self.case_key.case_index}, "
            f"backend_role={self.backend_role!r}, question=<private>)"
        )

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("SchedulerBackendRetrievalRequest contains private material")


@final
@dataclass(frozen=True, slots=True, repr=False)
class SchedulerBackendRetrievalResult:
    """Exact identity echo plus deterministic, cutoff-bounded ranked memories."""

    request_identity_sha256: str
    query_identity_sha256: str
    case_material_sha256: str
    run_id: str
    case_id: str
    backend_index: int
    backend_role: str
    target_identity_sha256: str
    memories: tuple[RetrievedMemory, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if (
            any(
                not _is_sha256(value)
                for value in (
                    self.request_identity_sha256,
                    self.query_identity_sha256,
                    self.case_material_sha256,
                    self.target_identity_sha256,
                )
            )
            or not _bounded_text(self.run_id, 200, allow_empty=False)
            or not _bounded_text(self.case_id, 200, allow_empty=False)
            or type(self.backend_index) is not int
            or self.backend_index not in (0, 1)
            or self.backend_role != SCHEDULER_RETRIEVAL_CAPTURE_BACKENDS[self.backend_index]
            or type(self.memories) is not tuple
            or len(self.memories) > SCHEDULER_OFFICIAL_ANSWER_CUTOFF
            or self.memories
            != deterministic_retrieval_memories(
                self.memories, cutoff=SCHEDULER_OFFICIAL_ANSWER_CUTOFF
            )
        ):
            _fail("scheduler_backend_retrieval_result_invalid")

    @classmethod
    def bind(
        cls,
        *,
        request: SchedulerBackendRetrievalRequest,
        memories: tuple[RetrievedMemory, ...],
    ) -> SchedulerBackendRetrievalResult:
        if type(request) is not SchedulerBackendRetrievalRequest:
            _fail("scheduler_backend_retrieval_result_invalid")
        ranked = deterministic_retrieval_memories(memories, cutoff=request.cutoff)
        return cls(
            request_identity_sha256=request.request_identity_sha256,
            query_identity_sha256=request.query_identity_sha256,
            case_material_sha256=request.case_material_sha256,
            run_id=request.case_key.run_id,
            case_id=request.case_key.case_id,
            backend_index=request.backend_index,
            backend_role=request.backend_role,
            target_identity_sha256=request.target_identity_sha256,
            memories=ranked,
        )

    def is_bound_to(self, request: SchedulerBackendRetrievalRequest) -> bool:
        return bool(
            type(request) is SchedulerBackendRetrievalRequest
            and self.request_identity_sha256 == request.request_identity_sha256
            and self.query_identity_sha256 == request.query_identity_sha256
            and self.case_material_sha256 == request.case_material_sha256
            and self.run_id == request.case_key.run_id
            and self.case_id == request.case_key.case_id
            and self.backend_index == request.backend_index
            and self.backend_role == request.backend_role
            and self.target_identity_sha256 == request.target_identity_sha256
        )

    def __repr__(self) -> str:
        return (
            "SchedulerBackendRetrievalResult("
            f"backend_role={self.backend_role!r}, memory_count={len(self.memories)}, "
            "memories=<private>)"
        )

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("SchedulerBackendRetrievalResult contains private material")


class SchedulerRetrievalBackendPort(Protocol):
    """One exact, target-bound, non-fallback backend retrieval call."""

    @property
    def backend_role(self) -> str: ...

    @property
    def target_identity_sha256(self) -> str: ...

    def retrieve_exact(
        self, *, request: SchedulerBackendRetrievalRequest
    ) -> SchedulerBackendRetrievalResult: ...


def deterministic_retrieval_memories(
    memories: tuple[RetrievedMemory, ...], *, cutoff: int
) -> tuple[RetrievedMemory, ...]:
    """Preserve backend rank, apply a stable tie-break, and assign contiguous ranks."""

    if (
        type(memories) is not tuple
        or len(memories) > SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT
        or type(cutoff) is not int
        or cutoff != SCHEDULER_OFFICIAL_ANSWER_CUTOFF
    ):
        _fail("scheduler_backend_retrieval_result_invalid")
    for memory in memories:
        if not _valid_memory(memory):
            _fail("scheduler_backend_retrieval_result_invalid")
        _digest(
            "scheduler-retrieval-memory-validation.v1",
            {
                "created_at": memory.created_at,
                "item_id": memory.item_id,
                "metadata": memory.metadata,
                "rank": memory.rank,
                "score": memory.score,
                "source_refs": list(memory.source_refs),
                "text": memory.text,
            },
        )
    ordered = sorted(memories, key=_memory_order_key)
    return tuple(replace(memory, rank=rank) for rank, memory in enumerate(ordered[:cutoff], 1))


def _memory_order_key(memory: RetrievedMemory) -> tuple[object, ...]:
    return (
        memory.rank,
        -float(memory.score),
        memory.item_id is None,
        memory.item_id or "",
        memory.created_at is None,
        memory.created_at or "",
        memory.text,
        memory.source_refs,
        _digest("scheduler-retrieval-memory-metadata.v1", memory.metadata),
    )


def _valid_memory(value: object) -> bool:
    if type(value) is not RetrievedMemory:
        return False
    memory = value
    return bool(
        type(memory.text) is str
        and type(memory.rank) is int
        and memory.rank > 0
        and type(memory.score) in {int, float}
        and not isinstance(memory.score, bool)
        and math.isfinite(float(memory.score))
        and (memory.item_id is None or type(memory.item_id) is str)
        and (memory.created_at is None or type(memory.created_at) is str)
        and type(memory.source_refs) is tuple
        and all(type(item) is str for item in memory.source_refs)
        and type(memory.metadata) is dict
    )


def _digest(domain: str, material: object) -> str:
    try:
        payload = canonical_json({"domain": domain, "material": material})
    except Exception:
        _fail("scheduler_retrieval_capture_identity_invalid")
    return hashlib.sha256(payload).hexdigest()


def _optional_bounded_text(value: object, limit: int) -> bool:
    return value is None or _bounded_text(value, limit, allow_empty=False)


def _case_manifest_matches(identities: tuple[SchedulerCaseAuthority, ...], expected: str) -> bool:
    try:
        return case_manifest_sha256(identities) == expected
    except Exception:
        return False


def _bounded_text(value: object, limit: int, *, allow_empty: bool) -> bool:
    if type(value) is not str or not allow_empty and not value:
        return False
    try:
        return len(value.encode("utf-8")) <= limit
    except UnicodeEncodeError:
        return False


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _fail(code: str) -> None:
    raise SchedulerRetrievalCaptureError(code)


__all__ = (
    "SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT",
    "SCHEDULER_RETRIEVAL_CAPTURE_BACKENDS",
    "SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT",
    "SCHEDULER_RETRIEVAL_CAPTURE_PAGE_GROUP_LIMIT",
    "SchedulerBackendRetrievalRequest",
    "SchedulerBackendRetrievalResult",
    "SchedulerRetrievalBackendPort",
    "SchedulerRetrievalCaptureError",
    "SchedulerRetrievalCapturePlan",
    "deterministic_retrieval_memories",
)
