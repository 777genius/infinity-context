from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import infinity_context_server.memory_comparison_managed_mem0_runtime_http as mem0_runtime_http
import pytest
from infinity_context_server.memory_comparison_managed_mem0_runtime_http import (
    ManagedMem0RuntimeAttestationPort,
    ManagedMem0RuntimeHttpError,
    ManagedUtcClockPort,
)
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    MEM0_MANAGED_PLATFORM_RUNTIME_MODE,
    VerifiedMem0RuntimeAttestationValidation,
    mem0_runtime_attestation_validation_is_publishable,
    public_mem0_runtime_attestation_validation,
)
from infinity_context_server.memory_comparison_service_probes import (
    MEM0_BENCHMARK_ATTESTATION_REFRESH_PATH,
)
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


def test_unsafe_target_is_rejected_before_transport_open() -> None:
    transport = _LeakingTransport("must-not-open")

    with pytest.raises(ManagedMem0RuntimeHttpError) as raised:
        ManagedMem0RuntimeAttestationPort(
            base_url="http://private.example.test",
            benchmark_probe_token=_PROBE_TOKEN,
            probe_nonce=NONCE,
            timeout_seconds=0.5,
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
            expected_implementation_sha256="0" * 64,
            allowed_target_hosts=("mem0.example.test",),
            vetted_transport=transport,
        )

    assert raised.value.code == "managed_mem0_runtime_implementation_mismatch"
    assert transport.opened is False


def _adapter(transport: object) -> ManagedMem0RuntimeAttestationPort:
    return ManagedMem0RuntimeAttestationPort(
        base_url=_TARGET_ORIGIN,
        benchmark_probe_token=_PROBE_TOKEN,
        probe_nonce=NONCE,
        timeout_seconds=0.5,
        expected_implementation_sha256=_IMPLEMENTATION_SHA,
        allowed_target_hosts=("mem0.example.test",),
        vetted_transport=transport,  # type: ignore[arg-type]
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


def _witnessed_manifest(
    now: datetime,
    *,
    runtime_mode: str = "managed_platform",
) -> dict[str, object]:
    manifest = _runtime_manifest(now)
    manifest["runtime_mode"] = runtime_mode
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
