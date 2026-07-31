from __future__ import annotations

import hashlib
import json

import pytest
from infinity_context_server.memory_comparison_mem0_official_chat import (
    APPROVED_OPENAI_ENDPOINT_PATH,
    APPROVED_OPENAI_ORIGIN,
    OFFICIAL_OPENAI_ROUTE_POLICY,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderCallProvenance,
    ProviderRouteAttestation,
    canonical_request_sha256,
    provider_provenance_contract,
)

_ENDPOINT = f"{APPROVED_OPENAI_ORIGIN}{APPROVED_OPENAI_ENDPOINT_PATH}"
_ROUTE_SHA256 = hashlib.sha256(_ENDPOINT.encode()).hexdigest()


def test_canonical_request_hash_is_order_stable_and_excludes_authorization() -> None:
    first = {"model": "gpt-5", "messages": [{"role": "user", "content": "question"}]}
    second = {"messages": first["messages"], "model": "gpt-5"}

    first_hash = canonical_request_sha256(
        endpoint_path=APPROVED_OPENAI_ENDPOINT_PATH,
        payload=first,
    )
    second_hash = canonical_request_sha256(
        endpoint_path=APPROVED_OPENAI_ENDPOINT_PATH,
        payload=second,
    )

    assert first_hash == second_hash
    assert len(first_hash) == 64
    assert "authorization" not in json.dumps(first)


def test_provider_call_redacts_sensitive_value_before_identifier_whitelist() -> None:
    secret = "sk-proj-super-secret-provider-value"
    payload = ProviderCallProvenance(
        route=_route(),
        requested_model=secret,
        observed_model=secret,
        response_id=secret,
        system_fingerprint=secret,
        request_sha256="a" * 64,
    ).public_payload()

    rendered = json.dumps(payload)
    assert secret not in rendered
    for field in (
        "requested_model",
        "observed_model",
        "response_id",
        "system_fingerprint",
    ):
        assert payload[field] == "[redacted]"
        assert payload[f"{field}_sha256"] == hashlib.sha256(secret.encode()).hexdigest()


def test_provider_call_redacts_malformed_provider_identifiers() -> None:
    private_value = "provider response private body with spaces"
    payload = ProviderCallProvenance(
        route=_route(),
        requested_model="gpt-5",
        observed_model=private_value,
        response_id=private_value,
        system_fingerprint=private_value,
        request_sha256="not-a-hash",
    ).public_payload()

    rendered = json.dumps(payload)
    assert private_value not in rendered
    assert payload["observed_model"] == "[redacted]"
    assert payload["response_id"] == "[redacted]"
    assert payload["system_fingerprint"] == "[redacted]"
    assert payload["request_sha256"] == "[invalid]"


def test_contract_never_aggregates_raw_sensitive_mapping_values() -> None:
    secret = "sk-proj-contract-aggregate-secret"
    evaluation = _evaluation()
    for stage in ("generation", "judgment"):
        raw = evaluation[stage]["metadata"]["provider_provenance"]
        for field in (
            "trust",
            "requested_model",
            "observed_model",
            "response_id",
            "system_fingerprint",
        ):
            raw[field] = secret

    contract = _contract(evaluation)

    assert contract["matches"] is False
    assert secret not in json.dumps(contract)
    assert contract["trust_counts"] == {"rejected": 2}
    assert contract["observed_models"] == {"[rejected]": 2}
    assert contract["system_fingerprints"] == {"[rejected]": 2}


def test_contract_rejects_extra_keys_without_echoing_values() -> None:
    secret = "Bearer private-token-should-reject"
    evaluation = _evaluation()
    evaluation["generation"]["metadata"]["provider_provenance"][
        "authorization"
    ] = secret
    evaluation["judgment"]["metadata"]["provider_provenance"]["route"] = {
        "authorization": secret
    }

    contract = _contract(evaluation)

    assert contract["matches"] is False
    assert contract["issues"]["answerer_payload"] == 1
    assert contract["issues"]["judge_payload"] == 1
    assert secret not in json.dumps(contract)
    assert "authorization" not in json.dumps(contract).casefold()


@pytest.mark.parametrize(
    "field",
    (
        "schema_version",
        "trust",
        "origin",
        "endpoint_path",
        "route_sha256",
        "transport_evidence",
        "credential_binding_id",
        "request_method",
        "requested_model",
        "observed_model",
        "response_id",
        "system_fingerprint",
        "request_sha256",
    ),
)
def test_contract_never_echoes_ordinary_private_string_fields(field: str) -> None:
    secret = "opaque-private-canary-82f4"
    evaluation = _evaluation()
    evaluation["generation"]["metadata"]["provider_provenance"][field] = secret

    contract = _contract(evaluation)

    assert contract["matches"] is False
    assert secret not in json.dumps(contract)


@pytest.mark.parametrize(
    ("stage", "field", "value", "issue"),
    (
        ("generation", "trust", "diagnostic_untrusted", "answerer_route"),
        (
            "generation",
            "transport_evidence",
            "injected-diagnostic-transport",
            "answerer_route",
        ),
        ("generation", "requested_model", "gpt-4.1", "answerer_requested_model"),
        ("judgment", "observed_model", "gpt-4.1", "judge_observed_model"),
        ("generation", "response_id", "fake-id", "answerer_response_id_shape"),
        (
            "judgment",
            "system_fingerprint",
            "fp_test",
            "judge_system_fingerprint_shape",
        ),
        ("generation", "request_sha256", "invalid", "answerer_request_sha256"),
        ("judgment", "response_status", 500, "judge_response_status"),
    ),
)
def test_publishable_contract_rejects_untrusted_call_fields(
    stage: str,
    field: str,
    value: object,
    issue: str,
) -> None:
    evaluation = _evaluation()
    evaluation[stage]["metadata"]["provider_provenance"][field] = value

    contract = _contract(evaluation)

    assert contract["matches"] is False
    assert contract["issues"][issue] == 1


def test_publishable_contract_accepts_complete_official_pair() -> None:
    contract = _contract(_evaluation())

    assert contract["matches"] is True
    assert contract["observed_call_count"] == 2
    assert contract["credential_binding_count"] == 1
    assert contract["route_policy_id"] == "official-openai-chat-completions.v1"


def test_publishable_contract_requires_unique_ids_and_one_shared_binding() -> None:
    duplicate = _evaluation()
    duplicate["judgment"]["metadata"]["provider_provenance"][
        "response_id"
    ] = "chatcmpl-answer123"
    duplicate["judgment"]["metadata"]["provider_provenance"][
        "credential_binding_id"
    ] = f"sha256:{'b' * 64}"

    contract = _contract(duplicate)

    assert contract["matches"] is False
    assert contract["duplicate_response_id_count"] == 1
    assert contract["credential_binding_count"] == 2


def test_empty_contract_is_not_publishable_and_blank_model_is_rejected() -> None:
    empty = provider_provenance_contract(
        (),
        required_model="gpt-5",
        route_policy=OFFICIAL_OPENAI_ROUTE_POLICY,
    )
    assert empty["matches"] is False
    with pytest.raises(ValueError, match="requires a model"):
        provider_provenance_contract(
            (),
            required_model="",
            route_policy=OFFICIAL_OPENAI_ROUTE_POLICY,
        )


def _contract(evaluation: dict[str, object]) -> dict[str, object]:
    return provider_provenance_contract(
        (evaluation,),
        required_model="gpt-5",
        route_policy=OFFICIAL_OPENAI_ROUTE_POLICY,
    )


def _evaluation() -> dict[str, object]:
    return {
        "generation": {
            "metadata": {"provider_provenance": _call("chatcmpl-answer123")}
        },
        "judgment": {
            "metadata": {"provider_provenance": _call("chatcmpl-judge1234")}
        },
    }


def _call(response_id: str) -> dict[str, object]:
    return {
        "schema_version": "memory-comparison-provider-call.v1",
        "trust": "official_openai",
        "origin": APPROVED_OPENAI_ORIGIN,
        "endpoint_path": APPROVED_OPENAI_ENDPOINT_PATH,
        "route_sha256": _ROUTE_SHA256,
        "transport_evidence": "httpx-direct-tls-no-env-v1",
        "credential_bound": True,
        "credential_binding_id": f"sha256:{'a' * 64}",
        "request_method": "POST",
        "response_status": 200,
        "requested_model": "gpt-5",
        "observed_model": "gpt-5",
        "response_id": response_id,
        "system_fingerprint": "fp_abcdef1234",
        "request_sha256": "a" * 64,
    }


def _route() -> ProviderRouteAttestation:
    return ProviderRouteAttestation(
        trust="official_openai",
        origin=APPROVED_OPENAI_ORIGIN,
        endpoint_path=APPROVED_OPENAI_ENDPOINT_PATH,
        route_sha256=_ROUTE_SHA256,
        transport_evidence="httpx-direct-tls-no-env-v1",
        credential_binding_id=f"sha256:{'a' * 64}",
        response_status=200,
    )
