from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_core.features.projection_receipts import ProjectionReceiptAuthenticator
from infinity_context_core.ports.managed_cleanup_v4_authority import (
    build_strict_v4_cleanup_authority_readback,
)
from infinity_context_server import memory_comparison_managed_v5_strict_v4_cleanup_cli as cli

RUN, CONTEXT, A2 = "1" * 64, "2" * 64, "3" * 64
KEY_ID, KEY = "cleanup-cli-key", b"strict-v4-cleanup-cli-key-material" * 2


def _invoke(
    journal: Path,
    key_file: Path,
    *args: str,
) -> tuple[int, dict[str, object]]:
    code = cli.main(
        [
            "--journal",
            str(journal),
            "--key-id",
            KEY_ID,
            "--key-file",
            str(key_file),
            *args,
        ]
    )
    return code, {}


def test_cli_create_initiate_and_recover_pending_is_provider_free(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    connectors: dict[str, object] = {}
    key_file = tmp_path / "key"
    key_file.write_bytes(KEY)
    key_file.chmod(0o600)
    readback = build_strict_v4_cleanup_authority_readback(
        run_id_sha256=RUN,
        context_sha256=CONTEXT,
        a2_terminal_sha256=A2,
        expected_index_terminal_sha256=A2,
        preparation_receipt_sha256="a" * 64,
        preparation_receipt_mac_sha256="b" * 64,
        registration_sha256="c" * 64,
        registration_mac_sha256="d" * 64,
        writer_authority_sha256="e" * 64,
        writer_authority_mac_sha256="f" * 64,
        authenticator=ProjectionReceiptAuthenticator(KEY),
        authentication_key_id=KEY_ID,
    )

    class Store:
        def read(self):
            return SimpleNamespace(run_id_sha256=RUN)

        def close(self):
            return None

    class Reader:
        def __init__(self, **kwargs: object) -> None:
            assert callable(kwargs["recover_preparation"])
            connectors["sealer"] = kwargs["connect"]

        async def read_registered_strict_v4(self, run_id_sha256):
            assert run_id_sha256 == RUN
            return readback

    class Registry:
        def __init__(self, **kwargs: object) -> None:
            connectors["registrar"] = kwargs["connect"]

    monkeypatch.setattr(cli.SQLiteStrictV4PreparationReceiptStore, "open", lambda _path: Store())
    monkeypatch.setattr(cli, "AsyncPostgresStrictV4CleanupAuthorityReader", Reader)
    monkeypatch.setattr(cli, "AsyncPostgresCleanupV4ContextAuthorityRegistry", Registry)
    receipt = tmp_path / "receipt.sqlite3"
    receipt.touch()
    registrar_dsn_file = tmp_path / "registrar-postgres.dsn"
    sealer_dsn_file = tmp_path / "sealer-postgres.dsn"
    receipt_key_file = tmp_path / "receipt.key"
    keyring_file = tmp_path / "keyring.json"
    for path, content in (
        (registrar_dsn_file, b"postgresql://registrar"),
        (sealer_dsn_file, b"postgresql://sealer"),
        (receipt_key_file, b"receipt-authentication-key-material" * 2),
        (keyring_file, b"{}"),
    ):
        path.write_bytes(content)
        path.chmod(0o600)
    journal = tmp_path / "journal.sqlite3"
    assert (
        _invoke(
            journal,
            key_file,
            "create",
            "--receipt",
            str(receipt),
            "--registrar-postgres-dsn-file",
            str(registrar_dsn_file),
            "--sealer-postgres-dsn-file",
            str(sealer_dsn_file),
            "--receipt-key-file",
            str(receipt_key_file),
            "--keyring",
            str(keyring_file),
        )[0]
        == 0
    )
    assert json.loads(capsys.readouterr().out)["state"] == "journal_created"
    assert connectors["registrar"] is not connectors["sealer"]
    assert _invoke(journal, key_file, "initiate")[0] == 0
    assert json.loads(capsys.readouterr().out)["receipt"]["state"] == "cleanup_pending"
    hostile_bindings = tmp_path / "hostile-bindings.json"
    hostile_bindings.write_text("{}")
    with pytest.raises(SystemExit):
        _invoke(
            journal,
            key_file,
            "complete",
            "--terminal-bindings",
            str(hostile_bindings),
        )
    capsys.readouterr()
    assert _invoke(journal, key_file, "recover")[0] == 0
    assert json.loads(capsys.readouterr().out)["state"] == "cleanup_pending"


def test_create_requires_explicit_registrar_and_sealer_capability_files() -> None:
    parser = cli._parser()
    common = [
        "--journal",
        "/tmp/journal",
        "--key-id",
        KEY_ID,
        "--key-file",
        "/tmp/key",
        "create",
        "--receipt",
        "/tmp/receipt",
        "--receipt-key-file",
        "/tmp/receipt-key",
        "--keyring",
        "/tmp/keyring",
    ]
    with pytest.raises(SystemExit):
        parser.parse_args([*common, "--postgres-dsn-file", "/tmp/shared"])
    with pytest.raises(SystemExit):
        parser.parse_args([*common, "--registrar-postgres-dsn-file", "/tmp/registrar"])
    with pytest.raises(SystemExit):
        parser.parse_args([*common, "--sealer-postgres-dsn-file", "/tmp/sealer"])


def test_create_wires_each_capability_to_only_its_authority_adapter() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert "connect=connect_registrar" in source
    assert "connect=connect_sealer" in source
    assert "connect=connect," not in source
    assert "args.postgres_dsn_file" not in source


def test_cli_module_does_not_import_provider_or_legacy_cleanup_plan() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")
    composition = Path(
        __import__(
            "infinity_context_server.memory_comparison_managed_v5_strict_v4_cleanup",
            fromlist=["x"],
        ).__file__
    ).read_text(encoding="utf-8")
    combined = source + composition
    assert "benchmark_cleanup_plan" not in combined
    assert "LegacyV2" not in combined
    assert "qdrant_client" not in combined
    assert "graphiti_core" not in combined
    assert "openai" not in combined
    assert "terminal-bindings" not in source
    assert "authority-readback" not in source
    assert "build_cleanup_v4_terminal_bindings" not in source


def test_cleanup_cli_is_registered_as_installed_console_script() -> None:
    project = Path(__file__).resolve().parents[2] / "pyproject.toml"
    assert (
        "infinity-context-managed-strict-v4-cleanup = "
        '"infinity_context_server.memory_comparison_managed_v5_strict_v4_cleanup_cli:main"'
        in project.read_text(encoding="utf-8")
    )


def test_secret_rejects_same_inode_same_size_overwrite_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "cleanup.key"
    path.write_bytes(b"a" * 64)
    path.chmod(0o600)
    before = path.stat()
    real_read = os.read
    mutated = False

    def racing_read(fd: int, size: int) -> bytes:
        nonlocal mutated
        chunk = real_read(fd, size)
        if not mutated:
            mutated = True
            path.write_bytes(b"b" * 64)
            path.chmod(0o600)
            os.utime(
                path,
                ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000),
            )
        return chunk

    monkeypatch.setattr(cli.os, "read", racing_read)
    with pytest.raises(ValueError, match="replaced"):
        cli._secret(path)
    after = path.stat()
    assert (after.st_dev, after.st_ino, after.st_size) == (
        before.st_dev,
        before.st_ino,
        before.st_size,
    )


def test_secret_rejects_concurrent_growth_before_unbounded_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "growing.key"
    path.write_bytes(b"x" * 32)
    path.chmod(0o600)
    calls = 0

    def growing_read(fd: int, size: int) -> bytes:
        nonlocal calls
        del fd, size
        calls += 1
        return b"x" * 32

    monkeypatch.setattr(cli.os, "read", growing_read)
    with pytest.raises(ValueError, match="too large"):
        cli._secret(path, min_bytes=1, max_bytes=64)
    assert calls == 3


@pytest.mark.parametrize("token", [b"NaN", b"Infinity", b"-Infinity"])
def test_cleanup_json_rejects_non_finite_constants(token: bytes) -> None:
    with pytest.raises(ValueError, match="constant"):
        cli._object_bytes(b'{"value":' + token + b"}")
