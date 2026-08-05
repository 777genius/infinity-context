from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from infinity_context_server import memory_comparison_managed_mem0_oss_usage_http as subject
from infinity_context_server.memory_comparison_mem0_oss_ingress import (
    inspect_mem0_oss_ingress_authority,
    issue_mem0_oss_ingress_credential_authority,
)
from infinity_context_server.memory_comparison_mem0_oss_usage_attestation import (
    MEM0_OSS_USAGE_ATTESTATION_SCHEMA_VERSION,
    MEM0_OSS_USAGE_WITNESS_CONTEXT,
    Mem0OssUsageAttestationRequest,
    verify_mem0_oss_usage_attestation,
)

_NOW = datetime(2026, 8, 4, 12, 0, 1, tzinfo=UTC)
_RUN_ID = "hosted-canary-1"
_NONCE = "a" * 64
_TARGET_URL = "http://127.0.0.1:8888"
_PROBE_TOKEN = "private-probe-token"
_INGRESS_KEY = "private-ingress-key"


def test_usage_http_port_consumes_exact_ingress_lane_once_and_hides_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    target = inspect_mem0_oss_ingress_authority(authority).target_identity_sha256
    verified = _verified(target)
    captured: dict[str, object] = {}

    def fake_probe(*args: object, **kwargs: object):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            passed=True,
            details={"verified_usage_attestation": verified},
        )

    monkeypatch.setattr(subject, "probe_mem0_oss_usage_attestation", fake_probe)
    port = subject.ManagedMem0OssUsageAttestationPort(
        base_url=_TARGET_URL,
        benchmark_probe_token=_PROBE_TOKEN,
        probe_nonce=_NONCE,
        ingress_authority=authority,
        timeout_seconds=10,
        deadline=_NOW + timedelta(seconds=10),
        clock=lambda: _NOW,
        allowed_target_hosts=("127.0.0.1",),
    )

    result = port.attest(
        run_id=_RUN_ID,
        target_identity_sha256=target,
    )

    assert result is verified
    assert captured["args"] == (_TARGET_URL,)
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["benchmark_probe_token"] == _PROBE_TOKEN
    assert kwargs["ingress_api_key"] == _INGRESS_KEY
    assert kwargs["timeout_seconds"] == 10
    assert kwargs["validated_at"] == _NOW
    assert _PROBE_TOKEN not in repr(port)
    assert _INGRESS_KEY not in repr(port)
    with pytest.raises(subject.ManagedMem0OssUsageHttpError, match="already_used"):
        port.attest(run_id=_RUN_ID, target_identity_sha256=target)


def test_usage_http_port_wrong_binding_burns_before_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    port = subject.ManagedMem0OssUsageAttestationPort(
        base_url=_TARGET_URL,
        benchmark_probe_token=_PROBE_TOKEN,
        probe_nonce=_NONCE,
        ingress_authority=authority,
        timeout_seconds=10,
        deadline=_NOW + timedelta(seconds=10),
        clock=lambda: _NOW,
        allowed_target_hosts=("127.0.0.1",),
    )
    monkeypatch.setattr(
        subject,
        "probe_mem0_oss_usage_attestation",
        lambda *_args, **_kwargs: pytest.fail("probe must stay closed"),
    )

    with pytest.raises(subject.ManagedMem0OssUsageHttpError, match="binding_invalid"):
        port.attest(run_id=_RUN_ID, target_identity_sha256="0" * 64)


def test_usage_http_port_caps_probe_to_the_remaining_absolute_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    target = inspect_mem0_oss_ingress_authority(authority).target_identity_sha256
    captured: dict[str, object] = {}

    def fake_probe(*_args: object, **kwargs: object):
        captured.update(kwargs)
        return SimpleNamespace(
            passed=True,
            details={"verified_usage_attestation": _verified(target)},
        )

    monkeypatch.setattr(subject, "probe_mem0_oss_usage_attestation", fake_probe)
    port = subject.ManagedMem0OssUsageAttestationPort(
        base_url=_TARGET_URL,
        benchmark_probe_token=_PROBE_TOKEN,
        probe_nonce=_NONCE,
        ingress_authority=authority,
        timeout_seconds=10,
        deadline=_NOW + timedelta(seconds=3),
        clock=lambda: _NOW,
        allowed_target_hosts=("127.0.0.1",),
    )

    port.attest(run_id=_RUN_ID, target_identity_sha256=target)

    assert captured["timeout_seconds"] == 3
    assert captured["validated_at"] == _NOW


def test_expired_usage_deadline_burns_the_one_shot_claim_before_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    target = inspect_mem0_oss_ingress_authority(authority).target_identity_sha256
    port = subject.ManagedMem0OssUsageAttestationPort(
        base_url=_TARGET_URL,
        benchmark_probe_token=_PROBE_TOKEN,
        probe_nonce=_NONCE,
        ingress_authority=authority,
        timeout_seconds=10,
        deadline=_NOW,
        clock=lambda: _NOW,
        allowed_target_hosts=("127.0.0.1",),
    )
    monkeypatch.setattr(
        subject,
        "probe_mem0_oss_usage_attestation",
        lambda *_args, **_kwargs: pytest.fail("expired usage proof must not probe"),
    )

    with pytest.raises(subject.ManagedMem0OssUsageHttpError, match="deadline_exceeded"):
        port.attest(run_id=_RUN_ID, target_identity_sha256=target)
    with pytest.raises(subject.ManagedMem0OssUsageHttpError, match="already_used"):
        port.attest(run_id=_RUN_ID, target_identity_sha256=target)


def test_usage_deadline_is_rechecked_after_ingress_claim_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    target = inspect_mem0_oss_ingress_authority(authority).target_identity_sha256
    observed_now = [_NOW]
    deadline = _NOW + timedelta(seconds=3)
    port = subject.ManagedMem0OssUsageAttestationPort(
        base_url=_TARGET_URL,
        benchmark_probe_token=_PROBE_TOKEN,
        probe_nonce=_NONCE,
        ingress_authority=authority,
        timeout_seconds=10,
        deadline=deadline,
        clock=lambda: observed_now[0],
        allowed_target_hosts=("127.0.0.1",),
    )

    def delayed_ingress(*_args: object, **_kwargs: object) -> str:
        observed_now[0] = deadline
        return _INGRESS_KEY

    monkeypatch.setattr(subject, "_consume_mem0_oss_ingress_usage_probe", delayed_ingress)
    monkeypatch.setattr(
        subject,
        "probe_mem0_oss_usage_attestation",
        lambda *_args, **_kwargs: pytest.fail("expired usage proof must not probe"),
    )

    with pytest.raises(subject.ManagedMem0OssUsageHttpError, match="deadline_exceeded"):
        port.attest(run_id=_RUN_ID, target_identity_sha256=target)


def _authority():
    return issue_mem0_oss_ingress_credential_authority(
        run_id=_RUN_ID,
        base_url=_TARGET_URL,
        ingress_api_key=_INGRESS_KEY,
        allowed_target_hosts=("127.0.0.1",),
    )


def _verified(target: str):
    attested_at = "2026-08-04T12:00:00.000Z"
    usage = {
        "mode": "raw_passthrough",
        "operation_count": 1,
        "extraction_calls": 0,
        "request_bytes": 0,
        "response_bytes": 0,
        "model": "gpt-5.6-sol",
        "first_operation_at": "2026-08-04T12:00:00.000Z",
        "last_operation_at": "2026-08-04T12:00:00.000Z",
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            {"attested_at": attested_at, "usage": usage},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    request = Mem0OssUsageAttestationRequest(
        run_id=_RUN_ID,
        probe_nonce=_NONCE,
        target_identity_sha256=target,
    )
    run_hash = hashlib.sha256(_RUN_ID.encode()).hexdigest()
    nonce_hash = hashlib.sha256(_NONCE.encode()).hexdigest()
    signature = hmac.new(
        _PROBE_TOKEN.encode(),
        "\n".join(
            (
                MEM0_OSS_USAGE_WITNESS_CONTEXT,
                run_hash,
                nonce_hash,
                target,
                attested_at,
                fingerprint,
            )
        ).encode(),
        hashlib.sha256,
    ).hexdigest()
    return verify_mem0_oss_usage_attestation(
        {
            "schema_version": MEM0_OSS_USAGE_ATTESTATION_SCHEMA_VERSION,
            "run_id_sha256": run_hash,
            "probe_nonce_sha256": nonce_hash,
            "target_identity_sha256": target,
            "attested_at": attested_at,
            "usage": usage,
            "usage_fingerprint_sha256": fingerprint,
            "algorithm": "hmac-sha256",
            "signature": signature,
        },
        benchmark_probe_token=_PROBE_TOKEN,
        request=request,
        validated_at=_NOW,
    )
