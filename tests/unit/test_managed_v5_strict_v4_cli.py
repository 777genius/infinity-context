from __future__ import annotations

import argparse
import inspect
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server import memory_comparison_managed_v5_strict_v4_cli as cli


def test_provider_free_cli_is_registered_and_has_no_live_execution_dependency() -> None:
    root = Path(__file__).resolve().parents[2]
    project = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert (
        "infinity-context-managed-strict-v4-prepare = "
        '"infinity_context_server.memory_comparison_managed_v5_strict_v4_cli:main"'
    ) in project
    source = inspect.getsource(cli)
    for forbidden in (
        "memory_comparison_managed_live_cli",
        "memory_comparison_managed_v5_live_root",
        "prepare_managed_v5_live_cleanup_plan",
        "provider_api_key",
        "OPENAI_API_KEY",
        "MEM0_API_KEY",
    ):
        assert forbidden not in source


def test_cli_exposes_provider_free_preparation_and_canonical_execution() -> None:
    parser = cli._parser()
    help_text = parser.format_help()
    assert (
        "{create-original-pair-authority,prepare,recover,seal,execute-facts,execute-documents}"
        in help_text
    )
    assert "authenticate/reopen the official LongMemEval pair authority" in " ".join(
        help_text.split()
    )
    assert "sealed official LongMemEval corpus" in help_text
    assert "recover_and_seal_strict_v4_writer_authority" in inspect.getsource(cli)
    assert "provider" not in " ".join(
        option for action in parser._actions for option in action.option_strings
    )
    with pytest.raises(SystemExit):
        parser.parse_args(["prepare", "--provider-api-key", "secret"])
    with pytest.raises(SystemExit):
        parser.parse_args(["recover", "--postgres-dsn", "postgresql://secret@host/db"])
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "execute-facts",
                "--request",
                "/request.json",
                "--dataset",
                "/dataset.json",
                "--receipt",
                "/receipt.sqlite3",
                "--postgres-dsn-file",
                "/registrar.dsn",
                "--receipt-key-file",
                "/receipt.key",
                "--keyring",
                "/keyring.json",
            ]
        )


def test_create_original_pair_help_is_bounded_and_provider_free(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = cli._parser()
    with pytest.raises(SystemExit) as raised:
        parser.parse_args(["create-original-pair-authority", "--help"])
    assert raised.value.code == 0
    help_text = capsys.readouterr().out
    normalized_help = " ".join(help_text.split())
    assert "directly from the bounded official LongMemEval bytes" in normalized_help
    assert "Exact replays reopen it without provider calls" in normalized_help
    assert "--request" in help_text
    assert "--dataset" in help_text
    assert "--keyring" in help_text
    assert "--postgres-dsn" not in help_text
    assert "--receipt" not in help_text

    args = parser.parse_args(
        [
            "create-original-pair-authority",
            "--request",
            "/request.json",
            "--dataset",
            "/official-longmemeval.json",
            "--keyring",
            "/keyring.json",
        ]
    )
    assert args.command == "create-original-pair-authority"
    assert args.dataset == Path("/official-longmemeval.json")


@pytest.mark.anyio
async def test_create_original_pair_composes_exact_official_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}
    pair_path = tmp_path / "original-pairs.sqlite3"
    pair_key = b"p" * 32

    class Keys:
        def resolve(self, *, purpose: str, key_id: str) -> bytes:
            observed["key_binding"] = (purpose, key_id)
            return pair_key

    class Pair:
        profile_id = "mem0-longmemeval-top50-v1"
        dataset_sha256 = "1" * 64
        terminal_commitment_sha256 = "2" * 64
        operation_count = 124_344
        original_pair_slot_count = 124_345

        def close(self) -> None:
            observed["pair_closed"] = True

    projection = SimpleNamespace(case_manifest_sha256="3" * 64)
    material = SimpleNamespace(
        profile_id="mem0-longmemeval-top50-v1",
        preparation={
            "case_manifest_sha256": projection.case_manifest_sha256,
            "original_pair_path": str(pair_path),
            "original_pair_key_id": "pair-key",
        },
        dataset_bytes=b"exact official bytes",
        projection=projection,
        manifest="manifest",
        request={"admission_commitment_sha256": "4" * 64},
        keys=Keys(),
    )
    pair = Pair()

    def create_or_open(
        cls: object, path: Path, *, dataset_bytes: bytes, authentication_key: bytes
    ) -> Pair:
        del cls
        observed["create_or_open"] = (path, dataset_bytes, authentication_key)
        return pair

    def projector(**values: object) -> object:
        observed["projector"] = values
        return object()

    monkeypatch.setattr(cli, "_run_material", lambda args: material)
    monkeypatch.setattr(
        cli.SQLiteOriginalPairIdentityAuthority,
        "create_or_open",
        classmethod(create_or_open),
    )
    monkeypatch.setattr(cli, "ManagedV5CleanupV4OperationProjector", projector)

    result = await cli._create_original_pair_authority(argparse.Namespace())
    assert observed["key_binding"] == ("original-pair", "pair-key")
    assert observed["create_or_open"] == (
        pair_path,
        b"exact official bytes",
        pair_key,
    )
    assert observed["projector"] == {
        "projection": projection,
        "manifest_authority": "manifest",
        "admission_commitment_sha256": "4" * 64,
        "profile_id": "mem0-longmemeval-top50-v1",
        "original_pair_authority": pair,
    }
    assert result["case_manifest_sha256"] == "3" * 64
    assert result["provider_calls"] == 0
    assert len(str(result["binding_commitment_sha256"])) == 64
    assert len(str(result["binding_mac_sha256"])) == 64
    assert observed["pair_closed"] is True


def test_original_pair_material_rejects_request_case_manifest_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}
    profile = object()
    projection = SimpleNamespace(cases=("case",), case_manifest_sha256="a" * 64)
    request = {
        "profile_id": "mem0-longmemeval-top50-v1",
        "projection_run_id": "run",
        "run_nonce_commitment_sha256": "1" * 64,
        "runtime_probe_nonce_sha256": "2" * 64,
        "backend_targets": [
            {
                "backend_role": "infinity-context",
                "target_identity_sha256": "3" * 64,
            }
        ],
        "current_date": "2026-08-10",
        "preparation": {"case_manifest_sha256": "0" * 64},
    }

    def build_projection(**values: object) -> SimpleNamespace:
        observed.update(values)
        return projection

    monkeypatch.setattr(cli, "_request", lambda path: request)
    monkeypatch.setattr(cli, "resolve_full_comparison_profile", lambda profile_id: profile)
    monkeypatch.setattr(cli, "_bound_input", lambda path, *, max_bytes: b"official")
    monkeypatch.setattr(cli, "build_managed_public_run_projection", build_projection)
    monkeypatch.setattr(
        cli,
        "ManagedMem0V5ManifestProjector",
        lambda: SimpleNamespace(project=lambda cases, *, current_date: "manifest"),
    )
    monkeypatch.setattr(cli, "_FileKeyIdentityAuthority", lambda path: object())

    with pytest.raises(ValueError, match="case manifest binding"):
        cli._run_material(
            argparse.Namespace(
                request=tmp_path / "request.json",
                dataset=tmp_path / "dataset.json",
                keyring=tmp_path / "keyring.json",
            )
        )
    assert observed["profile"] is profile
    assert observed["dataset_bytes"] == b"official"
    assert observed["scope"] == "full"


def test_document_projector_opens_the_created_pair_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}
    pair_path = tmp_path / "original-pairs.sqlite3"
    pair = SimpleNamespace(close=lambda: observed.update(pair_closed=True))

    class Keys:
        def resolve(self, *, purpose: str, key_id: str) -> bytes:
            observed["key_binding"] = (purpose, key_id)
            return b"k" * 32

    run_material = SimpleNamespace(
        profile_id="mem0-longmemeval-top50-v1",
        preparation={
            "original_pair_path": str(pair_path),
            "original_pair_key_id": "pair-key",
        },
        projection="projection",
        manifest="manifest",
        request={"admission_commitment_sha256": "a" * 64},
        keys=Keys(),
    )

    def open_pair(cls: object, path: Path, *, authentication_key: bytes) -> SimpleNamespace:
        del cls
        observed["open"] = (path, authentication_key)
        return pair

    monkeypatch.setattr(cli, "_run_material", lambda args: run_material)
    monkeypatch.setattr(
        cli.SQLiteOriginalPairIdentityAuthority,
        "open",
        classmethod(open_pair),
    )
    monkeypatch.setattr(
        cli,
        "ManagedV5CleanupV4OperationProjector",
        lambda **values: observed.update(projector=values) or "projector",
    )
    material = cli._projector_material(argparse.Namespace())
    assert observed["open"] == (pair_path, b"k" * 32)
    assert observed["projector"]["original_pair_authority"] is pair
    assert material.projector == "projector"
    material.close()
    assert observed["pair_closed"] is True


def test_execute_documents_help_requires_distinct_document_writer_capability(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = cli._parser()
    with pytest.raises(SystemExit) as raised:
        parser.parse_args(["execute-documents", "--help"])
    assert raised.value.code == 0
    help_text = capsys.readouterr().out
    assert "--document-writer-postgres-dsn-file" in help_text
    assert "idempotently ingest" in help_text
    assert "124,344 official documents" in help_text

    required = [
        "execute-documents",
        "--request",
        "/request.json",
        "--dataset",
        "/dataset.json",
        "--receipt",
        "/receipt.sqlite3",
        "--postgres-dsn-file",
        "/registrar.dsn",
        "--receipt-key-file",
        "/receipt.key",
        "--keyring",
        "/keyring.json",
    ]
    with pytest.raises(SystemExit):
        parser.parse_args(required)
    args = parser.parse_args(
        [
            *required,
            "--document-writer-postgres-dsn-file",
            "/document-writer.dsn",
        ]
    )
    assert args.command == "execute-documents"
    assert args.postgres_dsn_file == Path("/registrar.dsn")
    assert args.document_writer_postgres_dsn_file == Path("/document-writer.dsn")


def test_secret_loader_rejects_symlink_hardlink_and_public_mode(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    secret = tmp_path / "key"
    secret.write_bytes(b"k" * 32)
    secret.chmod(0o600)
    assert cli._secret(secret) == b"k" * 32
    link = tmp_path / "link"
    link.symlink_to(secret)
    with pytest.raises((OSError, ValueError)):
        cli._secret(link)
    link.unlink()
    hardlink = tmp_path / "hardlink"
    os.link(secret, hardlink)
    with pytest.raises(ValueError, match="unsafe"):
        cli._secret(secret)
    hardlink.unlink()
    secret.chmod(0o640)
    with pytest.raises(ValueError, match="unsafe"):
        cli._secret(secret)


def test_cli_error_boundary_does_not_echo_connection_or_secret_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fail(args: object) -> object:
        raise RuntimeError("postgresql://user:password@private-host/db")

    monkeypatch.setattr(cli, "_recover", fail)
    result = cli.main(
        [
            "recover",
            "--receipt",
            "/private/receipt.sqlite3",
            "--postgres-dsn-file",
            "/private/postgres.dsn",
            "--receipt-key-file",
            "/private/receipt.key",
            "--keyring",
            "/private/keyring.json",
        ]
    )
    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == "strict-v4 preparation failed\n"


@pytest.mark.anyio
async def test_seal_command_calls_recover_verify_seal_and_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = tmp_path / "receipt.sqlite3"
    receipt.touch()
    observed: dict[str, object] = {}

    class Store:
        def close(self) -> None:
            observed["closed"] = True

    class Authority:
        def payload(self) -> dict[str, object]:
            return {"sealed": True}

    async def seam(**values: object) -> Authority:
        observed.update(values)
        await observed["writer_connect"]()  # type: ignore[operator]
        return Authority()

    async def connect_factory(dsn: str) -> object:
        observed["writer_dsn"] = dsn
        return object()

    monkeypatch.setattr(cli, "_secret", lambda path: b"k" * 32)
    monkeypatch.setattr(cli, "_postgres_dsn", lambda path: path.name)
    monkeypatch.setattr(cli, "_FileKeyIdentityAuthority", lambda path: object())
    monkeypatch.setattr(cli, "_connect_factory", connect_factory)
    monkeypatch.setattr(
        cli,
        "_registry",
        lambda dsn, authenticator: observed.update(registration_dsn=dsn) or "registry",
    )
    monkeypatch.setattr(
        cli.SQLiteStrictV4PreparationReceiptStore,
        "open",
        classmethod(lambda cls, path: Store()),
    )
    monkeypatch.setattr(
        cli,
        "AsyncPostgresStrictV4WriterAuthority",
        lambda **kw: observed.update(writer_connect=kw["connect"]) or "writer",
    )
    monkeypatch.setattr(cli, "recover_and_seal_strict_v4_writer_authority", seam)
    sealed_at = datetime(2026, 8, 9, tzinfo=UTC)
    result = await cli._seal(
        argparse.Namespace(
            receipt=receipt,
            postgres_dsn_file=tmp_path / "postgres.dsn",
            seal_postgres_dsn_file=tmp_path / "seal-postgres.dsn",
            receipt_key_file=tmp_path / "receipt.key",
            keyring=tmp_path / "keyring.json",
            sealed_at=sealed_at.isoformat(),
        )
    )
    assert result == {"sealed": True}
    assert observed["registration_port"] == "registry"
    assert observed["registration_dsn"] == "postgres.dsn"
    assert observed["writer_dsn"] == "seal-postgres.dsn"
    assert observed["writer_authority_port"] == "writer"
    assert observed["sealed_at"] == sealed_at
    assert observed["closed"] is True


@pytest.mark.anyio
async def test_execute_facts_rebuilds_projection_and_uses_separate_writer_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    class Material:
        projector = SimpleNamespace(profile_id="mem0-locomo-top50-v1")
        keys = "keys"
        preparation = {}

        def close(self) -> None:
            observed["material_closed"] = True

    receipt = SimpleNamespace(
        receipt_sha256="1" * 64,
        receipt_mac_sha256="2" * 64,
        run_id_sha256="3" * 64,
        expected_index_terminal_sha256="4" * 64,
        a2_context=SimpleNamespace(context_sha256="5" * 64),
    )

    class Authority:
        def __init__(self) -> None:
            self.receipt = receipt

        def close(self) -> None:
            observed["authority_closed"] = True

    class Store:
        def close(self) -> None:
            observed["store_closed"] = True

    class Runtime:
        def __init__(self, **values: object) -> None:
            observed["runtime_init"] = values

        async def execute(self, **values: object) -> object:
            observed["runtime_execute"] = values
            return SimpleNamespace(payload=lambda: {"operation_count": 5_882})

        async def close(self) -> None:
            observed["runtime_closed"] = True

    async def recover(**values: object) -> Authority:
        observed["recover"] = values
        return Authority()

    monkeypatch.setattr(cli, "_projector_material", lambda args: Material())
    monkeypatch.setattr(cli, "_secret", lambda path: b"k" * 32)
    monkeypatch.setattr(cli, "_postgres_dsn", lambda path: path.name)
    monkeypatch.setattr(cli, "_registry", lambda dsn, auth: ("registry", dsn))
    monkeypatch.setattr(cli, "recover_strict_v4_fact_authority", recover)
    monkeypatch.setattr(cli, "_validate_execution_material", lambda material, value: "space")
    monkeypatch.setattr(cli, "StrictV4FactIngestRuntime", Runtime)
    monkeypatch.setattr(
        cli.SQLiteStrictV4PreparationReceiptStore,
        "open",
        classmethod(lambda cls, path: Store()),
    )
    result = await cli._execute_facts(
        argparse.Namespace(
            request=tmp_path / "request.json",
            dataset=tmp_path / "dataset.json",
            receipt=tmp_path / "receipt.sqlite3",
            postgres_dsn_file=tmp_path / "registrar.dsn",
            fact_writer_postgres_dsn_file=tmp_path / "fact-writer.dsn",
            receipt_key_file=tmp_path / "receipt.key",
            keyring=tmp_path / "keyring.json",
        )
    )
    assert observed["recover"]["registration_port"] == ("registry", "registrar.dsn")
    assert observed["recover"]["expected_projector"] is Material.projector
    assert observed["runtime_init"]["database_url"] == "fact-writer.dsn"
    assert observed["runtime_execute"] == {
        "projector": Material.projector,
        "space_slug": "space",
        "preparation_receipt": receipt,
        "authenticator": observed["recover"]["authenticator"],
    }
    assert result == {"operation_count": 5_882}
    assert observed["runtime_closed"] is True
    assert observed["authority_closed"] is True
    assert observed["store_closed"] is True
    assert observed["material_closed"] is True


@pytest.mark.anyio
async def test_execute_documents_recovers_exact_authority_and_uses_document_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    class Material:
        projector = SimpleNamespace(profile_id="mem0-longmemeval-top50-v1")
        keys = "keys"
        preparation = {}

        def close(self) -> None:
            observed["material_closed"] = True

    receipt = SimpleNamespace(
        receipt_sha256="1" * 64,
        receipt_mac_sha256="2" * 64,
        run_id_sha256="3" * 64,
        expected_index_terminal_sha256="4" * 64,
        a2_context=SimpleNamespace(context_sha256="5" * 64),
    )

    class Authority:
        def __init__(self) -> None:
            self.receipt = receipt

        def close(self) -> None:
            observed["authority_closed"] = True

    class Store:
        def close(self) -> None:
            observed["store_closed"] = True

    class Runtime:
        def __init__(self, **values: object) -> None:
            observed["runtime_init"] = values

        async def execute(self, **values: object) -> object:
            observed["runtime_execute"] = values
            return SimpleNamespace(
                payload=lambda: {
                    "document_count": 124_344,
                    "replayed_count": 124_344,
                    "provider_calls": 0,
                }
            )

        async def close(self) -> None:
            observed["runtime_closed"] = True

    async def recover(**values: object) -> Authority:
        observed["recover"] = values
        authority = Authority()
        observed["recovered_authority"] = authority
        return authority

    monkeypatch.setattr(cli, "_projector_material", lambda args: Material())
    monkeypatch.setattr(cli, "_secret", lambda path: b"k" * 32)
    monkeypatch.setattr(cli, "_postgres_dsn", lambda path: path.name)
    monkeypatch.setattr(cli, "_registry", lambda dsn, auth: ("registry", dsn))
    monkeypatch.setattr(cli, "recover_strict_v4_document_authority", recover)
    monkeypatch.setattr(cli, "_validate_execution_material", lambda material, value: "space")
    monkeypatch.setattr(cli, "StrictV4DocumentIngestRuntime", Runtime)
    monkeypatch.setattr(
        cli.SQLiteStrictV4PreparationReceiptStore,
        "open",
        classmethod(lambda cls, path: Store()),
    )
    result = await cli._execute_documents(
        argparse.Namespace(
            request=tmp_path / "request.json",
            dataset=tmp_path / "dataset.json",
            receipt=tmp_path / "receipt.sqlite3",
            postgres_dsn_file=tmp_path / "registrar.dsn",
            document_writer_postgres_dsn_file=tmp_path / "document-writer.dsn",
            receipt_key_file=tmp_path / "receipt.key",
            keyring=tmp_path / "keyring.json",
        )
    )
    assert observed["recover"]["registration_port"] == ("registry", "registrar.dsn")
    assert observed["recover"]["expected_projector"] is Material.projector
    assert observed["runtime_init"] == {
        "database_url": "document-writer.dsn",
        "authority": observed["recovered_authority"],
    }
    assert observed["runtime_execute"] == {
        "projector": Material.projector,
        "space_slug": "space",
        "preparation_receipt": receipt,
        "authenticator": observed["recover"]["authenticator"],
    }
    assert result == {
        "document_count": 124_344,
        "replayed_count": 124_344,
        "provider_calls": 0,
    }
    assert observed["runtime_closed"] is True
    assert observed["authority_closed"] is True
    assert observed["store_closed"] is True
    assert observed["material_closed"] is True


def test_private_config_is_bounded_and_json_is_strict(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    short_dsn = tmp_path / "postgres.dsn"
    short_dsn.write_text("pg://x", encoding="utf-8")
    short_dsn.chmod(0o600)
    assert cli._postgres_dsn(short_dsn) == "pg://x"
    with pytest.raises(ValueError, match="duplicate"):
        cli._strict_json('{"a":1,"a":2}')
    with pytest.raises(ValueError, match="constant"):
        cli._strict_json('{"a":NaN}')
    oversized = tmp_path / "oversized"
    oversized.write_bytes(b"k" * ((1 << 20) + 1))
    oversized.chmod(0o600)
    with pytest.raises(ValueError, match="size"):
        cli._secret(oversized)


def test_bound_input_rejects_oversize_and_rename_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "request.json"
    path.write_bytes(b'{"value":1}')
    with pytest.raises(ValueError, match="unsafe"):
        cli._bound_input(path, max_bytes=4)

    moved = tmp_path / "moved-request.json"
    replacement = b'{"replacement":true}'
    real_read = os.read
    replaced = False

    def racing_read(fd: int, size: int) -> bytes:
        nonlocal replaced
        chunk = real_read(fd, size)
        if not replaced:
            replaced = True
            path.rename(moved)
            path.write_bytes(replacement)
        return chunk

    monkeypatch.setattr(cli.os, "read", racing_read)
    with pytest.raises(ValueError, match="changed"):
        cli._bound_input(path, max_bytes=1024)
    assert path.read_bytes() == replacement


def test_secret_rejects_same_inode_same_size_overwrite_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "secret.key"
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


def test_bounded_read_rejects_concurrent_growth_before_unbounded_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "growing.input"
    path.write_bytes(b"x" * 32)
    path.chmod(0o600)
    calls = 0

    def growing_read(fd: int, size: int) -> bytes:
        nonlocal calls
        del fd, size
        calls += 1
        return b"x" * 32

    monkeypatch.setattr(cli.os, "read", growing_read)
    with pytest.raises(ValueError, match="size"):
        cli._secret(path, min_bytes=1, max_bytes=64)
    assert calls == 3
    calls = 0
    with pytest.raises(ValueError, match="too large"):
        cli._bound_input(path, max_bytes=64)
    assert calls == 3
