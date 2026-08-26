"""Fail-closed OS identity transition for the fresh Qdrant acceptance worker."""

from __future__ import annotations

import os


def enter_runtime_identity(runtime_uid: int, runtime_gid: int) -> None:
    """Enter and verify the configured unprivileged runtime identity."""
    if runtime_uid <= 0 or runtime_gid <= 0:
        raise RuntimeError("fresh_process_runtime_identity_must_be_unprivileged")

    if os.getgroups():
        try:
            os.setgroups([])
        except PermissionError as exc:
            # A restricted process cannot call setgroups. Accept the error only if
            # a re-read proves that the required empty-group state already holds.
            if os.getgroups():
                raise RuntimeError(
                    "fresh_process_supplementary_groups_could_not_be_cleared"
                ) from exc

    if os.getgid() != runtime_gid or os.getegid() != runtime_gid:
        os.setgid(runtime_gid)
    if os.getuid() != runtime_uid or os.geteuid() != runtime_uid:
        os.setuid(runtime_uid)

    actual_identity = (os.getuid(), os.geteuid(), os.getgid(), os.getegid())
    expected_identity = (runtime_uid, runtime_uid, runtime_gid, runtime_gid)
    supplementary_groups = os.getgroups()
    if actual_identity != expected_identity or supplementary_groups:
        raise RuntimeError(
            "fresh_process_runtime_identity_mismatch: "
            f"expected={expected_identity!r}, actual={actual_identity!r}, "
            f"supplementary_groups={supplementary_groups!r}"
        )
