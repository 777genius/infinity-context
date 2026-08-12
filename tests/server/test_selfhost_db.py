from __future__ import annotations

import argparse
import asyncio
import json

import pytest
from infinity_context_server import selfhost_db as subject


@pytest.mark.parametrize(
    ("command", "rotate_passwords"),
    (("provision-identities", False), ("rotate-passwords", True)),
)
def test_identity_commands_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    rotate_passwords: bool,
) -> None:
    calls: list[bool] = []

    async def apply(*, rotate_passwords: bool = False) -> None:
        calls.append(rotate_passwords)

    monkeypatch.setattr(subject, "apply_selfhost_identity_provisioning", apply)

    result = asyncio.run(subject._run(argparse.Namespace(command=command)))

    assert result == {"operation": command, "status": "ok"}
    assert calls == [rotate_passwords]


def test_reconcile_runtime_acl_uses_migrator_engine_and_disposes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []

    class Engine:
        async def dispose(self) -> None:
            events.append("disposed")

    engine = Engine()

    def build(database_url: str) -> Engine:
        events.append(("build", database_url))
        return engine

    async def reconcile(candidate: object) -> None:
        events.append(("reconcile", candidate))

    monkeypatch.setenv(
        subject.MIGRATOR_DATABASE_URL_ENV,
        "postgresql+asyncpg://migrator:secret@db/infinity_context",
    )
    monkeypatch.setattr(subject, "build_async_engine", build)
    monkeypatch.setattr(subject, "reconcile_runtime_acl", reconcile)

    result = asyncio.run(subject._run(argparse.Namespace(command="reconcile-runtime-acl")))

    assert result == {"operation": "reconcile-runtime-acl", "status": "ok"}
    assert events == [
        ("build", "postgresql+asyncpg://migrator:secret@db/infinity_context"),
        ("reconcile", engine),
        "disposed",
    ]


def test_reconcile_runtime_acl_disposes_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disposed = False

    class Engine:
        async def dispose(self) -> None:
            nonlocal disposed
            disposed = True

    async def fail(_engine: object) -> None:
        raise RuntimeError("acl failed")

    monkeypatch.setenv(
        subject.MIGRATOR_DATABASE_URL_ENV,
        "postgresql+asyncpg://migrator:secret@db/infinity_context",
    )
    monkeypatch.setattr(subject, "build_async_engine", lambda _url: Engine())
    monkeypatch.setattr(subject, "reconcile_runtime_acl", fail)

    with pytest.raises(RuntimeError, match="acl failed"):
        asyncio.run(subject._reconcile_runtime_acl())

    assert disposed is True


@pytest.mark.parametrize(
    ("environment", "message"),
    (
        ({}, "required database setting is missing"),
        (
            {subject.MIGRATOR_DATABASE_URL_ENV: "not a url"},
            "migrator database URL is invalid",
        ),
        (
            {subject.MIGRATOR_DATABASE_URL_ENV: "sqlite:///tmp.db"},
            "migrator database URL must use PostgreSQL",
        ),
        (
            {
                subject.MIGRATOR_DATABASE_URL_ENV: (
                    "postgresql+asyncpg://migrator@db/infinity_context"
                )
            },
            "migrator database URL must include credentials",
        ),
    ),
)
def test_migrator_url_validation_does_not_disclose_input(
    environment: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(RuntimeError, match=message) as exc_info:
        subject._load_migrator_database_url(environment)

    assert "not a url" not in str(exc_info.value)


def test_main_emits_secret_free_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def apply(*, rotate_passwords: bool = False) -> None:
        assert rotate_passwords is False

    monkeypatch.setattr(subject, "apply_selfhost_identity_provisioning", apply)

    subject.main(["provision-identities"])

    output = capsys.readouterr().out
    assert json.loads(output) == {"operation": "provision-identities", "status": "ok"}
    assert "password" not in output.lower()


def test_parser_rejects_unexpected_arguments() -> None:
    with pytest.raises(SystemExit) as exc_info:
        subject._parser().parse_args(["rotate-passwords", "unexpected"])

    assert exc_info.value.code == 2
