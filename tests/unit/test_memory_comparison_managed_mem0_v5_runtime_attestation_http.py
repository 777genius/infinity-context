from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from pathlib import Path

import httpx
import pytest
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_runtime_attestation as authority,
)
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_runtime_attestation_http as subject,
)
from infinity_context_server.memory_comparison_managed_runtime_validation import (
    MANAGED_MEM0_V5_RUNTIME_FAMILY,
    managed_runtime_validation_is_publishable,
    managed_runtime_validation_view,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _expected() -> subject.ManagedMem0V5ExpectedRuntimeAuthority:
    return subject.ManagedMem0V5ExpectedRuntimeAuthority(
        source_commit_sha1="1" * 40,
        source_tree_sha1="2" * 40,
        source_manifest_sha256=_sha("manifest"),
        source_closure_sha256=_sha("closure"),
        phase_c_infinity_commit_sha1="3" * 40,
        phase_c_infinity_tree_sha1="4" * 40,
        phase_c_release_manifest_sha256=_sha("release"),
        runtime_binding_commitment_sha256=_sha("adapter-binding"),
        subscription_runtime_binding_commitment_sha256=_sha("subscription-binding"),
        runtime_source_sha256=_sha("runtime-source"),
        runtime_route_binding_sha256=_sha("runtime-route"),
        runtime_transport_origin_sha256=_sha("runtime-origin"),
        expected_account_binding_hmac_sha256=_sha("account"),
        expected_base_instructions_sha256=_sha("base"),
        extraction_system_prompt_sha256=_sha("prompt"),
        extraction_response_format_sha256=_sha("format"),
        extraction_response_schema_sha256=_sha("schema"),
        requested_output_tokens=4096,
        output_limit_enforced=False,
        usage_attestation_required=False,
    )


def _signed_response(
    *,
    root_secret: bytes,
    request: dict[str, object],
    expected: subject.ManagedMem0V5ExpectedRuntimeAuthority,
    issued_at_unix: int = 1_000,
) -> dict[str, object]:
    static = expected.public_payload()
    implementation = authority._canonical_sha256(
        {
            "schema_version": "mem0-oss-adapter-v5.implementation-binding.v1",
            "route_contract_sha256": authority._ROUTE_SHA256,
            **static,
        }
    )
    unsigned = {
        "schema_version": authority.RESPONSE_SCHEMA,
        "service": "mem0-oss-adapter-v5",
        "route_contract_sha256": authority._ROUTE_SHA256,
        "target_origin_sha256": request["target_origin_sha256"],
        "run_id_sha256": request["run_id_sha256"],
        "probe_nonce_sha256": request["probe_nonce_sha256"],
        **static,
        "implementation_binding_sha256": implementation,
        "issued_at_unix": issued_at_unix,
        "expires_at_unix": issued_at_unix + int(request["validity_seconds"]),
        "provider_calls": 0,
    }
    signing_key = hmac.new(
        root_secret,
        authority._RESPONSE_KEY_DOMAIN,
        hashlib.sha256,
    ).digest()
    return {
        **unsigned,
        "attestation_hmac_sha256": hmac.new(
            signing_key,
            authority._RESPONSE_DOMAIN + authority._canonical_json(unsigned),
            hashlib.sha256,
        ).hexdigest(),
    }


def test_exact_signed_v5_response_issues_distinct_nominal_application_capability() -> None:
    root = b"r" * 32
    request = {
        "schema_version": subject.REQUEST_SCHEMA,
        "target_origin_sha256": _sha("target"),
        "run_id_sha256": _sha("run"),
        "probe_nonce_sha256": _sha("nonce"),
        "validity_seconds": 900,
    }
    expected = _expected()

    capability = authority._verify_and_issue(
        _signed_response(root_secret=root, request=request, expected=expected),
        request=request,
        root_secret=root,
        expected_authority=expected,
        now_unix=1_000,
    )

    assert type(capability) is subject.VerifiedManagedMem0V5RuntimeAttestationValidation
    view = managed_runtime_validation_view(capability)
    assert view is not None
    assert view.family == MANAGED_MEM0_V5_RUNTIME_FAMILY
    assert managed_runtime_validation_is_publishable(
        capability,
        required_runtime_mode="oss",
        required_family=MANAGED_MEM0_V5_RUNTIME_FAMILY,
    )
    assert capability.payload["max_age_seconds"] == 900
    assert capability.payload["attestation"]["usage_attestation_required"] is False


@pytest.mark.parametrize(
    "mutation",
    (
        lambda response: response.update(runtime_source_sha256=_sha("cross-wire")),
        lambda response: response.update(attestation_hmac_sha256="0" * 64),
        lambda response: response.update(provider_calls=1),
        lambda response: response.update(usage_attestation_required=True),
    ),
)
def test_tampered_or_cross_wired_response_never_issues_capability(mutation) -> None:
    root = b"r" * 32
    request = {
        "schema_version": subject.REQUEST_SCHEMA,
        "target_origin_sha256": _sha("target"),
        "run_id_sha256": _sha("run"),
        "probe_nonce_sha256": _sha("nonce"),
        "validity_seconds": 60,
    }
    expected = _expected()
    response = _signed_response(root_secret=root, request=request, expected=expected)
    mutation(response)

    with pytest.raises(
        subject.ManagedMem0V5RuntimeAttestationHttpError,
        match="managed_mem0_v5_runtime_capability_invalid",
    ):
        authority._verify_and_issue(
            response,
            request=request,
            root_secret=root,
            expected_authority=expected,
            now_unix=1_000,
        )


def test_root_secret_derivations_are_domain_separated() -> None:
    root = b"r" * 32
    bearer = hmac.new(root, subject._AUTH_DOMAIN, hashlib.sha256).digest()
    signing = hmac.new(root, authority._RESPONSE_KEY_DOMAIN, hashlib.sha256).digest()

    assert bearer != signing
    assert bearer != root
    assert signing != root


def test_implementation_pin_covers_both_split_modules_in_exact_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = {
        name: (index + 10, _sha(name)) for index, name in enumerate(sorted(subject._SOURCE_NAMES))
    }
    observed_paths: list[tuple[str, str]] = []

    def read(path: str, *, expected_name: str) -> tuple[int, str]:
        observed_paths.append((path, expected_name))
        return content[expected_name]

    monkeypatch.setattr(subject, "_read_implementation_source", read)
    rows = b"".join(
        name.encode("ascii")
        + b"\0"
        + str(content[name][0]).encode("ascii")
        + b"\0"
        + content[name][1].encode("ascii")
        + b"\n"
        for name in sorted(subject._SOURCE_NAMES)
    )

    baseline = subject._implementation_source_sha256()

    assert baseline == hashlib.sha256(rows).hexdigest()
    assert [name for _, name in observed_paths] == sorted(subject._SOURCE_NAMES)
    assert all(os.path.basename(path) == name for path, name in observed_paths)
    for name in subject._SOURCE_NAMES:
        original = content[name]
        content[name] = (original[0], _sha(name + "-tampered"))
        assert subject._implementation_source_sha256() != baseline
        content[name] = original


class _UnusedTransport:
    def open_client(self, *, base_url: str, timeout_seconds: float):
        del base_url, timeout_seconds
        raise AssertionError("transport client should be replaced by the test")


def _new_port(monkeypatch: pytest.MonkeyPatch) -> subject.ManagedMem0V5RuntimeAttestationPort:
    monkeypatch.setattr(subject, "_trusted_implementation_sha256", lambda value: value)
    return subject.ManagedMem0V5RuntimeAttestationPort(
        base_url="http://127.0.0.1:19091",
        runtime_attestation_root_secret="r" * 32,
        probe_nonce_sha256=_sha("nonce"),
        expected_authority=_expected(),
        timeout_seconds=5.0,
        deadline_budget_seconds=600.0,
        monotonic_clock=lambda: 100.0,
        expected_implementation_sha256=_sha("client-source"),
        allowed_target_hosts=("127.0.0.1",),
        vetted_transport=_UnusedTransport(),
        wall_clock=lambda: 1_000.0,
    )


def test_failed_prevalidation_is_a_terminal_single_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fail(**_kwargs):
        nonlocal calls
        calls += 1
        raise subject.ManagedMem0V5RuntimeAttestationHttpError(
            "managed_mem0_v5_runtime_probe_failed"
        )

    monkeypatch.setattr(subject, "_post_attestation", fail)
    port = _new_port(monkeypatch)
    binding = {
        "run_id": "failed-prevalidation",
        "probe_nonce_sha256": _sha("nonce"),
        "target_identity_sha256": _sha("http://127.0.0.1:19091"),
    }

    with pytest.raises(subject.ManagedMem0V5RuntimeAttestationHttpError, match="probe_failed"):
        port.prevalidate(**binding)
    with pytest.raises(subject.ManagedMem0V5RuntimeAttestationHttpError, match="already_used"):
        port.prevalidate(**binding)

    assert calls == 1


def test_concurrent_prevalidation_allows_exactly_one_transport_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    first_errors: list[Exception] = []

    async def block_then_fail(**_kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(timeout=2.0)
        raise subject.ManagedMem0V5RuntimeAttestationHttpError(
            "managed_mem0_v5_runtime_probe_failed"
        )

    monkeypatch.setattr(subject, "_post_attestation", block_then_fail)
    port = _new_port(monkeypatch)
    binding = {
        "run_id": "concurrent-prevalidation",
        "probe_nonce_sha256": _sha("nonce"),
        "target_identity_sha256": _sha("http://127.0.0.1:19091"),
    }

    def first_attempt() -> None:
        try:
            port.prevalidate(**binding)
        except Exception as exc:
            first_errors.append(exc)

    worker = threading.Thread(target=first_attempt)
    worker.start()
    assert entered.wait(timeout=2.0)
    with pytest.raises(subject.ManagedMem0V5RuntimeAttestationHttpError, match="already_used"):
        port.prevalidate(**binding)
    release.set()
    worker.join(timeout=2.0)

    assert not worker.is_alive()
    assert calls == 1
    assert len(first_errors) == 1
    assert "probe_failed" in str(first_errors[0])


def test_prevalidate_is_only_network_attempt_and_attest_consumes_after_http_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = b"r" * 32
    expected = _expected()
    calls: list[httpx.Request] = []
    wall = [1_000.0]

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        request = json.loads(http_request.content)
        response = _signed_response(root_secret=root, request=request, expected=expected)
        return httpx.Response(200, json=response)

    class _Transport:
        def open_client(self, *, base_url: str, timeout_seconds: float):
            del base_url, timeout_seconds

            class _Response:
                status_code = 200
                headers: dict[str, str] = {}

                def __init__(self, payload: bytes) -> None:
                    self.payload = payload

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return None

                async def aiter_raw(self, chunk_size=None):
                    del chunk_size
                    yield self.payload

            class _Client:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return None

                def stream(self, method, path, *, headers=None, json=None):
                    request = httpx.Request(
                        method, f"http://127.0.0.1:19091{path}", headers=headers, json=json
                    )
                    response = handler(request)
                    return _Response(response.content)

            return _Client()

    monkeypatch.setattr(subject, "_trusted_implementation_sha256", lambda value: value)
    run_id = "v5-prefetch-run"
    nonce = _sha("nonce")
    target = _sha("http://127.0.0.1:19091")
    port = subject.ManagedMem0V5RuntimeAttestationPort(
        base_url="http://127.0.0.1:19091",
        runtime_attestation_root_secret=root.decode(),
        probe_nonce_sha256=nonce,
        expected_authority=expected,
        timeout_seconds=5.0,
        deadline_budget_seconds=600.0,
        monotonic_clock=lambda: 100.0,
        expected_implementation_sha256=_sha("client-source"),
        allowed_target_hosts=("127.0.0.1",),
        vetted_transport=_Transport(),
        wall_clock=lambda: wall[0],
    )

    port.prevalidate(
        run_id=run_id,
        probe_nonce_sha256=nonce,
        target_identity_sha256=target,
    )
    assert len(calls) == 1
    request_body = json.loads(calls[0].content)
    request_sha = subject._canonical_sha256(request_body)
    assert calls[0].headers["x-request-commitment-sha256"] == request_sha
    assert (
        calls[0].headers["idempotency-key"]
        == hashlib.sha256(subject._IDEMPOTENCY_DOMAIN + bytes.fromhex(request_sha)).hexdigest()
    )
    assert calls[0].headers["authorization"] != f"Bearer {root.decode()}"

    wall[0] = 99_999.0
    capability = port.attest(
        run_id=run_id,
        probe_nonce_sha256=nonce,
        target_identity_sha256=target,
    )
    assert len(calls) == 1
    assert type(capability) is subject.VerifiedManagedMem0V5RuntimeAttestationValidation
    assert port.usage_attestation_required() is False
    with pytest.raises(subject.ManagedMem0V5RuntimeAttestationHttpError, match="already_used"):
        port.attest(
            run_id=run_id,
            probe_nonce_sha256=nonce,
            target_identity_sha256=target,
        )


def test_runtime_pin_is_safe_read_and_requires_attestation_contract_fields(
    tmp_path: Path,
) -> None:
    expected = _expected()
    contract = {
        "adapter_schema_version": "mem0-benchmark-full-run.v5",
        "provider_attempts_per_dispatch": 1,
        "status_provider_attempts": 0,
        "runtime_attestation_request_schema": subject.REQUEST_SCHEMA,
        "runtime_attestation_response_schema": authority.RESPONSE_SCHEMA,
        "runtime_attestation_route_contract_sha256": authority._ROUTE_SHA256,
        "requested_output_tokens": 4096,
        "output_limit_enforced": False,
        "usage_attestation_required": False,
        "transport_origin_sha256": expected.runtime_transport_origin_sha256,
        "route_binding_sha256": expected.runtime_route_binding_sha256,
        "adapter_extraction_system_prompt_sha256": expected.extraction_system_prompt_sha256,
        "adapter_extraction_response_format_sha256": (expected.extraction_response_format_sha256),
        "adapter_extraction_schema_sha256": expected.extraction_response_schema_sha256,
    }
    pin = {
        "schema_version": "mem0-oss-adapter-v5.runtime-pin.v1",
        "source_a": {
            "commit_sha1": expected.source_commit_sha1,
            "tree_sha1": expected.source_tree_sha1,
            "manifest_sha256": expected.source_manifest_sha256,
            "closure_sha256": expected.source_closure_sha256,
        },
        "phase_c": {
            "infinity_source_commit_sha1": expected.phase_c_infinity_commit_sha1,
            "infinity_source_tree_sha1": expected.phase_c_infinity_tree_sha1,
            "release_manifest_sha256": expected.phase_c_release_manifest_sha256,
        },
        "runtime_contract": contract,
    }
    path = (tmp_path / "runtime-pin.json").resolve()
    raw = json.dumps(pin, sort_keys=True).encode()
    path.write_bytes(raw)
    path.chmod(0o444)

    parsed = subject.expected_managed_mem0_v5_runtime_authority_from_pin(
        runtime_pin_file=path,
        runtime_pin_sha256=hashlib.sha256(raw).hexdigest(),
        runtime_source_sha256=expected.runtime_source_sha256,
        runtime_route_binding_sha256=expected.runtime_route_binding_sha256,
        subscription_runtime_binding_commitment_sha256=(
            expected.subscription_runtime_binding_commitment_sha256
        ),
        expected_account_binding_hmac_sha256=expected.expected_account_binding_hmac_sha256,
        expected_base_instructions_sha256=expected.expected_base_instructions_sha256,
        expected_extraction_system_prompt_sha256=expected.extraction_system_prompt_sha256,
        expected_extraction_response_format_sha256=expected.extraction_response_format_sha256,
        expected_extraction_response_schema_sha256=expected.extraction_response_schema_sha256,
        expected_requested_output_tokens=expected.requested_output_tokens,
    )
    assert len(parsed.runtime_binding_commitment_sha256) == 64

    mismatches = (
        {"expected_extraction_system_prompt_sha256": _sha("foreign-prompt")},
        {"expected_extraction_response_format_sha256": _sha("foreign-format")},
        {"expected_extraction_response_schema_sha256": _sha("foreign-schema")},
        {"expected_requested_output_tokens": 2048},
    )
    common = {
        "runtime_pin_file": path,
        "runtime_pin_sha256": hashlib.sha256(raw).hexdigest(),
        "runtime_source_sha256": expected.runtime_source_sha256,
        "runtime_route_binding_sha256": expected.runtime_route_binding_sha256,
        "subscription_runtime_binding_commitment_sha256": (
            expected.subscription_runtime_binding_commitment_sha256
        ),
        "expected_account_binding_hmac_sha256": expected.expected_account_binding_hmac_sha256,
        "expected_base_instructions_sha256": expected.expected_base_instructions_sha256,
        "expected_extraction_system_prompt_sha256": expected.extraction_system_prompt_sha256,
        "expected_extraction_response_format_sha256": (expected.extraction_response_format_sha256),
        "expected_extraction_response_schema_sha256": (expected.extraction_response_schema_sha256),
        "expected_requested_output_tokens": expected.requested_output_tokens,
    }
    for mismatch in mismatches:
        with pytest.raises(subject.ManagedMem0V5RuntimeAttestationHttpError):
            subject.expected_managed_mem0_v5_runtime_authority_from_pin(**{**common, **mismatch})

    contract.pop("usage_attestation_required")
    tampered = json.dumps(pin, sort_keys=True).encode()
    path.chmod(0o644)
    path.write_bytes(tampered)
    path.chmod(0o444)
    with pytest.raises(subject.ManagedMem0V5RuntimeAttestationHttpError):
        subject.expected_managed_mem0_v5_runtime_authority_from_pin(
            runtime_pin_file=path,
            runtime_pin_sha256=hashlib.sha256(tampered).hexdigest(),
            runtime_source_sha256=expected.runtime_source_sha256,
            runtime_route_binding_sha256=expected.runtime_route_binding_sha256,
            subscription_runtime_binding_commitment_sha256=(
                expected.subscription_runtime_binding_commitment_sha256
            ),
            expected_account_binding_hmac_sha256=expected.expected_account_binding_hmac_sha256,
            expected_base_instructions_sha256=expected.expected_base_instructions_sha256,
            expected_extraction_system_prompt_sha256=expected.extraction_system_prompt_sha256,
            expected_extraction_response_format_sha256=(expected.extraction_response_format_sha256),
            expected_extraction_response_schema_sha256=(expected.extraction_response_schema_sha256),
            expected_requested_output_tokens=expected.requested_output_tokens,
        )
