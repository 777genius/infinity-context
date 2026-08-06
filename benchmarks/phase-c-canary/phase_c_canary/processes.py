from __future__ import annotations

import json
import os
import signal
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID


class ProcessRegistryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True, order=True)
class ProcessIdentity:
    pid: int
    start_ticks: int
    pgid: int
    boot_id: str


class ProcessControlPort(Protocol):
    def identity(self, pid: int) -> ProcessIdentity | None: ...

    def terminate_group(self, pgid: int) -> None: ...

    def current_pgid(self) -> int: ...


class LinuxProcessControl(ProcessControlPort):
    def identity(self, pid: int) -> ProcessIdentity | None:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            # comm is parenthesized and may itself contain spaces or parentheses.
            suffix = stat[stat.rindex(")") + 2 :].split()
            boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
            return ProcessIdentity(
                pid=pid,
                start_ticks=int(suffix[19]),
                pgid=int(suffix[2]),
                boot_id=boot_id,
            )
        except (FileNotFoundError, IndexError, OSError, ValueError):
            return None

    def terminate_group(self, pgid: int) -> None:
        if pgid <= 1:
            raise ProcessRegistryError("refusing unsafe process-group target")
        os.killpg(pgid, signal.SIGTERM)

    def current_pgid(self) -> int:
        return os.getpgrp()


class ProcessRegistry:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> set[ProcessIdentity]:
        if not self._path.exists():
            return set()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            identities = {ProcessIdentity(**item) for item in raw}
            for identity in identities:
                _validate_group_leader(identity)
            return identities
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ProcessRegistryError("invalid process registry") from exc

    def store_union(self, discovered: set[ProcessIdentity]) -> set[ProcessIdentity]:
        for identity in discovered:
            _validate_group_leader(identity)
        merged = self.load() | discovered
        self._atomic_write([asdict(item) for item in sorted(merged)])
        return merged

    def cleanup(
        self,
        discovered: set[ProcessIdentity],
        control: ProcessControlPort,
    ) -> tuple[ProcessIdentity, ...]:
        targets = self.store_union(discovered)
        current_pgid = control.current_pgid()
        if any(target.pgid == current_pgid for target in targets):
            raise ProcessRegistryError("refusing to clean up the runner process group")
        terminated: list[ProcessIdentity] = []
        for target in sorted(targets):
            current = control.identity(target.pid)
            if current != target:
                continue
            control.terminate_group(target.pgid)
            terminated.append(target)
        return tuple(terminated)

    def _atomic_write(self, value: object) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self._path)
        descriptor = os.open(self._path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _validate_group_leader(identity: ProcessIdentity) -> None:
    try:
        canonical_boot_id = str(UUID(identity.boot_id))
    except (AttributeError, ValueError):
        canonical_boot_id = ""
    if (
        type(identity.pid) is not int
        or identity.pid <= 1
        or identity.pid != identity.pgid
        or type(identity.start_ticks) is not int
        or identity.start_ticks <= 0
        or type(identity.boot_id) is not str
        or canonical_boot_id != identity.boot_id
    ):
        raise ProcessRegistryError("process registry accepts exact process-group leaders only")
