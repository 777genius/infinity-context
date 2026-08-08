from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PHASE_C_ROOT = ROOT / "benchmarks" / "phase-c-canary"
sys.path.insert(0, str(PHASE_C_ROOT))

from infinity_context_server.memory_comparison_bounded_httpx_transport import (  # noqa: E402
    BoundedHttpResponse as _Response,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (  # noqa: E402
    MEM0_OSS_EMPTY_ROOT_SHA256,
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    Mem0OssManifestUnit,
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationResult,
    StorageVerificationResult,
    canonical_sha256,
    manifest_root_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (  # noqa: E402
    Mem0V5AdmitRequest,
    Mem0V5DispatchRequest,
    Mem0V5HttpError,
    Mem0V5HttpPort,
    Mem0V5OperationReceiptAuthority,
    Mem0V5ReceiptAuthority,
    Mem0V5RuntimeReceiptEnvelope,
    Mem0V5RuntimeReceiptVerifier,
    Mem0V5StatusRequest,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_persistence import (  # noqa: E402
    Mem0V5EvidenceStoreError,
    Mem0V5StoreCheckpoint,
    SQLiteMem0V5EvidenceStore,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_run import (  # noqa: E402
    Mem0OssFailedReceiptEvidence,
    Mem0OssRunSeal,
    Mem0OssTerminalCleanupEvidence,
)
from phase_c_canary.receipt import NodePublicReceiptVerifier  # noqa: E402
from phase_c_canary.runtime_binding import RuntimeBindingComposition  # noqa: E402
from phase_c_canary.runtime_receipt_v2 import RuntimeReceiptV2Boundary  # noqa: E402

_runtime_repo = os.environ.get("PHASE_C_RUNTIME_REPO")
RUNTIME_REPO = Path(_runtime_repo) if _runtime_repo else None
NODE_BINARY = shutil.which("node")
_requires_runtime = pytest.mark.skipif(
    RUNTIME_REPO is None or not RUNTIME_REPO.is_dir() or NODE_BINARY is None,
    reason="PHASE_C_RUNTIME_REPO and node are required",
)
SECRET = "provider-free-fixture-secret-at-least-32-bytes"
CHECKPOINT_KEY = b"external-checkpoint-key-32-bytes!!"
AUTH_KEY = b"database-authentication-key-32byte"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _unit() -> Mem0OssManifestUnit:
    return Mem0OssManifestUnit(_digest("identity"), _digest("unit"), _digest("scope"))


def _admission() -> tuple[Mem0OssFullRunAdmission, tuple[Mem0OssManifestUnit, ...]]:
    units = (_unit(),)
    request = Mem0OssAdmissionRequest(
        run_id="adapter-test-run",
        route_sha256=_route_binding(),
        credential_binding_sha256=_digest("credential"),
        model="gpt-5.6-sol",
        reasoning_effort="high",
        service_tier="default",
        runtime_source_revision="source-r1",
        runtime_source_sha256=_runtime_source(),
        runtime_base_sha256=_digest("base"),
        expected_operation_count=1,
    )
    return (
        Mem0OssFullRunAdmission(
            request=request,
            ingestion_manifest_sha256=_digest("manifest"),
            ingestion_root_sha256=manifest_root_sha256(units),
            ingestion_unit_count=1,
        ),
        units,
    )


def _admission_many(
    count: int,
) -> tuple[Mem0OssFullRunAdmission, tuple[Mem0OssManifestUnit, ...]]:
    units = tuple(
        Mem0OssManifestUnit(
            _digest(f"identity-{index}"),
            _digest(f"unit-{index}"),
            _digest(f"scope-{index}"),
        )
        for index in range(count)
    )
    request = Mem0OssAdmissionRequest(
        run_id=f"large-admission-{count}",
        route_sha256=_route_binding(),
        credential_binding_sha256=_digest("credential"),
        model="gpt-5.6-sol",
        reasoning_effort="high",
        service_tier="default",
        runtime_source_revision="source-r1",
        runtime_source_sha256=_runtime_source(),
        runtime_base_sha256=_digest("base"),
        expected_operation_count=count,
    )
    return (
        Mem0OssFullRunAdmission(
            request=request,
            ingestion_manifest_sha256=_digest(f"manifest-{count}"),
            ingestion_root_sha256=manifest_root_sha256(units),
            ingestion_unit_count=count,
        ),
        units,
    )


def _operation_id(admission: Mem0OssFullRunAdmission) -> str:
    return canonical_sha256(
        {
            "admission_commitment_sha256": admission.commitment_sha256,
            "unit_index": 0,
            "unit_identity_sha256": _unit().unit_identity_sha256,
        }
    )


def _operation_id_at(
    admission: Mem0OssFullRunAdmission,
    units: tuple[Mem0OssManifestUnit, ...],
    unit_index: int,
) -> str:
    return canonical_sha256(
        {
            "admission_commitment_sha256": admission.commitment_sha256,
            "unit_index": unit_index,
            "unit_identity_sha256": units[unit_index].unit_identity_sha256,
        }
    )


def _receipt_at(
    admission: Mem0OssFullRunAdmission,
    units: tuple[Mem0OssManifestUnit, ...],
    unit_index: int,
) -> RuntimeReceiptVerificationResult:
    unit = units[unit_index]
    return RuntimeReceiptVerificationResult(
        admission_commitment_sha256=admission.commitment_sha256,
        operation_id_sha256=_operation_id_at(admission, units, unit_index),
        unit_identity_sha256=unit.unit_identity_sha256,
        unit_sha256=unit.unit_sha256,
        route_sha256=admission.request.route_sha256,
        scope_sha256=unit.scope_sha256,
        provider_receipt_sha256=_digest(f"failed-receipt-{unit_index}"),
        disposition=Mem0OssReceiptDisposition.PROVIDER_FAILED,
        extraction_calls=1,
        retry_count=0,
        request_tokens=3,
        response_tokens=2,
    )


def _context(
    admission: Mem0OssFullRunAdmission, *, readback: bool
) -> RuntimeReceiptVerificationContext:
    unit = _unit()
    return RuntimeReceiptVerificationContext(
        admission_commitment_sha256=admission.commitment_sha256,
        operation_id_sha256=_operation_id(admission),
        unit_identity_sha256=unit.unit_identity_sha256,
        unit_sha256=unit.unit_sha256,
        route_sha256=admission.request.route_sha256,
        scope_sha256=unit.scope_sha256,
        readback_only=readback,
    )


def _receipt(
    admission: Mem0OssFullRunAdmission,
    *,
    disposition: Mem0OssReceiptDisposition = Mem0OssReceiptDisposition.COMPLETED,
) -> RuntimeReceiptVerificationResult:
    context = _context(admission, readback=False)
    return RuntimeReceiptVerificationResult(
        admission_commitment_sha256=context.admission_commitment_sha256,
        operation_id_sha256=context.operation_id_sha256,
        unit_identity_sha256=context.unit_identity_sha256,
        unit_sha256=context.unit_sha256,
        route_sha256=context.route_sha256,
        scope_sha256=context.scope_sha256,
        provider_receipt_sha256=_digest("provider-receipt"),
        disposition=disposition,
        extraction_calls=1,
        retry_count=0,
        request_tokens=10,
        response_tokens=4,
    )


def _storage(receipt: RuntimeReceiptVerificationResult) -> StorageVerificationResult:
    return StorageVerificationResult(
        admission_commitment_sha256=receipt.admission_commitment_sha256,
        operation_id_sha256=receipt.operation_id_sha256,
        unit_identity_sha256=receipt.unit_identity_sha256,
        unit_sha256=receipt.unit_sha256,
        route_sha256=receipt.route_sha256,
        scope_sha256=receipt.scope_sha256,
        provider_receipt_sha256=receipt.provider_receipt_sha256,
        stored_identity_sha256=_digest("stored"),
        stored_record_count=1,
    )


def _operation_payload(
    receipt: RuntimeReceiptVerificationResult,
    storage: StorageVerificationResult | None,
) -> dict[str, object]:
    return {
        "operation_id_sha256": receipt.operation_id_sha256,
        "unit_index": 0,
        "unit_identity_sha256": receipt.unit_identity_sha256,
        "unit_sha256": receipt.unit_sha256,
        "scope_sha256": receipt.scope_sha256,
        "provider_receipt_sha256": receipt.provider_receipt_sha256,
        "disposition": receipt.disposition.value,
        "extraction_calls": receipt.extraction_calls,
        "retry_count": receipt.retry_count,
        "request_tokens": receipt.request_tokens,
        "response_tokens": receipt.response_tokens,
        "stored_identity_sha256": storage.stored_identity_sha256 if storage else None,
        "stored_record_count": storage.stored_record_count if storage else 0,
    }


def _seal(
    admission: Mem0OssFullRunAdmission,
    receipt: RuntimeReceiptVerificationResult,
    storage: StorageVerificationResult,
) -> Mem0OssRunSeal:
    commitment = canonical_sha256(_operation_payload(receipt, storage))
    return Mem0OssRunSeal(
        admission_commitment_sha256=admission.commitment_sha256,
        operation_count=1,
        ingestion_root_sha256=admission.ingestion_root_sha256,
        operation_root_sha256=canonical_sha256({"operation_commitments": [commitment]}),
        provider_observed_extraction_calls=1,
        provider_observed_request_tokens=10,
        provider_observed_response_tokens=4,
    )


def _inventory_root(
    receipt: RuntimeReceiptVerificationResult,
    storage: StorageVerificationResult | None,
) -> str:
    base = _operation_payload(receipt, storage)
    if receipt.disposition is Mem0OssReceiptDisposition.COMPLETED and storage:
        state = "committed"
        commitment: str | None = canonical_sha256(base)
    else:
        state = "failed"
        commitment = None
    return canonical_sha256(
        {"operations": [{**base, "state": state, "commitment_sha256": commitment}]}
    )


def _cleanup(
    admission: Mem0OssFullRunAdmission,
    receipt: RuntimeReceiptVerificationResult,
    storage: StorageVerificationResult | None,
    seal: Mem0OssRunSeal | None,
) -> Mem0OssTerminalCleanupEvidence:
    failed = ()
    if receipt.disposition is not Mem0OssReceiptDisposition.COMPLETED:
        failed = (
            Mem0OssFailedReceiptEvidence(
                operation_id_sha256=receipt.operation_id_sha256,
                unit_index=0,
                disposition=receipt.disposition.value,
                provider_receipt_sha256=receipt.provider_receipt_sha256,
                extraction_calls=1,
                request_tokens=10,
                response_tokens=4,
            ),
        )
    return Mem0OssTerminalCleanupEvidence(
        terminal_state="deleted" if seal else "aborted",
        admission_commitment_sha256=admission.commitment_sha256,
        seal_commitment_sha256=seal.commitment_sha256 if seal else None,
        operation_root_sha256=seal.operation_root_sha256 if seal else None,
        operation_inventory_root_sha256=_inventory_root(receipt, storage),
        deleted_operation_count=1,
        residual_record_count=0,
        residual_root_sha256=MEM0_OSS_EMPTY_ROOT_SHA256,
        provider_observed_extraction_calls=1,
        provider_observed_request_tokens=10,
        provider_observed_response_tokens=4,
        failed_receipts=failed,
    )


def _abort_cleanup(
    admission: Mem0OssFullRunAdmission,
    units: tuple[Mem0OssManifestUnit, ...],
    receipts: dict[int, RuntimeReceiptVerificationResult],
    *,
    deleted_operation_count: int,
) -> Mem0OssTerminalCleanupEvidence:
    inventory: list[dict[str, object]] = []
    failed: list[Mem0OssFailedReceiptEvidence] = []
    for index, unit in enumerate(units):
        receipt = receipts.get(index)
        base = {
            "operation_id_sha256": _operation_id_at(admission, units, index),
            "unit_index": index,
            "unit_identity_sha256": unit.unit_identity_sha256,
            "unit_sha256": unit.unit_sha256,
            "scope_sha256": unit.scope_sha256,
            "provider_receipt_sha256": receipt.provider_receipt_sha256 if receipt else None,
            "disposition": receipt.disposition.value if receipt else None,
            "extraction_calls": receipt.extraction_calls if receipt else 0,
            "retry_count": receipt.retry_count if receipt else 0,
            "request_tokens": receipt.request_tokens if receipt else 0,
            "response_tokens": receipt.response_tokens if receipt else 0,
            "stored_identity_sha256": None,
            "stored_record_count": 0,
        }
        state = "failed" if receipt else "reserved"
        inventory.append({**base, "state": state, "commitment_sha256": None})
        if receipt:
            failed.append(
                Mem0OssFailedReceiptEvidence(
                    operation_id_sha256=receipt.operation_id_sha256,
                    unit_index=index,
                    disposition=receipt.disposition.value,
                    provider_receipt_sha256=receipt.provider_receipt_sha256,
                    extraction_calls=receipt.extraction_calls,
                    request_tokens=receipt.request_tokens,
                    response_tokens=receipt.response_tokens,
                )
            )
    return Mem0OssTerminalCleanupEvidence(
        terminal_state="aborted",
        admission_commitment_sha256=admission.commitment_sha256,
        seal_commitment_sha256=None,
        operation_root_sha256=None,
        operation_inventory_root_sha256=canonical_sha256({"operations": inventory}),
        deleted_operation_count=deleted_operation_count,
        residual_record_count=0,
        residual_root_sha256=MEM0_OSS_EMPTY_ROOT_SHA256,
        provider_observed_extraction_calls=sum(item.extraction_calls for item in receipts.values()),
        provider_observed_request_tokens=sum(item.request_tokens for item in receipts.values()),
        provider_observed_response_tokens=sum(item.response_tokens for item in receipts.values()),
        failed_receipts=tuple(failed),
    )


class _Transport:
    def __init__(self, response: _Response | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method: str, url: str, **kwargs: object) -> object:
        self.calls.append((method, url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _http(transport: _Transport) -> Mem0V5HttpPort:
    return Mem0V5HttpPort(
        origin="http://127.0.0.1:8888",
        bearer_token="private-bearer-value-at-least-32-bytes",
        timeout_seconds=3,
        transport=transport,
    )


def test_endpoint_specific_requests_and_responses_are_exact() -> None:
    admission, _ = _admission()
    response = {
        "admission_commitment_sha256": admission.commitment_sha256,
        "runtime_binding_commitment_sha256": _digest("binding"),
        "accepted": True,
    }
    transport = _Transport(_Response(200, json.dumps(response).encode()))
    result = _http(transport).admit(
        Mem0V5AdmitRequest(
            admission_commitment_sha256=admission.commitment_sha256,
            ingestion_manifest_sha256=admission.ingestion_manifest_sha256,
            ingestion_root_sha256=admission.ingestion_root_sha256,
            expected_operation_count=1,
            route_sha256=admission.request.route_sha256,
            idempotency_key=_digest("admit"),
        )
    )
    assert result.accepted is True
    _, url, kwargs = transport.calls[0]
    assert url.endswith("/v5/runs/admit")
    assert kwargs["follow_redirects"] is False
    assert b"question" not in kwargs["content"]


def test_every_endpoint_rejects_extra_or_alternate_private_response_fields() -> None:
    admission, _ = _admission()
    context = _context(admission, readback=False)
    dispatch = Mem0V5DispatchRequest(
        admission_commitment_sha256=admission.commitment_sha256,
        operation_id_sha256=context.operation_id_sha256,
        unit_identity_sha256=context.unit_identity_sha256,
        unit_sha256=context.unit_sha256,
        scope_sha256=context.scope_sha256,
        request_body_sha256="1" * 64,
        sequence=0,
        idempotency_key=_digest("dispatch"),
    )
    malicious = {
        "admission_commitment_sha256": admission.commitment_sha256,
        "operation_id_sha256": context.operation_id_sha256,
        "runtime_receipt": {},
        "raw_prompt": "private",
    }
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_response_invalid"):
        _http(_Transport(_Response(200, json.dumps(malicious).encode()))).dispatch(dispatch)


@pytest.mark.parametrize(
    "origin",
    [
        "https://127.0.0.1:8888",
        "http://localhost:8888",
        "http://user@127.0.0.1:8888",
        "http://127.0.0.1:8888/path",
        "http://127.0.0.1:8888?query=x",
        "http://10.0.0.1:8888",
    ],
)
def test_http_adapter_rejects_nonexact_loopback_origin(origin: str) -> None:
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_configuration_invalid"):
        Mem0V5HttpPort(
            origin=origin,
            bearer_token="private-bearer-value-at-least-32-bytes",
            timeout_seconds=1,
            transport=_Transport(_Response(200, b"{}")),
        )


def test_http_failures_are_bounded_no_redirect_and_secret_safe() -> None:
    admission, _ = _admission()
    request = Mem0V5StatusRequest(
        admission.commitment_sha256, _operation_id(admission), _digest("status")
    )
    secret = "provider-secret-output"
    with pytest.raises(Mem0V5HttpError) as caught:
        _http(_Transport(RuntimeError(secret))).status(request)
    assert caught.value.code == "mem0_v5_http_remote_failed"
    assert secret not in str(caught.value)
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_remote_failed"):
        _http(_Transport(_Response(307, b"{}"))).status(request)
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_response_invalid"):
        _http(_Transport(_Response(200, b"x" * 256_001))).status(request)


def _runtime_source() -> str:
    return hashlib.sha256(b"e904ec95fda4b04c333e5a7613c7729bf7abb125").hexdigest()


def _route_binding() -> str:
    return hashlib.sha256(b"http://127.0.0.1:8890/v1").hexdigest()


def _unsigned_runtime_receipt() -> dict[str, Any]:
    return {
        "metadata": {
            "schema_version": 2,
            "attestation_level": "provider_receipt",
            "usage_source": "codex_thread_token_usage_updated",
            "runtime_selection": {
                "account_binding_hmac_sha256": "4" * 64,
                "thread_id": "thread-provider-free",
                "turn_id": "turn-provider-free",
                "model": "gpt-5.6-sol",
                "model_provider": "openai",
                "reasoning_effort": "high",
                "service_tier": "default",
                "execution_profile": "stateless-completion",
                "base_instructions_sha256": (
                    "5c15d6c502d380282a933d4f20a886a06c9d04d3b5d7c918b95df0b0acf33671"
                ),
            },
            "request_identity": {
                "public_model": "gpt-5.6-sol",
                "client_requested_model": "gpt-5.6-sol",
                "configured_codex_model": "gpt-5.6-sol",
                "requested_codex_model": "gpt-5.6-sol",
                "request_body_sha256": "1" * 64,
                "response_format_type": "json_schema",
                "response_format_sha256": (
                    "812938567c7a81bac6ed3266608adf470dedc57706102e039422f695495322bf"
                ),
                "response_schema_sha256": (
                    "2461f7a465be82aa67751dc04e0717cde75c69b86e7db54bb306a2e3d1d4d8f0"
                ),
            },
            "output_identity": {
                "output_text_sha256": _digest("safe-output"),
                "terminal_status": "completed",
            },
            "output_token_limit": {"requested_tokens": 4096, "enforced": False},
            "receipt_hmac_sha256": "0" * 64,
        },
        "usage": {
            "prompt_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 2},
            "completion_tokens": 4,
            "completion_tokens_details": {"reasoning_tokens": 1},
            "total_tokens": 14,
        },
    }


def _sign_runtime_receipt(value: dict[str, Any]) -> dict[str, Any]:
    assert RUNTIME_REPO is not None and NODE_BINARY is not None
    receipt = copy.deepcopy(value)
    canonical_url = (
        RUNTIME_REPO / "dist/openai-compatible-codex/chat-completions/domain/runtime-attestation.js"
    ).as_uri()
    script = r"""
import {createHmac} from "node:crypto";
let body = ""; for await (const chunk of process.stdin) body += chunk;
const {receipt, secret, canonical_url} = JSON.parse(body); const m = receipt.metadata;
const {openAiBridgeRuntimeAttestationCanonicalBytes} = await import(canonical_url);
const bytes = openAiBridgeRuntimeAttestationCanonicalBytes({
  selection:m.runtime_selection, requestIdentity:m.request_identity,
  outputIdentity:m.output_identity, usage:receipt.usage,
  requestedOutputTokenLimit:m.output_token_limit.requested_tokens ?? undefined,
});
process.stdout.write(createHmac("sha256", secret).update(bytes).digest("hex"));
"""
    completed = subprocess.run(
        [NODE_BINARY, "--input-type=module", "-e", script],
        cwd=RUNTIME_REPO,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
        input=json.dumps({"receipt": receipt, "secret": SECRET, "canonical_url": canonical_url}),
        text=True,
        capture_output=True,
        check=True,
    )
    receipt["metadata"]["receipt_hmac_sha256"] = completed.stdout
    return receipt


def _verifier() -> tuple[Mem0V5RuntimeReceiptVerifier, Mem0OssFullRunAdmission, dict[str, Any]]:
    assert RUNTIME_REPO is not None
    admission, _ = _admission()
    receipt = _sign_runtime_receipt(_unsigned_runtime_receipt())
    binding = RuntimeBindingComposition.compose_phase_c_canary().issue()
    operation = Mem0V5OperationReceiptAuthority(
        operation_id_sha256=_operation_id(admission),
        sequence=0,
        thread_id="thread-provider-free",
        turn_id="turn-provider-free",
        request_body_sha256="1" * 64,
        output_text_sha256=_digest("safe-output"),
    )
    authority = Mem0V5ReceiptAuthority(
        model="gpt-5.6-sol",
        reasoning_effort="high",
        service_tier="default",
        base_instructions_sha256=(
            "5c15d6c502d380282a933d4f20a886a06c9d04d3b5d7c918b95df0b0acf33671"
        ),
        runtime_source_sha256=binding.runtime_source_sha256,
        route_binding_sha256=binding.route_binding_sha256,
        account_binding_hmac_sha256="4" * 64,
        response_format_type="json_schema",
        response_format_sha256=("812938567c7a81bac6ed3266608adf470dedc57706102e039422f695495322bf"),
        response_schema_sha256=("2461f7a465be82aa67751dc04e0717cde75c69b86e7db54bb306a2e3d1d4d8f0"),
        requested_output_tokens=4096,
        operations=(operation,),
    )
    verifier = Mem0V5RuntimeReceiptVerifier(
        boundary=RuntimeReceiptV2Boundary(
            NodePublicReceiptVerifier(RUNTIME_REPO, node_executable=Path(NODE_BINARY))
        ),
        runtime_binding=binding,
        receipt_secret=SECRET,
        authority=authority,
    )
    return verifier, admission, receipt


def _envelope(
    admission: Mem0OssFullRunAdmission, receipt: dict[str, Any]
) -> Mem0V5RuntimeReceiptEnvelope:
    return Mem0V5RuntimeReceiptEnvelope(
        admission_commitment_sha256=admission.commitment_sha256,
        operation_id_sha256=_operation_id(admission),
        runtime_receipt=receipt,
    )


@_requires_runtime
def test_concrete_phase_c_verifier_rejects_unsigned_tampered_and_replayed_receipts() -> None:
    verifier, admission, receipt = _verifier()
    result = verifier.verify_dispatch_receipt(
        payload=_envelope(admission, receipt),
        context=_context(admission, readback=False),
    )
    assert result.request_tokens == 10
    assert result.response_tokens == 4
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_runtime_receipt_replayed"):
        verifier.verify_dispatch_receipt(
            payload=_envelope(admission, receipt),
            context=_context(admission, readback=False),
        )

    verifier, admission, receipt = _verifier()
    receipt["usage"]["prompt_tokens"] = 11
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_runtime_receipt_unauthenticated"):
        verifier.verify_dispatch_receipt(
            payload=_envelope(admission, receipt),
            context=_context(admission, readback=False),
        )


@_requires_runtime
def test_outcome_unknown_allows_authenticated_status_once_and_never_redispatches() -> None:
    verifier, admission, receipt = _verifier()
    dispatch_context = _context(admission, readback=False)
    readback_context = _context(admission, readback=True)
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_runtime_receipt_state_invalid"):
        verifier.verify_status_readback(
            payload=_envelope(admission, receipt), context=readback_context
        )
    verifier.mark_outcome_unknown(context=dispatch_context)
    assert (
        verifier.verify_status_readback(
            payload=_envelope(admission, receipt), context=readback_context
        ).provider_receipt_sha256
        != MEM0_OSS_EMPTY_ROOT_SHA256
    )
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_runtime_receipt_replayed"):
        verifier.verify_dispatch_receipt(
            payload=_envelope(admission, receipt), context=dispatch_context
        )


@_requires_runtime
def test_private_nested_receipt_field_and_secret_errors_are_sanitized() -> None:
    verifier, admission, receipt = _verifier()
    receipt["metadata"]["runtime_selection"]["email"] = "private@example.test"
    with pytest.raises(Mem0V5HttpError) as caught:
        verifier.verify_dispatch_receipt(
            payload=_envelope(admission, receipt),
            context=_context(admission, readback=False),
        )
    assert caught.value.code == "mem0_v5_runtime_receipt_unauthenticated"
    assert "private@example.test" not in str(caught.value)


def _created_store(path: Path) -> SQLiteMem0V5EvidenceStore:
    return SQLiteMem0V5EvidenceStore.create(path=path, authentication_key=AUTH_KEY)


def test_store_recomputes_exact_seal_inventory_cleanup_and_reopens(tmp_path: Path) -> None:
    admission, units = _admission()
    receipt = _receipt(admission)
    storage = _storage(receipt)
    seal = _seal(admission, receipt, storage)
    cleanup = _cleanup(admission, receipt, storage, seal)
    path = tmp_path / "evidence.sqlite3"
    store = _created_store(path)
    store.put_admission(admission, units=units)
    store.put_receipt(unit_index=0, receipt=receipt)
    store.put_storage(unit_index=0, storage=storage)
    store.put_seal(seal)
    store.put_cleanup(cleanup)
    checkpoint = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    store.close()

    reopened = SQLiteMem0V5EvidenceStore.reopen(
        path=path,
        authentication_key=AUTH_KEY,
        checkpoint=checkpoint,
        checkpoint_key=CHECKPOINT_KEY,
    )
    assert len(list(reopened.iter_public_evidence())) == 6
    reopened.close()
    assert path.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("count", [500, 5_882])
def test_large_admission_is_chunked_and_validation_query_count_is_bounded(
    tmp_path: Path, count: int
) -> None:
    admission, units = _admission_many(count)
    store = _created_store(tmp_path / f"large-{count}.sqlite3")
    statements: list[str] = []
    store._connection.set_trace_callback(statements.append)
    store.put_admission(admission, units=units)
    checkpoint = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    evidence = list(store.iter_public_evidence())
    select_count = sum(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    expected_pages = (count + 63) // 64
    assert len(evidence) == expected_pages + 1
    assert all(len(json.dumps(item["payload"]).encode()) < 64_000 for item in evidence)
    assert select_count < 40
    store.close()
    reopened = SQLiteMem0V5EvidenceStore.reopen(
        path=tmp_path / f"large-{count}.sqlite3",
        authentication_key=AUTH_KEY,
        checkpoint=checkpoint,
        checkpoint_key=CHECKPOINT_KEY,
    )
    reopened.close()


def test_second_admission_is_rejected_without_replacing_original_authority(
    tmp_path: Path,
) -> None:
    path = tmp_path / "second-admission.sqlite3"
    original, original_units = _admission()
    replacement, replacement_units = _admission_many(1)
    store = _created_store(path)
    store.put_admission(original, units=original_units)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_order_invalid"):
        store.put_admission(replacement, units=replacement_units)
    store.validate()
    checkpoint = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    store.close()
    reopened = SQLiteMem0V5EvidenceStore.reopen(
        path=path,
        authentication_key=AUTH_KEY,
        checkpoint=checkpoint,
        checkpoint_key=CHECKPOINT_KEY,
    )
    admission_evidence = list(reopened.iter_public_evidence())[0]
    assert admission_evidence["subject_sha256"] == original.commitment_sha256
    reopened.close()


def test_store_rejects_cross_operation_storage_failed_seal_and_forged_roots(
    tmp_path: Path,
) -> None:
    admission, units = _admission()
    failed = _receipt(admission, disposition=Mem0OssReceiptDisposition.PROVIDER_FAILED)
    store = _created_store(tmp_path / "failed.sqlite3")
    store.put_admission(admission, units=units)
    store.put_receipt(unit_index=0, receipt=failed)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_order_invalid"):
        store.put_storage(unit_index=0, storage=_storage(failed))
    completed = _receipt(admission)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_terminal_invalid"):
        store.put_seal(_seal(admission, completed, _storage(completed)))
    forged = _cleanup(admission, failed, None, None)
    object.__setattr__(forged, "operation_inventory_root_sha256", _digest("forged"))
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_terminal_invalid"):
        store.put_cleanup(forged)
    store.close()


def test_store_rejects_route_substitution_and_arbitrary_cleanup_count(tmp_path: Path) -> None:
    admission, units = _admission()
    receipt = _receipt(admission)
    forged_route = replace(receipt, route_sha256=_digest("other-route"))
    store = _created_store(tmp_path / "bindings.sqlite3")
    store.put_admission(admission, units=units)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_payload_invalid"):
        store.put_receipt(unit_index=0, receipt=forged_route)
    store.put_receipt(unit_index=0, receipt=receipt)
    storage = _storage(receipt)
    store.put_storage(unit_index=0, storage=storage)
    seal = _seal(admission, receipt, storage)
    store.put_seal(seal)
    forged_cleanup = _cleanup(admission, receipt, storage, seal)
    object.__setattr__(forged_cleanup, "deleted_operation_count", 0)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_terminal_invalid"):
        store.put_cleanup(forged_cleanup)
    store.close()


def test_failed_usage_and_failed_receipt_projection_are_exact(tmp_path: Path) -> None:
    admission, units = _admission()
    failed = _receipt(admission, disposition=Mem0OssReceiptDisposition.PROVIDER_FAILED)
    cleanup = _cleanup(admission, failed, None, None)
    store = _created_store(tmp_path / "failed-cleanup.sqlite3")
    store.put_admission(admission, units=units)
    store.put_receipt(unit_index=0, receipt=failed)
    store.put_cleanup(cleanup)
    payload = list(store.iter_public_evidence())[-1]["payload"]
    assert payload["failed_receipts"] == [cleanup.failed_receipts[0].public_payload()]
    assert payload["provider_observed_extraction_calls"] == 1
    store.close()


@pytest.mark.parametrize(("dispatched", "deleted"), [(False, 0), (True, 1)])
def test_unsealed_abort_accepts_zero_or_partial_authenticated_deleted_count(
    tmp_path: Path, dispatched: bool, deleted: int
) -> None:
    admission, units = _admission_many(2)
    receipts: dict[int, RuntimeReceiptVerificationResult] = {}
    store = _created_store(tmp_path / f"abort-{dispatched}.sqlite3")
    store.put_admission(admission, units=units)
    if dispatched:
        receipts[0] = _receipt_at(admission, units, 0)
        store.put_receipt(unit_index=0, receipt=receipts[0])
    cleanup = _abort_cleanup(
        admission,
        units,
        receipts,
        deleted_operation_count=deleted,
    )
    store.put_cleanup(cleanup)
    assert list(store.iter_public_evidence())[-1]["payload"]["deleted_operation_count"] == deleted
    store.close()


@pytest.mark.parametrize("mutation", ["receipt", "storage", "seal", "cleanup", "admission"])
def test_cleanup_is_terminal_for_every_store_mutator(tmp_path: Path, mutation: str) -> None:
    admission, units = _admission()
    receipt = _receipt(admission)
    storage = _storage(receipt)
    seal = _seal(admission, receipt, storage)
    cleanup = _cleanup(admission, receipt, storage, seal)
    store = _created_store(tmp_path / f"terminal-{mutation}.sqlite3")
    store.put_admission(admission, units=units)
    store.put_receipt(unit_index=0, receipt=receipt)
    store.put_storage(unit_index=0, storage=storage)
    store.put_seal(seal)
    store.put_cleanup(cleanup)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_terminal_invalid"):
        if mutation == "receipt":
            store.put_receipt(unit_index=0, receipt=receipt)
        elif mutation == "storage":
            store.put_storage(unit_index=0, storage=storage)
        elif mutation == "seal":
            store.put_seal(seal)
        elif mutation == "cleanup":
            store.put_cleanup(cleanup)
        else:
            store.put_admission(admission, units=units)
    store.validate()
    store.close()


@pytest.mark.parametrize("mutation", ["row", "delete", "schema"])
def test_store_tamper_and_deletion_fail_closed(tmp_path: Path, mutation: str) -> None:
    path = tmp_path / "tampered.sqlite3"
    admission, units = _admission()
    store = _created_store(path)
    store.put_admission(admission, units=units)
    checkpoint = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    store.close()
    connection = sqlite3.connect(path)
    if mutation == "row":
        connection.execute("UPDATE evidence SET payload_json='{}' WHERE sequence=1")
    elif mutation == "delete":
        connection.execute("DELETE FROM evidence WHERE sequence=1")
    else:
        connection.execute("CREATE TRIGGER forged AFTER INSERT ON evidence BEGIN SELECT 1; END")
    connection.commit()
    connection.close()
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_corrupt"):
        SQLiteMem0V5EvidenceStore.reopen(
            path=path,
            authentication_key=AUTH_KEY,
            checkpoint=checkpoint,
            checkpoint_key=CHECKPOINT_KEY,
        )


def test_store_detects_whole_file_deletion_and_rollback_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "rollback.sqlite3"
    admission, units = _admission()
    store = _created_store(path)
    store.put_admission(admission, units=units)
    old = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    store.put_receipt(unit_index=0, receipt=_receipt(admission))
    current = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    store.close()
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_corrupt"):
        SQLiteMem0V5EvidenceStore.reopen(
            path=path,
            authentication_key=AUTH_KEY,
            checkpoint=old,
            checkpoint_key=CHECKPOINT_KEY,
        )
    path.unlink()
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_corrupt"):
        SQLiteMem0V5EvidenceStore.reopen(
            path=path,
            authentication_key=AUTH_KEY,
            checkpoint=current,
            checkpoint_key=CHECKPOINT_KEY,
        )


def test_store_rejects_tampered_external_checkpoint_and_implicit_recreate(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.sqlite3"
    admission, units = _admission()
    store = _created_store(path)
    store.put_admission(admission, units=units)
    checkpoint = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    store.close()
    replacement = "0" if checkpoint.token[-1] != "0" else "1"
    forged = Mem0V5StoreCheckpoint(token=checkpoint.token[:-1] + replacement)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_corrupt"):
        SQLiteMem0V5EvidenceStore.reopen(
            path=path,
            authentication_key=AUTH_KEY,
            checkpoint=forged,
            checkpoint_key=CHECKPOINT_KEY,
        )
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_corrupt"):
        SQLiteMem0V5EvidenceStore.create(path=path, authentication_key=AUTH_KEY)


def test_checkpoint_rejects_deleted_head_row_without_full_semantic_scan(tmp_path: Path) -> None:
    admission, units = _admission()
    store = _created_store(tmp_path / "deleted-head.sqlite3")
    store.put_admission(admission, units=units)
    store._connection.execute(
        "DELETE FROM evidence WHERE sequence = (SELECT MAX(sequence) FROM evidence)"
    )
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_corrupt"):
        store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    store.close()


def test_single_owner_and_concurrent_admissions_are_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "concurrent.sqlite3"
    candidates = (_admission(), _admission_many(1))
    store = _created_store(path)
    barrier = threading.Barrier(3)
    outcomes: list[str] = []

    def write(candidate: tuple[Mem0OssFullRunAdmission, tuple[Mem0OssManifestUnit, ...]]) -> None:
        barrier.wait()
        try:
            store.put_admission(candidate[0], units=candidate[1])
            outcomes.append("written")
        except Mem0V5EvidenceStoreError as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=write, args=(candidate,)) for candidate in candidates]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["mem0_v5_evidence_store_order_invalid", "written"]
    store.validate()
    checkpoint = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_busy"):
        SQLiteMem0V5EvidenceStore.reopen(
            path=path,
            authentication_key=AUTH_KEY,
            checkpoint=checkpoint,
            checkpoint_key=CHECKPOINT_KEY,
        )
    store.close()
    reopened = SQLiteMem0V5EvidenceStore.reopen(
        path=path,
        authentication_key=AUTH_KEY,
        checkpoint=checkpoint,
        checkpoint_key=CHECKPOINT_KEY,
    )
    reopened.close()
