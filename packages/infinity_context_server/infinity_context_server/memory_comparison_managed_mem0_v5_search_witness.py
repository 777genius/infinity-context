"""Opaque process-local authority for authenticated managed Mem0 v5 search."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5SearchReceipt,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import canonical_sha256

_AUTHENTICATED_SEARCH_KEY = secrets.token_bytes(32)
_ISSUANCE_TOKEN = object()


@final
class ManagedMem0V5AuthenticatedSearchWitness:
    """Immutable-by-authority receipt issued only after coordinator verification."""

    __slots__ = ("_commitment", "_receipt")

    def __init__(self, *, receipt: ManagedMem0V5SearchReceipt, _token: object) -> None:
        if _token is not _ISSUANCE_TOKEN or type(receipt) is not ManagedMem0V5SearchReceipt:
            raise ManagedRunError("managed Mem0 v5 authenticated search witness is invalid")
        self._receipt = receipt
        self._commitment = _commitment(receipt)

    @property
    def receipt(self) -> ManagedMem0V5SearchReceipt:
        if not hmac.compare_digest(self._commitment, _commitment(self._receipt)):
            raise ManagedRunError("managed Mem0 v5 authenticated search witness differs")
        return self._receipt

    def __repr__(self) -> str:
        return "ManagedMem0V5AuthenticatedSearchWitness(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("managed Mem0 v5 authenticated search witnesses are nonserializable")


def _issue_managed_mem0_v5_authenticated_search_witness(
    receipt: ManagedMem0V5SearchReceipt,
) -> ManagedMem0V5AuthenticatedSearchWitness:
    return ManagedMem0V5AuthenticatedSearchWitness(receipt=receipt, _token=_ISSUANCE_TOKEN)


def _commitment(receipt: ManagedMem0V5SearchReceipt) -> str:
    payload = {
        "admission_commitment_sha256": receipt.admission_commitment_sha256,
        "corpus_id": receipt.corpus_id,
        "query_commitment_sha256": receipt.query_commitment_sha256,
        "limit": receipt.limit,
        "records": [item.public_payload(rank) for rank, item in enumerate(receipt.records)],
        "result_root_sha256": receipt.result_root_sha256,
        "evidence_commitment_sha256": receipt.evidence_commitment_sha256,
    }
    return hmac.new(
        _AUTHENTICATED_SEARCH_KEY,
        canonical_sha256(payload).encode(),
        hashlib.sha256,
    ).hexdigest()


__all__ = ("ManagedMem0V5AuthenticatedSearchWitness",)
