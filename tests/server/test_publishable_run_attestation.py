"""Focused public-receipt tests for the outer publishable-run boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import FrozenInstanceError, replace

import pytest
from infinity_context_server.memory_comparison_paired_superiority_policy import (
    PAIRED_SUPERIORITY_POLICY_SHA256,
)
from infinity_context_server.publishable_durable_scheduler.contracts import canonical_json
from infinity_context_server.publishable_durable_scheduler.paired_outcome_contracts import (
    PAIRED_AUTHORITY_MAPPING_SHA256,
    PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256,
    PairedOutcomeSealBinding,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_attestation import (
    EXPECTED_CASE_COUNT,
    EXPECTED_EVALUATION_CALL_COUNT,
    EXPECTED_EXTRACTION_OPERATION_COUNT,
    EXPECTED_PROVIDER_CALL_COUNT,
    PUBLISHABLE_RUN_ATTESTATION_HMAC_DOMAIN,
    PUBLISHABLE_RUN_ATTESTATION_RECEIPT_DOMAIN,
    PUBLISHABLE_RUN_ATTESTATION_SCHEMA_VERSION,
    PublishableRunAttestation,
    PublishableRunAttestationError,
    verify_publishable_run_attestation,
)

_AUTHENTICATION_SECRET = b"publication-receipt-secret-v1-0123456789"
_WRONG_SECRET = b"publication-receipt-secret-v1-9876543210"
_PRIVATE_PATH = "/operator/private/runtime/provider-secrets.json"
_PRIVATE_TEXT = "private provider answer and operator-only diagnostic text"


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _paired_outcome(*, criterion_met: bool = True) -> PairedOutcomeSealBinding:
    return PairedOutcomeSealBinding(
        terminal_sha256=_sha("paired-terminal"),
        ordered_paired_outcomes_root_sha256=_sha("paired-outcomes-root"),
        pair_count=EXPECTED_CASE_COUNT,
        judge_normalization_policy_sha256=PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256,
        authority_mapping_sha256=PAIRED_AUTHORITY_MAPPING_SHA256,
        paired_superiority_policy_sha256=PAIRED_SUPERIORITY_POLICY_SHA256,
        policy_evidence_sha256=_sha("paired-policy-evidence"),
        policy_publication_bundle_sha256=_sha("paired-publication-bundle"),
        paired_superiority_metrics_sha256=_sha("paired-metrics"),
        paired_superiority_decision_sha256=_sha("paired-decision"),
        paired_superiority_criterion_met=criterion_met,
    )


def _exact_inputs(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "suite_authority_sha256": _sha("suite-authority"),
        "ordered_run_authority_sha256": (
            _sha("locomo-run-authority"),
            _sha("longmemeval-run-authority"),
        ),
        "official_case_authority_root_sha256": _sha(_PRIVATE_PATH),
        "retrieval_authority_root_sha256": _sha(_PRIVATE_TEXT),
        "extraction_suite_readback_sha256": _sha("extraction-suite-readback"),
        "production_composition_authority_sha256": _sha("production-composition"),
        "suite_seal_sha256": _sha("suite-seal"),
        "terminal_disposition": "sealed",
        "case_count": EXPECTED_CASE_COUNT,
        "evaluation_call_count": EXPECTED_EVALUATION_CALL_COUNT,
        "extraction_operation_count": EXPECTED_EXTRACTION_OPERATION_COUNT,
        "provider_intent_count": EXPECTED_PROVIDER_CALL_COUNT,
        "provider_result_count": EXPECTED_PROVIDER_CALL_COUNT,
        "provider_call_count": EXPECTED_PROVIDER_CALL_COUNT,
        "provider_accounting_complete": True,
        "charged_tokens": 123_456,
        "paired_outcome": _paired_outcome(),
        "authentication_key_id": "publication-key-v1",
        "authentication_secret": _AUTHENTICATION_SECRET,
    }
    values.update(overrides)
    return values


def _receipt(**overrides: object) -> PublishableRunAttestation:
    return PublishableRunAttestation.create(**_exact_inputs(**overrides))


def test_exact_terminal_evidence_issues_authenticated_publishable_receipt() -> None:
    receipt = _receipt()

    assert (
        EXPECTED_CASE_COUNT,
        EXPECTED_EVALUATION_CALL_COUNT,
        EXPECTED_EXTRACTION_OPERATION_COUNT,
        EXPECTED_PROVIDER_CALL_COUNT,
    ) == (2_040, 8_160, 130_226, 8_160)
    assert receipt.publishable is True
    assert (
        receipt.call_ledger.extraction_call_count,
        receipt.call_ledger.answer_judge_call_count,
        receipt.call_ledger.total_call_count,
    ) == (130_226, 8_160, 138_386)
    assert receipt.paired_outcome == _paired_outcome()
    assert receipt.ordered_run_authority_sha256 == (
        _sha("locomo-run-authority"),
        _sha("longmemeval-run-authority"),
    )
    assert verify_publishable_run_attestation(
        receipt,
        authentication_secret=_AUTHENTICATION_SECRET,
        expected_authentication_key_id="publication-key-v1",
    )
    assert len(receipt.receipt_sha256) == len(receipt.authentication_hmac_sha256) == 64


@pytest.mark.parametrize(
    ("field", "divergent_value"),
    [
        ("terminal_disposition", "failed_known"),
        ("case_count", EXPECTED_CASE_COUNT - 1),
        ("evaluation_call_count", EXPECTED_EVALUATION_CALL_COUNT - 1),
        ("extraction_operation_count", EXPECTED_EXTRACTION_OPERATION_COUNT - 1),
        ("provider_intent_count", EXPECTED_PROVIDER_CALL_COUNT - 1),
        ("provider_result_count", EXPECTED_PROVIDER_CALL_COUNT - 1),
        ("provider_call_count", EXPECTED_PROVIDER_CALL_COUNT - 1),
        ("provider_accounting_complete", False),
        ("suite_seal_sha256", None),
        ("paired_outcome", None),
        ("paired_outcome", _paired_outcome(criterion_met=False)),
    ],
)
def test_every_publication_gate_divergence_forces_false(
    field: str,
    divergent_value: object,
) -> None:
    receipt = _receipt(**{field: divergent_value})

    assert receipt.publishable is False
    assert verify_publishable_run_attestation(
        receipt,
        authentication_secret=_AUTHENTICATION_SECRET,
    )


@pytest.mark.parametrize("charged_tokens", [None, 0, 123_456])
def test_charged_tokens_are_optional_and_do_not_weaken_exact_gate(
    charged_tokens: int | None,
) -> None:
    receipt = _receipt(charged_tokens=charged_tokens)

    assert receipt.charged_tokens == charged_tokens
    assert receipt.publishable is True
    assert verify_publishable_run_attestation(
        receipt,
        authentication_secret=_AUTHENTICATION_SECRET,
    )


def test_wrong_key_hmac_tamper_and_body_tamper_fail_closed() -> None:
    receipt = _receipt()

    assert not verify_publishable_run_attestation(
        receipt,
        authentication_secret=_WRONG_SECRET,
    )
    assert not verify_publishable_run_attestation(
        receipt,
        authentication_secret=_AUTHENTICATION_SECRET,
        expected_authentication_key_id="different-publication-key",
    )
    tampered_hmac = replace(receipt, authentication_hmac_sha256="0" * 64)
    assert not verify_publishable_run_attestation(
        tampered_hmac,
        authentication_secret=_AUTHENTICATION_SECRET,
    )

    tampered_payload = receipt.payload()
    tampered_payload["provider_result_count"] = EXPECTED_PROVIDER_CALL_COUNT - 1
    with pytest.raises(
        PublishableRunAttestationError,
        match="publishable_run_attestation_payload_invalid",
    ):
        PublishableRunAttestation.from_payload(tampered_payload)

    tampered_commitment = receipt.payload()
    tampered_commitment["receipt_sha256"] = "0" * 64
    with pytest.raises(
        PublishableRunAttestationError,
        match="publishable_run_attestation_payload_invalid",
    ):
        PublishableRunAttestation.from_payload(tampered_commitment)


def test_domains_authenticate_the_independent_canonical_public_body() -> None:
    receipt = _receipt()
    body = receipt.payload()
    body.pop("receipt_sha256")
    body.pop("authentication_hmac_sha256")
    canonical = canonical_json(body)

    receipt_message = PUBLISHABLE_RUN_ATTESTATION_RECEIPT_DOMAIN.encode("ascii") + b"\0" + canonical
    authentication_message = (
        PUBLISHABLE_RUN_ATTESTATION_HMAC_DOMAIN.encode("ascii") + b"\0" + canonical
    )
    assert hashlib.sha256(receipt_message).hexdigest() == receipt.receipt_sha256
    assert (
        hmac.new(_AUTHENTICATION_SECRET, authentication_message, hashlib.sha256).hexdigest()
        == receipt.authentication_hmac_sha256
    )


@pytest.mark.parametrize(
    "invalid_secret",
    [b"short", "x" * 32, bytearray(b"x" * 32)],
)
def test_verifier_returns_false_for_invalid_secret_capabilities(
    invalid_secret: object,
) -> None:
    assert not verify_publishable_run_attestation(
        _receipt(),
        authentication_secret=invalid_secret,  # type: ignore[arg-type]
    )


def test_verifier_returns_false_for_non_receipt_objects() -> None:
    assert not verify_publishable_run_attestation(
        object(),  # type: ignore[arg-type]
        authentication_secret=_AUTHENTICATION_SECRET,
    )


def test_exact_payload_round_trip_is_json_safe_and_independently_verifiable() -> None:
    receipt = _receipt(charged_tokens=None)
    payload = receipt.payload()
    json_payload = json.loads(json.dumps(payload, sort_keys=True, separators=(",", ":")))

    parsed = PublishableRunAttestation.from_payload(json_payload)

    assert parsed == receipt
    assert parsed is not receipt
    assert parsed.payload() == payload
    assert payload["ordered_run_authority_sha256"] == list(receipt.ordered_run_authority_sha256)
    assert verify_publishable_run_attestation(
        parsed,
        authentication_secret=_AUTHENTICATION_SECRET,
    )


@pytest.mark.parametrize("mutation", ["unknown", "missing"])
def test_from_payload_rejects_unknown_and_missing_keys(mutation: str) -> None:
    payload = _receipt().payload()
    if mutation == "unknown":
        payload["unknown_private_field"] = _PRIVATE_TEXT
    else:
        payload.pop("charged_tokens")

    with pytest.raises(
        PublishableRunAttestationError,
        match="publishable_run_attestation_payload_invalid",
    ):
        PublishableRunAttestation.from_payload(payload)


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("ordered_run_authority_sha256", (_sha("run-0"), _sha("run-1"))),
        ("ordered_run_authority_sha256", [_sha("only-one-run")]),
        ("ordered_run_authority_sha256", [_sha("same-run"), _sha("same-run")]),
        ("case_count", True),
        ("evaluation_call_count", "8160"),
        ("provider_accounting_complete", 1),
        ("publishable", 1),
        ("suite_seal_sha256", 123),
        ("charged_tokens", False),
        ("authentication_key_id", b"publication-key-v1"),
        ("terminal_disposition", ["sealed"]),
        ("receipt_sha256", bytearray(64)),
    ],
)
def test_from_payload_rejects_wrong_exact_types_and_shapes(
    field: str,
    wrong_value: object,
) -> None:
    payload = _receipt().payload()
    payload[field] = wrong_value

    with pytest.raises(
        PublishableRunAttestationError,
        match="publishable_run_attestation_payload_invalid",
    ):
        PublishableRunAttestation.from_payload(payload)


def test_from_payload_rejects_mapping_subclasses() -> None:
    class PayloadSubclass(dict[str, object]):
        pass

    with pytest.raises(
        PublishableRunAttestationError,
        match="publishable_run_attestation_payload_invalid",
    ):
        PublishableRunAttestation.from_payload(PayloadSubclass(_receipt().payload()))


def test_secret_paths_and_private_text_never_enter_payload_repr_or_errors() -> None:
    receipt = _receipt()
    payload_text = json.dumps(receipt.payload(), sort_keys=True)
    representation = repr(receipt)
    private_values = (
        _AUTHENTICATION_SECRET.decode("ascii"),
        _PRIVATE_PATH,
        _PRIVATE_TEXT,
    )

    assert not hasattr(receipt, "authentication_secret")
    assert receipt.authentication_hmac_sha256 not in representation
    assert "authentication=<redacted>" in representation
    assert all(value not in payload_text for value in private_values)
    assert all(value not in representation for value in private_values)

    with pytest.raises(PublishableRunAttestationError) as captured:
        _receipt(terminal_disposition=_PRIVATE_PATH)
    assert captured.value.code == "publishable_run_attestation_invalid"
    assert all(value not in str(captured.value) for value in private_values)
    assert all(value not in repr(captured.value) for value in private_values)


def test_receipt_is_frozen_and_short_authentication_secrets_are_rejected() -> None:
    receipt = _receipt()
    payload_runs = receipt.payload()["ordered_run_authority_sha256"]
    assert type(receipt.ordered_run_authority_sha256) is tuple
    assert type(payload_runs) is list
    with pytest.raises(FrozenInstanceError):
        receipt.publishable = False  # type: ignore[misc]
    payload_runs.append(_sha("mutable-payload-copy"))
    assert len(receipt.ordered_run_authority_sha256) == 2

    with pytest.raises(
        PublishableRunAttestationError,
        match="publishable_run_attestation_invalid",
    ):
        _receipt(
            ordered_run_authority_sha256=[
                _sha("locomo-run-authority"),
                _sha("longmemeval-run-authority"),
            ]
        )

    with pytest.raises(
        PublishableRunAttestationError,
        match="publishable_run_attestation_authentication_secret_invalid",
    ):
        _receipt(authentication_secret=b"x" * 31)


def test_schema_and_exact_payload_keys_are_public_and_stable() -> None:
    payload = _receipt().payload()

    assert payload["schema_version"] == PUBLISHABLE_RUN_ATTESTATION_SCHEMA_VERSION
    assert set(payload) == {
        "authentication_hmac_sha256",
        "authentication_key_id",
        "call_ledger",
        "case_count",
        "charged_tokens",
        "evaluation_call_count",
        "extraction_operation_count",
        "extraction_suite_readback_sha256",
        "official_case_authority_root_sha256",
        "ordered_run_authority_sha256",
        "paired_outcome",
        "production_composition_authority_sha256",
        "provider_accounting_complete",
        "provider_call_count",
        "provider_intent_count",
        "provider_result_count",
        "publishable",
        "receipt_sha256",
        "retrieval_authority_root_sha256",
        "schema_version",
        "suite_authority_sha256",
        "suite_seal_sha256",
        "terminal_disposition",
    }
