"""Subprocess crash fixture for the SQLite checkpoint journal tests."""

from __future__ import annotations

import textwrap
from pathlib import Path


def crash_script(database_path: Path, fault_point: str) -> str:
    return textwrap.dedent(
        f"""
        import os
        from hashlib import sha256
        from pathlib import Path

        from infinity_context_server.publishable_checkpoint_journal.crypto import (
            HmacSha256JournalSigner,
        )
        from infinity_context_server.publishable_checkpoint_journal.domain import (
            BackendTargetAuthority,
            CallStage,
            LogicalCallIdentity,
            ManifestAuthority,
            ManifestCaseAuthority,
            PublishableEvaluationManifest,
            PublishableRunIdentity,
            RuntimeReceipt,
            VerifiedRuntimeReceipt,
        )
        from infinity_context_server.publishable_checkpoint_journal.service import (
            NullExternalLifecycle,
            PublishableCheckpointJournalService,
        )
        from infinity_context_server.publishable_checkpoint_journal.sqlite_adapter import (
            SQLiteCheckpointJournal,
        )


        def digest(value):
            return sha256(value.encode()).hexdigest()


        class Verifier:
            def verify(self, *, identity, receipt):
                return VerifiedRuntimeReceipt(
                    receipt=receipt,
                    verifier_key_id="receipt-verifier-1",
                    verification_commitment_sha256=digest("verification"),
                )


        authority = ManifestAuthority(
            ordered_cases=tuple(
                ManifestCaseAuthority(
                    case_id=f"case-{{ordinal}}",
                    case_alias=f"alias-{{ordinal}}",
                )
                for ordinal in range(1540)
            ),
            backend_targets=(
                BackendTargetAuthority(
                    backend_role="backend-0",
                    backend_target_id="target-0",
                    backend_target_commitment_sha256=digest("target-0"),
                ),
                BackendTargetAuthority(
                    backend_role="backend-1",
                    backend_target_id="target-1",
                    backend_target_commitment_sha256=digest("target-1"),
                ),
            ),
        )
        answers = tuple(
            LogicalCallIdentity(
                run_id="run-1",
                case_id=f"case-{{ordinal // 2}}",
                case_alias=f"alias-{{ordinal // 2}}",
                backend_role=f"backend-{{ordinal % 2}}",
                backend_target_id=f"target-{{ordinal % 2}}",
                backend_target_commitment_sha256=digest(f"target-{{ordinal % 2}}"),
                stage=CallStage.ANSWER,
                ordinal=ordinal,
            )
            for ordinal in range(3080)
        )
        judges = tuple(
            LogicalCallIdentity(
                run_id="run-1",
                case_id=answer.case_id,
                case_alias=answer.case_alias,
                backend_role=answer.backend_role,
                backend_target_id=answer.backend_target_id,
                backend_target_commitment_sha256=(
                    answer.backend_target_commitment_sha256
                ),
                stage=CallStage.JUDGE,
                ordinal=3080 + answer.ordinal,
                depends_on_logical_call_id=answer.logical_call_id,
            )
            for answer in answers
        )
        manifest = PublishableEvaluationManifest(
            authority=authority,
            calls=answers + judges,
        )
        run = PublishableRunIdentity(
            run_id="run-1",
            profile_id="profile-1",
            profile_commitment_sha256=digest("profile"),
            dataset_commitment_sha256=digest("dataset"),
            methodology_commitment_sha256=digest("methodology"),
            source_commit_sha256=digest("source"),
            runtime_pin_sha256=digest("runtime-pin"),
            case_manifest_sha256=manifest.case_manifest_sha256,
            manifest_authority_commitment_sha256=(
                manifest.manifest_authority_commitment_sha256
            ),
            evaluation_manifest_commitment_sha256=manifest.commitment_sha256,
            signer_key_id="journal-key-1",
        )
        database_path = Path({str(database_path)!r})
        journal = SQLiteCheckpointJournal(
            database_path,
            private_directory=database_path.parent,
        )
        service = PublishableCheckpointJournalService(
            journal=journal,
            signer=HmacSha256JournalSigner(
                key_id="journal-key-1",
                secret=b"journal-secret",
            ),
            receipt_verifier=Verifier(),
            external_lifecycle=NullExternalLifecycle(),
        )
        call = manifest.calls[0]
        service.initialize(run, manifest)
        service.reserve(call, request_commitment_sha256=digest("request-0"))
        if {fault_point!r} != "reserved":
            service.mark_dispatched(call)
        if {fault_point!r} == "committed":
            service.commit(
                call,
                RuntimeReceipt(
                    run_id=call.run_id,
                    logical_call_id=call.logical_call_id,
                    provider_receipt_id="receipt-0",
                    request_commitment_sha256=digest("request-0"),
                    result_commitment_sha256=digest("result-0"),
                ),
            )
        os._exit(0)
        """
    )


__all__ = ("crash_script",)
