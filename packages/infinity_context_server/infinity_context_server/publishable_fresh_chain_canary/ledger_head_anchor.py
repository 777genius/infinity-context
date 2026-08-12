"""Rollback-resistant external head anchor for the fresh-chain SQLite ledger."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import tempfile
from contextlib import suppress
from pathlib import Path

from .ledger_models import FreshChainLedgerError

ANCHOR_SUFFIX = ".head-anchor.json"
_SCHEMA = "infinity-context-fresh-chain-ledger-head-anchor.v1"
_DOMAIN = b"infinity-context/fresh-chain-ledger-head-anchor/v1\0"


class FreshChainLedgerHeadAnchor:
    """Authenticate the greatest durable SQLite event head outside SQLite."""

    def __init__(self, ledger_path: Path, *, key: bytes, identity: tuple[int, int]) -> None:
        self.path = ledger_path.with_name(ledger_path.name + ANCHOR_SUFFIX)
        self._key = key
        self._identity = identity

    def synchronize(
        self,
        connection: object,
        *,
        count: int,
        head: str,
        allow_create: bool,
    ) -> None:
        exists = os.path.lexists(self.path)
        if not exists and (not allow_create or count != 0):
            _fail("fresh_chain_ledger_anchor_missing")
        current = self._read() if exists else None
        if current is not None:
            anchored_count = current["event_count"]
            anchored_head = current["event_head_hmac"]
            if anchored_count > count:
                _fail("fresh_chain_ledger_rollback_detected")
            if anchored_count == count:
                if not hmac.compare_digest(anchored_head, head):
                    _fail("fresh_chain_ledger_rollback_detected")
                return
            if anchored_count == 0:
                observed = connection.execute(
                    "SELECT event_head_hmac FROM fresh_chain_head WHERE singleton = 1"
                ).fetchone()
                if observed is None and count != 0:
                    _fail("fresh_chain_ledger_rollback_detected")
            else:
                observed = connection.execute(
                    "SELECT event_hmac FROM fresh_chain_events WHERE sequence = ?",
                    (anchored_count,),
                ).fetchone()
                if observed is None or not hmac.compare_digest(str(observed[0]), anchored_head):
                    _fail("fresh_chain_ledger_rollback_detected")
        self._write(count=count, head=head)

    def write(self, *, count: int, head: str) -> None:
        if not os.path.lexists(self.path):
            _fail("fresh_chain_ledger_anchor_missing")
        current = self._read()
        if current["event_count"] > count or (
            current["event_count"] == count
            and not hmac.compare_digest(current["event_head_hmac"], head)
        ):
            _fail("fresh_chain_ledger_rollback_detected")
        self._write(count=count, head=head)

    def _read(self) -> dict[str, object]:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self.path,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            )
            metadata = os.fstat(descriptor)
            if not _private_file(metadata) or not 1 <= metadata.st_size <= 4096:
                raise ValueError
            raw = os.read(descriptor, 4097)
            value = json.loads(raw)
        except Exception:
            _fail("fresh_chain_ledger_anchor_invalid")
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if type(value) is not dict or set(value) != {
            "anchor_hmac_sha256",
            "event_count",
            "event_head_hmac",
            "ledger_device",
            "ledger_inode",
            "schema_version",
        }:
            _fail("fresh_chain_ledger_anchor_invalid")
        unsigned = {key: item for key, item in value.items() if key != "anchor_hmac_sha256"}
        if (
            value["schema_version"] != _SCHEMA
            or type(value["event_count"]) is not int
            or value["event_count"] < 0
            or not _sha(value["event_head_hmac"])
            or (value["ledger_device"], value["ledger_inode"]) != self._identity
            or not _sha(value["anchor_hmac_sha256"])
            or not hmac.compare_digest(value["anchor_hmac_sha256"], self._sign(unsigned))
        ):
            _fail("fresh_chain_ledger_anchor_invalid")
        return value

    def _write(self, *, count: int, head: str) -> None:
        unsigned = {
            "event_count": count,
            "event_head_hmac": head,
            "ledger_device": self._identity[0],
            "ledger_inode": self._identity[1],
            "schema_version": _SCHEMA,
        }
        encoded = _canonical({**unsigned, "anchor_hmac_sha256": self._sign(unsigned)})
        descriptor: int | None = None
        temporary: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
            temporary = Path(name)
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, encoded)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.replace(temporary, self.path)
            temporary = None
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except Exception:
            _fail("fresh_chain_ledger_anchor_unavailable")
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink()

    def _sign(self, value: dict[str, object]) -> str:
        return hmac.new(self._key, _DOMAIN + _canonical(value), hashlib.sha256).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _private_file(value: os.stat_result) -> bool:
    return (
        stat.S_ISREG(value.st_mode)
        and value.st_uid == os.geteuid()
        and stat.S_IMODE(value.st_mode) == 0o600
        and value.st_nlink == 1
    )


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _fail(code: str) -> None:
    raise FreshChainLedgerError(code) from None


__all__ = ("ANCHOR_SUFFIX", "FreshChainLedgerHeadAnchor")
