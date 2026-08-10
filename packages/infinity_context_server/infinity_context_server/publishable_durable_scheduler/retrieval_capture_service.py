"""Crash-resumable production capture into the sealed retrieval authority."""

from __future__ import annotations

import os
from pathlib import Path
from typing import final

from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SchedulerRetrievalEvidenceAuthorityPage,
    SchedulerRetrievalEvidenceAuthorityRow,
    SchedulerRetrievalEvidenceAuthorityTerminal,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_contracts import (
    SCHEDULER_RETRIEVAL_CAPTURE_BACKENDS,
    SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT,
    SchedulerBackendRetrievalRequest,
    SchedulerBackendRetrievalResult,
    SchedulerRetrievalBackendPort,
    SchedulerRetrievalCaptureError,
    SchedulerRetrievalCapturePlan,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SchedulerAuthenticatedOfficialCase,
    SchedulerOfficialCaseReaderPort,
)

from .retrieval_evidence_sqlite_authority import (
    SQLiteSchedulerRetrievalEvidenceAuthorityBuilder,
)


@final
class SQLiteSchedulerRetrievalCaptureService:
    """Query both exact backends in order and HMAC-seal all 4,080 groups."""

    __slots__ = (
        "_authentication_key",
        "_backends",
        "_case_reader",
        "_path",
        "_plan",
    )

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        plan: SchedulerRetrievalCapturePlan,
        case_reader: SchedulerOfficialCaseReaderPort,
        backends: tuple[SchedulerRetrievalBackendPort, SchedulerRetrievalBackendPort],
        authentication_key: bytes,
    ) -> None:
        if type(plan) is not SchedulerRetrievalCapturePlan:
            _fail("scheduler_retrieval_capture_composition_invalid")
        plan.__post_init__()
        try:
            selected_path = Path(path)
        except (TypeError, ValueError):
            _fail("scheduler_retrieval_capture_composition_invalid")
        if (
            not selected_path.is_absolute()
            or selected_path.name in {"", ".", ".."}
            or type(backends) is not tuple
            or len(backends) != 2
            or backends[0] is backends[1]
            or type(authentication_key) is not bytes
            or not 32 <= len(authentication_key) <= 1024
        ):
            _fail("scheduler_retrieval_capture_composition_invalid")
        try:
            reader_root = case_reader.authority_root_sha256
            observed = tuple(
                (backend.backend_role, backend.target_identity_sha256) for backend in backends
            )
            callables_valid = all(
                callable(getattr(backend, "retrieve_exact", None)) for backend in backends
            )
        except Exception:
            _fail("scheduler_retrieval_capture_composition_invalid")
        expected = tuple(
            (item.backend_role, item.target_identity_sha256) for item in plan.run_scopes[0].backends
        )
        if (
            reader_root != plan.case_authority_root_sha256
            or observed != expected
            or tuple(role for role, _target in observed) != SCHEDULER_RETRIEVAL_CAPTURE_BACKENDS
            or not callables_valid
        ):
            _fail("scheduler_retrieval_capture_composition_cross_wire")
        self._path = selected_path
        self._plan = plan
        self._case_reader = case_reader
        self._backends = backends
        self._authentication_key = authentication_key

    def capture(self) -> SchedulerRetrievalEvidenceAuthorityTerminal:
        """Resume at the next committed result, or create and seal a new authority."""

        self._verify_live_bindings()
        builder = self._open_builder()
        try:
            sequence = builder.next_sequence
            if sequence > SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT:
                _fail("scheduler_retrieval_capture_resume_boundary_invalid")
            while sequence < SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT:
                page = self._capture_page(
                    page_index=sequence,
                    start_sequence=sequence,
                    end_sequence=sequence + 1,
                )
                builder.append_page(page)
                next_sequence = builder.next_sequence
                if next_sequence != sequence + 1:
                    _fail("scheduler_retrieval_capture_progress_invalid")
                sequence = next_sequence
            terminal = builder.finalize()
            if (
                type(terminal) is not SchedulerRetrievalEvidenceAuthorityTerminal
                or terminal.group_count != SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT
                or terminal.page_count != SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT
            ):
                _fail("scheduler_retrieval_capture_terminal_invalid")
            return terminal
        finally:
            builder.close()

    def _verify_live_bindings(self) -> None:
        self._plan.__post_init__()
        expected = tuple(
            (item.backend_role, item.target_identity_sha256)
            for item in self._plan.run_scopes[0].backends
        )
        try:
            observed = tuple(
                (backend.backend_role, backend.target_identity_sha256) for backend in self._backends
            )
            reader_root = self._case_reader.authority_root_sha256
        except Exception:
            _fail("scheduler_retrieval_capture_composition_invalid")
        if observed != expected or reader_root != self._plan.case_authority_root_sha256:
            _fail("scheduler_retrieval_capture_composition_cross_wire")

    def _open_builder(self) -> SQLiteSchedulerRetrievalEvidenceAuthorityBuilder:
        kwargs = {
            "run_scopes": self._plan.run_scopes,
            "case_authority_root_sha256": self._plan.case_authority_root_sha256,
            "authentication_key": self._authentication_key,
        }
        if self._path.exists():
            return SQLiteSchedulerRetrievalEvidenceAuthorityBuilder.open(self._path, **kwargs)
        return SQLiteSchedulerRetrievalEvidenceAuthorityBuilder.create(self._path, **kwargs)

    def _capture_page(
        self,
        *,
        page_index: int,
        start_sequence: int,
        end_sequence: int,
    ) -> SchedulerRetrievalEvidenceAuthorityPage:
        rows: list[SchedulerRetrievalEvidenceAuthorityRow] = []
        cached_binding: tuple[str, int] | None = None
        case_read: SchedulerAuthenticatedOfficialCase | None = None
        for sequence in range(start_sequence, end_sequence):
            scope, identity, case_index, backend_index = self._plan.group_binding(sequence)
            binding = scope.case_scope.run_id, case_index
            if binding != cached_binding:
                case_key = scope.case_scope.case_key(
                    case_index=case_index,
                    case_id=identity.case_id,
                    case_alias=identity.case_alias,
                    authority_root_sha256=self._plan.case_authority_root_sha256,
                )
                try:
                    case_read = self._case_reader.read_exact(key=case_key)
                except Exception:
                    _fail("scheduler_retrieval_capture_case_read_failed")
                if (
                    type(case_read) is not SchedulerAuthenticatedOfficialCase
                    or case_read.key != case_key
                    or case_read.case.benchmark != scope.case_scope.benchmark.value
                    or case_read.case.case_id != identity.case_id
                ):
                    _fail("scheduler_retrieval_capture_case_cross_wire")
                case_read.__post_init__()
                cached_binding = binding
            if case_read is None:
                _fail("scheduler_retrieval_capture_case_read_failed")
            backend_scope = scope.backends[backend_index]
            request = SchedulerBackendRetrievalRequest(
                case_key=case_read.key,
                case_material_sha256=case_read.material_sha256,
                backend_index=backend_index,
                backend_role=backend_scope.backend_role,
                target_identity_sha256=backend_scope.target_identity_sha256,
                question=case_read.case.question,
                memory_scope_external_ref=(case_read.case.memory_scope_external_ref or None),
                thread_external_ref=(case_read.case.thread_external_ref or None),
            )
            result = self._retrieve(backend_index, request)
            rows.append(
                SchedulerRetrievalEvidenceAuthorityRow(
                    case_key=case_read.key,
                    case_material_sha256=case_read.material_sha256,
                    backend_index=backend_index,
                    memories=result.memories,
                )
            )
        return SchedulerRetrievalEvidenceAuthorityPage(page_index, tuple(rows))

    def _retrieve(
        self,
        backend_index: int,
        request: SchedulerBackendRetrievalRequest,
    ) -> SchedulerBackendRetrievalResult:
        backend = self._backends[backend_index]
        try:
            exact_binding = (
                backend.backend_role == request.backend_role
                and backend.target_identity_sha256 == request.target_identity_sha256
            )
        except Exception:
            exact_binding = False
        if not exact_binding:
            _fail("scheduler_retrieval_capture_backend_cross_wire")
        try:
            result = backend.retrieve_exact(request=request)
        except SchedulerRetrievalCaptureError:
            raise
        except Exception:
            _fail("scheduler_retrieval_capture_backend_failed")
        if type(result) is not SchedulerBackendRetrievalResult or not result.is_bound_to(request):
            _fail("scheduler_retrieval_capture_result_cross_wire")
        result.__post_init__()
        return result

    def __repr__(self) -> str:
        return "SQLiteSchedulerRetrievalCaptureService(<private-composition>)"


def _fail(code: str) -> None:
    raise SchedulerRetrievalCaptureError(code)


__all__ = ("SQLiteSchedulerRetrievalCaptureService",)
