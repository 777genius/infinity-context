"""Server-owned adapter for exact Mem0-v5 cleanup verification context."""

from __future__ import annotations

from typing import Protocol, final

from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    CleanupVerificationContext,
    Mem0OssFullRunAdmission,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5HttpError
from infinity_context_server.memory_comparison_mem0_oss_v5_run import (
    Mem0OssFullRunService,
    Mem0OssRunSeal,
)


class ManagedMem0V5CleanupBindingPort(Protocol):
    def cleanup_context(
        self,
        *,
        admission: Mem0OssFullRunAdmission,
        seal: Mem0OssRunSeal | None,
        aborting: bool,
    ) -> CleanupVerificationContext: ...


@final
class ManagedMem0V5ServiceCleanupBinding:
    """Derive cleanup request fields only from the live authenticated run service."""

    __slots__ = ("_service",)

    def __init__(self, *, service: Mem0OssFullRunService) -> None:
        if type(service) is not Mem0OssFullRunService:
            raise Mem0V5HttpError("mem0_v5_managed_cleanup_binding_invalid")
        self._service = service

    def cleanup_context(
        self,
        *,
        admission: Mem0OssFullRunAdmission,
        seal: Mem0OssRunSeal | None,
        aborting: bool,
    ) -> CleanupVerificationContext:
        if (
            type(admission) is not Mem0OssFullRunAdmission
            or admission != self._service.admission
            or type(aborting) is not bool
            or (aborting and seal is not None)
            or (not aborting and seal != self._service.seal_evidence)
        ):
            raise Mem0V5HttpError("mem0_v5_managed_cleanup_binding_invalid")
        try:
            context = self._service.cleanup_verification_context(aborting=aborting)
        except Exception:
            raise Mem0V5HttpError("mem0_v5_managed_cleanup_binding_invalid") from None
        if (
            context.admission_commitment_sha256 != admission.commitment_sha256
            or context.seal_commitment_sha256 != (None if seal is None else seal.commitment_sha256)
            or context.operation_root_sha256
            != (None if seal is None else seal.operation_root_sha256)
            or context.expected_operation_count != admission.request.expected_operation_count
            or context.aborting is not aborting
        ):
            raise Mem0V5HttpError("mem0_v5_managed_cleanup_binding_invalid")
        return context


__all__ = ("ManagedMem0V5CleanupBindingPort", "ManagedMem0V5ServiceCleanupBinding")
