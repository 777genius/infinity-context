"""Composition root for provider-free authenticated evidence services."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mem0_oss_adapter_v5.clean_state import AuthenticatedCleanStateService
from mem0_oss_adapter_v5.evidence_service import (
    AuthenticatedEvidenceService,
    ManifestEvidenceContext,
    OperationStorageAuthority,
)
from mem0_oss_adapter_v5.extraction_contract import ExtractionRequest
from mem0_oss_adapter_v5.mem0_storage import Mem0EvidenceStorage, Mem0StorageBackend
from mem0_oss_adapter_v5.request_binding import RequestBindingService
from mem0_oss_adapter_v5.sealed_manifest import InputUnit, SealedInputManifest
from mem0_oss_adapter_v5.state_sqlite import OperationRecord, SqliteOperationState


class V5EvidenceComposition:
    """Owns lazy evidence collaborators without growing run orchestration."""

    def __init__(
        self,
        *,
        manifest: SealedInputManifest,
        state: SqliteOperationState,
        backend: Callable[[], Mem0StorageBackend],
        current_admission: Callable[[], str | None],
        operation_id: Callable[[InputUnit], str],
        extraction_request: Callable[[InputUnit], ExtractionRequest],
        storage_authority: Callable[[InputUnit, OperationRecord], OperationStorageAuthority],
        runtime_binding_commitment_sha256: str,
        runtime_source_sha256: str,
        evidence_directory: Path,
        hmac_key: bytes,
    ) -> None:
        self._manifest = manifest
        self._state = state
        self._backend = backend
        self._current_admission = current_admission
        self._operation_id = operation_id
        self._extraction_request = extraction_request
        self._storage_authority = storage_authority
        self._runtime_binding = runtime_binding_commitment_sha256
        self._runtime_source = runtime_source_sha256
        self._evidence_directory = evidence_directory
        self._hmac_key = hmac_key
        self._storage: AuthenticatedEvidenceService | None = None
        self._request: RequestBindingService | None = None
        self._clean: AuthenticatedCleanStateService | None = None

    @property
    def storage(self) -> AuthenticatedEvidenceService:
        if self._storage is None:
            self._storage = AuthenticatedEvidenceService(
                context=ManifestEvidenceContext(
                    manifest=self._manifest,
                    state=self._state,
                    admission=self._current_admission,
                    operation_id=self._operation_id,
                    storage_authority=self._storage_authority,
                ),
                storage=Mem0EvidenceStorage(self._backend()),
                hmac_key=self._hmac_key,
            )
        return self._storage

    @property
    def request(self) -> RequestBindingService:
        if self._request is None:
            self._request = RequestBindingService(
                manifest=self._manifest,
                state=self._state,
                extraction_request=self._extraction_request,
                operation_id=self._operation_id,
                result_hmac_key=self._hmac_key,
            )
        return self._request

    @property
    def clean(self) -> AuthenticatedCleanStateService:
        if self._clean is None:
            self._clean = AuthenticatedCleanStateService(
                manifest=self._manifest,
                state=self._state,
                backend=self._backend(),
                current_admission=self._current_admission,
                runtime_binding_commitment_sha256=self._runtime_binding,
                runtime_source_sha256=self._runtime_source,
                evidence_directory=self._evidence_directory,
                hmac_key=self._hmac_key,
            )
        return self._clean


__all__ = ("V5EvidenceComposition",)
