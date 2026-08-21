"""Run one deterministic, exhaustive shard of the repository's pytest suite."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Sequence

import pytest


def validate_shard(*, shard_index: int, shard_total: int) -> None:
    """Validate a zero-based shard index and the total number of shards."""
    if shard_total < 1:
        raise ValueError("shard_total must be at least 1")
    if not 0 <= shard_index < shard_total:
        raise ValueError(
            f"shard_index must be between 0 and {shard_total - 1}, got {shard_index}"
        )


def shard_key_for_nodeid(nodeid: str) -> str:
    """Keep every test from one module in the same shard."""
    return nodeid.partition("::")[0]


def shard_index_for_nodeid(nodeid: str, *, shard_total: int) -> int:
    """Return a stable module-level shard for a pytest node ID."""
    if shard_total < 1:
        raise ValueError("shard_total must be at least 1")
    shard_key = shard_key_for_nodeid(nodeid)
    digest = hashlib.sha256(shard_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big") % shard_total


def select_nodeids_for_shard(
    nodeids: Sequence[str],
    *,
    shard_index: int,
    shard_total: int,
) -> tuple[str, ...]:
    """Select exactly the node IDs assigned to one shard."""
    validate_shard(shard_index=shard_index, shard_total=shard_total)
    return tuple(
        nodeid
        for nodeid in nodeids
        if shard_index_for_nodeid(nodeid, shard_total=shard_total) == shard_index
    )


class _ShardPlugin:
    def __init__(self, *, shard_index: int, shard_total: int) -> None:
        validate_shard(shard_index=shard_index, shard_total=shard_total)
        self._shard_index = shard_index
        self._shard_total = shard_total

    def pytest_collection_modifyitems(
        self,
        config: pytest.Config,
        items: list[pytest.Item],
    ) -> None:
        selected: list[pytest.Item] = []
        deselected: list[pytest.Item] = []
        for item in items:
            target = (
                selected
                if shard_index_for_nodeid(
                    item.nodeid,
                    shard_total=self._shard_total,
                )
                == self._shard_index
                else deselected
            )
            target.append(item)

        if deselected:
            config.hook.pytest_deselected(items=deselected)
        items[:] = selected


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a deterministic shard of the configured pytest suite."
    )
    parser.add_argument("--shard-index", required=True, type=int)
    parser.add_argument("--shard-total", required=True, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args, pytest_args = _build_parser().parse_known_args(argv)
    try:
        plugin = _ShardPlugin(
            shard_index=args.shard_index,
            shard_total=args.shard_total,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    return int(pytest.main(list(pytest_args), plugins=[plugin]))


if __name__ == "__main__":
    raise SystemExit(main())
