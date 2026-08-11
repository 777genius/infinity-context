"""Direct security tests for one-case canary activation evidence."""

from __future__ import annotations

import hashlib
import hmac
import inspect
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from infinity_context_server.publishable_durable_scheduler import (
    publishable_canary_activation_evidence as canary_evidence,
)
from infinity_context_server.publishable_durable_scheduler.contracts import canonical_json
from infinity_context_server.publishable_durable_scheduler.publishable_run_attestation import (
    PublishableRunAttestation,
    PublishableRunAttestationError,
)

CanaryActivationEvidenceBindings = canary_evidence.CanaryActivationEvidenceBindings
PublishableCanaryActivationEvidence = canary_evidence.PublishableCanaryActivationEvidence
PublishableCanaryActivationEvidenceError = (
    canary_evidence.PublishableCanaryActivationEvidenceError
)
PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_HMAC_DOMAIN = (
    canary_evidence.PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_HMAC_DOMAIN
)
PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_RECEIPT_DOMAIN = (
    canary_evidence.PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_RECEIPT_DOMAIN
)
PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_SCHEMA_VERSION = (
    canary_evidence.PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_SCHEMA_VERSION
)
PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT = (
    canary_evidence.PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
)
build_complete_canary_activation_evidence = (
    canary_evidence.build_complete_canary_activation_evidence
)
build_prepared_canary_activation_evidence = (
    canary_evidence.build_prepared_canary_activation_evidence
)
parse_publishable_canary_activation_evidence = (
    canary_evidence.parse_publishable_canary_activation_evidence
)
read_publishable_canary_activation_evidence = (
    canary_evidence.read_publishable_canary_activation_evidence
)
serialize_publishable_canary_activation_evidence = (
    canary_evidence.serialize_publishable_canary_activation_evidence
)
verify_publishable_canary_activation_evidence = (
    canary_evidence.verify_publishable_canary_activation_evidence
)
write_publishable_canary_activation_evidence = (
    canary_evidence.write_publishable_canary_activation_evidence
)

_SECRET = b"one-case-canary-activation-key-v1-0001"
_OTHER_SECRET = b"one-case-canary-activation-key-v1-9999"
_KEY_ID = "one-case-canary-activation-key-v1"
_PRIVATE_TEXT = "private provider answer that must never enter evidence"


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _bindings(seed: str = "authority") -> CanaryActivationEvidenceBindings:
    return CanaryActivationEvidenceBindings(
        canary_authority_sha256=_sha(f"{seed}:canary-authority"),
        canary_profile_sha256=_sha(f"{seed}:canary-profile"),
        canary_methodology_sha256=_sha(f"{seed}:canary-methodology"),
        target_publishable_profile_sha256=_sha(f"{seed}:target-profile-v4"),
        target_publishable_methodology_sha256=_sha(f"{seed}:target-methodology-v4"),
        suite_authority_sha256=_sha(f"{seed}:suite"),
        run_authority_sha256=_sha(f"{seed}:run"),
        selected_case_authority_sha256=_sha(f"{seed}:case"),
        official_case_authority_root_sha256=_sha(f"{seed}:official-input-root"),
        retrieval_authority_root_sha256=_sha(f"{seed}:retrieval-root"),
        input_authority_sha256=_sha(f"{seed}:input-authority"),
        extraction_suite_readback_sha256=_sha(f"{seed}:extraction-suite"),
        selected_extraction_authority_sha256=_sha(f"{seed}:selected-extraction"),
        runtime_provenance_sha256=_sha(f"{seed}:runtime-provenance"),
        fleet_authority_sha256=_sha(f"{seed}:fleet"),
        canary_composition_authority_sha256=_sha(f"{seed}:composition"),
        paired_path_authority_sha256=_sha(f"{seed}:paired-path"),
    )


def _logical_ids(seed: str = "call") -> tuple[str, str, str, str]:
    return tuple(_sha(f"{seed}:{index}") for index in range(4))  # type: ignore[return-value]


def _receipt_hashes(seed: str = "receipt") -> tuple[str, str, str, str]:
    return tuple(_sha(f"{seed}:{index}") for index in range(4))  # type: ignore[return-value]


def _prepared(
    *,
    bindings: CanaryActivationEvidenceBindings | None = None,
    logical_ids: tuple[str, str, str, str] | None = None,
    secret: bytes = _SECRET,
    key_id: str = _KEY_ID,
) -> PublishableCanaryActivationEvidence:
    return build_prepared_canary_activation_evidence(
        bindings=_bindings() if bindings is None else bindings,
        ordered_logical_call_ids=_logical_ids() if logical_ids is None else logical_ids,
        authentication_key_id=key_id,
        authentication_secret=secret,
    )


def _complete(
    *,
    bindings: CanaryActivationEvidenceBindings | None = None,
    logical_ids: tuple[str, str, str, str] | None = None,
    receipt_hashes: tuple[str, str, str, str] | None = None,
    intent_count: int = 4,
    result_count: int = 4,
    call_count: int = 4,
    pair_evidence: str | None = None,
    secret: bytes = _SECRET,
    key_id: str = _KEY_ID,
) -> PublishableCanaryActivationEvidence:
    return build_complete_canary_activation_evidence(
        bindings=_bindings() if bindings is None else bindings,
        ordered_logical_call_ids=_logical_ids() if logical_ids is None else logical_ids,
        ordered_provider_receipt_sha256=(
            _receipt_hashes() if receipt_hashes is None else receipt_hashes
        ),
        paired_outcome_evidence_sha256=(
            _sha("paired-outcome") if pair_evidence is None else pair_evidence
        ),
        measured_provider_intent_count=intent_count,
        measured_provider_result_count=result_count,
        measured_provider_call_count=call_count,
        authentication_key_id=key_id,
        authentication_secret=secret,
    )


def _resign(payload: dict[str, object], *, secret: bytes = _SECRET) -> dict[str, object]:
    body = dict(payload)
    body.pop("authentication_hmac_sha256")
    body.pop("receipt_sha256")
    receipt_message = (
        PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_RECEIPT_DOMAIN.encode("ascii")
        + b"\0"
        + canonical_json(body)
    )
    authentication_message = (
        PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_HMAC_DOMAIN.encode("ascii")
        + b"\0"
        + canonical_json(body)
    )
    payload["receipt_sha256"] = hashlib.sha256(receipt_message).hexdigest()
    payload["authentication_hmac_sha256"] = hmac.new(
        secret,
        authentication_message,
        hashlib.sha256,
    ).hexdigest()
    return payload


def _private_root(tmp_path: Path) -> Path:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


def test_prepared_state_is_authenticated_zero_call_non_admission_checkpoint() -> None:
    evidence = _prepared()

    assert evidence.activation_state == "prepared"
    assert evidence.expected_provider_call_count == 4
    assert (
        evidence.measured_provider_intent_count,
        evidence.measured_provider_result_count,
        evidence.measured_provider_call_count,
    ) == (0, 0, 0)
    assert len(evidence.ordered_logical_call_ids) == 4
    assert evidence.ordered_provider_receipt_sha256 == ()
    assert evidence.paired_outcome_evidence_sha256 is None
    assert evidence.provider_accounting_complete is False
    assert evidence.activation_evidence is False
    assert evidence.publishable is False
    assert evidence.full_receipt_eligible is False
    assert evidence.full_profile_admission == "review_required"
    assert verify_publishable_canary_activation_evidence(
        evidence,
        authentication_secret=_SECRET,
        expected_authentication_key_id=_KEY_ID,
    )


def test_complete_state_requires_and_authenticates_exact_four_call_measurements() -> None:
    evidence = _complete()

    assert evidence.activation_state == "complete"
    assert evidence.expected_provider_call_count == PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
    assert (
        evidence.measured_provider_intent_count,
        evidence.measured_provider_result_count,
        evidence.measured_provider_call_count,
    ) == (4, 4, 4)
    assert evidence.ordered_logical_call_ids == _logical_ids()
    assert evidence.ordered_provider_receipt_sha256 == _receipt_hashes()
    assert evidence.paired_outcome_evidence_sha256 == _sha("paired-outcome")
    assert evidence.provider_accounting_complete is True
    assert evidence.activation_evidence is True
    assert evidence.publishable is False
    assert evidence.full_receipt_eligible is False
    assert evidence.full_profile_admission == "review_required"
    assert "expected_provider_call_count" not in inspect.signature(
        build_complete_canary_activation_evidence
    ).parameters


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("intent_count", 3),
        ("intent_count", 5),
        ("intent_count", True),
        ("result_count", 3),
        ("result_count", 5),
        ("call_count", 3),
        ("call_count", 5),
    ],
)
def test_complete_builder_rejects_every_non_exact_measurement(
    field: str,
    value: int,
) -> None:
    with pytest.raises(PublishableCanaryActivationEvidenceError):
        _complete(**{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("logical_ids", (_sha("a"), _sha("b"), _sha("c"))),
        ("logical_ids", (_sha("same"),) * 4),
        ("receipt_hashes", (_sha("a"), _sha("b"), _sha("c"))),
        ("receipt_hashes", (_sha("same"),) * 4),
        ("pair_evidence", "not-a-digest"),
    ],
)
def test_complete_builder_rejects_incomplete_duplicate_or_malformed_scope(
    field: str,
    value: object,
) -> None:
    with pytest.raises(PublishableCanaryActivationEvidenceError):
        _complete(**{field: value})  # type: ignore[arg-type]


def test_canonical_round_trip_and_independent_domains_are_exact() -> None:
    evidence = _complete()
    raw = serialize_publishable_canary_activation_evidence(evidence)
    parsed = parse_publishable_canary_activation_evidence(raw)
    payload = evidence.payload()
    body = dict(payload)
    body.pop("receipt_sha256")
    body.pop("authentication_hmac_sha256")

    assert parsed == evidence
    assert raw == canonical_json(payload)
    assert payload["schema_version"] == PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_SCHEMA_VERSION
    receipt_message = (
        PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_RECEIPT_DOMAIN.encode("ascii")
        + b"\0"
        + canonical_json(body)
    )
    hmac_message = (
        PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_HMAC_DOMAIN.encode("ascii")
        + b"\0"
        + canonical_json(body)
    )
    assert hashlib.sha256(receipt_message).hexdigest() == evidence.receipt_sha256
    assert (
        hmac.new(_SECRET, hmac_message, hashlib.sha256).hexdigest()
        == evidence.authentication_hmac_sha256
    )
    assert PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_RECEIPT_DOMAIN != (
        "memory-comparison/publishable-run-attestation/receipt-sha256/v1"
    )
    assert PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_HMAC_DOMAIN != (
        "memory-comparison/publishable-run-attestation/hmac-sha256/v1"
    )


def test_wrong_key_tamper_and_cross_wired_authentication_fail_closed() -> None:
    evidence = _complete()

    assert not verify_publishable_canary_activation_evidence(
        evidence,
        authentication_secret=_OTHER_SECRET,
        expected_authentication_key_id=_KEY_ID,
    )
    assert not verify_publishable_canary_activation_evidence(
        evidence,
        authentication_secret=_SECRET,
        expected_authentication_key_id="different-canary-key",
    )
    assert not verify_publishable_canary_activation_evidence(
        replace(evidence, authentication_hmac_sha256="0" * 64),
        authentication_secret=_SECRET,
    )
    with pytest.raises(PublishableCanaryActivationEvidenceError):
        replace(evidence, receipt_sha256="0" * 64)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("publishable", True),
        ("full_receipt_eligible", True),
        ("full_profile_admission", "admitted"),
        ("expected_provider_call_count", 5),
        ("activation_evidence", True),
        ("provider_accounting_complete", True),
        ("measured_provider_call_count", 1),
        ("ordered_provider_receipt_sha256", [_sha("unexpected-receipt")]),
        ("paired_outcome_evidence_sha256", _sha("unexpected-pair")),
        ("call_scope_sha256", _sha("divergent-scope")),
    ],
)
def test_even_resigned_prepared_payload_cannot_weaken_state_or_admission(
    field: str,
    value: object,
) -> None:
    payload = _prepared().payload()
    payload[field] = value
    _resign(payload)

    with pytest.raises(PublishableCanaryActivationEvidenceError):
        PublishableCanaryActivationEvidence.from_payload(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("activation_evidence", False),
        ("provider_accounting_complete", False),
        ("measured_provider_intent_count", 3),
        ("measured_provider_result_count", 3),
        ("measured_provider_call_count", 3),
        ("ordered_provider_receipt_sha256", list(_receipt_hashes()[:3])),
        ("ordered_provider_receipt_sha256", [_sha("duplicate")] * 4),
        ("paired_outcome_evidence_sha256", None),
        ("publishable", True),
        ("full_receipt_eligible", True),
        ("full_profile_admission", "admitted"),
    ],
)
def test_even_resigned_complete_payload_cannot_be_partial_or_publishable(
    field: str,
    value: object,
) -> None:
    payload = _complete().payload()
    payload[field] = value
    _resign(payload)

    with pytest.raises(PublishableCanaryActivationEvidenceError):
        PublishableCanaryActivationEvidence.from_payload(payload)


def test_schema_is_cross_parser_incompatible_with_full_publication_receipt() -> None:
    canary = _complete()
    with pytest.raises(PublishableRunAttestationError):
        PublishableRunAttestation.from_payload(canary.payload())

    full = PublishableRunAttestation.create(
        suite_authority_sha256=_sha("full-suite"),
        ordered_run_authority_sha256=(_sha("full-locomo"), _sha("full-longmemeval")),
        official_case_authority_root_sha256=_sha("full-case-root"),
        retrieval_authority_root_sha256=_sha("full-retrieval-root"),
        extraction_suite_readback_sha256=_sha("full-extraction"),
        production_composition_authority_sha256=_sha("full-composition"),
        suite_seal_sha256=None,
        terminal_disposition="failed_known",
        case_count=0,
        evaluation_call_count=0,
        extraction_operation_count=0,
        provider_intent_count=0,
        provider_result_count=0,
        provider_call_count=0,
        provider_accounting_complete=False,
        charged_tokens=None,
        paired_outcome=None,
        authentication_key_id="full-publication-key",
        authentication_secret=_SECRET,
    )
    with pytest.raises(PublishableCanaryActivationEvidenceError):
        parse_publishable_canary_activation_evidence(canonical_json(full.payload()))


def test_file_lifecycle_is_prepared_then_complete_and_terminal_replay_is_exact(
    tmp_path: Path,
) -> None:
    path = _private_root(tmp_path) / "activation-evidence.json"
    prepared = _prepared()
    complete = _complete()

    with pytest.raises(
        PublishableCanaryActivationEvidenceError,
        match="publishable_canary_activation_evidence_prepared_required",
    ):
        write_publishable_canary_activation_evidence(
            path,
            complete,
            authentication_secret=_SECRET,
            expected_authentication_key_id=_KEY_ID,
        )

    assert write_publishable_canary_activation_evidence(
        path,
        prepared,
        authentication_secret=_SECRET,
        expected_authentication_key_id=_KEY_ID,
    ) == prepared
    prepared_bytes = path.read_bytes()
    assert write_publishable_canary_activation_evidence(
        path,
        prepared,
        authentication_secret=_SECRET,
        expected_authentication_key_id=_KEY_ID,
    ) == prepared
    assert path.read_bytes() == prepared_bytes

    assert write_publishable_canary_activation_evidence(
        path,
        complete,
        authentication_secret=_SECRET,
        expected_authentication_key_id=_KEY_ID,
    ) == complete
    terminal_bytes = path.read_bytes()
    assert read_publishable_canary_activation_evidence(
        path,
        authentication_secret=_SECRET,
        expected_authentication_key_id=_KEY_ID,
    ) == complete
    assert write_publishable_canary_activation_evidence(
        path,
        complete,
        authentication_secret=_SECRET,
        expected_authentication_key_id=_KEY_ID,
    ) == complete
    assert path.read_bytes() == terminal_bytes

    with pytest.raises(
        PublishableCanaryActivationEvidenceError,
        match="publishable_canary_activation_evidence_terminal_divergent",
    ):
        write_publishable_canary_activation_evidence(
            path,
            prepared,
            authentication_secret=_SECRET,
            expected_authentication_key_id=_KEY_ID,
        )


def test_prepared_to_complete_cross_wire_fails_without_replacing_checkpoint(
    tmp_path: Path,
) -> None:
    path = _private_root(tmp_path) / "activation-evidence.json"
    prepared = _prepared()
    write_publishable_canary_activation_evidence(
        path,
        prepared,
        authentication_secret=_SECRET,
        expected_authentication_key_id=_KEY_ID,
    )
    checkpoint = path.read_bytes()
    divergent = _complete(bindings=_bindings("cross-wired"))

    with pytest.raises(
        PublishableCanaryActivationEvidenceError,
        match="publishable_canary_activation_evidence_binding_divergent",
    ):
        write_publishable_canary_activation_evidence(
            path,
            divergent,
            authentication_secret=_SECRET,
            expected_authentication_key_id=_KEY_ID,
        )
    assert path.read_bytes() == checkpoint


def test_missing_tampered_and_wrong_key_files_fail_closed(tmp_path: Path) -> None:
    path = _private_root(tmp_path) / "activation-evidence.json"
    with pytest.raises(
        PublishableCanaryActivationEvidenceError,
        match="publishable_canary_activation_evidence_read_invalid",
    ):
        read_publishable_canary_activation_evidence(
            path,
            authentication_secret=_SECRET,
            expected_authentication_key_id=_KEY_ID,
        )

    write_publishable_canary_activation_evidence(
        path,
        _prepared(),
        authentication_secret=_SECRET,
        expected_authentication_key_id=_KEY_ID,
    )
    with pytest.raises(
        PublishableCanaryActivationEvidenceError,
        match="publishable_canary_activation_evidence_authentication_invalid",
    ):
        read_publishable_canary_activation_evidence(
            path,
            authentication_secret=_OTHER_SECRET,
            expected_authentication_key_id=_KEY_ID,
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["bindings"]["suite_authority_sha256"] = _sha("tampered-suite")
    path.write_bytes(canonical_json(payload))
    path.chmod(0o600)
    with pytest.raises(
        PublishableCanaryActivationEvidenceError,
        match="publishable_canary_activation_evidence_read_invalid",
    ):
        read_publishable_canary_activation_evidence(
            path,
            authentication_secret=_SECRET,
            expected_authentication_key_id=_KEY_ID,
        )


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b'{"duplicate":1,"duplicate":2}',
        b'{ "noncanonical":true}',
        b"[]",
        b"not-json",
        b"",
    ],
)
def test_parser_rejects_missing_duplicate_noncanonical_or_non_object_bytes(raw: bytes) -> None:
    with pytest.raises(PublishableCanaryActivationEvidenceError):
        parse_publishable_canary_activation_evidence(raw)


def test_unknown_missing_wrong_types_and_mapping_subclasses_fail_closed() -> None:
    payload = _prepared().payload()
    payload["unknown"] = _PRIVATE_TEXT
    with pytest.raises(PublishableCanaryActivationEvidenceError):
        PublishableCanaryActivationEvidence.from_payload(payload)

    payload = _prepared().payload()
    payload.pop("bindings")
    with pytest.raises(PublishableCanaryActivationEvidenceError):
        PublishableCanaryActivationEvidence.from_payload(payload)

    payload = _prepared().payload()
    payload["measured_provider_call_count"] = False
    with pytest.raises(PublishableCanaryActivationEvidenceError):
        PublishableCanaryActivationEvidence.from_payload(payload)

    class PayloadSubclass(dict[str, object]):
        pass

    with pytest.raises(PublishableCanaryActivationEvidenceError):
        PublishableCanaryActivationEvidence.from_payload(
            PayloadSubclass(_prepared().payload())
        )


def test_evidence_is_frozen_and_never_exposes_secrets_or_private_output() -> None:
    evidence = _complete()
    payload_text = json.dumps(evidence.payload(), sort_keys=True)
    representation = repr(evidence)

    assert not hasattr(evidence, "authentication_secret")
    assert _SECRET.decode("ascii") not in payload_text
    assert _SECRET.decode("ascii") not in representation
    assert _PRIVATE_TEXT not in payload_text
    assert evidence.authentication_hmac_sha256 not in representation
    assert "authentication=<redacted>" in representation
    with pytest.raises(FrozenInstanceError):
        evidence.publishable = True  # type: ignore[misc]


@pytest.mark.parametrize("invalid_secret", [b"short", "x" * 32, bytearray(b"x" * 32)])
def test_invalid_secret_capabilities_are_rejected(invalid_secret: object) -> None:
    with pytest.raises(
        PublishableCanaryActivationEvidenceError,
        match="publishable_canary_activation_evidence_authentication_secret_invalid",
    ):
        _prepared(secret=invalid_secret)  # type: ignore[arg-type]
    assert not verify_publishable_canary_activation_evidence(
        _prepared(),
        authentication_secret=invalid_secret,  # type: ignore[arg-type]
    )
