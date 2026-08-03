from __future__ import annotations

import pytest
from infinity_context_server_harness import (
    _FAILURE_TAIL_BYTES,
    _LOG_LIMIT_BYTES,
    _BoundedTempLog,
    run_infinity_context_server,
)


def test_process_logs_keep_only_a_bounded_tail(tmp_path) -> None:
    log = _BoundedTempLog(tmp_path, name="server")
    log.append(b"discarded-" + b"a" * _LOG_LIMIT_BYTES)
    log.append(b"\nterminal-line")

    assert log.path.stat().st_size <= _LOG_LIMIT_BYTES
    tail = log.tail()
    assert len(tail) == _FAILURE_TAIL_BYTES
    assert tail.endswith("terminal-line")
    assert log.tail(limit=len("terminal-line")) == "terminal-line"


def test_live_body_failure_attaches_server_and_worker_log_tails(tmp_path) -> None:
    with (
        pytest.raises(RuntimeError, match="body failure") as raised,
        run_infinity_context_server(tmp_path, projection_worker=True),
    ):
        raise RuntimeError("body failure")

    notes = raised.value.__notes__
    assert notes is not None
    assert "infinity_context_server log tail:" in notes[-1]
    assert "infinity_context projection worker log tail:" in notes[-1]
