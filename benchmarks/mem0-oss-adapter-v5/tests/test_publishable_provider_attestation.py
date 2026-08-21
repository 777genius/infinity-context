from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

import pytest
from publishable_mem0_v5 import provider_attestation as provider_subject
from publishable_mem0_v5.config import PublishableLaneConfig
from publishable_mem0_v5.provider_attestation import (
    ProviderAttestationError,
    ProviderFreeRuntimeAttestor,
)
from test_publishable_docker_acceptance import _acceptance_config, _canonical_json

from mem0_oss_adapter_v5 import runtime_attestation as runtime_contract


class SignedRuntimeAttestationTransport:
    def __init__(
        self,
        config: PublishableLaneConfig,
        secret: bytes,
        *,
        provider_calls: object = 0,
        requested_output_tokens: object = 4096,
        validity_seconds: int | None = None,
    ) -> None:
        self.config = config
        self.secret = secret
        self.provider_calls = provider_calls
        self.requested_output_tokens = requested_output_tokens
        self.validity_seconds = validity_seconds
        self.calls: list[tuple[str, int, str]] = []

    def post(
        self,
        *,
        host: str,
        port: int,
        path: str,
        body: bytes,
        headers: Any,
    ) -> bytes:
        self.calls.append((host, port, path))
        request = json.loads(body)
        request_sha256 = hashlib.sha256(body).hexdigest()
        expected_auth = hmac.new(
            self.secret,
            provider_subject._AUTHENTICATION_DOMAIN,
            hashlib.sha256,
        ).hexdigest()
        expected_idempotency = hashlib.sha256(
            provider_subject._IDEMPOTENCY_DOMAIN + bytes.fromhex(request_sha256)
        ).hexdigest()
        assert headers["Authorization"] == f"Bearer {expected_auth}"
        assert headers["X-Request-Commitment-SHA256"] == request_sha256
        assert headers["Idempotency-Key"] == expected_idempotency
        static = {
            "expected_account_binding_hmac_sha256": (
                self.config.bridges[0].account_binding_hmac_sha256
            ),
            "expected_base_instructions_sha256": provider_subject.BASE_INSTRUCTIONS_SHA256,
            "extraction_response_format_sha256": "1" * 64,
            "extraction_response_schema_sha256": "2" * 64,
            "extraction_system_prompt_sha256": "3" * 64,
            "output_limit_enforced": False,
            "phase_c_infinity_commit_sha1": "4" * 40,
            "phase_c_infinity_tree_sha1": "5" * 40,
            "phase_c_release_manifest_sha256": "6" * 64,
            "requested_output_tokens": self.requested_output_tokens,
            "route_contract_sha256": provider_subject._ROUTE_CONTRACT_SHA256,
            "runtime_binding_commitment_sha256": "7" * 64,
            "runtime_route_binding_sha256": "8" * 64,
            "runtime_source_sha256": "9" * 64,
            "runtime_transport_origin_sha256": provider_subject._RUNTIME_TRANSPORT_ORIGIN_SHA256,
            "source_closure_sha256": "a" * 64,
            "source_commit_sha1": "b" * 40,
            "source_manifest_sha256": self.config.source_manifest_sha256,
            "source_tree_sha1": "c" * 40,
            "subscription_runtime_binding_commitment_sha256": "d" * 64,
            "usage_attestation_required": False,
        }
        implementation = hashlib.sha256(
            _canonical_json(
                {
                    "schema_version": provider_subject._IMPLEMENTATION_SCHEMA,
                    **static,
                }
            )
        ).hexdigest()
        unsigned = {
            "schema_version": provider_subject._RESPONSE_SCHEMA,
            "service": "mem0-oss-adapter-v5",
            **static,
            "target_origin_sha256": request["target_origin_sha256"],
            "run_id_sha256": request["run_id_sha256"],
            "probe_nonce_sha256": request["probe_nonce_sha256"],
            "implementation_binding_sha256": implementation,
            "issued_at_unix": 1_900_000_000,
            "expires_at_unix": 1_900_000_000
            + (
                request["validity_seconds"]
                if self.validity_seconds is None
                else self.validity_seconds
            ),
            "provider_calls": self.provider_calls,
        }
        signing_key = hmac.new(
            self.secret,
            provider_subject._KEY_DOMAIN,
            hashlib.sha256,
        ).digest()
        signature = hmac.new(
            signing_key,
            provider_subject._SIGNATURE_DOMAIN + _canonical_json(unsigned),
            hashlib.sha256,
        ).hexdigest()
        return _canonical_json({**unsigned, "attestation_hmac_sha256": signature})


def test_authenticated_runtime_probe_binds_source_sha_and_zero_provider_calls(
    tmp_path: Path,
) -> None:
    config, _proc_root, _config_file = _acceptance_config(tmp_path)
    secret = b"runtime-attestation-root-secret-value"
    secret_path = config.paths.adapter_secret_dir / "runtime-attestation-secret"
    secret_path.write_bytes(secret)
    secret_path.chmod(0o600)
    transport = SignedRuntimeAttestationTransport(config, secret)
    attestor = ProviderFreeRuntimeAttestor(
        config,
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
        transport=transport,
        clock=lambda: 1_900_000_000.0,
        nonce=lambda _size: b"n" * 32,
    )

    evidence = attestor.attest(
        fleet_mode="create",
        runtime_attestation_sha256="e" * 64,
    )

    assert transport.calls == [("127.0.0.1", config.host_adapter_port, "/v5/runtime/attest")]
    assert evidence.source_commit_sha1 == "b" * 40
    assert evidence.source_tree_sha1 == "c" * 40
    payload = json.loads(evidence.path.read_bytes())
    assert payload["fleet_mode"] == "create"
    assert payload["runtime_attestation_sha256"] == "e" * 64
    assert payload["response"]["provider_calls"] == 0
    assert attestor.require_unchanged(evidence) == evidence

    tampered_transport = SignedRuntimeAttestationTransport(config, secret, provider_calls=1)
    tampered_attestor = ProviderFreeRuntimeAttestor(
        config,
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
        transport=tampered_transport,
        clock=lambda: 1_900_000_000.0,
        nonce=lambda _size: b"x" * 32,
    )
    with pytest.raises(ProviderAttestationError, match="publishable_provider_attestation_invalid"):
        tampered_attestor.attest(
            fleet_mode="reopen",
            runtime_attestation_sha256="f" * 64,
        )


@pytest.mark.parametrize(
    "overrides",
    (
        {"provider_calls": False},
        {"provider_calls": 0.0},
        {"requested_output_tokens": 4096.0},
        {"validity_seconds": 1_199},
    ),
)
def test_authenticated_runtime_probe_rejects_type_and_lifetime_drift(
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    config, _proc_root, _config_file = _acceptance_config(tmp_path)
    secret = b"runtime-attestation-root-secret-value"
    secret_path = config.paths.adapter_secret_dir / "runtime-attestation-secret"
    secret_path.write_bytes(secret)
    secret_path.chmod(0o600)
    attestor = ProviderFreeRuntimeAttestor(
        config,
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
        transport=SignedRuntimeAttestationTransport(config, secret, **overrides),
        clock=lambda: 1_900_000_000.0,
        nonce=lambda _size: b"z" * 32,
    )

    with pytest.raises(ProviderAttestationError, match="publishable_provider_attestation_invalid"):
        attestor.attest(fleet_mode="create", runtime_attestation_sha256="e" * 64)


def test_runtime_probe_protocol_constants_match_the_server_contract() -> None:
    assert provider_subject._REQUEST_SCHEMA == runtime_contract.REQUEST_SCHEMA
    assert provider_subject._RESPONSE_SCHEMA == runtime_contract.RESPONSE_SCHEMA
    assert provider_subject._ATTESTATION_PATH == runtime_contract.ATTESTATION_PATH
    assert provider_subject._ROUTE_CONTRACT_SHA256 == runtime_contract.V5_ROUTE_CONTRACT_SHA256
    assert provider_subject._AUTHENTICATION_DOMAIN == runtime_contract._AUTHENTICATION_DOMAIN
    assert provider_subject._KEY_DOMAIN == runtime_contract._KEY_DOMAIN
    assert provider_subject._IDEMPOTENCY_DOMAIN == runtime_contract._IDEMPOTENCY_DOMAIN
    assert provider_subject._SIGNATURE_DOMAIN == runtime_contract._SIGNATURE_DOMAIN


def test_runtime_probe_uses_one_absolute_wall_clock_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSocket:
        closed = False

        def settimeout(self, _seconds: float) -> None:
            pass

        def send(self, value: memoryview) -> int:
            return len(value)

        def recv(self, _size: int) -> bytes:
            raise AssertionError("deadline must expire before receive")

        def close(self) -> None:
            self.closed = True

    connection = FakeSocket()
    observed = iter((0.0, 0.1, 10.01))
    monkeypatch.setattr(provider_subject.time, "monotonic", lambda: next(observed))
    monkeypatch.setattr(
        provider_subject.socket,
        "create_connection",
        lambda *_args, **_kwargs: connection,
    )

    with pytest.raises(
        ProviderAttestationError, match="publishable_provider_attestation_unavailable"
    ):
        provider_subject.LoopbackRuntimeProbeTransport().post(
            host="127.0.0.1",
            port=8891,
            path="/v5/runtime/attest",
            body=b"{}",
            headers={"Connection": "close", "Content-Type": "application/json"},
        )
    assert connection.closed
