"""Pinned provider-free compiled parser differential support."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PINNED_RUNTIME_REPO = Path(
    os.environ.get(
        "INFINITY_CONTEXT_SUBSCRIPTION_RUNTIME_REPO",
        "/mnt/volume_ams3_1784742570542/infinity-context/runtimes/"
        "subscription-runtime/e904ec95/repo",
    )
)
RUNTIME_PARSER_SOURCE = (
    PINNED_RUNTIME_REPO / "src/openai-compatible-codex/chat-completions/application/"
    "parse-chat-completion-request.ts"
)
RUNTIME_PARSER_DIST = (
    PINNED_RUNTIME_REPO / "dist/openai-compatible-codex/chat-completions/application/"
    "parse-chat-completion-request.js"
)
NODE_BINARY = shutil.which("node")
requires_compiled_runtime = pytest.mark.skipif(
    NODE_BINARY is None or not RUNTIME_PARSER_SOURCE.is_file() or not RUNTIME_PARSER_DIST.is_file(),
    reason="the pinned e904ec95 source/dist parser and node are required",
)

_RUNTIME_PARSER_SOURCE_SHA256 = "c7c1647bc703ad4eaae112e61ccde1b6a4bd3ed806bd6a1aae7c28f64b95e9b7"
_RUNTIME_PARSER_DIST_SHA256 = "9d34a5da2bc5888322058ee5cebd8f551b320b2d3b81caeb0744f27b95ca0763"
_PARSE_SCRIPT = r"""
let raw = "";
for await (const chunk of process.stdin) raw += chunk;
const {parseChatCompletionRequest} = await import(process.argv[1]);
const parsed = parseChatCompletionRequest(JSON.parse(raw));
process.stdout.write(JSON.stringify(parsed));
"""


def compiled_runtime_parse(request_body: bytes) -> dict[str, object]:
    """Parse with the exact manifest-pinned e904ec95 compiled module."""

    assert NODE_BINARY is not None
    assert hashlib.sha256(RUNTIME_PARSER_SOURCE.read_bytes()).hexdigest() == (
        _RUNTIME_PARSER_SOURCE_SHA256
    )
    assert hashlib.sha256(RUNTIME_PARSER_DIST.read_bytes()).hexdigest() == (
        _RUNTIME_PARSER_DIST_SHA256
    )
    completed = subprocess.run(
        [NODE_BINARY, "--input-type=module", "-e", _PARSE_SCRIPT, RUNTIME_PARSER_DIST.as_uri()],
        cwd=PINNED_RUNTIME_REPO,
        env={"LANG": "C.UTF-8", "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")},
        input=request_body,
        capture_output=True,
        check=True,
        timeout=10,
    )
    parsed = json.loads(completed.stdout)
    assert isinstance(parsed, dict)
    return parsed


__all__ = ("compiled_runtime_parse", "requires_compiled_runtime")
