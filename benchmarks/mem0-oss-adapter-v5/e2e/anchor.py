"""Passive PID-1 process for the shared provider-free network namespace."""

from __future__ import annotations

import signal
import threading


def main() -> None:
    stopped = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    stopped.wait()


if __name__ == "__main__":
    main()
