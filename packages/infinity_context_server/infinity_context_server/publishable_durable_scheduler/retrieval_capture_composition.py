"""Production composition for sealing exact publishable retrieval evidence."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_http import (
    InfinityContextHttpComparisonBackend,
    Mem0HttpComparisonBackend,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerCallStage,
    SchedulerRunAuthority,
    SchedulerSuiteAuthority,
    require_run_authority,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    BuiltSchedulerManifest,
    SchedulerCaseAuthority,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SchedulerOfficialCaseRunScope,
    SchedulerRetrievalBackendScope,
    SchedulerRetrievalEvidenceAuthorityTerminal,
    SchedulerRetrievalRunScope,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_official_cases import (
    PreparedPublishableOfficialCases,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_contracts import (
    SchedulerRetrievalCaptureError,
    SchedulerRetrievalCapturePlan,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_http_adapters import (
    InfinityContextSchedulerRetrievalAdapter,
    Mem0SchedulerRetrievalAdapter,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_service import (
    SQLiteSchedulerRetrievalCaptureService,
)

from .retrieval_evidence_sqlite_authority import SQLiteSchedulerRetrievalEvidenceReader


@final
@dataclass(frozen=True, slots=True, repr=False)
class SealedSchedulerRetrievalEvidence:
    """Authenticated sealed terminal and its exact read capability."""

    plan: SchedulerRetrievalCapturePlan
    terminal: SchedulerRetrievalEvidenceAuthorityTerminal
    reader: SQLiteSchedulerRetrievalEvidenceReader = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.plan) is not SchedulerRetrievalCapturePlan
            or type(self.terminal) is not SchedulerRetrievalEvidenceAuthorityTerminal
            or type(self.reader) is not SQLiteSchedulerRetrievalEvidenceReader
            or self.reader.authority_root_sha256 != self.terminal.authority_root_sha256
        ):
            _fail("scheduler_retrieval_capture_sealed_evidence_invalid")

    def close(self) -> None:
        self.reader.close()

    def __repr__(self) -> str:
        return (
            "SealedSchedulerRetrievalEvidence("
            f"authority_root_sha256={self.terminal.authority_root_sha256!r}, "
            f"group_count={self.terminal.group_count}, private_reader=<bound>)"
        )


@final
@dataclass(frozen=True, slots=True, repr=False)
class SchedulerRetrievalCaptureComposition:
    """Target-bound producer which seals and reopens one retrieval authority."""

    path: Path = field(repr=False)
    authentication_key: bytes = field(repr=False)
    plan: SchedulerRetrievalCapturePlan
    service: SQLiteSchedulerRetrievalCaptureService = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.path, Path)
            or not self.path.is_absolute()
            or type(self.authentication_key) is not bytes
            or not 32 <= len(self.authentication_key) <= 1024
            or type(self.plan) is not SchedulerRetrievalCapturePlan
            or type(self.service) is not SQLiteSchedulerRetrievalCaptureService
        ):
            _fail("scheduler_retrieval_capture_composition_invalid")

    def capture(self) -> SealedSchedulerRetrievalEvidence:
        terminal = self.service.capture()
        reader = SQLiteSchedulerRetrievalEvidenceReader.open(
            self.path,
            authentication_key=self.authentication_key,
            authority_root_sha256=terminal.authority_root_sha256,
            case_authority_root_sha256=self.plan.case_authority_root_sha256,
        )
        try:
            return SealedSchedulerRetrievalEvidence(
                plan=self.plan,
                terminal=terminal,
                reader=reader,
            )
        except BaseException:
            reader.close()
            raise

    def __repr__(self) -> str:
        return (
            "SchedulerRetrievalCaptureComposition("
            f"capture_identity_sha256={self.plan.capture_identity_sha256!r}, "
            "private_capabilities=<bound>)"
        )


def compose_scheduler_retrieval_capture(
    path: str | os.PathLike[str],
    *,
    suite: SchedulerSuiteAuthority,
    official_cases: PreparedPublishableOfficialCases,
    infinity_backend: InfinityContextHttpComparisonBackend,
    mem0_backend: Mem0HttpComparisonBackend,
    authentication_key: bytes,
) -> SchedulerRetrievalCaptureComposition:
    """Bind prepared official cases to the two exact ordered HTTP targets."""

    try:
        selected_path = Path(path)
    except (TypeError, ValueError):
        _fail("scheduler_retrieval_capture_composition_invalid")
    if (
        type(suite) is not SchedulerSuiteAuthority
        or type(official_cases) is not PreparedPublishableOfficialCases
        or not selected_path.is_absolute()
        or official_cases.reader.authority_root_sha256
        != official_cases.terminal.authority_root_sha256
    ):
        _fail("scheduler_retrieval_capture_composition_invalid")
    runs = tuple(require_run_authority(suite, run) for run in official_cases.runs)
    ordered_cases = tuple(
        _manifest_cases(run=run, manifest=manifest)
        for run, manifest in zip(runs, official_cases.manifests, strict=True)
    )
    scopes = tuple(_retrieval_scope(suite=suite, run=run) for run in runs)
    plan = SchedulerRetrievalCapturePlan(
        run_scopes=scopes,
        ordered_cases=ordered_cases,
        case_authority_root_sha256=official_cases.terminal.authority_root_sha256,
    )
    infinity = InfinityContextSchedulerRetrievalAdapter(infinity_backend)
    mem0 = Mem0SchedulerRetrievalAdapter(mem0_backend)
    service = SQLiteSchedulerRetrievalCaptureService(
        selected_path,
        plan=plan,
        case_reader=official_cases.reader,
        backends=(infinity, mem0),
        authentication_key=authentication_key,
    )
    return SchedulerRetrievalCaptureComposition(
        path=selected_path,
        authentication_key=authentication_key,
        plan=plan,
        service=service,
    )


def _retrieval_scope(
    *,
    suite: SchedulerSuiteAuthority,
    run: SchedulerRunAuthority,
) -> SchedulerRetrievalRunScope:
    binding = run.binding
    case_scope = SchedulerOfficialCaseRunScope(
        suite_authority_sha256=suite.commitment_sha256,
        run_authority_sha256=run.commitment_sha256,
        run_binding_commitment_sha256=binding.binding_commitment_sha256,
        run_id=binding.run_id,
        benchmark=binding.profile.benchmark,
        scheduler_profile_id=binding.profile.profile_id,
        publishable_profile_id=PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
        publishable_profile_sha256=PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
        methodology_sha256=suite.methodology_sha256,
        dataset_sha256=binding.dataset_sha256,
        case_manifest_sha256=binding.case_manifest_sha256,
        case_count=binding.profile.case_count,
    )
    backends = tuple(
        SchedulerRetrievalBackendScope(
            backend_index=index,
            backend_role=backend.backend_role,
            target_identity_sha256=backend.target_identity_sha256,
        )
        for index, backend in enumerate(binding.backends)
    )
    return SchedulerRetrievalRunScope(case_scope=case_scope, backends=backends)


def _manifest_cases(
    *,
    run: SchedulerRunAuthority,
    manifest: BuiltSchedulerManifest,
) -> tuple[SchedulerCaseAuthority, ...]:
    if (
        type(run) is not SchedulerRunAuthority
        or type(manifest) is not BuiltSchedulerManifest
        or manifest.authority.run_authority_sha256 != run.commitment_sha256
        or manifest.authority.case_manifest_sha256 != run.binding.case_manifest_sha256
    ):
        _fail("scheduler_retrieval_capture_manifest_cross_wire")
    cases = tuple(
        SchedulerCaseAuthority(case_id=call.case_id, case_alias=call.case_alias)
        for shard in manifest.shards
        for call in shard.calls
        if call.backend_index == 0 and call.stage is SchedulerCallStage.ANSWER
    )
    if len(cases) != run.binding.profile.case_count or tuple(
        call.case_index
        for shard in manifest.shards
        for call in shard.calls
        if call.backend_index == 0 and call.stage is SchedulerCallStage.ANSWER
    ) != tuple(range(len(cases))):
        _fail("scheduler_retrieval_capture_manifest_coverage_invalid")
    return cases


def _fail(code: str) -> None:
    raise SchedulerRetrievalCaptureError(code) from None


__all__ = (
    "SchedulerRetrievalCaptureComposition",
    "SealedSchedulerRetrievalEvidence",
    "compose_scheduler_retrieval_capture",
)
