"""Gold-blind projection policy for authenticated managed Mem0 v5 search evidence."""

from __future__ import annotations

import hmac
from typing import final

from infinity_context_server.memory_comparison_gold_blind_answer_contract import GoldBlindEvidence
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5SearchRecord,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_search_witness import (
    ManagedMem0V5AuthenticatedSearchWitness,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    canonical_sha256,
    is_sha256,
)


@final
class ManagedMem0V5PairedEvidenceProjector:
    """Join contract-issued retrieval to canonical source time, never provider time."""

    __slots__ = (
        "_authority_commitment_sha256",
        "_expected_admission_commitment_sha256",
        "_sources",
    )

    def __init__(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        expected_admission_commitment_sha256: str,
    ) -> None:
        if type(authority) is not ManagedMem0V5ManifestAuthority:
            raise ManagedRunError("managed Mem0 v5 paired manifest authority is invalid")
        authority.__post_init__()
        if not is_sha256(expected_admission_commitment_sha256):
            raise ManagedRunError("managed Mem0 v5 paired admission authority is invalid")
        sources: dict[tuple[str, str], tuple[str, str]] = {}
        for unit in authority.units:
            key = (unit.corpus_id, unit.source_id)
            if key in sources:
                raise ManagedRunError("managed Mem0 v5 paired source authority is duplicated")
            sources[key] = (unit.source_sha256, unit.observation_date)
        self._sources = sources
        self._authority_commitment_sha256 = authority.authority_commitment_sha256
        self._expected_admission_commitment_sha256 = expected_admission_commitment_sha256

    @property
    def authority_commitment_sha256(self) -> str:
        return self._authority_commitment_sha256

    def project(
        self,
        *,
        authenticated_receipt: ManagedMem0V5AuthenticatedSearchWitness,
        corpus_id: str,
        query: str,
        top_k: int,
        cutoff: int,
    ) -> tuple[GoldBlindEvidence, ...]:
        _require_search_request(corpus_id=corpus_id, query=query, top_k=top_k, cutoff=cutoff)
        if type(authenticated_receipt) is not ManagedMem0V5AuthenticatedSearchWitness:
            raise ManagedRunError("managed Mem0 v5 paired search receipt is unauthenticated")
        receipt = authenticated_receipt.receipt
        receipt.__post_init__()
        expected_root = canonical_sha256(
            {
                "results": [
                    record.public_payload(rank) for rank, record in enumerate(receipt.records)
                ]
            }
        )
        if (
            receipt.admission_commitment_sha256 != self._expected_admission_commitment_sha256
            or receipt.corpus_id != corpus_id
            or receipt.query_commitment_sha256 != canonical_sha256({"query": query})
            or receipt.limit != top_k
            or len(receipt.records) > receipt.limit
            or receipt.result_root_sha256 != expected_root
        ):
            raise ManagedRunError("managed Mem0 v5 paired search binding differs")

        evidence: list[GoldBlindEvidence] = []
        seen_record_ids: set[str] = set()
        for rank, record in enumerate(receipt.records[:cutoff], start=1):
            if type(record) is not ManagedMem0V5SearchRecord:
                raise ManagedRunError("managed Mem0 v5 paired search record is invalid")
            record.__post_init__()
            if record.record_id in seen_record_ids:
                raise ManagedRunError("managed Mem0 v5 paired search record is duplicated")
            seen_record_ids.add(record.record_id)
            source = self._sources.get((corpus_id, record.source_id))
            if source is None:
                raise ManagedRunError("managed Mem0 v5 paired source authority is missing")
            source_sha256, created_at = source
            if not hmac.compare_digest(source_sha256, record.source_sha256):
                raise ManagedRunError("managed Mem0 v5 paired source authority differs")
            evidence.append(
                GoldBlindEvidence(
                    item_id=record.record_id,
                    text=record.memory,
                    rank=rank,
                    created_at=created_at,
                )
            )
        return tuple(evidence)


def _require_search_request(
    *, corpus_id: object, query: object, top_k: object, cutoff: object
) -> None:
    if (
        type(corpus_id) is not str  # noqa: E721 - exact public input required
        or not corpus_id
        or corpus_id != corpus_id.strip()
        or type(query) is not str  # noqa: E721
        or not query
        or query != query.strip()
        or type(top_k) is not int  # noqa: E721
        or not 1 <= top_k <= 200
        or type(cutoff) is not int  # noqa: E721
        or not 1 <= cutoff <= top_k
    ):
        raise ManagedRunError("managed Mem0 v5 paired search request is invalid")


__all__ = ("ManagedMem0V5PairedEvidenceProjector",)
