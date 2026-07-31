"""Abstract managed full-comparison orchestration with terminal cleanup."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import secrets
import threading
import weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import final

from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    execution_case_manifest_sha256,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FULL_COMPARISON_COMPONENT_KINDS,
    FullComparisonRunBindings,
    create_full_comparison_evidence_issuer,
    create_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_full_scope import (
    FULL_COMPARISON_SCOPE_CANARY,
)
from infinity_context_server.memory_comparison_managed_attestation import (
    VerifiedManagedCompositionAttestation,
    _issue_verified_managed_composition_attestation_for_composition_root,
    public_managed_composition_attestation,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedCaseExecution,
    ManagedCompositeAssemblerPort,
    ManagedExecutionArtifacts,
    ManagedExecutionPort,
    ManagedIngestEvidencePort,
    ManagedPolicyLifecyclePort,
    ManagedRunCase,
    ManagedRunError,
    ManagedRunPlan,
    _digest,
    _freeze_json,
    _identifier,
    _thaw_json,
    _unique_corpora,
    _validated_execution_case_manifest,
)
from infinity_context_server.memory_comparison_managed_run_ports import (
    ManagedAttestationPort,
    ManagedClockPort,
    ManagedResetPort,
)

MANAGED_RUN_SCHEMA_VERSION = "memory-comparison-managed-run.v1"
_TOKEN = object()
_LOCK = threading.RLock()


@final
class ManagedRunOutcome:
    """Opaque terminal outcome; the public report is revalidated on every read."""

    __slots__ = ("__commitment", "__weakref__")

    def __init__(self, *, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedRunError("managed outcomes must be sealed")
        self.__commitment = commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedRunOutcome is final")

    def __repr__(self) -> str:
        return "ManagedRunOutcome(<sealed>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedRunOutcome is nonserializable")


@dataclass(frozen=True, slots=True)
class _RunState:
    bindings: FullComparisonRunBindings
    assembler: ManagedCompositeAssemblerPort
    verdict: object
    projection: MappingProxyType[str, object]
    trace: tuple[str, ...]
    case_count: int
    corpus_count: int
    secret: bytes
    commitment: str


@dataclass(frozen=True, slots=True)
class _CleanupResult:
    terminal_delete: object | None
    error: BaseException | None


_OUTCOMES: weakref.WeakKeyDictionary[ManagedRunOutcome, _RunState] = weakref.WeakKeyDictionary()


def run_managed_comparison(
    plan: ManagedRunPlan,
    *,
    reset_port: ManagedResetPort,
    attestation_port: ManagedAttestationPort,
    ingest_port: ManagedIngestEvidencePort,
    clock: ManagedClockPort,
    execution_port: ManagedExecutionPort,
    policy_port: ManagedPolicyLifecyclePort,
    assembler: ManagedCompositeAssemblerPort,
) -> ManagedRunOutcome:
    """Run the full lifecycle; terminal delete executes for every BaseException."""

    if type(plan) is not ManagedRunPlan:
        raise ManagedRunError("managed run plan type must be exact")
    _validate_ports(
        reset_port,
        attestation_port,
        ingest_port,
        clock,
        execution_port,
        policy_port,
        assembler,
    )
    case_manifest = _validated_execution_case_manifest(
        plan.cases,
        plan.case_manifest,
        benchmark=plan.profile.benchmark,
    )
    case_manifest_sha256 = execution_case_manifest_sha256(case_manifest)
    bindings = create_full_comparison_run_bindings(
        run_id=plan.run_id,
        run_nonce_commitment_sha256=plan.run_nonce_commitment_sha256,
        runtime_probe_nonce_sha256=plan.runtime_probe_nonce_sha256,
        profile=plan.profile,
        methodology=plan.methodology,
        dataset_sha256=plan.dataset_sha256,
        selection_fingerprint_sha256=plan.selection_fingerprint_sha256,
        backend_targets=plan.backend_targets,
        scope=plan.scope,
    )
    issuer = create_full_comparison_evidence_issuer(bindings)
    trace = ["bindings.create", "issuer.create"]
    managed_attestation: VerifiedManagedCompositionAttestation | None = None
    managed_commitment: str | None = None
    execution: ManagedExecutionArtifacts | None = None
    canonical_source: tuple[object, ...] | None = None
    primary_error: BaseException | None = None
    primary_traceback = None
    cleanup = _CleanupResult(None, None)

    try:
        reset_port.reset(
            run_id=bindings.run_id,
            binding_commitment_sha256=bindings.binding_commitment_sha256,
            backend_targets=_target_pairs(bindings),
        )
        trace.append("reset.complete")
        runtime_validation = attestation_port.attest(
            run_id=bindings.run_id,
            probe_nonce_sha256=bindings.runtime_probe_nonce_sha256,
            target_identity_sha256=_target_identity(bindings, "mem0"),
        )
        managed_attestation = _issue_verified_managed_composition_attestation_for_composition_root(
            bindings=bindings,
            reset_port=reset_port,
            attestation_port=attestation_port,
            ingest_port=ingest_port,
            clock=clock,
            runtime_validation=runtime_validation,
            provider_route=plan.provider_route,
        )
        if managed_attestation is None:
            raise ManagedRunError("managed attestation is missing")
        managed_report = public_managed_composition_attestation(
            managed_attestation,
            bindings=bindings,
            reset_port=reset_port,
            attestation_port=attestation_port,
            ingest_port=ingest_port,
            clock=clock,
        )
        managed_commitment = _digest(
            managed_report.get("composition_attestation_sha256"),
            "managed attestation",
        )
        trace.append("attestation.live")
        ingest_receipts = _ingest(bindings, plan.cases, ingest_port, trace)
        executions = _execute_cases(bindings, plan.cases, execution_port, trace)
        execution = execution_port.seal_execution(
            bindings=bindings,
            case_manifest=case_manifest,
            executions=executions,
            case_manifest_sha256=case_manifest_sha256,
        )
        if (
            type(execution) is not ManagedExecutionArtifacts
            or execution.case_manifest_sha256 != case_manifest_sha256
        ):
            raise ManagedRunError("execution seal differs from case manifest")
        trace.append("execution.seal")
        canonical_source = policy_port.seal_canonical_source(
            bindings=bindings,
            cases=plan.cases,
            managed_attestation=managed_attestation,
            managed_attestation_commitment_sha256=managed_commitment,
            execution=execution,
            ingest_receipts=ingest_receipts,
        )
        _validate_canonical_source(canonical_source, expected_count=len(plan.cases))
        trace.append("canonical_source.seal")
    except BaseException as exc:
        primary_error = exc
        primary_traceback = exc.__traceback__
    finally:
        cleanup = _terminal_cleanup(
            bindings,
            policy_port,
            trace,
            managed_attestation=managed_attestation,
            managed_attestation_commitment_sha256=managed_commitment,
        )

    if primary_error is not None:
        if cleanup.error is not None:
            primary_error.add_note(f"terminal cleanup also failed: {type(cleanup.error).__name__}")
        raise primary_error.with_traceback(primary_traceback)
    if cleanup.error is not None:
        raise cleanup.error
    if (
        managed_attestation is None
        or managed_commitment is None
        or execution is None
        or canonical_source is None
        or cleanup.terminal_delete is None
    ):
        raise ManagedRunError("managed lifecycle artifacts are incomplete")

    policy_validation = policy_port.aggregate_policy(
        bindings=bindings,
        managed_attestation=managed_attestation,
        managed_attestation_commitment_sha256=managed_commitment,
        canonical_source=canonical_source,
        terminal_delete=cleanup.terminal_delete,
    )
    if policy_validation is None:
        raise ManagedRunError("policy aggregate is missing")
    trace.append("policy.aggregate")
    components = assembler.assemble_components(
        bindings=bindings,
        issuer=issuer,
        managed_attestation=managed_attestation,
        execution_validation=execution.execution_validation,
        gold_blind_validation=execution.gold_blind_validation,
        policy_validation=policy_validation,
        case_manifest_sha256=execution.case_manifest_sha256,
    )
    _validate_components(components)
    trace.append("components.issue")
    verdict = assembler.seal_verdict(
        bindings=bindings,
        issuer=issuer,
        components=components,
    )
    if verdict is None:
        raise ManagedRunError("sealed verdict is missing")
    trace.append("verdict.seal")
    projection = _validated_projection(
        assembler.public_verdict(verdict),
        bindings=bindings,
    )
    trace.append("verdict.public")
    return _seal_outcome(
        bindings,
        assembler=assembler,
        verdict=verdict,
        projection=projection,
        trace=tuple(trace),
        case_count=len(plan.cases),
        corpus_count=len(_unique_corpora(plan.cases)),
    )


def public_managed_run(outcome: ManagedRunOutcome) -> dict[str, object]:
    """Return the final projection only after live verdict revalidation."""

    if type(outcome) is not ManagedRunOutcome:
        raise ManagedRunError("managed outcome type must be exact")
    with _LOCK:
        state = _OUTCOMES.get(outcome)
    if state is None:
        raise ManagedRunError("managed outcome was not sealed")
    _validate_outcome(outcome, state)
    current = _validated_projection(
        state.assembler.public_verdict(state.verdict),
        bindings=state.bindings,
    )
    if _freeze_json(current) != state.projection:
        raise ManagedRunError("managed verdict projection changed")
    report = copy.deepcopy(current)
    report["managed_run"] = {
        "schema_version": MANAGED_RUN_SCHEMA_VERSION,
        "trace": list(state.trace),
        "case_count": state.case_count,
        "unique_corpus_count": state.corpus_count,
        "terminal_delete_complete": True,
        "component_count": len(FULL_COMPARISON_COMPONENT_KINDS),
    }
    return report


def _ingest(
    bindings: FullComparisonRunBindings,
    cases: tuple[ManagedRunCase, ...],
    port: ManagedIngestEvidencePort,
    trace: list[str],
) -> tuple[object, ...]:
    receipts: list[object] = []
    corpora = _unique_corpora(cases)
    for target in bindings.backend_targets:
        for corpus_id, record in corpora:
            receipt = port.ingest(
                run_id=bindings.run_id,
                backend_role=target.backend_role,
                target_identity_sha256=target.target_identity_sha256,
                record=_thaw_json(record),
            )
            if receipt is None or any(receipt is current for current in receipts):
                raise ManagedRunError("ingest receipts must be globally distinct")
            receipts.append(receipt)
            trace.append(f"ingest:{target.backend_role}:{corpus_id}")
    if len(receipts) != len(bindings.backend_targets) * len(corpora):
        raise ManagedRunError("ingest receipt coverage differs")
    return tuple(receipts)


def _execute_cases(
    bindings: FullComparisonRunBindings,
    cases: tuple[ManagedRunCase, ...],
    port: ManagedExecutionPort,
    trace: list[str],
) -> tuple[ManagedCaseExecution, ...]:
    executions: list[ManagedCaseExecution] = []
    for target in bindings.backend_targets:
        for case in cases:
            retrieval = port.retrieve(
                bindings=bindings,
                backend_role=target.backend_role,
                target_identity_sha256=target.target_identity_sha256,
                case=case,
            )
            trace.append(f"retrieve:{target.backend_role}:{case.case_id}")
            answer = port.answer(
                bindings=bindings,
                backend_role=target.backend_role,
                target_identity_sha256=target.target_identity_sha256,
                case=case,
                retrieval_receipt=retrieval,
            )
            trace.append(f"answer:{target.backend_role}:{case.case_id}")
            judgment = port.judge(
                bindings=bindings,
                backend_role=target.backend_role,
                target_identity_sha256=target.target_identity_sha256,
                case=case,
                answer_receipt=answer,
            )
            trace.append(f"judge:{target.backend_role}:{case.case_id}")
            executions.append(
                ManagedCaseExecution(
                    target.backend_role,
                    target.target_identity_sha256,
                    case.case_id,
                    retrieval,
                    answer,
                    judgment,
                )
            )
    result = tuple(executions)
    expected_lanes = tuple(
        (target.backend_role, target.target_identity_sha256, case.case_id)
        for target in bindings.backend_targets
        for case in cases
    )
    actual_lanes = tuple(
        (item.backend_role, item.target_identity_sha256, item.case_id) for item in result
    )
    receipts = tuple(
        receipt
        for item in result
        for receipt in (item.retrieval_receipt, item.answer_receipt, item.judge_receipt)
    )
    if actual_lanes != expected_lanes or len({id(item) for item in receipts}) != 3 * len(result):
        raise ManagedRunError("execution lane coverage or receipt identity differs")
    return result


def _terminal_cleanup(
    bindings: FullComparisonRunBindings,
    port: ManagedPolicyLifecyclePort,
    trace: list[str],
    *,
    managed_attestation: VerifiedManagedCompositionAttestation | None,
    managed_attestation_commitment_sha256: str | None,
) -> _CleanupResult:
    receipts: list[object] = []
    failures: list[BaseException] = []
    for pass_index in (1, 2):
        for target in bindings.backend_targets:
            trace.append(f"delete:{target.backend_role}:{pass_index}")
            try:
                receipt = port.terminal_delete(
                    bindings=bindings,
                    backend_role=target.backend_role,
                    target_identity_sha256=target.target_identity_sha256,
                    pass_index=pass_index,
                )
                if receipt is None:
                    raise ManagedRunError("terminal delete receipt is missing")
                if any(receipt is current for current in receipts):
                    raise ManagedRunError("terminal delete receipts must be globally distinct")
                receipts.append(receipt)
            except BaseException as exc:
                failures.append(exc)
    if failures:
        return _CleanupResult(None, failures[0])
    expected_count = 2 * len(bindings.backend_targets)
    if len(receipts) != expected_count:
        return _CleanupResult(None, ManagedRunError("terminal delete receipt coverage differs"))
    attestation_missing = managed_attestation is None
    commitment_missing = managed_attestation_commitment_sha256 is None
    if attestation_missing and commitment_missing:
        return _CleanupResult(None, None)
    if attestation_missing != commitment_missing:
        return _CleanupResult(
            None,
            ManagedRunError("terminal cleanup attestation pair is incomplete"),
        )
    try:
        assert managed_attestation is not None
        assert managed_attestation_commitment_sha256 is not None
        terminal = port.seal_terminal_delete(
            bindings=bindings,
            managed_attestation=managed_attestation,
            managed_attestation_commitment_sha256=managed_attestation_commitment_sha256,
            receipts=tuple(receipts),
        )
        if terminal is None:
            raise ManagedRunError("terminal delete seal is missing")
        trace.append("delete.seal")
        return _CleanupResult(terminal, None)
    except BaseException as exc:
        return _CleanupResult(None, exc)


def _validate_canonical_source(value: object, *, expected_count: int) -> None:
    if (
        type(value) is not tuple
        or len(value) != expected_count
        or any(item is None for item in value)
        or len({id(item) for item in value}) != len(value)
    ):
        raise ManagedRunError("canonical/source evidence coverage differs from cases")


def _validate_components(value: object) -> None:
    if (
        type(value) is not tuple
        or len(value) != len(FULL_COMPARISON_COMPONENT_KINDS)
        or any(item is None for item in value)
        or len({id(item) for item in value}) != len(value)
    ):
        raise ManagedRunError("component set must contain nine distinct live slots")


def _validated_projection(
    value: object,
    *,
    bindings: FullComparisonRunBindings,
) -> dict[str, object]:
    if type(value) is not dict or not _exact_json(value):
        raise ManagedRunError("verdict projection must be an exact JSON mapping")
    if (
        value.get("run_id") != bindings.run_id
        or value.get("profile_id") != bindings.profile_id
        or value.get("scope") != bindings.scope
        or type(value.get("publishable")) is not bool
        or type(value.get("eligible")) is not bool
    ):
        raise ManagedRunError("verdict projection binding differs")
    components = value.get("components")
    if (
        type(components) is not list
        or len(components) != len(FULL_COMPARISON_COMPONENT_KINDS)
        or tuple(item.get("component_kind") if type(item) is dict else None for item in components)
        != FULL_COMPARISON_COMPONENT_KINDS
    ):
        raise ManagedRunError("verdict projection component set differs")
    if bindings.scope == FULL_COMPARISON_SCOPE_CANARY and value["publishable"] is not False:
        raise ManagedRunError("canary verdict cannot be publishable")
    return copy.deepcopy(value)


def _seal_outcome(
    bindings: FullComparisonRunBindings,
    *,
    assembler: ManagedCompositeAssemblerPort,
    verdict: object,
    projection: dict[str, object],
    trace: tuple[str, ...],
    case_count: int,
    corpus_count: int,
) -> ManagedRunOutcome:
    secret = secrets.token_bytes(32)
    body = {
        "binding_commitment_sha256": bindings.binding_commitment_sha256,
        "projection_sha256": _json_sha256(projection),
        "trace": list(trace),
        "case_count": case_count,
        "corpus_count": corpus_count,
        "verdict_identity": id(verdict),
        "assembler_identity": id(assembler),
    }
    commitment = hmac.new(secret, _canonical_json(body), hashlib.sha256).hexdigest()
    outcome = ManagedRunOutcome(commitment=commitment, _token=_TOKEN)
    frozen = _freeze_json(projection)
    if type(frozen) is not MappingProxyType:
        raise ManagedRunError("verdict projection root changed")
    with _LOCK:
        _OUTCOMES[outcome] = _RunState(
            bindings,
            assembler,
            verdict,
            frozen,
            trace,
            case_count,
            corpus_count,
            secret,
            commitment,
        )
    return outcome


def _validate_outcome(outcome: ManagedRunOutcome, state: _RunState) -> None:
    try:
        current = outcome._ManagedRunOutcome__commitment
    except (AttributeError, TypeError):
        raise ManagedRunError("managed outcome integrity failed") from None
    body = {
        "binding_commitment_sha256": state.bindings.binding_commitment_sha256,
        "projection_sha256": _json_sha256(_thaw_json(state.projection)),
        "trace": list(state.trace),
        "case_count": state.case_count,
        "corpus_count": state.corpus_count,
        "verdict_identity": id(state.verdict),
        "assembler_identity": id(state.assembler),
    }
    expected = hmac.new(state.secret, _canonical_json(body), hashlib.sha256).hexdigest()
    if (
        type(current) is not str
        or not hmac.compare_digest(current, state.commitment)
        or not hmac.compare_digest(expected, state.commitment)
    ):
        raise ManagedRunError("managed outcome integrity failed")


def _validate_ports(*ports: object) -> None:
    required = (
        ("reset", ("reset",)),
        ("attestation", ("attest",)),
        ("ingest", ("ingest",)),
        ("clock", ("now",)),
        ("execution", ("retrieve", "answer", "judge", "seal_execution")),
        (
            "policy",
            (
                "seal_canonical_source",
                "terminal_delete",
                "seal_terminal_delete",
                "aggregate_policy",
            ),
        ),
        ("assembler", ("assemble_components", "seal_verdict", "public_verdict")),
    )
    if len({id(item) for item in ports}) != len(ports):
        raise ManagedRunError("managed orchestration ports must be distinct")
    for port, (role, operations) in zip(ports, required, strict=True):
        try:
            adapter_id = port.adapter_id
            implementation_sha256 = port.implementation_sha256
        except Exception:
            raise ManagedRunError(f"{role} port provenance is unavailable") from None
        _identifier(adapter_id, f"{role} adapter_id")
        _digest(implementation_sha256, f"{role} implementation")
        if any(not callable(getattr(port, name, None)) for name in operations):
            raise ManagedRunError(f"{role} port operation is unavailable")


def _target_pairs(
    bindings: FullComparisonRunBindings,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (item.backend_role, item.target_identity_sha256) for item in bindings.backend_targets
    )


def _target_identity(bindings: FullComparisonRunBindings, role: str) -> str:
    values = tuple(
        item.target_identity_sha256
        for item in bindings.backend_targets
        if item.backend_role == role
    )
    if len(values) != 1:
        raise ManagedRunError(f"managed run requires one {role} target")
    return values[0]


def _exact_json(value: object, *, depth: int = 0) -> bool:
    try:
        _freeze_json(value, depth=depth)
    except ManagedRunError:
        return False
    return True


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


__all__ = (
    "MANAGED_RUN_SCHEMA_VERSION",
    "ManagedCaseExecution",
    "ManagedCompositeAssemblerPort",
    "ManagedExecutionArtifacts",
    "ManagedExecutionPort",
    "ManagedPolicyLifecyclePort",
    "ManagedRunCase",
    "ManagedRunError",
    "ManagedRunOutcome",
    "ManagedRunPlan",
    "public_managed_run",
    "run_managed_comparison",
)
