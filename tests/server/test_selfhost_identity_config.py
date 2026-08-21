from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from infinity_context_server import selfhost_identity_config as subject


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        subject.SERVICE_TOKEN_ENV: "service-token",
        subject.SELFHOST_ADMIN_DATABASE_URL_ENV: "postgresql+asyncpg://admin:secret@db/ic",
        subject.SELFHOST_MIGRATOR_PASSWORD_ENV: "migrator-secret",
        subject.SELFHOST_RUNTIME_PASSWORD_ENV: "runtime-secret",
        subject.SELFHOST_CANONICAL_WRITER_PASSWORD_ENV: "canonical-secret",
        subject.SELFHOST_REGISTRAR_PASSWORD_ENV: "registrar-secret",
        subject.SELFHOST_SEALER_PASSWORD_ENV: "sealer-secret",
    }
    values.update(overrides)
    return values


def test_load_config_reads_admin_and_five_distinct_passwords() -> None:
    config = subject.load_selfhost_identity_provisioning_config(_environment())

    assert config.admin_database_url.startswith("postgresql+asyncpg://admin:")
    assert config.passwords.values() == (
        "migrator-secret",
        "runtime-secret",
        "canonical-secret",
        "registrar-secret",
        "sealer-secret",
    )


def test_load_config_missing_setting_does_not_echo_other_secrets() -> None:
    environment = _environment()
    environment.pop(subject.SELFHOST_REGISTRAR_PASSWORD_ENV)

    with pytest.raises(RuntimeError) as error:
        subject.load_selfhost_identity_provisioning_config(environment)

    assert str(error.value).endswith(subject.SELFHOST_REGISTRAR_PASSWORD_ENV)
    assert "migrator-secret" not in str(error.value)


def test_load_config_rejects_duplicate_passwords() -> None:
    environment = _environment(**{subject.SELFHOST_SEALER_PASSWORD_ENV: "registrar-secret"})

    with pytest.raises(ValueError, match="must be distinct"):
        subject.load_selfhost_identity_provisioning_config(environment)


def test_load_config_rejects_admin_password_reuse_without_echoing_it() -> None:
    secret = "migrator-secret"
    environment = _environment(
        **{subject.SELFHOST_ADMIN_DATABASE_URL_ENV: (f"postgresql+asyncpg://admin:{secret}@db/ic")}
    )

    with pytest.raises(RuntimeError) as error:
        subject.load_selfhost_identity_provisioning_config(environment)

    assert secret not in str(error.value)


@pytest.mark.parametrize(
    ("name", "value"),
    (
        (subject.SERVICE_TOKEN_ENV, "runtime-secret"),
        (subject.SERVICE_TOKEN_ENV, "secret"),
        (subject.SERVICE_TOKEN_ENV, "change-me-service-token"),
        (subject.SELFHOST_RUNTIME_PASSWORD_ENV, "change-me-runtime"),
    ),
)
def test_load_config_rejects_reused_or_placeholder_service_secrets(
    name: str,
    value: str,
) -> None:
    environment = _environment(**{name: value})

    with pytest.raises(RuntimeError) as error:
        subject.load_selfhost_identity_provisioning_config(environment)

    assert value not in str(error.value)


def test_load_config_rejects_admin_url_without_credentials() -> None:
    environment = _environment(
        **{subject.SELFHOST_ADMIN_DATABASE_URL_ENV: "postgresql+asyncpg://db/ic"}
    )

    with pytest.raises(RuntimeError, match="must include credentials"):
        subject.load_selfhost_identity_provisioning_config(environment)


def test_apply_rotation_uses_explicit_operation_and_disposes_engine(monkeypatch) -> None:
    calls: list[object] = []
    passwords = SimpleNamespace()

    class Engine:
        async def dispose(self) -> None:
            calls.append("disposed")

    engine = Engine()

    async def rotate(observed_engine, observed_passwords) -> None:
        calls.append((observed_engine, observed_passwords))

    monkeypatch.setattr(
        subject,
        "load_selfhost_identity_provisioning_config",
        lambda: SimpleNamespace(admin_database_url="redacted-url", passwords=passwords),
    )
    monkeypatch.setattr(subject, "build_async_engine", lambda _url: engine)
    monkeypatch.setattr(subject, "rotate_selfhost_login_passwords", rotate)

    asyncio.run(subject.apply_selfhost_identity_provisioning(rotate_passwords=True))

    assert calls == [(engine, passwords), "disposed"]
