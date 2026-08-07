"""Deterministic loopback readiness probes for the provider-free stack."""

from __future__ import annotations

import argparse
import http.client
import json
import time

from .canonical import E2EVerificationError


def wait_for_stack(*, adapter_port: int, qdrant_port: int, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _adapter_ready(adapter_port) and _qdrant_ready(qdrant_port):
            return
        time.sleep(0.25)
    raise E2EVerificationError("e2e_stack_not_ready")


def shared_namespace_ready() -> bool:
    return _fake_runtime_ready(8891) and _qdrant_ready(6334)


def _get(port: int, path: str) -> tuple[int, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read(4097)
    except Exception:
        return 0, b""
    finally:
        connection.close()


def _qdrant_ready(port: int) -> bool:
    status, body = _get(port, "/readyz")
    return status == 200 and 0 < len(body) <= 4096


def _fake_runtime_ready(port: int) -> bool:
    status, body = _get(port, "/health")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return status == 200 and value == {"ok": True, "provider_calls": 0}


def _adapter_ready(port: int) -> bool:
    status, body = _get(port, "/health")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return status == 200 and value == {
        "ok": True,
        "service": "mem0-oss-adapter-v5",
        "provider_calls": "dispatch_only",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", required=True)
    parser.parse_args()
    if not shared_namespace_ready():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
