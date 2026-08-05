from __future__ import annotations

import copy
import hashlib
import hmac
import json
import pickle
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest
from infinity_context_server import memory_comparison_full_run_components as components
from infinity_context_server import memory_comparison_managed_attestation as managed
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonBackendTarget,
    FullComparisonRunBindings,
    create_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_mem0_contract import (
    MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
)
from infinity_context_server.memory_comparison_mem0_platform_contract import (
    REVIEWED_MEM0_MANAGED_WRAPPER_SOURCE_REVISION,
    REVIEWED_MEM0_MANAGED_WRAPPER_SOURCE_SHA256,
)
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    MEM0_OSS_RUNTIME_MODE,
    VerifiedMem0RuntimeAttestationValidation,
    build_verified_mem0_runtime_attestation,
    mem0_runtime_target_identity_sha256,
    public_mem0_runtime_attestation_validation,
    validate_mem0_runtime_attestation_for_backends,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from test_memory_comparison_managed_mem0_runtime_http import (
    _PROBE_TOKEN as _OSS_PROBE_TOKEN,
)
from test_memory_comparison_managed_mem0_runtime_http import (
    _oss_v4_witnessed_manifest,
)
from test_memory_comparison_mem0_runtime_attestation import (
    NONCE as _OSS_NONCE,
)
from test_memory_comparison_mem0_runtime_attestation import (
    RUN_ID as _OSS_RUN_ID,
)
from test_memory_comparison_mem0_runtime_attestation import (
    TARGET_SHA as _OSS_TARGET,
)

_RUN = "managed-composition-run"
_NONCE = "managed-probe-nonce"
_TARGET = mem0_runtime_target_identity_sha256("https://mem0.example.test/managed-adapter")


class _Port:
    def __init__(self, adapter_id: str, implementation_sha256: str) -> None:
        self.adapter_id = adapter_id
        self.implementation_sha256 = implementation_sha256


class _ResetPort(_Port):
    def reset(
        self,
        *,
        run_id: str,
        binding_commitment_sha256: str,
        backend_targets: tuple[tuple[str, str], ...],
    ) -> None:
        del run_id, binding_commitment_sha256, backend_targets


class _AttestationPort(_Port):
    def attest(
        self,
        *,
        run_id: str,
        probe_nonce_sha256: str,
        target_identity_sha256: str,
    ) -> object:
        del run_id, probe_nonce_sha256, target_identity_sha256
        return object()


class _IngestPort(_Port):
    def ingest(
        self,
        *,
        run_id: str,
        backend_role: str,
        target_identity_sha256: str,
        record: Mapping[str, object],
    ) -> None:
        del run_id, backend_role, target_identity_sha256, record


class _Clock(_Port):
    def __init__(self, current: datetime) -> None:
        super().__init__("managed-clock-v1", "4" * 64)
        self.current = current

    def now(self) -> datetime:
        return self.current


class _RuntimeBackend:
    def __init__(self, name: str, *, target: str | None = None) -> None:
        self.name = name
        if target is not None:
            self.runtime_target_identity_sha256 = target


def _bindings(
    *,
    run_id: str = _RUN,
    selection: str = "5" * 64,
    probe_nonce_sha256: str | None = None,
    mem0_target: str = _TARGET,
    scope: str = "full",
    mem0_expected_runtime_mode: str | None = None,
) -> FullComparisonRunBindings:
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    return create_full_comparison_run_bindings(
        run_id=run_id,
        run_nonce_commitment_sha256="4" * 64,
        runtime_probe_nonce_sha256=(
            probe_nonce_sha256
            if probe_nonce_sha256 is not None
            else hashlib.sha256(_NONCE.encode()).hexdigest()
        ),
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset_sha256=profile.expected_dataset_hash,
        selection_fingerprint_sha256=selection,
        backend_targets=(
            FullComparisonBackendTarget("infinity-context", "6" * 64),
            FullComparisonBackendTarget("mem0", mem0_target),
        ),
        scope=scope,
        mem0_expected_runtime_mode=mem0_expected_runtime_mode,
    )


def _ports(now: datetime) -> tuple[_ResetPort, _AttestationPort, _IngestPort, _Clock]:
    return (
        _ResetPort("managed-reset-v1", "1" * 64),
        _AttestationPort("managed-attestation-v1", "2" * 64),
        _IngestPort("managed-ingest-v1", "3" * 64),
        _Clock(now),
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


def _subscription_route() -> ProviderRouteAttestation:
    origin = "http://127.0.0.1:8890"
    endpoint_path = "/v1/chat/completions"
    return ProviderRouteAttestation(
        trust="codex_subscription_runtime",
        origin=origin,
        endpoint_path=endpoint_path,
        route_sha256=hashlib.sha256(f"{origin}{endpoint_path}".encode()).hexdigest(),
        transport_evidence="subscription-runtime-openai-codex-bridge.v1",
        credential_binding_id=None,
        request_method="POST",
        response_status=200,
    )


def _runtime_manifest(
    now: datetime,
    *,
    run_id: str = _RUN,
    nonce: str = _NONCE,
    target: str = _TARGET,
) -> dict[str, object]:
    checked_at = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {
        "schema_version": MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
        "runtime_mode": "managed_platform",
        "wrapper_source_sha256": REVIEWED_MEM0_MANAGED_WRAPPER_SOURCE_SHA256,
        "wrapper_source_revision": REVIEWED_MEM0_MANAGED_WRAPPER_SOURCE_REVISION,
        "config_fingerprint_sha256": "c" * 64,
        "sdk": {
            "distribution": "mem0ai",
            "version": "2.0.14",
            "source_revision": "b357a5a1b03c299ec8229c268e63cfac0f7c6566",
            "artifact_sha256": ("9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"),
            "verification": {
                "method": "direct_url_archive_info_sha256",
                "observed_sha256": (
                    "9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"
                ),
                "passed": True,
            },
        },
        "platform": {
            "api_origin": "https://api.mem0.ai",
            "api_generation": "v3",
            "add_path": "/v3/memories/add/",
            "search_path": "/v3/memories/search/",
            "event_path_template": "/v1/event/{event_id}/",
            "server_source_revision": None,
            "server_revision_attestable": False,
        },
        "persisted_source_identity": {
            "request_metadata_required": True,
            "source_filtered_readback_supported": True,
            "source_id_roundtrip_attested": True,
            "source_sha256_roundtrip_attested": True,
            "sanitized_identity_response": True,
        },
        "timestamp": {
            "request_supported": True,
            "sdk_forwarding_supported": True,
            "event_completion_supported": True,
            "readback_supported": True,
            "attestation": {
                "status": "passed",
                "checked_at": checked_at,
                "probe_mode": "live_sentinel",
                "input_epoch_seconds": 1_672_531_200,
                "expected_created_at": "2023-01-01T00:00:00Z",
                "event_terminal_status": "SUCCEEDED",
                "readback_result_count": 1,
                "persisted_created_at": "2023-01-01T00:00:00Z",
                "delta_seconds": 0.0,
                "cleanup_succeeded": True,
                "failure_code": None,
            },
        },
        "refresh_binding": {
            "status": "passed",
            "run_id_sha256": hashlib.sha256(run_id.encode()).hexdigest(),
            "probe_nonce_sha256": hashlib.sha256(nonce.encode()).hexdigest(),
            "target_identity_sha256": target,
            "refreshed_at": checked_at,
        },
    }


def _runtime_validation(
    *,
    run_id: str = _RUN,
    nonce: str = _NONCE,
    target: str = _TARGET,
    managed_live_max_age_seconds: int | None = None,
) -> VerifiedMem0RuntimeAttestationValidation:
    observed_at = datetime.now(UTC)
    manifest = _runtime_manifest(
        observed_at,
        run_id=run_id,
        nonce=nonce,
        target=target,
    )
    manifest_fingerprint = hashlib.sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    binding = manifest["refresh_binding"]
    assert isinstance(binding, dict)
    message = "\n".join(
        (
            "mem0-benchmark-runtime-witness.v1",
            str(binding["run_id_sha256"]),
            str(binding["probe_nonce_sha256"]),
            str(binding["target_identity_sha256"]),
            str(binding["refreshed_at"]),
            manifest_fingerprint,
        )
    ).encode()
    token = "managed-composition-runtime-token"
    manifest["refresh_witness"] = {
        "algorithm": "hmac-sha256",
        "manifest_fingerprint_sha256": manifest_fingerprint,
        "signature": hmac.new(token.encode(), message, hashlib.sha256).hexdigest(),
    }
    verified = build_verified_mem0_runtime_attestation(
        runtime_manifest=manifest,
        benchmark_probe_token=token,
        openapi_fingerprint_sha256="d" * 64,
        openapi_contract_violations=(),
        probe_passed=True,
        run_id=run_id,
        probe_nonce=nonce,
        target_identity_sha256=target,
    )
    assert verified is not None
    validation = validate_mem0_runtime_attestation_for_backends(
        verified,
        (
            _RuntimeBackend("infinity-context"),
            _RuntimeBackend("mem0", target=target),
        ),
        run_id,
        nonce,
        validated_at=observed_at,
    )
    assert type(validation) is VerifiedMem0RuntimeAttestationValidation
    if managed_live_max_age_seconds is not None:
        from test_memory_comparison_managed_runtime_validity import (
            _bind_terminal_policy,
        )

        _bind_terminal_policy(
            validation,
            run_id=run_id,
            nonce=nonce,
            target=target,
            max_age_seconds=managed_live_max_age_seconds,
        )
    return validation


def _oss_v4_runtime_validation() -> VerifiedMem0RuntimeAttestationValidation:
    observed_at = datetime.now(UTC)
    verified = build_verified_mem0_runtime_attestation(
        runtime_manifest=_oss_v4_witnessed_manifest(observed_at),
        benchmark_probe_token=_OSS_PROBE_TOKEN,
        openapi_fingerprint_sha256="d" * 64,
        openapi_contract_violations=(),
        probe_passed=True,
        run_id=_OSS_RUN_ID,
        probe_nonce=_OSS_NONCE,
        target_identity_sha256=_OSS_TARGET,
    )
    assert verified is not None
    validation = validate_mem0_runtime_attestation_for_backends(
        verified,
        (
            _RuntimeBackend("infinity-context"),
            _RuntimeBackend("mem0", target=_OSS_TARGET),
        ),
        _OSS_RUN_ID,
        _OSS_NONCE,
        required_runtime_mode=MEM0_OSS_RUNTIME_MODE,
        validated_at=datetime.now(UTC),
    )
    assert type(validation) is VerifiedMem0RuntimeAttestationValidation
    return validation


def _validation_clock(
    validation: VerifiedMem0RuntimeAttestationValidation,
) -> datetime:
    public = public_mem0_runtime_attestation_validation(validation)
    return datetime.fromisoformat(str(public["validated_at"]).replace("Z", "+00:00"))


def _issue(
    *,
    bindings: FullComparisonRunBindings | None = None,
    validation: VerifiedMem0RuntimeAttestationValidation | None = None,
    route: ProviderRouteAttestation | None = None,
    ports: tuple[_ResetPort, _AttestationPort, _IngestPort, _Clock] | None = None,
):
    current_bindings = bindings or _bindings()
    current_validation = validation or _runtime_validation(
        run_id=current_bindings.run_id,
        target=next(
            target.target_identity_sha256
            for target in current_bindings.backend_targets
            if target.backend_role == "mem0"
        ),
    )
    current_ports = ports or _ports(_validation_clock(current_validation))
    current_route = route or _route()
    attestation = managed._issue_verified_managed_composition_attestation_for_composition_root(
        bindings=current_bindings,
        reset_port=current_ports[0],
        attestation_port=current_ports[1],
        ingest_port=current_ports[2],
        clock=current_ports[3],
        runtime_validation=current_validation,
        provider_route=current_route,
    )
    return attestation, current_bindings, current_validation, current_route, current_ports


def _public(
    attestation: managed.VerifiedManagedCompositionAttestation,
    bindings: FullComparisonRunBindings,
    ports: tuple[_ResetPort, _AttestationPort, _IngestPort, _Clock],
) -> dict[str, object]:
    return managed.public_managed_composition_attestation(
        attestation,
        bindings=bindings,
        reset_port=ports[0],
        attestation_port=ports[1],
        ingest_port=ports[2],
        clock=ports[3],
    )


def test_component_report_binds_exact_live_composition() -> None:
    attestation, bindings, _, route, ports = _issue()
    report = _public(attestation, bindings, ports)

    assert report["binding_commitment_sha256"] == (bindings.binding_commitment_sha256)
    assert report["backend_targets"] == [
        {
            "backend_role": target.backend_role,
            "target_identity_sha256": target.target_identity_sha256,
        }
        for target in bindings.backend_targets
    ]
    assert report["ports"] == [
        {
            "port_role": role,
            "adapter_id": port.adapter_id,
            "implementation_sha256": port.implementation_sha256,
        }
        for role, port in zip(
            ("reset", "attestation", "ingest", "clock"),
            ports,
            strict=True,
        )
    ]
    runtime = report["runtime"]
    assert isinstance(runtime, dict)
    assert runtime["probe_nonce_sha256"] == bindings.runtime_probe_nonce_sha256
    assert runtime["target_identity_sha256"] == _TARGET
    provider = report["provider_route"]
    assert isinstance(provider, dict)
    assert provider["route_sha256"] == route.route_sha256
    assert provider["credential_binding_id"] == route.credential_binding_id
    assert report["component_only"] is True
    assert report["evidence_role"] == "component_only"
    assert report["composite_consume_required"] is True
    assert report["externally_authentic"] is False
    assert not any("identity" in key for key in report)


def test_canary_accepts_exact_credentialless_subscription_bridge_but_full_rejects() -> None:
    route = _subscription_route()
    canary_bindings = _bindings(scope="canary")

    attestation, bindings, _, _, ports = _issue(
        bindings=canary_bindings,
        route=route,
    )
    report = _public(attestation, bindings, ports)

    provider = report["provider_route"]
    assert isinstance(provider, dict)
    assert provider["trust"] == "codex_subscription_runtime"
    assert provider["credential_binding_id"] is None

    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="credential binding",
    ):
        _issue(bindings=_bindings(scope="full"), route=_subscription_route())


def test_keyless_canary_oss_v4_runtime_uses_sealed_binding_mode() -> None:
    validation = _oss_v4_runtime_validation()
    bindings = _bindings(
        run_id=_OSS_RUN_ID,
        probe_nonce_sha256=hashlib.sha256(_OSS_NONCE.encode()).hexdigest(),
        mem0_target=_OSS_TARGET,
        scope="canary",
        mem0_expected_runtime_mode=MEM0_OSS_RUNTIME_MODE,
    )

    attestation, _, _, _, ports = _issue(
        bindings=bindings,
        validation=validation,
        route=_subscription_route(),
    )
    report = _public(attestation, bindings, ports)

    runtime = report["runtime"]
    assert isinstance(runtime, dict)
    assert runtime["runtime_mode"] == MEM0_OSS_RUNTIME_MODE
    assert components.live_component_status("runtime", validation, bindings) == (
        "verified",
        None,
    )


def test_no_public_self_issuer_or_raw_sha_wrapper() -> None:
    assert (
        "_issue_verified_managed_composition_attestation_for_composition_root"
        not in managed.__all__
    )
    assert "_consume_verified_managed_composition_attestation_for_composite" not in managed.__all__
    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="composition-root issued",
    ):
        managed.VerifiedManagedCompositionAttestation(
            commitment="0" * 64,
            nonce="1" * 64,
            _token=object(),
        )

    bindings = _bindings()
    validation = _runtime_validation()
    ports = _ports(_validation_clock(validation))
    with pytest.raises(TypeError, match="runtime_validation_sha256"):
        managed._issue_verified_managed_composition_attestation_for_composition_root(
            bindings=bindings,
            reset_port=ports[0],
            attestation_port=ports[1],
            ingest_port=ports[2],
            clock=ports[3],
            runtime_validation=validation,
            provider_route=_route(),
            runtime_validation_sha256="9" * 64,
        )


def test_issue_requires_exact_runtime_and_provider_capabilities() -> None:
    bindings = _bindings()
    validation = _runtime_validation()
    ports = _ports(_validation_clock(validation))

    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="runtime capability type",
    ):
        managed._issue_verified_managed_composition_attestation_for_composition_root(
            bindings=bindings,
            reset_port=ports[0],
            attestation_port=ports[1],
            ingest_port=ports[2],
            clock=ports[3],
            runtime_validation={},  # type: ignore[arg-type]
            provider_route=_route(),
        )
    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="provider route capability type",
    ):
        managed._issue_verified_managed_composition_attestation_for_composition_root(
            bindings=bindings,
            reset_port=ports[0],
            attestation_port=ports[1],
            ingest_port=ports[2],
            clock=ports[3],
            runtime_validation=validation,
            provider_route={},  # type: ignore[arg-type]
        )
    unbound_route = _route()
    object.__setattr__(unbound_route, "credential_binding_id", None)
    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="credential binding",
    ):
        managed._issue_verified_managed_composition_attestation_for_composition_root(
            bindings=bindings,
            reset_port=ports[0],
            attestation_port=ports[1],
            ingest_port=ports[2],
            clock=ports[3],
            runtime_validation=validation,
            provider_route=unbound_route,
        )


@pytest.mark.parametrize(
    ("change", "match"),
    (
        ({"run_id": "another-managed-run"}, "runtime binding"),
        ({"probe_nonce_sha256": "8" * 64}, "runtime binding"),
        ({"mem0_target": "9" * 64}, "runtime binding"),
    ),
)
def test_runtime_capability_rejects_cross_run_probe_and_target(
    change: dict[str, str],
    match: str,
) -> None:
    validation = _runtime_validation()
    bindings = _bindings(**change)
    ports = _ports(_validation_clock(validation))
    with pytest.raises(managed.ManagedCompositionAttestationError, match=match):
        managed._issue_verified_managed_composition_attestation_for_composition_root(
            bindings=bindings,
            reset_port=ports[0],
            attestation_port=ports[1],
            ingest_port=ports[2],
            clock=ports[3],
            runtime_validation=validation,
            provider_route=_route(),
        )


def test_capabilities_are_reserved_once_across_full_binding_replay() -> None:
    validation = _runtime_validation()
    route = _route()
    source = _bindings()
    ports = _ports(_validation_clock(validation))
    managed._issue_verified_managed_composition_attestation_for_composition_root(
        bindings=source,
        reset_port=ports[0],
        attestation_port=ports[1],
        ingest_port=ports[2],
        clock=ports[3],
        runtime_validation=validation,
        provider_route=route,
    )

    replay = _bindings(selection="7" * 64)
    replay_ports = _ports(_validation_clock(validation))
    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="already reserved",
    ):
        managed._issue_verified_managed_composition_attestation_for_composition_root(
            bindings=replay,
            reset_port=replay_ports[0],
            attestation_port=replay_ports[1],
            ingest_port=replay_ports[2],
            clock=replay_ports[3],
            runtime_validation=validation,
            provider_route=route,
        )


def test_exact_port_identity_and_live_provenance_are_rechecked() -> None:
    attestation, bindings, _, _, ports = _issue()
    equal_ports = _ports(ports[3].current)
    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="port identity",
    ):
        _public(attestation, bindings, equal_ports)

    ports[0].reset = lambda **kwargs: None  # type: ignore[method-assign]
    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="live capability changed",
    ):
        _public(attestation, bindings, ports)

    attestation, bindings, _, _, ports = _issue()
    ports[0].adapter_id = "mutated-reset"

    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="live capability changed",
    ):
        _public(attestation, bindings, ports)


def test_provider_route_and_opaque_state_mutation_fail_closed() -> None:
    attestation, bindings, _, route, ports = _issue()
    object.__setattr__(
        route,
        "credential_binding_id",
        "sha256:" + "0" * 64,
    )
    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="live capability changed",
    ):
        _public(attestation, bindings, ports)

    second, second_bindings, _, _, second_ports = _issue()
    object.__setattr__(
        second,
        "_VerifiedManagedCompositionAttestation__nonce",
        "mutated",
    )
    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="integrity",
    ):
        _public(second, second_bindings, second_ports)


def test_composite_consume_is_one_shot_and_keeps_public_revalidation_live() -> None:
    attestation, bindings, _, _, ports = _issue()
    report = managed._consume_verified_managed_composition_attestation_for_composite(
        attestation,
        bindings=bindings,
        reset_port=ports[0],
        attestation_port=ports[1],
        ingest_port=ports[2],
        clock=ports[3],
    )
    assert report["component_only"] is True

    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="already consumed",
    ):
        managed._consume_verified_managed_composition_attestation_for_composite(
            attestation,
            bindings=bindings,
            reset_port=ports[0],
            attestation_port=ports[1],
            ingest_port=ports[2],
            clock=ports[3],
        )
    assert _public(attestation, bindings, ports) == report
    assert _public(attestation, bindings, ports) == report


def test_current_clock_skew_boundary_and_staleness() -> None:
    attestation, bindings, _, _, ports = _issue()
    report = _public(attestation, bindings, ports)
    checked_at = datetime.fromisoformat(str(report["checked_at"]).replace("Z", "+00:00"))

    ports[3].current = checked_at - timedelta(seconds=0.999)
    assert _public(attestation, bindings, ports)["component_only"] is True

    ports[3].current = checked_at - timedelta(seconds=1.001)
    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="future",
    ):
        _public(attestation, bindings, ports)

    ports[3].current = checked_at + timedelta(seconds=121)
    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="stale",
    ):
        _public(attestation, bindings, ports)


def test_issue_rechecks_current_clock_and_timezone() -> None:
    bindings = _bindings()
    validation = _runtime_validation()
    observed_at = _validation_clock(validation)
    stale_ports = _ports(observed_at + timedelta(seconds=121))
    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="stale",
    ):
        managed._issue_verified_managed_composition_attestation_for_composition_root(
            bindings=bindings,
            reset_port=stale_ports[0],
            attestation_port=stale_ports[1],
            ingest_port=stale_ports[2],
            clock=stale_ports[3],
            runtime_validation=validation,
            provider_route=_route(),
        )

    naive_ports = _ports(observed_at.replace(tzinfo=None))
    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="timezone-aware",
    ):
        managed._issue_verified_managed_composition_attestation_for_composition_root(
            bindings=bindings,
            reset_port=naive_ports[0],
            attestation_port=naive_ports[1],
            ingest_port=naive_ports[2],
            clock=naive_ports[3],
            runtime_validation=validation,
            provider_route=_route(),
        )


def test_opaque_capability_is_final_noncopyable_and_nonserializable() -> None:
    attestation, _, _, _, _ = _issue()

    with pytest.raises(TypeError):

        class Child(managed.VerifiedManagedCompositionAttestation):
            pass

    with pytest.raises(TypeError):
        copy.copy(attestation)
    with pytest.raises(TypeError):
        copy.deepcopy(attestation)
    with pytest.raises(TypeError):
        pickle.dumps(attestation)
