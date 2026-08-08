from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from mem0_oss_adapter_v5 import bootstrap
from mem0_oss_adapter_v5.source_authority import _issue_verified_source_authority


def test_invalid_source_pin_fails_before_runtime_state_or_provider_initialization(
    monkeypatch,
) -> None:
    events = []

    class InvalidPin(RuntimeError):
        pass

    def reject_authority(**_kwargs):
        events.append("source-authority")
        raise InvalidPin

    def forbidden(name: str):
        def call(*_args, **_kwargs):
            events.append(name)
            raise AssertionError(f"{name} initialized before source authority")

        return call

    monkeypatch.setattr(bootstrap, "SealedInputManifest", lambda _path: object())
    monkeypatch.setattr(bootstrap, "_required_environment", lambda _name: "/tmp/value")
    monkeypatch.setattr(
        bootstrap,
        "_read_secret_file",
        lambda name: ("b" if name == "MEM0_V5_RESULT_HMAC_FILE" else "a") * 64,
    )
    monkeypatch.setattr(bootstrap, "_read_pinned_digest_file", lambda _name: "a" * 64)
    monkeypatch.setattr(bootstrap, "verify_source_authority", reject_authority)
    monkeypatch.setattr(bootstrap, "_receipt_authority", forbidden("receipt-runtime"))
    monkeypatch.setattr(bootstrap, "SubscriptionRuntimeClient", forbidden("runtime-client"))
    monkeypatch.setattr(bootstrap, "SqliteOperationState", forbidden("sqlite"))
    monkeypatch.setattr(bootstrap, "_build_pinned_memory", forbidden("mem0-qdrant"))
    with pytest.raises(InvalidPin):
        bootstrap.build_app_from_environment()
    assert events == ["source-authority"]


def test_state_and_result_hmac_keys_must_be_distinct(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "SealedInputManifest", lambda _path: object())
    monkeypatch.setattr(bootstrap, "_required_environment", lambda _name: "/tmp/value")
    monkeypatch.setattr(bootstrap, "_read_secret_file", lambda _name: "a" * 64)
    with pytest.raises(ValueError, match="adapter_configuration_invalid"):
        bootstrap.build_app_from_environment()


def test_runtime_attestation_root_must_be_distinct_from_every_runtime_secret() -> None:
    distinct = tuple(chr(97 + index) * 32 for index in range(6))
    bootstrap._require_distinct_secrets(*distinct)
    for index in range(len(distinct)):
        duplicate = list(distinct)
        duplicate[index] = distinct[(index + 1) % len(distinct)]
        with pytest.raises(ValueError, match="adapter_configuration_invalid"):
            bootstrap._require_distinct_secrets(*duplicate)


def test_build_app_reaches_real_service_constructor_with_shared_runtime_authority(
    tmp_path: Path, monkeypatch
) -> None:
    source_authority = _issue_verified_source_authority(
        source_commit_sha1="1" * 40,
        source_tree_sha1="2" * 40,
        manifest_sha256=_digest("source-manifest"),
        closure_sha256=_digest("source-closure"),
        phase_c_infinity_commit_sha1="3" * 40,
        phase_c_infinity_tree_sha1="4" * 40,
        phase_c_release_manifest_sha256=_digest("phase-release"),
    )
    receipt_bundle = bootstrap._ReceiptAuthorityBundle(
        authority=SimpleNamespace(),
        binding_commitment_sha256=_digest("runtime-binding"),
        runtime_source_sha256=_digest("runtime-source"),
        route_binding_sha256=_digest("runtime-route"),
    )
    state_path = tmp_path / "state.sqlite3"

    def required(name: str) -> str:
        if name == "MEM0_V5_STATE_DB_FILE":
            return str(state_path)
        return str(tmp_path / name.lower())

    def secret(name: str) -> str:
        if name == "MEM0_V5_RUNTIME_TRANSPORT_ORIGIN_FILE":
            return "http://127.0.0.1:8891"
        return _digest(name)

    monkeypatch.setattr(bootstrap, "_required_environment", required)
    monkeypatch.setattr(bootstrap, "_read_secret_file", secret)
    monkeypatch.setattr(bootstrap, "_read_pinned_digest_file", lambda _name: "a" * 64)
    monkeypatch.setattr(bootstrap, "SealedInputManifest", lambda _path: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "verify_source_authority", lambda **_kwargs: source_authority)
    monkeypatch.setattr(bootstrap, "_receipt_authority", lambda _secret: receipt_bundle)
    monkeypatch.setattr(bootstrap, "SubscriptionRuntimeClient", lambda **_kwargs: SimpleNamespace())
    monkeypatch.setattr(
        bootstrap, "SqliteOperationState", lambda *_args, **_kwargs: SimpleNamespace()
    )
    monkeypatch.setattr(bootstrap, "_build_pinned_memory", lambda _path: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "PinnedMem0Backend", lambda _memory: SimpleNamespace())
    monkeypatch.setattr(bootstrap, "Mem0StorageAdapter", lambda _backend: SimpleNamespace())

    app = bootstrap.build_app_from_environment()

    assert {route.path for route in app.routes} >= {"/health", "/v5/runtime/attest"}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_tampered_phase_c_authority_blocks_runtime_binding_issue(monkeypatch) -> None:
    phase_package = Path(__file__).resolve().parents[2] / "phase-c-canary"
    monkeypatch.syspath_prepend(str(phase_package))
    from phase_c_canary import attestation, runtime_binding

    events = []

    def reject(_authority) -> None:
        events.append("attestation")
        raise attestation.AuthorityError("tampered")

    def forbidden_issue():
        events.append("binding")
        raise AssertionError("runtime binding issued before immutable preflight")

    monkeypatch.setattr(attestation, "verify_immutable_authority", reject)
    monkeypatch.setattr(
        runtime_binding.RuntimeBindingComposition,
        "compose_phase_c_canary",
        forbidden_issue,
    )
    with pytest.raises(attestation.AuthorityError, match="tampered"):
        bootstrap._receipt_authority("receipt-secret")
    assert events == ["attestation"]


def _enable_adapter_imports(monkeypatch) -> None:
    adapter_package = Path(__file__).resolve().parents[2] / "mem0-oss-adapter"
    monkeypatch.syspath_prepend(str(adapter_package))


def test_build_pinned_memory_cold_start_uses_subscription_usage_ledger(
    tmp_path: Path, monkeypatch
) -> None:
    _enable_adapter_imports(monkeypatch)
    from mem0 import Memory
    from mem0_oss_adapter import sdk_oss
    from mem0_oss_adapter.subscription_llm import UsageLedger

    events = []
    expected_config = {"reviewed": True}
    expected_memory = object()

    def pinned_config(settings, *, usage_ledger):
        assert type(usage_ledger) is UsageLedger
        assert settings.state_dir == tmp_path / "mem0"
        events.append("configured")
        return expected_config

    @contextmanager
    def patched_factories():
        events.append("entered")
        yield
        events.append("exited")

    def from_config(config):
        assert config is expected_config
        events.append("constructed")
        return expected_memory

    monkeypatch.setenv("MEM0_V5_QDRANT_ORIGIN", "http://127.0.0.1:6334")
    monkeypatch.setattr(sdk_oss, "pinned_memory_config", pinned_config)
    monkeypatch.setattr(sdk_oss, "_patched_mem0_factories", patched_factories)
    monkeypatch.setattr(Memory, "from_config", staticmethod(from_config))

    assert bootstrap._build_pinned_memory(tmp_path) is expected_memory
    assert (tmp_path / "mem0").stat().st_mode & 0o777 == 0o700
    assert bootstrap._build_pinned_memory(tmp_path) is expected_memory
    assert events == [
        "configured",
        "entered",
        "constructed",
        "exited",
        "configured",
        "entered",
        "constructed",
        "exited",
    ]


def test_build_pinned_memory_rejects_symlinked_state_directory(tmp_path: Path, monkeypatch) -> None:
    _enable_adapter_imports(monkeypatch)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    (state / "mem0").symlink_to(tmp_path)
    monkeypatch.setenv("MEM0_V5_QDRANT_ORIGIN", "http://127.0.0.1:6334")
    with pytest.raises(ValueError, match="adapter_configuration_invalid"):
        bootstrap._build_pinned_memory(state)


def test_build_pinned_memory_rejects_unsafe_existing_state_directory(
    tmp_path: Path, monkeypatch
) -> None:
    _enable_adapter_imports(monkeypatch)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    memory_state = state / "mem0"
    memory_state.mkdir(mode=0o755)
    monkeypatch.setenv("MEM0_V5_QDRANT_ORIGIN", "http://127.0.0.1:6334")
    with pytest.raises(ValueError, match="adapter_configuration_invalid"):
        bootstrap._build_pinned_memory(state)


def _public_digest(tmp_path: Path, raw: bytes = b"a" * 64) -> Path:
    path = tmp_path / "manifest.sha256"
    path.write_bytes(raw)
    path.chmod(0o444)
    return path


def test_public_pinned_digest_reader_accepts_root_owned_read_only_file(
    tmp_path: Path, monkeypatch
) -> None:
    path = _public_digest(tmp_path)
    real_fstat = os.fstat

    def root_owned(descriptor: int):
        value = real_fstat(descriptor)
        fields = {
            name: getattr(value, name)
            for name in (
                "st_mode",
                "st_nlink",
                "st_size",
                "st_dev",
                "st_ino",
                "st_mtime_ns",
            )
        }
        return SimpleNamespace(**fields, st_uid=0, st_gid=0)

    monkeypatch.setenv("PIN_FILE", str(path))
    monkeypatch.setattr(bootstrap.os, "fstat", root_owned)
    assert bootstrap._read_pinned_digest_file("PIN_FILE") == "a" * 64


@pytest.mark.parametrize("raw", [b"a" * 64 + b"\n", b"A" * 64, b"a" * 63])
def test_public_pinned_digest_reader_rejects_noncanonical_bytes(
    tmp_path: Path, monkeypatch, raw: bytes
) -> None:
    path = _public_digest(tmp_path, raw)
    monkeypatch.setenv("PIN_FILE", str(path))
    with pytest.raises(ValueError, match="adapter_configuration_invalid"):
        bootstrap._read_pinned_digest_file("PIN_FILE")


def test_public_pinned_digest_reader_rejects_mutable_mode(tmp_path: Path, monkeypatch) -> None:
    path = _public_digest(tmp_path)
    path.chmod(0o644)
    monkeypatch.setenv("PIN_FILE", str(path))
    with pytest.raises(ValueError, match="adapter_configuration_invalid"):
        bootstrap._read_pinned_digest_file("PIN_FILE")


def test_public_pinned_digest_reader_rejects_path_replacement(tmp_path: Path, monkeypatch) -> None:
    path = _public_digest(tmp_path)
    real_lstat = os.lstat

    def replace_before_lstat(candidate):
        alternate = tmp_path / "replacement"
        alternate.write_bytes(b"a" * 64)
        alternate.chmod(0o444)
        os.replace(alternate, path)
        return real_lstat(candidate)

    monkeypatch.setenv("PIN_FILE", str(path))
    monkeypatch.setattr(bootstrap.os, "lstat", replace_before_lstat)
    with pytest.raises(ValueError, match="adapter_configuration_invalid"):
        bootstrap._read_pinned_digest_file("PIN_FILE")
