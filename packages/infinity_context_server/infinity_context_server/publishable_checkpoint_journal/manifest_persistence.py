"""Streaming verification for the persisted manifest-authority projection."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import final

from infinity_context_server.publishable_checkpoint_journal.domain import (
    CHECKPOINT_JOURNAL_SCHEMA_VERSION,
    PUBLISHABLE_CASE_COUNT,
    BackendTargetAuthority,
    CheckpointJournalError,
    ManifestCaseAuthority,
    canonical_json,
)


@final
@dataclass(frozen=True, slots=True)
class ManifestAuthorityVerification:
    case_manifest_sha256: str
    manifest_authority_commitment_sha256: str
    case_count: int
    backend_target_count: int

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManifestAuthorityVerification is final")


def verify_manifest_authority_stream(
    ordered_cases: Iterable[tuple[int, ManifestCaseAuthority]],
    backend_targets: Iterable[tuple[int, BackendTargetAuthority]],
) -> ManifestAuthorityVerification:
    """Recompute both authority commitments without materializing persisted rows."""

    case_digest = hashlib.sha256()
    case_digest.update(b'{"ordered_cases":[')
    case_ids: set[str] = set()
    case_aliases: set[str] = set()
    case_count = 0
    for ordinal, case in ordered_cases:
        if (
            not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or ordinal != case_count
            or not isinstance(case, ManifestCaseAuthority)
            or case.case_id in case_ids
            or case.case_alias in case_aliases
        ):
            raise CheckpointJournalError("checkpoint_journal_persisted_case_authority_invalid")
        if case_count:
            case_digest.update(b",")
        case_digest.update(canonical_json(case.commitment_payload()).encode("utf-8"))
        case_ids.add(case.case_id)
        case_aliases.add(case.case_alias)
        case_count += 1
    if case_count != PUBLISHABLE_CASE_COUNT:
        raise CheckpointJournalError("checkpoint_journal_persisted_case_authority_invalid")
    case_digest.update(b'],"schema_version":')
    case_digest.update(canonical_json(CHECKPOINT_JOURNAL_SCHEMA_VERSION).encode("utf-8"))
    case_digest.update(b"}")
    case_manifest_sha256 = case_digest.hexdigest()

    authority_digest = hashlib.sha256()
    authority_digest.update(b'{"backend_targets":[')
    roles: set[str] = set()
    target_ids: set[str] = set()
    target_commitments: set[str] = set()
    backend_target_count = 0
    for ordinal, target in backend_targets:
        if (
            not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or ordinal != backend_target_count
            or not isinstance(target, BackendTargetAuthority)
            or target.backend_role in roles
            or target.backend_target_id in target_ids
            or target.backend_target_commitment_sha256 in target_commitments
        ):
            raise CheckpointJournalError("checkpoint_journal_persisted_backend_authority_invalid")
        if backend_target_count:
            authority_digest.update(b",")
        authority_digest.update(canonical_json(target.commitment_payload()).encode("utf-8"))
        roles.add(target.backend_role)
        target_ids.add(target.backend_target_id)
        target_commitments.add(target.backend_target_commitment_sha256)
        backend_target_count += 1
    if backend_target_count != 2:
        raise CheckpointJournalError("checkpoint_journal_persisted_backend_authority_invalid")
    authority_digest.update(b'],"case_manifest_sha256":')
    authority_digest.update(canonical_json(case_manifest_sha256).encode("utf-8"))
    authority_digest.update(b',"schema_version":')
    authority_digest.update(canonical_json(CHECKPOINT_JOURNAL_SCHEMA_VERSION).encode("utf-8"))
    authority_digest.update(b"}")
    return ManifestAuthorityVerification(
        case_manifest_sha256=case_manifest_sha256,
        manifest_authority_commitment_sha256=authority_digest.hexdigest(),
        case_count=case_count,
        backend_target_count=backend_target_count,
    )


__all__ = ("ManifestAuthorityVerification", "verify_manifest_authority_stream")
