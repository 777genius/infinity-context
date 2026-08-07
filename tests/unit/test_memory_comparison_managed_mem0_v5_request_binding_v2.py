from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_request_binding import (
    REQUEST_BINDING_V2_DOMAIN,
    REQUEST_BINDING_V2_SCHEMA,
    ManagedMem0V5RequestBindingContext,
    ManagedMem0V5RequestBindingV2Context,
    verify_request_binding_payload,
    verify_request_binding_v2_payload,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import canonical_sha256
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5HttpError

KEY = b"k" * 32


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _context() -> ManagedMem0V5RequestBindingV2Context:
    return ManagedMem0V5RequestBindingV2Context(
        admission_commitment_sha256="a" * 64,
        operation_id_sha256="b" * 64,
        unit_identity_sha256="c" * 64,
        unit_sha256="d" * 64,
        corpus_id="corpus-1",
        source_id="source-1",
        source_sha256="e" * 64,
        observation_date="2026-08-07",
        observation_date_commitment_sha256=canonical_sha256({"observation_date": "2026-08-07"}),
    )


def _payload(context: ManagedMem0V5RequestBindingV2Context) -> dict[str, object]:
    evidence = {**context.evidence_payload(), "request_body_sha256": "f" * 64}
    unsigned = {
        **evidence,
        "request_binding_evidence_sha256": canonical_sha256(evidence),
    }
    return {
        **unsigned,
        "request_binding_hmac_sha256": hmac.new(
            KEY, _canonical(unsigned), hashlib.sha256
        ).hexdigest(),
    }


def test_v2_authenticates_exact_source_and_request_tuple() -> None:
    context = _context()
    witness = verify_request_binding_v2_payload(
        payload=_payload(context), context=context, hmac_key=KEY
    )
    receipt = witness.receipt

    assert receipt.corpus_id == "corpus-1"
    assert receipt.observation_date == "2026-08-07"
    assert receipt.request_body_sha256 == "f" * 64
    assert receipt.request_binding_evidence_sha256 == canonical_sha256(
        {**context.evidence_payload(), "request_body_sha256": "f" * 64}
    )
    assert REQUEST_BINDING_V2_SCHEMA.endswith(".v2")
    assert REQUEST_BINDING_V2_DOMAIN == b"request-binding/v2"


@pytest.mark.parametrize(
    "field,value",
    (
        ("corpus_id", "other"),
        ("source_sha256", "0" * 64),
        ("observation_date", "2026-08-08"),
        ("request_body_sha256", "0" * 64),
        ("request_binding_evidence_sha256", "0" * 64),
    ),
)
def test_v2_fails_closed_for_authenticated_or_unsigned_tamper(field: str, value: object) -> None:
    payload = _payload(_context())
    payload[field] = value
    with pytest.raises(Mem0V5HttpError):
        verify_request_binding_v2_payload(payload=payload, context=_context(), hmac_key=KEY)


def test_v1_does_not_accept_v2_and_remains_reproducible() -> None:
    v1 = ManagedMem0V5RequestBindingContext(
        "a" * 64,
        "1" * 64,
        "2" * 64,
        "3" * 64,
        "b" * 64,
        "c" * 64,
        "d" * 64,
        "4" * 64,
        "source-1",
        "e" * 64,
        0,
    )
    with pytest.raises(Mem0V5HttpError):
        verify_request_binding_payload(payload=_payload(_context()), context=v1, hmac_key=KEY)
    with pytest.raises(Mem0V5HttpError):
        verify_request_binding_v2_payload(payload={}, context=_context(), hmac_key=b"short")
