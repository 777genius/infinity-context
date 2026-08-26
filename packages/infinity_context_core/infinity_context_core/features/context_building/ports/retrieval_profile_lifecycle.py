"""Provider-neutral ports for one durable Retrieval profile lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from infinity_context_core.features.context_building.domain.retrieval_profile_lifecycle import (
    ProfileActivationEvidence,
    ProfileAttestationLease,
    ProfileCoverageAttestation,
    RetrievalProfileIdentity,
)


@dataclass(frozen=True, slots=True)
class InstalledReleaseIdentity:
    """Deterministic identity of the repository release executing the lifecycle."""

    service_revision: str
    source_tree_digest_sha256: str
    installed_distribution_digest_sha256: str
    runtime_modules_digest_sha256: str

    def __post_init__(self) -> None:
        if len(self.service_revision) != 40 or any(
            character not in "0123456789abcdef" for character in self.service_revision
        ):
            raise ValueError("Installed release revision must be Git SHA hex")
        for name in (
            "source_tree_digest_sha256",
            "installed_distribution_digest_sha256",
            "runtime_modules_digest_sha256",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or len(value) != 71
                or not value.startswith("sha256:")
                or any(character not in "0123456789abcdef" for character in value[7:])
            ):
                raise ValueError(f"Installed release {name} must be a SHA-256 identity")

    def payload(self) -> dict[str, str]:
        return {
            "installed_distribution_digest_sha256": (self.installed_distribution_digest_sha256),
            "runtime_modules_digest_sha256": self.runtime_modules_digest_sha256,
            "service_revision": self.service_revision,
            "source_tree_digest_sha256": self.source_tree_digest_sha256,
        }

    def digest(self) -> str:
        import hashlib
        import json

        encoded = json.dumps(
            {"release": self.payload(), "schema": "infinity-context.release-identity.v1"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def unrecoverable(cls) -> InstalledReleaseIdentity:
        return cls("0" * 40, *("sha256:" + "0" * 64 for _ in range(3)))


@dataclass(frozen=True, slots=True)
class CanonicalProjectionItem:
    canonical_identity: str
    canonical_version: int
    canonical_watermark: int
    payload_digest: str
    space_id: str
    memory_scope_id: str
    thread_id: str | None
    text: str
    vector_metadata: tuple[tuple[str, object], ...]

    def __post_init__(self) -> None:
        for name in ("canonical_identity", "space_id", "memory_scope_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"Canonical projection {name} must be non-empty")
        if (
            not isinstance(self.canonical_version, int)
            or isinstance(self.canonical_version, bool)
            or not 1 <= self.canonical_version <= 9_007_199_254_740_991
        ):
            raise ValueError("Canonical projection version is invalid")
        if (
            not isinstance(self.canonical_watermark, int)
            or isinstance(self.canonical_watermark, bool)
            or self.canonical_watermark < 0
        ):
            raise ValueError("Canonical projection watermark is invalid")
        if (
            not isinstance(self.payload_digest, str)
            or len(self.payload_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.payload_digest)
        ):
            raise ValueError("Canonical projection payload digest is invalid")
        if self.thread_id is not None and (
            not isinstance(self.thread_id, str) or not self.thread_id
        ):
            raise ValueError("Canonical projection thread_id is invalid")
        if not isinstance(self.text, str):
            raise ValueError("Canonical projection text must be a string")
        if not isinstance(self.vector_metadata, tuple) or not all(
            isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str) and item[0]
            for item in self.vector_metadata
        ):
            raise ValueError("Canonical projection metadata must be immutable pairs")
        keys = tuple(item[0] for item in self.vector_metadata)
        if len(set(keys)) != len(keys):
            raise ValueError("Canonical projection metadata keys must be unique")


@dataclass(frozen=True, slots=True)
class CanonicalProjectionPage:
    items: tuple[CanonicalProjectionItem, ...]
    next_cursor: str | None
    canonical_watermark: int

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple) or not all(
            isinstance(item, CanonicalProjectionItem) for item in self.items
        ):
            raise ValueError("Canonical projection page items must be immutable")
        if self.next_cursor is not None and (
            not isinstance(self.next_cursor, str) or not self.next_cursor
        ):
            raise ValueError("Canonical projection page cursor is invalid")
        if (
            not isinstance(self.canonical_watermark, int)
            or isinstance(self.canonical_watermark, bool)
            or self.canonical_watermark < 0
        ):
            raise ValueError("Canonical projection page watermark is invalid")


@dataclass(frozen=True, slots=True)
class ProfileAttestationCheckpoint:
    cursor: str | None
    item_count: int
    digest_accumulator: str
    complete: bool
    scan_complete: bool
    scan_page_count: int
    validation_cursor: str | None
    validation_page_number: int
    validation_item_count: int
    validation_accumulator: str
    provider_epoch: int = 0


@dataclass(frozen=True, slots=True)
class ProfileReconciliationOperation:
    operation_id: str
    profile_id: str
    predecessor_lease_id: str | None
    predecessor_generation: str
    predecessor_evidence_digest: str | None
    predecessor_lease_issued_at: datetime | None
    predecessor_lease_expires_at: datetime | None
    predecessor_drifted: bool
    runtime_instance_id: str | None = None
    runtime_generation: str | None = None
    lifecycle_identity_sha256: str | None = None


class ProfileReconciliationWriteOutcome(StrEnum):
    """Truthful result of the canonical reconciliation compare-and-swap."""

    APPLIED = "applied"
    IDEMPOTENT_REPLAY = "idempotent_replay"
    STALE = "stale"
    CONFLICT = "conflict"
    # Source compatibility for callers written against the incomplete checkpoint.
    REPLAYED = "idempotent_replay"


@dataclass(frozen=True, slots=True)
class ExactVersionDeletionProof:
    """Provider observation proving one exact projected generation is absent."""

    canonical_ids: tuple[str, ...]
    canonical_version: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.canonical_ids, tuple)
            or not self.canonical_ids
            or not all(isinstance(item, str) and item for item in self.canonical_ids)
            or len(set(self.canonical_ids)) != len(self.canonical_ids)
        ):
            raise ValueError("Exact deletion proof identities are invalid")
        if (
            not isinstance(self.canonical_version, int)
            or isinstance(self.canonical_version, bool)
            or not 1 <= self.canonical_version <= 9_007_199_254_740_991
        ):
            raise ValueError("Exact deletion proof version is invalid")


@dataclass(frozen=True, slots=True)
class ProfileTombstoneDeleteAuthorization:
    """Canonical authorization binding lifecycle and projected generations."""

    identity: RetrievalProfileIdentity
    canonical_version: int
    delete_canonical_version: int

    def __post_init__(self) -> None:
        for name in ("canonical_version", "delete_canonical_version"):
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 1 <= value <= 9_007_199_254_740_991
            ):
                raise ValueError(f"Profile tombstone {name} is invalid")


@dataclass(frozen=True, slots=True)
class ProfileAttestationPageReceipt:
    page_number: int
    start_cursor: str | None
    end_cursor: str | None
    item_count: int
    byte_count: int
    page_digest: str


@dataclass(frozen=True, slots=True)
class RuntimeFenceOwner:
    """One process incarnation; generations are never reused after restart."""

    instance_id: str
    generation: str
    supervisor_key_id: str
    supervisor_public_key: str
    trust_root_sha256: str
    trust_registry_generation: int
    launch_token: str
    process_pid: int
    process_birth_identity: str
    executable_identity: str
    executable_sha256: str
    installed_release: InstalledReleaseIdentity
    launch_signature: str

    def __post_init__(self) -> None:
        for name in (
            "instance_id",
            "generation",
            "supervisor_key_id",
            "launch_token",
            "process_birth_identity",
            "executable_identity",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"Runtime fence owner {name} must be normalized")
            if len(value) > (512 if name == "executable_identity" else 120):
                raise ValueError(f"Runtime fence owner {name} is too long")
        if (
            not isinstance(self.process_pid, int)
            or isinstance(self.process_pid, bool)
            or self.process_pid < 1
        ):
            raise ValueError("Runtime fence owner process_pid must be positive")
        if (
            not isinstance(self.supervisor_public_key, str)
            or len(self.supervisor_public_key) != 64
            or any(character not in "0123456789abcdef" for character in self.supervisor_public_key)
        ):
            raise ValueError("Runtime fence owner supervisor public key must be Ed25519 hex")
        if (
            not isinstance(self.trust_root_sha256, str)
            or len(self.trust_root_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.trust_root_sha256)
        ):
            raise ValueError("Runtime fence owner trust root must be SHA-256 hex")
        if (
            not isinstance(self.trust_registry_generation, int)
            or isinstance(self.trust_registry_generation, bool)
            or self.trust_registry_generation < 0
        ):
            raise ValueError("Runtime fence owner trust registry generation is invalid")
        if (
            not isinstance(self.executable_sha256, str)
            or len(self.executable_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.executable_sha256)
        ):
            raise ValueError("Runtime fence owner executable digest must be SHA-256 hex")
        if not isinstance(self.launch_signature, str) or len(self.launch_signature) > 120:
            raise ValueError("Runtime fence owner launch signature is invalid")
        if not isinstance(self.installed_release, InstalledReleaseIdentity):
            raise ValueError("Runtime fence owner installed release identity is invalid")

    def launch_payload(self) -> bytes:
        """Canonical supervisor-signed launch identity persisted at first admission."""

        import json

        return json.dumps(
            {
                "executable_identity": self.executable_identity,
                "executable_sha256": self.executable_sha256,
                "generation": self.generation,
                "instance_id": self.instance_id,
                "launch_token": self.launch_token,
                "release_identity": self.installed_release.payload(),
                "release_identity_sha256": self.installed_release.digest(),
                "process_birth_identity": self.process_birth_identity,
                "process_pid": self.process_pid,
                "schema": "retrieval-runtime-launch.v3",
                "supervisor_key_id": self.supervisor_key_id,
                "supervisor_public_key": self.supervisor_public_key,
                "trust_registry_generation": self.trust_registry_generation,
                "trust_root_sha256": self.trust_root_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def lifecycle_identity_payload(
        self,
        *,
        sealed_proof_id: str | None = None,
        sealed_proof_sha256: str | None = None,
    ) -> dict[str, object]:
        """One versioned identity contract for lifecycle proofs and receipts."""

        import hashlib

        if (sealed_proof_id is None) != (sealed_proof_sha256 is None):
            raise ValueError("Lifecycle sealed proof identity must be complete")
        if sealed_proof_sha256 is not None and (
            len(sealed_proof_sha256) != 64
            or any(character not in "0123456789abcdef" for character in sealed_proof_sha256)
        ):
            raise ValueError("Lifecycle sealed proof digest is invalid")
        return {
            "schema_version": "retrieval-lifecycle-proof-identity.v1",
            "runtime_instance_id": self.instance_id,
            "runtime_generation": self.generation,
            "launch_identity_sha256": hashlib.sha256(self.launch_payload()).hexdigest(),
            "process_identity": {
                "pid": self.process_pid,
                "birth_identity": self.process_birth_identity,
                "executable_identity": self.executable_identity,
                "executable_sha256": self.executable_sha256,
            },
            "trust_identity": {
                "supervisor_key_id": self.supervisor_key_id,
                "registry_generation": self.trust_registry_generation,
                "root_sha256": self.trust_root_sha256,
            },
            "installed_release_identity": self.installed_release.payload(),
            "installed_release_identity_sha256": self.installed_release.digest(),
            "sealed_proof_identity": (
                None
                if sealed_proof_id is None
                else {"proof_id": sealed_proof_id, "proof_sha256": sealed_proof_sha256}
            ),
        }

    def lifecycle_identity_sha256(
        self,
        *,
        sealed_proof_id: str | None = None,
        sealed_proof_sha256: str | None = None,
    ) -> str:
        import hashlib
        import json

        payload = self.lifecycle_identity_payload(
            sealed_proof_id=sealed_proof_id,
            sealed_proof_sha256=sealed_proof_sha256,
        )
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @classmethod
    def unrecoverable_current(
        cls, *, instance_id: str, generation: str, key_id: str = "unrecoverable-in-process"
    ) -> RuntimeFenceOwner:
        """Create a process-bound owner that intentionally has no death authority."""

        import hashlib
        import os
        from uuid import uuid4

        pid = os.getpid()
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as stream:
                stat = stream.read()
            birth = stat[stat.rfind(")") + 2 :].split()[19]
            executable = os.path.realpath(f"/proc/{pid}/exe")
            with open(f"/proc/{pid}/exe", "rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
        except (OSError, IndexError) as exc:
            raise RuntimeError("retrieval_profile_runtime_identity_unavailable") from exc
        return cls(
            instance_id,
            generation,
            key_id,
            "0" * 64,
            "0" * 64,
            0,
            f"unrecoverable-launch-{uuid4().hex}",
            pid,
            birth,
            executable,
            digest,
            InstalledReleaseIdentity.unrecoverable(),
            "",
        )

    @classmethod
    def from_launch_identity_json(cls, value: str) -> RuntimeFenceOwner:
        """Load the exact external supervisor-issued launch identity."""

        import json

        try:
            decoded = json.loads(value)
            if not isinstance(decoded, dict) or set(decoded) != {
                "instance_id",
                "generation",
                "supervisor_key_id",
                "supervisor_public_key",
                "trust_root_sha256",
                "trust_registry_generation",
                "launch_token",
                "process_pid",
                "process_birth_identity",
                "executable_identity",
                "executable_sha256",
                "installed_release",
                "launch_signature",
            }:
                raise ValueError
            decoded["installed_release"] = InstalledReleaseIdentity(**decoded["installed_release"])
            return cls(**decoded)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("retrieval_profile_runtime_launch_invalid") from exc

    def assert_current_process(self) -> None:
        """Reject an owner copied from a different or PID-reused process."""

        import hashlib
        import os

        if os.getpid() != self.process_pid:
            raise RuntimeError("retrieval_profile_runtime_process_mismatch")
        proc = f"/proc/{self.process_pid}"
        try:
            with open(f"{proc}/stat", encoding="utf-8") as stream:
                stat = stream.read()
            birth = stat[stat.rfind(")") + 2 :].split()[19]
            executable = os.path.realpath(f"{proc}/exe")
            with open(f"{proc}/exe", "rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
        except (OSError, IndexError) as exc:
            raise RuntimeError("retrieval_profile_runtime_identity_unavailable") from exc
        if (
            birth != self.process_birth_identity
            or executable != self.executable_identity
            or digest != self.executable_sha256
        ):
            raise RuntimeError("retrieval_profile_runtime_process_mismatch")


class ProfileQueryAdmissionStatus(StrEnum):
    NO_PROFILE = "no_profile"
    ADMITTED = "admitted"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ProfileQueryAdmission:
    status: ProfileQueryAdmissionStatus
    identity: RetrievalProfileIdentity | None = None
    activation_lease_id: str | None = None

    def __post_init__(self) -> None:
        admitted = self.status is ProfileQueryAdmissionStatus.ADMITTED
        if admitted != (self.identity is not None and self.activation_lease_id is not None):
            raise ValueError("Profile query admission payload does not match its status")
        if not admitted and (self.identity is not None or self.activation_lease_id is not None):
            raise ValueError("Non-admitted profile query cannot carry a target")


class RetrievalProfileRegistryPort(Protocol):
    async def create_building(
        self, identity: RetrievalProfileIdentity, *, now: datetime
    ) -> None: ...

    async def building(self) -> RetrievalProfileIdentity | None: ...

    async def routable(self) -> tuple[RetrievalProfileIdentity, ...]: ...

    async def promotable(self, profile_id: str) -> RetrievalProfileIdentity | None: ...

    async def backfill_cursor(self, profile_id: str) -> str | None: ...

    async def backfill_complete(self, profile_id: str) -> bool: ...

    async def record_projection(
        self,
        profile_id: str,
        items: tuple[CanonicalProjectionItem, ...],
        *,
        projected_at: datetime,
    ) -> None: ...

    async def authorize_tombstone(
        self, profile_id: str, chunk_id: str, *, canonical_version: int
    ) -> ProfileTombstoneDeleteAuthorization | None: ...

    async def complete_tombstone(
        self,
        profile_id: str,
        chunk_id: str,
        *,
        canonical_version: int,
        delete_canonical_version: int,
        completed_at: datetime,
    ) -> bool: ...

    async def checkpoint_backfill(
        self,
        profile_id: str,
        *,
        previous_cursor: str | None,
        cursor: str | None,
        watermark: int,
        complete: bool,
        now: datetime,
    ) -> None: ...

    async def coverage(
        self,
        profile_id: str,
        *,
        reconciliation_operation: ProfileReconciliationOperation | None = None,
        runtime_owner: RuntimeFenceOwner | None = None,
    ) -> ProfileCoverageAttestation: ...

    async def activation_evidence(
        self,
        profile_id: str,
        *,
        now: datetime,
        reconciliation_operation: ProfileReconciliationOperation | None = None,
        runtime_owner: RuntimeFenceOwner | None = None,
    ) -> ProfileActivationEvidence: ...

    async def issue_activation_lease(
        self,
        profile_id: str,
        evidence: ProfileActivationEvidence,
        *,
        lease_id: str,
        now: datetime,
        expires_at: datetime,
        mutation_epoch: int = 0,
    ) -> ProfileAttestationLease: ...

    async def activate(
        self,
        lease: ProfileAttestationLease,
        evidence: ProfileActivationEvidence,
        *,
        now: datetime,
        maximum_queue_lag: timedelta,
        maximum_retained: int,
        runtime_owner: RuntimeFenceOwner | None = None,
    ) -> tuple[str, ...]: ...

    async def active_lease(self, *, now: datetime) -> ProfileAttestationLease | None: ...

    async def register_runtime_incarnation(
        self, owner: RuntimeFenceOwner, *, now: datetime
    ) -> None:
        """Register the exact process generation before lifecycle work begins."""
        ...

    async def verify_registered_runtime_owner(self, owner: RuntimeFenceOwner) -> None:
        """Verify an exact existing runtime incarnation without registering it."""
        ...

    async def retire_runtime_incarnation(
        self, owner: RuntimeFenceOwner, *, now: datetime
    ) -> None: ...

    async def consumed_transition_profile(self, lease_id: str) -> str | None: ...

    async def attestation_checkpoint(
        self, profile_id: str, operation_id: str
    ) -> ProfileAttestationCheckpoint | None: ...

    async def attestation_page_receipt(
        self, profile_id: str, operation_id: str, page_number: int
    ) -> ProfileAttestationPageReceipt | None: ...

    async def checkpoint_attestation(
        self,
        profile_id: str,
        operation_id: str,
        *,
        previous_cursor: str | None,
        cursor: str | None,
        item_count: int,
        digest_accumulator: str,
        started_at: datetime,
        deadline_at: datetime,
        now: datetime,
        complete: bool,
        scan_complete: bool = False,
        page_receipt: ProfileAttestationPageReceipt | None = None,
        validation_cursor: str | None = None,
        validation_page_number: int = 0,
        validation_item_count: int = 0,
        validation_accumulator: str = "0" * 64,
        provider_epoch: int = 0,
        owner_operation_id: str | None = None,
        reconciliation_operation: ProfileReconciliationOperation | None = None,
        runtime_owner: RuntimeFenceOwner | None = None,
    ) -> ProfileReconciliationWriteOutcome: ...

    async def record_reconciliation(
        self,
        profile_id: str,
        evidence: ProfileActivationEvidence,
        *,
        operation: ProfileReconciliationOperation,
        runtime_owner: RuntimeFenceOwner | None,
        now: datetime,
        expires_at: datetime,
        drifted: bool,
        mutation_epoch: int = 0,
    ) -> ProfileReconciliationWriteOutcome: ...

    async def reconciliation_operation(
        self,
        profile_id: str,
        *,
        runtime_owner: RuntimeFenceOwner | None = None,
    ) -> ProfileReconciliationOperation: ...

    async def mark_reconciliation_drift(
        self,
        profile_id: str,
        *,
        operation: ProfileReconciliationOperation,
        runtime_owner: RuntimeFenceOwner,
        now: datetime,
    ) -> ProfileReconciliationWriteOutcome: ...

    async def provider_attestation_epoch(self, profile_id: str, *, now: datetime) -> int: ...

    async def begin_provider_mutation(
        self,
        profile_id: str,
        operation_id: str,
        *,
        owner: RuntimeFenceOwner,
        now: datetime,
        expires_at: datetime,
    ) -> int: ...

    async def finish_provider_mutation(
        self,
        profile_id: str,
        operation_id: str,
        *,
        owner: RuntimeFenceOwner,
        started_epoch: int | None = None,
        now: datetime,
    ) -> int: ...

    async def heartbeat_provider_mutation(
        self,
        profile_id: str,
        operation_id: str,
        *,
        owner: RuntimeFenceOwner,
        started_epoch: int,
        now: datetime,
        expires_at: datetime,
    ) -> None: ...

    async def begin_profile_query(
        self,
        operation_id: str,
        *,
        owner: RuntimeFenceOwner,
        now: datetime,
        expires_at: datetime,
    ) -> ProfileQueryAdmission: ...

    async def finish_profile_query(
        self,
        profile_id: str,
        operation_id: str,
        *,
        owner: RuntimeFenceOwner,
        activation_lease_id: str,
    ) -> None: ...


class CanonicalProjectionSourcePort(Protocol):
    async def page_eligible(self, *, after: str | None, limit: int) -> CanonicalProjectionPage: ...


class RetrievalProfileProjectionPort(Protocol):
    async def prepare_profile(self, identity: RetrievalProfileIdentity) -> None: ...

    async def upsert_profile(
        self, identity: RetrievalProfileIdentity, items: tuple[CanonicalProjectionItem, ...]
    ) -> None: ...

    async def delete_profile_if_version(
        self,
        identity: RetrievalProfileIdentity,
        canonical_ids: tuple[str, ...],
        *,
        canonical_version: int,
    ) -> ExactVersionDeletionProof:
        """Prove points carrying the exact stale canonical version are absent."""

    async def attestation_epoch(
        self, identity: RetrievalProfileIdentity, *, now: datetime
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class ProfileCleanup:
    identity: RetrievalProfileIdentity
    phase: str
    attempt_count: int
    last_error_code: str | None


@dataclass(frozen=True, slots=True)
class ProfileCollectionDeleteAuthorization:
    identity: RetrievalProfileIdentity
    delete_token: str
    provider_epoch: int

    def __post_init__(self) -> None:
        if not self.delete_token or self.provider_epoch < 1:
            raise ValueError("Profile collection delete authorization is invalid")


class RetrievalProfileRetirementPort(Protocol):
    async def rollback(
        self, profile_id: str, *, now: datetime, maximum_retained: int
    ) -> tuple[str, ...]: ...

    async def retire(
        self, profile_id: str, *, now: datetime, maximum_retained: int
    ) -> tuple[str, ...]: ...

    async def request_cleanup(self, profile_id: str, *, now: datetime) -> ProfileCleanup: ...

    async def cleanup(self, profile_id: str) -> ProfileCleanup: ...

    async def cleanup_candidates(self, *, limit: int) -> tuple[str, ...]: ...

    async def reconcile_retained_profiles(
        self, *, now: datetime, maximum_retained: int
    ) -> tuple[str, ...]: ...

    async def authorize_collection_delete(
        self, profile_id: str, *, now: datetime
    ) -> ProfileCollectionDeleteAuthorization | None: ...

    async def mark_collection_deleted(
        self,
        authorization: ProfileCollectionDeleteAuthorization,
        *,
        now: datetime,
    ) -> None: ...

    async def cleanup_postgres(self, profile_id: str, *, now: datetime) -> None: ...

    async def complete_cleanup(self, profile_id: str, *, now: datetime) -> None: ...

    async def record_cleanup_failure(
        self, profile_id: str, *, error_code: str, now: datetime
    ) -> None: ...


class RetrievalProfileCollectionCleanupPort(Protocol):
    async def delete_profile(self, authorization: ProfileCollectionDeleteAuthorization) -> None: ...

    async def delete_profile_if_version(
        self,
        identity: RetrievalProfileIdentity,
        canonical_ids: tuple[str, ...],
        *,
        canonical_version: int,
    ) -> None: ...

    async def attestation_page(
        self,
        identity: RetrievalProfileIdentity,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[tuple[str, int, str], ...], str | None]: ...


class RetrievalProfileDiagnosticsPort(Protocol):
    def record(self, profile_id: str, event: str, value: int | float = 1) -> None: ...


__all__ = (
    "CanonicalProjectionItem",
    "CanonicalProjectionPage",
    "CanonicalProjectionSourcePort",
    "ExactVersionDeletionProof",
    "ProfileAttestationCheckpoint",
    "ProfileAttestationPageReceipt",
    "ProfileReconciliationOperation",
    "InstalledReleaseIdentity",
    "ProfileCleanup",
    "ProfileCollectionDeleteAuthorization",
    "ProfileTombstoneDeleteAuthorization",
    "RetrievalProfileCollectionCleanupPort",
    "RetrievalProfileDiagnosticsPort",
    "RetrievalProfileProjectionPort",
    "RetrievalProfileRegistryPort",
    "RetrievalProfileRetirementPort",
)
