from __future__ import annotations

import json

import httpx
import pytest
from infinity_context_server.memory_comparison_clean_state import (
    CleanStateProofError,
    clean_state_identity_sha256,
    public_clean_state_proof,
)
from infinity_context_server.memory_comparison_clean_state_http import (
    InfinityCleanStateSession,
    Mem0CleanStateSession,
)

_KEY = b"h" * 32
_CORPUS = clean_state_identity_sha256("corpus")


def test_infinity_session_requires_fresh_namespace_and_retains_proof() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": "space-1",
                    "slug": "benchmark-space",
                    "name": "Benchmark Space",
                    "status": "active",
                    "created_at": "2026-07-31T12:00:00Z",
                    "updated_at": "2026-07-31T12:00:00Z",
                }
            },
        )

    session = InfinityCleanStateSession(backend="infinity-context")
    with httpx.Client(
        base_url="http://infinity.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        proof = session.reset(
            client,
            run_id="sensitive-run-id",
            slug="benchmark-space",
            corpus_identity_sha256=_CORPUS,
            expected_scope_count=1,
            attestation_key=_KEY,
        )

    payload = public_clean_state_proof(proof)
    assert json.loads(requests[0].content) == {
        "slug": "benchmark-space",
        "name": "benchmark-space",
    }
    assert session.proof_for_ingest() is proof
    assert session.proofs() == (proof,)
    assert payload["verified"] is True
    assert payload["http_status_code"] == 201
    assert "sensitive-run-id" not in json.dumps(payload)
    assert "benchmark-space" not in json.dumps(payload)
    assert _KEY.hex() not in json.dumps(payload)


@pytest.mark.parametrize(
    ("status_code", "payload"),
    [
        (200, {"data": {"slug": "benchmark-space"}}),
        (201, {"slug": "benchmark-space"}),
        (201, {"data": {"slug": "other-space"}}),
        (201, {"data": {"slug": "benchmark-space"}, "raw_user_id": "secret"}),
    ],
)
def test_infinity_session_rejects_duplicate_or_non_exact_create_response(
    status_code: int,
    payload: dict[str, object],
) -> None:
    session = InfinityCleanStateSession(backend="infinity-context")
    transport = httpx.MockTransport(lambda _: httpx.Response(status_code, json=payload))
    with (
        httpx.Client(base_url="http://infinity.test", transport=transport) as client,
        pytest.raises(CleanStateProofError, match="clean_state_namespace_ack_invalid"),
    ):
        session.reset(
            client,
            run_id="run",
            slug="benchmark-space",
            corpus_identity_sha256=_CORPUS,
            expected_scope_count=1,
            attestation_key=_KEY,
        )

    assert session.proofs() == ()


def test_infinity_malformed_ack_uses_safe_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, text="provider raw response")

    session = InfinityCleanStateSession(backend="infinity-context")
    with (
        httpx.Client(
            base_url="http://infinity.test",
            transport=httpx.MockTransport(handler),
        ) as client,
        pytest.raises(CleanStateProofError) as raised,
    ):
        session.reset(
            client,
            run_id="private-run",
            slug="private-space",
            corpus_identity_sha256=_CORPUS,
            expected_scope_count=1,
            attestation_key=_KEY,
        )

    assert raised.value.code == "clean_state_namespace_ack_malformed"
    assert raised.value.__cause__ is None


def test_mem0_session_records_only_authenticated_hashes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"deleted": True, "verified_absent": True})

    session = Mem0CleanStateSession(reset_enabled=True)
    with httpx.Client(
        base_url="http://mem0.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        proof = session.reset_scope(
            client,
            user_id="private-user-scope",
            run_id="private-run-id",
            corpus_identity_sha256=_CORPUS,
            expected_scope_count=1,
            attestation_key=_KEY,
            record=True,
        )

    payload = public_clean_state_proof(proof)
    assert requests[0].method == "DELETE"
    assert session.proofs() == (proof,)
    assert payload["deleted"] is True
    assert payload["verified_absent"] is True
    assert "private-user-scope" not in json.dumps(payload)
    assert "private-run-id" not in json.dumps(payload)


def test_mem0_fails_closed_when_delete_cannot_prove_absence() -> None:
    session = Mem0CleanStateSession(reset_enabled=True)
    with (
        httpx.Client(
            base_url="http://mem0.test",
            transport=httpx.MockTransport(lambda _: httpx.Response(204)),
        ) as client,
        pytest.raises(CleanStateProofError, match="mem0_delete_ack_invalid"),
    ):
        session.reset_scope(
            client,
            user_id="scope",
            run_id="run",
            corpus_identity_sha256=_CORPUS,
            expected_scope_count=1,
            attestation_key=_KEY,
        )
    assert session.proofs() == ()


def test_mem0_diagnostic_skip_is_authenticated_but_unverified() -> None:
    session = Mem0CleanStateSession(reset_enabled=False)
    with httpx.Client(base_url="http://mem0.test") as client:
        proof = session.reset_scope(
            client,
            user_id="diagnostic-scope",
            run_id="diagnostic-run",
            corpus_identity_sha256=_CORPUS,
            expected_scope_count=1,
            attestation_key=_KEY,
            record=True,
        )

    payload = public_clean_state_proof(proof)
    assert payload["verified"] is False
    assert payload["reason_code"] == "mem0_reset_disabled"
    assert session.proofs() == (proof,)


def test_transport_error_is_replaced_with_safe_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private-user-scope leaked", request=request)

    session = Mem0CleanStateSession(reset_enabled=True)
    with (
        httpx.Client(
            base_url="http://mem0.test",
            transport=httpx.MockTransport(handler),
        ) as client,
        pytest.raises(CleanStateProofError) as raised,
    ):
        session.reset_scope(
            client,
            user_id="private-user-scope",
            run_id="private-run-id",
            corpus_identity_sha256=_CORPUS,
            expected_scope_count=1,
            attestation_key=_KEY,
        )

    assert raised.value.code == "mem0_delete_request_failed"
    assert str(raised.value) == "mem0_delete_request_failed"
    assert raised.value.__cause__ is None
