"""Exact clean-state HMAC verification shared by the managed v5 lane."""

from __future__ import annotations

import hashlib
import hmac
import json

from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5CleanStateReceipt,
    Mem0V5CleanStateRequest,
    Mem0V5CleanStateScope,
    Mem0V5HttpError,
)


def verify_clean_state_receipt(
    *,
    signing_key: bytes,
    receipt: Mem0V5CleanStateReceipt,
    request: Mem0V5CleanStateRequest,
    ingestion_manifest_sha256: str,
    ingestion_root_sha256: str,
) -> tuple[Mem0V5CleanStateScope, ...]:
    if (
        type(signing_key) is not bytes
        or len(signing_key) != hashlib.sha256().digest_size
        or type(receipt) is not Mem0V5CleanStateReceipt
        or type(request) is not Mem0V5CleanStateRequest
        or not is_sha256(ingestion_manifest_sha256)
        or not is_sha256(ingestion_root_sha256)
    ):
        _fail()
    value = receipt.payload
    try:
        scopes = tuple(Mem0V5CleanStateScope(**item) for item in value["scopes"])
    except Exception:
        _fail()
    base = {
        key: item
        for key, item in value.items()
        if key not in {"evidence_commitment_sha256", "clean_state_hmac_sha256"}
    }
    signed = {**base, "evidence_commitment_sha256": value["evidence_commitment_sha256"]}
    expected = {
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
    if (
        base != expected
        or scopes != request.scopes
        or value["evidence_commitment_sha256"] != canonical_sha256(base)
        or not _valid_hmac(signing_key, signed, value["clean_state_hmac_sha256"])
    ):
        _fail()
    return scopes


def _valid_hmac(key: bytes, payload: dict[str, object], signature: object) -> bool:
    if not is_sha256(signature):
        return False
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()
    expected = hmac.new(key, encoded, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.encode())


def _fail() -> None:
    raise Mem0V5HttpError("mem0_v5_http_response_invalid")


__all__ = ("verify_clean_state_receipt",)
