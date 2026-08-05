from __future__ import annotations

import hashlib
import hmac
import json
import weakref
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import infinity_context_server.memory_comparison_managed_mem0_runtime_http as mem0_runtime_http
import pytest
from infinity_context_server.memory_comparison_managed_mem0_runtime_http import (
    ManagedMem0RuntimeAttestationPort,
    ManagedMem0RuntimeAuthorityDescriptor,
    ManagedMem0RuntimeHttpError,
    ManagedUtcClockPort,
)
from infinity_context_server.memory_comparison_mem0_contract import (
    public_mem0_runtime_manifest,
)
from infinity_context_server.memory_comparison_mem0_oss_contract import (
    evaluate_mem0_oss_runtime_capabilities,
    mem0_oss_runtime_manifest_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v4_manifest import (
    mem0_oss_v4_runtime_manifest_sha256,
)
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    MEM0_MANAGED_PLATFORM_RUNTIME_MODE,
    MEM0_OSS_RUNTIME_MODE,
    VerifiedMem0RuntimeAttestation,
    VerifiedMem0RuntimeAttestationValidation,
    mem0_runtime_attestation_validation_is_publishable,
    public_mem0_runtime_attestation_validation,
    validate_mem0_runtime_attestation_for_backends,
)
from infinity_context_server.memory_comparison_service_probes import (
    MEM0_BENCHMARK_ATTESTATION_REFRESH_PATH,
    probe_mem0_api,
)
from test_memory_comparison_mem0_contract import _valid_capabilities
from test_memory_comparison_mem0_oss_contract import valid_v3_capabilities
from test_memory_comparison_mem0_oss_v4_contract import valid_v4_capabilities
from test_memory_comparison_mem0_runtime_attestation import (
    NONCE,
    RUN_ID,
    TARGET_SHA,
    TARGET_URL,
    _runtime_manifest,
)
from test_memory_comparison_service_probes import (
    _refreshable_openapi,
    _Response,
    _Transport,
)

_TARGET_ORIGIN = "https://mem0.example.test:8443"
_PROBE_TOKEN = "unit-probe-token"
_NONCE_SHA = hashlib.sha256(NONCE.encode()).hexdigest()
_IMPLEMENTATION_SOURCE = Path(mem0_runtime_http.__file__).read_bytes()
_IMPLEMENTATION_SHA = hashlib.sha256(_IMPLEMENTATION_SOURCE).hexdigest()


def test_production_adapter_returns_exact_publishable_same_run_validation() -> None:
    calls: list[tuple[str, str, object, object]] = []
    transport = _transport(calls, _witnessed_manifest(datetime.now(UTC)))
    adapter = _adapter(transport)

    validation = adapter.attest(
        run_id=RUN_ID,
        probe_nonce_sha256=_NONCE_SHA,
        target_identity_sha256=TARGET_SHA,
    )

    assert type(validation) is VerifiedMem0RuntimeAttestationValidation
    assert mem0_runtime_attestation_validation_is_publishable(
        validation,
        required_runtime_mode=MEM0_MANAGED_PLATFORM_RUNTIME_MODE,
    )
    public = public_mem0_runtime_attestation_validation(validation)
    assert public["eligible"] is True
    attestation = public["attestation"]
    assert isinstance(attestation, dict)
    assert attestation["probe_nonce_sha256"] == _NONCE_SHA
    assert attestation["target_identity_sha256"] == TARGET_SHA
    assert calls[1][2] == {"X-Benchmark-Probe-Token": _PROBE_TOKEN}
    rendered = json.dumps(public, sort_keys=True)
    assert all(value not in rendered for value in (_PROBE_TOKEN, NONCE, RUN_ID, TARGET_URL))


def test_oss_adapter_accepts_only_a_valid_oss_same_run_runtime_attestation() -> None:
    calls: list[tuple[str, str, object, object]] = []
    adapter = _adapter(
        _transport(calls, _oss_witnessed_manifest(datetime.now(UTC))),
        expected_runtime_mode=MEM0_OSS_RUNTIME_MODE,
    )
    assert adapter.authority_descriptor().expected_runtime_mode == MEM0_OSS_RUNTIME_MODE

    validation = adapter.attest(
        run_id=RUN_ID,
        probe_nonce_sha256=_NONCE_SHA,
        target_identity_sha256=TARGET_SHA,
    )

    assert type(validation) is VerifiedMem0RuntimeAttestationValidation
    assert mem0_runtime_attestation_validation_is_publishable(
        validation,
        required_runtime_mode=MEM0_OSS_RUNTIME_MODE,
    )
    assert adapter.usage_attestation_required() is False


def test_oss_v3_adapter_accepts_only_a_valid_oss_same_run_runtime_attestation() -> None:
    calls: list[tuple[str, str, object, object]] = []
    adapter = _adapter(
        _transport(calls, _oss_v3_witnessed_manifest(datetime.now(UTC))),
        expected_runtime_mode=MEM0_OSS_RUNTIME_MODE,
    )

    validation = adapter.attest(
        run_id=RUN_ID,
        probe_nonce_sha256=_NONCE_SHA,
        target_identity_sha256=TARGET_SHA,
    )

    assert type(validation) is VerifiedMem0RuntimeAttestationValidation
    assert mem0_runtime_attestation_validation_is_publishable(
        validation,
        required_runtime_mode=MEM0_OSS_RUNTIME_MODE,
    )
    assert adapter.usage_attestation_required() is False


def test_oss_v4_adapter_requires_post_sealed_usage_attestation_only_after_verification() -> None:
    adapter = _adapter(
        _transport([], _oss_v4_witnessed_manifest(datetime.now(UTC))),
        expected_runtime_mode=MEM0_OSS_RUNTIME_MODE,
    )

    with pytest.raises(ManagedMem0RuntimeHttpError, match="capability_invalid"):
        adapter.usage_attestation_required()

    validation = adapter.attest(
        run_id=RUN_ID,
        probe_nonce_sha256=_NONCE_SHA,
        target_identity_sha256=TARGET_SHA,
    )

    assert mem0_runtime_attestation_validation_is_publishable(
        validation,
        required_runtime_mode=MEM0_OSS_RUNTIME_MODE,
    )
    assert adapter.usage_attestation_required() is True


def test_oss_v3_raw_refresh_without_hmac_witness_is_rejected_at_generic_probe_boundary() -> None:
    manifest = _oss_v3_witnessed_manifest(datetime.now(UTC))
    witness = manifest.pop("refresh_witness")
    assert isinstance(witness, dict)
    assert evaluate_mem0_oss_runtime_capabilities(manifest, require_timestamp=True) == ()

    outcome = _probe_oss_v3_refresh(manifest)

    assert outcome.passed is False
    assert outcome.reason_code == "mem0_runtime_attestation_refresh_failed"
    assert outcome.details["verified_runtime_attestation"] is None


def test_oss_v3_binding_only_projection_requires_verified_post_projection_capability() -> None:
    now = datetime.now(UTC)
    outcome = _probe_oss_v3_refresh(_oss_v3_witnessed_manifest(now))

    assert outcome.passed is True
    verified = outcome.details["verified_runtime_attestation"]
    assert isinstance(verified, VerifiedMem0RuntimeAttestation)
    projected_manifest = public_mem0_runtime_manifest(verified.payload["runtime_manifest"])
    assert "refresh_binding" in projected_manifest
    assert "refresh_witness" not in projected_manifest
    assert evaluate_mem0_oss_runtime_capabilities(projected_manifest, require_timestamp=True) == ()

    untrusted_validation = validate_mem0_runtime_attestation_for_backends(
        dict(verified.payload),
        (SimpleNamespace(name="mem0", runtime_target_identity_sha256=TARGET_SHA),),
        RUN_ID,
        NONCE,
        required_runtime_mode=MEM0_OSS_RUNTIME_MODE,
        validated_at=now,
    )

    assert type(untrusted_validation) is dict
    assert untrusted_validation["eligible"] is False
    assert "mem0_runtime_witness_capability_missing" in untrusted_validation["issues"]


def test_authority_descriptor_commits_exact_pending_private_authority() -> None:
    transport = _Transport([], {})
    adapter = _adapter(transport)

    descriptor = adapter.authority_descriptor()

    assert type(descriptor) is ManagedMem0RuntimeAuthorityDescriptor
    assert descriptor.adapter_id == adapter.adapter_id
    assert descriptor.implementation_sha256 == adapter.implementation_sha256
    assert descriptor.target_identity_sha256 == TARGET_SHA
    assert descriptor.probe_nonce_sha256 == _NONCE_SHA
    assert descriptor.probe_token_credential_binding_id == (
        "sha256:" + hashlib.sha256(_PROBE_TOKEN.encode()).hexdigest()
    )
    assert descriptor.request_timeout_seconds == 0.5
    assert descriptor.max_attempts == 1
    assert descriptor.expected_runtime_mode == MEM0_MANAGED_PLATFORM_RUNTIME_MODE
    assert adapter.authority_descriptor() is descriptor
    assert weakref.ref(adapter)() is adapter
    assert transport.opened is False


def test_authority_descriptor_is_immutable_and_secret_safe() -> None:
    descriptor = _adapter(_Transport([], {})).authority_descriptor()

    with pytest.raises(FrozenInstanceError):
        descriptor.max_attempts = 2

    rendered = repr(descriptor)
    assert _PROBE_TOKEN not in rendered
    assert NONCE not in rendered
    assert _TARGET_ORIGIN not in rendered
    assert TARGET_URL not in rendered


def test_authority_descriptor_binds_actual_token_and_nonce_not_peer_claims() -> None:
    other_token = "other-unit-probe-token"
    other_nonce = "other-private-probe-nonce-00000001"
    transport = _Transport([], {})
    adapter = ManagedMem0RuntimeAttestationPort(
        base_url=_TARGET_ORIGIN,
        benchmark_probe_token=other_token,
        probe_nonce=other_nonce,
        timeout_seconds=0.5,
        deadline_budget_seconds=60.0,
        monotonic_clock=lambda: 100.0,
        expected_implementation_sha256=_IMPLEMENTATION_SHA,
        allowed_target_hosts=("mem0.example.test",),
        vetted_transport=transport,
    )

    descriptor = adapter.authority_descriptor()

    assert descriptor.probe_nonce_sha256 == hashlib.sha256(other_nonce.encode()).hexdigest()
    assert descriptor.probe_nonce_sha256 != _NONCE_SHA
    assert descriptor.probe_token_credential_binding_id == (
        "sha256:" + hashlib.sha256(other_token.encode()).hexdigest()
    )
    assert descriptor.probe_token_credential_binding_id != (
        "sha256:" + hashlib.sha256(_PROBE_TOKEN.encode()).hexdigest()
    )
    assert transport.opened is False


def test_authority_descriptor_cannot_be_replayed_after_attest_claim() -> None:
    transport = _Transport([], {})
    adapter = _adapter(transport)
    adapter.authority_descriptor()

    with pytest.raises(ManagedMem0RuntimeHttpError):
        adapter.attest(
            run_id=RUN_ID,
            probe_nonce_sha256="0" * 64,
            target_identity_sha256=TARGET_SHA,
        )

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        adapter.authority_descriptor()

    assert raised.value.code == "managed_mem0_runtime_already_used"
    assert transport.opened is False


def test_target_mismatch_fails_before_any_http() -> None:
    transport = _Transport([], {})
    adapter = _adapter(transport)

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        adapter.attest(
            run_id=RUN_ID,
            probe_nonce_sha256=_NONCE_SHA,
            target_identity_sha256="f" * 64,
        )

    assert raised.value.code == "managed_mem0_runtime_binding_invalid"
    assert transport.opened is False


def test_raw_nonce_digest_mismatch_fails_before_any_http() -> None:
    transport = _Transport([], {})
    adapter = _adapter(transport)

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        adapter.attest(
            run_id=RUN_ID,
            probe_nonce_sha256=hashlib.sha256(b"other-private-nonce").hexdigest(),
            target_identity_sha256=TARGET_SHA,
        )

    assert raised.value.code == "managed_mem0_runtime_binding_invalid"
    assert transport.opened is False


@pytest.mark.parametrize(
    ("manifest", "expected_code"),
    (
        (
            lambda: _witnessed_manifest(datetime.now(UTC) - timedelta(minutes=10)),
            "managed_mem0_runtime_capability_invalid",
        ),
        (
            lambda: _witnessed_manifest(datetime.now(UTC), runtime_mode="oss"),
            "managed_mem0_runtime_probe_failed",
        ),
    ),
)
def test_stale_or_wrong_runtime_capability_fails_closed(
    manifest: object,
    expected_code: str,
) -> None:
    factory = manifest
    assert callable(factory)
    transport = _transport([], factory())
    adapter = _adapter(transport)

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        adapter.attest(
            run_id=RUN_ID,
            probe_nonce_sha256=_NONCE_SHA,
            target_identity_sha256=TARGET_SHA,
        )

    assert raised.value.code == expected_code


@pytest.mark.parametrize(
    ("expected_runtime_mode", "manifest"),
    (
        (MEM0_OSS_RUNTIME_MODE, lambda: _witnessed_manifest(datetime.now(UTC))),
        (
            MEM0_MANAGED_PLATFORM_RUNTIME_MODE,
            lambda: _oss_witnessed_manifest(datetime.now(UTC)),
        ),
        (
            MEM0_MANAGED_PLATFORM_RUNTIME_MODE,
            lambda: _oss_v3_witnessed_manifest(datetime.now(UTC)),
        ),
    ),
)
def test_cross_mode_runtime_attestations_fail_closed(
    expected_runtime_mode: str,
    manifest: object,
) -> None:
    factory = manifest
    assert callable(factory)
    adapter = _adapter(
        _transport([], factory()),
        expected_runtime_mode=expected_runtime_mode,
    )

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        adapter.attest(
            run_id=RUN_ID,
            probe_nonce_sha256=_NONCE_SHA,
            target_identity_sha256=TARGET_SHA,
        )

    assert raised.value.code == "managed_mem0_runtime_capability_invalid"


def test_invalid_expected_runtime_mode_fails_before_transport_open() -> None:
    transport = _Transport([], {})

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        _adapter(transport, expected_runtime_mode="ambient")

    assert raised.value.code == "managed_mem0_runtime_configuration_invalid"
    assert transport.opened is False


def test_unsafe_target_is_rejected_before_transport_open() -> None:
    transport = _LeakingTransport("must-not-open")

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        ManagedMem0RuntimeAttestationPort(
            base_url="http://private.example.test",
            benchmark_probe_token=_PROBE_TOKEN,
            probe_nonce=NONCE,
            timeout_seconds=0.5,
            deadline_budget_seconds=60.0,
            monotonic_clock=lambda: 100.0,
            expected_implementation_sha256=_IMPLEMENTATION_SHA,
            vetted_transport=transport,
        )

    assert raised.value.code == "managed_mem0_runtime_target_unsafe"
    assert transport.opened is False


def test_base_url_path_is_rejected_before_transport_open() -> None:
    transport = _Transport([], {})

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        ManagedMem0RuntimeAttestationPort(
            base_url=f"{_TARGET_ORIGIN}/tenant-a",
            benchmark_probe_token=_PROBE_TOKEN,
            probe_nonce=NONCE,
            timeout_seconds=0.5,
            deadline_budget_seconds=60.0,
            monotonic_clock=lambda: 100.0,
            expected_implementation_sha256=_IMPLEMENTATION_SHA,
            allowed_target_hosts=("mem0.example.test",),
            vetted_transport=transport,
        )

    assert raised.value.code == "managed_mem0_runtime_target_unsafe"
    assert transport.opened is False


@pytest.mark.parametrize("nonce", ("too-short", "n" * 257))
def test_private_nonce_bounds_fail_before_transport_open(nonce: str) -> None:
    transport = _Transport([], {})

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        ManagedMem0RuntimeAttestationPort(
            base_url=TARGET_URL,
            benchmark_probe_token=_PROBE_TOKEN,
            probe_nonce=nonce,
            timeout_seconds=0.5,
            deadline_budget_seconds=60.0,
            monotonic_clock=lambda: 100.0,
            expected_implementation_sha256=_IMPLEMENTATION_SHA,
            allowed_target_hosts=("mem0.example.test",),
            vetted_transport=transport,
        )

    assert raised.value.code == "managed_mem0_runtime_configuration_invalid"
    assert transport.opened is False


def test_adapter_and_probe_failure_do_not_leak_token_or_raw_nonce() -> None:
    secret_marker = f"{_PROBE_TOKEN}:{NONCE}"
    transport = _LeakingTransport(secret_marker)
    adapter = _adapter(transport)

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        adapter.attest(
            run_id=RUN_ID,
            probe_nonce_sha256=_NONCE_SHA,
            target_identity_sha256=TARGET_SHA,
        )

    rendered = " ".join((repr(adapter), repr(raised.value), str(raised.value)))
    assert _PROBE_TOKEN not in rendered
    assert NONCE not in rendered
    assert secret_marker not in rendered
    assert raised.value.code == "managed_mem0_runtime_probe_failed"


def test_private_binding_is_one_shot_even_after_rejected_attempt() -> None:
    transport = _Transport([], {})
    adapter = _adapter(transport)
    with pytest.raises(ManagedMem0RuntimeHttpError):
        adapter.attest(
            run_id=RUN_ID,
            probe_nonce_sha256="0" * 64,
            target_identity_sha256=TARGET_SHA,
        )

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        adapter.attest(
            run_id=RUN_ID,
            probe_nonce_sha256=_NONCE_SHA,
            target_identity_sha256=TARGET_SHA,
        )

    assert raised.value.code == "managed_mem0_runtime_already_used"
    assert transport.opened is False


def test_utc_clock_has_safe_stable_provenance_and_aware_time() -> None:
    clock = ManagedUtcClockPort()

    before = datetime.now(UTC)
    observed = clock.now()
    after = datetime.now(UTC)

    assert before <= observed <= after
    assert observed.tzinfo is not None
    assert clock.adapter_id == "managed.utc.clock.v1"
    assert len(clock.implementation_sha256) == 64
    assert repr(clock) == "ManagedUtcClockPort()"


def test_adapter_provenance_commits_the_exact_loaded_source() -> None:
    adapter = _adapter(_Transport([], {}))

    assert adapter.implementation_sha256 == _IMPLEMENTATION_SHA
    changed_source = _IMPLEMENTATION_SOURCE + b"\n# simulated source change\n"
    assert hashlib.sha256(changed_source).hexdigest() != adapter.implementation_sha256


def test_expected_implementation_mismatch_fails_before_transport_open() -> None:
    transport = _Transport([], {})

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        ManagedMem0RuntimeAttestationPort(
            base_url=_TARGET_ORIGIN,
            benchmark_probe_token=_PROBE_TOKEN,
            probe_nonce=NONCE,
            timeout_seconds=0.5,
            deadline_budget_seconds=60.0,
            monotonic_clock=lambda: 100.0,
            expected_implementation_sha256="0" * 64,
            allowed_target_hosts=("mem0.example.test",),
            vetted_transport=transport,
        )

    assert raised.value.code == "managed_mem0_runtime_implementation_mismatch"
    assert transport.opened is False


def _adapter(
    transport: object,
    *,
    expected_runtime_mode: str = MEM0_MANAGED_PLATFORM_RUNTIME_MODE,
) -> ManagedMem0RuntimeAttestationPort:
    return ManagedMem0RuntimeAttestationPort(
        base_url=_TARGET_ORIGIN,
        benchmark_probe_token=_PROBE_TOKEN,
        probe_nonce=NONCE,
        timeout_seconds=0.5,
        deadline_budget_seconds=60.0,
        monotonic_clock=lambda: 100.0,
        expected_implementation_sha256=_IMPLEMENTATION_SHA,
        allowed_target_hosts=("mem0.example.test",),
        vetted_transport=transport,  # type: ignore[arg-type]
        expected_runtime_mode=expected_runtime_mode,
    )


def _transport(
    calls: list[tuple[str, str, object, object]],
    manifest: dict[str, object],
) -> _Transport:
    return _Transport(
        calls,
        {
            ("GET", "/openapi.json"): _Response(200, _refreshable_openapi()),
            ("POST", MEM0_BENCHMARK_ATTESTATION_REFRESH_PATH): _Response(200, manifest),
        },
    )


def _probe_oss_v3_refresh(manifest: dict[str, object]):
    return probe_mem0_api(
        _TARGET_ORIGIN,
        require_timestamp=True,
        require_runtime_contract=True,
        timeout_seconds=0.5,
        refresh_runtime_attestation=True,
        benchmark_probe_token=_PROBE_TOKEN,
        run_id=RUN_ID,
        probe_nonce=NONCE,
        allowed_target_hosts=("mem0.example.test",),
        vetted_transport=_transport([], manifest),
    )


def _witnessed_manifest(
    now: datetime,
    *,
    runtime_mode: str = "managed_platform",
) -> dict[str, object]:
    manifest = _runtime_manifest(now)
    manifest["runtime_mode"] = runtime_mode
    return _signed_manifest(manifest)


def _oss_witnessed_manifest(now: datetime) -> dict[str, object]:
    checked_at = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    manifest = _valid_capabilities()
    timestamp = manifest["timestamp"]
    assert isinstance(timestamp, dict)
    timestamp["attestation"] = {
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
    }
    manifest["refresh_binding"] = {
        "status": "passed",
        "run_id_sha256": hashlib.sha256(RUN_ID.encode()).hexdigest(),
        "probe_nonce_sha256": hashlib.sha256(NONCE.encode()).hexdigest(),
        "target_identity_sha256": TARGET_SHA,
        "refreshed_at": checked_at,
    }
    return _signed_manifest(manifest)


def _oss_v3_witnessed_manifest(now: datetime) -> dict[str, object]:
    checked_at = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    manifest = valid_v3_capabilities()
    timestamp = manifest["timestamp"]
    identity = manifest["persisted_source_identity"]
    assert isinstance(timestamp, dict)
    assert isinstance(identity, dict)
    timestamp["attestation"] = {
        "status": "passed",
        "checked_at": checked_at,
        "metadata_created_at_roundtrip_attested": True,
        "cleanup_succeeded": True,
    }
    identity.update(
        {
            "source_id_roundtrip_attested": True,
            "source_sha256_roundtrip_attested": True,
        }
    )
    manifest["refresh_binding"] = {
        "status": "passed",
        "run_id_sha256": hashlib.sha256(RUN_ID.encode()).hexdigest(),
        "probe_nonce_sha256": hashlib.sha256(NONCE.encode()).hexdigest(),
        "target_identity_sha256": TARGET_SHA,
        "refreshed_at": checked_at,
    }
    integrity = manifest["integrity"]
    assert isinstance(integrity, dict)
    integrity_sha256 = mem0_oss_runtime_manifest_sha256(manifest)
    assert integrity_sha256 is not None
    integrity["manifest_sha256"] = integrity_sha256
    return _signed_manifest(manifest)


def _oss_v4_witnessed_manifest(now: datetime) -> dict[str, object]:
    checked_at = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    manifest = valid_v4_capabilities()
    timestamp = manifest["timestamp"]
    identity = manifest["persisted_source_identity"]
    assert isinstance(timestamp, dict)
    assert isinstance(identity, dict)
    timestamp["attestation"] = {
        "status": "passed",
        "checked_at": checked_at,
        "metadata_created_at_roundtrip_attested": True,
        "cleanup_succeeded": True,
    }
    identity.update(
        {
            "source_id_roundtrip_attested": True,
            "source_sha256_roundtrip_attested": True,
        }
    )
    manifest["refresh_binding"] = {
        "status": "passed",
        "run_id_sha256": hashlib.sha256(RUN_ID.encode()).hexdigest(),
        "probe_nonce_sha256": hashlib.sha256(NONCE.encode()).hexdigest(),
        "target_identity_sha256": TARGET_SHA,
        "refreshed_at": checked_at,
    }
    integrity = manifest["integrity"]
    assert isinstance(integrity, dict)
    integrity_sha256 = mem0_oss_v4_runtime_manifest_sha256(manifest)
    assert integrity_sha256 is not None
    integrity["manifest_sha256"] = integrity_sha256
    return _signed_manifest(manifest)


def _signed_manifest(manifest: dict[str, object]) -> dict[str, object]:
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
    manifest["refresh_witness"] = {
        "algorithm": "hmac-sha256",
        "manifest_fingerprint_sha256": manifest_fingerprint,
        "signature": hmac.new(_PROBE_TOKEN.encode(), message, hashlib.sha256).hexdigest(),
    }
    return manifest


class _LeakingTransport:
    def __init__(self, secret_marker: str) -> None:
        self.secret_marker = secret_marker
        self.opened = False

    def open_client(self, *, base_url: str, timeout_seconds: float) -> object:
        del base_url, timeout_seconds
        self.opened = True
        raise RuntimeError(self.secret_marker)


class _FakeMonotonic:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class _TimeoutRecordingTransport(_Transport):
    def __init__(
        self,
        calls: list[tuple[str, str, object, object]],
        responses: dict[tuple[str, str], _Response],
    ) -> None:
        super().__init__(calls, responses)
        self.timeouts: list[float] = []

    def open_client(self, *, base_url: str, timeout_seconds: float):
        self.timeouts.append(timeout_seconds)
        return super().open_client(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )


def _deadline_adapter(
    transport: object,
    clock: _FakeMonotonic,
    *,
    timeout_seconds: float,
    deadline_budget_seconds: float,
) -> ManagedMem0RuntimeAttestationPort:
    return ManagedMem0RuntimeAttestationPort(
        base_url=_TARGET_ORIGIN,
        benchmark_probe_token=_PROBE_TOKEN,
        probe_nonce=NONCE,
        timeout_seconds=timeout_seconds,
        deadline_budget_seconds=deadline_budget_seconds,
        monotonic_clock=clock,
        expected_implementation_sha256=_IMPLEMENTATION_SHA,
        allowed_target_hosts=("mem0.example.test",),
        vetted_transport=transport,  # type: ignore[arg-type]
    )


def test_attest_shrinks_transport_timeout_to_exact_monotonic_remaining() -> None:
    calls: list[tuple[str, str, object, object]] = []
    responses = {
        ("GET", "/openapi.json"): _Response(200, _refreshable_openapi()),
        (
            "POST",
            MEM0_BENCHMARK_ATTESTATION_REFRESH_PATH,
        ): _Response(200, _witnessed_manifest(datetime.now(UTC))),
    }
    transport = _TimeoutRecordingTransport(calls, responses)
    clock = _FakeMonotonic(100.0)
    adapter = _deadline_adapter(
        transport,
        clock,
        timeout_seconds=4.0,
        deadline_budget_seconds=5.0,
    )
    descriptor = adapter.authority_descriptor()
    assert descriptor.deadline_budget_seconds == 5.0
    assert descriptor.deadline_policy == "monotonic-hard-deadline.v1"
    assert descriptor.minimum_network_timeout_seconds == 0.001

    clock.value = 102.0
    adapter.attest(
        run_id=RUN_ID,
        probe_nonce_sha256=_NONCE_SHA,
        target_identity_sha256=TARGET_SHA,
    )

    assert transport.timeouts == [3.0]


@pytest.mark.parametrize("elapsed", (1.0, 0.9995))
def test_expired_or_too_small_deadline_burns_claim_before_any_transport(
    elapsed: float,
) -> None:
    transport = _Transport([], {})
    clock = _FakeMonotonic(10.0)
    adapter = _deadline_adapter(
        transport,
        clock,
        timeout_seconds=0.5,
        deadline_budget_seconds=1.0,
    )
    descriptor = adapter.authority_descriptor()
    clock.value += elapsed

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        adapter.attest(
            run_id=RUN_ID,
            probe_nonce_sha256=_NONCE_SHA,
            target_identity_sha256=TARGET_SHA,
        )

    assert raised.value.code == "managed_mem0_runtime_deadline_exceeded"
    assert transport.opened is False
    with pytest.raises(ManagedMem0RuntimeHttpError) as replay:
        adapter.attest(
            run_id=RUN_ID,
            probe_nonce_sha256=descriptor.probe_nonce_sha256,
            target_identity_sha256=descriptor.target_identity_sha256,
        )
    assert replay.value.code == "managed_mem0_runtime_already_used"


@pytest.mark.parametrize(
    "budget",
    (True, 0.0, 0.0005, float("nan"), float("inf"), 172_801.0),
)
def test_invalid_deadline_budget_fails_before_transport_open(budget: object) -> None:
    transport = _Transport([], {})

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        ManagedMem0RuntimeAttestationPort(
            base_url=_TARGET_ORIGIN,
            benchmark_probe_token=_PROBE_TOKEN,
            probe_nonce=NONCE,
            timeout_seconds=0.5,
            deadline_budget_seconds=budget,  # type: ignore[arg-type]
            monotonic_clock=lambda: 100.0,
            expected_implementation_sha256=_IMPLEMENTATION_SHA,
            allowed_target_hosts=("mem0.example.test",),
            vetted_transport=transport,
        )

    assert raised.value.code == "managed_mem0_runtime_configuration_invalid"
    assert transport.opened is False


@pytest.mark.parametrize("observed", (True, float("nan"), float("inf"), "now"))
def test_invalid_monotonic_clock_fails_before_transport_open(observed: object) -> None:
    transport = _Transport([], {})

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        ManagedMem0RuntimeAttestationPort(
            base_url=_TARGET_ORIGIN,
            benchmark_probe_token=_PROBE_TOKEN,
            probe_nonce=NONCE,
            timeout_seconds=0.5,
            deadline_budget_seconds=10.0,
            monotonic_clock=lambda: observed,  # type: ignore[return-value]
            expected_implementation_sha256=_IMPLEMENTATION_SHA,
            allowed_target_hosts=("mem0.example.test",),
            vetted_transport=transport,
        )

    assert raised.value.code == "managed_mem0_runtime_configuration_invalid"
    assert transport.opened is False
