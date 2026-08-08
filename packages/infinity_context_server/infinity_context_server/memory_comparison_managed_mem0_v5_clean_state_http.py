"""Managed clean-state adapters over the single hardened Mem0 v5 HTTP port."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_store import (
    HmacAtomicManagedMem0V5CleanStateStore,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5AuthenticatedCleanStateWitness,
    ManagedMem0V5CleanCorpusScope,
    ManagedMem0V5CleanStateSnapshotPort,
    ManagedMem0V5CleanStateWitnessIssuerPort,
    ManagedMem0V5CleanStateWitnessVerifierPort,
    ManagedMem0V5DurableCleanStatePort,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5CleanStateRequest,
    Mem0V5CleanStateScope,
    Mem0V5HttpError,
    Mem0V5HttpPort,
    mem0_v5_canonical_request_size,
)

_ERROR = "managed Mem0 v5 clean-state HTTP evidence is invalid"


class ManagedMem0V5SecretCapability(Protocol):
    def validate(self) -> None: ...

    def consume(self) -> bytes: ...


class ManagedMem0V5CleanStateLanePort(Protocol):
    def clean_state(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
        scopes: tuple[Mem0V5CleanStateScope, ...],
    ) -> tuple[Mem0V5CleanStateScope, ...]: ...


@final
class ManagedMem0V5HttpCleanStateSnapshotFactory:
    """Create one lazy snapshot over the already-composed authenticated lane."""

    __slots__ = ("_used",)

    def __init__(self) -> None:
        self._used = False

    def create_snapshot_port(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
        witness_issuer: ManagedMem0V5CleanStateWitnessIssuerPort,
        runtime_binding_port: ManagedMem0V5CleanStateLanePort,
    ) -> ManagedMem0V5CleanStateSnapshotPort:
        if (
            self._used
            or type(authority) is not ManagedMem0V5ManifestAuthority
            or type(admission) is not Mem0OssFullRunAdmission
            or admission.ingestion_manifest_sha256 != authority.ingestion_manifest_sha256
            or admission.ingestion_root_sha256 != authority.ingestion_root_sha256
            or admission.ingestion_unit_count != authority.operation_count
            or not callable(getattr(witness_issuer, "issue_authenticated_clean_state", None))
            or not callable(getattr(runtime_binding_port, "clean_state", None))
        ):
            raise ManagedRunError(_ERROR)
        preflight_managed_mem0_v5_clean_state_request(authority=authority, admission=admission)
        self._used = True
        return _LazyManagedMem0V5CleanStateSnapshot(
            authority=authority,
            admission=admission,
            witness_issuer=witness_issuer,
            lane=runtime_binding_port,
        )


@final
class _LazyManagedMem0V5CleanStateSnapshot(ManagedMem0V5CleanStateSnapshotPort):
    __slots__ = ("_admission", "_authority", "_issuer", "_lane", "_used")

    def __init__(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
        witness_issuer: ManagedMem0V5CleanStateWitnessIssuerPort,
        lane: ManagedMem0V5CleanStateLanePort,
    ) -> None:
        self._authority = authority
        self._admission = admission
        self._issuer = witness_issuer
        self._lane = lane
        self._used = False

    def binding_commitment_sha256(self) -> str:
        return canonical_sha256(
            {
                "kind": "managed-mem0-v5-clean-state-snapshot.v1",
                "authority_commitment_sha256": self._authority.authority_commitment_sha256,
                "admission_commitment_sha256": self._admission.commitment_sha256,
                "issuer_identity": id(self._issuer),
                "lane_identity": id(self._lane),
            }
        )

    def prove_empty_scopes(
        self,
        *,
        expected_admission_commitment_sha256: str,
        expected_run_id_sha256: str,
        expected_authority_commitment_sha256: str,
        expected_scopes: tuple[ManagedMem0V5CleanCorpusScope, ...],
    ) -> ManagedMem0V5AuthenticatedCleanStateWitness:
        if self._used:
            raise ManagedRunError(_ERROR)
        authority = self._authority
        admission = self._admission
        exact_scopes = _expected_scopes(authority, admission.commitment_sha256)
        if (
            expected_admission_commitment_sha256 != admission.commitment_sha256
            or expected_run_id_sha256
            != hashlib.sha256(admission.request.run_id.encode()).hexdigest()
            or expected_authority_commitment_sha256 != authority.authority_commitment_sha256
            or expected_scopes != exact_scopes
        ):
            raise ManagedRunError(_ERROR)
        self._used = True
        try:
            verified = self._lane.clean_state(
                authority=authority,
                admission=admission,
                scopes=_http_scopes(exact_scopes),
            )
        except Exception:
            raise ManagedRunError(_ERROR) from None
        if verified != _http_scopes(exact_scopes):
            raise ManagedRunError(_ERROR)
        return self._issuer.issue_authenticated_clean_state(
            admission_commitment_sha256=expected_admission_commitment_sha256,
            run_id_sha256=expected_run_id_sha256,
            authority_commitment_sha256=expected_authority_commitment_sha256,
            scopes=expected_scopes,
        )


@final
class ManagedMem0V5HmacDurableCleanStateFactory:
    __slots__ = ("_hmac_key", "_path", "_used")

    def __init__(self, *, path: Path, hmac_key_capability: ManagedMem0V5SecretCapability) -> None:
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or path.name in {"", ".", ".."}
            or not callable(getattr(hmac_key_capability, "validate", None))
            or not callable(getattr(hmac_key_capability, "consume", None))
        ):
            raise ManagedRunError(_ERROR)
        self._path = path
        self._hmac_key = hmac_key_capability
        self._used = False

    def create_durable_port(
        self,
        *,
        witness_issuer: ManagedMem0V5CleanStateWitnessIssuerPort,
        witness_verifier: ManagedMem0V5CleanStateWitnessVerifierPort,
    ) -> ManagedMem0V5DurableCleanStatePort:
        if (
            self._used
            or not callable(getattr(witness_issuer, "issue_authenticated_clean_state", None))
            or not callable(getattr(witness_verifier, "authenticate_clean_state", None))
        ):
            raise ManagedRunError(_ERROR)
        try:
            self._hmac_key.validate()
        except Exception:
            raise ManagedRunError(_ERROR) from None
        self._used = True
        try:
            key = self._hmac_key.consume()
        except Exception:
            raise ManagedRunError(_ERROR) from None
        if type(key) is not bytes or not 32 <= len(key) <= 4_096:  # noqa: E721
            raise ManagedRunError(_ERROR)
        return HmacAtomicManagedMem0V5CleanStateStore(
            path=self._path,
            hmac_key=key,
            issuer=witness_issuer,
            verifier=witness_verifier,
        )


def preflight_managed_mem0_v5_clean_state_request(
    *,
    authority: ManagedMem0V5ManifestAuthority,
    admission: Mem0OssFullRunAdmission,
) -> int:
    """Enforce the exact 64KB wire cap before any credential is consumed."""

    try:
        request = Mem0V5CleanStateRequest(
            admission.commitment_sha256,
            hashlib.sha256(admission.request.run_id.encode()).hexdigest(),
            authority.authority_commitment_sha256,
            authority.case_count,
            admission.request.credential_binding_sha256,
            admission.request.runtime_source_revision,
            admission.request.runtime_source_sha256,
            admission.request.runtime_base_sha256,
            "0" * 64,
            _http_scopes(_expected_scopes(authority, admission.commitment_sha256)),
            canonical_sha256({"kind": "clean-state", "binding": admission.commitment_sha256}),
        )
        return mem0_v5_canonical_request_size(request.body())
    except (ManagedRunError, Mem0V5HttpError):
        raise ManagedRunError(_ERROR) from None


def managed_mem0_v5_clean_state_request(
    *,
    authority: ManagedMem0V5ManifestAuthority,
    admission: Mem0OssFullRunAdmission,
    runtime_binding_commitment_sha256: str,
    scopes: tuple[Mem0V5CleanStateScope, ...],
) -> Mem0V5CleanStateRequest:
    return Mem0V5CleanStateRequest(
        admission.commitment_sha256,
        hashlib.sha256(admission.request.run_id.encode()).hexdigest(),
        authority.authority_commitment_sha256,
        authority.case_count,
        admission.request.credential_binding_sha256,
        admission.request.runtime_source_revision,
        admission.request.runtime_source_sha256,
        admission.request.runtime_base_sha256,
        runtime_binding_commitment_sha256,
        scopes,
        canonical_sha256({"kind": "clean-state", "binding": admission.commitment_sha256}),
    )


def execute_managed_mem0_v5_clean_state(
    *,
    authority: ManagedMem0V5ManifestAuthority,
    admission: Mem0OssFullRunAdmission,
    scopes: tuple[Mem0V5CleanStateScope, ...],
    admitted_runtime_binding: tuple[str, str] | None,
    control: Mem0V5HttpPort,
    verifier: object,
) -> tuple[Mem0V5CleanStateScope, ...]:
    if (
        admitted_runtime_binding is None
        or admitted_runtime_binding[0] != admission.commitment_sha256
    ):
        raise ManagedRunError(_ERROR)
    request = managed_mem0_v5_clean_state_request(
        authority=authority,
        admission=admission,
        runtime_binding_commitment_sha256=admitted_runtime_binding[1],
        scopes=scopes,
    )
    receipt = control.clean_state(request)
    return verifier.verify_clean_state(
        receipt=receipt,
        request=request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
    )


def _http_scopes(
    scopes: tuple[ManagedMem0V5CleanCorpusScope, ...],
) -> tuple[Mem0V5CleanStateScope, ...]:
    return tuple(Mem0V5CleanStateScope(**item.payload()) for item in scopes)


def _expected_scopes(
    authority: ManagedMem0V5ManifestAuthority,
    admission_commitment_sha256: str,
) -> tuple[ManagedMem0V5CleanCorpusScope, ...]:
    grouped: dict[str, list[object]] = {}
    for unit in authority.units:
        grouped.setdefault(unit.corpus_id, []).append(unit)
    return tuple(
        ManagedMem0V5CleanCorpusScope(
            canonical_sha256({"corpus_id": corpus_id}),
            canonical_sha256(
                {
                    "admission_commitment_sha256": admission_commitment_sha256,
                    "corpus_id": corpus_id,
                    "source_scope_root_sha256": canonical_sha256(
                        {
                            "source_scopes": [
                                {
                                    "source_id": unit.source_id,
                                    "source_sha256": unit.source_sha256,
                                }
                                for unit in units
                            ]
                        }
                    ),
                }
            ),
            len(units),
            0,
            hashlib.sha256(b"").hexdigest(),
        )
        for corpus_id, units in grouped.items()
    )


__all__ = (
    "ManagedMem0V5HmacDurableCleanStateFactory",
    "ManagedMem0V5HttpCleanStateSnapshotFactory",
    "execute_managed_mem0_v5_clean_state",
    "managed_mem0_v5_clean_state_request",
    "preflight_managed_mem0_v5_clean_state_request",
)
