"""Atomic nine-secret snapshot for managed-v5 live activation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    ManagedMem0V5CredentialCapabilities,
    ManagedMem0V5CredentialPaths,
    _validate_text_secret,
    read_managed_mem0_v5_private_secret,
    wipe_managed_mem0_v5_private_secret,
)


class ManagedV5LiveSecretSnapshotError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(slots=True, repr=False)
class ManagedV5RecoverySecretMaterial:
    credentials: ManagedMem0V5CredentialCapabilities
    operation_signer_secret: bytearray
    durable_clean_state_secret: bytearray
    checkpoint_head_secret: bytearray

    def close(self) -> None:
        try:
            self.credentials.close()
        finally:
            for value in (
                self.operation_signer_secret,
                self.durable_clean_state_secret,
                self.checkpoint_head_secret,
            ):
                wipe_managed_mem0_v5_private_secret(value)
                value.clear()


def load_recovery_distinct_secrets(
    *,
    filesystem: object,
    credential_paths: ManagedMem0V5CredentialPaths,
    recovery_secret_sha256: str,
) -> ManagedV5RecoverySecretMaterial:
    expected_paths = (
        filesystem.ingress_bearer_file,
        filesystem.evidence_key_file,
        filesystem.receipt_secret_file,
        filesystem.checkpoint_signing_key_file,
        filesystem.checkpoint_head_key_file,
    )
    peer_paths = (
        filesystem.operation_journal_signer_secret_file,
        filesystem.durable_clean_state_hmac_secret_file,
        filesystem.runtime_attestation_secret_file,
        filesystem.recovery_hmac_secret_file,
    )
    if (
        credential_paths.values() != expected_paths
        or len(set(expected_paths + peer_paths)) != 9
        or not _sha(recovery_secret_sha256)
    ):
        _fail("secret_paths_crosswired")
    loaded = []
    try:
        loaded = [read_managed_mem0_v5_private_secret(path) for path in expected_paths + peer_paths]
        commitments = tuple(hashlib.sha256(item.value).digest() for item in loaded)
        if len({item.identity for item in loaded}) != 9 or len(set(commitments)) != 9:
            _fail("secret_reused")
        if commitments[7].hex() != filesystem.runtime_attestation_secret_sha256:
            _fail("runtime_attestation_secret_changed")
        if commitments[8].hex() != recovery_secret_sha256:
            _fail("recovery_secret_changed")
        _validate_text_secret(loaded[0].value)
        _validate_text_secret(loaded[2].value)
        return ManagedV5RecoverySecretMaterial(
            ManagedMem0V5CredentialCapabilities(tuple(item.value for item in loaded[:5])),
            bytearray(loaded[5].value),
            bytearray(loaded[6].value),
            bytearray(loaded[4].value),
        )
    except ManagedV5LiveSecretSnapshotError:
        raise
    except Exception:
        _fail("secret_invalid")
    finally:
        for item in loaded:
            wipe_managed_mem0_v5_private_secret(item.value)


def load_nine_distinct_secrets(
    *,
    filesystem: object,
    credential_paths: ManagedMem0V5CredentialPaths,
    recovery_secret_sha256: str,
) -> tuple[ManagedMem0V5CredentialCapabilities, bytes, bytes]:
    expected_paths = (
        filesystem.ingress_bearer_file,
        filesystem.evidence_key_file,
        filesystem.receipt_secret_file,
        filesystem.checkpoint_signing_key_file,
        filesystem.checkpoint_head_key_file,
    )
    peer_paths = (
        filesystem.operation_journal_signer_secret_file,
        filesystem.durable_clean_state_hmac_secret_file,
        filesystem.runtime_attestation_secret_file,
        filesystem.recovery_hmac_secret_file,
    )
    if (
        credential_paths.values() != expected_paths
        or len(set(expected_paths + peer_paths)) != 9
        or not _sha(recovery_secret_sha256)
    ):
        _fail("secret_paths_crosswired")
    loaded = []
    try:
        loaded = [read_managed_mem0_v5_private_secret(path) for path in expected_paths + peer_paths]
        if len({item.identity for item in loaded}) != 9:
            _fail("secret_reused")
        commitments = tuple(hashlib.sha256(item.value).digest() for item in loaded)
        if len(set(commitments)) != 9:
            _fail("secret_reused")
        if commitments[7].hex() != filesystem.runtime_attestation_secret_sha256:
            _fail("runtime_attestation_secret_changed")
        if commitments[8].hex() != recovery_secret_sha256:
            _fail("recovery_secret_changed")
        _validate_text_secret(loaded[0].value)
        _validate_text_secret(loaded[2].value)
        capabilities = ManagedMem0V5CredentialCapabilities(tuple(item.value for item in loaded[:5]))
        return capabilities, bytes(loaded[5].value), bytes(loaded[6].value)
    except ManagedV5LiveSecretSnapshotError:
        raise
    except Exception:
        _fail("secret_invalid")
    finally:
        for item in loaded:
            wipe_managed_mem0_v5_private_secret(item.value)


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= set("0123456789abcdef")


def _fail(code: str) -> None:
    raise ManagedV5LiveSecretSnapshotError(code)


__all__ = (
    "ManagedV5RecoverySecretMaterial",
    "ManagedV5LiveSecretSnapshotError",
    "load_nine_distinct_secrets",
    "load_recovery_distinct_secrets",
)
