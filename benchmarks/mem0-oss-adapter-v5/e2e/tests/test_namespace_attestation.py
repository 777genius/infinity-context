from __future__ import annotations

import hashlib
import os
import socket
import subprocess
from pathlib import Path

import pytest

from e2e.namespace_attestation import (
    FAILURE,
    PINNED_DOCKER,
    PINNED_NODE_SHA256,
    REQUEST,
    SUCCESS,
    PinnedExecutableAttestor,
    RootDockerLifecycleHelper,
    attest_tmpfs,
)

PROJECT = "mem0-v5-e2e-deadbeef-r1"


def test_tmpfs_accepts_physical_qdrant_binary_unit_representation() -> None:
    host = {
        "Tmpfs": {
            "/qdrant/storage": "size=1g,mode=0700,uid=65532,gid=65532",
            "/tmp": "size=32m,mode=1770,uid=65532,gid=65532",
        }
    }
    attest_tmpfs(
        host,
        {
            "/qdrant/storage": (1024**3, "0700"),
            "/tmp": (32 * 1024**2, "1770"),
        },
    )


@pytest.mark.parametrize(
    "options",
    [
        "size=2g,mode=0700,uid=65532,gid=65532",
        "size=1gb,mode=0700,uid=65532,gid=65532",
        "size=1G,mode=0700,uid=65532,gid=65532",
        "size=1g,size=1073741824,mode=0700,uid=65532,gid=65532",
        "size=1g,mode=0700,uid=65532,gid=65532,nosuid=true",
    ],
)
def test_tmpfs_rejects_wrong_noncanonical_duplicate_or_unknown_options(
    options: str,
) -> None:
    with pytest.raises(ValueError, match="e2e_service_tmpfs_invalid"):
        attest_tmpfs(
            {"Tmpfs": {"/qdrant/storage": options}},
            {"/qdrant/storage": (1024**3, "0700")},
        )


def _environment() -> dict[str, str]:
    names = (
        "MEM0_V5_INPUT_DIR",
        "MEM0_V5_STATE_DIR",
        "MEM0_V5_SECRET_DIR",
        "MEM0_V5_FAKE_RUNTIME_STATE_DIR",
        "MEM0_V5_RUNTIME_AUTHORITY_DIR",
        "MEM0_V5_SOURCE_AUTHORITY_DIR",
        "MEM0_V5_SOURCE_AUTHORITY_PIN_DIR",
        "MEM0_V5_SOURCE_AUTHORITY_PIN_SHA256_FILE",
        "MEM0_V5_NODE_EXECUTABLE_SOURCE",
    )
    return {name: f"/absolute/{name.lower()}" for name in names}


def _helper(
    tmp_path: Path,
    parent: socket.socket,
    calls: list,
    runner=None,
    trust_attestor=None,
):
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}\n")
    return RootDockerLifecycleHelper(
        channel=parent,
        compose_file=compose,
        project_name=PROJECT,
        environment=_environment(),
        trust_attestor=trust_attestor or (lambda: None),
        run_process=runner or (lambda command, **kwargs: calls.append((command, kwargs))),
    )


def test_root_helper_accepts_one_exact_request_and_two_fixed_commands(
    tmp_path: Path,
) -> None:
    parent, child = socket.socketpair()
    calls = []
    trust_command_counts = []
    helper = _helper(
        tmp_path,
        parent,
        calls,
        trust_attestor=lambda: trust_command_counts.append(len(calls)),
    )
    child.sendall(REQUEST)
    child.shutdown(socket.SHUT_WR)
    assert helper.serve_once() is True
    assert child.recv(32) == SUCCESS
    assert len(calls) == 2
    assert trust_command_counts == [0, 1]
    assert calls[0][0][-4:] == ["kill", "--signal", "KILL", "mem0-oss-adapter-v5"]
    assert calls[1][0][-2:] == ["start", "mem0-oss-adapter-v5"]
    assert all(command[0] == PINNED_DOCKER for command, _ in calls)
    assert all(kwargs["stderr"] is subprocess.DEVNULL for _, kwargs in calls)
    child.close()


@pytest.mark.parametrize("fail_on", [1, 2])
def test_root_helper_trust_failure_aborts_next_mutation(tmp_path: Path, fail_on: int) -> None:
    parent, child = socket.socketpair()
    calls = []
    trust_calls = []

    def attest_trust() -> None:
        trust_calls.append(True)
        if len(trust_calls) == fail_on:
            raise RuntimeError("private trust failure")

    helper = _helper(tmp_path, parent, calls, trust_attestor=attest_trust)
    child.sendall(REQUEST)
    child.shutdown(socket.SHUT_WR)
    assert helper.serve_once() is False
    assert child.recv(32) == FAILURE
    assert len(trust_calls) == fail_on
    assert len(calls) == fail_on - 1
    child.close()


@pytest.mark.parametrize("payload", [b"bad\n", REQUEST + REQUEST, b""])
def test_root_helper_rejects_malformed_duplicate_or_missing_request(
    tmp_path: Path, payload: bytes
) -> None:
    parent, child = socket.socketpair()
    calls = []
    helper = _helper(tmp_path, parent, calls)
    if payload:
        child.sendall(payload)
    child.shutdown(socket.SHUT_WR)
    assert helper.serve_once() is False
    assert child.recv(32) == FAILURE
    assert calls == []
    child.close()


def test_root_helper_sanitizes_command_failure(tmp_path: Path) -> None:
    parent, child = socket.socketpair()
    helper = _helper(
        tmp_path,
        parent,
        [],
        runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    child.sendall(REQUEST)
    child.shutdown(socket.SHUT_WR)
    assert helper.serve_once() is False
    assert child.recv(32) == FAILURE
    child.close()


def test_root_helper_bounds_idle_channel_and_returns_sanitized_failure(
    tmp_path: Path,
) -> None:
    class TimeoutChannel:
        def __init__(self) -> None:
            self.reply = b""
            self.timeout = None
            self.closed = False

        def settimeout(self, value) -> None:
            self.timeout = value

        def recv(self, _size: int) -> bytes:
            raise TimeoutError

        def sendall(self, value: bytes) -> None:
            self.reply += value

        def shutdown(self, _direction: int) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    channel = TimeoutChannel()
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}\n")
    helper = RootDockerLifecycleHelper(
        channel=channel,
        compose_file=compose,
        project_name=PROJECT,
        environment=_environment(),
        trust_attestor=lambda: pytest.fail("must not attest before a request"),
        run_process=lambda *_args, **_kwargs: pytest.fail("must not invoke Docker"),
    )
    assert helper.serve_once() is False
    assert channel.timeout == 75
    assert channel.reply == FAILURE
    assert channel.closed is True


def _node_attestor(path: Path, expected: str = PINNED_NODE_SHA256):
    return PinnedExecutableAttestor(
        path=path,
        expected_sha256=expected,
        error_type=RuntimeError,
    )


def test_node_attestor_binds_digest_and_rechecks_same_inode(tmp_path: Path) -> None:
    node = tmp_path / "node"
    content = b"reviewed-node"
    node.write_bytes(content)
    attestor = _node_attestor(node, hashlib.sha256(content).hexdigest())
    descriptor, identity = attestor.open()
    try:
        attestor.reattest(descriptor, identity)
    finally:
        os.close(descriptor)


def test_node_attestor_rejects_digest_mismatch_and_symlink(tmp_path: Path) -> None:
    node = tmp_path / "node"
    node.write_bytes(b"wrong-node")
    with pytest.raises(RuntimeError, match="e2e_node_executable_invalid"):
        _node_attestor(node).open()
    link = tmp_path / "node-link"
    link.symlink_to(node)
    with pytest.raises(RuntimeError, match="e2e_node_executable_invalid"):
        _node_attestor(link).open()


def test_node_attestor_rejects_path_replacement(tmp_path: Path) -> None:
    node = tmp_path / "node"
    content = b"reviewed-node"
    node.write_bytes(content)
    attestor = _node_attestor(node, hashlib.sha256(content).hexdigest())
    descriptor, identity = attestor.open()
    replacement = tmp_path / "replacement"
    replacement.write_bytes(content)
    os.replace(replacement, node)
    try:
        with pytest.raises(RuntimeError, match="e2e_node_executable_changed"):
            attestor.reattest(descriptor, identity)
    finally:
        os.close(descriptor)
