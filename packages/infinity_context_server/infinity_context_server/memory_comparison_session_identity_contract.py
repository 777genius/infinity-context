"""Run-scoped, non-serializable session-isolation proof contract.

The live HMAC verifier is required at publication time. Serialized verdict fields
alone never authorize publication, and neither the key nor proofs are emitted.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

SESSION_IDENTITY_CONTRACT_SCHEMA_VERSION = "memory-comparison-session-isolation.v2"
_SESSION_ALIAS_RE = re.compile(r"session-[0-9]{4}")
_MAX_ID_LENGTH = 512
_MAX_COUNT = 1_000_000_000
_KEY_CONSTRUCTION_SEAL = object()


@dataclass(frozen=True, slots=True)
class SessionIdentityMapping:
    """Exact public identity mapping expected for one conversation role."""

    corpus_id: str
    thread_id: str
    case_id: str
    conversation_role: str
    session_alias: str


@dataclass(frozen=True, slots=True)
class SessionIdentityEvidence:
    """In-memory signed mapping; its byte proof is never placed in artifacts."""

    mapping: SessionIdentityMapping
    proof: bytes = field(repr=False)

    def __getstate__(self) -> object:
        raise TypeError("session identity HMAC proofs must never be serialized")


class RunScopedSessionHmacKey:
    """Opaque run key used to issue and verify exact mapping evidence."""

    __slots__ = ("_run_id", "_secret", "_seal")

    def __init__(
        self,
        *,
        run_id: str,
        secret: bytes,
        _construction_seal: object,
    ) -> None:
        if _construction_seal is not _KEY_CONSTRUCTION_SEAL:
            raise TypeError("use RunScopedSessionHmacKey.generate")
        if not _valid_id(run_id):
            raise ValueError("run_id must be a bounded non-empty string")
        if type(secret) is not bytes or len(secret) != 32:
            raise ValueError("session HMAC secret must contain exactly 32 bytes")
        self._run_id = run_id
        self._secret = secret
        self._seal = _KEY_CONSTRUCTION_SEAL

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("RunScopedSessionHmacKey is sealed")

    @classmethod
    def generate(cls, *, run_id: str) -> RunScopedSessionHmacKey:
        """Create a fresh key for one in-memory benchmark run."""

        del cls
        return RunScopedSessionHmacKey(
            run_id=run_id,
            secret=secrets.token_bytes(32),
            _construction_seal=_KEY_CONSTRUCTION_SEAL,
        )

    def issue(self, mapping: SessionIdentityMapping) -> SessionIdentityEvidence:
        """Sign one validated mapping without exposing the secret."""

        if not _valid_mapping(mapping):
            raise ValueError("cannot sign an invalid session identity mapping")
        return SessionIdentityEvidence(
            mapping=mapping,
            proof=hmac.new(
                self._secret,
                _mapping_payload(self._run_id, mapping),
                hashlib.sha256,
            ).digest(),
        )

    def verify(self, evidence: SessionIdentityEvidence) -> bool:
        """Verify evidence for this exact run and mapping."""

        if not self._is_sealed() or type(evidence) is not SessionIdentityEvidence:
            return False
        if not _valid_mapping(evidence.mapping) or type(evidence.proof) is not bytes:
            return False
        expected = hmac.new(
            self._secret,
            _mapping_payload(self._run_id, evidence.mapping),
            hashlib.sha256,
        ).digest()
        return hmac.compare_digest(expected, evidence.proof)

    def _is_sealed(self) -> bool:
        return type(self) is RunScopedSessionHmacKey and self._seal is _KEY_CONSTRUCTION_SEAL

    def __repr__(self) -> str:
        return "RunScopedSessionHmacKey(<redacted>)"

    def __getstate__(self) -> object:
        raise TypeError("run-scoped session HMAC keys must never be serialized")


def session_identity_contract(
    expected_mappings: Sequence[object],
    evidence: Sequence[object],
    *,
    verifier: RunScopedSessionHmacKey | None,
) -> dict[str, object]:
    """Verify signed evidence equals the complete expected isolation mapping."""

    counters: Counter[str] = Counter()
    trusted_verifier = (
        verifier if type(verifier) is RunScopedSessionHmacKey and verifier._is_sealed() else None
    )
    expected = _validated_mappings(expected_mappings, counters, prefix="expected")
    observed = _validated_evidence(evidence, verifier=trusted_verifier, counters=counters)

    if verifier is None:
        counters["missing_live_verifier_count"] += 1
    elif trusted_verifier is None:
        counters["invalid_live_verifier_type_count"] += 1
    if not expected:
        counters["empty_expected_mapping_count"] += 1
    if not evidence:
        counters["empty_evidence_count"] += 1

    expected_set = set(expected)
    observed_mappings = tuple(item.mapping for item in observed)
    observed_set = set(observed_mappings)
    counters["missing_mapping_count"] += len(expected_set - observed_set)
    counters["unexpected_mapping_count"] += len(observed_set - expected_set)
    counters["duplicate_evidence_count"] += len(observed_mappings) - len(observed_set)

    matches = bool(
        expected
        and evidence
        and len(expected) == len(expected_set)
        and len(observed_mappings) == len(expected)
        and not any(counters.values())
    )
    blockers = [] if matches else ["session_isolation_not_verified"]
    blockers.append("retrieval_completeness_not_composed")
    return {
        "schema_version": SESSION_IDENTITY_CONTRACT_SCHEMA_VERSION,
        "status": "valid" if matches else "blocked",
        "matches": matches,
        "publishable": False,
        "publication_status": "pending_composite_wiring",
        "publication_blockers": blockers,
        "wiring_status": "live_run_scoped_hmac_verifier_required",
        "expected_mapping_count": min(len(expected), _MAX_COUNT),
        "verified_mapping_count": min(len(observed_mappings), _MAX_COUNT),
        "failure_counts": {
            key: min(value, _MAX_COUNT) for key, value in sorted(counters.items()) if value
        },
    }


def session_identity_contract_is_verified(
    payload: object,
    *,
    expected_mappings: Sequence[object],
    evidence: Sequence[object],
    verifier: RunScopedSessionHmacKey | None,
) -> bool:
    """Re-run live proof verification; never trust writable serialized markers."""

    if not isinstance(payload, dict):
        return False
    expected_payload = session_identity_contract(
        expected_mappings,
        evidence,
        verifier=verifier,
    )
    return bool(expected_payload["matches"] is True and payload == expected_payload)


def session_identity_contract_is_publishable(
    payload: object,
    *,
    expected_mappings: Sequence[object],
    evidence: Sequence[object],
    verifier: RunScopedSessionHmacKey | None,
) -> bool:
    """Remain closed until live retrieval completeness is composed in a later slice."""

    del payload, expected_mappings, evidence, verifier
    return False


def _validated_mappings(
    values: Sequence[object],
    counters: Counter[str],
    *,
    prefix: str,
) -> tuple[SessionIdentityMapping, ...]:
    if not isinstance(values, Sequence) or isinstance(values, str | bytes | bytearray):
        counters[f"invalid_{prefix}_sequence_count"] += 1
        return ()
    valid: list[SessionIdentityMapping] = []
    role_keys: Counter[tuple[str, str]] = Counter()
    alias_keys: Counter[tuple[str, str]] = Counter()
    case_corpora: dict[str, set[str]] = {}
    case_threads: dict[str, set[str]] = {}
    corpus_cases: dict[str, set[str]] = {}
    thread_cases: dict[str, set[str]] = {}
    alias_cases: dict[str, set[str]] = {}
    for value in values:
        if type(value) is not SessionIdentityMapping or not _valid_mapping(value):
            counters[f"invalid_{prefix}_mapping_count"] += 1
            continue
        valid.append(value)
        role_keys[(value.case_id, value.conversation_role)] += 1
        alias_keys[(value.case_id, value.session_alias)] += 1
        case_corpora.setdefault(value.case_id, set()).add(value.corpus_id)
        case_threads.setdefault(value.case_id, set()).add(value.thread_id)
        corpus_cases.setdefault(value.corpus_id, set()).add(value.case_id)
        thread_cases.setdefault(value.thread_id, set()).add(value.case_id)
        alias_cases.setdefault(value.session_alias, set()).add(value.case_id)
    counters[f"duplicate_{prefix}_role_count"] += sum(
        max(0, count - 1) for count in role_keys.values()
    )
    counters[f"duplicate_{prefix}_alias_count"] += sum(
        max(0, count - 1) for count in alias_keys.values()
    )
    counters[f"multiple_{prefix}_corpus_per_case_count"] += sum(
        len(corpora) != 1 for corpora in case_corpora.values()
    )
    counters[f"multiple_{prefix}_thread_per_case_count"] += sum(
        len(threads) != 1 for threads in case_threads.values()
    )
    counters[f"cross_case_{prefix}_corpus_reuse_count"] += sum(
        len(cases) > 1 for cases in corpus_cases.values()
    )
    counters[f"cross_case_{prefix}_thread_reuse_count"] += sum(
        len(cases) > 1 for cases in thread_cases.values()
    )
    counters[f"cross_case_{prefix}_alias_reuse_count"] += sum(
        len(cases) > 1 for cases in alias_cases.values()
    )
    return tuple(valid)


def _validated_evidence(
    values: Sequence[object],
    *,
    verifier: RunScopedSessionHmacKey | None,
    counters: Counter[str],
) -> tuple[SessionIdentityEvidence, ...]:
    if not isinstance(values, Sequence) or isinstance(values, str | bytes | bytearray):
        counters["invalid_evidence_sequence_count"] += 1
        return ()
    accepted: list[SessionIdentityEvidence] = []
    for value in values:
        if type(value) is not SessionIdentityEvidence:
            counters["invalid_evidence_type_count"] += 1
            continue
        if not _valid_mapping(value.mapping) or type(value.proof) is not bytes or not value.proof:
            counters["invalid_evidence_shape_count"] += 1
            continue
        accepted.append(value)
    _validated_mappings(
        tuple(item.mapping for item in accepted),
        counters,
        prefix="evidence",
    )
    verified: list[SessionIdentityEvidence] = []
    for value in accepted:
        if verifier is None or not verifier.verify(value):
            counters["invalid_hmac_proof_count"] += 1
            continue
        verified.append(value)
    return tuple(verified)


def _valid_mapping(value: object) -> bool:
    return bool(
        type(value) is SessionIdentityMapping
        and _valid_id(value.corpus_id)
        and _valid_id(value.thread_id)
        and _valid_id(value.case_id)
        and _valid_id(value.conversation_role)
        and _valid_alias(value.session_alias)
    )


def _valid_id(value: object) -> bool:
    return type(value) is str and 0 < len(value) <= _MAX_ID_LENGTH and value == value.strip()


def _valid_alias(value: object) -> bool:
    if type(value) is not str or _SESSION_ALIAS_RE.fullmatch(value) is None:
        return False
    return int(value.removeprefix("session-")) > 0


def _mapping_payload(run_id: str, mapping: SessionIdentityMapping) -> bytes:
    return json.dumps(
        {
            "case_id": mapping.case_id,
            "conversation_role": mapping.conversation_role,
            "corpus_id": mapping.corpus_id,
            "run_id": run_id,
            "session_alias": mapping.session_alias,
            "thread_id": mapping.thread_id,
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


__all__ = (
    "SESSION_IDENTITY_CONTRACT_SCHEMA_VERSION",
    "RunScopedSessionHmacKey",
    "SessionIdentityEvidence",
    "SessionIdentityMapping",
    "session_identity_contract",
    "session_identity_contract_is_publishable",
    "session_identity_contract_is_verified",
)
