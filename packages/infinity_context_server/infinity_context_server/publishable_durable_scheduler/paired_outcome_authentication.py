"""Authentication primitives for exact private paired judge output readback."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from typing import final

from infinity_context_server.memory_comparison_paired_superiority_policy import (
    paired_superiority_policy_payload,
)
from infinity_context_server.memory_comparison_publishable_contracts import (
    canonical_payload_sha256,
)
from infinity_context_server.publishable_durable_scheduler.contracts import canonical_json

PAIRED_JUDGE_OUTPUT_SCHEMA_VERSION = "memory-comparison-authenticated-judge-output.v1"

_EXPECTED_BENCHMARKS = frozenset(("locomo", "longmemeval"))
_EXPECTED_CATEGORIES = frozenset(
    item["category"] for item in paired_superiority_policy_payload()["expected_strata"]
)
_EXPECTED_BACKENDS = frozenset(("infinity-context", "mem0"))
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_JUDGE_OUTPUT_BYTES = 1024 * 1024
_JUDGE_OUTPUT_HMAC_DOMAIN = "memory-comparison/paired-judge-output/hmac-sha256/v1"


class PairedOutcomeContractError(ValueError):
    """Secret-free fail-closed rejection of invalid paired evidence."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True, repr=False)
class AuthenticatedJudgeOutput:
    """One exact judge plaintext authenticated to its scheduler lane."""

    suite_authority_sha256: str
    run_authority_sha256: str
    binding_commitment_sha256: str
    case_manifest_sha256: str
    benchmark: str
    category: str
    case_index: int
    case_id: str
    case_alias: str
    backend_role: str
    logical_call_id: str
    receipt_sha256: str
    read_policy_sha256: str
    raw_output: bytes = field(repr=False)
    authentication_hmac_sha256: str
    raw_output_sha256: str = field(init=False)
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        digests = (
            self.suite_authority_sha256,
            self.run_authority_sha256,
            self.binding_commitment_sha256,
            self.case_manifest_sha256,
            self.logical_call_id,
            self.receipt_sha256,
            self.read_policy_sha256,
            self.authentication_hmac_sha256,
        )
        if (
            any(not _is_sha256(value) for value in digests)
            or self.benchmark not in _EXPECTED_BENCHMARKS
            or self.category not in _EXPECTED_CATEGORIES
            or type(self.case_index) is not int
            or self.case_index < 0
            or not _bounded_text(self.case_id)
            or not _bounded_text(self.case_alias)
            or self.backend_role not in _EXPECTED_BACKENDS
            or type(self.raw_output) is not bytes
            or not 1 <= len(self.raw_output) <= _MAX_JUDGE_OUTPUT_BYTES
        ):
            _fail("paired_judge_output_invalid")
        raw_sha256 = hashlib.sha256(self.raw_output).hexdigest()
        object.__setattr__(self, "raw_output_sha256", raw_sha256)
        object.__setattr__(
            self,
            "commitment_sha256",
            canonical_payload_sha256(
                {
                    **self.authentication_material(),
                    "authentication_hmac_sha256": self.authentication_hmac_sha256,
                }
            ),
        )

    def authentication_material(self) -> dict[str, object]:
        return {
            "schema_version": PAIRED_JUDGE_OUTPUT_SCHEMA_VERSION,
            "suite_authority_sha256": self.suite_authority_sha256,
            "run_authority_sha256": self.run_authority_sha256,
            "binding_commitment_sha256": self.binding_commitment_sha256,
            "case_manifest_sha256": self.case_manifest_sha256,
            "benchmark": self.benchmark,
            "category": self.category,
            "case_index": self.case_index,
            "case_id": self.case_id,
            "case_alias": self.case_alias,
            "backend_role": self.backend_role,
            "logical_call_id": self.logical_call_id,
            "receipt_sha256": self.receipt_sha256,
            "read_policy_sha256": self.read_policy_sha256,
            "raw_output_sha256": self.raw_output_sha256,
        }

    def __repr__(self) -> str:
        return (
            "AuthenticatedJudgeOutput("
            f"benchmark={self.benchmark!r}, case_index={self.case_index!r}, "
            f"backend_role={self.backend_role!r}, raw_output=<private>)"
        )


def authenticate_judge_output(
    *,
    suite_authority_sha256: str,
    run_authority_sha256: str,
    binding_commitment_sha256: str,
    case_manifest_sha256: str,
    benchmark: str,
    category: str,
    case_index: int,
    case_id: str,
    case_alias: str,
    backend_role: str,
    logical_call_id: str,
    receipt_sha256: str,
    read_policy_sha256: str,
    raw_output: bytes,
    authentication_secret: bytes,
) -> AuthenticatedJudgeOutput:
    """Issue an authenticated DTO after an adapter proves exact plaintext readback."""

    raw_sha256 = hashlib.sha256(raw_output).hexdigest() if type(raw_output) is bytes else ""
    material = _judge_output_material(
        suite_authority_sha256=suite_authority_sha256,
        run_authority_sha256=run_authority_sha256,
        binding_commitment_sha256=binding_commitment_sha256,
        case_manifest_sha256=case_manifest_sha256,
        benchmark=benchmark,
        category=category,
        case_index=case_index,
        case_id=case_id,
        case_alias=case_alias,
        backend_role=backend_role,
        logical_call_id=logical_call_id,
        receipt_sha256=receipt_sha256,
        read_policy_sha256=read_policy_sha256,
        raw_output_sha256=raw_sha256,
    )
    authentication = _hmac_sha256(
        authentication_secret,
        _JUDGE_OUTPUT_HMAC_DOMAIN,
        material,
    )
    return AuthenticatedJudgeOutput(
        suite_authority_sha256=suite_authority_sha256,
        run_authority_sha256=run_authority_sha256,
        binding_commitment_sha256=binding_commitment_sha256,
        case_manifest_sha256=case_manifest_sha256,
        benchmark=benchmark,
        category=category,
        case_index=case_index,
        case_id=case_id,
        case_alias=case_alias,
        backend_role=backend_role,
        logical_call_id=logical_call_id,
        receipt_sha256=receipt_sha256,
        read_policy_sha256=read_policy_sha256,
        raw_output=raw_output,
        authentication_hmac_sha256=authentication,
    )


def verify_authenticated_judge_output(
    value: object,
    *,
    authentication_secret: bytes,
) -> bool:
    try:
        if type(value) is not AuthenticatedJudgeOutput:
            return False
        AuthenticatedJudgeOutput.__post_init__(value)
        expected = _hmac_sha256(
            authentication_secret,
            _JUDGE_OUTPUT_HMAC_DOMAIN,
            value.authentication_material(),
        )
        return hmac.compare_digest(expected, value.authentication_hmac_sha256)
    except Exception:
        return False


def _judge_output_material(**values: object) -> dict[str, object]:
    return {"schema_version": PAIRED_JUDGE_OUTPUT_SCHEMA_VERSION, **values}


def _hmac_sha256(secret: object, domain: str, material: object) -> str:
    if not _valid_secret(secret):
        _fail("paired_outcome_authentication_secret_invalid")
    try:
        message = domain.encode("ascii") + b"\0" + canonical_json(material)
    except Exception:
        _fail("paired_outcome_authentication_material_invalid")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _valid_secret(value: object) -> bool:
    return type(value) is bytes and 32 <= len(value) <= 1024


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _bounded_text(value: object) -> bool:
    if type(value) is not str or not value:
        return False
    try:
        return len(value.encode("utf-8")) <= 200
    except UnicodeEncodeError:
        return False


def _fail(code: str) -> None:
    raise PairedOutcomeContractError(code) from None


__all__ = (
    "PAIRED_JUDGE_OUTPUT_SCHEMA_VERSION",
    "AuthenticatedJudgeOutput",
    "PairedOutcomeContractError",
    "authenticate_judge_output",
    "verify_authenticated_judge_output",
)
