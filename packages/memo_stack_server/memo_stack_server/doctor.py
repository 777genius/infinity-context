"""Readiness CLI for Core Lite deployments."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from memo_stack_server.admin import (
    ACTIVE_CONTEXT_MANUAL_CHECK_NAMES,
    active_context_readiness_gate,
    doctor,
)


async def run_doctor(
    *,
    gate: str | None = None,
    acknowledged_checks: set[str] | None = None,
) -> dict[str, object]:
    try:
        if gate == "active_context":
            return await active_context_readiness_gate(
                acknowledged_checks=acknowledged_checks or set()
            )
        return await doctor()
    except Exception as exc:
        return {
            "status": "failed",
            "checks": [
                {
                    "name": "postgres",
                    "status": "failed",
                    "safe_error": exc.__class__.__name__,
                }
            ],
        }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Memo Stack readiness checks")
    parser.add_argument("--gate", choices=("active_context",), default=None)
    parser.add_argument(
        "--ack",
        action="append",
        choices=ACTIVE_CONTEXT_MANUAL_CHECK_NAMES,
        default=[],
        help="Acknowledge a manual active_context gate check. Repeatable.",
    )
    parser.add_argument(
        "--ack-all-manual",
        action="store_true",
        help="Acknowledge all manual checks after verifying them outside the doctor command.",
    )
    args = parser.parse_args(argv)
    acknowledged_checks = (
        set(ACTIVE_CONTEXT_MANUAL_CHECK_NAMES)
        if args.ack_all_manual
        else set(args.ack)
    )
    result = asyncio.run(
        run_doctor(gate=args.gate, acknowledged_checks=acknowledged_checks)
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    sys.exit(0 if result.get("status") == "ok" else 1)


if __name__ == "__main__":
    main()
