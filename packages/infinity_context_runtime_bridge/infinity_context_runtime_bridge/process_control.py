"""Exact Linux process identity and signaling port for bridge launch ownership."""

from __future__ import annotations

import os
import signal
from pathlib import Path
from typing import Protocol, final

from .process_contracts import BridgeProcessError, ProcessIdentity
from .process_files import bounded_read


class ProcessControlPort(Protocol):
    def identity(self, pid: int) -> ProcessIdentity | None: ...

    def signal_group(self, pgid: int, signum: int) -> None: ...

    def current_pgid(self) -> int: ...


@final
class LinuxProcessControl:
    """Bind PID, start ticks, group leadership and kernel boot; zombies are terminal."""

    def identity(self, pid: int) -> ProcessIdentity | None:
        if type(pid) is not int or pid <= 1:
            return None
        try:
            raw = bounded_read(Path(f"/proc/{pid}/stat"), maximum_bytes=64 * 1024)
            text = raw.decode("utf-8", errors="strict")
            suffix = text[text.rindex(")") + 2 :].split()
            if suffix[0] in {"X", "Z"}:
                return None
            boot_id = (
                bounded_read(Path("/proc/sys/kernel/random/boot_id"), maximum_bytes=128)
                .decode("ascii", errors="strict")
                .strip()
            )
            return ProcessIdentity(
                pid=pid,
                start_ticks=int(suffix[19]),
                pgid=int(suffix[2]),
                boot_id=boot_id,
            )
        except (BridgeProcessError, IndexError, OSError, UnicodeError, ValueError):
            return None

    def signal_group(self, pgid: int, signum: int) -> None:
        if type(pgid) is not int or pgid <= 1 or signum not in {signal.SIGTERM, signal.SIGKILL}:
            raise BridgeProcessError("bridge_process_signal_target_invalid")
        try:
            os.killpg(pgid, signum)
        except ProcessLookupError:
            return
        except OSError as exc:
            raise BridgeProcessError("bridge_process_signal_failed") from exc

    def current_pgid(self) -> int:
        return os.getpgrp()


__all__ = ("LinuxProcessControl", "ProcessControlPort")
