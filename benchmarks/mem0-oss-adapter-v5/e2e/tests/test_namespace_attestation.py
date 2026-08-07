from __future__ import annotations

import hashlib
import os
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from e2e.namespace_attestation import (
    FAILURE,
    PINNED_DOCKER,
    PINNED_NODE_SHA256,
    REQUEST,
    SUCCESS,
    PinnedExecutableAttestor,
    PrivateDirectoryAttestingExecutor,
    PrivateDirectoryAttestor,
    RootDockerLifecycleHelper,
    SourcePinAttestingExecutor,
    SourcePinAttestor,
    _immutable_file_identity,
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
        environment={**_environment(), "MEM0_DIR": "/attacker", "HOME": "/attacker-home"},
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
    assert all(
        "MEM0_DIR" not in kwargs["env"] and "HOME" not in kwargs["env"] for _, kwargs in calls
    )
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
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        allowed_chain_owners=_chain_owners(path.parent),
        chain_anchor=path.parent,
    )


def _chain_owners(path: Path) -> frozenset[tuple[int, int]]:
    owners = set()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        metadata = current.lstat()
        owners.add((metadata.st_uid, metadata.st_gid))
    return frozenset(owners)


def _immutable_node(tmp_path: Path, content: bytes) -> Path:
    node = tmp_path / "node"
    node.write_bytes(content)
    node.chmod(0o555)
    tmp_path.chmod(0o555)
    return node


def test_node_attestor_binds_digest_and_rechecks_same_inode(tmp_path: Path) -> None:
    content = b"reviewed-node"
    node = _immutable_node(tmp_path, content)
    attestor = _node_attestor(node, hashlib.sha256(content).hexdigest())
    descriptor, identity = attestor.open()
    try:
        attestor.reattest(descriptor, identity)
    finally:
        os.close(descriptor)


def test_node_attestor_rejects_digest_mismatch_and_symlink(tmp_path: Path) -> None:
    node = _immutable_node(tmp_path, b"wrong-node")
    with pytest.raises(RuntimeError, match="e2e_node_executable_invalid"):
        _node_attestor(node).open()
    tmp_path.chmod(0o755)
    link = tmp_path / "node-link"
    link.symlink_to(node)
    tmp_path.chmod(0o555)
    with pytest.raises(RuntimeError, match="e2e_node_executable_invalid"):
        _node_attestor(link).open()


def test_node_attestor_rejects_path_replacement(tmp_path: Path) -> None:
    content = b"reviewed-node"
    node = _immutable_node(tmp_path, content)
    attestor = _node_attestor(node, hashlib.sha256(content).hexdigest())
    descriptor, identity = attestor.open()
    tmp_path.chmod(0o755)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(content)
    replacement.chmod(0o555)
    os.replace(replacement, node)
    tmp_path.chmod(0o555)
    try:
        with pytest.raises(RuntimeError, match="e2e_node_executable_changed"):
            attestor.reattest(descriptor, identity)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("mode", [0o755, 0o544])
def test_node_attestor_rejects_nonexact_leaf_mode(tmp_path: Path, mode: int) -> None:
    node = _immutable_node(tmp_path, b"reviewed-node")
    tmp_path.chmod(0o755)
    node.chmod(mode)
    tmp_path.chmod(0o555)
    with pytest.raises(RuntimeError, match="e2e_node_executable_invalid"):
        _node_attestor(node, hashlib.sha256(b"reviewed-node").hexdigest()).open()


def _source_pin(tmp_path: Path, content: bytes = b'{"reviewed":true}') -> tuple[Path, Path]:
    pin = tmp_path / "deadbeef"
    pin.mkdir(mode=0o755)
    manifest = pin / "manifest.json"
    digest = pin / "manifest.sha256"
    manifest.write_bytes(content)
    digest.write_bytes(hashlib.sha256(content).hexdigest().encode())
    manifest.chmod(0o444)
    digest.chmod(0o444)
    pin.chmod(0o555)
    return manifest, digest


def test_source_pin_attestor_binds_and_reattests_manifest_and_digest(tmp_path: Path) -> None:
    manifest, digest = _source_pin(tmp_path)
    attestor = SourcePinAttestor(
        manifest_path=manifest,
        digest_path=digest,
        error_type=RuntimeError,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        allowed_chain_owners=_chain_owners(manifest.parent),
        chain_anchor=manifest.parent,
    )
    descriptors, identities, expected = attestor.open()
    try:
        attestor.reattest(descriptors, identities, expected)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def test_source_pin_identity_rejects_nonroot_owner() -> None:
    metadata = SimpleNamespace(
        st_mode=0o100444,
        st_uid=1001,
        st_gid=1001,
        st_nlink=1,
        st_size=64,
        st_dev=1,
        st_ino=2,
        st_mtime_ns=3,
    )
    with pytest.raises(ValueError, match="immutable_file_invalid"):
        _immutable_file_identity(metadata, maximum=64)


@pytest.mark.parametrize("raw", [b"a" * 64 + b"\n", b"A" * 64, b"a" * 63])
def test_source_pin_rejects_noncanonical_digest(tmp_path: Path, raw: bytes) -> None:
    manifest, digest = _source_pin(tmp_path)
    manifest.parent.chmod(0o755)
    digest.chmod(0o644)
    digest.write_bytes(raw)
    digest.chmod(0o444)
    manifest.parent.chmod(0o555)
    with pytest.raises(RuntimeError, match="e2e_source_pin_digest_invalid"):
        SourcePinAttestor(
            manifest_path=manifest,
            digest_path=digest,
            error_type=RuntimeError,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            allowed_chain_owners=_chain_owners(manifest.parent),
            chain_anchor=manifest.parent,
        ).open()


@pytest.mark.parametrize(
    ("target", "mode"), [("dir", 0o755), ("manifest", 0o400), ("digest", 0o644)]
)
def test_source_pin_rejects_mutable_or_nonexact_modes(
    tmp_path: Path, target: str, mode: int
) -> None:
    manifest, digest = _source_pin(tmp_path)
    manifest.parent.chmod(0o755)
    {"dir": manifest.parent, "manifest": manifest, "digest": digest}[target].chmod(mode)
    if target != "dir":
        manifest.parent.chmod(0o555)
    with pytest.raises(RuntimeError, match="e2e_source_pin_invalid"):
        SourcePinAttestor(
            manifest_path=manifest,
            digest_path=digest,
            error_type=RuntimeError,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            allowed_chain_owners=_chain_owners(manifest.parent),
            chain_anchor=manifest.parent,
        ).open()


def test_source_pin_executor_rejects_replacement_during_delegate(tmp_path: Path) -> None:
    manifest, digest = _source_pin(tmp_path)

    class ReplacingDelegate:
        def execute(self, *_arguments):
            manifest.parent.chmod(0o755)
            replacement = manifest.parent / "replacement"
            replacement.write_bytes(manifest.read_bytes())
            replacement.chmod(0o444)
            os.replace(replacement, manifest)
            manifest.parent.chmod(0o555)
            return {"verdict": "must-not-escape"}

    executor = SourcePinAttestingExecutor(
        delegate=ReplacingDelegate(),
        manifest_path=manifest,
        digest_path=digest,
        error_type=RuntimeError,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        allowed_chain_owners=_chain_owners(manifest.parent),
        chain_anchor=manifest.parent,
    )
    with pytest.raises(RuntimeError, match="e2e_source_pin_changed"):
        executor.execute()


def _private_directory_executor(
    tmp_path: Path, delegate, *, path: Path | None = None, expected_uid: int | None = None
):
    path = path or tmp_path / "state" / "e2e-mem0-config"
    return PrivateDirectoryAttestingExecutor(
        delegate=delegate,
        attestor=PrivateDirectoryAttestor(
            run_root=tmp_path,
            path=path,
            expected_uid=os.getuid() if expected_uid is None else expected_uid,
            expected_gid=os.getgid(),
            error_type=RuntimeError,
        ),
    )


def _prepare_private_mem0_directory(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    path = state / "e2e-mem0-config"
    path.mkdir(mode=0o700)
    return path


def test_private_mem0_directory_is_attested_and_restart_idempotent(tmp_path: Path) -> None:
    path = _prepare_private_mem0_directory(tmp_path)
    calls = []

    class Delegate:
        def execute(self):
            assert path.is_dir()
            assert path.stat().st_mode & 0o777 == 0o700
            calls.append(True)
            return {"ready": True}

    executor = _private_directory_executor(tmp_path, Delegate())
    assert executor.execute() == {"ready": True}
    assert executor.execute() == {"ready": True}
    assert calls == [True, True]


@pytest.mark.parametrize("existing", ["missing", "regular", "symlink", "unsafe-mode"])
def test_private_mem0_directory_rejects_unsafe_existing_path(tmp_path: Path, existing: str) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    path = state / "e2e-mem0-config"
    if existing == "symlink":
        path.symlink_to(tmp_path)
    elif existing == "regular":
        path.write_text("not-a-directory")
    elif existing == "unsafe-mode":
        path.mkdir(mode=0o755)
    executor = _private_directory_executor(
        tmp_path, type("Delegate", (), {"execute": lambda self: None})()
    )
    with pytest.raises(RuntimeError, match="e2e_child_mem0_dir_invalid"):
        executor.execute()


def test_private_mem0_directory_rejects_wrong_owner_or_outside_path(tmp_path: Path) -> None:
    path = _prepare_private_mem0_directory(tmp_path)
    executor = _private_directory_executor(
        tmp_path,
        type("Delegate", (), {"execute": lambda self: None})(),
        expected_uid=os.getuid() + 1,
    )
    with pytest.raises(RuntimeError, match="e2e_child_mem0_dir_invalid"):
        executor.execute()
    with pytest.raises(RuntimeError, match="e2e_child_mem0_dir_invalid"):
        _private_directory_executor(tmp_path, object(), path=path.parent / "outside")


def test_private_mem0_directory_rejects_replacement_during_child(tmp_path: Path) -> None:
    path = _prepare_private_mem0_directory(tmp_path)

    class ReplacingDelegate:
        def execute(self):
            path.rename(path.parent / "old-e2e-mem0-config")
            path.mkdir(mode=0o700)
            return None

    with pytest.raises(RuntimeError, match="e2e_child_mem0_dir_changed"):
        _private_directory_executor(tmp_path, ReplacingDelegate()).execute()
