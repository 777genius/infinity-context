"""Fail-closed retrieval-completeness evidence for fair comparisons.

This module intentionally has no HTTP/provider wiring. A trusted adapter must
issue evidence with the exact run-scoped key before any observation can match.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

RETRIEVAL_TOP_K = 200
ANSWER_CUTOFF = 50
COMPARISON_BACKEND_ROLES = ("infinity-context", "mem0")

_MAX_COUNT = 1_000_000_000
_MAX_ID_LENGTH = 512
_KEY_CONSTRUCTION_SEAL = object()


@dataclass(frozen=True)
class RetrievalCompletenessEvidence:
    """In-memory evidence emitted and attested by a retrieval adapter."""

    backend_role: str
    case_id: str
    requested_count: int
    answer_cutoff: int
    returned_count: int
    available_count: int
    exhaustive: bool
    continuation_proof: bytes | None = field(repr=False)
    attestation: bytes = field(repr=False)

    def __getstate__(self) -> object:
        raise TypeError("retrieval completeness proofs must never be serialized")


class RunScopedRetrievalCompletenessKey:
    """Exact sealed verifier for one in-memory retrieval comparison run."""

    __slots__ = ("_run_id", "_secret", "_seal")

    def __init__(
        self,
        *,
        run_id: str,
        secret: bytes,
        _construction_seal: object,
    ) -> None:
        if _construction_seal is not _KEY_CONSTRUCTION_SEAL:
            raise TypeError("use RunScopedRetrievalCompletenessKey.generate")
        if not _valid_id(run_id):
            raise ValueError("run_id must be a bounded non-empty string")
        if type(secret) is not bytes or len(secret) != 32:
            raise ValueError("retrieval completeness secret must contain exactly 32 bytes")
        self._run_id = run_id
        self._secret = secret
        self._seal = _KEY_CONSTRUCTION_SEAL

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("RunScopedRetrievalCompletenessKey is sealed")

    @classmethod
    def generate(cls, *, run_id: str) -> RunScopedRetrievalCompletenessKey:
        del cls
        return RunScopedRetrievalCompletenessKey(
            run_id=run_id,
            secret=secrets.token_bytes(32),
            _construction_seal=_KEY_CONSTRUCTION_SEAL,
        )

    def issue(
        self,
        *,
        backend_role: str,
        case_id: str,
        requested_count: int,
        answer_cutoff: int,
        returned_count: int,
        available_count: int,
        exhaustive: bool,
        continuation_proof: bytes | None,
    ) -> RetrievalCompletenessEvidence:
        evidence = RetrievalCompletenessEvidence(
            backend_role=backend_role,
            case_id=case_id,
            requested_count=requested_count,
            answer_cutoff=answer_cutoff,
            returned_count=returned_count,
            available_count=available_count,
            exhaustive=exhaustive,
            continuation_proof=continuation_proof,
            attestation=b"",
        )
        if not _attestable_evidence(evidence):
            raise ValueError("cannot attest malformed retrieval completeness evidence")
        return RetrievalCompletenessEvidence(
            backend_role=backend_role,
            case_id=case_id,
            requested_count=requested_count,
            answer_cutoff=answer_cutoff,
            returned_count=returned_count,
            available_count=available_count,
            exhaustive=exhaustive,
            continuation_proof=continuation_proof,
            attestation=hmac.new(
                self._secret,
                _attestation_payload(self._run_id, evidence),
                hashlib.sha256,
            ).digest(),
        )

    def verify(self, evidence: RetrievalCompletenessEvidence) -> bool:
        if not self._is_sealed() or not _attestable_evidence(evidence):
            return False
        expected = hmac.new(
            self._secret,
            _attestation_payload(self._run_id, evidence),
            hashlib.sha256,
        ).digest()
        return hmac.compare_digest(expected, evidence.attestation)

    def _is_sealed(self) -> bool:
        return (
            type(self) is RunScopedRetrievalCompletenessKey and self._seal is _KEY_CONSTRUCTION_SEAL
        )

    def __repr__(self) -> str:
        return "RunScopedRetrievalCompletenessKey(<redacted>)"

    def __getstate__(self) -> object:
        raise TypeError("run-scoped retrieval completeness keys must never be serialized")


def retrieval_width_contract(
    evidence: Sequence[object],
    *,
    expected_case_ids: Sequence[object],
    verifier: RunScopedRetrievalCompletenessKey | None,
) -> dict[str, object]:
    """Verify exact 200-wide retrieval for both frozen backend roles and every case."""

    evidence_sequence_valid = isinstance(evidence, Sequence) and not isinstance(
        evidence, str | bytes | bytearray
    )
    evidence_values = evidence if evidence_sequence_valid else ()
    expected_cases = _exact_unique_nonempty_strings(expected_case_ids)
    expected_cases_valid = expected_cases is not None and bool(expected_cases)
    expected_cases = expected_cases or ()
    expected_pairs = {
        (role, case_id) for role in COMPARISON_BACKEND_ROLES for case_id in expected_cases
    }

    counters: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    observed_pairs: Counter[tuple[str, str]] = Counter()
    requested_total = 0
    returned_total = 0
    available_total = 0
    exhaustive_count = 0
    continuation_count = 0

    if not expected_cases_valid:
        counters["invalid_expected_case_set_count"] += 1
    if not evidence_sequence_valid:
        counters["invalid_evidence_sequence_count"] += 1
    trusted_verifier = (
        verifier
        if type(verifier) is RunScopedRetrievalCompletenessKey and verifier._is_sealed()
        else None
    )
    if verifier is None:
        counters["missing_verifier_count"] += 1
    elif trusted_verifier is None:
        counters["invalid_verifier_type_count"] += 1

    for raw in evidence_values:
        if not isinstance(raw, RetrievalCompletenessEvidence):
            counters["invalid_evidence_type_count"] += 1
            continue
        identity = (raw.backend_role, raw.case_id)
        observed_pairs[identity] += 1
        if raw.backend_role not in COMPARISON_BACKEND_ROLES:
            counters["invalid_backend_role_count"] += 1
            continue
        role_counts[raw.backend_role] += 1
        if raw.case_id not in expected_cases:
            counters["unexpected_case_count"] += 1
            continue
        if observed_pairs[identity] > 1:
            counters["duplicate_role_case_count"] += 1

        counts = (
            raw.requested_count,
            raw.answer_cutoff,
            raw.returned_count,
            raw.available_count,
        )
        if any(_exact_bounded_count(value) is None for value in counts):
            counters["invalid_count_count"] += 1
            continue
        requested_total = _bounded_add(requested_total, raw.requested_count)
        returned_total = _bounded_add(returned_total, raw.returned_count)
        available_total = _bounded_add(available_total, raw.available_count)

        if raw.requested_count != RETRIEVAL_TOP_K:
            counters["mismatched_requested_count"] += 1
        if raw.answer_cutoff != ANSWER_CUTOFF:
            counters["mismatched_answer_cutoff_count"] += 1
        if raw.returned_count > raw.available_count:
            counters["returned_exceeds_available_count"] += 1
        if raw.returned_count != min(raw.available_count, RETRIEVAL_TOP_K):
            counters["incomplete_return_count"] += 1

        if type(raw.exhaustive) is not bool:
            counters["invalid_exhaustive_flag_count"] += 1
            continue
        continuation_present = _nonempty_bytes(raw.continuation_proof)
        if raw.exhaustive:
            exhaustive_count += 1
        if continuation_present:
            continuation_count += 1
        if raw.available_count <= RETRIEVAL_TOP_K:
            shape_valid = (
                raw.exhaustive
                and raw.continuation_proof is None
                and raw.returned_count == raw.available_count
            )
        else:
            shape_valid = (
                not raw.exhaustive
                and continuation_present
                and raw.returned_count == RETRIEVAL_TOP_K
            )
        if not shape_valid:
            counters["missing_exhaustive_or_continuation_evidence_count"] += 1

        if not _nonempty_bytes(raw.attestation):
            counters["missing_attestation_count"] += 1
        elif trusted_verifier is None or not trusted_verifier.verify(raw):
            counters["untrusted_attestation_count"] += 1

    missing_pairs = expected_pairs - set(observed_pairs)
    unexpected_pairs = set(observed_pairs) - expected_pairs
    duplicate_pair_count = sum(max(0, count - 1) for count in observed_pairs.values())
    counters["missing_role_case_count"] += len(missing_pairs)
    counters["unexpected_role_case_count"] += len(unexpected_pairs)
    counters["duplicate_role_case_count"] = max(
        counters["duplicate_role_case_count"], duplicate_pair_count
    )

    matches = bool(
        expected_cases_valid
        and evidence_values
        and len(observed_pairs) == len(expected_pairs)
        and not any(counters.values())
    )
    blockers = [] if matches else ["retrieval_completeness_not_verified"]
    blockers.append("session_isolation_not_composed")
    return {
        "schema_version": "memory-comparison-retrieval-completeness.v1",
        "status": "valid" if matches else "blocked",
        "matches": matches,
        "publishable": False,
        "publication_status": "pending_composite_wiring",
        "publication_blockers": blockers,
        "wiring_status": "trusted_adapter_verifier_required",
        "expected_retrieval_top_k": RETRIEVAL_TOP_K,
        "expected_answer_cutoff": ANSWER_CUTOFF,
        "expected_backend_roles": list(COMPARISON_BACKEND_ROLES),
        "expected_case_count": min(len(expected_cases), _MAX_COUNT),
        "expected_observation_count": min(len(expected_pairs), _MAX_COUNT),
        "observation_count": min(len(evidence_values), _MAX_COUNT),
        "observed_backend_role_counts": {
            role: min(role_counts[role], _MAX_COUNT) for role in COMPARISON_BACKEND_ROLES
        },
        "requested_count_total": requested_total,
        "returned_count_total": returned_total,
        "available_count_total": available_total,
        "exhaustive_observation_count": min(exhaustive_count, _MAX_COUNT),
        "continuation_observation_count": min(continuation_count, _MAX_COUNT),
        "failure_counts": {
            key: min(value, _MAX_COUNT) for key, value in sorted(counters.items()) if value
        },
    }


def _exact_unique_nonempty_strings(value: Sequence[object]) -> tuple[str, ...] | None:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return None
    items = tuple(value)
    if not items or any(
        type(item) is not str or not item or len(item) > _MAX_ID_LENGTH or item != item.strip()
        for item in items
    ):
        return None
    normalized = tuple(items)
    if len(set(normalized)) != len(normalized):
        return None
    return normalized


def _exact_bounded_count(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= _MAX_COUNT else None


def _nonempty_bytes(value: object) -> bool:
    return type(value) is bytes and bool(value)


def _bounded_add(total: int, value: int) -> int:
    return min(_MAX_COUNT, total + value)


def _valid_id(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and len(value) <= _MAX_ID_LENGTH
        and value == value.strip()
    )


def _attestable_evidence(value: object) -> bool:
    return bool(
        type(value) is RetrievalCompletenessEvidence
        and value.backend_role in COMPARISON_BACKEND_ROLES
        and _valid_id(value.case_id)
        and all(
            _exact_bounded_count(count) is not None
            for count in (
                value.requested_count,
                value.answer_cutoff,
                value.returned_count,
                value.available_count,
            )
        )
        and type(value.exhaustive) is bool
        and (value.continuation_proof is None or type(value.continuation_proof) is bytes)
        and type(value.attestation) is bytes
    )


def _attestation_payload(
    run_id: str,
    evidence: RetrievalCompletenessEvidence,
) -> bytes:
    return json.dumps(
        {
            "answer_cutoff": evidence.answer_cutoff,
            "available_count": evidence.available_count,
            "backend_role": evidence.backend_role,
            "case_id": evidence.case_id,
            "continuation_proof_hex": (
                evidence.continuation_proof.hex() if evidence.continuation_proof else None
            ),
            "exhaustive": evidence.exhaustive,
            "requested_count": evidence.requested_count,
            "returned_count": evidence.returned_count,
            "run_id": run_id,
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


__all__ = (
    "ANSWER_CUTOFF",
    "COMPARISON_BACKEND_ROLES",
    "RETRIEVAL_TOP_K",
    "RetrievalCompletenessEvidence",
    "RunScopedRetrievalCompletenessKey",
    "retrieval_width_contract",
)
