"""Concrete managed composition root for the sealed full-comparison verdict."""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass
from typing import cast, final

from infinity_context_server.memory_comparison_full_execution_validation import (
    VerifiedFullExecutionValidation,
    public_full_execution_validation_report,
)
from infinity_context_server.memory_comparison_full_policy_component_validation import (
    VerifiedFullPolicyComponentValidation,
    public_full_policy_component_validation,
)
from infinity_context_server.memory_comparison_full_run_components import (
    _digest_value,
    _validate_execution_aggregate_report,
    _validate_policy_aggregate_report,
    _validate_runtime_aggregate_report,
    issue_execution_component_evidence_set,
    issue_gold_blind_component_evidence,
    issue_policy_component_evidence_set,
    issue_runtime_component_evidence_from_managed_attestation,
    live_component_status,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FULL_COMPARISON_COMPONENT_KINDS,
    FullComparisonComponentEvidence,
    FullComparisonEvidenceError,
    FullComparisonEvidenceIssuer,
    FullComparisonPolicyBlocker,
    FullComparisonRunBindings,
    _component_state,
    _issuer_state,
    _validate_bindings,
    issue_full_comparison_run_evidence,
)
from infinity_context_server.memory_comparison_full_verdict import (
    FullComparisonVerdict,
    public_full_comparison_verdict,
    verify_full_comparison_run,
)
from infinity_context_server.memory_comparison_gold_blind_run_proof import (
    VerifiedGoldBlindExecutionValidation,
    verified_gold_blind_execution_report,
)
from infinity_context_server.memory_comparison_managed_attestation import (
    VerifiedManagedCompositionAttestation,
    public_managed_composition_attestation,
)
from infinity_context_server.memory_comparison_managed_run_ports import (
    ManagedAttestationPort,
    ManagedClockPort,
    ManagedIngestPort,
    ManagedResetPort,
)


class ManagedCompositeAssemblerError(FullComparisonEvidenceError):
    """Raised when managed composite assembly cannot remain trustworthy."""


@dataclass(frozen=True, slots=True)
class _PortSnapshot:
    role: str
    port: object
    adapter_id: str
    implementation_sha256: str
    operation_identity: int


@dataclass(slots=True)
class _AssemblyRecord:
    bindings: FullComparisonRunBindings
    issuer: FullComparisonEvidenceIssuer
    phase: str
    components: tuple[FullComparisonComponentEvidence, ...] | None = None
    verdict: FullComparisonVerdict | None = None


@final
class ManagedFullComparisonAssembler:
    """Assemble the nine nominal slots once for one exact managed run."""

    __slots__ = (
        "__adapter_id",
        "__assembler_provenance",
        "__attestation_port",
        "__clock",
        "__implementation_sha256",
        "__ingest_port",
        "__lock",
        "__port_snapshots",
        "__records",
        "__reset_port",
    )

    def __init__(
        self,
        *,
        adapter_id: str,
        implementation_sha256: str,
        reset_port: ManagedResetPort,
        attestation_port: ManagedAttestationPort,
        ingest_port: ManagedIngestPort,
        clock: ManagedClockPort,
    ) -> None:
        trusted_adapter_id = _adapter_id(adapter_id, "assembler adapter_id")
        trusted_implementation = _digest(
            implementation_sha256,
            "assembler implementation",
        )
        ports = (reset_port, attestation_port, ingest_port, clock)
        self.__adapter_id = trusted_adapter_id
        self.__implementation_sha256 = trusted_implementation
        self.__assembler_provenance = (
            trusted_adapter_id,
            trusted_implementation,
        )
        self.__port_snapshots = _port_snapshots(ports)
        self.__reset_port = reset_port
        self.__attestation_port = attestation_port
        self.__ingest_port = ingest_port
        self.__clock = clock
        self.__lock = threading.RLock()
        self.__records: weakref.WeakKeyDictionary[FullComparisonEvidenceIssuer, _AssemblyRecord] = (
            weakref.WeakKeyDictionary()
        )

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedFullComparisonAssembler is final")

    @property
    def adapter_id(self) -> str:
        """Return the stable composition adapter identifier."""

        return self.__adapter_id

    @property
    def implementation_sha256(self) -> str:
        """Return the pinned composition implementation digest."""

        return self.__implementation_sha256

    def assemble_components(
        self,
        *,
        bindings: FullComparisonRunBindings,
        issuer: FullComparisonEvidenceIssuer,
        managed_attestation: VerifiedManagedCompositionAttestation,
        execution_validation: object,
        gold_blind_validation: object,
        policy_validation: object,
        case_manifest_sha256: str,
    ) -> tuple[FullComparisonComponentEvidence, ...]:
        """Preflight every producer, then consume and mint all nine slots once."""

        trusted = self._assembly_identity(bindings, issuer)
        expected_manifest = _digest(case_manifest_sha256, "case manifest")
        self._reserve(issuer, trusted)
        try:
            self._preflight(
                bindings=trusted,
                managed_attestation=managed_attestation,
                execution_validation=execution_validation,
                gold_blind_validation=gold_blind_validation,
                policy_validation=policy_validation,
                case_manifest_sha256=expected_manifest,
            )
        except BaseException as exc:
            self._rollback_preflight(issuer)
            if isinstance(exc, Exception):
                raise ManagedCompositeAssemblerError("managed composite preflight failed") from None
            raise

        self._begin_consumption(issuer)
        try:
            runtime = issue_runtime_component_evidence_from_managed_attestation(
                issuer,
                managed_attestation,
                reset_port=self.__reset_port,
                attestation_port=self.__attestation_port,
                ingest_port=self.__ingest_port,
                clock=self.__clock,
            )
            execution = issue_execution_component_evidence_set(
                issuer,
                execution_validation,
                case_manifest_sha256=expected_manifest,
            )
            gold = issue_gold_blind_component_evidence(issuer, gold_blind_validation)
            policy = issue_policy_component_evidence_set(issuer, policy_validation)
            components = (
                execution[0],
                runtime,
                execution[1],
                execution[2],
                gold,
                execution[3],
                *policy,
            )
            _require_exact_component_order(components, issuer)
        except BaseException as exc:
            self._finish_assembly(issuer, components=None)
            if isinstance(exc, Exception):
                raise ManagedCompositeAssemblerError("managed composite assembly failed") from None
            raise
        self._finish_assembly(issuer, components=components)
        return components

    def seal_verdict(
        self,
        *,
        bindings: FullComparisonRunBindings,
        components: tuple[object, ...],
        issuer: FullComparisonEvidenceIssuer,
        policy_blockers: tuple[FullComparisonPolicyBlocker, ...] = (),
    ) -> FullComparisonVerdict:
        """Seal exactly one verdict from this assembler's completed slot tuple."""

        trusted = self._assembly_identity(bindings, issuer)
        if type(components) is not tuple:
            raise ManagedCompositeAssemblerError("components must be an exact tuple")
        if type(policy_blockers) is not tuple:
            raise ManagedCompositeAssemblerError("policy blockers must be an exact tuple")
        trusted_components = _require_exact_component_order(components, issuer)
        self._begin_verdict(issuer, trusted, trusted_components)
        try:
            evidence = issue_full_comparison_run_evidence(
                trusted,
                trusted_components,
                issuer,
                policy_blockers=policy_blockers,
            )
            verdict = verify_full_comparison_run(evidence)
        except BaseException as exc:
            self._finish_verdict(issuer, verdict=None)
            if isinstance(exc, Exception):
                raise ManagedCompositeAssemblerError("managed verdict sealing failed") from None
            raise
        self._finish_verdict(issuer, verdict=verdict)
        return verdict

    def public_verdict(self, verdict: object) -> dict[str, object]:
        """Project one assembler-sealed verdict after fresh live revalidation."""

        self._require_ports_stable()
        if type(verdict) is not FullComparisonVerdict:
            raise ManagedCompositeAssemblerError("verdict type must be exact")
        with self.__lock:
            owned = any(
                record.phase == "sealed" and record.verdict is verdict
                for record in self.__records.values()
            )
        if not owned:
            raise ManagedCompositeAssemblerError("verdict was not sealed by this assembler")
        return public_full_comparison_verdict(verdict)

    def _assembly_identity(
        self,
        bindings: FullComparisonRunBindings,
        issuer: FullComparisonEvidenceIssuer,
    ) -> FullComparisonRunBindings:
        self._require_ports_stable()
        if type(bindings) is not FullComparisonRunBindings:
            raise ManagedCompositeAssemblerError("run bindings type must be exact")
        if type(issuer) is not FullComparisonEvidenceIssuer:
            raise ManagedCompositeAssemblerError("evidence issuer type must be exact")
        try:
            trusted = _validate_bindings(bindings)
            issuer_state = _issuer_state(issuer)
        except Exception:
            raise ManagedCompositeAssemblerError("managed assembly identity is invalid") from None
        if issuer_state.bindings is not trusted:
            raise ManagedCompositeAssemblerError("issuer and run bindings differ")
        return trusted

    def _preflight(
        self,
        *,
        bindings: FullComparisonRunBindings,
        managed_attestation: VerifiedManagedCompositionAttestation,
        execution_validation: object,
        gold_blind_validation: object,
        policy_validation: object,
        case_manifest_sha256: str,
    ) -> None:
        if type(managed_attestation) is not VerifiedManagedCompositionAttestation:
            raise ManagedCompositeAssemblerError("managed validation type must be exact")
        if type(execution_validation) is not VerifiedFullExecutionValidation:
            raise ManagedCompositeAssemblerError("execution validation type must be exact")
        if type(gold_blind_validation) is not VerifiedGoldBlindExecutionValidation:
            raise ManagedCompositeAssemblerError("gold validation type must be exact")
        if type(policy_validation) is not VerifiedFullPolicyComponentValidation:
            raise ManagedCompositeAssemblerError("policy validation type must be exact")
        self._require_ports_stable()
        managed_report = public_managed_composition_attestation(
            managed_attestation,
            bindings=bindings,
            reset_port=self.__reset_port,
            attestation_port=self.__attestation_port,
            ingest_port=self.__ingest_port,
            clock=self.__clock,
        )
        managed_commitment = _validate_runtime_aggregate_report(managed_report, bindings)
        execution_report = public_full_execution_validation_report(execution_validation)
        observed_manifest = _validate_execution_aggregate_report(execution_report, bindings)
        if observed_manifest != case_manifest_sha256:
            raise ManagedCompositeAssemblerError("execution case manifest differs")
        case_count = execution_report.get("case_count")
        if type(case_count) is not int or case_count < 1:
            raise ManagedCompositeAssemblerError("execution case count is invalid")
        policy_report = public_full_policy_component_validation(policy_validation)
        _validate_policy_aggregate_report(
            policy_report,
            bindings,
            managed_commitment=managed_commitment,
        )
        manifest_item_count = policy_report.get("manifest_item_count")
        if (
            type(manifest_item_count) is not int
            or manifest_item_count < 1
            or manifest_item_count != case_count
        ):
            raise ManagedCompositeAssemblerError("policy manifest coverage differs")
        status, blocker = live_component_status("gold_blind", gold_blind_validation, bindings)
        if status != "verified" or blocker is not None:
            raise ManagedCompositeAssemblerError("gold validation binding is invalid")
        gold_report = verified_gold_blind_execution_report(gold_blind_validation)
        if gold_report.get("comparison_binding_commitment_sha256") != (
            bindings.binding_commitment_sha256
        ):
            raise ManagedCompositeAssemblerError("gold validation binding differs")
        expected_gold_count = gold_report.get("expected_case_count")
        if (
            type(expected_gold_count) is not int
            or expected_gold_count < 1
            or expected_gold_count != case_count * len(bindings.backend_targets)
        ):
            raise ManagedCompositeAssemblerError("gold validation lane coverage differs")

    def _reserve(
        self,
        issuer: FullComparisonEvidenceIssuer,
        bindings: FullComparisonRunBindings,
    ) -> None:
        with self.__lock:
            if issuer in self.__records:
                raise ManagedCompositeAssemblerError("managed assembly was already reserved")
            self.__records[issuer] = _AssemblyRecord(bindings, issuer, "preflighting")

    def _rollback_preflight(self, issuer: FullComparisonEvidenceIssuer) -> None:
        with self.__lock:
            record = self.__records.get(issuer)
            if record is not None and record.phase == "preflighting":
                del self.__records[issuer]

    def _begin_consumption(self, issuer: FullComparisonEvidenceIssuer) -> None:
        with self.__lock:
            record = self.__records.get(issuer)
            if record is None or record.phase != "preflighting":
                raise ManagedCompositeAssemblerError("managed assembly reservation changed")
            record.phase = "consuming"

    def _finish_assembly(
        self,
        issuer: FullComparisonEvidenceIssuer,
        *,
        components: tuple[FullComparisonComponentEvidence, ...] | None,
    ) -> None:
        with self.__lock:
            record = self.__records.get(issuer)
            if record is None or record.phase != "consuming":
                raise ManagedCompositeAssemblerError("managed assembly reservation changed")
            record.components = components
            record.phase = "assembled" if components is not None else "terminal"

    def _begin_verdict(
        self,
        issuer: FullComparisonEvidenceIssuer,
        bindings: FullComparisonRunBindings,
        components: tuple[FullComparisonComponentEvidence, ...],
    ) -> None:
        with self.__lock:
            record = self.__records.get(issuer)
            if (
                record is None
                or record.phase != "assembled"
                or record.bindings is not bindings
                or record.components is not components
            ):
                raise ManagedCompositeAssemblerError("managed assembly is not sealable")
            record.phase = "sealing"

    def _finish_verdict(
        self,
        issuer: FullComparisonEvidenceIssuer,
        *,
        verdict: FullComparisonVerdict | None,
    ) -> None:
        with self.__lock:
            record = self.__records.get(issuer)
            if record is None or record.phase != "sealing":
                raise ManagedCompositeAssemblerError("managed verdict reservation changed")
            record.verdict = verdict
            record.phase = "sealed" if verdict is not None else "terminal"

    def _require_ports_stable(self) -> None:
        if (
            self.__adapter_id,
            self.__implementation_sha256,
        ) != self.__assembler_provenance:
            raise ManagedCompositeAssemblerError("assembler provenance changed")
        current = _port_snapshots(
            (
                self.__reset_port,
                self.__attestation_port,
                self.__ingest_port,
                self.__clock,
            )
        )
        if current != self.__port_snapshots:
            raise ManagedCompositeAssemblerError("managed adapter provenance changed")


def _port_snapshots(ports: tuple[object, ...]) -> tuple[_PortSnapshot, ...]:
    if len(ports) != 4 or any(port is None for port in ports):
        raise ManagedCompositeAssemblerError("all managed ports must be concrete")
    if any(left is right for index, left in enumerate(ports) for right in ports[index + 1 :]):
        raise ManagedCompositeAssemblerError("managed ports must be distinct objects")
    snapshots: list[_PortSnapshot] = []
    for role, operation_name, port in zip(
        ("reset", "attestation", "ingest", "clock"),
        ("reset", "attest", "ingest", "now"),
        ports,
        strict=True,
    ):
        try:
            adapter_id = port.adapter_id
            implementation = port.implementation_sha256
            operation = getattr(port, operation_name)
        except Exception:
            raise ManagedCompositeAssemblerError(
                f"managed {role} adapter provenance is unavailable"
            ) from None
        if (
            type(adapter_id) is not str
            or not adapter_id
            or adapter_id != adapter_id.strip()
            or len(adapter_id) > 200
        ):
            raise ManagedCompositeAssemblerError(f"managed {role} adapter_id is invalid")
        _digest(implementation, f"managed {role} implementation")
        if not callable(operation):
            raise ManagedCompositeAssemblerError(f"managed {role} operation is unavailable")
        target = getattr(operation, "__func__", operation)
        snapshots.append(_PortSnapshot(role, port, adapter_id, implementation, id(target)))
    return tuple(snapshots)


def _require_exact_component_order(
    components: tuple[object, ...],
    issuer: FullComparisonEvidenceIssuer,
) -> tuple[FullComparisonComponentEvidence, ...]:
    if type(components) is not tuple or len(components) != len(FULL_COMPARISON_COMPONENT_KINDS):
        raise ManagedCompositeAssemblerError("full component tuple shape is invalid")
    kinds: list[str] = []
    for component in components:
        if type(component) is not FullComparisonComponentEvidence:
            raise ManagedCompositeAssemblerError("component evidence type must be exact")
        state = _component_state(component)
        if state.issuer is not issuer:
            raise ManagedCompositeAssemblerError("component belongs to another issuer")
        kinds.append(state.component_kind)
    if tuple(kinds) != FULL_COMPARISON_COMPONENT_KINDS:
        raise ManagedCompositeAssemblerError("full component order differs")
    return cast(tuple[FullComparisonComponentEvidence, ...], components)


def _digest(value: object, name: str) -> str:
    try:
        return _digest_value(value, name)
    except Exception:
        raise ManagedCompositeAssemblerError(f"{name} must be SHA-256") from None


def _adapter_id(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 200
        or not value[0].isalnum()
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
            for character in value
        )
    ):
        raise ManagedCompositeAssemblerError(f"{name} is invalid")
    return value


__all__ = (
    "ManagedCompositeAssemblerError",
    "ManagedFullComparisonAssembler",
)
