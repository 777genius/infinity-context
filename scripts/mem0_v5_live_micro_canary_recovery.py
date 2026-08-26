"""Crash-exact lifecycle and report recovery for the live Mem0 v5 micro-canary."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    canonical_sha256,
)

from scripts.mem0_v5_live_micro_canary_storage import LockedPrivateRoot
from scripts.mem0_v5_live_micro_canary_views import (
    CompositionFactory,
    SealView,
    SearchView,
    TerminalView,
)
from scripts.mem0_v5_live_runtime_authority import MicroCanaryInputs

REPORT_SCHEMA = "managed-mem0-v5-live-micro-canary.v1"
RECOVERY_CAPSULE_SCHEMA = "managed-mem0-v5-live-micro-canary-recovery.v1"
RECOVERY_CAPSULE_NAME = "live-canary-report-capsule.json"

_CAPSULE_KEY_DOMAIN = b"managed-mem0-v5/live-canary-report-capsule-key/v1\0"
_CAPSULE_MAC_DOMAIN = b"managed-mem0-v5/live-canary-report-capsule/v1\0"
_SHA256_CHARS = frozenset("0123456789abcdef")
_MAX_CAPSULE_BYTES = 256 * 1024
_MAX_REPORT_BYTES = 256 * 1024
_SUCCESS_COMMITMENTS = frozenset(
    {
        "admission_commitment_sha256",
        "operation_root_sha256",
        "seal_commitment_sha256",
        "search_evidence_commitment_sha256",
        "search_result_root_sha256",
    }
)
_SUCCESS_FIELDS = frozenset(
    {"authenticated_search_result_count", "authenticated_storage_record_count", "usage"}
)


class _RecoveryStore(Protocol):
    def load(self, *, expected_base: dict[str, object]) -> _RecoveryCapsule | None: ...

    def seal_evidence(
        self, report: dict[str, object], *, expected_base: dict[str, object]
    ) -> _RecoveryCapsule: ...

    def mark_report_ready(
        self,
        capsule: _RecoveryCapsule,
        *,
        report: dict[str, object],
        terminal_evidence: dict[str, object],
        expected_base: dict[str, object],
    ) -> _RecoveryCapsule: ...


@dataclass(frozen=True, slots=True)
class _RecoveryCapsule:
    stage: str
    report: dict[str, object]
    terminal_evidence: dict[str, object] | None


@final
class LiveCanaryRecoverySession:
    """Authenticated monotonic capsule held under a per-state-root process lock."""

    __slots__ = ("_boundary", "_key", "_storage")

    def __init__(
        self,
        *,
        state_root: Path,
        checkpoint_signing_key: bytes,
        boundary_hook: Callable[[str], None] | None = None,
    ) -> None:
        if (
            not isinstance(state_root, Path)
            or not state_root.is_absolute()
            or type(checkpoint_signing_key) is not bytes
            or not 32 <= len(checkpoint_signing_key) <= 4096
            or (boundary_hook is not None and not callable(boundary_hook))
        ):
            raise ValueError("mem0_v5_live_recovery_inputs_invalid")
        self._key = hmac.new(
            checkpoint_signing_key,
            _CAPSULE_KEY_DOMAIN,
            hashlib.sha256,
        ).digest()
        self._boundary = boundary_hook
        self._storage = LockedPrivateRoot(
            state_root,
            root_code="mem0_v5_live_recovery_root_invalid",
        )

    def __enter__(self) -> LiveCanaryRecoverySession:
        self._storage.__enter__()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()

    def close(self) -> None:
        self._storage.close()

    def load(self, *, expected_base: dict[str, object]) -> _RecoveryCapsule | None:
        raw = self._storage.read_optional(
            RECOVERY_CAPSULE_NAME,
            maximum_bytes=_MAX_CAPSULE_BYTES,
            code="mem0_v5_live_recovery_capsule_invalid",
        )
        if raw is None:
            return None
        return self._decode(raw, expected_base=expected_base)

    def seal_evidence(
        self, report: dict[str, object], *, expected_base: dict[str, object]
    ) -> _RecoveryCapsule:
        _validate_success_report(report, expected_base=expected_base, terminal=False)
        current = self.load(expected_base=expected_base)
        if current is not None:
            if current.stage == "evidence_sealed" and current.report == report:
                return current
            raise ValueError("mem0_v5_live_recovery_capsule_replayed")
        capsule = _RecoveryCapsule("evidence_sealed", deepcopy(report), None)
        self._write(capsule)
        return self.load(expected_base=expected_base) or _unreachable()

    def mark_report_ready(
        self,
        capsule: _RecoveryCapsule,
        *,
        report: dict[str, object],
        terminal_evidence: dict[str, object],
        expected_base: dict[str, object],
    ) -> _RecoveryCapsule:
        if capsule.stage == "report_ready":
            if capsule.report == report and capsule.terminal_evidence == terminal_evidence:
                return capsule
            raise ValueError("mem0_v5_live_recovery_capsule_replayed")
        if capsule.stage != "evidence_sealed":
            raise ValueError("mem0_v5_live_recovery_capsule_invalid")
        _validate_success_report(report, expected_base=expected_base, terminal=True)
        current = self.load(expected_base=expected_base)
        if current != capsule:
            raise ValueError("mem0_v5_live_recovery_capsule_replayed")
        ready = _RecoveryCapsule(
            "report_ready",
            deepcopy(report),
            deepcopy(terminal_evidence),
        )
        self._write(ready)
        loaded = self.load(expected_base=expected_base)
        if loaded != ready:
            raise ValueError("mem0_v5_live_recovery_capsule_write_failed")
        return loaded

    def _decode(self, raw: bytes, *, expected_base: dict[str, object]) -> _RecoveryCapsule:
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("mem0_v5_live_recovery_capsule_invalid") from None
        if type(value) is not dict or set(value) != {
            "schema_version",
            "stage",
            "report",
            "terminal_evidence",
            "capsule_hmac_sha256",
        }:
            raise ValueError("mem0_v5_live_recovery_capsule_invalid")
        unsigned = {key: item for key, item in value.items() if key != "capsule_hmac_sha256"}
        expected_mac = hmac.new(
            self._key,
            _CAPSULE_MAC_DOMAIN + _json_bytes(unsigned),
            hashlib.sha256,
        ).hexdigest()
        if (
            value["schema_version"] != RECOVERY_CAPSULE_SCHEMA
            or value["stage"] not in {"evidence_sealed", "report_ready"}
            or type(value["report"]) is not dict
            or not _is_sha256(value["capsule_hmac_sha256"])
            or not hmac.compare_digest(expected_mac, value["capsule_hmac_sha256"])
            or raw != _json_bytes(value)
        ):
            raise ValueError("mem0_v5_live_recovery_capsule_invalid")
        terminal = value["stage"] == "report_ready"
        terminal_evidence = value["terminal_evidence"]
        if terminal != (type(terminal_evidence) is dict):
            raise ValueError("mem0_v5_live_recovery_capsule_invalid")
        _validate_success_report(
            value["report"],
            expected_base=expected_base,
            terminal=terminal,
        )
        return _RecoveryCapsule(value["stage"], value["report"], terminal_evidence)

    def _write(self, capsule: _RecoveryCapsule) -> None:
        unsigned = {
            "schema_version": RECOVERY_CAPSULE_SCHEMA,
            "stage": capsule.stage,
            "report": capsule.report,
            "terminal_evidence": capsule.terminal_evidence,
        }
        payload = {
            **unsigned,
            "capsule_hmac_sha256": hmac.new(
                self._key,
                _CAPSULE_MAC_DOMAIN + _json_bytes(unsigned),
                hashlib.sha256,
            ).hexdigest(),
        }
        self._storage.atomic_replace(
            RECOVERY_CAPSULE_NAME,
            _json_bytes(payload),
            boundary=self._boundary,
            prefix="capsule",
        )


def execute_micro_canary(
    *,
    inputs: MicroCanaryInputs,
    composition_factory: CompositionFactory,
    recovery: _RecoveryStore | None = None,
    report_context: dict[str, object] | None = None,
) -> dict[str, object]:
    """Execute at most one dispatch and recover the exact terminal report."""

    base = base_report(inputs, report_context=report_context)
    if inputs.orphan_dispatch_claim:
        return _no_go(base, "orphan_dispatch_claim")
    composition = None
    terminal: TerminalView | None = None
    seal: SealView | None = None
    capsule: _RecoveryCapsule | None = None
    record_count = 0
    started = False
    succeeded = False
    failure = "live_micro_canary_failed"
    try:
        capsule = None if recovery is None else recovery.load(expected_base=base)
        if capsule is not None and not inputs.restore_existing:
            failure = "recovery_state_mismatch"
            raise _NoGo
        composition = composition_factory()
        coordinator = composition.coordinator
        if inputs.restore_existing:
            started = True
            checkpoint = coordinator.restore(
                authority=composition.authority,
                request=composition.request,
                budget_policy=ManagedMem0V5BudgetPolicy(maximum_total_call_count=5),
            )
            phase = _phase(checkpoint)
            if phase in {"cleanup_attempted", "terminal"}:
                terminal = coordinator.terminal_evidence
                if capsule is None:
                    failure = "recovery_evidence_missing"
                    raise _NoGo
                return _recover_terminal_report(
                    base=base,
                    capsule=capsule,
                    checkpoint=checkpoint,
                    terminal=terminal,
                    recovery=recovery,
                )
            if capsule is not None and capsule.stage == "report_ready":
                failure = "recovery_state_mismatch"
                raise _NoGo
            seal = coordinator.seal_restored_completed()
        else:
            coordinator.admit(
                authority=composition.authority,
                request=composition.request,
                budget_policy=ManagedMem0V5BudgetPolicy(maximum_total_call_count=5),
            )
            started = True
            try:
                seal = coordinator.dispatch_pending()
            except Exception:
                recovery_composition = composition_factory()
                composition = recovery_composition
                coordinator = recovery_composition.coordinator
                started = True
                try:
                    checkpoint = coordinator.restore(
                        authority=recovery_composition.authority,
                        request=recovery_composition.request,
                        budget_policy=ManagedMem0V5BudgetPolicy(maximum_total_call_count=5),
                    )
                    if _phase(checkpoint) in {"cleanup_attempted", "terminal"}:
                        failure = "recovery_evidence_missing"
                        raise _NoGo
                    seal = coordinator.seal_restored_completed()
                except _NoGo:
                    raise
                except Exception:
                    failure = "dispatch_status_unavailable"
                    raise _NoGo from None
        if getattr(coordinator.budget, "total_call_count", None) != 5:
            failure = "coordinator_budget_invalid"
            raise _NoGo
        observations = coordinator.storage_observations
        record_count = sum(len(item.created_record_ids) for item in observations)
        if record_count < 1:
            failure = "zero_authenticated_memories"
            raise _NoGo
        if capsule is None:
            search = coordinator.search_evidence(
                corpus_id=inputs.projection.cases[0].corpus_id,
                query=inputs.projection.search_query,
                limit=10,
            )
            if not search.records:
                failure = "authenticated_search_empty"
                raise _NoGo
            staged_report = _success_report(
                base,
                seal=seal,
                search=search,
                record_count=record_count,
            )
            capsule = (
                _RecoveryCapsule("evidence_sealed", staged_report, None)
                if recovery is None
                else recovery.seal_evidence(staged_report, expected_base=base)
            )
        _validate_preterminal_binding(capsule.report, seal=seal, record_count=record_count)
        succeeded = True
    except _NoGo:
        pass
    except Exception:
        failure = "live_micro_canary_failed"
    finally:
        if started and composition is not None and terminal is None:
            try:
                terminal = (
                    composition.coordinator.cleanup()
                    if succeeded or seal is not None
                    else composition.coordinator.abort()
                )
            except Exception:
                terminal = None
                succeeded = False
                failure = "terminal_cleanup_failed"
    if not succeeded or seal is None or terminal is None or capsule is None:
        report = _no_go(base, failure)
        if terminal is not None:
            _attach_terminal(report, terminal)
        return report
    try:
        final_report, terminal_payload = _finalize_report(capsule.report, terminal=terminal)
        if recovery is not None:
            capsule = recovery.mark_report_ready(
                capsule,
                report=final_report,
                terminal_evidence=terminal_payload,
                expected_base=base,
            )
            final_report = capsule.report
        return deepcopy(final_report)
    except Exception:
        report = _no_go(base, "terminal_evidence_invalid")
        _attach_terminal(report, terminal)
        return report


def base_report(
    inputs: MicroCanaryInputs,
    *,
    report_context: dict[str, object] | None = None,
) -> dict[str, object]:
    projection = inputs.projection
    runtime = inputs.runtime
    report: dict[str, object] = {
        "schema_version": REPORT_SCHEMA,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "ok": False,
        "outcome": "NO-GO",
        "failure_code": None,
        "budget": {
            "coordinator_full_plan_total_calls": 5,
            "hard_dispatch_guard_max": 1,
            "benchmark_calls_executed": 0,
            "answer_calls_executed": 0,
            "judge_calls_executed": 0,
        },
        "requested_output_tokens": 4096,
        "requested_output_tokens_enforced": False,
        "release": {"account": "<redacted>", "runtime": "<redacted>"},
        "commitments": {
            "case_file_sha256": projection.case_file_sha256,
            "manifest_authority_commitment_sha256": (
                projection.authority.authority_commitment_sha256
            ),
            "sealed_payload_sha256": projection.authority.sealed_payload_sha256,
            "request_body_sha256": projection.request_body_sha256,
            "response_format_sha256": projection.response_format_sha256,
            "response_schema_sha256": projection.response_schema_sha256,
            "runtime_response_format_sha256": runtime.response_format_sha256,
            "runtime_response_schema_sha256": runtime.response_schema_sha256,
            "account_binding_hmac_sha256": runtime.account_binding_hmac_sha256,
            "runtime_source_sha256": runtime.runtime_source_sha256,
            "runtime_base_sha256": runtime.runtime_base_sha256,
            "route_binding_sha256": runtime.route_binding_sha256,
            "base_instructions_sha256": runtime.base_instructions_sha256,
            "extraction_system_prompt_sha256": runtime.extraction_system_prompt_sha256,
        },
    }
    if report_context is not None:
        context = deepcopy(report_context)
        additions = context.pop("commitments", None)
        if type(additions) is not dict or any(key in report["commitments"] for key in additions):
            raise ValueError("mem0_v5_live_report_context_invalid")
        commitments = report["commitments"]
        assert type(commitments) is dict
        commitments.update(additions)
        if any(key in report for key in context):
            raise ValueError("mem0_v5_live_report_context_invalid")
        report.update(context)
    return report


def publish_report(
    path: Path,
    root: Path,
    report: dict[str, object],
    *,
    boundary_hook: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Atomically publish or exactly read back an already-published report."""

    if (
        not isinstance(path, Path)
        or not isinstance(root, Path)
        or not path.is_absolute()
        or path.parent != root
        or (boundary_hook is not None and not callable(boundary_hook))
    ):
        raise ValueError("mem0_v5_live_report_path_invalid")
    encoded = _json_bytes(report)
    if not 1 <= len(encoded) <= _MAX_REPORT_BYTES:
        raise ValueError("mem0_v5_live_report_invalid")
    with LockedPrivateRoot(
        root,
        root_code="mem0_v5_live_report_root_invalid",
    ) as storage:
        existing = storage.read_optional(
            path.name,
            maximum_bytes=_MAX_REPORT_BYTES,
            code="mem0_v5_live_report_invalid",
        )
        if existing is not None:
            if existing != encoded:
                raise ValueError("mem0_v5_live_report_differs")
            return _decode_report(existing)
        storage.atomic_replace(
            path.name,
            encoded,
            boundary=boundary_hook,
            prefix="report",
        )
        readback = storage.read_optional(
            path.name,
            maximum_bytes=_MAX_REPORT_BYTES,
            code="mem0_v5_live_report_invalid",
        )
        if readback != encoded:
            raise ValueError("mem0_v5_live_report_readback_differs")
        if boundary_hook is not None:
            boundary_hook("report_read_back")
        return _decode_report(readback)


def _recover_terminal_report(
    *,
    base: dict[str, object],
    capsule: _RecoveryCapsule,
    checkpoint: object,
    terminal: TerminalView,
    recovery: _RecoveryStore | None,
) -> dict[str, object]:
    if _phase(checkpoint) != "terminal":
        raise ValueError("mem0_v5_live_terminal_checkpoint_invalid")
    checkpoint_terminal = getattr(checkpoint, "terminal_evidence", None)
    seal = getattr(checkpoint, "seal", None)
    units = getattr(checkpoint, "units", None)
    if checkpoint_terminal != terminal or type(units) is not tuple:
        raise ValueError("mem0_v5_live_terminal_checkpoint_invalid")
    record_count = sum(len(getattr(unit, "record_ids", ())) for unit in units)
    source_report = (
        _preterminal_report(capsule.report) if capsule.stage == "report_ready" else capsule.report
    )
    _validate_preterminal_binding(source_report, seal=seal, record_count=record_count)
    final_report, terminal_payload = _finalize_report(source_report, terminal=terminal)
    if capsule.stage == "report_ready":
        if capsule.report != final_report or capsule.terminal_evidence != terminal_payload:
            raise ValueError("mem0_v5_live_recovery_capsule_differs")
        return deepcopy(capsule.report)
    if recovery is None:
        return final_report
    ready = recovery.mark_report_ready(
        capsule,
        report=final_report,
        terminal_evidence=terminal_payload,
        expected_base=base,
    )
    return deepcopy(ready.report)


def _success_report(
    base: dict[str, object],
    *,
    seal: SealView,
    search: SearchView,
    record_count: int,
) -> dict[str, object]:
    report = deepcopy(base)
    commitments = report["commitments"]
    assert type(commitments) is dict
    commitments.update(
        {
            "admission_commitment_sha256": seal.admission_commitment_sha256,
            "seal_commitment_sha256": seal.commitment_sha256,
            "operation_root_sha256": seal.operation_root_sha256,
            "search_result_root_sha256": search.result_root_sha256,
            "search_evidence_commitment_sha256": search.evidence_commitment_sha256,
        }
    )
    report.update(
        {
            "outcome": "GO",
            "ok": True,
            "failure_code": None,
            "usage": _usage(seal),
            "authenticated_search_result_count": len(search.records),
            "authenticated_storage_record_count": record_count,
        }
    )
    return report


def _finalize_report(
    preterminal: dict[str, object], *, terminal: TerminalView
) -> tuple[dict[str, object], dict[str, object]]:
    terminal_payload = _terminal_payload(terminal)
    commitments = preterminal.get("commitments")
    if type(commitments) is not dict:
        raise ValueError("mem0_v5_live_terminal_evidence_invalid")
    if (
        terminal_payload["terminal_state"] != "deleted"
        or terminal_payload["admission_commitment_sha256"]
        != commitments.get("admission_commitment_sha256")
        or terminal_payload["seal_commitment_sha256"] != commitments.get("seal_commitment_sha256")
        or terminal_payload["operation_root_sha256"] != commitments.get("operation_root_sha256")
        or terminal_payload["deleted_operation_count"] != 1
        or terminal_payload["residual_record_count"] != 0
        or terminal_payload["residual_root_sha256"] != MEM0_OSS_EMPTY_ROOT_SHA256
        or terminal_payload["failed_receipts"] != []
        or _usage(terminal) != preterminal.get("usage")
        or _usage(terminal).get("extraction_calls") != 1
        or terminal.commitment_sha256 != canonical_sha256(terminal_payload)
    ):
        raise ValueError("mem0_v5_live_terminal_evidence_invalid")
    report = deepcopy(preterminal)
    final_commitments = report["commitments"]
    assert type(final_commitments) is dict
    final_commitments["terminal_cleanup_commitment_sha256"] = terminal.commitment_sha256
    report["terminal_state"] = "deleted"
    return report, terminal_payload


def _terminal_payload(terminal: TerminalView) -> dict[str, object]:
    validate = getattr(terminal, "__post_init__", None)
    if callable(validate):
        validate()
    payload_factory = getattr(terminal, "public_payload", None)
    if callable(payload_factory):
        payload = payload_factory()
    else:
        payload = {
            "terminal_state": terminal.terminal_state,
            "admission_commitment_sha256": terminal.admission_commitment_sha256,
            "seal_commitment_sha256": terminal.seal_commitment_sha256,
            "operation_root_sha256": terminal.operation_root_sha256,
            "operation_inventory_root_sha256": terminal.operation_inventory_root_sha256,
            "deleted_operation_count": terminal.deleted_operation_count,
            "residual_record_count": terminal.residual_record_count,
            "residual_root_sha256": terminal.residual_root_sha256,
            "provider_observed_extraction_calls": terminal.provider_observed_extraction_calls,
            "provider_observed_request_tokens": terminal.provider_observed_request_tokens,
            "provider_observed_response_tokens": terminal.provider_observed_response_tokens,
            "failed_receipts": list(terminal.failed_receipts),
        }
    if type(payload) is not dict or set(payload) != {
        "terminal_state",
        "admission_commitment_sha256",
        "seal_commitment_sha256",
        "operation_root_sha256",
        "operation_inventory_root_sha256",
        "deleted_operation_count",
        "residual_record_count",
        "residual_root_sha256",
        "provider_observed_extraction_calls",
        "provider_observed_request_tokens",
        "provider_observed_response_tokens",
        "failed_receipts",
    }:
        raise ValueError("mem0_v5_live_terminal_evidence_invalid")
    return payload


def _validate_preterminal_binding(
    report: dict[str, object], *, seal: SealView | None, record_count: int
) -> None:
    commitments = report.get("commitments")
    if (
        seal is None
        or type(commitments) is not dict
        or report.get("authenticated_storage_record_count") != record_count
        or commitments.get("admission_commitment_sha256") != seal.admission_commitment_sha256
        or commitments.get("seal_commitment_sha256") != seal.commitment_sha256
        or commitments.get("operation_root_sha256") != seal.operation_root_sha256
        or report.get("usage") != _usage(seal)
    ):
        raise ValueError("mem0_v5_live_recovery_binding_differs")


def _validate_success_report(
    report: dict[str, object], *, expected_base: dict[str, object], terminal: bool
) -> None:
    if type(report) is not dict or set(report) != set(expected_base) | _SUCCESS_FIELDS | (
        {"terminal_state"} if terminal else set()
    ):
        raise ValueError("mem0_v5_live_recovery_capsule_invalid")
    for key, expected in expected_base.items():
        if key in {"completed_at_utc", "commitments", "failure_code", "ok", "outcome"}:
            continue
        if report.get(key) != expected:
            raise ValueError("mem0_v5_live_recovery_binding_differs")
    try:
        completed = datetime.fromisoformat(str(report["completed_at_utc"]))
    except ValueError:
        raise ValueError("mem0_v5_live_recovery_capsule_invalid") from None
    expected_commitments = expected_base.get("commitments")
    commitments = report.get("commitments")
    terminal_key = {"terminal_cleanup_commitment_sha256"} if terminal else set()
    if (
        completed.tzinfo is None
        or completed.utcoffset() is None
        or report.get("ok") is not True
        or report.get("outcome") != "GO"
        or report.get("failure_code") is not None
        or type(expected_commitments) is not dict
        or type(commitments) is not dict
        or set(commitments) != set(expected_commitments) | _SUCCESS_COMMITMENTS | terminal_key
        or any(commitments.get(key) != value for key, value in expected_commitments.items())
        or any(not _is_sha256(commitments.get(key)) for key in _SUCCESS_COMMITMENTS | terminal_key)
        or type(report.get("authenticated_search_result_count")) is not int
        or report["authenticated_search_result_count"] < 1
        or type(report.get("authenticated_storage_record_count")) is not int
        or report["authenticated_storage_record_count"] < 1
        or not _valid_usage(report.get("usage"))
        or terminal != (report.get("terminal_state") == "deleted")
    ):
        raise ValueError("mem0_v5_live_recovery_capsule_invalid")


def _preterminal_report(report: dict[str, object]) -> dict[str, object]:
    value = deepcopy(report)
    value.pop("terminal_state", None)
    commitments = value.get("commitments")
    if type(commitments) is not dict:
        raise ValueError("mem0_v5_live_recovery_capsule_invalid")
    commitments.pop("terminal_cleanup_commitment_sha256", None)
    return value


def _valid_usage(value: object) -> bool:
    return bool(
        type(value) is dict
        and set(value) == {"prompt_tokens", "completion_tokens", "total_tokens", "extraction_calls"}
        and all(type(value[key]) is int and value[key] >= 0 for key in value)
        and value["extraction_calls"] == 1
        and value["total_tokens"] == value["prompt_tokens"] + value["completion_tokens"]
    )


def _usage(source: SealView | TerminalView) -> dict[str, int]:
    prompt = source.provider_observed_request_tokens
    completion = source.provider_observed_response_tokens
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "extraction_calls": source.provider_observed_extraction_calls,
    }


def _attach_terminal(report: dict[str, object], terminal: TerminalView) -> None:
    report["terminal_state"] = terminal.terminal_state
    report["usage"] = _usage(terminal)
    commitments = report.get("commitments")
    if type(commitments) is dict:
        commitments["terminal_cleanup_commitment_sha256"] = terminal.commitment_sha256


def _no_go(report: dict[str, object], code: str) -> dict[str, object]:
    report["ok"] = False
    report["outcome"] = "NO-GO"
    report["failure_code"] = code
    return report


class _NoGo(Exception):
    pass


def _phase(checkpoint: object) -> str | None:
    value = getattr(checkpoint, "run_phase", None)
    return getattr(value, "value", value)


def _json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError):
        raise ValueError("mem0_v5_live_json_invalid") from None


def _decode_report(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("mem0_v5_live_report_invalid") from None
    if type(value) is not dict or raw != _json_bytes(value):
        raise ValueError("mem0_v5_live_report_invalid")
    return value


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _SHA256_CHARS


def _unreachable():
    raise AssertionError("recovery capsule disappeared after durable publication")


__all__ = (
    "LiveCanaryRecoverySession",
    "RECOVERY_CAPSULE_NAME",
    "RECOVERY_CAPSULE_SCHEMA",
    "REPORT_SCHEMA",
    "base_report",
    "execute_micro_canary",
    "publish_report",
)
