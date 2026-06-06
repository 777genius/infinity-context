"""Package CLI dispatcher."""

from __future__ import annotations

import sys

from memo_stack_server.eval import main as eval_main


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "eval":
        eval_main(args[1:])
        return
    raise SystemExit("Supported command: python -m memo_stack_server eval ...")


if __name__ == "__main__":
    main()
