from __future__ import annotations

import hashlib
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from infinity_context_server.publishable_durable_scheduler import (
    retrieval_capture_contracts as capture_contracts,
)
from infinity_context_server.publishable_durable_scheduler import (
    retrieval_capture_service as capture_service,
)
from infinity_context_server.publishable_durable_scheduler import (
    retrieval_evidence_sqlite_authority as retrieval_authority,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerBenchmark,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerCaseAuthority,
    case_manifest_sha256,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SchedulerOfficialAuthorityError,
    SchedulerOfficialCaseAuthorityPage,
    SchedulerOfficialCaseAuthorityRow,
    SchedulerOfficialCaseRunScope,
    SchedulerRetrievalBackendScope,
    SchedulerRetrievalRunScope,
)
from infinity_context_server.publishable_durable_scheduler.official_case_sqlite_authority import (
    SQLiteSchedulerOfficialCaseAuthorityBuilder,
    SQLiteSchedulerOfficialCaseReader,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_contracts import (
    SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT,
    SchedulerBackendRetrievalRequest,
    SchedulerBackendRetrievalResult,
    SchedulerRetrievalCaptureError,
    SchedulerRetrievalCapturePlan,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_service import (
    SQLiteSchedulerRetrievalCaptureService,
    verify_scheduler_retrieval_capture_progress,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
    SchedulerRetrievalEvidenceKey,
)

_KEY = b"scheduler-retrieval-capture-e2e-key/v1" * 2
_OTHER_KEY = b"scheduler-retrieval-capture-wrong-key/v1" * 2


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _identities(benchmark: SchedulerBenchmark, count: int) -> tuple[SchedulerCaseAuthority, ...]:
    return tuple(
        SchedulerCaseAuthority(
            case_id=f"{benchmark.value}-case-{index:04d}",
            case_alias=f"{benchmark.value}-alias-{index:04d}",
        )
        for index in range(count)
    )


def _case_scopes(
    *, locomo_count: int, longmemeval_count: int
) -> tuple[SchedulerOfficialCaseRunScope, ...]:
    scopes = []
    for benchmark, count in (
        (SchedulerBenchmark.LOCOMO, locomo_count),
        (SchedulerBenchmark.LONGMEMEVAL, longmemeval_count),
    ):
        identities = _identities(benchmark, count)
        scopes.append(
            SchedulerOfficialCaseRunScope(
                suite_authority_sha256=_sha("suite"),
                run_authority_sha256=_sha(f"run:{benchmark.value}"),
                run_binding_commitment_sha256=_sha(f"binding:{benchmark.value}"),
                run_id=f"run-{benchmark.value}",
                benchmark=benchmark,
                scheduler_profile_id=f"scheduler-{benchmark.value}",
                publishable_profile_id="publishable-priority-v4",
                publishable_profile_sha256=_sha("publishable-profile"),
                methodology_sha256=_sha("methodology"),
                dataset_sha256=_sha(f"dataset:{benchmark.value}"),
                case_manifest_sha256=case_manifest_sha256(identities),
                case_count=count,
            )
        )
    return tuple(scopes)


def _retrieval_scopes(
    case_scopes: tuple[SchedulerOfficialCaseRunScope, ...],
) -> tuple[SchedulerRetrievalRunScope, ...]:
    return tuple(
        SchedulerRetrievalRunScope(
            case_scope=scope,
            backends=(
                SchedulerRetrievalBackendScope(0, "infinity-context", _sha("infinity-target")),
                SchedulerRetrievalBackendScope(1, "mem0", _sha("mem0-target")),
            ),
        )
        for scope in case_scopes
    )


def _case(
    scope: SchedulerOfficialCaseRunScope,
    identity: SchedulerCaseAuthority,
    index: int,
) -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark=scope.benchmark.value,
        case_id=identity.case_id,
        question=f"What is the current choice for case {index}?",
        expected_terms=(f"gold-answer-{index}",),
        forbidden_terms=(f"gold-forbidden-{index}",),
        memory_scope_external_ref=f"scope-{scope.benchmark.value}-{index}",
        thread_external_ref=f"thread-{scope.benchmark.value}-{index}",
        metadata={
            "_evaluator_ground_truth": f"private-gold-{index}",
            "question_type": "synthetic",
        },
    )


def _build_case_authority(
    path: Path,
    scopes: tuple[SchedulerOfficialCaseRunScope, ...],
    identities: tuple[tuple[SchedulerCaseAuthority, ...], ...],
):
    builder = SQLiteSchedulerOfficialCaseAuthorityBuilder.create(
        path,
        run_scopes=scopes,
        authentication_key=_KEY,
    )
    pending = []
    page_index = 0
    for scope, run_identities in zip(scopes, identities, strict=True):
        for index, identity in enumerate(run_identities):
            pending.append(
                SchedulerOfficialCaseAuthorityRow(
                    run_id=scope.run_id,
                    case_index=index,
                    case_id=identity.case_id,
                    case_alias=identity.case_alias,
                    case=_case(scope, identity, index),
                )
            )
            if len(pending) == 256:
                builder.append_page(SchedulerOfficialCaseAuthorityPage(page_index, tuple(pending)))
                pending.clear()
                page_index += 1
    if pending:
        builder.append_page(SchedulerOfficialCaseAuthorityPage(page_index, tuple(pending)))
    terminal = builder.finalize()
    builder.close()
    return terminal


class _SyntheticBackend:
    def __init__(
        self,
        role: str,
        target: str,
        *,
        fail_at: int | None = None,
        crosswire_result: bool = False,
        ordered_calls: list[str] | None = None,
    ) -> None:
        self._role = role
        self._target = target
        self.fail_at = fail_at
        self.crosswire_result = crosswire_result
        self.ordered_calls = ordered_calls
        self.calls: list[tuple[str, str, str, str, int]] = []
        self.successful_calls: list[tuple[str, str, str, str, int]] = []

    @property
    def backend_role(self) -> str:
        return self._role

    @property
    def target_identity_sha256(self) -> str:
        return self._target

    def retrieve_exact(
        self, *, request: SchedulerBackendRetrievalRequest
    ) -> SchedulerBackendRetrievalResult:
        assert request.retrieval_limit == SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT
        assert request.cutoff == SCHEDULER_OFFICIAL_ANSWER_CUTOFF
        assert not hasattr(request, "expected_terms")
        assert not hasattr(request, "forbidden_terms")
        assert not hasattr(request, "metadata")
        self.calls.append(
            (
                request.case_key.run_id,
                request.case_key.case_id,
                request.query_identity_sha256,
                request.request_identity_sha256,
                request.backend_index,
            )
        )
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            raise RuntimeError("synthetic process crash")
        self.successful_calls.append(self.calls[-1])
        if self.ordered_calls is not None:
            self.ordered_calls.append(self._role)
        memory = RetrievedMemory(
            text=f"evidence:{self._role}:{request.case_key.case_id}",
            rank=1,
            score=0.5,
            item_id=f"{self._role}:{request.case_key.case_id}",
            created_at="2024-01-01T00:00:00Z",
            source_refs=(request.case_key.case_alias,),
            metadata={"query_identity_sha256": request.query_identity_sha256},
        )
        result = SchedulerBackendRetrievalResult.bind(
            request=request,
            memories=(memory,),
        )
        if self.crosswire_result:
            return replace(result, target_identity_sha256=_sha("foreign-target"))
        return result


def _reader_key(scope, identity, index, root):
    return scope.case_key(
        case_index=index,
        case_id=identity.case_id,
        case_alias=identity.case_alias,
        authority_root_sha256=root,
    )


def test_focused_capture_exact_resume_seal_reopen_and_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locomo_count = 2
    longmemeval_count = 1
    case_count = locomo_count + longmemeval_count
    group_count = case_count * 2
    monkeypatch.setattr(
        capture_contracts,
        "LOCOMO_PROFILE",
        SimpleNamespace(case_count=locomo_count),
    )
    monkeypatch.setattr(
        capture_contracts,
        "LONGMEMEVAL_PROFILE",
        SimpleNamespace(case_count=longmemeval_count),
    )
    monkeypatch.setattr(capture_contracts, "PUBLISHABLE_SUITE_CASE_COUNT", case_count)
    monkeypatch.setattr(
        capture_contracts,
        "SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT",
        group_count,
    )
    monkeypatch.setattr(
        capture_service,
        "SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT",
        group_count,
    )
    case_scopes = _case_scopes(
        locomo_count=locomo_count,
        longmemeval_count=longmemeval_count,
    )
    identities = tuple(_identities(scope.benchmark, scope.case_count) for scope in case_scopes)
    case_terminal = _build_case_authority(
        tmp_path / "official-cases.sqlite3", case_scopes, identities
    )
    assert case_terminal.case_count == case_count
    case_reader = SQLiteSchedulerOfficialCaseReader.open(
        tmp_path / "official-cases.sqlite3",
        authentication_key=_KEY,
        authority_root_sha256=case_terminal.authority_root_sha256,
    )
    retrieval_scopes = _retrieval_scopes(case_scopes)
    plan = SchedulerRetrievalCapturePlan(
        run_scopes=retrieval_scopes,
        ordered_cases=identities,
        case_authority_root_sha256=case_terminal.authority_root_sha256,
    )
    ordered_calls: list[str] = []
    infinity = _SyntheticBackend(
        "infinity-context",
        retrieval_scopes[0].backends[0].target_identity_sha256,
        ordered_calls=ordered_calls,
    )
    mem0 = _SyntheticBackend(
        "mem0",
        retrieval_scopes[0].backends[1].target_identity_sha256,
        fail_at=1,
        ordered_calls=ordered_calls,
    )
    retrieval_path = tmp_path / "retrieval-evidence.sqlite3"
    service = SQLiteSchedulerRetrievalCaptureService(
        retrieval_path,
        plan=plan,
        case_reader=case_reader,
        backends=(infinity, mem0),
        authentication_key=_KEY,
    )
    with pytest.raises(SchedulerRetrievalCaptureError, match="backend_failed"):
        service.capture()
    with sqlite3.connect(retrieval_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM retrieval_groups").fetchone()[0] == 1

    mem0.fail_at = None
    progress = service.capture_through(4)
    assert progress.next_sequence == 4
    assert progress.expected_group_count == group_count
    assert progress.complete is False
    assert progress.terminal is None
    assert verify_scheduler_retrieval_capture_progress(
        progress,
        plan=plan,
        authentication_key=_KEY,
    )
    assert not verify_scheduler_retrieval_capture_progress(
        progress,
        plan=plan,
        authentication_key=_OTHER_KEY,
    )
    boundary_calls = len(infinity.calls), len(mem0.calls)
    assert service.read_progress() == progress
    assert (len(infinity.calls), len(mem0.calls)) == boundary_calls
    assert service.capture_through(4) == progress
    assert (len(infinity.calls), len(mem0.calls)) == boundary_calls
    tampered_progress = replace(progress, authentication_hmac_sha256="0" * 64)
    assert not verify_scheduler_retrieval_capture_progress(
        tampered_progress,
        plan=plan,
        authentication_key=_KEY,
    )
    with pytest.raises(SchedulerRetrievalCaptureError, match="resume_boundary_invalid"):
        service.capture_through(3)

    terminal = service.capture()
    calls_after_seal = len(infinity.calls), len(mem0.calls)
    successful_calls_after_seal = (
        len(infinity.successful_calls),
        len(mem0.successful_calls),
    )
    assert terminal.group_count == group_count
    assert terminal.result_row_count == group_count
    assert terminal.page_count == group_count
    assert len(terminal.terminal_hmac_sha256) == 64
    assert calls_after_seal == (case_count, case_count + 1)
    assert successful_calls_after_seal == (case_count, case_count)
    assert len({item[3] for item in infinity.successful_calls}) == case_count
    assert len({item[3] for item in mem0.successful_calls}) == case_count
    assert (
        tuple(ordered_calls)
        == (
            "infinity-context",
            "mem0",
        )
        * case_count
    )

    assert service.capture() == terminal
    assert (len(infinity.calls), len(mem0.calls)) == calls_after_seal
    assert (
        len(infinity.successful_calls),
        len(mem0.successful_calls),
    ) == successful_calls_after_seal
    with sqlite3.connect(retrieval_path) as connection:
        maximum = connection.execute("SELECT MAX(group_count) FROM authority_pages").fetchone()[0]
        assert maximum == 1
        assert maximum <= capture_contracts.SCHEDULER_RETRIEVAL_CAPTURE_PAGE_GROUP_LIMIT

    reader = retrieval_authority.SQLiteSchedulerRetrievalEvidenceReader.open(
        retrieval_path,
        authentication_key=_KEY,
        authority_root_sha256=terminal.authority_root_sha256,
        case_authority_root_sha256=case_terminal.authority_root_sha256,
    )
    sample_scope = retrieval_scopes[1]
    sample_identity = identities[1][-1]
    case_read = case_reader.read_exact(
        key=_reader_key(
            sample_scope.case_scope,
            sample_identity,
            longmemeval_count - 1,
            case_terminal.authority_root_sha256,
        )
    )
    backend = sample_scope.backends[1]
    result = reader.read_exact(
        key=SchedulerRetrievalEvidenceKey(
            case_key=case_read.key,
            case_material_sha256=case_read.material_sha256,
            backend_index=1,
            backend_role=backend.backend_role,
            target_identity_sha256=backend.target_identity_sha256,
            cutoff=50,
            authority_root_sha256=terminal.authority_root_sha256,
        )
    )
    assert len(result.memories) == 1
    assert result.memories[0].text.startswith("evidence:mem0:")
    reader.close()
    with pytest.raises(SchedulerOfficialAuthorityError, match="authentication"):
        retrieval_authority.SQLiteSchedulerRetrievalEvidenceReader.open(
            retrieval_path,
            authentication_key=_OTHER_KEY,
            authority_root_sha256=terminal.authority_root_sha256,
            case_authority_root_sha256=case_terminal.authority_root_sha256,
        )

    tampered = tmp_path / "retrieval-tampered.sqlite3"
    shutil.copy2(retrieval_path, tampered)
    tampered.chmod(0o600)
    with sqlite3.connect(tampered) as connection:
        connection.execute(
            "UPDATE retrieval_rows SET memory_json=? WHERE group_sequence=0 AND rank=1",
            ('{"tampered":true}',),
        )
    with pytest.raises(SchedulerOfficialAuthorityError, match="retrieval"):
        retrieval_authority.SQLiteSchedulerRetrievalEvidenceReader.open(
            tampered,
            authentication_key=_KEY,
            authority_root_sha256=terminal.authority_root_sha256,
            case_authority_root_sha256=case_terminal.authority_root_sha256,
        )

    with pytest.raises(SchedulerRetrievalCaptureError, match="cross_wire"):
        SQLiteSchedulerRetrievalCaptureService(
            tmp_path / "swapped.sqlite3",
            plan=plan,
            case_reader=case_reader,
            backends=(mem0, infinity),
            authentication_key=_KEY,
        )
    bad_infinity = _SyntheticBackend(
        "infinity-context",
        retrieval_scopes[0].backends[0].target_identity_sha256,
        crosswire_result=True,
    )
    crosswired = SQLiteSchedulerRetrievalCaptureService(
        tmp_path / "crosswired-result.sqlite3",
        plan=plan,
        case_reader=case_reader,
        backends=(bad_infinity, mem0),
        authentication_key=_KEY,
    )
    with pytest.raises(SchedulerRetrievalCaptureError, match="result_cross_wire"):
        crosswired.capture()
    case_reader.close()
