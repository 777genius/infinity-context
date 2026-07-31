"""Nominal live component adapters for full-run evidence."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from infinity_context_server.memory_comparison_clean_state import (
    VerifiedCleanStateValidation,
    public_clean_state_validation,
)
from infinity_context_server.memory_comparison_full_profiles import (
    FullComparisonProfile,
    frozen_full_comparison_profile,
    resolve_full_comparison_profile,
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

    if component_kind == "provider" and type(validation) is ProviderRouteAttestation:
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
    "issue_gold_blind_component_evidence",
    "issue_provider_component_evidence",
    "issue_runtime_component_evidence",
    "issue_session_component_evidence",
    "issue_transport_component_evidence",
)
