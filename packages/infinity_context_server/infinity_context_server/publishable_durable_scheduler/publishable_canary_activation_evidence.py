"""Authenticated activation evidence for the exact one-case publishable canary.

This receipt is deliberately not a publication receipt.  Its schema, receipt
commitment domain, and HMAC domain are independent from the 2,040-case receipt,
and every valid state keeps all publication/admission verdicts fail closed.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from pathlib import Path
from typing import final

from infinity_context_server.features.subscription_runtime_bridge.process_files import (
    read_private_json,
    write_private_json_once,
    write_private_json_replace,
)
from infinity_context_server.publishable_durable_scheduler.contracts import canonical_json

PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_SCHEMA_VERSION = (
    "memory-comparison-publishable-one-case-canary-activation-evidence.v1"
)
PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_RECEIPT_DOMAIN = (
    "memory-comparison/publishable-one-case-canary/activation-evidence/receipt-sha256/v1"
)
PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_HMAC_DOMAIN = (
    "memory-comparison/publishable-one-case-canary/activation-evidence/hmac-sha256/v1"
)
PUBLISHABLE_CANARY_CALL_SCOPE_DOMAIN = (
    "memory-comparison/publishable-one-case-canary/call-scope/sha256/v1"
)
PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT = 4
PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_BYTES_LIMIT = 32 * 1024

_PREPARED = "prepared"
_COMPLETE = "complete"
_REVIEW_REQUIRED = "review_required"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")

_BINDING_KEYS = frozenset(
    {
        "canary_authority_sha256",
        "canary_composition_authority_sha256",
        "canary_methodology_sha256",
        "canary_profile_sha256",
        "extraction_suite_readback_sha256",
        "fleet_authority_sha256",
        "input_authority_sha256",
        "official_case_authority_root_sha256",
        "paired_path_authority_sha256",
        "retrieval_authority_root_sha256",
        "run_authority_sha256",
        "runtime_provenance_sha256",
        "selected_case_authority_sha256",
        "selected_extraction_authority_sha256",
        "suite_authority_sha256",
        "target_publishable_methodology_sha256",
        "target_publishable_profile_sha256",
    }
)
_BODY_KEYS = frozenset(
    {
        "activation_evidence",
        "activation_state",
        "authentication_key_id",
        "bindings",
        "call_scope_sha256",
        "expected_provider_call_count",
        "full_profile_admission",
        "full_receipt_eligible",
        "measured_provider_call_count",
        "measured_provider_intent_count",
        "measured_provider_result_count",
        "ordered_logical_call_ids",
        "ordered_provider_receipt_sha256",
        "paired_outcome_evidence_sha256",
        "provider_accounting_complete",
        "publishable",
        "schema_version",
    }
)
_PAYLOAD_KEYS = _BODY_KEYS | {"authentication_hmac_sha256", "receipt_sha256"}


class PublishableCanaryActivationEvidenceError(RuntimeError):
    """Stable, secret-free rejection from the canary evidence boundary."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"PublishableCanaryActivationEvidenceError({self.code!r})"


@final
@dataclass(frozen=True, slots=True)
class CanaryActivationEvidenceBindings:
    """Immutable authority graph that the canary observation is allowed to attest."""

    canary_authority_sha256: str
    canary_profile_sha256: str
    canary_methodology_sha256: str
    target_publishable_profile_sha256: str
    target_publishable_methodology_sha256: str
    suite_authority_sha256: str
    run_authority_sha256: str
    selected_case_authority_sha256: str
    official_case_authority_root_sha256: str
    retrieval_authority_root_sha256: str
    input_authority_sha256: str
    extraction_suite_readback_sha256: str
    selected_extraction_authority_sha256: str
    runtime_provenance_sha256: str
    fleet_authority_sha256: str
    canary_composition_authority_sha256: str
    paired_path_authority_sha256: str

    def __post_init__(self) -> None:
        if any(not _is_sha256(value) for value in self.material().values()):
            _fail("publishable_canary_activation_evidence_bindings_invalid")

    @classmethod
    def from_material(cls, value: object) -> CanaryActivationEvidenceBindings:
        if (
            type(value) is not dict
            or set(value) != _BINDING_KEYS
            or any(type(value[key]) is not str for key in _BINDING_KEYS)
        ):
            _payload_fail()
        try:
            return cls(**{key: value[key] for key in _BINDING_KEYS})
        except (PublishableCanaryActivationEvidenceError, TypeError, ValueError):
            _payload_fail()

    def material(self) -> dict[str, str]:
        return {
            "canary_authority_sha256": self.canary_authority_sha256,
            "canary_composition_authority_sha256": (
                self.canary_composition_authority_sha256
            ),
            "canary_methodology_sha256": self.canary_methodology_sha256,
            "canary_profile_sha256": self.canary_profile_sha256,
            "extraction_suite_readback_sha256": self.extraction_suite_readback_sha256,
            "fleet_authority_sha256": self.fleet_authority_sha256,
            "input_authority_sha256": self.input_authority_sha256,
            "official_case_authority_root_sha256": (
                self.official_case_authority_root_sha256
            ),
            "paired_path_authority_sha256": self.paired_path_authority_sha256,
            "retrieval_authority_root_sha256": self.retrieval_authority_root_sha256,
            "run_authority_sha256": self.run_authority_sha256,
            "runtime_provenance_sha256": self.runtime_provenance_sha256,
            "selected_case_authority_sha256": self.selected_case_authority_sha256,
            "selected_extraction_authority_sha256": (
                self.selected_extraction_authority_sha256
            ),
            "suite_authority_sha256": self.suite_authority_sha256,
            "target_publishable_methodology_sha256": (
                self.target_publishable_methodology_sha256
            ),
            "target_publishable_profile_sha256": self.target_publishable_profile_sha256,
        }


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableCanaryActivationEvidence:
    """Authenticated prepared checkpoint or terminal activation evidence."""

    bindings: CanaryActivationEvidenceBindings
    activation_state: str
    ordered_logical_call_ids: tuple[str, str, str, str]
    ordered_provider_receipt_sha256: tuple[str, ...]
    call_scope_sha256: str
    measured_provider_intent_count: int
    measured_provider_result_count: int
    measured_provider_call_count: int
    provider_accounting_complete: bool
    paired_outcome_evidence_sha256: str | None
    activation_evidence: bool
    publishable: bool
    full_receipt_eligible: bool
    full_profile_admission: str
    authentication_key_id: str
    receipt_sha256: str
    authentication_hmac_sha256: str
    expected_provider_call_count: int = PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
    schema_version: str = PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.bindings) is not CanaryActivationEvidenceBindings
            or type(self.ordered_logical_call_ids) is not tuple
            or type(self.ordered_provider_receipt_sha256) is not tuple
        ):
            _fail("publishable_canary_activation_evidence_invalid")
        try:
            CanaryActivationEvidenceBindings.__post_init__(self.bindings)
        except Exception:
            _fail("publishable_canary_activation_evidence_invalid")
        body = self._body()
        _validate_body(body)
        if (
            not _is_sha256(self.receipt_sha256)
            or not _is_sha256(self.authentication_hmac_sha256)
            or not hmac.compare_digest(self.receipt_sha256, _receipt_sha256(body))
        ):
            _fail("publishable_canary_activation_evidence_commitment_invalid")

    @classmethod
    def from_payload(cls, value: object) -> PublishableCanaryActivationEvidence:
        """Decode only the exact JSON-compatible canary evidence shape."""

        if type(value) is not dict or set(value) != _PAYLOAD_KEYS:
            _payload_fail()
        logical_ids = value["ordered_logical_call_ids"]
        receipt_hashes = value["ordered_provider_receipt_sha256"]
        string_fields = (
            "activation_state",
            "authentication_hmac_sha256",
            "authentication_key_id",
            "call_scope_sha256",
            "full_profile_admission",
            "receipt_sha256",
            "schema_version",
        )
        count_fields = (
            "expected_provider_call_count",
            "measured_provider_call_count",
            "measured_provider_intent_count",
            "measured_provider_result_count",
        )
        boolean_fields = (
            "activation_evidence",
            "full_receipt_eligible",
            "provider_accounting_complete",
            "publishable",
        )
        if (
            type(logical_ids) is not list
            or any(type(item) is not str for item in logical_ids)
            or type(receipt_hashes) is not list
            or any(type(item) is not str for item in receipt_hashes)
            or any(type(value[name]) is not str for name in string_fields)
            or any(type(value[name]) is not int for name in count_fields)
            or any(type(value[name]) is not bool for name in boolean_fields)
            or type(value["bindings"]) is not dict
            or value["paired_outcome_evidence_sha256"] is not None
            and type(value["paired_outcome_evidence_sha256"]) is not str
        ):
            _payload_fail()
        try:
            return cls(
                bindings=CanaryActivationEvidenceBindings.from_material(value["bindings"]),
                activation_state=value["activation_state"],
                ordered_logical_call_ids=tuple(logical_ids),  # type: ignore[arg-type]
                ordered_provider_receipt_sha256=tuple(receipt_hashes),
                call_scope_sha256=value["call_scope_sha256"],
                measured_provider_intent_count=value["measured_provider_intent_count"],
                measured_provider_result_count=value["measured_provider_result_count"],
                measured_provider_call_count=value["measured_provider_call_count"],
                provider_accounting_complete=value["provider_accounting_complete"],
                paired_outcome_evidence_sha256=value["paired_outcome_evidence_sha256"],
                activation_evidence=value["activation_evidence"],
                publishable=value["publishable"],
                full_receipt_eligible=value["full_receipt_eligible"],
                full_profile_admission=value["full_profile_admission"],
                authentication_key_id=value["authentication_key_id"],
                receipt_sha256=value["receipt_sha256"],
                authentication_hmac_sha256=value["authentication_hmac_sha256"],
                expected_provider_call_count=value["expected_provider_call_count"],
                schema_version=value["schema_version"],
            )
        except (PublishableCanaryActivationEvidenceError, TypeError, ValueError):
            _payload_fail()

    def payload(self) -> dict[str, object]:
        """Return the complete secret-free evidence payload."""

        return {
            **self._body(),
            "authentication_hmac_sha256": self.authentication_hmac_sha256,
            "receipt_sha256": self.receipt_sha256,
        }

    def _body(self) -> dict[str, object]:
        return _body(
            bindings=self.bindings,
            activation_state=self.activation_state,
            ordered_logical_call_ids=self.ordered_logical_call_ids,
            ordered_provider_receipt_sha256=self.ordered_provider_receipt_sha256,
            call_scope_sha256=self.call_scope_sha256,
            measured_provider_intent_count=self.measured_provider_intent_count,
            measured_provider_result_count=self.measured_provider_result_count,
            measured_provider_call_count=self.measured_provider_call_count,
            provider_accounting_complete=self.provider_accounting_complete,
            paired_outcome_evidence_sha256=self.paired_outcome_evidence_sha256,
            activation_evidence=self.activation_evidence,
            publishable=self.publishable,
            full_receipt_eligible=self.full_receipt_eligible,
            full_profile_admission=self.full_profile_admission,
            authentication_key_id=self.authentication_key_id,
            expected_provider_call_count=self.expected_provider_call_count,
            schema_version=self.schema_version,
        )

    def __repr__(self) -> str:
        return (
            "PublishableCanaryActivationEvidence("
            f"activation_state={self.activation_state!r}, "
            f"activation_evidence={self.activation_evidence!r}, "
            f"publishable={self.publishable!r}, "
            f"receipt_sha256={self.receipt_sha256!r}, authentication=<redacted>)"
        )


def build_prepared_canary_activation_evidence(
    *,
    bindings: CanaryActivationEvidenceBindings,
    ordered_logical_call_ids: tuple[str, str, str, str],
    authentication_key_id: str,
    authentication_secret: bytes,
) -> PublishableCanaryActivationEvidence:
    """Create the authenticated zero-call checkpoint required before dispatch."""

    return _build(
        bindings=bindings,
        activation_state=_PREPARED,
        ordered_logical_call_ids=ordered_logical_call_ids,
        ordered_provider_receipt_sha256=(),
        measured_provider_intent_count=0,
        measured_provider_result_count=0,
        measured_provider_call_count=0,
        paired_outcome_evidence_sha256=None,
        authentication_key_id=authentication_key_id,
        authentication_secret=authentication_secret,
    )


def build_complete_canary_activation_evidence(
    *,
    bindings: CanaryActivationEvidenceBindings,
    ordered_logical_call_ids: tuple[str, str, str, str],
    ordered_provider_receipt_sha256: tuple[str, str, str, str],
    paired_outcome_evidence_sha256: str,
    measured_provider_intent_count: int,
    measured_provider_result_count: int,
    measured_provider_call_count: int,
    authentication_key_id: str,
    authentication_secret: bytes,
) -> PublishableCanaryActivationEvidence:
    """Create terminal activation evidence only from four measured provider calls."""

    return _build(
        bindings=bindings,
        activation_state=_COMPLETE,
        ordered_logical_call_ids=ordered_logical_call_ids,
        ordered_provider_receipt_sha256=ordered_provider_receipt_sha256,
        measured_provider_intent_count=measured_provider_intent_count,
        measured_provider_result_count=measured_provider_result_count,
        measured_provider_call_count=measured_provider_call_count,
        paired_outcome_evidence_sha256=paired_outcome_evidence_sha256,
        authentication_key_id=authentication_key_id,
        authentication_secret=authentication_secret,
    )


def verify_publishable_canary_activation_evidence(
    evidence: PublishableCanaryActivationEvidence,
    *,
    authentication_secret: bytes,
    expected_authentication_key_id: str | None = None,
) -> bool:
    """Return true only for an exact receipt commitment authenticated by the HMAC key."""

    try:
        _require_secret(authentication_secret)
        if type(evidence) is not PublishableCanaryActivationEvidence:
            return False
        PublishableCanaryActivationEvidence.__post_init__(evidence)
        if expected_authentication_key_id is not None and (
            not _is_identifier(expected_authentication_key_id)
            or not hmac.compare_digest(
                evidence.authentication_key_id,
                expected_authentication_key_id,
            )
        ):
            return False
        expected = _authentication_hmac(authentication_secret, evidence._body())
        return hmac.compare_digest(expected, evidence.authentication_hmac_sha256)
    except Exception:
        return False


def serialize_publishable_canary_activation_evidence(
    evidence: PublishableCanaryActivationEvidence,
) -> bytes:
    """Serialize one exact canonical JSON payload."""

    if type(evidence) is not PublishableCanaryActivationEvidence:
        _fail("publishable_canary_activation_evidence_serialize_invalid")
    try:
        PublishableCanaryActivationEvidence.__post_init__(evidence)
        raw = canonical_json(evidence.payload())
    except Exception:
        _fail("publishable_canary_activation_evidence_serialize_invalid")
    if not raw or len(raw) > PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_BYTES_LIMIT:
        _fail("publishable_canary_activation_evidence_serialize_invalid")
    return raw


def parse_publishable_canary_activation_evidence(
    raw: bytes,
) -> PublishableCanaryActivationEvidence:
    """Parse only bounded, canonical bytes for this canary schema."""

    if type(raw) is not bytes or not raw or (
        len(raw) > PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_BYTES_LIMIT
    ):
        _fail("publishable_canary_activation_evidence_parse_invalid")
    try:
        import json

        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        if type(value) is not dict or canonical_json(value) != raw:
            _fail("publishable_canary_activation_evidence_parse_invalid")
        return PublishableCanaryActivationEvidence.from_payload(value)
    except PublishableCanaryActivationEvidenceError:
        raise
    except Exception:
        _fail("publishable_canary_activation_evidence_parse_invalid")


def read_publishable_canary_activation_evidence(
    path: Path,
    *,
    authentication_secret: bytes,
    expected_authentication_key_id: str,
) -> PublishableCanaryActivationEvidence:
    """Read and authenticate one private canary evidence file."""

    if not isinstance(path, Path):
        _fail("publishable_canary_activation_evidence_read_invalid")
    try:
        payload = read_private_json(
            path,
            maximum_bytes=PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_BYTES_LIMIT,
        )
        evidence = PublishableCanaryActivationEvidence.from_payload(payload)
    except Exception:
        _fail("publishable_canary_activation_evidence_read_invalid")
    if not verify_publishable_canary_activation_evidence(
        evidence,
        authentication_secret=authentication_secret,
        expected_authentication_key_id=expected_authentication_key_id,
    ):
        _fail("publishable_canary_activation_evidence_authentication_invalid")
    return evidence


def write_publishable_canary_activation_evidence(
    path: Path,
    evidence: PublishableCanaryActivationEvidence,
    *,
    authentication_secret: bytes,
    expected_authentication_key_id: str,
) -> PublishableCanaryActivationEvidence:
    """Persist prepared -> complete exactly, with terminal replay byte-for-byte."""

    if not isinstance(path, Path) or not verify_publishable_canary_activation_evidence(
        evidence,
        authentication_secret=authentication_secret,
        expected_authentication_key_id=expected_authentication_key_id,
    ):
        _fail("publishable_canary_activation_evidence_write_invalid")
    payload = evidence.payload()
    try:
        if not path.exists():
            if evidence.activation_state != _PREPARED:
                _fail("publishable_canary_activation_evidence_prepared_required")
            write_private_json_once(
                path,
                payload,
                maximum_bytes=PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_BYTES_LIMIT,
            )
        else:
            prior = read_publishable_canary_activation_evidence(
                path,
                authentication_secret=authentication_secret,
                expected_authentication_key_id=expected_authentication_key_id,
            )
            if prior.activation_state == _COMPLETE:
                if prior != evidence or prior.payload() != payload:
                    _fail("publishable_canary_activation_evidence_terminal_divergent")
                return prior
            if evidence.activation_state == _PREPARED:
                if prior != evidence or prior.payload() != payload:
                    _fail("publishable_canary_activation_evidence_prepared_divergent")
                return prior
            _require_same_immutable_binding(prior, evidence)
            write_private_json_replace(
                path,
                payload,
                maximum_bytes=PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_BYTES_LIMIT,
            )
        readback = read_publishable_canary_activation_evidence(
            path,
            authentication_secret=authentication_secret,
            expected_authentication_key_id=expected_authentication_key_id,
        )
    except PublishableCanaryActivationEvidenceError:
        raise
    except Exception:
        _fail("publishable_canary_activation_evidence_write_invalid")
    if readback != evidence or readback.payload() != payload:
        _fail("publishable_canary_activation_evidence_readback_invalid")
    return readback


def _build(
    *,
    bindings: CanaryActivationEvidenceBindings,
    activation_state: str,
    ordered_logical_call_ids: tuple[str, str, str, str],
    ordered_provider_receipt_sha256: tuple[str, ...],
    measured_provider_intent_count: int,
    measured_provider_result_count: int,
    measured_provider_call_count: int,
    paired_outcome_evidence_sha256: str | None,
    authentication_key_id: str,
    authentication_secret: bytes,
) -> PublishableCanaryActivationEvidence:
    _require_secret(authentication_secret)
    call_scope_sha256 = _call_scope_sha256(bindings, ordered_logical_call_ids)
    complete = activation_state == _COMPLETE
    body = _body(
        bindings=bindings,
        activation_state=activation_state,
        ordered_logical_call_ids=ordered_logical_call_ids,
        ordered_provider_receipt_sha256=ordered_provider_receipt_sha256,
        call_scope_sha256=call_scope_sha256,
        measured_provider_intent_count=measured_provider_intent_count,
        measured_provider_result_count=measured_provider_result_count,
        measured_provider_call_count=measured_provider_call_count,
        provider_accounting_complete=complete,
        paired_outcome_evidence_sha256=paired_outcome_evidence_sha256,
        activation_evidence=complete,
        publishable=False,
        full_receipt_eligible=False,
        full_profile_admission=_REVIEW_REQUIRED,
        authentication_key_id=authentication_key_id,
    )
    _validate_body(body)
    receipt_sha256 = _receipt_sha256(body)
    return PublishableCanaryActivationEvidence(
        bindings=bindings,
        activation_state=activation_state,
        ordered_logical_call_ids=ordered_logical_call_ids,
        ordered_provider_receipt_sha256=ordered_provider_receipt_sha256,
        call_scope_sha256=call_scope_sha256,
        measured_provider_intent_count=measured_provider_intent_count,
        measured_provider_result_count=measured_provider_result_count,
        measured_provider_call_count=measured_provider_call_count,
        provider_accounting_complete=complete,
        paired_outcome_evidence_sha256=paired_outcome_evidence_sha256,
        activation_evidence=complete,
        publishable=False,
        full_receipt_eligible=False,
        full_profile_admission=_REVIEW_REQUIRED,
        authentication_key_id=authentication_key_id,
        receipt_sha256=receipt_sha256,
        authentication_hmac_sha256=_authentication_hmac(authentication_secret, body),
    )


def _body(
    *,
    bindings: object,
    activation_state: object,
    ordered_logical_call_ids: object,
    ordered_provider_receipt_sha256: object,
    call_scope_sha256: object,
    measured_provider_intent_count: object,
    measured_provider_result_count: object,
    measured_provider_call_count: object,
    provider_accounting_complete: object,
    paired_outcome_evidence_sha256: object,
    activation_evidence: object,
    publishable: object,
    full_receipt_eligible: object,
    full_profile_admission: object,
    authentication_key_id: object,
    expected_provider_call_count: object = PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT,
    schema_version: object = PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_SCHEMA_VERSION,
) -> dict[str, object]:
    return {
        "activation_evidence": activation_evidence,
        "activation_state": activation_state,
        "authentication_key_id": authentication_key_id,
        "bindings": bindings.material()
        if type(bindings) is CanaryActivationEvidenceBindings
        else bindings,
        "call_scope_sha256": call_scope_sha256,
        "expected_provider_call_count": expected_provider_call_count,
        "full_profile_admission": full_profile_admission,
        "full_receipt_eligible": full_receipt_eligible,
        "measured_provider_call_count": measured_provider_call_count,
        "measured_provider_intent_count": measured_provider_intent_count,
        "measured_provider_result_count": measured_provider_result_count,
        "ordered_logical_call_ids": list(ordered_logical_call_ids)
        if type(ordered_logical_call_ids) is tuple
        else ordered_logical_call_ids,
        "ordered_provider_receipt_sha256": list(ordered_provider_receipt_sha256)
        if type(ordered_provider_receipt_sha256) is tuple
        else ordered_provider_receipt_sha256,
        "paired_outcome_evidence_sha256": paired_outcome_evidence_sha256,
        "provider_accounting_complete": provider_accounting_complete,
        "publishable": publishable,
        "schema_version": schema_version,
    }


def _validate_body(body: dict[str, object]) -> None:
    try:
        bindings = CanaryActivationEvidenceBindings.from_material(body.get("bindings"))
    except Exception:
        _fail("publishable_canary_activation_evidence_invalid")
    logical_ids = body.get("ordered_logical_call_ids")
    receipt_hashes = body.get("ordered_provider_receipt_sha256")
    state = body.get("activation_state")
    measured_counts = (
        body.get("measured_provider_intent_count"),
        body.get("measured_provider_result_count"),
        body.get("measured_provider_call_count"),
    )
    if (
        set(body) != _BODY_KEYS
        or body.get("schema_version")
        != PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_SCHEMA_VERSION
        or body.get("expected_provider_call_count")
        != PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
        or type(body.get("expected_provider_call_count")) is not int
        or type(state) is not str
        or type(logical_ids) is not list
        or len(logical_ids) != PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
        or any(not _is_sha256(value) for value in logical_ids)
        or len(set(logical_ids)) != PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
        or type(receipt_hashes) is not list
        or any(not _is_sha256(value) for value in receipt_hashes)
        or len(set(receipt_hashes)) != len(receipt_hashes)
        or not _is_sha256(body.get("call_scope_sha256"))
        or not hmac.compare_digest(
            body["call_scope_sha256"],
            _call_scope_sha256(bindings, tuple(logical_ids)),
        )
        or any(type(value) is not int for value in measured_counts)
        or type(body.get("provider_accounting_complete")) is not bool
        or type(body.get("activation_evidence")) is not bool
        or body.get("publishable") is not False
        or body.get("full_receipt_eligible") is not False
        or type(body.get("full_profile_admission")) is not str
        or body.get("full_profile_admission") != _REVIEW_REQUIRED
        or body.get("paired_outcome_evidence_sha256") is not None
        and type(body.get("paired_outcome_evidence_sha256")) is not str
        or not _is_identifier(body.get("authentication_key_id"))
    ):
        _fail("publishable_canary_activation_evidence_invalid")
    if state == _PREPARED:
        valid_state = (
            measured_counts == (0, 0, 0)
            and receipt_hashes == []
            and body.get("paired_outcome_evidence_sha256") is None
            and body["provider_accounting_complete"] is False
            and body["activation_evidence"] is False
        )
    elif state == _COMPLETE:
        valid_state = (
            measured_counts
            == (PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT,) * 3
            and len(receipt_hashes) == PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
            and _is_sha256(body.get("paired_outcome_evidence_sha256"))
            and body["provider_accounting_complete"] is True
            and body["activation_evidence"] is True
        )
    else:
        valid_state = False
    if not valid_state:
        _fail("publishable_canary_activation_evidence_state_invalid")


def _call_scope_sha256(
    bindings: CanaryActivationEvidenceBindings,
    ordered_logical_call_ids: tuple[str, ...],
) -> str:
    if type(bindings) is not CanaryActivationEvidenceBindings:
        _fail("publishable_canary_activation_evidence_bindings_invalid")
    material = {
        "canary_authority_sha256": bindings.canary_authority_sha256,
        "expected_provider_call_count": PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT,
        "ordered_logical_call_ids": list(ordered_logical_call_ids),
        "run_authority_sha256": bindings.run_authority_sha256,
        "selected_case_authority_sha256": bindings.selected_case_authority_sha256,
    }
    message = _domain_message(PUBLISHABLE_CANARY_CALL_SCOPE_DOMAIN, material)
    return hashlib.sha256(message).hexdigest()


def _receipt_sha256(body: dict[str, object]) -> str:
    return hashlib.sha256(
        _domain_message(PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_RECEIPT_DOMAIN, body)
    ).hexdigest()


def _authentication_hmac(secret: bytes, body: dict[str, object]) -> str:
    return hmac.new(
        secret,
        _domain_message(PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_HMAC_DOMAIN, body),
        hashlib.sha256,
    ).hexdigest()


def _domain_message(domain: str, value: object) -> bytes:
    try:
        return domain.encode("ascii") + b"\0" + canonical_json(value)
    except Exception:
        _fail("publishable_canary_activation_evidence_invalid")


def _require_same_immutable_binding(
    prior: PublishableCanaryActivationEvidence,
    observed: PublishableCanaryActivationEvidence,
) -> None:
    prior_binding = (
        prior.bindings,
        prior.ordered_logical_call_ids,
        prior.call_scope_sha256,
        prior.expected_provider_call_count,
        prior.authentication_key_id,
        prior.schema_version,
    )
    observed_binding = (
        observed.bindings,
        observed.ordered_logical_call_ids,
        observed.call_scope_sha256,
        observed.expected_provider_call_count,
        observed.authentication_key_id,
        observed.schema_version,
    )
    if prior_binding != observed_binding:
        _fail("publishable_canary_activation_evidence_binding_divergent")


def _require_secret(value: object) -> bytes:
    if type(value) is not bytes or len(value) < 32:
        _fail("publishable_canary_activation_evidence_authentication_secret_invalid")
    return value


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _is_identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            _fail("publishable_canary_activation_evidence_parse_invalid")
        value[key] = item
    return value


def _reject_nonfinite(_value: str) -> None:
    _fail("publishable_canary_activation_evidence_parse_invalid")


def _payload_fail() -> None:
    _fail("publishable_canary_activation_evidence_payload_invalid")


def _fail(code: str) -> None:
    raise PublishableCanaryActivationEvidenceError(code) from None


__all__ = (
    "CanaryActivationEvidenceBindings",
    "PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_BYTES_LIMIT",
    "PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_HMAC_DOMAIN",
    "PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_RECEIPT_DOMAIN",
    "PUBLISHABLE_CANARY_ACTIVATION_EVIDENCE_SCHEMA_VERSION",
    "PUBLISHABLE_CANARY_CALL_SCOPE_DOMAIN",
    "PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT",
    "PublishableCanaryActivationEvidence",
    "PublishableCanaryActivationEvidenceError",
    "build_complete_canary_activation_evidence",
    "build_prepared_canary_activation_evidence",
    "parse_publishable_canary_activation_evidence",
    "read_publishable_canary_activation_evidence",
    "serialize_publishable_canary_activation_evidence",
    "verify_publishable_canary_activation_evidence",
    "write_publishable_canary_activation_evidence",
)
