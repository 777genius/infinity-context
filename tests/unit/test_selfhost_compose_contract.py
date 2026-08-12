from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_selfhost_compose_uses_split_database_identities() -> None:
    compose = (ROOT / "docker-compose.selfhost.yml").read_text(encoding="utf-8")
    env = (ROOT / ".env.selfhost.example").read_text(encoding="utf-8")

    for identity in (
        "ADMIN",
        "MIGRATOR",
        "RUNTIME",
        "CANONICAL_WRITER",
        "REGISTRAR",
        "SEALER",
    ):
        assert f"INFINITY_CONTEXT_SELFHOST_{identity}_PASSWORD=change-me" in env

    assert "image: postgres:18.4-bookworm" in compose
    assert "infinity_context_identity_bootstrap:" in compose
    assert "infinity_context_runtime_acl:" in compose
    assert "infinity_context_seed:" in compose
    assert "python -m infinity_context_server.selfhost_db provision-identities" in compose
    assert "python -m infinity_context_server.selfhost_db reconcile-runtime-acl" in compose


def test_selfhost_compose_does_not_leak_privileged_credentials() -> None:
    compose = (ROOT / "docker-compose.selfhost.yml").read_text(encoding="utf-8")

    identity_bootstrap = compose.split(
        "  infinity_context_identity_bootstrap:", maxsplit=1
    )[1].split("  infinity_context_migrate:", maxsplit=1)[0]
    assert "MEMORY_SERVICE_TOKEN:" in identity_bootstrap
    assert "INFINITY_CONTEXT_SELFHOST_ADMIN_DATABASE_URL:" in identity_bootstrap

    runtime_services = compose.split("  infinity_context_server:", maxsplit=1)[1]
    assert "INFINITY_CONTEXT_SELFHOST_ADMIN_DATABASE_URL" not in runtime_services

    runtime_acl = compose.split("  infinity_context_runtime_acl:", maxsplit=1)[1].split(
        "  infinity_context_seed:", maxsplit=1
    )[0]
    assert "postgresql+asyncpg://infinity_context_migrator:" in runtime_acl
    assert "INFINITY_CONTEXT_SELFHOST_ADMIN_DATABASE_URL" not in runtime_acl
    assert "INFINITY_CONTEXT_SELFHOST_ADMIN_PASSWORD" not in runtime_acl
    assert "INFINITY_CONTEXT_SELFHOST_RUNTIME_PASSWORD" not in runtime_acl
    assert "INFINITY_CONTEXT_SELFHOST_CANONICAL_WRITER_PASSWORD" not in runtime_acl
    assert "INFINITY_CONTEXT_SELFHOST_REGISTRAR_PASSWORD" not in runtime_acl
    assert "INFINITY_CONTEXT_SELFHOST_SEALER_PASSWORD" not in runtime_acl
