from __future__ import annotations

import copy
import json
import pickle

import pytest
from infinity_context_server.memory_comparison_clean_state import (
    VerifiedCleanStateValidation,
)
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_components import (
    issue_clean_state_component_evidence,
    issue_provider_component_evidence,
    issue_session_component_evidence,
    issue_transport_component_evidence,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FULL_COMPARISON_CANARY_WAIVER_CODES,
    FULL_COMPARISON_COMPONENT_KINDS,
    FullComparisonBackendTarget,
    FullComparisonComponentEvidence,
    FullComparisonEvidenceError,
    FullComparisonEvidenceIssuer,
    FullComparisonPolicyBlocker,
    FullComparisonRunBindings,
    FullComparisonRunEvidence,
    create_full_comparison_evidence_issuer,
    create_full_comparison_run_bindings,
    issue_full_comparison_run_evidence,
)
from infinity_context_server.memory_comparison_full_scope import (
    FULL_COMPARISON_SCOPE_CANARY,
    FULL_COMPARISON_SCOPE_FULL,
)
from infinity_context_server.memory_comparison_full_verdict import (
    FullComparisonVerdict,
    FullComparisonVerdictError,
    public_full_comparison_verdict,
    verify_full_comparison_run,
)
from infinity_context_server.memory_comparison_locomo_transport import (
    RunScopedLocomoTransportEvidenceKey,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_session_identity_contract import (
    RunScopedSessionHmacKey,
)


def _bindings(
    *,
    run_id: str = "run-1",
    scope: str = FULL_COMPARISON_SCOPE_FULL,
    selection: str = "b" * 64,
    dataset_sha256: str | None = None,
) -> FullComparisonRunBindings:
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    return create_full_comparison_run_bindings(
        run_id=run_id,
        run_nonce_commitment_sha256="a" * 64,
        runtime_probe_nonce_sha256="0" * 64,
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset_sha256=(
            profile.expected_dataset_hash if dataset_sha256 is None else dataset_sha256
        ),
        selection_fingerprint_sha256=selection,
        backend_targets=(
            FullComparisonBackendTarget("infinity-context", "c" * 64),
            FullComparisonBackendTarget("mem0", "d" * 64),
        ),
        scope=scope,
    )


def _route() -> ProviderRouteAttestation:
    return ProviderRouteAttestation(
        trust="official_openai",
        origin="https://api.openai.com",
        endpoint_path="/v1/chat/completions",
        route_sha256="e" * 64,
        transport_evidence="direct_https",
        credential_binding_id="sha256:" + "f" * 64,
        request_method="POST",
        response_status=200,
    )


def _empty_evidence(
    *,
    bindings: FullComparisonRunBindings | None = None,
    blockers: tuple[FullComparisonPolicyBlocker, ...] = (),
) -> tuple[FullComparisonRunEvidence, FullComparisonEvidenceIssuer]:
    current = bindings or _bindings()
    issuer = create_full_comparison_evidence_issuer(current)
    return (
        issue_full_comparison_run_evidence(
            current,
            (),
            issuer,
            policy_blockers=blockers,
        ),
        issuer,
    )


def test_bindings_are_exact_and_commit_every_publication_axis() -> None:
    bindings = _bindings()
    assert bindings.profile_id == PROFILE_LOCOMO_TOP_50
    assert bindings.dataset_sha256
    assert bindings.methodology_commitment_sha256
    assert bindings.selection_fingerprint_sha256 == "b" * 64
    assert tuple(item.backend_role for item in bindings.backend_targets) == (
        "infinity-context",
        "mem0",
    )
    assert len(bindings.binding_commitment_sha256) == 64

    object.__setattr__(bindings, "selection_fingerprint_sha256", "9" * 64)
    with pytest.raises(FullComparisonEvidenceError, match="commitment differs"):
        create_full_comparison_evidence_issuer(bindings)


@pytest.mark.parametrize(
    "targets",
    (
        (
            FullComparisonBackendTarget("mem0", "c" * 64),
            FullComparisonBackendTarget("infinity-context", "d" * 64),
        ),
        (
            FullComparisonBackendTarget("infinity-context", "c" * 64),
            FullComparisonBackendTarget("mem0", "c" * 64),
        ),
    ),
)
def test_backend_targets_require_exact_order_and_distinct_identity(
    targets: tuple[FullComparisonBackendTarget, ...],
) -> None:
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    with pytest.raises(FullComparisonEvidenceError):
        create_full_comparison_run_bindings(
            run_id="run-1",
            run_nonce_commitment_sha256="a" * 64,
            runtime_probe_nonce_sha256="0" * 64,
            profile=profile,
            methodology=full_comparison_methodology_contract(profile),
            dataset_sha256=profile.expected_dataset_hash,
            selection_fingerprint_sha256="b" * 64,
            backend_targets=targets,
        )


def test_dataset_must_match_frozen_profile_and_methodology() -> None:
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    with pytest.raises(FullComparisonEvidenceError, match="dataset differs"):
        create_full_comparison_run_bindings(
            run_id="run-1",
            run_nonce_commitment_sha256="a" * 64,
            runtime_probe_nonce_sha256="0" * 64,
            profile=profile,
            methodology=full_comparison_methodology_contract(profile),
            dataset_sha256="0" * 64,
            selection_fingerprint_sha256="b" * 64,
            backend_targets=(
                FullComparisonBackendTarget("infinity-context", "c" * 64),
                FullComparisonBackendTarget("mem0", "d" * 64),
            ),
        )


def test_canary_binds_independent_actual_dataset_hash_and_never_publishes() -> None:
    actual_dataset_sha256 = "1" * 64
    bindings = _bindings(
        scope=FULL_COMPARISON_SCOPE_CANARY,
        dataset_sha256=actual_dataset_sha256,
    )

    assert bindings.dataset_sha256 == actual_dataset_sha256
    evidence, _ = _empty_evidence(bindings=bindings)
    report = public_full_comparison_verdict(verify_full_comparison_run(evidence))

    assert report["scope"] == FULL_COMPARISON_SCOPE_CANARY
    assert report["claim_scope"] == "diagnostic_canary"
    assert report["publishable"] is False
    assert report["commitments"]["dataset_sha256"] == actual_dataset_sha256


@pytest.mark.parametrize("dataset_sha256", ("", "1" * 63, "G" * 64))
def test_canary_rejects_invalid_actual_dataset_digest(dataset_sha256: str) -> None:
    with pytest.raises(FullComparisonEvidenceError, match="digest must be SHA-256"):
        _bindings(
            scope=FULL_COMPARISON_SCOPE_CANARY,
            dataset_sha256=dataset_sha256,
        )


def test_canary_binding_cannot_be_reused_or_laundered_as_full() -> None:
    canary = _bindings(scope=FULL_COMPARISON_SCOPE_CANARY)
    full = _bindings(scope=FULL_COMPARISON_SCOPE_FULL)
    assert canary.binding_commitment_sha256 != full.binding_commitment_sha256

    canary_issuer = create_full_comparison_evidence_issuer(canary)
    component = issue_provider_component_evidence(canary_issuer, _route())
    full_issuer = create_full_comparison_evidence_issuer(full)
    with pytest.raises(FullComparisonEvidenceError, match="another issuer"):
        issue_full_comparison_run_evidence(full, (component,), full_issuer)

    object.__setattr__(canary, "scope", FULL_COMPARISON_SCOPE_FULL)
    with pytest.raises(FullComparisonEvidenceError, match="commitment differs"):
        create_full_comparison_evidence_issuer(canary)


def test_canary_dataset_tampering_invalidates_bound_capability() -> None:
    bindings = _bindings(
        scope=FULL_COMPARISON_SCOPE_CANARY,
        dataset_sha256="1" * 64,
    )
    create_full_comparison_evidence_issuer(bindings)
    object.__setattr__(bindings, "dataset_sha256", "2" * 64)

    with pytest.raises(FullComparisonEvidenceError, match="commitment differs"):
        create_full_comparison_evidence_issuer(bindings)


def test_nominal_component_slots_reject_public_mappings() -> None:
    bindings = _bindings()
    issuer = create_full_comparison_evidence_issuer(bindings)
    route = _route()
    component = issue_provider_component_evidence(issuer, route)
    assert type(component) is FullComparisonComponentEvidence

    with pytest.raises(FullComparisonEvidenceError, match="type must be exact"):
        issue_provider_component_evidence(issuer, route.public_payload())  # type: ignore[arg-type]
    with pytest.raises(FullComparisonEvidenceError, match="type must be exact"):
        issue_clean_state_component_evidence(issuer, {"eligible": True})  # type: ignore[arg-type]
    with pytest.raises(FullComparisonEvidenceError, match="type must be exact"):
        issue_full_comparison_run_evidence(bindings, ({},), issuer)  # type: ignore[arg-type]


def test_known_live_capabilities_are_nominal_but_unwired_slices_stay_blocked() -> None:
    bindings = _bindings()
    issuer = create_full_comparison_evidence_issuer(bindings)
    components = (
        issue_provider_component_evidence(issuer, _route()),
        issue_session_component_evidence(
            issuer,
            RunScopedSessionHmacKey.generate(run_id=bindings.run_id),
        ),
        issue_clean_state_component_evidence(
            issuer,
            VerifiedCleanStateValidation({"eligible": True}),
        ),
        issue_transport_component_evidence(
            issuer,
            RunScopedLocomoTransportEvidenceKey.generate(run_id=bindings.run_id),
        ),
    )
    evidence = issue_full_comparison_run_evidence(bindings, components, issuer)
    report = public_full_comparison_verdict(verify_full_comparison_run(evidence))
    statuses = {item["component_kind"]: item["status"] for item in report["components"]}
    assert statuses == {
        "provider": "unwired",
        "runtime": "missing",
        "session": "unwired",
        "clean_state": "unwired",
        "gold_blind": "missing",
        "transport": "unwired",
        "delete": "missing",
        "canonical": "missing",
        "source": "missing",
    }
    assert report["publishable"] is False
    assert "provider_call_validation_unwired" in report["blocking_reasons"]
    assert "missing_delete_component" in report["blocking_reasons"]


def test_missing_components_create_exact_fail_closed_verdict() -> None:
    evidence, _ = _empty_evidence()
    report = public_full_comparison_verdict(verify_full_comparison_run(evidence))
    assert report["publishable"] is False
    assert report["eligible"] is False
    assert report["claim_scope"] == "full_comparison"
    assert report["blocking_reasons"] == [
        f"missing_{kind}_component" for kind in FULL_COMPARISON_COMPONENT_KINDS
    ]
    assert report["waivers"] == []
    assert report["commitments"]["binding_sha256"] == _bindings().binding_commitment_sha256


def test_component_duplicates_and_cross_run_components_are_rejected() -> None:
    first = _bindings(run_id="run-1")
    second = _bindings(run_id="run-2")
    first_issuer = create_full_comparison_evidence_issuer(first)
    second_issuer = create_full_comparison_evidence_issuer(second)
    one = issue_provider_component_evidence(first_issuer, _route())
    two = issue_provider_component_evidence(first_issuer, _route())

    with pytest.raises(FullComparisonEvidenceError, match="duplicated"):
        issue_full_comparison_run_evidence(first, (one, two), first_issuer)
    with pytest.raises(FullComparisonEvidenceError, match="another issuer"):
        issue_full_comparison_run_evidence(second, (one,), second_issuer)
    with pytest.raises(FullComparisonEvidenceError, match="bindings differ"):
        issue_full_comparison_run_evidence(second, (), first_issuer)


def test_evidence_is_one_shot_and_cross_run_replay_cannot_upgrade() -> None:
    evidence, _ = _empty_evidence()
    verdict = verify_full_comparison_run(evidence)
    assert public_full_comparison_verdict(verdict)["publishable"] is False
    with pytest.raises(FullComparisonEvidenceError, match="already consumed"):
        verify_full_comparison_run(evidence)

    other, _ = _empty_evidence(bindings=_bindings(run_id="run-2"))
    other_report = public_full_comparison_verdict(verify_full_comparison_run(other))
    assert other_report["run_id"] == "run-2"
    assert other_report["commitments"] != public_full_comparison_verdict(verdict)["commitments"]


@pytest.mark.parametrize(
    "factory",
    (
        lambda: _empty_evidence()[0],
        lambda: _empty_evidence()[1],
        lambda: issue_provider_component_evidence(
            create_full_comparison_evidence_issuer(_bindings()),
            _route(),
        ),
    ),
)
def test_evidence_capabilities_are_noncopyable_and_nonserializable(factory) -> None:
    value = factory()
    for operation in (
        copy.copy,
        copy.deepcopy,
        pickle.dumps,
    ):
        with pytest.raises(TypeError):
            operation(value)


def test_object_new_and_direct_construction_cannot_forge_evidence() -> None:
    forged = object.__new__(FullComparisonRunEvidence)
    with pytest.raises(FullComparisonEvidenceError, match="was not issued"):
        verify_full_comparison_run(forged)
    with pytest.raises(FullComparisonEvidenceError, match="must be issued"):
        FullComparisonRunEvidence(
            binding_commitment="a" * 64,
            nonce="b" * 64,
            _token=object(),
        )
    forged_component = object.__new__(FullComparisonComponentEvidence)
    bindings = _bindings()
    issuer = create_full_comparison_evidence_issuer(bindings)
    with pytest.raises(FullComparisonEvidenceError, match="was not issued"):
        issue_full_comparison_run_evidence(bindings, (forged_component,), issuer)


def test_canary_waives_only_exact_three_policy_codes_and_never_publishes() -> None:
    blockers = tuple(
        FullComparisonPolicyBlocker(code) for code in FULL_COMPARISON_CANARY_WAIVER_CODES
    ) + (FullComparisonPolicyBlocker("retrieval_width_mismatch"),)
    evidence, _ = _empty_evidence(
        bindings=_bindings(scope=FULL_COMPARISON_SCOPE_CANARY),
        blockers=blockers,
    )
    report = public_full_comparison_verdict(verify_full_comparison_run(evidence))
    assert report["claim_scope"] == "diagnostic_canary"
    assert report["waivers"] == list(FULL_COMPARISON_CANARY_WAIVER_CODES)
    assert "retrieval_width_mismatch" in report["blocking_reasons"]
    assert report["publishable"] is False

    full_evidence, _ = _empty_evidence(
        blockers=tuple(
            FullComparisonPolicyBlocker(code) for code in FULL_COMPARISON_CANARY_WAIVER_CODES
        ),
    )
    full_report = public_full_comparison_verdict(verify_full_comparison_run(full_evidence))
    assert full_report["waivers"] == []
    assert set(FULL_COMPARISON_CANARY_WAIVER_CODES) <= set(full_report["blocking_reasons"])


def test_verdict_projection_revalidates_and_rejects_stale_live_state() -> None:
    bindings = _bindings()
    issuer = create_full_comparison_evidence_issuer(bindings)
    route = _route()
    component = issue_provider_component_evidence(issuer, route)
    evidence = issue_full_comparison_run_evidence(bindings, (component,), issuer)
    verdict = verify_full_comparison_run(evidence)
    assert public_full_comparison_verdict(verdict)["publishable"] is False

    object.__setattr__(route, "origin", "https://proxy.invalid")
    with pytest.raises(FullComparisonEvidenceError, match="integrity failed"):
        public_full_comparison_verdict(verdict)


def test_policy_mutation_after_verification_makes_verdict_stale() -> None:
    blocker = FullComparisonPolicyBlocker("safety_blocker")
    evidence, _ = _empty_evidence(blockers=(blocker,))
    verdict = verify_full_comparison_run(evidence)
    object.__setattr__(blocker, "code", "different_safety_blocker")
    with pytest.raises(FullComparisonEvidenceError, match="integrity failed"):
        public_full_comparison_verdict(verdict)


def test_verdict_is_sealed_and_json_roundtrip_is_projection_only() -> None:
    evidence, _ = _empty_evidence()
    verdict = verify_full_comparison_run(evidence)
    report = public_full_comparison_verdict(verdict)
    roundtrip = json.loads(json.dumps(report))
    assert roundtrip == report
    with pytest.raises(FullComparisonVerdictError, match="type must be exact"):
        public_full_comparison_verdict(roundtrip)  # type: ignore[arg-type]
    for operation in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            operation(verdict)
    with pytest.raises(FullComparisonVerdictError, match="was not verified"):
        public_full_comparison_verdict(object.__new__(FullComparisonVerdict))


def test_mutating_public_projection_never_mutates_sealed_verdict() -> None:
    evidence, _ = _empty_evidence()
    verdict = verify_full_comparison_run(evidence)
    first = public_full_comparison_verdict(verdict)
    first["blocking_reasons"].clear()
    first["components"][0]["status"] = "verified"
    second = public_full_comparison_verdict(verdict)
    assert second["blocking_reasons"]
    assert second["components"][0]["status"] == "missing"


def test_nominal_classes_are_final() -> None:
    for base in (
        FullComparisonBackendTarget,
        FullComparisonRunBindings,
        FullComparisonPolicyBlocker,
        FullComparisonEvidenceIssuer,
        FullComparisonComponentEvidence,
        FullComparisonRunEvidence,
        FullComparisonVerdict,
    ):
        with pytest.raises(TypeError):
            type("Forged", (base,), {})
