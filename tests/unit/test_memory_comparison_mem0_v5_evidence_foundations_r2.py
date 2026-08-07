from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_server import memory_comparison_clean_state as clean_state_module
from infinity_context_server.memory_comparison_clean_state import (
    fresh_namespace_clean_state_proof,
)
from infinity_context_server.memory_comparison_full_execution_evidence_variants import (
    inspect_full_execution_clean_state_evidence,
    issue_infinity_di_full_execution_clean_state_evidence,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCleanScope,
    FullExecutionValidationError,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    HmacSha256ManagedMem0V5EvidenceVerifier,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    create_managed_mem0_v5_storage_witness_authority,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5CleanStateReceipt,
    Mem0V5CleanStateRequest,
    Mem0V5CleanStateScope,
    Mem0V5HttpError,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_native_infinity_claim_uses_only_exact_infinity_proofs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = b"infinity-only-attestation-key!!" * 2
    corpus = _sha("corpus")
    scope = _sha("space")
    proof = fresh_namespace_clean_state_proof(
        backend="infinity-context",
        run_id="run-1",
        expected_slug="space",
        corpus_identity_sha256=corpus,
        expected_scope_count=1,
        status_code=201,
        payload={"data": {"slug": "space"}},
        attestation_key=key,
    )

    legacy_mem0_calls = 0

    def reject_legacy_mem0(**_values: object) -> object:
        nonlocal legacy_mem0_calls
        legacy_mem0_calls += 1
        raise AssertionError("native Infinity claim called legacy Mem0 proof API")

    monkeypatch.setattr(
        clean_state_module,
        "mem0_delete_clean_state_proof",
        reject_legacy_mem0,
    )
    claim = issue_infinity_di_full_execution_clean_state_evidence(
        corpus_ids=("corpus",),
        proofs=(proof,),
        scopes=(FullExecutionCleanScope("infinity-context", corpus, scope),),
        attestation_key=key,
    )

    descriptor = inspect_full_execution_clean_state_evidence(claim)
    assert descriptor.variant == "infinity_di"
    assert descriptor.backend_roles == ("infinity-context",)
    assert descriptor.corpus_scopes == ((canonical_sha256({"corpus_id": "corpus"}), scope, 0),)
    assert legacy_mem0_calls == 0


def test_native_infinity_claim_rejects_forged_or_reordered_proofs() -> None:
    key = b"infinity-only-attestation-key!!" * 2
    corpus_ids = ("corpus-1", "corpus-2")
    corpus = tuple(_sha(item) for item in corpus_ids)
    proofs = tuple(
        fresh_namespace_clean_state_proof(
            backend="infinity-context",
            run_id="run-1",
            expected_slug=f"space-{index}",
            corpus_identity_sha256=item,
            expected_scope_count=2,
            status_code=201,
            payload={"data": {"slug": f"space-{index}"}},
            attestation_key=key,
        )
        for index, item in enumerate(corpus)
    )
    scopes = tuple(
        FullExecutionCleanScope("infinity-context", item, _sha(f"space-{index}"))
        for index, item in enumerate(corpus)
    )

    with pytest.raises(FullExecutionValidationError, match="binding_invalid"):
        issue_infinity_di_full_execution_clean_state_evidence(
            corpus_ids=corpus_ids,
            proofs=proofs[::-1],
            scopes=scopes,
            attestation_key=key,
        )
    with pytest.raises(FullExecutionValidationError, match="binding_invalid"):
        issue_infinity_di_full_execution_clean_state_evidence(
            corpus_ids=corpus_ids,
            proofs=(replace(proofs[0], attestation_hmac_sha256="0" * 64), proofs[1]),
            scopes=scopes,
            attestation_key=key,
        )
    with pytest.raises(FullExecutionValidationError, match="binding_invalid"):
        issue_infinity_di_full_execution_clean_state_evidence(
            corpus_ids=corpus_ids,
            proofs=proofs,
            scopes=scopes,
            attestation_key=b"foreign-attestation-key-value!!" * 2,
        )


def test_native_infinity_claim_rejects_cross_corpus_splice() -> None:
    key = b"infinity-only-attestation-key!!" * 2
    corpus_id = "corpus-1"
    proof_corpus = _sha(corpus_id)
    scope = _sha("space")
    proof = fresh_namespace_clean_state_proof(
        backend="infinity-context",
        run_id="run-1",
        expected_slug="space",
        corpus_identity_sha256=proof_corpus,
        expected_scope_count=1,
        status_code=201,
        payload={"data": {"slug": "space"}},
        attestation_key=key,
    )

    with pytest.raises(FullExecutionValidationError, match="binding_invalid"):
        issue_infinity_di_full_execution_clean_state_evidence(
            corpus_ids=("corpus-2",),
            proofs=(proof,),
            scopes=(FullExecutionCleanScope("infinity-context", proof_corpus, scope),),
            attestation_key=key,
        )


def _clean_request() -> Mem0V5CleanStateRequest:
    scope = Mem0V5CleanStateScope(
        _sha("corpus"),
        _sha("scope"),
        1,
        0,
        MEM0_OSS_EMPTY_ROOT_SHA256,
    )
    admission = _sha("admission")
    return Mem0V5CleanStateRequest(
        admission,
        _sha("run"),
        _sha("authority"),
        1,
        _sha("credential"),
        "runtime-r1",
        _sha("runtime-source"),
        _sha("runtime-base"),
        _sha("runtime-binding"),
        (scope,),
        canonical_sha256({"kind": "clean-state", "binding": admission}),
    )


@pytest.mark.parametrize("residual_record_count", (False, True))
def test_clean_state_scope_rejects_boolean_residual_count(
    residual_record_count: bool,
) -> None:
    with pytest.raises(Mem0V5HttpError, match="request_invalid"):
        Mem0V5CleanStateScope(
            _sha("corpus"),
            _sha("scope"),
            1,
            residual_record_count,
            MEM0_OSS_EMPTY_ROOT_SHA256,
        )


def test_clean_state_scope_requires_exact_empty_root() -> None:
    with pytest.raises(Mem0V5HttpError, match="request_invalid"):
        Mem0V5CleanStateScope(
            _sha("corpus"),
            _sha("scope"),
            1,
            0,
            _sha("not-empty"),
        )


def _clean_ingestion_context() -> tuple[str, str]:
    return _sha("manifest"), _sha("root")


def _response(request: Mem0V5CleanStateRequest, key: bytes) -> dict[str, object]:
    ingestion_manifest_sha256, ingestion_root_sha256 = _clean_ingestion_context()
    base = {
        "schema_version": "mem0-oss-adapter-v5.clean-state.v1",
        "admission_commitment_sha256": request.admission_commitment_sha256,
        "run_id_sha256": request.run_id_sha256,
        "authority_commitment_sha256": request.authority_commitment_sha256,
        "ingestion_manifest_sha256": ingestion_manifest_sha256,
        "ingestion_root_sha256": ingestion_root_sha256,
        "runtime_binding_commitment_sha256": request.runtime_binding_commitment_sha256,
        "request_commitment_sha256": canonical_sha256(request.body()),
        "request_id_sha256": request.idempotency_key,
        "scope_count": len(request.scopes),
        "scope_inventory_root_sha256": canonical_sha256(
            {"scopes": [item.body() for item in request.scopes]}
        ),
        "scopes": [item.body() for item in request.scopes],
    }
    unsigned = {**base, "evidence_commitment_sha256": canonical_sha256(base)}
    root = hmac.new(key, b"mem0-oss-adapter-v5/evidence-key/v1", hashlib.sha256).digest()
    signing_key = hmac.new(root, b"clean-state/v1", hashlib.sha256).digest()
    encoded = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    return {
        **unsigned,
        "clean_state_hmac_sha256": hmac.new(signing_key, encoded, hashlib.sha256).hexdigest(),
    }


def _resign(payload: dict[str, object], key: bytes) -> None:
    unsigned = {name: value for name, value in payload.items() if name != "clean_state_hmac_sha256"}
    encoded = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    root = hmac.new(key, b"mem0-oss-adapter-v5/evidence-key/v1", hashlib.sha256).digest()
    signing_key = hmac.new(root, b"clean-state/v1", hashlib.sha256).digest()
    payload["clean_state_hmac_sha256"] = hmac.new(signing_key, encoded, hashlib.sha256).hexdigest()


class _EvidenceKey:
    def __init__(self, key: bytes) -> None:
        self.key = key
        self.consumed = False

    def validate(self) -> None:
        assert not self.consumed
        assert 32 <= len(self.key) <= 4_096

    def consume(self) -> bytes:
        assert not self.consumed
        self.consumed = True
        return self.key


def _clean_verifier(key: bytes) -> HmacSha256ManagedMem0V5EvidenceVerifier:
    issuer, _verifier = create_managed_mem0_v5_storage_witness_authority()
    return HmacSha256ManagedMem0V5EvidenceVerifier(
        key_capability=_EvidenceKey(key),
        storage_witness_issuer=issuer,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(run_id_sha256=_sha("foreign-run")),
        lambda payload: payload.update(request_id_sha256=_sha("foreign-idempotency")),
        lambda payload: payload["scopes"].append(payload["scopes"][0]),
        lambda payload: payload["scopes"][0].update(residual_record_count=1),
        lambda payload: payload.update(clean_state_hmac_sha256="0" * 64),
    ],
)
def test_clean_state_http_verifier_fails_closed_on_response_mutation(mutation) -> None:
    key = b"response-hmac-key" * 2
    request = _clean_request()
    payload = _response(request, key)
    mutation(payload)
    ingestion_manifest_sha256, ingestion_root_sha256 = _clean_ingestion_context()

    with pytest.raises(Mem0V5HttpError):
        _clean_verifier(key).verify_clean_state(
            receipt=Mem0V5CleanStateReceipt(payload),
            request=request,
            ingestion_manifest_sha256=ingestion_manifest_sha256,
            ingestion_root_sha256=ingestion_root_sha256,
        )


@pytest.mark.parametrize("mode", ("missing", "duplicate", "reordered", "nonzero"))
def test_clean_state_http_verifier_rejects_resigned_scope_set_changes(mode: str) -> None:
    key = b"response-hmac-key" * 2
    scopes = tuple(
        Mem0V5CleanStateScope(
            _sha(f"corpus-{index}"),
            _sha(f"scope-{index}"),
            1,
            0,
            MEM0_OSS_EMPTY_ROOT_SHA256,
        )
        for index in range(2)
    )
    request = replace(_clean_request(), scopes=scopes)
    payload = _response(request, key)
    response_scopes = payload["scopes"]
    assert isinstance(response_scopes, list)
    if mode == "missing":
        response_scopes.pop()
    elif mode == "duplicate":
        response_scopes.append(response_scopes[0])
    elif mode == "reordered":
        response_scopes.reverse()
    else:
        response_scopes[0]["residual_record_count"] = 1
    _resign(payload, key)
    ingestion_manifest_sha256, ingestion_root_sha256 = _clean_ingestion_context()

    with pytest.raises(Mem0V5HttpError):
        _clean_verifier(key).verify_clean_state(
            receipt=Mem0V5CleanStateReceipt(payload),
            request=request,
            ingestion_manifest_sha256=ingestion_manifest_sha256,
            ingestion_root_sha256=ingestion_root_sha256,
        )


@pytest.mark.parametrize(
    "field",
    (
        "admission_commitment_sha256",
        "run_id_sha256",
        "authority_commitment_sha256",
        "request_id_sha256",
        "request_commitment_sha256",
    ),
)
def test_clean_state_http_verifier_rejects_resigned_binding_changes(field: str) -> None:
    key = b"response-hmac-key" * 2
    request = _clean_request()
    payload = _response(request, key)
    payload[field] = _sha(f"foreign-{field}")
    _resign(payload, key)
    ingestion_manifest_sha256, ingestion_root_sha256 = _clean_ingestion_context()

    with pytest.raises(Mem0V5HttpError):
        _clean_verifier(key).verify_clean_state(
            receipt=Mem0V5CleanStateReceipt(payload),
            request=request,
            ingestion_manifest_sha256=ingestion_manifest_sha256,
            ingestion_root_sha256=ingestion_root_sha256,
        )


def test_low_level_paired_bridge_does_not_import_full_execution_evidence() -> None:
    module_path = (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "infinity_context_server"
        / "infinity_context_server"
        / "memory_comparison_managed_mem0_v5_paired_bridge.py"
    )
    source = module_path.read_text(encoding="utf-8")

    assert "memory_comparison_full_execution_evidence_variants" not in source
