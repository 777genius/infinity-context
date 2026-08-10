"""Public contracts for provider-free scheduler case and retrieval authorities."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import final

from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from infinity_context_server.publishable_durable_scheduler.contracts import SchedulerBenchmark
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    SchedulerRunnerError,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
    SchedulerOfficialCaseKey,
)

SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION = (
    "memory-comparison-publishable-official-sqlite-authority.v1"
)
SCHEDULER_OFFICIAL_CASE_PAGE_ROW_LIMIT = 256
SCHEDULER_RETRIEVAL_PAGE_GROUP_LIMIT = 64
SCHEDULER_OFFICIAL_AUTHORITY_PAGE_BYTES_LIMIT = 8 * 1024 * 1024
SCHEDULER_OFFICIAL_AUTHORITY_CASE_LIMIT = 2_040
SCHEDULER_OFFICIAL_AUTHORITY_RETRIEVAL_GROUP_LIMIT = 4_080

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")


class SchedulerOfficialAuthorityError(SchedulerRunnerError):
    """Stable fail-closed error without private authority material."""


@final
@dataclass(frozen=True, slots=True)
class SchedulerOfficialCaseRunScope:
    """All non-case fields required to bind one run's official case rows."""

    suite_authority_sha256: str
    run_authority_sha256: str
    run_binding_commitment_sha256: str
    run_id: str
    benchmark: SchedulerBenchmark
    scheduler_profile_id: str
    publishable_profile_id: str
    publishable_profile_sha256: str
    methodology_sha256: str
    dataset_sha256: str
    case_manifest_sha256: str
    case_count: int

    def __post_init__(self) -> None:
        if (
            any(
                not _is_sha256(value)
                for value in (
                    self.suite_authority_sha256,
                    self.run_authority_sha256,
                    self.run_binding_commitment_sha256,
                    self.publishable_profile_sha256,
                    self.methodology_sha256,
                    self.dataset_sha256,
                    self.case_manifest_sha256,
                )
            )
            or type(self.benchmark) is not SchedulerBenchmark
            or any(
                not _is_identifier(value)
                for value in (
                    self.run_id,
                    self.scheduler_profile_id,
                    self.publishable_profile_id,
                )
            )
            or type(self.case_count) is not int
            or not 1 <= self.case_count <= SCHEDULER_OFFICIAL_AUTHORITY_CASE_LIMIT
        ):
            _fail("scheduler_official_case_authority_run_scope_invalid")

    def material(self) -> dict[str, object]:
        return {
            "benchmark": self.benchmark.value,
            "case_count": self.case_count,
            "case_manifest_sha256": self.case_manifest_sha256,
            "dataset_sha256": self.dataset_sha256,
            "methodology_sha256": self.methodology_sha256,
            "publishable_profile_id": self.publishable_profile_id,
            "publishable_profile_sha256": self.publishable_profile_sha256,
            "run_authority_sha256": self.run_authority_sha256,
            "run_binding_commitment_sha256": self.run_binding_commitment_sha256,
            "run_id": self.run_id,
            "scheduler_profile_id": self.scheduler_profile_id,
            "suite_authority_sha256": self.suite_authority_sha256,
        }

    def case_key(
        self,
        *,
        case_index: int,
        case_id: str,
        case_alias: str,
        authority_root_sha256: str,
    ) -> SchedulerOfficialCaseKey:
        return SchedulerOfficialCaseKey(
            suite_authority_sha256=self.suite_authority_sha256,
            run_authority_sha256=self.run_authority_sha256,
            run_binding_commitment_sha256=self.run_binding_commitment_sha256,
            run_id=self.run_id,
            benchmark=self.benchmark,
            scheduler_profile_id=self.scheduler_profile_id,
            publishable_profile_id=self.publishable_profile_id,
            publishable_profile_sha256=self.publishable_profile_sha256,
            methodology_sha256=self.methodology_sha256,
            dataset_sha256=self.dataset_sha256,
            case_manifest_sha256=self.case_manifest_sha256,
            case_index=case_index,
            case_id=case_id,
            case_alias=case_alias,
            authority_root_sha256=authority_root_sha256,
        )


@final
@dataclass(frozen=True, slots=True)
class SchedulerRetrievalBackendScope:
    """One exact ordered backend target used by a retrieval authority."""

    backend_index: int
    backend_role: str
    target_identity_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.backend_index) is not int
            or self.backend_index not in (0, 1)
            or not _is_identifier(self.backend_role)
            or not _is_sha256(self.target_identity_sha256)
        ):
            _fail("scheduler_retrieval_evidence_authority_backend_scope_invalid")

    def material(self) -> dict[str, object]:
        return {
            "backend_index": self.backend_index,
            "backend_role": self.backend_role,
            "target_identity_sha256": self.target_identity_sha256,
        }


@final
@dataclass(frozen=True, slots=True)
class SchedulerRetrievalRunScope:
    """Expected case coverage and both backend targets for one run."""

    case_scope: SchedulerOfficialCaseRunScope
    backends: tuple[SchedulerRetrievalBackendScope, SchedulerRetrievalBackendScope]
    cutoff: int = SCHEDULER_OFFICIAL_ANSWER_CUTOFF

    def __post_init__(self) -> None:
        if (
            type(self.case_scope) is not SchedulerOfficialCaseRunScope
            or type(self.backends) is not tuple
            or len(self.backends) != 2
            or any(type(item) is not SchedulerRetrievalBackendScope for item in self.backends)
            or tuple(item.backend_index for item in self.backends) != (0, 1)
            or len({item.backend_role for item in self.backends}) != 2
            or len({item.target_identity_sha256 for item in self.backends}) != 2
            or type(self.cutoff) is not int
            or self.cutoff != SCHEDULER_OFFICIAL_ANSWER_CUTOFF
        ):
            _fail("scheduler_retrieval_evidence_authority_run_scope_invalid")

    def material(self) -> dict[str, object]:
        return {
            "backends": [item.material() for item in self.backends],
            "case_scope": self.case_scope.material(),
            "cutoff": self.cutoff,
        }


@final
@dataclass(frozen=True, slots=True, repr=False)
class SchedulerOfficialCaseAuthorityRow:
    """One private case supplied incrementally to a case authority builder."""

    run_id: str
    case_index: int
    case_id: str
    case_alias: str
    case: PublicBenchmarkCase = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not _is_identifier(self.run_id)
            or type(self.case_index) is not int
            or self.case_index < 0
            or not _bounded_identity(self.case_id)
            or not _bounded_identity(self.case_alias)
            or type(self.case) is not PublicBenchmarkCase
        ):
            _fail("scheduler_official_case_authority_row_invalid")

    def __repr__(self) -> str:
        return (
            "SchedulerOfficialCaseAuthorityRow("
            f"run_id={self.run_id!r}, case_index={self.case_index}, case=<private>)"
        )

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("SchedulerOfficialCaseAuthorityRow contains private material")


@final
@dataclass(frozen=True, slots=True, repr=False)
class SchedulerOfficialCaseAuthorityPage:
    """A bounded, replay-addressable page of ordered official cases."""

    page_index: int
    rows: tuple[SchedulerOfficialCaseAuthorityRow, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.page_index) is not int
            or self.page_index < 0
            or type(self.rows) is not tuple
            or not 1 <= len(self.rows) <= SCHEDULER_OFFICIAL_CASE_PAGE_ROW_LIMIT
            or any(type(row) is not SchedulerOfficialCaseAuthorityRow for row in self.rows)
        ):
            _fail("scheduler_official_case_authority_page_invalid")

    def __repr__(self) -> str:
        return (
            "SchedulerOfficialCaseAuthorityPage("
            f"page_index={self.page_index}, row_count={len(self.rows)})"
        )

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("SchedulerOfficialCaseAuthorityPage contains private material")


@final
@dataclass(frozen=True, slots=True, repr=False)
class SchedulerRetrievalEvidenceAuthorityRow:
    """One backend/case ranked result supplied incrementally to a builder."""

    case_key: SchedulerOfficialCaseKey
    case_material_sha256: str
    backend_index: int
    memories: tuple[RetrievedMemory, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.case_key) is not SchedulerOfficialCaseKey
            or not _is_sha256(self.case_material_sha256)
            or type(self.backend_index) is not int
            or self.backend_index not in (0, 1)
            or type(self.memories) is not tuple
            or len(self.memories) > SCHEDULER_OFFICIAL_ANSWER_CUTOFF
            or any(type(item) is not RetrievedMemory for item in self.memories)
        ):
            _fail("scheduler_retrieval_evidence_authority_row_invalid")

    def __repr__(self) -> str:
        return (
            "SchedulerRetrievalEvidenceAuthorityRow("
            f"case_index={self.case_key.case_index}, backend_index={self.backend_index}, "
            f"memory_count={len(self.memories)})"
        )

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("SchedulerRetrievalEvidenceAuthorityRow contains private material")


@final
@dataclass(frozen=True, slots=True, repr=False)
class SchedulerRetrievalEvidenceAuthorityPage:
    """A bounded, replay-addressable page of backend/case result groups."""

    page_index: int
    rows: tuple[SchedulerRetrievalEvidenceAuthorityRow, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.page_index) is not int
            or self.page_index < 0
            or type(self.rows) is not tuple
            or not 1 <= len(self.rows) <= SCHEDULER_RETRIEVAL_PAGE_GROUP_LIMIT
            or any(type(row) is not SchedulerRetrievalEvidenceAuthorityRow for row in self.rows)
        ):
            _fail("scheduler_retrieval_evidence_authority_page_invalid")

    def __repr__(self) -> str:
        return (
            "SchedulerRetrievalEvidenceAuthorityPage("
            f"page_index={self.page_index}, group_count={len(self.rows)})"
        )

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("SchedulerRetrievalEvidenceAuthorityPage contains private material")


@final
@dataclass(frozen=True, slots=True)
class SchedulerOfficialCaseAuthorityTerminal:
    schema_fingerprint_sha256: str
    configuration_sha256: str
    case_count: int
    page_count: int
    pages_root_sha256: str
    rows_root_sha256: str
    terminal_commitment_sha256: str
    terminal_hmac_sha256: str
    authority_root_sha256: str

    def __post_init__(self) -> None:
        _validate_terminal(
            digests=(
                self.schema_fingerprint_sha256,
                self.configuration_sha256,
                self.pages_root_sha256,
                self.rows_root_sha256,
                self.terminal_commitment_sha256,
                self.terminal_hmac_sha256,
                self.authority_root_sha256,
            ),
            counts=(self.case_count, self.page_count),
        )


@final
@dataclass(frozen=True, slots=True)
class SchedulerRetrievalEvidenceAuthorityTerminal:
    schema_fingerprint_sha256: str
    configuration_sha256: str
    group_count: int
    result_row_count: int
    page_count: int
    pages_root_sha256: str
    groups_root_sha256: str
    result_rows_root_sha256: str
    terminal_commitment_sha256: str
    terminal_hmac_sha256: str
    authority_root_sha256: str

    def __post_init__(self) -> None:
        _validate_terminal(
            digests=(
                self.schema_fingerprint_sha256,
                self.configuration_sha256,
                self.pages_root_sha256,
                self.groups_root_sha256,
                self.result_rows_root_sha256,
                self.terminal_commitment_sha256,
                self.terminal_hmac_sha256,
                self.authority_root_sha256,
            ),
            counts=(self.group_count, self.result_row_count, self.page_count),
        )


def validate_case_run_scopes(
    value: object,
) -> tuple[SchedulerOfficialCaseRunScope, ...]:
    if (
        type(value) is not tuple
        or not value
        or any(type(item) is not SchedulerOfficialCaseRunScope for item in value)
        or len({item.run_id for item in value}) != len(value)
        or len({item.run_authority_sha256 for item in value}) != len(value)
        or len({item.benchmark for item in value}) != len(value)
        or len({item.suite_authority_sha256 for item in value}) != 1
        or len({item.methodology_sha256 for item in value}) != 1
        or len({item.publishable_profile_id for item in value}) != 1
        or len({item.publishable_profile_sha256 for item in value}) != 1
        or sum(item.case_count for item in value) > SCHEDULER_OFFICIAL_AUTHORITY_CASE_LIMIT
    ):
        _fail("scheduler_official_case_authority_scopes_invalid")
    return value


def validate_retrieval_run_scopes(
    value: object,
) -> tuple[SchedulerRetrievalRunScope, ...]:
    if (
        type(value) is not tuple
        or not value
        or any(type(item) is not SchedulerRetrievalRunScope for item in value)
        or len({item.case_scope.run_id for item in value}) != len(value)
        or len({item.case_scope.run_authority_sha256 for item in value}) != len(value)
        or len({item.case_scope.suite_authority_sha256 for item in value}) != 1
        or len({item.case_scope.methodology_sha256 for item in value}) != 1
        or len({item.case_scope.publishable_profile_id for item in value}) != 1
        or len({item.case_scope.publishable_profile_sha256 for item in value}) != 1
        or sum(item.case_scope.case_count * 2 for item in value)
        > SCHEDULER_OFFICIAL_AUTHORITY_RETRIEVAL_GROUP_LIMIT
    ):
        _fail("scheduler_retrieval_evidence_authority_scopes_invalid")
    return value


def _validate_terminal(*, digests: tuple[object, ...], counts: tuple[object, ...]) -> None:
    if any(not _is_sha256(value) for value in digests) or any(
        type(value) is not int or value < 0 for value in counts
    ):
        _fail("scheduler_official_authority_terminal_invalid")


def _bounded_identity(value: object) -> bool:
    if type(value) is not str or not value:
        return False
    try:
        return len(value.encode("utf-8")) <= 200
    except UnicodeEncodeError:
        return False


def _is_identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _fail(code: str) -> None:
    raise SchedulerOfficialAuthorityError(code)


__all__ = (
    "SCHEDULER_OFFICIAL_AUTHORITY_CASE_LIMIT",
    "SCHEDULER_OFFICIAL_AUTHORITY_PAGE_BYTES_LIMIT",
    "SCHEDULER_OFFICIAL_AUTHORITY_RETRIEVAL_GROUP_LIMIT",
    "SCHEDULER_OFFICIAL_AUTHORITY_SCHEMA_VERSION",
    "SCHEDULER_OFFICIAL_CASE_PAGE_ROW_LIMIT",
    "SCHEDULER_RETRIEVAL_PAGE_GROUP_LIMIT",
    "SchedulerOfficialAuthorityError",
    "SchedulerOfficialCaseAuthorityPage",
    "SchedulerOfficialCaseAuthorityRow",
    "SchedulerOfficialCaseAuthorityTerminal",
    "SchedulerOfficialCaseRunScope",
    "SchedulerRetrievalBackendScope",
    "SchedulerRetrievalEvidenceAuthorityPage",
    "SchedulerRetrievalEvidenceAuthorityRow",
    "SchedulerRetrievalEvidenceAuthorityTerminal",
    "SchedulerRetrievalRunScope",
)
