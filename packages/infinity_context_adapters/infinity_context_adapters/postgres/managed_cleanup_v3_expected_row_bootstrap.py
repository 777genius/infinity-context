"""Serialized recovery of a pre-schema cleanup-v4 expected-row index bootstrap."""

from __future__ import annotations

import errno
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from infinity_context_core.ports.managed_cleanup_v3_contracts import ManagedCleanupV3Error

from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_files import (
    close_secure_lock,
    open_secure_lock,
    open_secure_sqlite,
    unlink_secure_file,
)

_T = TypeVar("_T")


def open_or_create_repairable_bootstrap(
    path: Path,
    *,
    claim_path: Path,
    open_existing: Callable[[], _T],
    create_new: Callable[[], _T],
) -> _T:
    """Open a sealed index or recreate only an exact empty pre-schema inode."""
    lock = open_secure_lock(path.with_name(f"{path.name}.bootstrap.lock"))
    try:
        try:
            path.lstat()
        except FileNotFoundError:
            return _create_or_open_race(create_new, open_existing)
        try:
            return open_existing()
        except BaseException as open_error:
            _repair_empty_main(path, claim_path, open_error)
        return _create_or_open_race(create_new, open_existing)
    finally:
        close_secure_lock(lock)


def _repair_empty_main(path: Path, claim_path: Path, open_error: BaseException) -> None:
    try:
        claim_path.lstat()
    except FileNotFoundError:
        pass
    else:
        raise open_error from None
    try:
        db, descriptor = open_secure_sqlite(path, readonly=False)
    except BaseException:
        raise open_error from None
    db_closed = False
    descriptor_closed = False
    try:
        if not _is_zero_user_data(db):
            raise open_error from None
        db.close()
        db_closed = True
        try:
            unlink_secure_file(path, descriptor)
        finally:
            os.close(descriptor)
            descriptor_closed = True
    except BaseException:
        try:
            if not db_closed:
                db.close()
        finally:
            if not descriptor_closed:
                os.close(descriptor)
        raise


def _is_zero_user_data(db: sqlite3.Connection) -> bool:
    try:
        schema_rows = tuple(db.execute("SELECT type,name FROM sqlite_schema"))
        page_count = int(db.execute("PRAGMA page_count").fetchone()[0])
        freelist_count = int(db.execute("PRAGMA freelist_count").fetchone()[0])
        application_id = int(db.execute("PRAGMA application_id").fetchone()[0])
        user_version = int(db.execute("PRAGMA user_version").fetchone()[0])
    except (sqlite3.DatabaseError, TypeError, ValueError, IndexError):
        return False
    return (
        not schema_rows
        and page_count in (0, 1)
        and freelist_count == 0
        and application_id == 0
        and user_version == 0
    )


def _create_or_open_race(create_new: Callable[[], _T], open_existing: Callable[[], _T]) -> _T:
    try:
        return create_new()
    except ManagedCleanupV3Error as exc:
        if not _caused_by_exists(exc):
            raise
        return open_existing()


def _caused_by_exists(error: BaseException) -> bool:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, OSError) and current.errno == errno.EEXIST:
            return True
        current = current.__cause__
    return False


__all__ = ("open_or_create_repairable_bootstrap",)
