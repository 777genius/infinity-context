"""Supervisor-owned proof capability for crashed Retrieval runtimes."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from subprocess import Popen
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from infinity_context_core.features.context_building.public import (
    InstalledReleaseIdentity,
    RuntimeFenceOwner,
)


@dataclass(frozen=True, slots=True)
class RuntimeDeathProof:
    proof_id: str
    instance_id: str
    generation: str
    supervisor_key_id: str
    trust_root_sha256: str
    trust_registry_generation: int
    launch_token: str
    process_pid: int
    process_birth_identity: str
    executable_identity: str
    executable_sha256: str
    installed_release: InstalledReleaseIdentity
    maintenance_generation: int
    exit_observation_id: str
    exited_at: datetime
    exit_code: int
    signature: str

    def payload(self) -> bytes:
        return _payload(
            proof_id=self.proof_id,
            instance_id=self.instance_id,
            generation=self.generation,
            supervisor_key_id=self.supervisor_key_id,
            trust_root_sha256=self.trust_root_sha256,
            trust_registry_generation=self.trust_registry_generation,
            launch_token=self.launch_token,
            process_pid=self.process_pid,
            process_birth_identity=self.process_birth_identity,
            executable_identity=self.executable_identity,
            executable_sha256=self.executable_sha256,
            installed_release=self.installed_release,
            maintenance_generation=self.maintenance_generation,
            exit_observation_id=self.exit_observation_id,
            exited_at=self.exited_at,
            exit_code=self.exit_code,
        )


class RuntimeProcessSupervisor:
    """Owns the signing key and observes one concrete child process lifecycle."""

    def __init__(
        self,
        *,
        key_id: str,
        process: Popen[bytes],
        trust_root_sha256: str,
        trust_registry_generation: int,
        installed_release: InstalledReleaseIdentity,
        signing_key: Ed25519PrivateKey | None = None,
        instance_id: str | None = None,
        generation: str | None = None,
    ) -> None:
        if not key_id or key_id != key_id.strip() or len(key_id) > 120:
            raise ValueError("Runtime supervisor key_id is invalid")
        self._key_id = key_id
        self._trust_root_sha256 = trust_root_sha256
        self._trust_registry_generation = trust_registry_generation
        if not isinstance(installed_release, InstalledReleaseIdentity):
            raise ValueError("Runtime supervisor installed release identity is invalid")
        self._installed_release = installed_release
        self._process = process
        self._private_key = signing_key or Ed25519PrivateKey.generate()
        self._owner = self._issue_owner(instance_id=instance_id, generation=generation)

    def owner(self) -> RuntimeFenceOwner:
        """Return the immutable supervisor-issued identity for the concrete child."""

        return self._owner

    def _issue_owner(self, *, instance_id: str | None, generation: str | None) -> RuntimeFenceOwner:
        public_key = (
            self._private_key.public_key()
            .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            .hex()
        )
        pid = int(self._process.pid)
        birth, executable, executable_sha256 = _process_identity(pid)
        values = {
            "instance_id": instance_id or f"runtime-{uuid4().hex}",
            "generation": generation or f"generation-{uuid4().hex}",
            "supervisor_key_id": self._key_id,
            "supervisor_public_key": public_key,
            "trust_root_sha256": self._trust_root_sha256,
            "trust_registry_generation": self._trust_registry_generation,
            "launch_token": f"launch-{uuid4().hex}",
            "process_pid": pid,
            "process_birth_identity": birth,
            "executable_identity": executable,
            "executable_sha256": executable_sha256,
            "installed_release": self._installed_release,
        }
        unsigned = RuntimeFenceOwner(**values, launch_signature="")
        signature = base64.b64encode(self._private_key.sign(unsigned.launch_payload())).decode(
            "ascii"
        )
        return RuntimeFenceOwner(**values, launch_signature=signature)

    def prove_exit(self, *, maintenance_generation: int) -> RuntimeDeathProof:
        exit_code = self._process.poll()
        if exit_code is None:
            raise RuntimeError("retrieval_profile_runtime_still_live")
        exited_at = datetime.now(UTC)
        values = {
            "proof_id": f"runtime-death-{uuid4().hex}",
            "instance_id": self._owner.instance_id,
            "generation": self._owner.generation,
            "supervisor_key_id": self._owner.supervisor_key_id,
            "trust_root_sha256": self._owner.trust_root_sha256,
            "trust_registry_generation": self._owner.trust_registry_generation,
            "launch_token": self._owner.launch_token,
            "process_pid": self._owner.process_pid,
            "process_birth_identity": self._owner.process_birth_identity,
            "executable_identity": self._owner.executable_identity,
            "executable_sha256": self._owner.executable_sha256,
            "installed_release": self._owner.installed_release,
            "maintenance_generation": maintenance_generation,
            "exit_observation_id": f"exit-observation-{uuid4().hex}",
            "exited_at": exited_at,
            "exit_code": int(exit_code),
        }
        signature = base64.b64encode(self._private_key.sign(_payload(**values))).decode("ascii")
        return RuntimeDeathProof(**values, signature=signature)


def _payload(**values: object) -> bytes:
    payload = dict(values)
    installed_release = payload.pop("installed_release", None)
    if not isinstance(installed_release, InstalledReleaseIdentity):
        raise ValueError("Runtime death proof release identity is invalid")
    payload["release_identity"] = installed_release.payload()
    payload["release_identity_sha256"] = installed_release.digest()
    exited_at = payload["exited_at"]
    if not isinstance(exited_at, datetime) or exited_at.utcoffset() is None:
        raise ValueError("Runtime death proof exited_at must be timezone-aware")
    payload["exited_at"] = exited_at.isoformat()
    payload["schema"] = "retrieval-runtime-death.v5"
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _process_identity(pid: int) -> tuple[str, str, str]:
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as stream:
            stat = stream.read()
        birth = stat[stat.rfind(")") + 2 :].split()[19]
        executable = os.path.realpath(f"/proc/{pid}/exe")
        with open(f"/proc/{pid}/exe", "rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
    except (OSError, IndexError) as exc:
        raise RuntimeError("retrieval_profile_runtime_identity_unavailable") from exc
    return birth, executable, digest


__all__ = ("RuntimeDeathProof", "RuntimeProcessSupervisor")
