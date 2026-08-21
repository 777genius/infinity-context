"""Fail-closed port for LongMemEval original pair identity authority."""

from __future__ import annotations

from typing import Protocol

LONGMEMEVAL_OMITTED_ORIGINAL_PAIR_IDENTITY_ROOT_SHA256 = (
    "752cca9263addd0ec16eb9fcf10e7898d8c88774437767c4e8f7f2ccc327007d"
)


class OriginalPairIdentityAuthorityPort(Protocol):
    """Authenticated mapping retained before normalized ingestion drops invalid slots."""

    @property
    def profile_id(self) -> str: ...

    @property
    def dataset_sha256(self) -> str: ...

    @property
    def operation_count(self) -> int: ...

    @property
    def original_pair_slot_count(self) -> int: ...

    @property
    def omitted_source_identity_count(self) -> int: ...

    @property
    def omitted_source_identity_root_sha256(self) -> str: ...

    @property
    def omitted_original_pair_identity_root_sha256(self) -> str: ...

    @property
    def original_pair_slot_root_sha256(self) -> str: ...

    @property
    def ordered_mapping_root_sha256(self) -> str: ...

    @property
    def terminal_commitment_sha256(self) -> str: ...

    def lookup(
        self,
        *,
        sequence: int,
        corpus_id: str,
        normalized_source_id: str,
    ) -> str | None: ...


__all__ = (
    "LONGMEMEVAL_OMITTED_ORIGINAL_PAIR_IDENTITY_ROOT_SHA256",
    "OriginalPairIdentityAuthorityPort",
)
