"""Provider-free composition for the strict-v4 cleanup journal lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_adapters.postgres.managed_cleanup_v4_sqlite_journal import (
    JOURNAL_KEY_PURPOSE,
    CleanupJournalKeyIdentityPort,
    ManagedCleanupV4JournalError,
    SQLiteManagedCleanupV4Journal,
)
from infinity_context_core.application.use_cases.managed_cleanup_v4_lifecycle import (
    ManagedCleanupV4InitiationReceipt,
    ManagedCleanupV4TerminalReceipt,
    ManagedCleanupV4Transition,
    build_cleanup_v4_terminal_bindings,
    complete_managed_cleanup_v4,
    initiate_managed_cleanup_v4,
)
from infinity_context_core.features.projection_receipts import ProjectionReceiptAuthenticator
from infinity_context_core.ports.managed_cleanup_v3_absence import (
    ManagedCleanupV3TerminalEvidence,
)
from infinity_context_core.ports.managed_cleanup_v4_authority import (
    StrictV4CleanupAuthorityResolver,
)


@dataclass(frozen=True, slots=True)
class StrictV4CleanupRecovery:
    initiation: ManagedCleanupV4InitiationReceipt | None
    terminal: ManagedCleanupV4TerminalReceipt | None


async def initiate_strict_v4_cleanup(
    *,
    journal: SQLiteManagedCleanupV4Journal,
    key_identity_authority: CleanupJournalKeyIdentityPort,
) -> ManagedCleanupV4Transition:
    authenticator = _authenticator(journal, key_identity_authority)
    authority = await _authority(journal, authenticator)
    return await initiate_managed_cleanup_v4(
        authority=authority,
        lifecycle=journal,
        authenticator=authenticator,
        authentication_key_id=journal.authentication_key_id,
    )


async def complete_strict_v4_cleanup(
    *,
    journal: SQLiteManagedCleanupV4Journal,
    terminal_evidence: ManagedCleanupV3TerminalEvidence,
    key_identity_authority: CleanupJournalKeyIdentityPort,
) -> ManagedCleanupV4Transition:
    if type(terminal_evidence) is not ManagedCleanupV3TerminalEvidence:
        raise ManagedCleanupV4JournalError("managed_cleanup_v4_completion_evidence_invalid")
    terminal_evidence.__post_init__()
    authenticator = _authenticator(journal, key_identity_authority)
    authority = await _authority(journal, authenticator)
    if (
        terminal_evidence.context.run_id_sha256 != authority.run_id_sha256
        or terminal_evidence.context.context_sha256 != authority.context_sha256
        or terminal_evidence.authority_terminal_sha256 != authority.a2_terminal_sha256
    ):
        raise ManagedCleanupV4JournalError("managed_cleanup_v4_completion_evidence_conflict")
    terminal_bindings = build_cleanup_v4_terminal_bindings(
        inventory_terminal_sha256=terminal_evidence.inventory.terminal_sha256,
        qdrant_absence_pass_sha256=tuple(
            item.pass_sha256 for item in terminal_evidence.qdrant_passes
        ),
        graphiti_absence_pass_sha256=tuple(
            item.pass_sha256 for item in terminal_evidence.graphiti_passes
        ),
        cognee_evidence_sha256=terminal_evidence.context.cognee_policy_sha256,
        context_sha256=terminal_evidence.context.context_sha256,
        a2_terminal_sha256=terminal_evidence.authority_terminal_sha256,
    )
    return await complete_managed_cleanup_v4(
        authority=authority,
        terminal_bindings=terminal_bindings,
        lifecycle=journal,
        authenticator=authenticator,
        authentication_key_id=journal.authentication_key_id,
    )


async def recover_strict_v4_cleanup(
    *,
    journal: SQLiteManagedCleanupV4Journal,
    key_identity_authority: CleanupJournalKeyIdentityPort,
) -> StrictV4CleanupRecovery:
    authenticator = _authenticator(journal, key_identity_authority)
    authority = await _authority(journal, authenticator)
    initiation = await journal.read_initiation(authority.run_id_sha256)
    terminal = await journal.read_terminal(authority.run_id_sha256)
    if terminal is not None and initiation is None:
        raise ManagedCleanupV4JournalError("managed_cleanup_v4_journal_recovery_order_invalid")
    if initiation is not None:
        replay = await initiate_managed_cleanup_v4(
            authority=authority,
            lifecycle=journal,
            authenticator=authenticator,
            authentication_key_id=journal.authentication_key_id,
        )
        if not replay.replayed:
            raise ManagedCleanupV4JournalError("managed_cleanup_v4_journal_recovery_invalid")
    if terminal is not None:
        replay = await complete_managed_cleanup_v4(
            authority=authority,
            terminal_bindings=terminal.terminal_bindings,
            lifecycle=journal,
            authenticator=authenticator,
            authentication_key_id=journal.authentication_key_id,
        )
        if not replay.replayed:
            raise ManagedCleanupV4JournalError("managed_cleanup_v4_journal_recovery_invalid")
    return StrictV4CleanupRecovery(initiation=initiation, terminal=terminal)


async def _authority(
    journal: SQLiteManagedCleanupV4Journal,
    authenticator: ProjectionReceiptAuthenticator,
):
    return await StrictV4CleanupAuthorityResolver(
        run_id_sha256=journal.run_id_sha256,
        reader=journal,
        authenticator=authenticator,
        authentication_key_id=journal.authentication_key_id,
    ).resolve()


def _authenticator(
    journal: SQLiteManagedCleanupV4Journal,
    keys: CleanupJournalKeyIdentityPort,
) -> ProjectionReceiptAuthenticator:
    value = keys.resolve(
        purpose=JOURNAL_KEY_PURPOSE,
        key_id=journal.authentication_key_id,
    )
    if type(value) is not bytes or len(value) < 32:
        raise ManagedCleanupV4JournalError("managed_cleanup_v4_journal_key_invalid")
    return ProjectionReceiptAuthenticator(value)


__all__ = (
    "StrictV4CleanupRecovery",
    "complete_strict_v4_cleanup",
    "initiate_strict_v4_cleanup",
    "recover_strict_v4_cleanup",
)
