"""Exact public-value validation for gold-blind dispatch proofs."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Callable

from infinity_context_server.memory_comparison_gold_blind_validation import (
    GoldBlindContractError,
)

RUN_DISPATCH_PROOF_SCHEMA_VERSION = "memory-comparison-gold-blind-dispatch-proof.v4"
_MAX_ID_CHARS = 16_384
_HEX_256 = re.compile(r"^[0-9a-f]{64}$")


def build_dispatch_commitment(
    secret: bytes,
    fields: dict[str, object],
) -> str:
    payload = canonical_dispatch_json(
        {"schema_version": RUN_DISPATCH_PROOF_SCHEMA_VERSION, **fields}
    )
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def build_dispatch_report_fields(
    *,
    run_id: str,
    comparison_binding_commitment_sha256: str,
    case_ids: tuple[str, ...],
    stages: tuple[str, ...],
    receipt_identity: Callable[[str, str], str],
) -> dict[str, object]:
    stage_identities = {
        stage: hashlib.sha256(
            "".join(receipt_identity(case_id, stage) for case_id in sorted(case_ids)).encode()
        ).hexdigest()
        for stage in stages
    }
    count = len(case_ids)
    return {
        "run_id": run_id,
        "comparison_binding_commitment_sha256": comparison_binding_commitment_sha256,
        "expected_case_count": count,
        "retrieval_dispatch_count": count,
        "answer_dispatch_count": count,
        "judge_dispatch_count": count,
        "retrieval_identity": stage_identities["retrieval"],
        "answer_identity": stage_identities["answer"],
        "judge_identity": stage_identities["judge"],
    }


def validate_dispatch_id(value: object, *, field_name: str) -> None:
    if type(value) is not str or not value.strip() or len(value) > _MAX_ID_CHARS:
        raise GoldBlindContractError(f"{field_name} is invalid")


def validate_dispatch_digest(value: object, *, field_name: str) -> None:
    if type(value) is not str or not _HEX_256.fullmatch(value):
        raise GoldBlindContractError(f"{field_name} is invalid")


def canonical_dispatch_json(value: object) -> bytes:
    _validate_exact_json(value, depth=0)
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError):
        raise GoldBlindContractError("Dispatch identity is not JSON") from None


def parse_canonical_dispatch_json(value: bytes) -> object:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, UnicodeError):
        raise GoldBlindContractError("Dispatch identity is not JSON") from None
    if canonical_dispatch_json(parsed) != value:
        raise GoldBlindContractError("Dispatch identity is not canonical")
    return parsed


def _validate_exact_json(value: object, *, depth: int) -> None:
    if depth > 12:
        raise GoldBlindContractError("Dispatch identity nesting is invalid")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise GoldBlindContractError("Dispatch identity number is invalid")
        return
    if type(value) is list:
        for item in value:
            _validate_exact_json(item, depth=depth + 1)
        return
    if type(value) is dict:
        for key, _item in value.items():
            if type(key) is not str:
                raise GoldBlindContractError("Dispatch identity key is invalid")
