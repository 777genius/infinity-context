"""Synthetic input authority and exact operation identities for the hosting E2E."""

from __future__ import annotations

import hashlib
import importlib
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .canonical import atomic_private_write, canonical_bytes, canonical_sha256, require_digest

LOGICAL_RUNTIME_ROUTE = "http://127.0.0.1:8890/v1"
ROUTE_SHA256 = hashlib.sha256(LOGICAL_RUNTIME_ROUTE.encode("utf-8")).hexdigest()
TRANSPORT_ORIGIN = "http://127.0.0.1:8891"
PINNED_STATELESS_BASE_SHA256 = "5c15d6c502d380282a933d4f20a886a06c9d04d3b5d7c918b95df0b0acf33671"
SYNTHETIC_OUTPUT = (
    '{"memory":[{"id":"0","text":"Alice likes tea.",'
    '"attributed_to":"user","linked_memory_ids":[]}]}'
)
_CONTAINER_RUNTIME_UID = 65532
_CONTAINER_RUNTIME_GID = 65532
_MAX_IDENTITY = 2**31 - 1


@dataclass(frozen=True, slots=True)
class RuntimeOwnership:
    """Attested rootless bind ownership, separate from the container identity."""

    host_mapped_uid: int
    host_mapped_gid: int
    container_runtime_uid: int
    container_runtime_gid: int

    def __post_init__(self) -> None:
        values = (
            self.host_mapped_uid,
            self.host_mapped_gid,
            self.container_runtime_uid,
            self.container_runtime_gid,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_IDENTITY
            for value in values
        ):
            raise ValueError("e2e_runtime_identity_invalid")
        if (
            self.container_runtime_uid != _CONTAINER_RUNTIME_UID
            or self.container_runtime_gid != _CONTAINER_RUNTIME_GID
        ):
            raise ValueError("e2e_container_runtime_identity_invalid")
        if (
            self.host_mapped_uid == self.container_runtime_uid
            or self.host_mapped_gid == self.container_runtime_gid
        ):
            raise ValueError("e2e_rootless_identity_conflated")

    def attest_caller(self) -> None:
        if os.geteuid() != self.host_mapped_uid or os.getegid() != self.host_mapped_gid:
            raise ValueError("e2e_host_mapped_owner_mismatch")

    def attest_created_tree(self, root: Path) -> None:
        paths = (root, *root.rglob("*"))
        for path in paths:
            try:
                metadata = os.lstat(path)
            except OSError:
                raise ValueError("e2e_host_mapped_owner_invalid") from None
            if metadata.st_uid != self.host_mapped_uid or metadata.st_gid != self.host_mapped_gid:
                raise ValueError("e2e_host_mapped_owner_invalid")

    def public_attestation(self) -> dict[str, int]:
        return {
            "host_mapped_uid": self.host_mapped_uid,
            "host_mapped_gid": self.host_mapped_gid,
            "container_runtime_uid": self.container_runtime_uid,
            "container_runtime_gid": self.container_runtime_gid,
        }


class RequestProjector(Protocol):
    def project(self, unit: SyntheticUnit, *, current_date: str) -> RequestProjection: ...


@dataclass(frozen=True, slots=True)
class RequestProjection:
    request_body_sha256: str
    response_format_sha256: str
    response_schema_sha256: str


@dataclass(frozen=True, slots=True)
class SyntheticUnit:
    sequence: int
    corpus_id: str
    source_id: str
    observation_date: str
    source_messages: tuple[dict[str, str], ...]
    unit_identity_sha256: str
    unit_sha256: str
    scope_sha256: str

    @classmethod
    def one(cls) -> SyntheticUnit:
        messages = ({"role": "user", "content": "Alice likes tea."},)
        unit_sha = canonical_sha256({"source_messages": list(messages)})
        corpus = "provider-free-e2e-corpus"
        source = "provider-free-e2e-source"
        scope_sha = canonical_sha256(
            {"corpus_id": corpus, "source_id": source, "unit_sha256": unit_sha}
        )
        identity = canonical_sha256(
            {"sequence": 0, "scope_sha256": scope_sha, "unit_sha256": unit_sha}
        )
        return cls(0, corpus, source, "2024-03-10", messages, identity, unit_sha, scope_sha)


class PinnedRequestProjector:
    """Delegates only request projection to the pinned adapter extraction contract."""

    def project(self, unit: SyntheticUnit, *, current_date: str) -> RequestProjection:
        module = importlib.import_module("mem0_oss_adapter_v5.extraction_contract")
        request = module.build_extraction_request(
            source_messages=unit.source_messages,
            current_date=current_date,
            timestamp=unit.observation_date,
        )
        return RequestProjection(
            request_body_sha256=require_digest(
                request.request_body_sha256, "e2e_request_projection_invalid"
            ),
            response_format_sha256=require_digest(
                module.EXTRACTION_RESPONSE_FORMAT_SHA256, "e2e_request_projection_invalid"
            ),
            response_schema_sha256=require_digest(
                module.EXTRACTION_SCHEMA_SHA256, "e2e_request_projection_invalid"
            ),
        )


@dataclass(frozen=True, slots=True)
class RunFixture:
    current_date: str
    unit: SyntheticUnit
    ingestion_manifest_sha256: str
    ingestion_root_sha256: str
    admission_commitment_sha256: str
    operation_id_sha256: str
    request_body_sha256: str
    response_format_sha256: str
    response_schema_sha256: str
    account_binding_hmac_sha256: str
    base_instructions_sha256: str

    @classmethod
    def create(cls, projector: RequestProjector) -> RunFixture:
        current_date = "2026-08-06"
        unit = SyntheticUnit.one()
        public = {
            "units": [
                {
                    "unit_identity_sha256": unit.unit_identity_sha256,
                    "unit_sha256": unit.unit_sha256,
                    "scope_sha256": unit.scope_sha256,
                }
            ]
        }
        ingestion_root = canonical_sha256(public)
        ingestion_manifest = canonical_sha256(
            {"current_date": current_date, "ingestion_root_sha256": ingestion_root}
        )
        admission = canonical_sha256(
            {
                "expected_operation_count": 1,
                "ingestion_manifest_sha256": ingestion_manifest,
                "ingestion_root_sha256": ingestion_root,
                "route_sha256": ROUTE_SHA256,
            }
        )
        operation = canonical_sha256(
            {
                "admission_commitment_sha256": admission,
                "unit_index": 0,
                "unit_identity_sha256": unit.unit_identity_sha256,
            }
        )
        projection = projector.project(unit, current_date=current_date)
        return cls(
            current_date=current_date,
            unit=unit,
            ingestion_manifest_sha256=ingestion_manifest,
            ingestion_root_sha256=ingestion_root,
            admission_commitment_sha256=admission,
            operation_id_sha256=operation,
            request_body_sha256=projection.request_body_sha256,
            response_format_sha256=projection.response_format_sha256,
            response_schema_sha256=projection.response_schema_sha256,
            account_binding_hmac_sha256=canonical_sha256("provider-free-e2e-account"),
            base_instructions_sha256=PINNED_STATELESS_BASE_SHA256,
        )

    def manifest(self) -> dict[str, object]:
        unsigned = {
            "schema_version": "mem0-oss-adapter-v5.sealed-input.v1",
            "ingestion_manifest_sha256": self.ingestion_manifest_sha256,
            "ingestion_root_sha256": self.ingestion_root_sha256,
            "current_date": self.current_date,
            "units": [
                {
                    "sequence": self.unit.sequence,
                    "unit_identity_sha256": self.unit.unit_identity_sha256,
                    "unit_sha256": self.unit.unit_sha256,
                    "scope_sha256": self.unit.scope_sha256,
                    "corpus_id": self.unit.corpus_id,
                    "source_id": self.unit.source_id,
                    "observation_date": self.unit.observation_date,
                    "source_messages": list(self.unit.source_messages),
                }
            ],
        }
        return {**unsigned, "sealed_payload_sha256": canonical_sha256(unsigned)}

    def dispatch_body(self) -> dict[str, object]:
        return {
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "operation_id_sha256": self.operation_id_sha256,
            "unit_identity_sha256": self.unit.unit_identity_sha256,
            "unit_sha256": self.unit.unit_sha256,
            "scope_sha256": self.unit.scope_sha256,
            "request_body_sha256": self.request_body_sha256,
            "sequence": self.unit.sequence,
        }

    def materialize(
        self, run_root: Path, *, ownership: RuntimeOwnership | None = None
    ) -> dict[str, str]:
        """Create only private run inputs; authorities remain external and immutable."""

        if not run_root.is_absolute() or run_root.exists() or run_root.is_symlink():
            raise ValueError("e2e_run_root_invalid")
        if ownership is not None:
            if not isinstance(ownership, RuntimeOwnership):
                raise TypeError("e2e_runtime_ownership_invalid")
            ownership.attest_caller()
        run_root.mkdir(parents=True, mode=0o700)
        directories = {
            name: run_root / name for name in ("input", "state", "secrets", "fake-runtime")
        }
        for path in directories.values():
            path.mkdir(mode=0o700)
        (directories["state"] / "e2e-mem0-config").mkdir(mode=0o700)
        generated = {
            "ingress-bearer": secrets.token_hex(32),
            "state-hmac": secrets.token_hex(32),
            "result-hmac": secrets.token_hex(32),
            "runtime-attestation-secret": secrets.token_hex(32),
            "runtime-bearer": secrets.token_hex(32),
            "runtime-receipt-secret": secrets.token_hex(32),
            "runtime-transport-origin": TRANSPORT_ORIGIN,
            "account-binding-hmac-sha256": self.account_binding_hmac_sha256,
            "base-instructions-sha256": self.base_instructions_sha256,
        }
        attestation_secret = generated["runtime-attestation-secret"]
        if any(
            value == attestation_secret
            for name, value in generated.items()
            if name != "runtime-attestation-secret"
        ):
            raise ValueError("e2e_runtime_attestation_secret_not_distinct")
        atomic_private_write(
            directories["input"] / "manifest.json",
            canonical_bytes(self.manifest()),
            mode=0o400,
        )
        for name, value in generated.items():
            atomic_private_write(directories["secrets"] / name, value.encode(), mode=0o600)
        if ownership is not None:
            ownership.attest_created_tree(run_root)
        return {name: str(path) for name, path in directories.items()}

    def idempotency_key(self, action: str) -> str:
        return canonical_sha256(
            {
                "action": action,
                "admission_commitment_sha256": self.admission_commitment_sha256,
            }
        )
