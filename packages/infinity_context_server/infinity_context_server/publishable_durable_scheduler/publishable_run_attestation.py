"""Authenticated public receipt for one terminal publishable scheduler suite."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import final

from infinity_context_server.publishable_durable_scheduler.contracts import canonical_json
from infinity_context_server.publishable_durable_scheduler.paired_outcome_contracts import (
    PairedOutcomeSealBinding,
    paired_outcome_seal_binding_from_material,
)
from infinity_context_server.publishable_durable_scheduler.publishable_call_ledger import (
    PublishableCallLedger,
    exact_publishable_call_ledger,
    publishable_call_ledger_from_material,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    PUBLISHABLE_SUITE_CASE_COUNT,
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
    PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT,
)

PUBLISHABLE_RUN_ATTESTATION_SCHEMA_VERSION = "memory-comparison-publishable-run-attestation.v1"
PUBLISHABLE_RUN_ATTESTATION_RECEIPT_DOMAIN = (
    "memory-comparison/publishable-run-attestation/receipt-sha256/v1"
)
PUBLISHABLE_RUN_ATTESTATION_HMAC_DOMAIN = (
    "memory-comparison/publishable-run-attestation/hmac-sha256/v1"
)

EXPECTED_CASE_COUNT = PUBLISHABLE_SUITE_CASE_COUNT
EXPECTED_EVALUATION_CALL_COUNT = PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT
EXPECTED_EXTRACTION_OPERATION_COUNT = PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT
EXPECTED_PROVIDER_CALL_COUNT = PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_DISPOSITION = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_SEALED = "sealed"

_BODY_KEYS = frozenset(
    {
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
        "retrieval_authority_root_sha256",
        "schema_version",
        "suite_authority_sha256",
        "suite_seal_sha256",
        "terminal_disposition",
    }
)
_PAYLOAD_KEYS = _BODY_KEYS | {"authentication_hmac_sha256", "receipt_sha256"}


class PublishableRunAttestationError(RuntimeError):
    """Stable secret-free rejection of malformed or unauthenticated receipts."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"PublishableRunAttestationError({self.code!r})"


@final
@dataclass(frozen=True, slots=True, repr=False)
class PublishableRunAttestation:
    """Immutable, secret-free terminal receipt suitable for publication."""

    suite_authority_sha256: str
    ordered_run_authority_sha256: tuple[str, str]
    official_case_authority_root_sha256: str
    retrieval_authority_root_sha256: str
    extraction_suite_readback_sha256: str
    production_composition_authority_sha256: str
    suite_seal_sha256: str | None
    terminal_disposition: str
    case_count: int
    evaluation_call_count: int
    extraction_operation_count: int
    provider_intent_count: int
    provider_result_count: int
    provider_call_count: int
    provider_accounting_complete: bool
    charged_tokens: int | None
    publishable: bool
    authentication_key_id: str
    receipt_sha256: str
    authentication_hmac_sha256: str
    call_ledger: PublishableCallLedger
    paired_outcome: PairedOutcomeSealBinding | None
    schema_version: str = PUBLISHABLE_RUN_ATTESTATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.ordered_run_authority_sha256) is not tuple
            or type(self.call_ledger) is not PublishableCallLedger
            or self.paired_outcome is not None
            and type(self.paired_outcome) is not PairedOutcomeSealBinding
        ):
            _fail("publishable_run_attestation_invalid")
        try:
            PublishableCallLedger.__post_init__(self.call_ledger)
            if self.paired_outcome is not None:
                PairedOutcomeSealBinding.__post_init__(self.paired_outcome)
        except Exception:
            _fail("publishable_run_attestation_invalid")
        body = self._body()
        _validate_body(body)
        if (
            not _is_sha256(self.receipt_sha256)
            or not _is_sha256(self.authentication_hmac_sha256)
            or not hmac.compare_digest(self.receipt_sha256, _receipt_sha256(body))
        ):
            _fail("publishable_run_attestation_commitment_invalid")

    @classmethod
    def create(
        cls,
        *,
        suite_authority_sha256: str,
        ordered_run_authority_sha256: tuple[str, str],
        official_case_authority_root_sha256: str,
        retrieval_authority_root_sha256: str,
        extraction_suite_readback_sha256: str,
        production_composition_authority_sha256: str,
        suite_seal_sha256: str | None = None,
        terminal_disposition: str,
        case_count: int,
        evaluation_call_count: int,
        extraction_operation_count: int,
        provider_intent_count: int,
        provider_result_count: int,
        provider_call_count: int,
        provider_accounting_complete: bool,
        charged_tokens: int | None = None,
        call_ledger: PublishableCallLedger | None = None,
        paired_outcome: PairedOutcomeSealBinding | None = None,
        authentication_key_id: str,
        authentication_secret: bytes,
    ) -> PublishableRunAttestation:
        """Issue a receipt and derive its publication verdict from exact evidence."""

        _require_secret(authentication_secret)
        resolved_call_ledger = (
            exact_publishable_call_ledger() if call_ledger is None else call_ledger
        )
        body = _body(
            suite_authority_sha256=suite_authority_sha256,
            ordered_run_authority_sha256=ordered_run_authority_sha256,
            official_case_authority_root_sha256=official_case_authority_root_sha256,
            retrieval_authority_root_sha256=retrieval_authority_root_sha256,
            extraction_suite_readback_sha256=extraction_suite_readback_sha256,
            production_composition_authority_sha256=production_composition_authority_sha256,
            suite_seal_sha256=suite_seal_sha256,
            terminal_disposition=terminal_disposition,
            case_count=case_count,
            evaluation_call_count=evaluation_call_count,
            extraction_operation_count=extraction_operation_count,
            provider_intent_count=provider_intent_count,
            provider_result_count=provider_result_count,
            provider_call_count=provider_call_count,
            provider_accounting_complete=provider_accounting_complete,
            charged_tokens=charged_tokens,
            call_ledger=resolved_call_ledger,
            paired_outcome=paired_outcome,
            publishable=False,
            authentication_key_id=authentication_key_id,
        )
        _validate_body(body)
        body["publishable"] = _publication_gate(body)
        receipt_sha256 = _receipt_sha256(body)
        authentication_hmac_sha256 = _authentication_hmac(authentication_secret, body)
        return cls(
            suite_authority_sha256=suite_authority_sha256,
            ordered_run_authority_sha256=ordered_run_authority_sha256,
            official_case_authority_root_sha256=official_case_authority_root_sha256,
            retrieval_authority_root_sha256=retrieval_authority_root_sha256,
            extraction_suite_readback_sha256=extraction_suite_readback_sha256,
            production_composition_authority_sha256=production_composition_authority_sha256,
            suite_seal_sha256=suite_seal_sha256,
            terminal_disposition=terminal_disposition,
            case_count=case_count,
            evaluation_call_count=evaluation_call_count,
            extraction_operation_count=extraction_operation_count,
            provider_intent_count=provider_intent_count,
            provider_result_count=provider_result_count,
            provider_call_count=provider_call_count,
            provider_accounting_complete=provider_accounting_complete,
            charged_tokens=charged_tokens,
            publishable=bool(body["publishable"]),
            authentication_key_id=authentication_key_id,
            receipt_sha256=receipt_sha256,
            authentication_hmac_sha256=authentication_hmac_sha256,
            call_ledger=resolved_call_ledger,
            paired_outcome=paired_outcome,
        )

    @classmethod
    def from_payload(cls, value: object) -> PublishableRunAttestation:
        """Decode only the exact JSON-compatible public receipt shape."""

        if type(value) is not dict or set(value) != _PAYLOAD_KEYS:
            _payload_fail()
        ordered_runs = value["ordered_run_authority_sha256"]
        scalar_strings = (
            "authentication_hmac_sha256",
            "authentication_key_id",
            "extraction_suite_readback_sha256",
            "official_case_authority_root_sha256",
            "production_composition_authority_sha256",
            "receipt_sha256",
            "retrieval_authority_root_sha256",
            "schema_version",
            "suite_authority_sha256",
            "terminal_disposition",
        )
        count_fields = (
            "case_count",
            "evaluation_call_count",
            "extraction_operation_count",
            "provider_call_count",
            "provider_intent_count",
            "provider_result_count",
        )
        if (
            type(ordered_runs) is not list
            or len(ordered_runs) != 2
            or any(type(item) is not str for item in ordered_runs)
            or any(type(value[name]) is not str for name in scalar_strings)
            or any(type(value[name]) is not int for name in count_fields)
            or type(value["provider_accounting_complete"]) is not bool
            or type(value["publishable"]) is not bool
            or value["suite_seal_sha256"] is not None
            and type(value["suite_seal_sha256"]) is not str
            or value["charged_tokens"] is not None
            and type(value["charged_tokens"]) is not int
            or type(value["call_ledger"]) is not dict
            or value["paired_outcome"] is not None
            and type(value["paired_outcome"]) is not dict
        ):
            _payload_fail()
        try:
            call_ledger = publishable_call_ledger_from_material(value["call_ledger"])
            paired_outcome = (
                None
                if value["paired_outcome"] is None
                else paired_outcome_seal_binding_from_material(value["paired_outcome"])
            )
            return cls(
                suite_authority_sha256=value["suite_authority_sha256"],
                ordered_run_authority_sha256=(ordered_runs[0], ordered_runs[1]),
                official_case_authority_root_sha256=(value["official_case_authority_root_sha256"]),
                retrieval_authority_root_sha256=value["retrieval_authority_root_sha256"],
                extraction_suite_readback_sha256=value["extraction_suite_readback_sha256"],
                production_composition_authority_sha256=(
                    value["production_composition_authority_sha256"]
                ),
                suite_seal_sha256=value["suite_seal_sha256"],
                terminal_disposition=value["terminal_disposition"],
                case_count=value["case_count"],
                evaluation_call_count=value["evaluation_call_count"],
                extraction_operation_count=value["extraction_operation_count"],
                provider_intent_count=value["provider_intent_count"],
                provider_result_count=value["provider_result_count"],
                provider_call_count=value["provider_call_count"],
                provider_accounting_complete=value["provider_accounting_complete"],
                charged_tokens=value["charged_tokens"],
                publishable=value["publishable"],
                authentication_key_id=value["authentication_key_id"],
                receipt_sha256=value["receipt_sha256"],
                authentication_hmac_sha256=value["authentication_hmac_sha256"],
                call_ledger=call_ledger,
                paired_outcome=paired_outcome,
                schema_version=value["schema_version"],
            )
        except (PublishableRunAttestationError, TypeError, ValueError):
            _payload_fail()

    def payload(self) -> dict[str, object]:
        """Return the complete public receipt without authentication secrets."""

        return {
            **self._body(),
            "receipt_sha256": self.receipt_sha256,
            "authentication_hmac_sha256": self.authentication_hmac_sha256,
        }

    def _body(self) -> dict[str, object]:
        return _body(
            suite_authority_sha256=self.suite_authority_sha256,
            ordered_run_authority_sha256=self.ordered_run_authority_sha256,
            official_case_authority_root_sha256=self.official_case_authority_root_sha256,
            retrieval_authority_root_sha256=self.retrieval_authority_root_sha256,
            extraction_suite_readback_sha256=self.extraction_suite_readback_sha256,
            production_composition_authority_sha256=self.production_composition_authority_sha256,
            suite_seal_sha256=self.suite_seal_sha256,
            terminal_disposition=self.terminal_disposition,
            case_count=self.case_count,
            evaluation_call_count=self.evaluation_call_count,
            extraction_operation_count=self.extraction_operation_count,
            provider_intent_count=self.provider_intent_count,
            provider_result_count=self.provider_result_count,
            provider_call_count=self.provider_call_count,
            provider_accounting_complete=self.provider_accounting_complete,
            charged_tokens=self.charged_tokens,
            call_ledger=self.call_ledger,
            paired_outcome=self.paired_outcome,
            publishable=self.publishable,
            authentication_key_id=self.authentication_key_id,
            schema_version=self.schema_version,
        )

    def __repr__(self) -> str:
        return (
            "PublishableRunAttestation("
            f"authentication_key_id={self.authentication_key_id!r}, "
            f"terminal_disposition={self.terminal_disposition!r}, "
            f"publishable={self.publishable!r}, "
            f"receipt_sha256={self.receipt_sha256!r}, authentication=<redacted>)"
        )


def verify_publishable_run_attestation(
    receipt: PublishableRunAttestation,
    *,
    authentication_secret: bytes,
    expected_authentication_key_id: str | None = None,
) -> bool:
    """Fail closed unless the exact receipt commitment and HMAC authenticate."""

    try:
        _require_secret(authentication_secret)
        if type(receipt) is not PublishableRunAttestation:
            return False
        PublishableRunAttestation.__post_init__(receipt)
        if expected_authentication_key_id is not None and (
            not _is_identifier(expected_authentication_key_id)
            or not hmac.compare_digest(
                receipt.authentication_key_id,
                expected_authentication_key_id,
            )
        ):
            return False
        expected = _authentication_hmac(authentication_secret, receipt._body())
        return hmac.compare_digest(expected, receipt.authentication_hmac_sha256)
    except Exception:
        return False


def publishable_run_attestation_from_payload(value: object) -> PublishableRunAttestation:
    return PublishableRunAttestation.from_payload(value)


def _body(
    *,
    suite_authority_sha256: object,
    ordered_run_authority_sha256: object,
    official_case_authority_root_sha256: object,
    retrieval_authority_root_sha256: object,
    extraction_suite_readback_sha256: object,
    production_composition_authority_sha256: object,
    suite_seal_sha256: object,
    terminal_disposition: object,
    case_count: object,
    evaluation_call_count: object,
    extraction_operation_count: object,
    provider_intent_count: object,
    provider_result_count: object,
    provider_call_count: object,
    provider_accounting_complete: object,
    charged_tokens: object,
    call_ledger: object,
    paired_outcome: object,
    publishable: object,
    authentication_key_id: object,
    schema_version: object = PUBLISHABLE_RUN_ATTESTATION_SCHEMA_VERSION,
) -> dict[str, object]:
    ordered = (
        list(ordered_run_authority_sha256)
        if type(ordered_run_authority_sha256) is tuple
        else ordered_run_authority_sha256
    )
    ledger_material = (
        call_ledger.material() if type(call_ledger) is PublishableCallLedger else call_ledger
    )
    paired_material = (
        paired_outcome.material()
        if type(paired_outcome) is PairedOutcomeSealBinding
        else paired_outcome
    )
    return {
        "schema_version": schema_version,
        "suite_authority_sha256": suite_authority_sha256,
        "ordered_run_authority_sha256": ordered,
        "official_case_authority_root_sha256": official_case_authority_root_sha256,
        "retrieval_authority_root_sha256": retrieval_authority_root_sha256,
        "extraction_suite_readback_sha256": extraction_suite_readback_sha256,
        "production_composition_authority_sha256": production_composition_authority_sha256,
        "suite_seal_sha256": suite_seal_sha256,
        "terminal_disposition": terminal_disposition,
        "case_count": case_count,
        "evaluation_call_count": evaluation_call_count,
        "extraction_operation_count": extraction_operation_count,
        "provider_intent_count": provider_intent_count,
        "provider_result_count": provider_result_count,
        "provider_call_count": provider_call_count,
        "provider_accounting_complete": provider_accounting_complete,
        "charged_tokens": charged_tokens,
        "call_ledger": ledger_material,
        "paired_outcome": paired_material,
        "publishable": publishable,
        "authentication_key_id": authentication_key_id,
    }


def _validate_body(body: dict[str, object]) -> None:
    ordered_runs = body.get("ordered_run_authority_sha256")
    required_digests = (
        body.get("suite_authority_sha256"),
        body.get("official_case_authority_root_sha256"),
        body.get("retrieval_authority_root_sha256"),
        body.get("extraction_suite_readback_sha256"),
        body.get("production_composition_authority_sha256"),
    )
    counts = (
        body.get("case_count"),
        body.get("evaluation_call_count"),
        body.get("extraction_operation_count"),
        body.get("provider_intent_count"),
        body.get("provider_result_count"),
        body.get("provider_call_count"),
    )
    charged_tokens = body.get("charged_tokens")
    seal = body.get("suite_seal_sha256")
    try:
        publishable_call_ledger_from_material(body.get("call_ledger"))
        paired_material = body.get("paired_outcome")
        if paired_material is not None:
            paired_outcome_seal_binding_from_material(paired_material)
    except Exception:
        _fail("publishable_run_attestation_invalid")
    if (
        set(body) != _BODY_KEYS
        or body.get("schema_version") != PUBLISHABLE_RUN_ATTESTATION_SCHEMA_VERSION
        or type(ordered_runs) is not list
        or len(ordered_runs) != 2
        or any(not _is_sha256(item) for item in ordered_runs)
        or len(set(ordered_runs)) != 2
        or any(not _is_sha256(item) for item in required_digests)
        or seal is not None
        and not _is_sha256(seal)
        or type(body.get("terminal_disposition")) is not str
        or _DISPOSITION.fullmatch(body["terminal_disposition"]) is None
        or any(not _is_count(item) for item in counts)
        or charged_tokens is not None
        and not _is_count(charged_tokens)
        or type(body.get("provider_accounting_complete")) is not bool
        or type(body.get("publishable")) is not bool
        or not _is_identifier(body.get("authentication_key_id"))
        or body["publishable"] is True
        and not _publication_gate(body)
    ):
        _fail("publishable_run_attestation_invalid")


def _publication_gate(body: dict[str, object]) -> bool:
    try:
        ledger = publishable_call_ledger_from_material(body.get("call_ledger"))
        paired = paired_outcome_seal_binding_from_material(body.get("paired_outcome"))
    except Exception:
        return False
    return bool(
        body.get("terminal_disposition") == _SEALED
        and body.get("case_count") == EXPECTED_CASE_COUNT
        and body.get("evaluation_call_count") == EXPECTED_EVALUATION_CALL_COUNT
        and body.get("extraction_operation_count") == EXPECTED_EXTRACTION_OPERATION_COUNT
        and body.get("provider_intent_count") == EXPECTED_PROVIDER_CALL_COUNT
        and body.get("provider_result_count") == EXPECTED_PROVIDER_CALL_COUNT
        and body.get("provider_call_count") == EXPECTED_PROVIDER_CALL_COUNT
        and body.get("provider_accounting_complete") is True
        and _is_sha256(body.get("suite_seal_sha256"))
        and ledger.extraction_call_count == EXPECTED_EXTRACTION_OPERATION_COUNT
        and ledger.answer_judge_call_count == EXPECTED_EVALUATION_CALL_COUNT
        and ledger.total_call_count
        == EXPECTED_EXTRACTION_OPERATION_COUNT + EXPECTED_EVALUATION_CALL_COUNT
        and paired.pair_count == EXPECTED_CASE_COUNT
        and paired.paired_superiority_criterion_met is True
    )


def _receipt_sha256(body: dict[str, object]) -> str:
    message = _domain_message(PUBLISHABLE_RUN_ATTESTATION_RECEIPT_DOMAIN, body)
    return hashlib.sha256(message).hexdigest()


def _authentication_hmac(secret: bytes, body: dict[str, object]) -> str:
    return hmac.new(
        secret,
        _domain_message(PUBLISHABLE_RUN_ATTESTATION_HMAC_DOMAIN, body),
        hashlib.sha256,
    ).hexdigest()


def _domain_message(domain: str, body: dict[str, object]) -> bytes:
    try:
        return domain.encode("ascii") + b"\0" + canonical_json(body)
    except Exception:
        _fail("publishable_run_attestation_invalid")


def _require_secret(value: object) -> bytes:
    if type(value) is not bytes or len(value) < 32:
        _fail("publishable_run_attestation_authentication_secret_invalid")
    return value


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _is_identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def _is_count(value: object) -> bool:
    return type(value) is int and 0 <= value <= _MAX_SAFE_INTEGER


def _payload_fail() -> None:
    _fail("publishable_run_attestation_payload_invalid")


def _fail(code: str) -> None:
    raise PublishableRunAttestationError(code) from None


__all__ = (
    "EXPECTED_CASE_COUNT",
    "EXPECTED_EVALUATION_CALL_COUNT",
    "EXPECTED_EXTRACTION_OPERATION_COUNT",
    "EXPECTED_PROVIDER_CALL_COUNT",
    "PUBLISHABLE_RUN_ATTESTATION_HMAC_DOMAIN",
    "PUBLISHABLE_RUN_ATTESTATION_RECEIPT_DOMAIN",
    "PUBLISHABLE_RUN_ATTESTATION_SCHEMA_VERSION",
    "PublishableRunAttestation",
    "PublishableRunAttestationError",
    "publishable_run_attestation_from_payload",
    "verify_publishable_run_attestation",
)
