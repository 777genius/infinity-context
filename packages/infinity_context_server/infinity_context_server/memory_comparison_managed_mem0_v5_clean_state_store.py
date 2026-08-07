"""Crash-safe durable original clean-state witness for managed Mem0 v5."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import tempfile
import threading
from contextlib import contextmanager, suppress
from fcntl import LOCK_EX, LOCK_SH, LOCK_UN, flock
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5AuthenticatedCleanStateWitness,
    ManagedMem0V5CleanCorpusScope,
    ManagedMem0V5CleanStateWitnessIssuerPort,
    ManagedMem0V5CleanStateWitnessVerifierPort,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import canonical_sha256

_SCHEMA = "managed-mem0-v5.clean-state-original.v1"


@final
class HmacAtomicManagedMem0V5CleanStateStore:
    """Persist only authenticated primitive evidence and reissue on restore."""

    __slots__ = ("_hmac_key", "_issuer", "_lock", "_lock_path", "_path", "_verifier")

    def __init__(
        self,
        *,
        path: Path,
        hmac_key: bytes,
        issuer: ManagedMem0V5CleanStateWitnessIssuerPort,
        verifier: ManagedMem0V5CleanStateWitnessVerifierPort,
    ) -> None:
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or path.name in {"", ".", ".."}
            or type(hmac_key) is not bytes
            or len(hmac_key) < 32
            or not callable(getattr(issuer, "issue_authenticated_clean_state", None))
            or not callable(getattr(verifier, "authenticate_clean_state", None))
        ):
            raise ManagedRunError("managed Mem0 v5 clean-state store is invalid")
        self._path = path
        self._lock_path = path.with_name(f".{path.name}.lock")
        self._hmac_key = bytes(hmac_key)
        self._issuer = issuer
        self._verifier = verifier
        self._lock = threading.RLock()

    def save_original(self, witness: ManagedMem0V5AuthenticatedCleanStateWitness) -> None:
        with self._lock:
            authenticated = self._authenticate(witness)
            payload = _payload(authenticated)
            document = _signed_document(payload, self._hmac_key)
            with self._file_lock(exclusive=True):
                if self._path.exists():
                    existing = self._read_document()
                    if not hmac.compare_digest(
                        canonical_sha256(existing["payload"]), canonical_sha256(payload)
                    ):
                        raise ManagedRunError("managed Mem0 v5 clean-state original differs")
                    return
                self._atomic_write(document)

    def load_original(
        self,
        *,
        expected_admission_commitment_sha256: str,
        expected_run_id_sha256: str,
        expected_authority_commitment_sha256: str,
        expected_evidence_commitment_sha256: str,
    ) -> ManagedMem0V5AuthenticatedCleanStateWitness:
        with self._lock:
            with self._file_lock(exclusive=False):
                payload = self._read_document()["payload"]
            if (
                payload.get("admission_commitment_sha256") != expected_admission_commitment_sha256
                or payload.get("run_id_sha256") != expected_run_id_sha256
                or payload.get("authority_commitment_sha256")
                != expected_authority_commitment_sha256
                or payload.get("evidence_commitment_sha256") != expected_evidence_commitment_sha256
            ):
                raise ManagedRunError("managed Mem0 v5 clean-state original binding differs")
            try:
                scopes = tuple(ManagedMem0V5CleanCorpusScope(**item) for item in payload["scopes"])
                issued = self._issuer.issue_authenticated_clean_state(
                    admission_commitment_sha256=payload["admission_commitment_sha256"],
                    run_id_sha256=payload["run_id_sha256"],
                    authority_commitment_sha256=payload["authority_commitment_sha256"],
                    scopes=scopes,
                )
            except Exception:
                raise ManagedRunError("managed Mem0 v5 clean-state original is invalid") from None
            authenticated = self._authenticate(issued)
            if authenticated.evidence_commitment_sha256 != expected_evidence_commitment_sha256:
                raise ManagedRunError("managed Mem0 v5 clean-state original binding differs")
            return authenticated

    @contextmanager
    def _file_lock(self, *, exclusive: bool):
        parent = self._path.parent
        descriptor: int | None = None
        try:
            parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                self._lock_path,
                os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077
            ):
                raise OSError("unsafe lock file")
            flock(descriptor, LOCK_EX if exclusive else LOCK_SH)
            yield
        except OSError:
            raise ManagedRunError("managed Mem0 v5 clean-state lock failed") from None
        finally:
            if descriptor is not None:
                with suppress(OSError):
                    flock(descriptor, LOCK_UN)
                with suppress(OSError):
                    os.close(descriptor)

    def _authenticate(self, witness: object) -> ManagedMem0V5AuthenticatedCleanStateWitness:
        try:
            authenticated = self._verifier.authenticate_clean_state(witness)
        except Exception:
            raise ManagedRunError(
                "managed Mem0 v5 clean-state original is unauthenticated"
            ) from None
        if type(authenticated) is not ManagedMem0V5AuthenticatedCleanStateWitness:
            raise ManagedRunError("managed Mem0 v5 clean-state original is unauthenticated")
        authenticated.__post_init__()
        return authenticated

    def _read_document(self) -> dict[str, object]:
        try:
            raw = self._path.read_bytes()
            if not 1 <= len(raw) <= 1_000_000:
                raise ValueError
            document = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise ManagedRunError("managed Mem0 v5 clean-state original is unreadable") from None
        if type(document) is not dict or set(document) != {"schema_version", "payload", "mac"}:
            raise ManagedRunError("managed Mem0 v5 clean-state original is invalid")
        payload = document.get("payload")
        mac = document.get("mac")
        if (
            document.get("schema_version") != _SCHEMA
            or type(payload) is not dict
            or type(mac) is not str
            or not hmac.compare_digest(mac, _mac(payload, self._hmac_key))
        ):
            raise ManagedRunError("managed Mem0 v5 clean-state original authentication failed")
        return document

    def _atomic_write(self, document: dict[str, object]) -> None:
        parent = self._path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=f".{self._path.name}.", dir=parent)
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(_encode(document))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self._path)
                directory = os.open(parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except Exception:
                with suppress(OSError):
                    os.unlink(temporary)
                raise
        except OSError:
            raise ManagedRunError("managed Mem0 v5 clean-state original write failed") from None


def _payload(witness: ManagedMem0V5AuthenticatedCleanStateWitness) -> dict[str, object]:
    return {
        **witness.commitment_payload(),
        "evidence_commitment_sha256": witness.evidence_commitment_sha256,
    }


def _signed_document(payload: dict[str, object], key: bytes) -> dict[str, object]:
    return {"schema_version": _SCHEMA, "payload": payload, "mac": _mac(payload, key)}


def _mac(payload: dict[str, object], key: bytes) -> str:
    return hmac.new(key, canonical_sha256(payload).encode(), hashlib.sha256).hexdigest()


def _encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


__all__ = ("HmacAtomicManagedMem0V5CleanStateStore",)
