"""Private nonblocking process lock for one publishable input authority set."""

from __future__ import annotations

import fcntl
import os
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import final

from infinity_context_runtime_bridge.process_files import (
    verify_private_directory,
)

from .contracts import PublishableInputPreparationError


@final
@dataclass(slots=True, repr=False)
class PublishableInputPreparationProcessLock:
    """Hold one owner-only advisory lock until all producer resources close."""

    path: Path
    descriptor: int

    @classmethod
    def acquire(cls, path: Path) -> PublishableInputPreparationProcessLock:
        if not isinstance(path, Path) or not path.is_absolute() or path.name in {"", ".", ".."}:
            _fail("publishable_input_process_lock_invalid")
        descriptor = -1
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            verify_private_directory(path.parent, "publishable_input_lock_parent")
            before = path.lstat() if os.path.lexists(path) else None
            previous_umask = os.umask(0o077)
            try:
                descriptor = os.open(path, flags, 0o600)
            finally:
                os.umask(previous_umask)
            opened = os.fstat(descriptor)
            after = path.lstat()
            if (
                stat.S_ISLNK(after.st_mode)
                or not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) != 0o600
                or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
                or before is not None
                and (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                _fail("publishable_input_process_lock_invalid")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return cls(path=path, descriptor=descriptor)
        except BlockingIOError:
            _close_descriptor(descriptor)
            _fail("publishable_input_process_already_active")
        except PublishableInputPreparationError:
            _close_descriptor(descriptor)
            raise
        except (OSError, ValueError):
            _close_descriptor(descriptor)
            _fail("publishable_input_process_lock_invalid")

    def close(self) -> None:
        if self.descriptor < 0:
            return
        descriptor, self.descriptor = self.descriptor, -1
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def __repr__(self) -> str:
        return "PublishableInputPreparationProcessLock(private_file=<bound>)"


def _close_descriptor(descriptor: int) -> None:
    if descriptor >= 0:
        with suppress(OSError):
            os.close(descriptor)


def _fail(code: str) -> None:
    raise PublishableInputPreparationError(code) from None


__all__ = ("PublishableInputPreparationProcessLock",)
