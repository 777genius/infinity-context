"""Nominal live component adapters for full-run evidence."""

from __future__ import annotations

import hashlib
import threading
import weakref
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, final

from infinity_context_server.memory_comparison_clean_state import (
    VerifiedCleanStateValidation,
    public_clean_state_validation,
)
from infinity_context_server.memory_comparison_full_profiles import (
    FullComparisonProfile,
    frozen_full_comparison_profile,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_component_sets import (
    issue_execution_component_evidence_set,
    issue_policy_component_evidence_set,
    issue_runtime_component_evidence_from_managed_attestation,
)
from infinity_context_server.memory_comparison_gold_blind_run_proof import (
    VerifiedGoldBlindExecutionValidation,
    verified_gold_blind_execution_report,
)
from infinity_context_server.memory_comparison_locomo_transport import (
    RunScopedLocomoTransportEvidenceKey,
)
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    VerifiedMem0RuntimeAttestationValidation,
    mem0_runtime_attestation_validation_is_publishable,
    public_mem0_runtime_attestation_validation,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_session_identity_contract import (
    RunScopedSessionHmacKey,
)

if TYPE_CHECKING:
    from infinity_context_server.memory_comparison_full_run_evidence import (
        FullComparisonComponentEvidence,
        FullComparisonEvidenceIssuer,
        FullComparisonRunBindings,
    )


_MAX_RUNTIME_CLOCK_SKEW_SECONDS = 1.0
_AGGREGATE_TOKEN = object()
_AGGREGATE_LOCK = threading.RLock()
_EXECUTION_KINDS = ("provider", "session", "clean_state", "transport")
_POLICY_KINDS = ("delete", "canonical", "source")


@dataclass(slots=True)
class _IssuerAggregateState:
    runtime_phase: str = "open"
    execution_phase: str = "open"
    policy_phase: str = "open"
    managed_attestation_commitment_sha256: str | None = None
    execution_case_manifest_sha256: str | None = None


@final
class _AggregateComponentValidation:
    __slots__ = (
        "baseline_report_sha256",
        "binding_commitment_sha256",
        "bindings",
        "capability",
        "context",
        "kinds",
        "managed_attestation_commitment_sha256",
        "source",
    )

    def __init__(
        self,
        *,
        source: str,
        kinds: tuple[str, ...],
        capability: object,
        context: tuple[object, ...],
        bindings: FullComparisonRunBindings,
        binding_commitment_sha256: str,
        managed_attestation_commitment_sha256: str,
        baseline_report_sha256: str,
        _token: object,
    ) -> None:
        if _token is not _AGGREGATE_TOKEN:
            raise _evidence_error("aggregate component validations must be issued")
        self.source = source
        self.kinds = kinds
        self.capability = capability
        self.context = context
        self.bindings = bindings
        self.binding_commitment_sha256 = binding_commitment_sha256
        self.managed_attestation_commitment_sha256 = managed_attestation_commitment_sha256
        self.baseline_report_sha256 = baseline_report_sha256

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("_AggregateComponentValidation is final")


_ISSUER_AGGREGATES: weakref.WeakKeyDictionary[
    FullComparisonEvidenceIssuer, _IssuerAggregateState
] = weakref.WeakKeyDictionary()


def issue_provider_component_evidence(
    issuer: FullComparisonEvidenceIssuer,
    validation: ProviderRouteAttestation,
) -> FullComparisonComponentEvidence:
    """Bind typed route evidence; call completeness remains fail-closed."""

    from infinity_context_server.memory_comparison_full_run_evidence import _issue_component

    return _issue_component(issuer, "provider", validation, ProviderRouteAttestation)


def issue_runtime_component_evidence(
    issuer: FullComparisonEvidenceIssuer,
    validation: VerifiedMem0RuntimeAttestationValidation,
) -> FullComparisonComponentEvidence:
    """Bind the exact runner-produced runtime validation capability."""

    from infinity_context_server.memory_comparison_full_run_evidence import _issue_component

    _require_verified_component_binding(issuer, "runtime", validation)
    return _issue_component(issuer, "runtime", validation, VerifiedMem0RuntimeAttestationValidation)


def issue_session_component_evidence(
    issuer: FullComparisonEvidenceIssuer,
    validation: RunScopedSessionHmacKey,
) -> FullComparisonComponentEvidence:
    """Bind the live session verifier; completeness remains fail-closed."""

    from infinity_context_server.memory_comparison_full_run_evidence import _issue_component

    return _issue_component(issuer, "session", validation, RunScopedSessionHmacKey)


def issue_clean_state_component_evidence(
    issuer: FullComparisonEvidenceIssuer,
    validation: VerifiedCleanStateValidation,
) -> FullComparisonComponentEvidence:
    """Bind typed clean-state validation; live-key replay remains fail-closed."""

    from infinity_context_server.memory_comparison_full_run_evidence import _issue_component

    return _issue_component(issuer, "clean_state", validation, VerifiedCleanStateValidation)


def issue_gold_blind_component_evidence(
    issuer: FullComparisonEvidenceIssuer,
    validation: VerifiedGoldBlindExecutionValidation,
) -> FullComparisonComponentEvidence:
    """Bind a live gold-blind dispatch capability."""

    from infinity_context_server.memory_comparison_full_run_evidence import _issue_component

    _require_verified_component_binding(issuer, "gold_blind", validation)
    return _issue_component(issuer, "gold_blind", validation, VerifiedGoldBlindExecutionValidation)


def issue_transport_component_evidence(
    issuer: FullComparisonEvidenceIssuer,
    validation: RunScopedLocomoTransportEvidenceKey,
) -> FullComparisonComponentEvidence:
    """Bind the live transport verifier; corpus coverage remains fail-closed."""

    from infinity_context_server.memory_comparison_full_run_evidence import _issue_component

    return _issue_component(issuer, "transport", validation, RunScopedLocomoTransportEvidenceKey)


def live_component_commitment(component_kind: str, validation: object) -> str:
    """Commit exact typed live state so later mutation is detected."""

    if type(validation) is _AggregateComponentValidation:
        payload: object = _aggregate_live_payload(component_kind, validation)
    elif component_kind == "provider" and type(validation) is ProviderRouteAttestation:
        payload: object = validation.public_payload()
    elif (
        component_kind == "runtime" and type(validation) is VerifiedMem0RuntimeAttestationValidation
    ):
        payload = public_mem0_runtime_attestation_validation(validation)
    elif component_kind == "session" and type(validation) is RunScopedSessionHmacKey:
        if not validation._is_sealed():
            raise _evidence_error("session capability is invalid")
        payload = {"run_id": validation._run_id, "sealed": True}
    elif component_kind == "clean_state" and type(validation) is VerifiedCleanStateValidation:
        payload = public_clean_state_validation(validation)
    elif (
        component_kind == "gold_blind" and type(validation) is VerifiedGoldBlindExecutionValidation
    ):
        try:
            payload = verified_gold_blind_execution_report(validation)
        except Exception:
            raise _evidence_error("gold-blind capability is invalid") from None
    elif component_kind == "transport" and type(validation) is RunScopedLocomoTransportEvidenceKey:
        if not validation._is_sealed():
            raise _evidence_error("transport capability is invalid")
        payload = {"run_id": validation._run_id, "sealed": True}
    else:
        raise _evidence_error(f"{component_kind} validation type must be exact")
    return _json_sha256(payload)


def live_component_status(
    component_kind: str,
    validation: object,
    bindings: FullComparisonRunBindings,
) -> tuple[str, str | None]:
    """Revalidate one exact capability without upgrading incomplete slices."""

    if type(validation) is _AggregateComponentValidation:
        return _aggregate_live_status(component_kind, validation, bindings)
    if component_kind == "runtime":
        if type(validation) is not VerifiedMem0RuntimeAttestationValidation:
            return "invalid", "runtime_component_invalid"
        profile = _profile(bindings.profile_id)
        public = public_mem0_runtime_attestation_validation(validation)
        attestation = public.get("attestation")
        run_hash = attestation.get("run_id_sha256") if type(attestation) is dict else None
        valid = bool(
            run_hash == hashlib.sha256(bindings.run_id.encode()).hexdigest()
            and attestation.get("probe_nonce_sha256") == bindings.runtime_probe_nonce_sha256
            and attestation.get("target_identity_sha256") == _mem0_target_identity(bindings)
            and _runtime_validation_is_current(public)
            and mem0_runtime_attestation_validation_is_publishable(
                validation,
                required_runtime_mode=profile.required_mem0_runtime_mode,
            )
        )
        return ("verified", None) if valid else ("invalid", "runtime_component_invalid")
    if component_kind == "gold_blind":
        if type(validation) is not VerifiedGoldBlindExecutionValidation:
            return "invalid", "gold_blind_component_invalid"
        try:
            report = verified_gold_blind_execution_report(validation)
        except Exception:
            return "invalid", "gold_blind_component_invalid"
        count = report.get("expected_case_count")
        valid = bool(
            type(count) is int
            and count > 0
            and report.get("run_id") == bindings.run_id
            and report.get("comparison_binding_commitment_sha256")
            == bindings.binding_commitment_sha256
            and count == report.get("retrieval_dispatch_count")
            and count == report.get("answer_dispatch_count")
            and count == report.get("judge_dispatch_count")
        )
        return ("verified", None) if valid else ("invalid", "gold_blind_component_invalid")
    expected_type = {
        "provider": ProviderRouteAttestation,
        "session": RunScopedSessionHmacKey,
        "clean_state": VerifiedCleanStateValidation,
        "transport": RunScopedLocomoTransportEvidenceKey,
    }.get(component_kind)
    if expected_type is not None and type(validation) is expected_type:
        blocker = {
            "provider": "provider_call_validation_unwired",
            "session": "session_completeness_unwired",
            "clean_state": "clean_state_live_revalidation_unwired",
            "transport": "transport_coverage_unwired",
        }[component_kind]
        return "unwired", blocker
    return "invalid", f"{component_kind}_component_invalid"


def _require_verified_component_binding(
    issuer: FullComparisonEvidenceIssuer,
    component_kind: str,
    validation: object,
) -> None:
    from infinity_context_server.memory_comparison_full_run_evidence import _issuer_state

    status, blocker = live_component_status(
        component_kind,
        validation,
        _issuer_state(issuer).bindings,
    )
    if status != "verified" or blocker is not None:
        raise _evidence_error(f"{component_kind} validation binding is invalid")


def _reserve_aggregate_set(
    issuer: FullComparisonEvidenceIssuer,
    source: str,
    *,
    require_runtime: bool,
) -> tuple[FullComparisonRunBindings, str]:
    from infinity_context_server.memory_comparison_full_run_evidence import _issuer_state

    issuer_state = _issuer_state(issuer)
    phase_name = f"{source}_phase"
    with _AGGREGATE_LOCK:
        state = _ISSUER_AGGREGATES.get(issuer)
        if state is None:
            state = _IssuerAggregateState()
            _ISSUER_AGGREGATES[issuer] = state
        if getattr(state, phase_name) != "open":
            raise _evidence_error(f"{source} aggregate slot set was already reserved")
        managed = state.managed_attestation_commitment_sha256
        if require_runtime and (state.runtime_phase != "issued" or managed is None):
            raise _evidence_error("managed runtime aggregate must be issued first")
        setattr(state, phase_name, "prevalidating")
    return issuer_state.bindings, managed or ""


def _rollback_prevalidation(
    issuer: FullComparisonEvidenceIssuer,
    source: str,
) -> None:
    phase_name = f"{source}_phase"
    with _AGGREGATE_LOCK:
        state = _ISSUER_AGGREGATES.get(issuer)
        if state is not None and getattr(state, phase_name) == "prevalidating":
            setattr(state, phase_name, "open")


def _begin_aggregate_consumption(
    issuer: FullComparisonEvidenceIssuer,
    source: str,
) -> None:
    phase_name = f"{source}_phase"
    with _AGGREGATE_LOCK:
        state = _ISSUER_AGGREGATES.get(issuer)
        if state is None or getattr(state, phase_name) != "prevalidating":
            raise _evidence_error(f"{source} aggregate reservation changed")
        setattr(state, phase_name, "consuming")


def _finish_aggregate_set(
    issuer: FullComparisonEvidenceIssuer,
    source: str,
    *,
    success: bool,
    managed_commitment: str | None = None,
    execution_case_manifest: str | None = None,
) -> None:
    phase_name = f"{source}_phase"
    with _AGGREGATE_LOCK:
        state = _ISSUER_AGGREGATES.get(issuer)
        if state is None or getattr(state, phase_name) != "consuming":
            raise _evidence_error(f"{source} aggregate reservation changed")
        setattr(state, phase_name, "issued" if success else "terminal")
        if success and source == "runtime":
            state.managed_attestation_commitment_sha256 = _digest_value(
                managed_commitment,
                "managed attestation commitment",
            )
        if success and source == "execution":
            state.execution_case_manifest_sha256 = _digest_value(
                execution_case_manifest,
                "execution case manifest",
            )


def _issued_execution_case_manifest(
    issuer: FullComparisonEvidenceIssuer,
    capability: object,
) -> str | None:
    if not _is_managed_http_policy_validation(capability):
        return None
    with _AGGREGATE_LOCK:
        state = _ISSUER_AGGREGATES.get(issuer)
        if (
            state is None
            or state.execution_phase != "issued"
            or state.execution_case_manifest_sha256 is None
        ):
            raise _evidence_error(
                "managed HTTP policy requires issued execution aggregate"
            )
        return state.execution_case_manifest_sha256


def _aggregate_wrapper(
    *,
    source: str,
    kinds: tuple[str, ...],
    capability: object,
    context: tuple[object, ...],
    bindings: FullComparisonRunBindings,
    managed_commitment: str,
    report: dict[str, object],
) -> _AggregateComponentValidation:
    return _AggregateComponentValidation(
        source=source,
        kinds=kinds,
        capability=capability,
        context=context,
        bindings=bindings,
        binding_commitment_sha256=bindings.binding_commitment_sha256,
        managed_attestation_commitment_sha256=managed_commitment,
        baseline_report_sha256=_json_sha256(report),
        _token=_AGGREGATE_TOKEN,
    )


def _mint_component_set(
    issuer: FullComparisonEvidenceIssuer,
    validation: _AggregateComponentValidation,
    kinds: tuple[str, ...],
) -> tuple[FullComparisonComponentEvidence, ...]:
    from infinity_context_server import memory_comparison_full_run_evidence as evidence_module

    components: list[FullComparisonComponentEvidence] = []
    try:
        for kind in kinds:
            components.append(
                evidence_module._issue_component(
                    issuer,
                    kind,
                    validation,
                    _AggregateComponentValidation,
                )
            )
    except BaseException:
        with evidence_module._LOCK:
            minted = tuple(
                component
                for component, state in evidence_module._COMPONENTS.items()
                if state.issuer is issuer and state.live_validation is validation
            )
            for component in minted:
                evidence_module._COMPONENTS.pop(component, None)
        raise
    return tuple(components)


def _aggregate_live_payload(
    component_kind: str,
    validation: _AggregateComponentValidation,
) -> dict[str, object]:
    if component_kind not in validation.kinds:
        raise _evidence_error(f"{component_kind} aggregate slot is invalid")
    report = _current_aggregate_report(validation)
    _validate_current_aggregate_report(validation, report)
    return {
        "source": validation.source,
        "component_kind": component_kind,
        "binding_commitment_sha256": validation.binding_commitment_sha256,
        "managed_attestation_commitment_sha256": (validation.managed_attestation_commitment_sha256),
        "producer_report": report,
    }


def _aggregate_live_status(
    component_kind: str,
    validation: _AggregateComponentValidation,
    bindings: FullComparisonRunBindings,
) -> tuple[str, str | None]:
    blocker = f"{component_kind}_component_invalid"
    if validation.bindings is not bindings or component_kind not in validation.kinds:
        return "invalid", blocker
    try:
        report = _current_aggregate_report(validation)
        _validate_current_aggregate_report(validation, report)
    except Exception:
        return "invalid", blocker
    if _json_sha256(report) != validation.baseline_report_sha256:
        return "invalid", blocker
    return "verified", None


def _current_aggregate_report(
    validation: _AggregateComponentValidation,
) -> dict[str, object]:
    if validation.source == "runtime":
        from infinity_context_server.memory_comparison_managed_attestation import (
            public_managed_composition_attestation,
        )

        reset, attestation, ingest, clock = validation.context
        return public_managed_composition_attestation(
            validation.capability,
            bindings=validation.bindings,
            reset_port=reset,
            attestation_port=attestation,
            ingest_port=ingest,
            clock=clock,
        )
    if validation.source == "execution":
        from infinity_context_server.memory_comparison_full_execution_validation import (
            public_full_execution_validation_report,
        )

        return public_full_execution_validation_report(validation.capability)
    if validation.source == "policy":
        from infinity_context_server.memory_comparison_full_run_component_sets import (
            _public_policy_component_validation,
        )

        return _public_policy_component_validation(validation.capability)
    raise _evidence_error("aggregate component source is invalid")


def _validate_current_aggregate_report(
    validation: _AggregateComponentValidation,
    report: dict[str, object],
) -> None:
    if validation.source == "runtime":
        current = _validate_runtime_aggregate_report(report, validation.bindings)
        if current != validation.managed_attestation_commitment_sha256:
            raise _evidence_error("managed attestation commitment changed")
        return
    if validation.source == "execution":
        _validate_execution_aggregate_report(report, validation.bindings)
        return
    if validation.source == "policy":
        _validate_policy_aggregate_report(
            report,
            validation.bindings,
            managed_commitment=validation.managed_attestation_commitment_sha256,
            capability=validation.capability,
            execution_case_manifest_sha256=(
                validation.context[0] if len(validation.context) == 1 else None
            ),
        )
        return
    raise _evidence_error("aggregate component source is invalid")


def _validate_runtime_aggregate_report(
    report: dict[str, object],
    bindings: FullComparisonRunBindings,
) -> str:
    trusted = _exact_report(report, "runtime aggregate report")
    if (
        trusted.get("binding_commitment_sha256") != bindings.binding_commitment_sha256
        or trusted.get("component_only") is not True
        or trusted.get("composite_consume_required") is not True
        or trusted.get("externally_authentic") is not False
    ):
        raise _evidence_error("runtime aggregate binding is invalid")
    return _digest_value(
        trusted.get("composition_attestation_sha256"),
        "managed attestation commitment",
    )


def _validate_execution_aggregate_report(
    report: dict[str, object],
    bindings: FullComparisonRunBindings,
) -> str:
    trusted = _exact_report(report, "execution aggregate report")
    if (
        trusted.get("comparison_commitment_sha256") != bindings.binding_commitment_sha256
        or trusted.get("run_id") != bindings.run_id
        or trusted.get("profile_id") != bindings.profile_id
        or trusted.get("dataset_sha256") != bindings.dataset_sha256
        or trusted.get("selection_sha256") != bindings.selection_fingerprint_sha256
        or trusted.get("scope") != bindings.scope
        or trusted.get("component_only") is not True
        or trusted.get("externally_authentic") is not False
        or trusted.get("composite_wiring_required") is not True
        or trusted.get("admission_from_public_mapping") is not False
    ):
        raise _evidence_error("execution aggregate binding is invalid")
    return _digest_value(trusted.get("case_manifest_sha256"), "case manifest")


def _validate_policy_aggregate_report(
    report: dict[str, object],
    bindings: FullComparisonRunBindings,
    *,
    managed_commitment: str,
    capability: object | None = None,
    execution_case_manifest_sha256: str | None = None,
) -> str:
    if _is_managed_http_policy_validation(capability):
        return _validate_managed_http_policy_aggregate_report(
            report,
            bindings,
            managed_commitment=managed_commitment,
            execution_case_manifest_sha256=execution_case_manifest_sha256,
        )
    trusted = _exact_report(report, "policy aggregate report")
    roles = tuple(target.backend_role for target in bindings.backend_targets)
    if (
        trusted.get("run_id") != bindings.run_id
        or trusted.get("profile_id") != bindings.profile_id
        or trusted.get("infinity_backend_id") != roles[0]
        or trusted.get("mem0_backend_id") != roles[1]
        or trusted.get("managed_attestation_commitment_sha256") != managed_commitment
        or trusted.get("status") != "verified"
        or trusted.get("delete_consumed_last") is not True
        or trusted.get("all_components_consumed") is not True
        or trusted.get("admission_from_public_json") is not False
    ):
        raise _evidence_error("policy aggregate binding is invalid")
    return _digest_value(
        trusted.get("manifest_commitment_sha256"),
        "policy manifest commitment",
    )


def _is_managed_http_policy_validation(value: object) -> bool:
    from infinity_context_server.memory_comparison_managed_http_policy_validation import (
        VerifiedManagedHttpPolicyValidation,
    )

    return type(value) is VerifiedManagedHttpPolicyValidation


def _validate_managed_http_policy_aggregate_report(
    report: dict[str, object],
    bindings: FullComparisonRunBindings,
    *,
    managed_commitment: str,
    execution_case_manifest_sha256: str | None,
) -> str:
    from infinity_context_server.memory_comparison_managed_http_policy_validation import (
        MANAGED_HTTP_POLICY_VALIDATION_SCHEMA_VERSION,
    )

    trusted = _exact_report(report, "managed HTTP policy aggregate report")
    expected_targets = [
        {
            "backend_role": target.backend_role,
            "target_identity_sha256": target.target_identity_sha256,
        }
        for target in bindings.backend_targets
    ]
    case_count = trusted.get("case_count")
    unique_corpus_count = trusted.get("unique_corpus_count")
    source_pair_count = trusted.get("source_pair_count")
    derived_commitment_count = trusted.get("derived_commitment_count")
    cleanup_pass_count = trusted.get("cleanup_pass_count")
    if (
        trusted.get("schema_version") != MANAGED_HTTP_POLICY_VALIDATION_SCHEMA_VERSION
        or trusted.get("run_id") != bindings.run_id
        or trusted.get("profile_id") != bindings.profile_id
        or trusted.get("scope_id") != bindings.scope
        or trusted.get("binding_commitment_sha256")
        != bindings.binding_commitment_sha256
        or trusted.get("managed_attestation_commitment_sha256") != managed_commitment
        or trusted.get("execution_case_manifest_sha256")
        != execution_case_manifest_sha256
        or trusted.get("backend_targets") != expected_targets
        or type(case_count) is not int
        or case_count < 1
        or type(unique_corpus_count) is not int
        or unique_corpus_count < 1
        or unique_corpus_count > case_count
        or type(source_pair_count) is not int
        or source_pair_count < unique_corpus_count
        or type(derived_commitment_count) is not int
        or derived_commitment_count < unique_corpus_count
        or cleanup_pass_count != 4
    ):
        raise _evidence_error("managed HTTP policy aggregate binding is invalid")
    adapter_id = trusted.get("adapter_id")
    if (
        type(adapter_id) is not str
        or not adapter_id
        or adapter_id != adapter_id.strip()
        or len(adapter_id) > 200
    ):
        raise _evidence_error("managed HTTP policy adapter id is invalid")
    for key, label in (
        ("implementation_sha256", "managed HTTP policy implementation"),
        ("execution_case_manifest_sha256", "managed HTTP execution case manifest"),
        ("case_corpus_mapping_sha256", "managed HTTP case corpus mapping"),
        ("corpus_evidence_commitment_sha256", "managed HTTP corpus evidence"),
        ("cleanup_commitment_sha256", "managed HTTP cleanup"),
        ("material_commitment_sha256", "managed HTTP policy material"),
        ("validation_commitment_sha256", "managed HTTP policy validation"),
    ):
        _digest_value(trusted.get(key), label)
    return bindings.binding_commitment_sha256


def _exact_report(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise _evidence_error(f"{name} must be an exact mapping")
    return value


def _digest_value(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _evidence_error(f"{name} must be SHA-256")
    return value


def _mem0_target_identity(bindings: FullComparisonRunBindings) -> str:
    targets = tuple(
        target.target_identity_sha256
        for target in bindings.backend_targets
        if target.backend_role == "mem0"
    )
    return targets[0] if len(targets) == 1 else "invalid"


def _runtime_validation_is_current(public: dict[str, object]) -> bool:
    validated_at = _parse_utc_instant(public.get("validated_at"))
    max_age = public.get("max_age_seconds")
    attestation = public.get("attestation")
    checked_at = (
        _parse_utc_instant(attestation.get("checked_at")) if type(attestation) is dict else None
    )
    if validated_at is None or checked_at is None or type(max_age) is not int or max_age <= 0:
        return False
    now = datetime.now(UTC)
    validation_delta = (now - validated_at).total_seconds()
    attestation_delta = (now - checked_at).total_seconds()
    if (
        validation_delta < -_MAX_RUNTIME_CLOCK_SKEW_SECONDS
        or attestation_delta < -_MAX_RUNTIME_CLOCK_SKEW_SECONDS
    ):
        return False
    validation_age = max(0.0, validation_delta)
    attestation_age = max(0.0, attestation_delta)
    ages = (
        public.get("age_seconds"),
        public.get("timestamp_attestation_age_seconds"),
        public.get("refresh_age_seconds"),
    )
    return bool(
        validation_age <= max_age
        and attestation_age <= max_age
        and all(
            type(age) in {int, float}
            and float(age) >= -_MAX_RUNTIME_CLOCK_SKEW_SECONDS
            and max(0.0, float(age)) + validation_age <= max_age
            for age in ages
        )
    )


def _parse_utc_instant(value: object) -> datetime | None:
    if type(value) is not str or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _profile(profile_id: str) -> FullComparisonProfile:
    profile = resolve_full_comparison_profile(profile_id)
    if profile is None:
        raise _evidence_error("full comparison profile is missing")
    return frozen_full_comparison_profile(profile)


def _evidence_error(message: str) -> Exception:
    from infinity_context_server.memory_comparison_full_run_evidence import (
        FullComparisonEvidenceError,
    )

    return FullComparisonEvidenceError(message)


def _json_sha256(value: object) -> str:
    from infinity_context_server.memory_comparison_full_run_evidence import _json_sha256

    return _json_sha256(value)


__all__ = (
    "issue_clean_state_component_evidence",
    "issue_execution_component_evidence_set",
    "issue_gold_blind_component_evidence",
    "issue_policy_component_evidence_set",
    "issue_provider_component_evidence",
    "issue_runtime_component_evidence",
    "issue_runtime_component_evidence_from_managed_attestation",
    "issue_session_component_evidence",
    "issue_transport_component_evidence",
)
