"""Authenticated sealed Infinity retrieval for the fixed fresh-chain case."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from infinity_context_server.publishable_durable_scheduler import (
    official_authority_integrity,
    official_authority_sqlite_files,
    retrieval_evidence_sqlite_authority,
    retrieval_evidence_sqlite_schema,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    LOCOMO_PROFILE,
    SchedulerBenchmark,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerCaseAuthority,
    case_manifest_sha256,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SchedulerOfficialCaseRunScope,
    SchedulerRetrievalBackendScope,
    SchedulerRetrievalEvidenceAuthorityPage,
    SchedulerRetrievalEvidenceAuthorityRow,
    SchedulerRetrievalRunScope,
)
from infinity_context_server.publishable_durable_scheduler.runner_official_request_renderer import (
    SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
    SchedulerRetrievalEvidenceKey,
    official_case_material_sha256,
)

from .contracts import FreshChainCanaryError

SQLiteSchedulerRetrievalEvidenceReader = (
    retrieval_evidence_sqlite_authority.SQLiteSchedulerRetrievalEvidenceReader
)
SQLiteSchedulerRetrievalEvidenceAuthorityBuilder = (
    retrieval_evidence_sqlite_authority.SQLiteSchedulerRetrievalEvidenceAuthorityBuilder
)


@final
@dataclass(slots=True, repr=False)
class SealedFreshChainInfinityRetrieval:
    """Lazily read one authenticated Infinity result from the canonical store."""

    reader: SQLiteSchedulerRetrievalEvidenceReader = field(repr=False)
    key: SchedulerRetrievalEvidenceKey
    _memories: tuple[RetrievedMemory, ...] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.reader) is not SQLiteSchedulerRetrievalEvidenceReader
            or type(self.key) is not SchedulerRetrievalEvidenceKey
            or self.key.backend_index != 0
            or self.key.backend_role != "infinity-context"
            or self.key.authority_root_sha256 != self.reader.authority_root_sha256
        ):
            _fail("fresh_chain_infinity_retrieval_composition_invalid")

    def retrieve(self) -> tuple[RetrievedMemory, ...]:
        if self._memories is None:
            evidence = self.reader.read_exact(key=self.key)
            if evidence.key != self.key or not evidence.memories:
                _fail("fresh_chain_infinity_retrieval_evidence_invalid")
            self._memories = evidence.memories
        return self._memories

    def close(self) -> None:
        self.reader.close()


def open_sealed_fresh_chain_infinity_retrieval(
    *,
    database_path: Path,
    authentication_key: bytes,
    retrieval_authority_root_sha256: str | None,
    case: PublicBenchmarkCase,
    case_alias: str,
    expected_run_id: str,
) -> SealedFreshChainInfinityRetrieval:
    """Open the genuine sealed reader and bind its exact fixed-case lookup."""

    reader = _open_from_authenticated_configuration(
        database_path,
        authentication_key=authentication_key,
        authority_root_sha256=retrieval_authority_root_sha256,
    )
    try:
        scopes = reader._scopes
        if (
            type(scopes) is not tuple
            or not scopes
            or type(scopes[0]) is not SchedulerRetrievalRunScope
            or scopes[0].case_scope.run_id != expected_run_id
        ):
            _fail("fresh_chain_infinity_retrieval_scope_invalid")
        scope = scopes[0]
        case_key = scope.case_scope.case_key(
            case_index=0,
            case_id=case.case_id,
            case_alias=case_alias,
            authority_root_sha256=reader._case_root,
        )
        key = SchedulerRetrievalEvidenceKey(
            case_key=case_key,
            case_material_sha256=official_case_material_sha256(case_key, case),
            backend_index=0,
            backend_role=scope.backends[0].backend_role,
            target_identity_sha256=scope.backends[0].target_identity_sha256,
            cutoff=SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
            authority_root_sha256=retrieval_authority_root_sha256,
        )
        if SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS != 4096:
            _fail("fresh_chain_evaluation_token_policy_invalid")
        return SealedFreshChainInfinityRetrieval(reader=reader, key=key)
    except BaseException:
        reader.close()
        raise


def _open_from_authenticated_configuration(
    path: Path,
    *,
    authentication_key: bytes,
    authority_root_sha256: str | None,
) -> SQLiteSchedulerRetrievalEvidenceReader:
    expected = (
        None
        if authority_root_sha256 is None
        else official_authority_integrity.require_digest(
            authority_root_sha256,
            code="scheduler_retrieval_evidence_authority_root_invalid",
        )
    )
    authenticator = official_authority_integrity.SchedulerOfficialAuthorityAuthenticator(
        authentication_key,
        kind=retrieval_evidence_sqlite_schema.KIND,
    )
    handle = official_authority_sqlite_files.open_secure_authority_sqlite(path, readonly=True)
    try:
        official_authority_integrity.validate_schema(
            handle.connection,
            retrieval_evidence_sqlite_schema.SCHEMA,
        )
        raw, configuration_sha256, terminal = retrieval_evidence_sqlite_schema.verify_meta(
            handle.connection,
            authenticator,
            expected_configuration=None,
        )
        if terminal is None or (
            expected is not None and terminal.authority_root_sha256 != expected
        ):
            _fail("fresh_chain_infinity_retrieval_root_invalid")
        scopes, case_root = retrieval_evidence_sqlite_schema.scopes_from_configuration(raw)
        reader = SQLiteSchedulerRetrievalEvidenceReader(
            handle,
            authenticator,
            scopes,
            case_root,
            configuration_sha256,
            terminal,
        )
        retrieval_evidence_sqlite_authority._verify_retrieval_state(
            reader,
            require_complete=True,
            terminal=terminal,
        )
        handle.freeze_identity()
        return reader
    except BaseException:
        handle.close(validate=False)
        raise


def prepare_sealed_fresh_chain_infinity_retrieval(
    *,
    database_path: Path,
    authentication_key: bytes,
    case: PublicBenchmarkCase,
    case_alias: str,
    run_id: str,
    infinity_target_identity_sha256: str,
    mem0_target_identity_sha256: str,
    infinity_memories: tuple[RetrievedMemory, ...],
) -> str:
    """Seal exactly one Infinity result plus an empty structural Mem0 pair."""

    digest = official_authority_integrity.authority_digest
    suite = digest("fresh-chain/suite", {"case_id": case.case_id, "run_id": run_id})
    case_scope = SchedulerOfficialCaseRunScope(
        suite_authority_sha256=suite,
        run_authority_sha256=digest("fresh-chain/run", {"suite": suite}),
        run_binding_commitment_sha256=digest("fresh-chain/binding", {"suite": suite}),
        run_id=run_id,
        benchmark=SchedulerBenchmark.LOCOMO,
        scheduler_profile_id=LOCOMO_PROFILE.profile_id,
        publishable_profile_id=PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
        publishable_profile_sha256=PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
        methodology_sha256=digest("fresh-chain/methodology", {"publishable": False}),
        dataset_sha256=digest("fresh-chain/dataset", {"case_id": case.case_id}),
        case_manifest_sha256=case_manifest_sha256(
            (SchedulerCaseAuthority(case_id=case.case_id, case_alias=case_alias),)
        ),
        case_count=1,
    )
    scope = SchedulerRetrievalRunScope(
        case_scope=case_scope,
        backends=(
            SchedulerRetrievalBackendScope(0, "infinity-context", infinity_target_identity_sha256),
            SchedulerRetrievalBackendScope(1, "mem0", mem0_target_identity_sha256),
        ),
    )
    case_root = digest(
        "fresh-chain/case-authority", {"case": case_scope.material(), "case_alias": case_alias}
    )
    builder_arguments = {
        "run_scopes": (scope,),
        "case_authority_root_sha256": case_root,
        "authentication_key": authentication_key,
    }
    builder = (
        SQLiteSchedulerRetrievalEvidenceAuthorityBuilder.open(database_path, **builder_arguments)
        if database_path.exists()
        else SQLiteSchedulerRetrievalEvidenceAuthorityBuilder.create(
            database_path, **builder_arguments
        )
    )
    try:
        case_key = case_scope.case_key(
            case_index=0,
            case_id=case.case_id,
            case_alias=case_alias,
            authority_root_sha256=case_root,
        )
        material = official_case_material_sha256(case_key, case)
        builder.append_page(
            SchedulerRetrievalEvidenceAuthorityPage(
                0,
                (
                    SchedulerRetrievalEvidenceAuthorityRow(
                        case_key, material, 0, infinity_memories
                    ),
                    SchedulerRetrievalEvidenceAuthorityRow(case_key, material, 1, ()),
                ),
            )
        )
        return builder.finalize().authority_root_sha256
    finally:
        builder.close()


def _fail(code: str) -> None:
    raise FreshChainCanaryError(code) from None


__all__ = (
    "SealedFreshChainInfinityRetrieval",
    "open_sealed_fresh_chain_infinity_retrieval",
    "prepare_sealed_fresh_chain_infinity_retrieval",
)
