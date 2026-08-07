from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from mem0_oss_adapter_v5 import bootstrap


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
    monkeypatch.setattr(bootstrap, "_read_secret_file", lambda _name: "a" * 64)
    monkeypatch.setattr(bootstrap, "_read_pinned_digest_file", lambda _name: "a" * 64)
    monkeypatch.setattr(bootstrap, "verify_source_authority", reject_authority)
    monkeypatch.setattr(bootstrap, "_receipt_authority", forbidden("receipt-runtime"))
    monkeypatch.setattr(bootstrap, "SubscriptionRuntimeClient", forbidden("runtime-client"))
    monkeypatch.setattr(bootstrap, "SqliteOperationState", forbidden("sqlite"))
    monkeypatch.setattr(bootstrap, "_build_pinned_memory", forbidden("mem0-qdrant"))
    with pytest.raises(InvalidPin):
        bootstrap.build_app_from_environment()
    assert events == ["source-authority"]


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
