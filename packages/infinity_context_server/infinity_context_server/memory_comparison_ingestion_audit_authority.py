"""Run-scoped HMAC authority for private ingestion source audits."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol

from infinity_context_server.memory_comparison_ingestion_contracts import (
    IngestionManifestError,
    IngestionUnitManifest,
    private_canonical_json_bytes,
)

INGESTION_PRIVATE_AUDIT_AUTHORITY_SCHEMA_VERSION = "ingestion-private-audit-authority.v1"


@dataclass(frozen=True, slots=True)
class IngestionPrivateAuditAuthority:
    """Secret-free receipt proving one manifest's private audit for one run."""

    schema_version: str
    run_id_sha256: str
    manifest_sha256: str
    corpus_projection_sha256: str
    source_audit_sha256: str
    authority_hmac_sha256: str

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.schema_version != INGESTION_PRIVATE_AUDIT_AUTHORITY_SCHEMA_VERSION:
            raise IngestionManifestError("private audit authority schema is invalid")
        for label, value in (
            ("run_id_sha256", self.run_id_sha256),
            ("manifest_sha256", self.manifest_sha256),
            ("corpus_projection_sha256", self.corpus_projection_sha256),
            ("source_audit_sha256", self.source_audit_sha256),
            ("authority_hmac_sha256", self.authority_hmac_sha256),
        ):
            _require_sha256(label, value)

    def receipt_payload(self) -> dict[str, str]:
        """Return only secret-free authority evidence safe for an artifact."""

        return {
            "authority_hmac_sha256": self.authority_hmac_sha256,
            "corpus_projection_sha256": self.corpus_projection_sha256,
            "manifest_sha256": self.manifest_sha256,
            "run_id_sha256": self.run_id_sha256,
            "schema_version": self.schema_version,
            "source_audit_sha256": self.source_audit_sha256,
        }


class IngestionPrivateAuditSignerPort(Protocol):
    def sign(
        self,
        manifest: IngestionUnitManifest,
        *,
        run_id: str,
    ) -> IngestionPrivateAuditAuthority:
        """Issue one secret-free run-scoped private audit authority."""


class IngestionPrivateAuditAuthorityVerifierPort(Protocol):
    def verify(
        self,
        manifest: IngestionUnitManifest,
        authority: object,
        *,
        run_id: str,
    ) -> None:
        """Fail closed unless authority matches the exact manifest and run."""


class HmacIngestionPrivateAuditAuthority:
    """Process-local signer/verifier; the key is never serialized or exposed."""

    __slots__ = ("__signing_key",)

    def __init__(self, signing_key: bytes) -> None:
        if type(signing_key) is not bytes or len(signing_key) < 32:
            raise IngestionManifestError(
                "private audit signing key must be at least 32 exact bytes"
            )
        self.__signing_key = bytes(signing_key)

    def __repr__(self) -> str:
        return "HmacIngestionPrivateAuditAuthority(<redacted>)"

    def sign(
        self,
        manifest: IngestionUnitManifest,
        *,
        run_id: str,
    ) -> IngestionPrivateAuditAuthority:
        manifest = _validated_manifest(manifest)
        run_id_sha256 = _run_id_sha256(run_id)
        material = _authority_material(
            manifest=manifest,
            run_id_sha256=run_id_sha256,
        )
        return IngestionPrivateAuditAuthority(
            schema_version=INGESTION_PRIVATE_AUDIT_AUTHORITY_SCHEMA_VERSION,
            run_id_sha256=run_id_sha256,
            manifest_sha256=manifest.manifest_sha256,
            corpus_projection_sha256=manifest.corpus_projection_sha256,
            source_audit_sha256=manifest.source_audit_sha256,
            authority_hmac_sha256=hmac.new(
                self.__signing_key,
                material,
                hashlib.sha256,
            ).hexdigest(),
        )

    def verify(
        self,
        manifest: IngestionUnitManifest,
        authority: object,
        *,
        run_id: str,
    ) -> None:
        manifest = _validated_manifest(manifest)
        if type(authority) is not IngestionPrivateAuditAuthority:
            raise IngestionManifestError("private audit authority has an invalid type")
        authority.validate()
        expected = self.sign(manifest, run_id=run_id)
        if not hmac.compare_digest(
            private_canonical_json_bytes(authority.receipt_payload()),
            private_canonical_json_bytes(expected.receipt_payload()),
        ):
            raise IngestionManifestError("private audit authority verification failed")


def _validated_manifest(manifest: object) -> IngestionUnitManifest:
    if type(manifest) is not IngestionUnitManifest:
        raise IngestionManifestError("private audit authority requires an exact manifest")
    manifest.validate()
    return manifest


def _run_id_sha256(run_id: object) -> str:
    if type(run_id) is not str or not run_id.strip() or run_id != run_id.strip():
        raise IngestionManifestError("private audit run_id must be exact non-empty text")
    return hashlib.sha256(run_id.encode("utf-8")).hexdigest()


def _authority_material(
    *,
    manifest: IngestionUnitManifest,
    run_id_sha256: str,
) -> bytes:
    return private_canonical_json_bytes(
        {
            "corpus_projection_sha256": manifest.corpus_projection_sha256,
            "manifest_sha256": manifest.manifest_sha256,
            "run_id_sha256": run_id_sha256,
            "schema_version": INGESTION_PRIVATE_AUDIT_AUTHORITY_SCHEMA_VERSION,
            "source_audit_sha256": manifest.source_audit_sha256,
        }
    )


def _require_sha256(label: str, value: object) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise IngestionManifestError(f"{label} must be lowercase SHA-256")


__all__ = [
    "HmacIngestionPrivateAuditAuthority",
    "INGESTION_PRIVATE_AUDIT_AUTHORITY_SCHEMA_VERSION",
    "IngestionPrivateAuditAuthority",
    "IngestionPrivateAuditAuthorityVerifierPort",
    "IngestionPrivateAuditSignerPort",
]
