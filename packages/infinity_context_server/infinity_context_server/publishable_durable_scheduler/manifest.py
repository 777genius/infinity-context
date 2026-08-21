"""Exact case-aligned shard manifest for the publishable scheduler v4."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import final

from infinity_context_server.publishable_durable_scheduler.contracts import (
    SCHEDULER_CALLS_PER_CASE,
    SCHEDULER_QUERY_LIMIT,
    SCHEDULER_SCHEMA_VERSION,
    SCHEDULER_SHARD_CALL_LIMIT,
    SchedulerCallStage,
    SchedulerContractError,
    SchedulerRunAuthority,
    SchedulerSuiteAuthority,
    commitment,
    require_run_authority,
)


@final
@dataclass(frozen=True, slots=True)
class SchedulerCaseAuthority:
    case_id: str
    case_alias: str

    def __post_init__(self) -> None:
        if (
            type(self.case_id) is not str
            or not self.case_id
            or len(self.case_id) > 200
            or type(self.case_alias) is not str
            or not self.case_alias
            or len(self.case_alias) > 200
        ):
            _fail("scheduler_case_authority_invalid")

    def material(self) -> dict[str, str]:
        return {"case_alias": self.case_alias, "case_id": self.case_id}


def case_manifest_sha256(cases: tuple[SchedulerCaseAuthority, ...]) -> str:
    if (
        type(cases) is not tuple
        or not cases
        or any(type(item) is not SchedulerCaseAuthority for item in cases)
        or len({item.case_id for item in cases}) != len(cases)
        or len({item.case_alias for item in cases}) != len(cases)
    ):
        _fail("scheduler_case_manifest_invalid")
    return commitment(
        "case-manifest",
        {
            "ordered_cases": [item.material() for item in cases],
            "schema_version": SCHEDULER_SCHEMA_VERSION,
        },
    )


@final
@dataclass(frozen=True, slots=True)
class SchedulerLogicalCall:
    suite_authority_sha256: str
    run_authority_sha256: str
    run_id: str
    case_index: int
    case_id: str
    case_alias: str
    backend_index: int
    backend_role: str
    target_identity_sha256: str
    stage: SchedulerCallStage
    ordinal: int
    shard_index: int
    token_ceiling: int
    depends_on_logical_call_id: str | None
    logical_call_id: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            not _sha(self.suite_authority_sha256)
            or not _sha(self.run_authority_sha256)
            or type(self.run_id) is not str
            or not self.run_id
            or type(self.case_id) is not str
            or not self.case_id
            or type(self.case_alias) is not str
            or not self.case_alias
            or type(self.case_index) is not int
            or self.case_index < 0
            or type(self.backend_index) is not int
            or self.backend_index not in (0, 1)
            or type(self.ordinal) is not int
            or self.ordinal < 0
            or type(self.shard_index) is not int
            or self.shard_index < 0
            or type(self.token_ceiling) is not int
            or self.token_ceiling < 1
            or type(self.stage) is not SchedulerCallStage
            or type(self.backend_role) is not str
            or not self.backend_role
            or not _sha(self.target_identity_sha256)
        ):
            _fail("scheduler_call_shape_invalid")
        expected_ordinal = (
            self.case_index * SCHEDULER_CALLS_PER_CASE
            + self.backend_index * 2
            + (1 if self.stage is SchedulerCallStage.JUDGE else 0)
        )
        if (
            self.ordinal != expected_ordinal
            or self.shard_index != self.ordinal // SCHEDULER_SHARD_CALL_LIMIT
        ):
            _fail("scheduler_call_ordinal_invalid")
        if self.stage is SchedulerCallStage.ANSWER:
            if self.depends_on_logical_call_id is not None:
                _fail("scheduler_answer_dependency_invalid")
        elif (
            type(self.depends_on_logical_call_id) is not str
            or len(self.depends_on_logical_call_id) != 64
            or any(char not in "0123456789abcdef" for char in self.depends_on_logical_call_id)
        ):
            _fail("scheduler_judge_dependency_invalid")
        object.__setattr__(self, "logical_call_id", _logical_call_id(self.identity_material()))

    def identity_material(self) -> dict[str, object]:
        return {
            "backend_index": self.backend_index,
            "backend_role": self.backend_role,
            "case_alias": self.case_alias,
            "case_id": self.case_id,
            "case_index": self.case_index,
            "depends_on_logical_call_id": self.depends_on_logical_call_id,
            "ordinal": self.ordinal,
            "run_authority_sha256": self.run_authority_sha256,
            "run_id": self.run_id,
            "schema_version": SCHEDULER_SCHEMA_VERSION,
            "shard_index": self.shard_index,
            "stage": self.stage.value,
            "suite_authority_sha256": self.suite_authority_sha256,
            "target_identity_sha256": self.target_identity_sha256,
            "token_ceiling": self.token_ceiling,
        }


@final
@dataclass(frozen=True, slots=True)
class SchedulerManifestShard:
    run_id: str
    run_authority_sha256: str
    shard_index: int
    start_ordinal: int
    end_ordinal: int
    calls: tuple[SchedulerLogicalCall, ...]
    calls_root_sha256: str = field(init=False)
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.shard_index) is not int
            or self.shard_index < 0
            or type(self.start_ordinal) is not int
            or type(self.end_ordinal) is not int
            or self.start_ordinal != self.shard_index * SCHEDULER_SHARD_CALL_LIMIT
            or self.end_ordinal <= self.start_ordinal
            or self.end_ordinal - self.start_ordinal > SCHEDULER_SHARD_CALL_LIMIT
            or self.start_ordinal % SCHEDULER_CALLS_PER_CASE != 0
            or self.end_ordinal % SCHEDULER_CALLS_PER_CASE != 0
            or type(self.calls) is not tuple
            or len(self.calls) != self.end_ordinal - self.start_ordinal
        ):
            _fail("scheduler_manifest_shard_shape_invalid")
        for offset, call in enumerate(self.calls):
            if (
                type(call) is not SchedulerLogicalCall
                or call.run_id != self.run_id
                or call.run_authority_sha256 != self.run_authority_sha256
                or call.shard_index != self.shard_index
                or call.ordinal != self.start_ordinal + offset
            ):
                _fail("scheduler_manifest_shard_call_invalid")
            if call.stage is SchedulerCallStage.JUDGE:
                if offset == 0:
                    _fail("scheduler_manifest_shard_dependency_invalid")
                answer = self.calls[offset - 1]
                if (
                    answer.stage is not SchedulerCallStage.ANSWER
                    or answer.case_index != call.case_index
                    or answer.backend_index != call.backend_index
                    or call.depends_on_logical_call_id != answer.logical_call_id
                ):
                    _fail("scheduler_manifest_shard_dependency_invalid")
        calls_root = commitment(
            "shard-calls",
            {
                "logical_call_ids": [item.logical_call_id for item in self.calls],
                "run_authority_sha256": self.run_authority_sha256,
                "shard_index": self.shard_index,
            },
        )
        object.__setattr__(self, "calls_root_sha256", calls_root)
        object.__setattr__(self, "commitment_sha256", commitment("shard", self.material()))

    def material(self) -> dict[str, object]:
        return {
            "calls_root_sha256": self.calls_root_sha256,
            "end_ordinal": self.end_ordinal,
            "item_count": len(self.calls),
            "run_authority_sha256": self.run_authority_sha256,
            "run_id": self.run_id,
            "schema_version": SCHEDULER_SCHEMA_VERSION,
            "shard_index": self.shard_index,
            "start_ordinal": self.start_ordinal,
        }


@final
@dataclass(frozen=True, slots=True)
class SchedulerRunManifestAuthority:
    suite_authority_sha256: str
    run_authority_sha256: str
    run_id: str
    case_manifest_sha256: str
    call_count: int
    ordered_shard_commitments: tuple[str, ...]
    ordered_call_root_sha256: str
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.call_count) is not int
            or self.call_count < 1
            or type(self.ordered_shard_commitments) is not tuple
            or not self.ordered_shard_commitments
            or any(not _sha(item) for item in self.ordered_shard_commitments)
            or not _sha(self.suite_authority_sha256)
            or not _sha(self.run_authority_sha256)
            or not _sha(self.case_manifest_sha256)
            or not _sha(self.ordered_call_root_sha256)
        ):
            _fail("scheduler_manifest_authority_invalid")
        object.__setattr__(
            self,
            "commitment_sha256",
            commitment("run-manifest", self.material()),
        )

    def material(self) -> dict[str, object]:
        return {
            "call_count": self.call_count,
            "case_manifest_sha256": self.case_manifest_sha256,
            "ordered_call_root_sha256": self.ordered_call_root_sha256,
            "ordered_shard_commitments": list(self.ordered_shard_commitments),
            "run_authority_sha256": self.run_authority_sha256,
            "run_id": self.run_id,
            "schema_version": SCHEDULER_SCHEMA_VERSION,
            "suite_authority_sha256": self.suite_authority_sha256,
        }


@final
@dataclass(frozen=True, slots=True)
class BuiltSchedulerManifest:
    authority: SchedulerRunManifestAuthority
    shards: tuple[SchedulerManifestShard, ...]

    def __post_init__(self) -> None:
        if (
            type(self.authority) is not SchedulerRunManifestAuthority
            or type(self.shards) is not tuple
            or any(type(item) is not SchedulerManifestShard for item in self.shards)
            or tuple(item.commitment_sha256 for item in self.shards)
            != self.authority.ordered_shard_commitments
        ):
            _fail("scheduler_built_manifest_invalid")


@final
@dataclass(frozen=True, slots=True)
class SchedulerPageQuery:
    run_id: str
    run_manifest_authority_sha256: str
    shard_index: int
    limit: int

    def __post_init__(self) -> None:
        if (
            type(self.run_id) is not str
            or not self.run_id
            or not _sha(self.run_manifest_authority_sha256)
            or type(self.shard_index) is not int
            or self.shard_index < 0
            or type(self.limit) is not int
            or not 1 <= self.limit <= SCHEDULER_QUERY_LIMIT
        ):
            _fail("scheduler_page_query_invalid")


def build_scheduler_manifest(
    run: SchedulerRunAuthority,
    *,
    suite: SchedulerSuiteAuthority,
    ordered_cases: tuple[SchedulerCaseAuthority, ...],
) -> BuiltSchedulerManifest:
    require_run_authority(suite, run)
    profile = run.binding.profile
    if (
        type(ordered_cases) is not tuple
        or len(ordered_cases) != profile.case_count
        or case_manifest_sha256(ordered_cases) != run.binding.case_manifest_sha256
    ):
        _fail("scheduler_case_manifest_binding_invalid")
    calls: list[SchedulerLogicalCall] = []
    for case_index, case in enumerate(ordered_cases):
        for backend_index, _backend in enumerate(run.binding.backends):
            answer = _call(
                run,
                case=case,
                case_index=case_index,
                backend_index=backend_index,
                stage=SchedulerCallStage.ANSWER,
                dependency=None,
            )
            calls.append(answer)
            calls.append(
                _call(
                    run,
                    case=case,
                    case_index=case_index,
                    backend_index=backend_index,
                    stage=SchedulerCallStage.JUDGE,
                    dependency=answer.logical_call_id,
                )
            )
    if len(calls) != profile.call_count:
        _fail("scheduler_manifest_call_count_invalid")
    shards = tuple(
        SchedulerManifestShard(
            run_id=run.binding.run_id,
            run_authority_sha256=run.commitment_sha256,
            shard_index=index,
            start_ordinal=index * SCHEDULER_SHARD_CALL_LIMIT,
            end_ordinal=min((index + 1) * SCHEDULER_SHARD_CALL_LIMIT, len(calls)),
            calls=tuple(
                calls[index * SCHEDULER_SHARD_CALL_LIMIT : (index + 1) * SCHEDULER_SHARD_CALL_LIMIT]
            ),
        )
        for index in range(profile.shard_count)
    )
    if len(shards) != profile.shard_count or shards[-1].end_ordinal != len(calls):
        _fail("scheduler_manifest_shard_count_invalid")
    ordered_call_root = commitment(
        "ordered-calls",
        {
            "logical_call_ids": [item.logical_call_id for item in calls],
            "run_authority_sha256": run.commitment_sha256,
        },
    )
    authority = SchedulerRunManifestAuthority(
        suite_authority_sha256=run.suite_authority_sha256,
        run_authority_sha256=run.commitment_sha256,
        run_id=run.binding.run_id,
        case_manifest_sha256=run.binding.case_manifest_sha256,
        call_count=len(calls),
        ordered_shard_commitments=tuple(item.commitment_sha256 for item in shards),
        ordered_call_root_sha256=ordered_call_root,
    )
    return BuiltSchedulerManifest(authority=authority, shards=shards)


def _call(
    run: SchedulerRunAuthority,
    *,
    case: SchedulerCaseAuthority,
    case_index: int,
    backend_index: int,
    stage: SchedulerCallStage,
    dependency: str | None,
) -> SchedulerLogicalCall:
    backend = run.binding.backends[backend_index]
    ordinal = case_index * SCHEDULER_CALLS_PER_CASE + backend_index * 2
    if stage is SchedulerCallStage.JUDGE:
        ordinal += 1
    limits = run.binding.limits
    return SchedulerLogicalCall(
        suite_authority_sha256=run.suite_authority_sha256,
        run_authority_sha256=run.commitment_sha256,
        run_id=run.binding.run_id,
        case_index=case_index,
        case_id=case.case_id,
        case_alias=case.case_alias,
        backend_index=backend_index,
        backend_role=backend.backend_role,
        target_identity_sha256=backend.target_identity_sha256,
        stage=stage,
        ordinal=ordinal,
        shard_index=ordinal // SCHEDULER_SHARD_CALL_LIMIT,
        token_ceiling=(
            limits.answer_max_output_tokens
            if stage is SchedulerCallStage.ANSWER
            else limits.judge_max_output_tokens
        ),
        depends_on_logical_call_id=dependency,
    )


def _logical_call_id(material: dict[str, object]) -> str:
    return commitment("logical-call", material)


def _sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _fail(code: str) -> None:
    raise SchedulerContractError(code)


__all__ = (
    "BuiltSchedulerManifest",
    "SchedulerCaseAuthority",
    "SchedulerLogicalCall",
    "SchedulerManifestShard",
    "SchedulerPageQuery",
    "SchedulerRunManifestAuthority",
    "build_scheduler_manifest",
    "case_manifest_sha256",
)
