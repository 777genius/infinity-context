"""Cold-start bootstrap for provider-free managed-v5 recovery."""

from __future__ import annotations

import sys
from collections.abc import Sequence

sys.dont_write_bytecode = True


def main(argv: Sequence[str] | None = None) -> int:
    from infinity_context_server.memory_comparison_managed_v5_recovery_cli import (
        main as recovery_main,
    )

    return recovery_main(argv)


__all__ = ("main",)
