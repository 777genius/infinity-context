from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from infinity_context_server.memory_comparison_mem0_oss_usage_attestation import (
    MEM0_OSS_MAX_USAGE_OPERATIONS,
    MEM0_OSS_USAGE_ATTESTATION_SCHEMA_VERSION,
    MEM0_OSS_USAGE_WITNESS_CONTEXT,
    Mem0OssUsageAttestationError,
    Mem0OssUsageAttestationRequest,
    VerifiedMem0OssUsageAttestation,
    verify_mem0_oss_usage_attestation,
)

_NOW = datetime(2026, 8, 4, 12, 0, 1, tzinfo=UTC)
_RUN_ID = "hosted-canary-1"
_NONCE = "a" * 64
_TARGET = "b" * 64
_TOKEN = "private-probe-token"


@pytest.mark.parametrize(
    ("mode", "operation_count", "extraction_calls"),
    (
        ("raw_passthrough", 1, 0),
        ("raw_passthrough", MEM0_OSS_MAX_USAGE_OPERATIONS, 0),
        ("subscription_llm", 1, 1),
    ),
)
def test_usage_attestation_verifies_exact_single_add_modes(
    mode: str,
    operation_count: int,
    extraction_calls: int,
) -> None:
    request = _request()
    payload = _signed_payload(
        mode=mode,
        operation_count=operation_count,
        extraction_calls=extraction_calls,
    )

    verified = verify_mem0_oss_usage_attestation(
        payload,
        benchmark_probe_token=_TOKEN,
        request=request,
        validated_at=_NOW,
    )

    assert type(verified) is VerifiedMem0OssUsageAttestation
    assert verified.evidence.mode == mode
    assert verified.evidence.operation_count == operation_count
    assert verified.evidence.extraction_calls == extraction_calls
    public = verified.public_payload()
    assert public["run_id_sha256"] == hashlib.sha256(_RUN_ID.encode()).hexdigest()
    rendered = json.dumps(public, sort_keys=True)
    assert _TOKEN not in rendered
    assert _RUN_ID not in rendered
    assert _NONCE not in rendered
    assert payload["signature"] not in rendered


@pytest.mark.parametrize(
    ("path", "value", "code"),
    (
        (("run_id_sha256",), "0" * 64, "mem0_oss_usage_binding_invalid"),
        (("probe_nonce_sha256",), "0" * 64, "mem0_oss_usage_binding_invalid"),
        (("target_identity_sha256",), "0" * 64, "mem0_oss_usage_binding_invalid"),
        (("usage", "operation_count"), 0, "mem0_oss_usage_invariant_invalid"),
        (
            ("usage", "operation_count"),
            MEM0_OSS_MAX_USAGE_OPERATIONS + 1,
            "mem0_oss_usage_invariant_invalid",
        ),
        (("usage", "operation_count"), True, "mem0_oss_usage_invariant_invalid"),
        (("usage", "extraction_calls"), 1, "mem0_oss_usage_invariant_invalid"),
        (("usage", "request_bytes"), 1, "mem0_oss_usage_invariant_invalid"),
        (("usage", "response_bytes"), 1, "mem0_oss_usage_invariant_invalid"),
        (("usage", "model"), "gpt-5", "mem0_oss_usage_invariant_invalid"),
        (("usage_fingerprint_sha256",), "0" * 64, "mem0_oss_usage_fingerprint_invalid"),
        (("signature",), "0" * 64, "mem0_oss_usage_signature_invalid"),
    ),
)
def test_usage_attestation_rejects_binding_invariant_and_signature_mutations(
    path: tuple[str, ...],
    value: object,
    code: str,
) -> None:
    payload = _signed_payload()
    target: dict[str, object] = payload
    for key in path[:-1]:
        child = target[key]
        assert isinstance(child, dict)
        target = child
    target[path[-1]] = value

    with pytest.raises(Mem0OssUsageAttestationError) as caught:
        verify_mem0_oss_usage_attestation(
            payload,
            benchmark_probe_token=_TOKEN,
            request=_request(),
            validated_at=_NOW,
        )

    assert caught.value.code == code
    assert _TOKEN not in repr(caught.value)


@pytest.mark.parametrize("location", ("response", "usage"))
def test_usage_attestation_requires_exact_field_sets(location: str) -> None:
    payload = _signed_payload()
    if location == "response":
        payload["unexpected"] = "private"
    else:
        usage = payload["usage"]
        assert isinstance(usage, dict)
        usage["unexpected"] = "private"

    with pytest.raises(Mem0OssUsageAttestationError) as caught:
        verify_mem0_oss_usage_attestation(
            payload,
            benchmark_probe_token=_TOKEN,
            request=_request(),
            validated_at=_NOW,
        )

    assert caught.value.code in {
        "mem0_oss_usage_response_invalid",
        "mem0_oss_usage_invariant_invalid",
    }
    assert "private" not in repr(caught.value)


@pytest.mark.parametrize(
    ("run_id", "nonce"),
    (("a" * 161, _NONCE), (_RUN_ID, "A" * 64), (_RUN_ID, "a" * 63)),
)
def test_usage_request_matches_adapter_safe_identifier_and_hex_nonce(
    run_id: str,
    nonce: str,
) -> None:
    with pytest.raises(Mem0OssUsageAttestationError) as caught:
        Mem0OssUsageAttestationRequest(
            run_id=run_id,
            probe_nonce=nonce,
            target_identity_sha256=_TARGET,
        )
    assert caught.value.code == "mem0_oss_usage_request_invalid"


def test_usage_attestation_rejects_stale_or_non_millisecond_timestamps() -> None:
    stale = _signed_payload(attested_at=_NOW - timedelta(seconds=121))
    future = _signed_payload(attested_at=_NOW + timedelta(seconds=6))
    malformed = _signed_payload()
    malformed["attested_at"] = "2026-08-04T12:00:00Z"
    _reseal(malformed)

    with pytest.raises(Mem0OssUsageAttestationError, match="timestamp_invalid"):
        verify_mem0_oss_usage_attestation(
            stale,
            benchmark_probe_token=_TOKEN,
            request=_request(),
            validated_at=_NOW,
        )
    with pytest.raises(Mem0OssUsageAttestationError, match="timestamp_invalid"):
        verify_mem0_oss_usage_attestation(
            future,
            benchmark_probe_token=_TOKEN,
            request=_request(),
            validated_at=_NOW,
        )
    with pytest.raises(Mem0OssUsageAttestationError, match="timestamp_invalid"):
        verify_mem0_oss_usage_attestation(
            malformed,
            benchmark_probe_token=_TOKEN,
            request=_request(),
            validated_at=_NOW,
        )


def test_usage_attestation_accepts_historical_operation_interval() -> None:
    payload = _signed_payload(
        operation_at=_NOW - timedelta(days=30),
        attested_at=_NOW - timedelta(seconds=1),
    )

    verified = verify_mem0_oss_usage_attestation(
        payload,
        benchmark_probe_token=_TOKEN,
        request=_request(),
        validated_at=_NOW,
    )

    assert verified.evidence.last_operation_at == "2026-07-05T12:00:01.000Z"
    assert verified.evidence.attested_at == "2026-08-04T12:00:00.000Z"


@pytest.mark.parametrize(
    ("operation_count", "extraction_calls", "request_bytes", "response_bytes"),
    (
        (2, 1, 128, 256),
        (1, 0, 128, 256),
        (1, 1, 0, 256),
        (1, 1, 128, 1_048_577),
    ),
)
def test_usage_attestation_rejects_subscription_invariant_mutations(
    operation_count: int,
    extraction_calls: int,
    request_bytes: int,
    response_bytes: int,
) -> None:
    payload = _signed_payload(
        mode="subscription_llm",
        operation_count=operation_count,
        extraction_calls=extraction_calls,
        request_bytes=request_bytes,
        response_bytes=response_bytes,
    )

    with pytest.raises(Mem0OssUsageAttestationError, match="invariant_invalid"):
        verify_mem0_oss_usage_attestation(
            payload,
            benchmark_probe_token=_TOKEN,
            request=_request(),
            validated_at=_NOW,
        )


def test_usage_attestation_binds_attested_at_to_fingerprint_and_signature() -> None:
    fingerprint_mutation = _signed_payload()
    fingerprint_mutation["attested_at"] = "2026-08-04T12:00:01.000Z"
    signature_mutation = _signed_payload()
    signature_mutation["attested_at"] = "2026-08-04T12:00:01.000Z"
    _reseal_fingerprint_only(signature_mutation)

    with pytest.raises(Mem0OssUsageAttestationError, match="fingerprint_invalid"):
        verify_mem0_oss_usage_attestation(
            fingerprint_mutation,
            benchmark_probe_token=_TOKEN,
            request=_request(),
            validated_at=_NOW,
        )
    with pytest.raises(Mem0OssUsageAttestationError, match="signature_invalid"):
        verify_mem0_oss_usage_attestation(
            signature_mutation,
            benchmark_probe_token=_TOKEN,
            request=_request(),
            validated_at=_NOW,
        )


def test_usage_attestation_rejects_operation_after_attestation() -> None:
    payload = _signed_payload(
        operation_at=_NOW,
        attested_at=_NOW - timedelta(seconds=1),
    )

    with pytest.raises(Mem0OssUsageAttestationError, match="timestamp_invalid"):
        verify_mem0_oss_usage_attestation(
            payload,
            benchmark_probe_token=_TOKEN,
            request=_request(),
            validated_at=_NOW,
        )


def _request() -> Mem0OssUsageAttestationRequest:
    return Mem0OssUsageAttestationRequest(
        run_id=_RUN_ID,
        probe_nonce=_NONCE,
        target_identity_sha256=_TARGET,
    )


def _signed_payload(
    *,
    mode: str = "raw_passthrough",
    operation_count: int = 1,
    extraction_calls: int = 0,
    request_bytes: int | None = None,
    response_bytes: int | None = None,
    operation_at: datetime | None = None,
    attested_at: datetime | None = None,
) -> dict[str, object]:
    instant = (operation_at or (_NOW - timedelta(seconds=1))).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    attested = (attested_at or (_NOW - timedelta(seconds=1))).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    is_subscription = mode == "subscription_llm"
    usage: dict[str, object] = {
        "mode": mode,
        "operation_count": operation_count,
        "extraction_calls": extraction_calls,
        "request_bytes": request_bytes
        if request_bytes is not None
        else (128 if is_subscription else 0),
        "response_bytes": response_bytes
        if response_bytes is not None
        else (256 if is_subscription else 0),
        "model": "gpt-5.6-sol",
        "first_operation_at": instant,
        "last_operation_at": instant,
    }
    payload: dict[str, object] = {
        "schema_version": MEM0_OSS_USAGE_ATTESTATION_SCHEMA_VERSION,
        "run_id_sha256": hashlib.sha256(_RUN_ID.encode()).hexdigest(),
        "probe_nonce_sha256": hashlib.sha256(_NONCE.encode()).hexdigest(),
        "target_identity_sha256": _TARGET,
        "attested_at": attested,
        "usage": usage,
        "usage_fingerprint_sha256": "0" * 64,
        "algorithm": "hmac-sha256",
        "signature": "0" * 64,
    }
    _reseal(payload)
    return deepcopy(payload)


def _reseal(payload: dict[str, object]) -> None:
    _reseal_fingerprint_only(payload)
    fingerprint = str(payload["usage_fingerprint_sha256"])
    message = "\n".join(
        (
            MEM0_OSS_USAGE_WITNESS_CONTEXT,
            str(payload["run_id_sha256"]),
            str(payload["probe_nonce_sha256"]),
            str(payload["target_identity_sha256"]),
            str(payload["attested_at"]),
            fingerprint,
        )
    ).encode()
    payload["signature"] = hmac.new(_TOKEN.encode(), message, hashlib.sha256).hexdigest()


def _reseal_fingerprint_only(payload: dict[str, object]) -> None:
    usage = payload["usage"]
    assert isinstance(usage, dict)
    fingerprint = hashlib.sha256(
        json.dumps(
            {"attested_at": payload["attested_at"], "usage": usage},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    payload["usage_fingerprint_sha256"] = fingerprint
