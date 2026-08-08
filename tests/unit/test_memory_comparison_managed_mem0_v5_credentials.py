from __future__ import annotations

import copy
import gc
import os
import pickle
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from infinity_context_server import memory_comparison_managed_mem0_v5_credentials as module
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    ManagedMem0V5CredentialError,
    ManagedMem0V5CredentialPaths,
    ReadOnceManagedMem0V5BearerToken,
    ReadOnceManagedMem0V5CheckpointHeadKey,
    ReadOnceManagedMem0V5CheckpointSigningKey,
    ReadOnceManagedMem0V5EvidenceKey,
    ReadOnceManagedMem0V5ReceiptSecret,
    load_managed_mem0_v5_credentials,
)

_NAMES = ("bearer", "evidence", "receipt", "checkpoint", "head")


def _secret(name: str) -> bytes:
    return (name + "-" + name[0] * 40).encode()


def _paths(root: Path, *, values: tuple[bytes, ...] | None = None) -> ManagedMem0V5CredentialPaths:
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    for name, value in zip(_NAMES, values or tuple(_secret(name) for name in _NAMES), strict=True):
        path = root / name
        path.write_bytes(value)
        path.chmod(0o600)
    return ManagedMem0V5CredentialPaths(*(root / name for name in _NAMES))


def test_loads_distinct_private_files_into_typed_read_once_capabilities(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "credentials")
    capabilities = load_managed_mem0_v5_credentials(paths)

    assert type(capabilities.bearer_token) is ReadOnceManagedMem0V5BearerToken
    assert type(capabilities.evidence_key) is ReadOnceManagedMem0V5EvidenceKey
    assert type(capabilities.receipt_secret) is ReadOnceManagedMem0V5ReceiptSecret
    assert type(capabilities.checkpoint_signing_key) is ReadOnceManagedMem0V5CheckpointSigningKey
    assert type(capabilities.checkpoint_head_key) is ReadOnceManagedMem0V5CheckpointHeadKey
    rendered = repr(capabilities)
    for name in _NAMES:
        assert _secret(name).decode() not in rendered

    assert capabilities.bearer_token.consume() == _secret("bearer").decode()
    assert capabilities.evidence_key.consume() == _secret("evidence")
    assert capabilities.receipt_secret.consume() == _secret("receipt").decode()
    assert capabilities.checkpoint_signing_key.consume() == _secret("checkpoint")
    assert capabilities.checkpoint_head_key.consume() == _secret("head")
    with pytest.raises(ManagedMem0V5CredentialError) as replay:
        capabilities.evidence_key.consume()
    assert replay.value.code == "managed_mem0_v5_credential_replayed"


def test_capability_is_single_consumer_under_concurrency(tmp_path: Path) -> None:
    capabilities = load_managed_mem0_v5_credentials(_paths(tmp_path / "credentials"))
    capability = capabilities.bearer_token

    def consume() -> str:
        try:
            return capability.consume()
        except ManagedMem0V5CredentialError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = tuple(executor.map(lambda _: consume(), range(16)))

    assert outcomes.count(_secret("bearer").decode()) == 1
    assert outcomes.count("managed_mem0_v5_credential_replayed") == 15


@pytest.mark.parametrize(
    ("target", "mode"),
    (("directory", 0o750), ("file", 0o640)),
)
def test_rejects_non_private_modes(tmp_path: Path, target: str, mode: int) -> None:
    paths = _paths(tmp_path / "credentials")
    if target == "directory":
        paths.bearer_token.parent.chmod(mode)
    else:
        paths.bearer_token.chmod(mode)

    with pytest.raises(ManagedMem0V5CredentialError) as rejected:
        load_managed_mem0_v5_credentials(paths)
    assert rejected.value.code == "managed_mem0_v5_credential_unavailable"


def test_rejects_symlink_and_hardlink_secret_files(tmp_path: Path) -> None:
    symlink_paths = _paths(tmp_path / "symlink")
    symlink_paths.bearer_token.unlink()
    symlink_paths.bearer_token.symlink_to(symlink_paths.evidence_key)
    with pytest.raises(ManagedMem0V5CredentialError):
        load_managed_mem0_v5_credentials(symlink_paths)

    hardlink_paths = _paths(tmp_path / "hardlink")
    hardlink_paths.bearer_token.unlink()
    os.link(hardlink_paths.evidence_key, hardlink_paths.bearer_token)
    with pytest.raises(ManagedMem0V5CredentialError):
        load_managed_mem0_v5_credentials(hardlink_paths)


def test_rejects_duplicate_secret_values_across_distinct_inodes(tmp_path: Path) -> None:
    duplicate = _secret("same")
    values = (duplicate, duplicate, _secret("a"), _secret("b"), _secret("c"))
    with pytest.raises(ManagedMem0V5CredentialError) as rejected:
        load_managed_mem0_v5_credentials(_paths(tmp_path / "credentials", values=values))
    assert rejected.value.code == "managed_mem0_v5_credential_roles_not_distinct"


@pytest.mark.parametrize("value", (b"", b"x" * 4_097))
def test_rejects_empty_and_oversized_credentials(tmp_path: Path, value: bytes) -> None:
    values = (value, _secret("e"), _secret("r"), _secret("c"), _secret("h"))
    with pytest.raises(ManagedMem0V5CredentialError) as rejected:
        load_managed_mem0_v5_credentials(_paths(tmp_path / "credentials", values=values))
    assert rejected.value.code == "managed_mem0_v5_credential_unavailable"


@pytest.mark.parametrize("index", (0, 2))
@pytest.mark.parametrize("unsafe", ("\n", "\x7f", "\u200b", "\u202e"))
def test_rejects_unsafe_text_secret_before_capability_issue(
    tmp_path: Path, index: int, unsafe: str
) -> None:
    values = list(_secret(name) for name in _NAMES)
    values[index] = ("x" * 31 + unsafe).encode()

    with pytest.raises(ManagedMem0V5CredentialError) as rejected:
        load_managed_mem0_v5_credentials(_paths(tmp_path / "credentials", values=tuple(values)))

    assert rejected.value.code == "managed_mem0_v5_credential_unavailable"


def test_rejects_inode_replacement_between_precheck_and_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path / "credentials")
    real_stat = module.os.stat
    replaced = False

    def racing_stat(path, *args, **kwargs):
        nonlocal replaced
        result = real_stat(path, *args, **kwargs)
        if path == paths.bearer_token.name and not replaced:
            replaced = True
            replacement = paths.bearer_token.parent / "replacement"
            replacement.write_bytes(_secret("replacement"))
            replacement.chmod(0o600)
            replacement.replace(paths.bearer_token)
        return result

    monkeypatch.setattr(module.os, "stat", racing_stat)
    with pytest.raises(ManagedMem0V5CredentialError) as rejected:
        load_managed_mem0_v5_credentials(paths)
    assert rejected.value.code == "managed_mem0_v5_credential_unavailable"


def test_partial_load_failure_wipes_already_read_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = ManagedMem0V5CredentialPaths(*(tmp_path / name for name in _NAMES))
    first = module._LoadedSecret(bytearray(_secret("first")), (1, 1))
    calls = 0

    def fail_second(path: Path):
        nonlocal calls
        del path
        calls += 1
        if calls == 1:
            return first
        raise ManagedMem0V5CredentialError("managed_mem0_v5_credential_unavailable")

    monkeypatch.setattr(module, "_read_private_secret", fail_second)
    with pytest.raises(ManagedMem0V5CredentialError):
        load_managed_mem0_v5_credentials(paths)
    assert first.value == bytearray()


def test_capabilities_do_not_copy_pickle_or_render_secrets(tmp_path: Path) -> None:
    capabilities = load_managed_mem0_v5_credentials(_paths(tmp_path / "credentials"))
    with pytest.raises(TypeError, match="noncopyable"):
        copy.copy(capabilities)
    with pytest.raises(TypeError, match="nonserializable"):
        pickle.dumps(capabilities)
    assert _secret("bearer").decode() not in repr(capabilities.bearer_token)


def test_partial_read_and_post_read_stat_failures_wipe_local_buffer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path / "partial-read")
    real_read = module.os.read
    real_wipe = module._wipe
    wiped: list[bytes] = []
    reads = 0

    def failing_read(descriptor: int, size: int) -> bytes:
        nonlocal reads
        reads += 1
        if reads == 2:
            raise OSError("injected partial read failure")
        return real_read(descriptor, size)

    def tracking_wipe(value: bytearray) -> None:
        wiped.append(bytes(value))
        real_wipe(value)

    monkeypatch.setattr(module.os, "read", failing_read)
    monkeypatch.setattr(module, "_wipe", tracking_wipe)
    with pytest.raises(ManagedMem0V5CredentialError):
        load_managed_mem0_v5_credentials(paths)
    assert _secret("bearer") in wiped

    monkeypatch.setattr(module.os, "read", real_read)
    paths = _paths(tmp_path / "post-stat")
    real_stat = module.os.stat
    stats = 0

    def failing_stat(*args, **kwargs):
        nonlocal stats
        stats += 1
        if stats == 2:
            raise OSError("injected post-read stat failure")
        return real_stat(*args, **kwargs)

    monkeypatch.setattr(module.os, "stat", failing_stat)
    with pytest.raises(ManagedMem0V5CredentialError):
        load_managed_mem0_v5_credentials(paths)
    assert wiped.count(_secret("bearer")) >= 2


def test_capability_constructor_failure_unwinds_created_capabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path / "credentials")
    real_bearer = module.ReadOnceManagedMem0V5BearerToken
    real_evidence = module.ReadOnceManagedMem0V5EvidenceKey
    buffers: list[bytearray] = []

    def bearer(value: bytearray):
        capability = real_bearer(value)
        assert capability._value is not None
        buffers.append(capability._value)
        return capability

    def evidence(value: bytearray):
        capability = real_evidence(value)
        assert capability._value is not None
        buffers.append(capability._value)
        return capability

    def fail_receipt(value: bytearray):
        del value
        raise RuntimeError("injected constructor failure")

    monkeypatch.setattr(module, "ReadOnceManagedMem0V5BearerToken", bearer)
    monkeypatch.setattr(module, "ReadOnceManagedMem0V5EvidenceKey", evidence)
    monkeypatch.setattr(module, "ReadOnceManagedMem0V5ReceiptSecret", fail_receipt)
    with pytest.raises(RuntimeError, match="constructor failure"):
        load_managed_mem0_v5_credentials(paths)
    assert len(buffers) == 2
    assert all(value == bytearray() for value in buffers)


def test_bundle_and_capability_close_are_idempotent_and_context_managed(
    tmp_path: Path,
) -> None:
    capabilities = load_managed_mem0_v5_credentials(_paths(tmp_path / "credentials"))
    capability_buffers = [
        capability._value
        for capability in (
            capabilities.bearer_token,
            capabilities.evidence_key,
            capabilities.receipt_secret,
            capabilities.checkpoint_signing_key,
            capabilities.checkpoint_head_key,
        )
    ]
    with capabilities as entered:
        assert entered is capabilities
    capabilities.close()
    assert all(value == bytearray() for value in capability_buffers)
    with pytest.raises(ManagedMem0V5CredentialError, match="replayed"):
        capabilities.evidence_key.consume()


def test_individual_capability_context_and_finalizer_wipe_unconsumed_value() -> None:
    capability = ReadOnceManagedMem0V5EvidenceKey(bytearray(_secret("ephemeral")))
    context_buffer = capability._value
    with capability as entered:
        assert entered is capability
    capability.close()
    assert context_buffer == bytearray()

    finalized = ReadOnceManagedMem0V5EvidenceKey(bytearray(_secret("finalized")))
    finalizer_buffer = finalized._value
    del finalized
    gc.collect()
    assert finalizer_buffer == bytearray()
