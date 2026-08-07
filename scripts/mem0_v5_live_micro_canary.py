"""Run one bounded live Mem0 v5 extraction with authenticated evidence."""

# ruff: noqa: E402 - direct CLI execution bootstraps repository package roots.

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import socket
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _repository_path in (
    _PROJECT_ROOT,
    _PROJECT_ROOT / "packages" / "infinity_context_core",
    _PROJECT_ROOT / "packages" / "infinity_context_server",
):
    if str(_repository_path) not in sys.path:
        sys.path.insert(0, str(_repository_path))

from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    canonical_sha256,
)

from scripts.mem0_v5_live_container_copy_contract import (
    validate_private_credentials,
    verify_container_copy_authority,
)
from scripts.mem0_v5_live_project_one_unit import OneUnitProjection, project_one_unit

_IMAGE_ID_PREFIX = "sha256:"
_REPORT_SCHEMA = "managed-mem0-v5-live-micro-canary.v1"
_AUTHORITY_SCHEMA = "managed-mem0-v5-live-runtime-authority.v1"
_SHA256_CHARS = frozenset("0123456789abcdef")
_MAX_AUTHORITY_BYTES = 64 * 1024
_REVIEWED_NODE_SHA256 = "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"
_MAX_PUBLIC_IMMUTABLE_BYTES = 32 * 1024 * 1024
_REVIEWED_NODE_SIZE_BYTES = 123_438_592
_RUNTIME_TRANSPORT_ORIGIN = b"http://127.0.0.1:8891"


class SealView(Protocol):
    admission_commitment_sha256: str
    commitment_sha256: str
    operation_root_sha256: str
    provider_observed_extraction_calls: int
    provider_observed_request_tokens: int
    provider_observed_response_tokens: int


class SearchView(Protocol):
    records: tuple[object, ...]
    result_root_sha256: str
    evidence_commitment_sha256: str


class TerminalView(Protocol):
    terminal_state: str
    commitment_sha256: str
    provider_observed_extraction_calls: int
    provider_observed_request_tokens: int
    provider_observed_response_tokens: int


class CoordinatorView(Protocol):
    @property
    def budget(self) -> object: ...

    @property
    def storage_observations(self) -> tuple[object, ...]: ...

    @property
    def terminal_evidence(self) -> TerminalView: ...

    def admit(self, *, authority: object, request: object, budget_policy: object) -> None: ...

    def dispatch_pending(self) -> SealView: ...

    def restore(self, *, authority: object, request: object, budget_policy: object) -> object: ...

    def seal_restored_completed(self) -> SealView: ...

    def search_evidence(self, *, corpus_id: str, query: str, limit: int) -> SearchView: ...

    def cleanup(self) -> TerminalView: ...

    def abort(self) -> TerminalView: ...


class CompositionView(Protocol):
    authority: object
    request: object
    coordinator: CoordinatorView


CompositionFactory = Callable[[], CompositionView]


@dataclass(frozen=True, slots=True)
class _ProductionPublicContract:
    request: Mem0OssAdmissionRequest
    state_paths: object
    credential_paths: object
    runtime_receipt_boundary: object
    trusted_runtime_binding: object
    receipt_authority: object
    dispatch_guard: object


@dataclass(frozen=True, slots=True)
class LiveRuntimeAuthority:
    model: str
    reasoning_effort: str
    service_tier: str
    runtime_source_revision: str
    runtime_source_sha256: str
    runtime_base_sha256: str
    route_binding_sha256: str
    base_instructions_sha256: str
    account_binding_hmac_sha256: str
    response_format_type: str
    response_format_sha256: str
    response_schema_sha256: str
    requested_output_tokens: int

    @classmethod
    def parse(cls, raw: bytes) -> LiveRuntimeAuthority:
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("mem0_v5_live_runtime_authority_invalid") from None
        keys = {
            "schema_version",
            "model",
            "reasoning_effort",
            "service_tier",
            "runtime_source_revision",
            "runtime_source_sha256",
            "runtime_base_sha256",
            "route_binding_sha256",
            "base_instructions_sha256",
            "account_binding_hmac_sha256",
            "response_format_type",
            "response_format_sha256",
            "response_schema_sha256",
            "requested_output_tokens",
        }
        if type(payload) is not dict or set(payload) != keys:
            raise ValueError("mem0_v5_live_runtime_authority_invalid")
        if payload.pop("schema_version") != _AUTHORITY_SCHEMA:
            raise ValueError("mem0_v5_live_runtime_authority_invalid")
        try:
            value = cls(**payload)
        except TypeError:
            raise ValueError("mem0_v5_live_runtime_authority_invalid") from None
        value.require_valid()
        return value

    def require_valid(self) -> None:
        text = (
            self.model,
            self.reasoning_effort,
            self.service_tier,
            self.runtime_source_revision,
            self.response_format_type,
        )
        digests = (
            self.runtime_source_sha256,
            self.runtime_base_sha256,
            self.route_binding_sha256,
            self.base_instructions_sha256,
            self.account_binding_hmac_sha256,
            self.response_format_sha256,
            self.response_schema_sha256,
        )
        if (
            any(
                type(item) is not str or not item or item != item.strip() or len(item) > 512
                for item in text
            )
            or any(not _is_sha256(item) for item in digests)
            or self.requested_output_tokens != 4096
        ):
            raise ValueError("mem0_v5_live_runtime_authority_invalid")


@dataclass(frozen=True, slots=True)
class MicroCanaryInputs:
    projection: OneUnitProjection
    runtime: LiveRuntimeAuthority
    restore_existing: bool
    orphan_dispatch_claim: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.projection) is not OneUnitProjection
            or type(self.runtime) is not LiveRuntimeAuthority
            or type(self.restore_existing) is not bool
            or type(self.orphan_dispatch_claim) is not bool
            or self.projection.response_format_sha256 != self.runtime.response_format_sha256
            or self.projection.response_schema_sha256 != self.runtime.response_schema_sha256
            or self.projection.requested_output_tokens != self.runtime.requested_output_tokens
        ):
            raise ValueError("mem0_v5_live_inputs_invalid")


def execute_micro_canary(
    *,
    inputs: MicroCanaryInputs,
    composition_factory: CompositionFactory,
) -> dict[str, object]:
    """Execute at most one dispatch; every started lifecycle ends terminal."""

    base = _base_report(inputs)
    if inputs.orphan_dispatch_claim:
        return _no_go(base, "orphan_dispatch_claim")
    composition: CompositionView | None = None
    terminal: TerminalView | None = None
    seal: SealView | None = None
    search: SearchView | None = None
    record_count = 0
    started = False
    succeeded = False
    failure = "live_micro_canary_failed"
    try:
        composition = composition_factory()
        coordinator = composition.coordinator
        if inputs.restore_existing:
            started = True
            checkpoint = coordinator.restore(
                authority=composition.authority,
                request=composition.request,
                budget_policy=ManagedMem0V5BudgetPolicy(maximum_total_call_count=5),
            )
            phase = getattr(checkpoint, "run_phase", None)
            if getattr(phase, "value", phase) == "terminal":
                terminal = coordinator.terminal_evidence
                failure = "run_already_terminal"
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
                recovery = composition_factory()
                composition = recovery
                coordinator = recovery.coordinator
                started = True
                try:
                    coordinator.restore(
                        authority=recovery.authority,
                        request=recovery.request,
                        budget_policy=ManagedMem0V5BudgetPolicy(maximum_total_call_count=5),
                    )
                    seal = coordinator.seal_restored_completed()
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
        search = coordinator.search_evidence(
            corpus_id=inputs.projection.cases[0].corpus_id,
            query=inputs.projection.search_query,
            limit=10,
        )
        if not search.records:
            failure = "authenticated_search_empty"
            raise _NoGo
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
    if not succeeded or seal is None or search is None or terminal is None:
        report = _no_go(base, failure)
        if terminal is not None:
            _attach_terminal(report, terminal)
        return report
    if terminal.terminal_state != "deleted":
        report = _no_go(base, "cleanup_terminal_state_invalid")
        _attach_terminal(report, terminal)
        return report
    usage = _usage(seal)
    if usage["extraction_calls"] != 1 or usage != _usage(terminal):
        report = _no_go(base, "terminal_usage_binding_invalid")
        _attach_terminal(report, terminal)
        return report
    base.update(
        {
            "outcome": "GO",
            "ok": True,
            "failure_code": None,
            "usage": usage,
            "commitments": {
                **base["commitments"],
                "admission_commitment_sha256": seal.admission_commitment_sha256,
                "seal_commitment_sha256": seal.commitment_sha256,
                "operation_root_sha256": seal.operation_root_sha256,
                "search_result_root_sha256": search.result_root_sha256,
                "search_evidence_commitment_sha256": search.evidence_commitment_sha256,
                "terminal_cleanup_commitment_sha256": terminal.commitment_sha256,
            },
            "authenticated_search_result_count": len(search.records),
            "authenticated_storage_record_count": record_count,
            "terminal_state": terminal.terminal_state,
        }
    )
    return base


class _NoGo(Exception):
    pass


def _base_report(inputs: MicroCanaryInputs) -> dict[str, object]:
    projection = inputs.projection
    runtime = inputs.runtime
    return {
        "schema_version": _REPORT_SCHEMA,
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
            "account_binding_hmac_sha256": runtime.account_binding_hmac_sha256,
            "runtime_source_sha256": runtime.runtime_source_sha256,
            "runtime_base_sha256": runtime.runtime_base_sha256,
            "route_binding_sha256": runtime.route_binding_sha256,
        },
    }


def _no_go(report: dict[str, object], code: str) -> dict[str, object]:
    report["ok"] = False
    report["outcome"] = "NO-GO"
    report["failure_code"] = code
    return report


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
    commitments = report["commitments"]
    assert type(commitments) is dict
    commitments["terminal_cleanup_commitment_sha256"] = terminal.commitment_sha256


def _production_factory(
    *,
    args: argparse.Namespace,
    projection: OneUnitProjection,
    contract: _ProductionPublicContract,
) -> CompositionFactory:
    from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
        compose_managed_mem0_v5,
    )

    def compose() -> CompositionView:
        return compose_managed_mem0_v5(
            cases=projection.cases,
            current_date=args.current_date,
            request=contract.request,
            origin=f"http://127.0.0.1:{args.adapter_port}",
            timeout_seconds=args.timeout_seconds,
            state_paths=contract.state_paths,
            credential_paths=contract.credential_paths,
            runtime_receipt_boundary=contract.runtime_receipt_boundary,
            trusted_runtime_binding=contract.trusted_runtime_binding,
            receipt_authority=contract.receipt_authority,
            dispatch_guard=contract.dispatch_guard,
        )

    return compose


def _build_public_contract(
    *, args: argparse.Namespace, projection: OneUnitProjection, runtime: LiveRuntimeAuthority
) -> _ProductionPublicContract:
    phase_c_root = args.phase_c_package_root
    if str(phase_c_root) not in sys.path:
        sys.path.insert(0, str(phase_c_root))
    from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
        ManagedMem0V5StatePaths,
        preflight_managed_mem0_v5,
    )
    from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
        ManagedMem0V5CredentialPaths,
    )
    from infinity_context_server.memory_comparison_managed_mem0_v5_dispatch_guard import (
        create_managed_mem0_v5_single_dispatch_guard,
    )
    from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
        Mem0V5ObservedExtractionReceiptAuthority,
    )
    from phase_c_canary.receipt import NodePublicReceiptVerifier
    from phase_c_canary.runtime_binding import RuntimeBindingComposition
    from phase_c_canary.runtime_receipt_v2 import RuntimeReceiptV2Boundary

    binding = RuntimeBindingComposition.compose_phase_c_canary().issue()
    if (
        binding.runtime_source_sha256 != runtime.runtime_source_sha256
        or binding.route_binding_sha256 != runtime.route_binding_sha256
    ):
        raise ValueError("mem0_v5_live_runtime_binding_differs")
    request = Mem0OssAdmissionRequest(
        run_id=args.run_id,
        route_sha256=runtime.route_binding_sha256,
        credential_binding_sha256=args.evidence_key_sha256,
        model=runtime.model,
        reasoning_effort=runtime.reasoning_effort,
        service_tier=runtime.service_tier,
        runtime_source_revision=runtime.runtime_source_revision,
        runtime_source_sha256=runtime.runtime_source_sha256,
        runtime_base_sha256=runtime.runtime_base_sha256,
        expected_operation_count=1,
    )
    admission = Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=projection.authority.ingestion_manifest_sha256,
        ingestion_root_sha256=projection.authority.ingestion_root_sha256,
        ingestion_unit_count=1,
    )
    unit = projection.authority.units[0]
    operation_id = canonical_sha256(
        {
            "admission_commitment_sha256": admission.commitment_sha256,
            "unit_index": 0,
            "unit_identity_sha256": unit.unit_identity_sha256,
        }
    )
    observed = Mem0V5ObservedExtractionReceiptAuthority(
        admission_commitment_sha256=admission.commitment_sha256,
        operation_id_sha256=operation_id,
        unit_identity_sha256=unit.unit_identity_sha256,
        unit_sha256=unit.unit_sha256,
        scope_sha256=unit.scope_sha256,
        sequence=0,
        request_body_sha256=projection.request_body_sha256,
        model=runtime.model,
        reasoning_effort=runtime.reasoning_effort,
        service_tier=runtime.service_tier,
        base_instructions_sha256=runtime.base_instructions_sha256,
        runtime_source_sha256=runtime.runtime_source_sha256,
        route_binding_sha256=runtime.route_binding_sha256,
        account_binding_hmac_sha256=runtime.account_binding_hmac_sha256,
        response_format_type=runtime.response_format_type,
        response_format_sha256=runtime.response_format_sha256,
        response_schema_sha256=runtime.response_schema_sha256,
        node_executable_path=str(args.node_executable),
        node_executable_sha256=args.node_executable_sha256,
        requested_output_tokens=4096,
    )
    credential_paths = ManagedMem0V5CredentialPaths(
        bearer_token=args.ingress_bearer_file,
        evidence_key=args.evidence_key_file,
        receipt_secret=args.receipt_secret_file,
        checkpoint_signing_key=args.checkpoint_signing_key_file,
        checkpoint_head_key=args.checkpoint_head_key_file,
    )
    state_paths = ManagedMem0V5StatePaths(
        checkpoint=args.state_root / "checkpoint.json",
        local_checkpoint_head=args.state_root / "checkpoint-head.sqlite3",
    )
    boundary = RuntimeReceiptV2Boundary(
        NodePublicReceiptVerifier(args.runtime_repo, node_executable=args.node_executable)
    )
    guard = create_managed_mem0_v5_single_dispatch_guard(args.dispatch_journal)
    preflight = preflight_managed_mem0_v5(
        cases=projection.cases,
        current_date=args.current_date,
        request=request,
        origin=f"http://127.0.0.1:{args.adapter_port}",
        timeout_seconds=args.timeout_seconds,
        state_paths=state_paths,
        credential_paths=credential_paths,
        runtime_receipt_boundary=boundary,
        trusted_runtime_binding=binding,
        receipt_authority=observed,
        dispatch_guard=guard,
    )
    if preflight.authority != projection.authority or preflight.admission != admission:
        raise ValueError("mem0_v5_live_production_preflight_differs")
    return _ProductionPublicContract(
        request=request,
        state_paths=state_paths,
        credential_paths=credential_paths,
        runtime_receipt_boundary=boundary,
        trusted_runtime_binding=binding,
        receipt_authority=observed,
        dispatch_guard=guard,
    )


def _preflight(
    args: argparse.Namespace,
) -> tuple[OneUnitProjection, LiveRuntimeAuthority, _ProductionPublicContract]:
    roots = (args.input_root, args.state_root, args.secret_root, args.report_root)
    if len({path.resolve(strict=False) for path in roots}) != len(roots):
        raise ValueError("mem0_v5_live_private_roots_overlap")
    for root in roots:
        _require_private_directory(root)
    if (
        not args.dispatch_journal.is_absolute()
        or args.dispatch_journal.parent.resolve(strict=True) != args.state_root.resolve(strict=True)
        or args.dispatch_journal.name in {"", ".", ".."}
    ):
        raise ValueError("mem0_v5_live_dispatch_journal_path_invalid")
    for path in (
        args.case_file,
        args.runtime_authority_file,
        args.input_root / "manifest.json",
        args.input_root / "one-unit-authority.json",
        args.phase_c_package_root,
        args.runtime_repo,
        args.runtime_artifact_manifest,
        args.node_executable,
        args.container_copy_authority_file,
    ):
        if not path.is_absolute():
            raise ValueError("mem0_v5_live_path_invalid")
    if args.runtime_artifact_manifest != args.runtime_repo.parent / "artifact-manifest.json":
        raise ValueError("mem0_v5_live_runtime_artifact_path_invalid")
    _verify_public_immutable(
        args.runtime_artifact_manifest,
        args.runtime_artifact_manifest_sha256,
        executable=False,
    )
    _verify_reviewed_node(args.node_executable, args.node_executable_sha256)
    for directory in (args.phase_c_package_root, args.runtime_repo):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("mem0_v5_live_runtime_path_invalid")
    _image_id(args.adapter_image_id)
    _image_id(args.qdrant_image_id)
    if (
        type(args.adapter_port) is not int
        or type(args.qdrant_port) is not int
        or args.adapter_port != 19091
        or args.qdrant_port != 6334
        or type(args.timeout_seconds) not in {int, float}
        or isinstance(args.timeout_seconds, bool)
        or not math.isfinite(args.timeout_seconds)
        or not 0.01 <= args.timeout_seconds <= 120.0
    ):
        raise ValueError("mem0_v5_live_port_invalid")
    raw_authority = _read_immutable(
        args.runtime_authority_file,
        args.runtime_authority_sha256,
        maximum_bytes=_MAX_AUTHORITY_BYTES,
    )
    runtime = LiveRuntimeAuthority.parse(raw_authority)
    from mem0_oss_adapter_v5.extraction_contract import build_extraction_request

    projection = project_one_unit(
        case_file=args.case_file,
        expected_case_sha256=args.case_sha256,
        current_date=args.current_date,
        extraction_projector=build_extraction_request,
    )
    _require_materialized_projection(args, projection)
    contract = _build_public_contract(args=args, projection=projection, runtime=runtime)
    secret_digests = validate_private_credentials(
        secret_root=args.secret_root,
        runner_paths={
            "ingress-bearer": args.ingress_bearer_file,
            "result-hmac": args.evidence_key_file,
            "runtime-receipt-secret": args.receipt_secret_file,
            "checkpoint-signing-key": args.checkpoint_signing_key_file,
            "checkpoint-head-key": args.checkpoint_head_key_file,
        },
        evidence_key_sha256=args.evidence_key_sha256,
        read_private=_read_private_file,
    )
    verify_container_copy_authority(
        path=args.container_copy_authority_file,
        expected_sha256=args.container_copy_authority_sha256,
        input_manifest_sha256=args.input_manifest_sha256,
        secret_digests=secret_digests,
        maximum_bytes=_MAX_AUTHORITY_BYTES,
    )
    return projection, runtime, contract


def _require_materialized_projection(
    args: argparse.Namespace, projection: OneUnitProjection
) -> None:
    manifest = _read_immutable(
        args.input_root / "manifest.json",
        args.input_manifest_sha256,
        maximum_bytes=32 * 1024 * 1024,
    )
    authority = _read_immutable(
        args.input_root / "one-unit-authority.json",
        args.one_unit_authority_sha256,
        maximum_bytes=_MAX_AUTHORITY_BYTES,
    )
    expected_manifest = json.dumps(
        projection.authority.private_payload(), sort_keys=True, separators=(",", ":")
    ).encode()
    expected_authority = json.dumps(
        projection.public_payload(), sort_keys=True, separators=(",", ":")
    ).encode()
    if manifest != expected_manifest or authority != expected_authority:
        raise ValueError("mem0_v5_live_materialized_projection_differs")


def _preflight_report(
    args: argparse.Namespace, projection: OneUnitProjection, runtime: LiveRuntimeAuthority
) -> dict[str, object]:
    inputs = MicroCanaryInputs(
        projection=projection,
        runtime=runtime,
        restore_existing=(args.state_root / "checkpoint.json").exists(),
        orphan_dispatch_claim=(
            args.dispatch_journal.exists() and not (args.state_root / "checkpoint.json").exists()
        ),
    )
    report = _base_report(inputs)
    adapter_ready = _tcp_probe(args.adapter_port, args.timeout_seconds)
    qdrant_ready = _tcp_probe(args.qdrant_port, args.timeout_seconds)
    safe = adapter_ready and qdrant_ready and not inputs.orphan_dispatch_claim
    report.update(
        {
            "preflight_only": True,
            "ok": safe,
            "outcome": "GO" if safe else "NO-GO",
            "failure_code": None if safe else "tcp_or_state_preflight_failed",
            "tcp_readiness": {"adapter": adapter_ready, "qdrant": qdrant_ready},
            "images": {
                "adapter_image_id": args.adapter_image_id,
                "qdrant_image_id": args.qdrant_image_id,
            },
        }
    )
    commitments = report["commitments"]
    assert type(commitments) is dict
    commitments.update(
        {
            "node_executable_sha256": args.node_executable_sha256,
            "runtime_artifact_manifest_sha256": (args.runtime_artifact_manifest_sha256),
        }
    )
    return report


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case-file", required=True, type=Path)
    parser.add_argument("--case-sha256", required=True)
    parser.add_argument("--current-date", required=True)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--input-manifest-sha256", required=True)
    parser.add_argument("--one-unit-authority-sha256", required=True)
    parser.add_argument("--runtime-authority-file", required=True, type=Path)
    parser.add_argument("--runtime-authority-sha256", required=True)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--secret-root", required=True, type=Path)
    parser.add_argument("--report-root", required=True, type=Path)
    parser.add_argument("--report-file", required=True, type=Path)
    parser.add_argument("--dispatch-journal", required=True, type=Path)
    parser.add_argument("--ingress-bearer-file", required=True, type=Path)
    parser.add_argument("--evidence-key-file", required=True, type=Path)
    parser.add_argument("--evidence-key-sha256", required=True)
    parser.add_argument("--receipt-secret-file", required=True, type=Path)
    parser.add_argument("--checkpoint-signing-key-file", required=True, type=Path)
    parser.add_argument("--checkpoint-head-key-file", required=True, type=Path)
    parser.add_argument("--phase-c-package-root", required=True, type=Path)
    parser.add_argument("--runtime-repo", required=True, type=Path)
    parser.add_argument("--runtime-artifact-manifest", required=True, type=Path)
    parser.add_argument("--runtime-artifact-manifest-sha256", required=True)
    parser.add_argument("--node-executable", required=True, type=Path)
    parser.add_argument("--node-executable-sha256", required=True)
    parser.add_argument("--container-copy-authority-file", required=True, type=Path)
    parser.add_argument("--container-copy-authority-sha256", required=True)
    parser.add_argument("--adapter-image-id", required=True)
    parser.add_argument("--qdrant-image-id", required=True)
    parser.add_argument("--adapter-port", required=True, type=int)
    parser.add_argument("--qdrant-port", required=True, type=int)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report: dict[str, object]
    try:
        projection, runtime, contract = _preflight(args)
        if args.preflight_only:
            report = _preflight_report(args, projection, runtime)
        else:
            if not _tcp_probe(args.adapter_port, args.timeout_seconds) or not _tcp_probe(
                args.qdrant_port, args.timeout_seconds
            ):
                raise ValueError("mem0_v5_live_tcp_readiness_failed")
            inputs = MicroCanaryInputs(
                projection=projection,
                runtime=runtime,
                restore_existing=(args.state_root / "checkpoint.json").exists(),
                orphan_dispatch_claim=(
                    args.dispatch_journal.exists()
                    and not (args.state_root / "checkpoint.json").exists()
                ),
            )
            report = execute_micro_canary(
                inputs=inputs,
                composition_factory=_production_factory(
                    args=args, projection=projection, contract=contract
                ),
            )
        report["images"] = {
            "adapter_image_id": args.adapter_image_id,
            "qdrant_image_id": args.qdrant_image_id,
        }
        commitments = report.get("commitments")
        if type(commitments) is dict:
            commitments.update(
                {
                    "node_executable_sha256": args.node_executable_sha256,
                    "runtime_artifact_manifest_sha256": (args.runtime_artifact_manifest_sha256),
                    "container_copy_authority_sha256": (args.container_copy_authority_sha256),
                    "evidence_key_sha256": args.evidence_key_sha256,
                }
            )
    except Exception:
        report = {
            "schema_version": _REPORT_SCHEMA,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "ok": False,
            "outcome": "NO-GO",
            "failure_code": "live_micro_canary_preflight_failed",
        }
    try:
        _write_report(args.report_file, args.report_root, report)
    except Exception:
        return 3
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("ok") is True else 2


def _write_report(path: Path, root: Path, report: dict[str, object]) -> None:
    if not path.is_absolute() or path.parent.resolve(strict=False) != root.resolve(strict=True):
        raise ValueError("mem0_v5_live_report_path_invalid")
    encoded = json.dumps(
        report, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(encoded)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise OSError("short write")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent = os.open(
        root,
        os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def _tcp_probe(port: int, timeout: float) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=min(timeout, 5.0)):
            return True
    except OSError:
        return False


def _read_private_file(path: Path, *, parent: Path) -> bytes:
    if not path.is_absolute() or path.parent.resolve(strict=True) != parent.resolve(strict=True):
        raise ValueError("mem0_v5_live_private_file_invalid")
    raw = _read_snapshot(
        path,
        maximum_bytes=4096,
        allowed_modes={0o600},
        allowed_owners={os.geteuid()},
        code="mem0_v5_live_private_file_invalid",
    )
    if path.name == "runtime-transport-origin":
        if raw != _RUNTIME_TRANSPORT_ORIGIN:
            raise ValueError("mem0_v5_live_private_file_invalid")
    elif len(raw) < 32:
        raise ValueError("mem0_v5_live_private_file_invalid")
    return raw


def _require_private_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError:
        raise ValueError("mem0_v5_live_private_root_invalid") from None
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ValueError("mem0_v5_live_private_root_invalid")


def _read_immutable(path: Path, expected: str, *, maximum_bytes: int) -> bytes:
    if not path.is_absolute() or not _is_sha256(expected):
        raise ValueError("mem0_v5_live_immutable_file_invalid")
    raw = _read_snapshot(
        path,
        maximum_bytes=maximum_bytes,
        allowed_modes={0o400, 0o440, 0o444},
        allowed_owners={os.geteuid()},
        code="mem0_v5_live_immutable_file_invalid",
    )
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("mem0_v5_live_immutable_file_invalid")
    return raw


def _image_id(value: str) -> None:
    digest = value.removeprefix(_IMAGE_ID_PREFIX)
    if not value.startswith(_IMAGE_ID_PREFIX) or not _is_sha256(digest):
        raise ValueError("mem0_v5_live_image_id_invalid")


def _verify_public_immutable(
    path: Path,
    expected: str,
    *,
    executable: bool,
    maximum_bytes: int = _MAX_PUBLIC_IMMUTABLE_BYTES,
) -> None:
    if not path.is_absolute() or not _is_sha256(expected):
        raise ValueError("mem0_v5_live_public_immutable_invalid")
    allowed = {0o500, 0o550, 0o555, 0o700, 0o750, 0o755} if executable else {0o400, 0o440, 0o444}
    raw = _read_snapshot(
        path,
        maximum_bytes=maximum_bytes,
        allowed_modes=allowed,
        allowed_owners={0, os.geteuid()},
        code="mem0_v5_live_public_immutable_invalid",
    )
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("mem0_v5_live_public_immutable_invalid")


def _verify_reviewed_node(path: Path, expected: str) -> None:
    try:
        canonical = path.resolve(strict=True)
    except OSError:
        raise ValueError("mem0_v5_live_node_authority_invalid") from None
    if expected != _REVIEWED_NODE_SHA256 or canonical != path:
        raise ValueError("mem0_v5_live_node_authority_invalid")
    try:
        _verify_public_immutable(
            path,
            expected,
            executable=True,
            maximum_bytes=_REVIEWED_NODE_SIZE_BYTES,
        )
    except ValueError:
        raise ValueError("mem0_v5_live_node_authority_invalid") from None


def _read_snapshot(
    path: Path,
    *,
    maximum_bytes: int,
    allowed_modes: set[int],
    allowed_owners: set[int],
    code: str,
) -> bytes:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        current = os.lstat(path)
        identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid not in allowed_owners
            or stat.S_IMODE(opened.st_mode) not in allowed_modes
            or opened.st_nlink != 1
            or not 1 <= opened.st_size <= maximum_bytes
            or identity != (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
        ):
            raise ValueError
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65_536, maximum_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum_bytes:
                raise ValueError
        final = os.fstat(descriptor)
        if identity != (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns):
            raise ValueError
        return b"".join(chunks)
    except (OSError, ValueError):
        raise ValueError(code) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _SHA256_CHARS


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "LiveRuntimeAuthority",
    "MicroCanaryInputs",
    "execute_micro_canary",
    "main",
)
