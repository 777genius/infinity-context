from __future__ import annotations

import argparse
from pathlib import Path

from .authority import immutable_authority
from .journal import ProviderUsageJournal
from .orchestrator import CanaryOrchestrator, RunMode, render_preflight
from .python_closure import require_bytecode_disabled


class _OfflineVerifier:
    def verify(self, *, receipt: dict[str, object], secret: str) -> None:
        raise RuntimeError("receipt verification is unavailable in offline preflight")


def main(argv: list[str] | None = None) -> int:
    require_bytecode_disabled()
    parser = argparse.ArgumentParser(description="Phase C provider-free canary v5")
    parser.add_argument("--mode", choices=("offline", "fake"), required=True)
    parser.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args(argv)
    journal = ProviderUsageJournal(args.journal)
    try:
        report = CanaryOrchestrator(
            authority=immutable_authority(), journal=journal, verifier=_OfflineVerifier()
        ).preflight(RunMode(args.mode))
        print(render_preflight(report))
    finally:
        journal.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
