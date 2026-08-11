"""Crash-resumable production capture into the sealed retrieval authority."""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import final

from infinity_context_server.publishable_durable_scheduler.contracts import canonical_json
from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SchedulerOfficialAuthorityError,
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
from .retrieval_evidence_sqlite_schema import terminal_payload

_CAPTURE_PROGRESS_SCHEMA = "scheduler-retrieval-capture-progress.v1"
_CAPTURE_PROGRESS_MAC_DOMAIN = b"infinity-context/scheduler-retrieval-capture-progress/v1\0"


@final
@dataclass(frozen=True, slots=True)
class SchedulerRetrievalCaptureProgress:
    """Authenticated durable cursor for one exact retrieval-capture plan."""

    capture_identity_sha256: str
    case_authority_root_sha256: str
    next_sequence: int
    expected_group_count: int
    terminal: SchedulerRetrievalEvidenceAuthorityTerminal | None = field(repr=False)
    authentication_hmac_sha256: str

    def __post_init__(self) -> None:
        complete = self.next_sequence == self.expected_group_count
        if (
            not _sha256(self.capture_identity_sha256)
            or not _sha256(self.case_authority_root_sha256)
            or type(self.next_sequence) is not int
            or type(self.expected_group_count) is not int
            or self.expected_group_count != SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT
            or not 0 <= self.next_sequence <= self.expected_group_count
            or not _sha256(self.authentication_hmac_sha256)
            or complete != (self.terminal is not None)
        ):
            _fail("scheduler_retrieval_capture_progress_invalid")
        if self.terminal is not None:
            try:
                self.terminal.__post_init__()
            except Exception:
                _fail("scheduler_retrieval_capture_progress_invalid")
            if self.terminal.group_count != self.expected_group_count:
                _fail("scheduler_retrieval_capture_progress_invalid")

    @property
    def complete(self) -> bool:
        return self.next_sequence == self.expected_group_count

    def material(self) -> dict[str, object]:
        return {
            "capture_identity_sha256": self.capture_identity_sha256,
            "case_authority_root_sha256": self.case_authority_root_sha256,
            "expected_group_count": self.expected_group_count,
            "next_sequence": self.next_sequence,
            "schema_version": _CAPTURE_PROGRESS_SCHEMA,
            "terminal": None if self.terminal is None else terminal_payload(self.terminal),
        }


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

    def capture(
        self, *, expected_authority_root_sha256: str | None = None
    ) -> SchedulerRetrievalEvidenceAuthorityTerminal:
        """Resume at the next committed result, or create and seal a new authority."""

        progress = self.capture_through(
            SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT,
            expected_authority_root_sha256=expected_authority_root_sha256,
        )
        terminal = progress.terminal
        if terminal is None:  # pragma: no cover - exact total boundary requires a terminal
            _fail("scheduler_retrieval_capture_terminal_invalid")
        return terminal

    def read_progress(
        self, *, expected_authority_root_sha256: str | None = None
    ) -> SchedulerRetrievalCaptureProgress:
        """Authenticate the durable cursor without issuing a retrieval call."""

        _validate_expected_authority_root(expected_authority_root_sha256)
        self._verify_live_bindings()
        builder = self._open_builder()
        try:
            sequence = builder.next_sequence
            terminal = (
                _finalize_expected(
                    builder,
                    expected_authority_root_sha256=expected_authority_root_sha256,
                )
                if sequence == SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT
                else None
            )
            progress = _capture_progress(
                plan=self._plan,
                next_sequence=sequence,
                terminal=terminal,
                authentication_key=self._authentication_key,
            )
            if not verify_scheduler_retrieval_capture_progress(
                progress,
                plan=self._plan,
                authentication_key=self._authentication_key,
            ):
                _fail("scheduler_retrieval_capture_progress_authentication_invalid")
            return progress
        finally:
            builder.close()

    def capture_through(
        self,
        end_sequence: int,
        *,
        expected_authority_root_sha256: str | None = None,
    ) -> SchedulerRetrievalCaptureProgress:
        """Capture through one exact durable cursor, without crossing that boundary."""

        if (
            type(end_sequence) is not int
            or not 0 <= end_sequence <= SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT
        ):
            _fail("scheduler_retrieval_capture_end_sequence_invalid")
        _validate_expected_authority_root(expected_authority_root_sha256)
        self._verify_live_bindings()
        builder = self._open_builder()
        try:
            sequence = builder.next_sequence
            if sequence > end_sequence:
                _fail("scheduler_retrieval_capture_resume_boundary_invalid")
            while sequence < end_sequence:
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
            terminal = None
            if sequence == SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT:
                terminal = _finalize_expected(
                    builder,
                    expected_authority_root_sha256=expected_authority_root_sha256,
                )
                if (
                    type(terminal) is not SchedulerRetrievalEvidenceAuthorityTerminal
                    or terminal.group_count != SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT
                    or terminal.page_count != SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT
                ):
                    _fail("scheduler_retrieval_capture_terminal_invalid")
            progress = _capture_progress(
                plan=self._plan,
                next_sequence=sequence,
                terminal=terminal,
                authentication_key=self._authentication_key,
            )
            if not verify_scheduler_retrieval_capture_progress(
                progress,
                plan=self._plan,
                authentication_key=self._authentication_key,
            ):
                _fail("scheduler_retrieval_capture_progress_authentication_invalid")
            return progress
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


def verify_scheduler_retrieval_capture_progress(
    progress: object,
    *,
    plan: SchedulerRetrievalCapturePlan,
    authentication_key: bytes,
) -> bool:
    """Verify that a progress cursor belongs to the exact plan and HMAC key."""

    try:
        if (
            type(progress) is not SchedulerRetrievalCaptureProgress
            or type(plan) is not SchedulerRetrievalCapturePlan
            or type(authentication_key) is not bytes
            or not 32 <= len(authentication_key) <= 1024
        ):
            return False
        progress.__post_init__()
        plan.__post_init__()
        if (
            progress.capture_identity_sha256 != plan.capture_identity_sha256
            or progress.case_authority_root_sha256 != plan.case_authority_root_sha256
            or progress.expected_group_count != plan.group_count
        ):
            return False
        expected = _progress_hmac(progress.material(), authentication_key=authentication_key)
        return hmac.compare_digest(expected, progress.authentication_hmac_sha256)
    except Exception:
        return False


def _capture_progress(
    *,
    plan: SchedulerRetrievalCapturePlan,
    next_sequence: int,
    terminal: SchedulerRetrievalEvidenceAuthorityTerminal | None,
    authentication_key: bytes,
) -> SchedulerRetrievalCaptureProgress:
    values = {
        "capture_identity_sha256": plan.capture_identity_sha256,
        "case_authority_root_sha256": plan.case_authority_root_sha256,
        "next_sequence": next_sequence,
        "expected_group_count": plan.group_count,
        "terminal": terminal,
    }
    unsigned = SchedulerRetrievalCaptureProgress(
        **values,
        authentication_hmac_sha256="0" * 64,
    )
    return SchedulerRetrievalCaptureProgress(
        **values,
        authentication_hmac_sha256=_progress_hmac(
            unsigned.material(),
            authentication_key=authentication_key,
        ),
    )


def _progress_hmac(material: dict[str, object], *, authentication_key: bytes) -> str:
    if type(authentication_key) is not bytes or not 32 <= len(authentication_key) <= 1024:
        _fail("scheduler_retrieval_capture_progress_authentication_invalid")
    return hmac.new(
        authentication_key,
        _CAPTURE_PROGRESS_MAC_DOMAIN + canonical_json(material),
        hashlib.sha256,
    ).hexdigest()


def _finalize_expected(
    builder: SQLiteSchedulerRetrievalEvidenceAuthorityBuilder,
    *,
    expected_authority_root_sha256: str | None,
) -> SchedulerRetrievalEvidenceAuthorityTerminal:
    try:
        return builder.finalize(
            expected_authority_root_sha256=expected_authority_root_sha256,
        )
    except SchedulerOfficialAuthorityError as error:
        if error.code == "scheduler_retrieval_evidence_authority_root_mismatch":
            _fail("scheduler_retrieval_capture_expected_authority_mismatch")
        raise


def _validate_expected_authority_root(value: str | None) -> None:
    if value is not None and not _sha256(value):
        _fail("scheduler_retrieval_capture_expected_authority_invalid")


def _sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise SchedulerRetrievalCaptureError(code)


__all__ = (
    "SQLiteSchedulerRetrievalCaptureService",
    "SchedulerRetrievalCaptureProgress",
    "verify_scheduler_retrieval_capture_progress",
)
