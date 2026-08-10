from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PHASE_C_ROOT = ROOT / "benchmarks" / "phase-c-canary"
UNIT_TEST_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PHASE_C_ROOT))
sys.path.insert(0, str(UNIT_TEST_ROOT))

import infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt as observed_module  # noqa: E402
from _phase_c_hermetic import install_hermetic_phase_c_authority  # noqa: E402
from infinity_context_adapters.postgres.managed_full_run_extraction_sqlite_ledger import (  # noqa: E402
    SQLiteManagedFullRunExtractionLedger,
)
from infinity_context_core.ports.managed_full_run_extraction_ledger import (  # noqa: E402
    ManagedFullRunExtractionContext,
)
from infinity_context_server.memory_comparison_managed_full_run_extraction_ledger import (  # noqa: E402
    ManagedFullRunExtractionDispatch,
    ManagedFullRunExtractionLedgerService,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (  # noqa: E402
    Mem0OssFullRunError,
    RuntimeReceiptVerificationContext,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (  # noqa: E402
    Mem0V5HttpError,
    Mem0V5RuntimeReceiptEnvelope,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (  # noqa: E402
    Mem0V5ObservedExtractionOperationAuthority,
    Mem0V5ObservedExtractionReceiptAuthority,
    Mem0V5ObservedExtractionReceiptVerifier,
    require_mem0_v5_observed_extraction_receipt_boundary,
)
from phase_c_canary.hashing import canonical_json_bytes  # noqa: E402
from phase_c_canary.receipt import NodePublicReceiptVerifier  # noqa: E402
from phase_c_canary.runtime_binding import RuntimeBindingComposition  # noqa: E402
from phase_c_canary.runtime_receipt_v2 import RuntimeReceiptV2Boundary  # noqa: E402

SECRET = "deterministic-receipt-secret-at-least-32-bytes"
_RUNTIME_REPO_ENV = os.environ.get("INFINITY_CONTEXT_PHASE_C_RUNTIME_REPO")
_NODE_EXECUTABLE_ENV = os.environ.get("INFINITY_CONTEXT_PHASE_C_NODE_EXECUTABLE")
RUNTIME_REPO = Path(_RUNTIME_REPO_ENV or "/explicit-hosting-runtime-unavailable")
NODE_EXECUTABLE = Path(_NODE_EXECUTABLE_ENV or "/usr/local/bin/node")
NODE_EXECUTABLE_SHA256 = "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"
E904_RUNTIME_SOURCE_SHA256 = "6c0bfa587ea52cea8b3cfff75980836ffa157efcc3f074ce97faa55d9bed4695"
E904_ARTIFACT_MANIFEST_SHA256 = "789018b5b15a1299252895babdc550c3d5322c54a1d9c82656f93d31423a0850"
HERMETIC_RUNTIME_SOURCE_SHA256 = "841d8d3dc7c815975d7b5cfd5fc0f811db7d9160a1cf66230bc43e5d72322d43"
_hosting_runtime_available = bool(_RUNTIME_REPO_ENV and _NODE_EXECUTABLE_ENV) and (
    RUNTIME_REPO.is_dir() and NODE_EXECUTABLE.is_file()
)
_requires_pinned_runtime = pytest.mark.skipif(
    not _hosting_runtime_available,
    reason="explicit pinned Phase-C runtime integration is unavailable",
)


@pytest.fixture(autouse=True)
def _hermetic_phase_c_authority(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[object, Path] | None:
    if "_real_phase_c_authority" in request.fixturenames:
        return None
    return install_hermetic_phase_c_authority(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        phase_c_root=PHASE_C_ROOT,
    )


@pytest.fixture
def _real_phase_c_authority() -> None:
    """Explicit opt-out: integration tests must consume the reviewed authority."""


def _assert_e904_binding(binding: object) -> None:
    from phase_c_canary.authority import immutable_authority

    reviewed = immutable_authority()
    artifact = reviewed.runtime_artifact_manifest.path
    assert _RUNTIME_REPO_ENV is not None
    assert _NODE_EXECUTABLE_ENV is not None
    assert reviewed.runtime_root / "repo" == RUNTIME_REPO
    assert artifact == RUNTIME_REPO.parent / "artifact-manifest.json"
    assert reviewed.runtime_artifact_manifest.sha256 == E904_ARTIFACT_MANIFEST_SHA256
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == E904_ARTIFACT_MANIFEST_SHA256
    assert binding.runtime_source_sha256 == E904_RUNTIME_SOURCE_SHA256
    assert binding.runtime_source_sha256 != HERMETIC_RUNTIME_SOURCE_SHA256


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class _DeterministicReceiptHmacVerifier:
    def verify(self, *, receipt: dict[str, Any], secret: str) -> None:
        unsigned = copy.deepcopy(receipt)
        metadata = unsigned["metadata"]
        presented = metadata.pop("receipt_hmac_sha256")
        expected = hmac.new(
            secret.encode(), canonical_json_bytes(unsigned), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(presented, expected):
            raise ValueError("receipt_hmac_invalid")


class _SecretConsumptionProbe:
    consumed = False

    def encode(self) -> bytes:
        self.consumed = True
        raise AssertionError("secret must not be consumed before boundary preflight")


def _sign(receipt: dict[str, Any]) -> dict[str, Any]:
    signed = copy.deepcopy(receipt)
    metadata = signed["metadata"]
    metadata.pop("receipt_hmac_sha256", None)
    metadata["receipt_hmac_sha256"] = hmac.new(
        SECRET.encode(), canonical_json_bytes(signed), hashlib.sha256
    ).hexdigest()
    return signed


def _binding() -> object:
    return RuntimeBindingComposition.compose_phase_c_canary().issue()


def test_ordinary_binding_is_exact_class_and_never_uses_hosting_authority(
    _hermetic_phase_c_authority: tuple[object, Path],
) -> None:
    reference, artifact = _hermetic_phase_c_authority
    binding = _binding()
    assert type(binding) is type(reference)
    assert binding.runtime_source_sha256 == reference.runtime_source_sha256
    assert binding.route_binding_sha256 == reference.route_binding_sha256
    assert artifact.name == "artifact-manifest.json"
    assert "/mnt/volume_ams3_" not in str(artifact)


def _authority(binding: object) -> Mem0V5ObservedExtractionReceiptAuthority:
    admission = _sha("admission")
    unit_identity = _sha("unit-identity")
    return Mem0V5ObservedExtractionReceiptAuthority(
        admission_commitment_sha256=admission,
        model="gpt-5.6-sol",
        reasoning_effort="high",
        service_tier="default",
        base_instructions_sha256=_sha("base-instructions"),
        runtime_source_sha256=binding.runtime_source_sha256,
        route_binding_sha256=binding.route_binding_sha256,
        account_binding_hmac_sha256=_sha("account-binding"),
        node_executable_path=str(NODE_EXECUTABLE),
        node_executable_sha256=NODE_EXECUTABLE_SHA256,
        response_format_type="json_schema",
        response_format_sha256=_sha("response-format"),
        response_schema_sha256=_sha("response-schema"),
        operations=(
            Mem0V5ObservedExtractionOperationAuthority(
                operation_id_sha256=canonical_sha256(
                    {
                        "admission_commitment_sha256": admission,
                        "unit_index": 0,
                        "unit_identity_sha256": unit_identity,
                    }
                ),
                unit_identity_sha256=unit_identity,
                unit_sha256=_sha("unit"),
                scope_sha256=_sha("scope"),
                sequence=0,
                request_body_sha256=_sha("request-body"),
            ),
        ),
    )


def _scaled_authority(
    binding: object,
    count: int,
) -> Mem0V5ObservedExtractionReceiptAuthority:
    base = _authority(binding)
    operations = tuple(
        Mem0V5ObservedExtractionOperationAuthority(
            operation_id_sha256=canonical_sha256(
                {
                    "admission_commitment_sha256": base.admission_commitment_sha256,
                    "unit_index": sequence,
                    "unit_identity_sha256": _sha(f"unit-identity-{sequence}"),
                }
            ),
            unit_identity_sha256=_sha(f"unit-identity-{sequence}"),
            unit_sha256=_sha(f"unit-{sequence}"),
            scope_sha256=_sha(f"scope-{sequence}"),
            sequence=sequence,
            request_body_sha256=_sha(f"request-{sequence}"),
        )
        for sequence in range(count)
    )
    return replace(base, operations=operations)


def _operation(
    authority: Mem0V5ObservedExtractionReceiptAuthority,
) -> Mem0V5ObservedExtractionOperationAuthority:
    return authority.operations[0]


class _SingleExpectedOperation:
    def __init__(self, operation_id_sha256: str, manifest_context_sha256: str) -> None:
        self.operation_id_sha256 = operation_id_sha256
        self.manifest_context_sha256 = manifest_context_sha256

    def read_operation_page(
        self,
        *,
        manifest_context_sha256: str,
        start_sequence: int,
    ) -> tuple[str, ...]:
        assert manifest_context_sha256 == self.manifest_context_sha256
        assert start_sequence == 0
        return (self.operation_id_sha256,)


def _verifier(
    *,
    binding: object | None = None,
) -> tuple[
    Mem0V5ObservedExtractionReceiptVerifier,
    Mem0V5ObservedExtractionReceiptAuthority,
]:
    selected_binding = binding or _binding()
    authority = _authority(selected_binding)
    return (
        Mem0V5ObservedExtractionReceiptVerifier._for_provider_free_tests(
            boundary=RuntimeReceiptV2Boundary(_DeterministicReceiptHmacVerifier()),
            runtime_binding=selected_binding,
            receipt_secret=SECRET,
            authority=authority,
        ),
        authority,
    )


def _context(
    authority: Mem0V5ObservedExtractionReceiptAuthority,
    *,
    readback: bool,
) -> RuntimeReceiptVerificationContext:
    operation = _operation(authority)
    return RuntimeReceiptVerificationContext(
        admission_commitment_sha256=authority.admission_commitment_sha256,
        operation_id_sha256=operation.operation_id_sha256,
        unit_identity_sha256=operation.unit_identity_sha256,
        unit_sha256=operation.unit_sha256,
        route_sha256=authority.route_binding_sha256,
        scope_sha256=operation.scope_sha256,
        readback_only=readback,
    )


def _unsigned_receipt(authority: Mem0V5ObservedExtractionReceiptAuthority) -> dict[str, Any]:
    operation = _operation(authority)
    return {
        "metadata": {
            "schema_version": 2,
            "attestation_level": "provider_receipt",
            "usage_source": "codex_thread_token_usage_updated",
            "runtime_selection": {
                "account_binding_hmac_sha256": authority.account_binding_hmac_sha256,
                "thread_id": "thread-provider-observed",
                "turn_id": "turn-provider-observed",
                "model": authority.model,
                "model_provider": "openai",
                "reasoning_effort": authority.reasoning_effort,
                "service_tier": authority.service_tier,
                "execution_profile": "stateless-completion",
                "base_instructions_sha256": authority.base_instructions_sha256,
            },
            "request_identity": {
                "public_model": authority.model,
                "client_requested_model": authority.model,
                "configured_codex_model": authority.model,
                "requested_codex_model": authority.model,
                "request_body_sha256": operation.request_body_sha256,
                "response_format_type": authority.response_format_type,
                "response_format_sha256": authority.response_format_sha256,
                "response_schema_sha256": authority.response_schema_sha256,
            },
            "output_identity": {
                "output_text_sha256": _sha("provider-output"),
                "terminal_status": "completed",
            },
            "output_token_limit": {
                "requested_tokens": authority.requested_output_tokens,
                "enforced": False,
            },
            "receipt_hmac_sha256": "0" * 64,
        },
        "usage": {
            "prompt_tokens": 11,
            "prompt_tokens_details": {"cached_tokens": 3},
            "completion_tokens": 5,
            "completion_tokens_details": {"reasoning_tokens": 2},
            "total_tokens": 16,
        },
    }


def _envelope(
    authority: Mem0V5ObservedExtractionReceiptAuthority,
    receipt: dict[str, Any],
) -> Mem0V5RuntimeReceiptEnvelope:
    operation = _operation(authority)
    return Mem0V5RuntimeReceiptEnvelope(
        admission_commitment_sha256=authority.admission_commitment_sha256,
        operation_id_sha256=operation.operation_id_sha256,
        runtime_receipt=receipt,
    )


def _sign_with_pinned_node(receipt: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(receipt)
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
        [str(NODE_EXECUTABLE), "--input-type=module", "-e", script],
        cwd=RUNTIME_REPO,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
        input=json.dumps({"receipt": result, "secret": SECRET, "canonical_url": canonical_url}),
        text=True,
        capture_output=True,
        check=True,
    )
    result["metadata"]["receipt_hmac_sha256"] = completed.stdout
    return result


def test_actual_phase_c_boundary_accepts_observed_provider_identity_once() -> None:
    binding = _binding()
    verifier, authority = _verifier(binding=binding)
    receipt = _sign(_unsigned_receipt(authority))

    result = verifier.verify_dispatch_receipt(
        payload=_envelope(authority, receipt),
        context=_context(authority, readback=False),
    )

    assert result.admission_commitment_sha256 == authority.admission_commitment_sha256
    assert result.operation_id_sha256 == _operation(authority).operation_id_sha256
    assert result.provider_receipt_sha256 != _sha("")
    assert result.sequence == 0
    assert result.request_body_sha256 == _operation(authority).request_body_sha256
    assert result.output_text_sha256 == _sha("provider-output")
    assert result.runtime_binding_commitment_sha256 == binding.commitment_sha256
    assert result.request_tokens == 11
    assert result.response_tokens == 5
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_runtime_receipt_replayed"):
        verifier.verify_dispatch_receipt(
            payload=_envelope(authority, receipt),
            context=_context(authority, readback=False),
        )


def test_scaled_authority_runtime_integrity_check_is_constant_per_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    authority = _scaled_authority(binding, 5_882)
    verifier = Mem0V5ObservedExtractionReceiptVerifier._for_provider_free_tests(
        boundary=RuntimeReceiptV2Boundary(_DeterministicReceiptHmacVerifier()),
        runtime_binding=binding,
        receipt_secret=SECRET,
        authority=authority,
    )
    operation = authority.operations[-1]
    context = RuntimeReceiptVerificationContext(
        admission_commitment_sha256=authority.admission_commitment_sha256,
        operation_id_sha256=operation.operation_id_sha256,
        unit_identity_sha256=operation.unit_identity_sha256,
        unit_sha256=operation.unit_sha256,
        route_sha256=authority.route_binding_sha256,
        scope_sha256=operation.scope_sha256,
        readback_only=False,
    )
    original_snapshot = observed_module._operation_snapshot
    snapshot_calls = 0

    def count_snapshot(
        selected: Mem0V5ObservedExtractionOperationAuthority,
    ) -> tuple[object, ...]:
        nonlocal snapshot_calls
        snapshot_calls += 1
        return original_snapshot(selected)

    monkeypatch.setattr(observed_module, "_operation_snapshot", count_snapshot)
    verifier.mark_outcome_unknown(context=context)
    assert snapshot_calls == 1

    object.__setattr__(operation, "request_body_sha256", _sha("tampered-request"))
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_runtime_receipt_state_invalid"):
        verifier.mark_outcome_unknown(context=context)


def test_actual_phase_c_receipt_flows_into_authenticated_full_run_ledger(
    tmp_path: Path,
) -> None:
    binding = _binding()
    verifier, authority = _verifier(binding=binding)
    operation = _operation(authority)
    receipt = _sign(_unsigned_receipt(authority))
    ledger = SQLiteManagedFullRunExtractionLedger.create(
        tmp_path / "observed-full-run.sqlite3",
        authentication_key=b"l" * 32,
    )
    service = ManagedFullRunExtractionLedgerService(
        ledger=ledger,
        expected_operations=_SingleExpectedOperation(
            operation.operation_id_sha256,
            _sha("a1-context"),
        ),
        receipt_verifier=verifier,
    )
    service.begin(
        ManagedFullRunExtractionContext(
            profile_id="managed-mem0-v5-publishable",
            run_id_sha256=_sha("run"),
            binding_commitment_sha256=_sha("binding"),
            methodology_commitment_sha256=_sha("methodology"),
            admission_commitment_sha256=authority.admission_commitment_sha256,
            ingestion_root_sha256=_sha("ingestion"),
            a1_terminal_commitment_sha256=_sha("a1-terminal"),
            a1_manifest_context_sha256=_sha("a1-context"),
            runtime_binding_commitment_sha256=binding.commitment_sha256,
            expected_receipt_count=1,
        )
    )
    service.verify_dispatch_page(
        (
            ManagedFullRunExtractionDispatch(
                receipt_payload=_envelope(authority, receipt),
                verification_context=_context(authority, readback=False),
            ),
        )
    )
    terminal = service.finalize()
    assert terminal.receipt_count == 1
    assert terminal.page_count == 1
    assert terminal.prompt_tokens == 11
    assert terminal.completion_tokens == 5
    assert terminal.total_tokens == 16
    service.close()

    reopened = SQLiteManagedFullRunExtractionLedger.open(
        tmp_path / "observed-full-run.sqlite3",
        authentication_key=b"l" * 32,
    )
    assert reopened.readback() == terminal
    assert operation.request_body_sha256 != _sha("provider-output")
    reopened.close()


@_requires_pinned_runtime
def test_public_live_constructor_requires_and_uses_pinned_node_verifier(
    _real_phase_c_authority: None,
) -> None:
    binding = _binding()
    _assert_e904_binding(binding)
    authority = _authority(binding)
    boundary = RuntimeReceiptV2Boundary(
        NodePublicReceiptVerifier(RUNTIME_REPO, node_executable=NODE_EXECUTABLE)
    )
    receipt = _sign_with_pinned_node(_unsigned_receipt(authority))
    verifier = Mem0V5ObservedExtractionReceiptVerifier(
        boundary=boundary,
        runtime_binding=binding,
        receipt_secret=SECRET,
        authority=authority,
    )
    assert (
        verifier.verify_dispatch_receipt(
            payload=_envelope(authority, receipt),
            context=_context(authority, readback=False),
        ).operation_id_sha256
        == _operation(authority).operation_id_sha256
    )

    forged = copy.deepcopy(receipt)
    forged["metadata"]["receipt_hmac_sha256"] = "f" * 64
    verifier = Mem0V5ObservedExtractionReceiptVerifier(
        boundary=boundary,
        runtime_binding=binding,
        receipt_secret=SECRET,
        authority=authority,
    )
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_runtime_receipt_unauthenticated"):
        verifier.verify_dispatch_receipt(
            payload=_envelope(authority, forged),
            context=_context(authority, readback=False),
        )


def test_forged_hmac_is_rejected_without_consuming_the_operation() -> None:
    verifier, authority = _verifier()
    forged = _sign(_unsigned_receipt(authority))
    forged["metadata"]["receipt_hmac_sha256"] = "f" * 64

    with pytest.raises(Mem0V5HttpError, match="mem0_v5_runtime_receipt_unauthenticated"):
        verifier.verify_dispatch_receipt(
            payload=_envelope(authority, forged),
            context=_context(authority, readback=False),
        )

    authentic = _sign(_unsigned_receipt(authority))
    assert (
        verifier.verify_dispatch_receipt(
            payload=_envelope(authority, authentic),
            context=_context(authority, readback=False),
        ).operation_id_sha256
        == _operation(authority).operation_id_sha256
    )


@pytest.mark.parametrize(
    ("section", "field", "drift"),
    (
        ("runtime_selection", "model", "gpt-5.6-terra"),
        ("request_identity", "request_body_sha256", _sha("other-request")),
        ("output_token_limit", "requested_tokens", 2048),
    ),
)
def test_authentic_receipt_static_field_drift_is_rejected(
    section: str,
    field: str,
    drift: object,
) -> None:
    verifier, authority = _verifier()
    receipt = _unsigned_receipt(authority)
    receipt["metadata"][section][field] = drift

    with pytest.raises(Mem0V5HttpError, match="mem0_v5_runtime_receipt_unauthenticated"):
        verifier.verify_dispatch_receipt(
            payload=_envelope(authority, _sign(receipt)),
            context=_context(authority, readback=False),
        )


def test_wrong_operation_and_context_binding_are_rejected_before_boundary() -> None:
    verifier, authority = _verifier()
    receipt = _sign(_unsigned_receipt(authority))
    wrong_envelope = replace(_envelope(authority, receipt), operation_id_sha256=_sha("wrong"))
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_runtime_receipt_invalid"):
        verifier.verify_dispatch_receipt(
            payload=wrong_envelope,
            context=_context(authority, readback=False),
        )

    wrong_context = replace(_context(authority, readback=False), scope_sha256=_sha("wrong"))
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_runtime_receipt_invalid"):
        verifier.verify_dispatch_receipt(
            payload=_envelope(authority, receipt),
            context=wrong_context,
        )


def test_non_authentic_boundary_and_binding_are_rejected_at_composition() -> None:
    binding = _binding()
    authority = _authority(binding)
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_configuration_invalid"):
        Mem0V5ObservedExtractionReceiptVerifier(
            boundary=object(),
            runtime_binding=binding,
            receipt_secret=SECRET,
            authority=authority,
        )
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_configuration_invalid"):
        Mem0V5ObservedExtractionReceiptVerifier(
            boundary=RuntimeReceiptV2Boundary(_DeterministicReceiptHmacVerifier()),
            runtime_binding=object(),
            receipt_secret=SECRET,
            authority=authority,
        )


def test_public_constructor_rejects_noop_nested_verifier_before_secret_consumption() -> None:
    binding = _binding()
    authority = _authority(binding)
    secret = _SecretConsumptionProbe()
    fake_boundary = RuntimeReceiptV2Boundary(_DeterministicReceiptHmacVerifier())

    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_configuration_invalid"):
        require_mem0_v5_observed_extraction_receipt_boundary(
            boundary=fake_boundary,
            runtime_binding=binding,
            authority=authority,
        )
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_configuration_invalid"):
        Mem0V5ObservedExtractionReceiptVerifier(
            boundary=fake_boundary,
            runtime_binding=binding,
            receipt_secret=secret,  # type: ignore[arg-type]
            authority=authority,
        )
    assert secret.consumed is False


def test_attacker_executable_is_rejected_before_secret_consumption(tmp_path: Path) -> None:
    binding = _binding()
    secret = _SecretConsumptionProbe()
    attacker = tmp_path / "node"
    attacker.write_text("#!/bin/sh\nprintf 'verified\\n'\n", encoding="utf-8")
    attacker.chmod(0o700)
    authority = replace(
        _authority(binding),
        node_executable_path=str(attacker),
        node_executable_sha256=hashlib.sha256(attacker.read_bytes()).hexdigest(),
    )
    boundary = RuntimeReceiptV2Boundary(
        NodePublicReceiptVerifier(RUNTIME_REPO, node_executable=attacker)
    )

    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_configuration_invalid"):
        Mem0V5ObservedExtractionReceiptVerifier(
            boundary=boundary,
            runtime_binding=binding,
            receipt_secret=secret,  # type: ignore[arg-type]
            authority=authority,
        )
    assert secret.consumed is False


@_requires_pinned_runtime
def test_node_hash_drift_is_rejected_before_secret_consumption(
    _real_phase_c_authority: None,
) -> None:
    binding = _binding()
    _assert_e904_binding(binding)
    authority = replace(_authority(binding), node_executable_sha256=_sha("wrong-node"))
    secret = _SecretConsumptionProbe()
    boundary = RuntimeReceiptV2Boundary(
        NodePublicReceiptVerifier(RUNTIME_REPO, node_executable=NODE_EXECUTABLE)
    )

    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_configuration_invalid"):
        Mem0V5ObservedExtractionReceiptVerifier(
            boundary=boundary,
            runtime_binding=binding,
            receipt_secret=secret,  # type: ignore[arg-type]
            authority=authority,
        )
    assert secret.consumed is False


@_requires_pinned_runtime
def test_authority_and_verifier_node_path_mismatch_is_rejected_before_secret(
    _real_phase_c_authority: None,
) -> None:
    binding = _binding()
    _assert_e904_binding(binding)
    authority = replace(_authority(binding), node_executable_path="/different/node")
    secret = _SecretConsumptionProbe()
    boundary = RuntimeReceiptV2Boundary(
        NodePublicReceiptVerifier(RUNTIME_REPO, node_executable=NODE_EXECUTABLE)
    )

    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_configuration_invalid"):
        Mem0V5ObservedExtractionReceiptVerifier(
            boundary=boundary,
            runtime_binding=binding,
            receipt_secret=secret,  # type: ignore[arg-type]
            authority=authority,
        )
    assert secret.consumed is False


@pytest.mark.parametrize(
    ("section", "field", "malformed"),
    (
        ("runtime_selection", "thread_id", ""),
        ("runtime_selection", "turn_id", {"private": "value"}),
        ("output_identity", "output_text_sha256", "not-a-digest"),
    ),
)
def test_malformed_observed_provider_fields_are_rejected_safely(
    section: str,
    field: str,
    malformed: object,
) -> None:
    verifier, authority = _verifier()
    receipt = _unsigned_receipt(authority)
    receipt["metadata"][section][field] = malformed

    with pytest.raises(Mem0V5HttpError) as caught:
        verifier.verify_dispatch_receipt(
            payload=_envelope(authority, receipt),
            context=_context(authority, readback=False),
        )
    assert caught.value.code == "mem0_v5_runtime_receipt_invalid"
    assert "private" not in str(caught.value)


def test_outcome_unknown_is_idempotent_and_status_recovery_is_fresh_process_safe() -> None:
    binding = _binding()
    verifier, authority = _verifier(binding=binding)
    receipt = _sign(_unsigned_receipt(authority))
    dispatch = _context(authority, readback=False)
    readback = _context(authority, readback=True)

    verifier.mark_outcome_unknown(context=dispatch)
    verifier.mark_outcome_unknown(context=dispatch)
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_runtime_receipt_state_invalid"):
        verifier.verify_dispatch_receipt(
            payload=_envelope(authority, receipt),
            context=dispatch,
        )
    assert (
        verifier.verify_status_readback(
            payload=_envelope(authority, receipt),
            context=readback,
        ).operation_id_sha256
        == _operation(authority).operation_id_sha256
    )

    fresh, fresh_authority = _verifier(binding=binding)
    assert fresh_authority == authority
    assert fresh.verify_status_readback(
        payload=_envelope(authority, receipt),
        context=readback,
    ).provider_receipt_sha256 != _sha("")
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_runtime_receipt_replayed"):
        fresh.verify_status_readback(
            payload=_envelope(authority, receipt),
            context=readback,
        )


def test_dispatch_and_status_require_matching_context_modes() -> None:
    verifier, authority = _verifier()
    receipt = _sign(_unsigned_receipt(authority))
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_receipt_context_invalid"):
        verifier.verify_dispatch_receipt(
            payload=_envelope(authority, receipt),
            context=_context(authority, readback=True),
        )
    with pytest.raises(Mem0OssFullRunError, match="mem0_v5_receipt_context_invalid"):
        verifier.verify_status_readback(
            payload=_envelope(authority, receipt),
            context=_context(authority, readback=False),
        )


def test_authority_requires_exact_single_extraction_output_limit() -> None:
    binding = _binding()
    with pytest.raises(Mem0V5HttpError, match="mem0_v5_http_configuration_invalid"):
        replace(_authority(binding), requested_output_tokens=2048)
