"""Private completed-readiness context inspection for managed composition."""

from __future__ import annotations

from datetime import datetime

from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedPreflightRequest,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials import (
    ManagedRuntimeCredentialAuthority,
    ManagedSubscriptionReadinessClaim,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_integrity import (
    canonical_json_bytes,
    hmac_sha256,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_models import (
    ManagedRuntimeCredentialError,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_subscription_probe import (
    SubscriptionRuntimeProbeObservation,
    VerifiedSubscriptionRuntimeProbe,
    inspect_verified_subscription_runtime_probe,
)


def _inspect_completed_managed_runtime_credential_context(
    authority: object,
    readiness_claim: object,
    *,
    expected_request: ManagedPreflightRequest,
    expected_probe: VerifiedSubscriptionRuntimeProbe,
    run_id: str,
    deadline: datetime,
) -> str:
    """Fingerprint one completed readiness claim without consuming a lane."""

    if type(authority) is not ManagedRuntimeCredentialAuthority:
        _fail()
    return authority._inspect_completed_context(
        readiness_claim=readiness_claim,
        expected_request=expected_request,
        expected_probe=expected_probe,
        run_id=run_id,
        deadline=deadline,
    )


def _inspect_completed_context_for_authority(
    authority: ManagedRuntimeCredentialAuthority,
    state: object,
    readiness_claim: object,
    expected_request: object,
    expected_probe: object,
) -> str:
    if (
        type(readiness_claim) is not ManagedSubscriptionReadinessClaim
        or type(expected_request) is not ManagedPreflightRequest
        or type(expected_probe) is not VerifiedSubscriptionRuntimeProbe
    ):
        _fail()
    claim_route = readiness_claim.route_attestation
    request_route = state.material.provider_route
    completed = readiness_claim._completed_probe_for(state)
    if completed is None:
        _fail()
    claim_probe, observation = completed
    try:
        current_observation = inspect_verified_subscription_runtime_probe(
            expected_probe,
            now=observation.checked_at,
        )
    except Exception:
        _fail()
    if (
        state.root_phase != "bound"
        or state.readiness_phase != "completed"
        or state.readiness_claim is not readiness_claim
        or not readiness_claim._is_completed_for(state)
        or claim_probe is not expected_probe
        or type(observation) is not SubscriptionRuntimeProbeObservation
        or current_observation is not observation
        or observation.route != claim_route
        or observation.model != expected_request.answerer_model
        or observation.model != expected_request.judge_model
        or observation.checked_at < state.issued_at
        or observation.checked_at >= state.deadline
        or expected_request.provider_route is not request_route
        or type(claim_route) is not ProviderRouteAttestation
        or _static_route(claim_route) != _static_route(request_route)
        or not 200 <= claim_route.response_status < 300
    ):
        _fail()
    payload = canonical_json_bytes(
        {
            "authority_identity": id(authority),
            "claim_identity": id(readiness_claim),
            "request_identity": id(expected_request),
            "probe_identity": id(expected_probe),
            "run_id": state.run_id,
            "deadline": state.deadline.isoformat(),
            "preflight_commitment": state.preflight_commitment,
            "preflight_route": request_route.public_payload(),
            "readiness_route": claim_route.public_payload(),
            "readiness_observation": observation.public_payload(),
            "secret_commitments": list(state.secret_commitments),
        }
    )
    return hmac_sha256(state.binding_key, payload)


def _static_route(route: ProviderRouteAttestation) -> tuple[str, ...]:
    return (
        route.trust,
        route.origin,
        route.endpoint_path,
        route.route_sha256,
        route.transport_evidence,
        route.credential_binding_id,
        route.request_method,
    )


def _fail() -> None:
    raise ManagedRuntimeCredentialError("managed_credentials_context_mismatch")


__all__ = ()
