"""HMAC-authenticated opaque corpus ingest receipts for managed Mem0 v5."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import weakref
from dataclasses import dataclass, replace
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5CorpusIngestEvidence,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    canonical_sha256,
    is_sha256,
)


class ManagedMem0V5IngestReceiptError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _ReceiptSetState:
    binding: ManagedRunnerCompositionBinding
    corpus_ids: tuple[str, ...]
    authority_commitment_sha256: str
    seal_commitment_sha256: str | None
    issued: tuple[weakref.ReferenceType[ManagedMem0V5CorpusIngestReceipt], ...]
    consumed: bool
    integrity_mac: bytes


@dataclass(frozen=True, slots=True)
class _ReceiptState:
    owner_ref: weakref.ReferenceType[ManagedMem0V5CorpusIngestReceiptSet]
    binding: ManagedRunnerCompositionBinding
    evidence: ManagedMem0V5CorpusIngestEvidence
    ordinal: int
    corpus_id: str
    authority_commitment_sha256: str
    seal_commitment_sha256: str
    target_identity_sha256: str
    evidence_snapshot_sha256: str
    phase: str
    integrity_mac: bytes


_LOCK = threading.RLock()
_SECRET = secrets.token_bytes(32)
_SETS: weakref.WeakKeyDictionary[ManagedMem0V5CorpusIngestReceiptSet, _ReceiptSetState]
_RECEIPTS: weakref.WeakKeyDictionary[ManagedMem0V5CorpusIngestReceipt, _ReceiptState]


@final
class ManagedMem0V5CorpusIngestReceipt:
    __slots__ = ("__weakref__",)

    def __repr__(self) -> str:
        return "ManagedMem0V5CorpusIngestReceipt(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedMem0V5CorpusIngestReceipt is nonserializable")


@final
class ManagedMem0V5CorpusIngestReceiptSet:
    """Issue, consume and later revalidate one exact manifest-ordered set."""

    __slots__ = ("__weakref__",)

    def __init__(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        corpus_ids: tuple[str, ...],
        authority_commitment_sha256: str,
    ) -> None:
        if (
            type(composition_binding) is not ManagedRunnerCompositionBinding
            or type(corpus_ids) is not tuple
            or not corpus_ids
            or any(type(item) is not str or not item or item != item.strip() for item in corpus_ids)
            or len(set(corpus_ids)) != len(corpus_ids)
            or not is_sha256(authority_commitment_sha256)
        ):
            raise ManagedMem0V5IngestReceiptError("managed_mem0_v5_receipt_set_invalid")
        _store_set(
            self,
            _ReceiptSetState(
                composition_binding,
                corpus_ids,
                authority_commitment_sha256,
                None,
                (),
                False,
                b"",
            ),
        )

    @property
    def composition_binding(self) -> ManagedRunnerCompositionBinding:
        return _set_state(self).binding

    def issue(
        self, evidence: ManagedMem0V5CorpusIngestEvidence
    ) -> ManagedMem0V5CorpusIngestReceipt:
        with _LOCK:
            owner = _set_state_locked(self)
            ordinal = len(owner.issued)
            if (
                owner.consumed
                or ordinal >= len(owner.corpus_ids)
                or type(evidence) is not ManagedMem0V5CorpusIngestEvidence
                or evidence.run_id != owner.binding.run_id
                or evidence.corpus_id != owner.corpus_ids[ordinal]
                or evidence.authority_commitment_sha256 != owner.authority_commitment_sha256
                or (
                    owner.seal_commitment_sha256 is not None
                    and evidence.seal_commitment_sha256 != owner.seal_commitment_sha256
                )
            ):
                raise ManagedMem0V5IngestReceiptError("managed_mem0_v5_receipt_issue_invalid")
            evidence.__post_init__()
            receipt = ManagedMem0V5CorpusIngestReceipt()
            receipt_state = _ReceiptState(
                weakref.ref(self),
                owner.binding,
                evidence,
                ordinal,
                evidence.corpus_id,
                evidence.authority_commitment_sha256,
                evidence.seal_commitment_sha256,
                evidence.target_identity_sha256,
                _evidence_snapshot_sha256(evidence),
                "issued",
                b"",
            )
            _store_receipt(receipt, receipt_state)
            _store_set_locked(
                self,
                replace(
                    owner,
                    seal_commitment_sha256=evidence.seal_commitment_sha256,
                    issued=(*owner.issued, weakref.ref(receipt)),
                    integrity_mac=b"",
                ),
            )
            return receipt

    def consume_exact_ordered(
        self, receipts: tuple[ManagedMem0V5CorpusIngestReceipt, ...]
    ) -> tuple[ManagedMem0V5CorpusIngestEvidence, ...]:
        """Authenticate the complete tuple before atomically consuming any item."""

        with _LOCK:
            owner = _set_state_locked(self)
            states = _require_exact_receipts_locked(
                self,
                owner,
                receipts,
                expected_phase="issued",
                require_consumed=False,
            )
            next_receipts = tuple(
                replace(
                    state,
                    phase="consumed",
                    integrity_mac=b"",
                )
                for state in states
            )
            authenticated = tuple(
                replace(state, integrity_mac=_receipt_mac(receipt, state))
                for receipt, state in zip(receipts, next_receipts, strict=True)
            )
            next_owner = replace(owner, consumed=True, integrity_mac=b"")
            next_owner = replace(
                next_owner,
                integrity_mac=_set_mac(self, next_owner),
            )
            for receipt, state in zip(receipts, authenticated, strict=True):
                _RECEIPTS[receipt] = state
            _SETS[self] = next_owner
            return tuple(state.evidence for state in authenticated)

    def authenticate_exact_ordered(
        self, receipts: tuple[ManagedMem0V5CorpusIngestReceipt, ...]
    ) -> tuple[ManagedMem0V5CorpusIngestEvidence, ...]:
        """Authenticate an issued tuple without crossing its consume boundary."""

        with _LOCK:
            owner = _set_state_locked(self)
            states = _require_exact_receipts_locked(
                self,
                owner,
                receipts,
                expected_phase="issued",
                require_consumed=False,
            )
            return tuple(state.evidence for state in states)

    def validate_consumed(
        self,
        receipts: tuple[ManagedMem0V5CorpusIngestReceipt, ...],
    ) -> tuple[ManagedMem0V5CorpusIngestEvidence, ...]:
        """Reauthenticate the accepted snapshot immediately before cleanup I/O."""

        with _LOCK:
            owner = _set_state_locked(self)
            states = _require_exact_receipts_locked(
                self,
                owner,
                receipts,
                expected_phase="consumed",
                require_consumed=True,
            )
            return tuple(state.evidence for state in states)

    def __repr__(self) -> str:
        return "ManagedMem0V5CorpusIngestReceiptSet(<opaque>)"


def _require_exact_receipts_locked(
    receipt_set: ManagedMem0V5CorpusIngestReceiptSet,
    owner: _ReceiptSetState,
    receipts: object,
    *,
    expected_phase: str,
    require_consumed: bool,
) -> tuple[_ReceiptState, ...]:
    if (
        owner.consumed is not require_consumed
        or type(receipts) is not tuple
        or len(receipts) != len(owner.corpus_ids)
        or len(owner.issued) != len(owner.corpus_ids)
        or any(
            issued_ref() is not supplied
            for supplied, issued_ref in zip(receipts, owner.issued, strict=True)
        )
    ):
        raise ManagedMem0V5IngestReceiptError("managed_mem0_v5_receipt_consume_invalid")
    states = []
    for ordinal, receipt in enumerate(receipts):
        state = _receipt_state_locked(receipt)
        if (
            state.owner_ref() is not receipt_set
            or state.binding is not owner.binding
            or state.ordinal != ordinal
            or state.corpus_id != owner.corpus_ids[ordinal]
            or state.authority_commitment_sha256 != owner.authority_commitment_sha256
            or state.seal_commitment_sha256 != owner.seal_commitment_sha256
            or state.phase != expected_phase
        ):
            raise ManagedMem0V5IngestReceiptError("managed_mem0_v5_receipt_consume_invalid")
        states.append(state)
    return tuple(states)


def _set_state(value: object) -> _ReceiptSetState:
    if type(value) is not ManagedMem0V5CorpusIngestReceiptSet:
        raise ManagedMem0V5IngestReceiptError("managed_mem0_v5_receipt_set_invalid")
    with _LOCK:
        return _set_state_locked(value)


def _set_state_locked(value: ManagedMem0V5CorpusIngestReceiptSet) -> _ReceiptSetState:
    state = _SETS.get(value)
    try:
        valid = state is not None and hmac.compare_digest(
            state.integrity_mac,
            _set_mac(value, replace(state, integrity_mac=b"")),
        )
    except Exception:
        valid = False
    if (
        not valid
        or state is None
        or type(state.binding) is not ManagedRunnerCompositionBinding
        or type(state.corpus_ids) is not tuple
        or not state.corpus_ids
        or not is_sha256(state.authority_commitment_sha256)
        or (
            state.seal_commitment_sha256 is not None and not is_sha256(state.seal_commitment_sha256)
        )
        or type(state.issued) is not tuple
        or len(state.issued) > len(state.corpus_ids)
        or any(
            type(item) is not weakref.ReferenceType
            or type(item()) is not ManagedMem0V5CorpusIngestReceipt
            for item in state.issued
        )
        or type(state.consumed) is not bool
        or (state.consumed and len(state.issued) != len(state.corpus_ids))
    ):
        raise ManagedMem0V5IngestReceiptError("managed_mem0_v5_receipt_set_invalid")
    return state


def _receipt_state_locked(value: object) -> _ReceiptState:
    if type(value) is not ManagedMem0V5CorpusIngestReceipt:
        raise ManagedMem0V5IngestReceiptError("managed_mem0_v5_receipt_consume_invalid")
    state = _RECEIPTS.get(value)
    try:
        valid = state is not None and hmac.compare_digest(
            state.integrity_mac,
            _receipt_mac(value, replace(state, integrity_mac=b"")),
        )
    except Exception:
        valid = False
    if (
        not valid
        or state is None
        or type(state.owner_ref) is not weakref.ReferenceType
        or type(state.owner_ref()) is not ManagedMem0V5CorpusIngestReceiptSet
        or type(state.binding) is not ManagedRunnerCompositionBinding
        or type(state.evidence) is not ManagedMem0V5CorpusIngestEvidence
        or type(state.ordinal) is not int
        or state.ordinal < 0
        or state.phase not in {"issued", "consumed"}
    ):
        raise ManagedMem0V5IngestReceiptError("managed_mem0_v5_receipt_consume_invalid")
    state.evidence.__post_init__()
    if (
        state.evidence.run_id != state.binding.run_id
        or state.evidence.corpus_id != state.corpus_id
        or state.evidence.authority_commitment_sha256 != state.authority_commitment_sha256
        or state.evidence.seal_commitment_sha256 != state.seal_commitment_sha256
        or state.evidence.target_identity_sha256 != state.target_identity_sha256
        or _evidence_snapshot_sha256(state.evidence) != state.evidence_snapshot_sha256
    ):
        raise ManagedMem0V5IngestReceiptError("managed_mem0_v5_receipt_consume_invalid")
    return state


def _store_set(
    receipt_set: ManagedMem0V5CorpusIngestReceiptSet,
    state: _ReceiptSetState,
) -> None:
    with _LOCK:
        _store_set_locked(receipt_set, state)


def _store_set_locked(
    receipt_set: ManagedMem0V5CorpusIngestReceiptSet,
    state: _ReceiptSetState,
) -> None:
    unsigned = replace(state, integrity_mac=b"")
    _SETS[receipt_set] = replace(
        unsigned,
        integrity_mac=_set_mac(receipt_set, unsigned),
    )


def _store_receipt(
    receipt: ManagedMem0V5CorpusIngestReceipt,
    state: _ReceiptState,
) -> None:
    unsigned = replace(state, integrity_mac=b"")
    _RECEIPTS[receipt] = replace(
        unsigned,
        integrity_mac=_receipt_mac(receipt, unsigned),
    )


def _set_mac(
    receipt_set: ManagedMem0V5CorpusIngestReceiptSet,
    state: _ReceiptSetState,
) -> bytes:
    payload = {
        "set_identity": id(receipt_set),
        "binding_identity": id(state.binding),
        "run_id": state.binding.run_id,
        "binding_commitment_sha256": state.binding.binding_commitment_sha256,
        "corpus_ids": state.corpus_ids,
        "authority_commitment_sha256": state.authority_commitment_sha256,
        "seal_commitment_sha256": state.seal_commitment_sha256,
        "issued_identities": tuple(_weak_identity(item) for item in state.issued),
        "consumed": state.consumed,
    }
    return _mac(payload)


def _receipt_mac(
    receipt: ManagedMem0V5CorpusIngestReceipt,
    state: _ReceiptState,
) -> bytes:
    payload = {
        "receipt_identity": id(receipt),
        "owner_identity": _weak_identity(state.owner_ref),
        "binding_identity": id(state.binding),
        "run_id": state.binding.run_id,
        "ordinal": state.ordinal,
        "corpus_id": state.corpus_id,
        "authority_commitment_sha256": state.authority_commitment_sha256,
        "seal_commitment_sha256": state.seal_commitment_sha256,
        "target_identity_sha256": state.target_identity_sha256,
        "evidence_snapshot_sha256": state.evidence_snapshot_sha256,
        "current_evidence_snapshot_sha256": _evidence_snapshot_sha256(state.evidence),
        "phase": state.phase,
    }
    return _mac(payload)


def _evidence_snapshot_sha256(evidence: ManagedMem0V5CorpusIngestEvidence) -> str:
    return canonical_sha256(
        {
            **evidence.commitment_payload(),
            "evidence_commitment_sha256": evidence.evidence_commitment_sha256,
            "storage_commitments": [
                unit.storage_evidence_commitment_sha256 for unit in evidence.units
            ],
        }
    )


def _weak_identity(reference: weakref.ReferenceType[object]) -> int | None:
    value = reference()
    return None if value is None else id(value)


def _mac(payload: dict[str, object]) -> bytes:
    return hmac.new(
        _SECRET,
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).digest()


_SETS = weakref.WeakKeyDictionary()
_RECEIPTS = weakref.WeakKeyDictionary()


__all__ = (
    "ManagedMem0V5CorpusIngestReceipt",
    "ManagedMem0V5CorpusIngestReceiptSet",
    "ManagedMem0V5IngestReceiptError",
)
