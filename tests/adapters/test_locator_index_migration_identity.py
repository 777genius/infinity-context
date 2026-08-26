from __future__ import annotations

import asyncio

import pytest
from infinity_context_adapters.postgres import locator_index_maintenance


class _HistoryConnection:
    def __init__(self, checksum: str | None) -> None:
        self.checksum = checksum

    async def scalar(self, *_args, **_kwargs) -> str | None:
        return self.checksum


def test_index_bootstrap_accepts_published_0039_identity() -> None:
    connection = _HistoryConnection(
        "83f22c9e4087e6f4713294665a00ce99f7ffc981893702a2fbb3a575813c418d"
    )

    asyncio.run(locator_index_maintenance._require_expand_migration(connection))


@pytest.mark.parametrize("checksum", [None, "0" * 64])
def test_index_bootstrap_rejects_unknown_0039_identity(checksum: str | None) -> None:
    with pytest.raises(RuntimeError, match="absent or has checksum drift"):
        asyncio.run(
            locator_index_maintenance._require_expand_migration(
                _HistoryConnection(checksum)
            )
        )
