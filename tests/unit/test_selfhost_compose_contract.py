from pathlib import Path

ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "infinity-context-ci.yml"


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
    assert "infinity_context_locator_index_bootstrap:" in compose
    assert "infinity_context_runtime_acl:" in compose
    assert "infinity_context_seed:" in compose
    assert "python -m infinity_context_server.selfhost_db provision-identities" in compose
    assert "python -m infinity_context_server.db bootstrap-locator-indexes" in compose
    assert "python -m infinity_context_server.selfhost_db reconcile-runtime-acl" in compose


def test_selfhost_locator_indexes_fail_closed_before_runtime_acl() -> None:
    compose = (ROOT / "docker-compose.selfhost.yml").read_text(encoding="utf-8")

    bootstrap = compose.split("  infinity_context_locator_index_bootstrap:", maxsplit=1)[1].split(
        "  infinity_context_runtime_acl:", maxsplit=1
    )[0]
    runtime_acl = compose.split("  infinity_context_runtime_acl:", maxsplit=1)[1].split(
        "  infinity_context_seed:", maxsplit=1
    )[0]

    assert "postgresql+asyncpg://infinity_context_migrator:" in bootstrap
    assert "python -m infinity_context_server.db bootstrap-locator-indexes" in bootstrap
    assert "infinity_context_migrate:" in bootstrap
    assert "condition: service_completed_successfully" in bootstrap
    assert "infinity_context_locator_index_bootstrap:" in runtime_acl
    assert "condition: service_completed_successfully" in runtime_acl


def test_local_runtime_commands_bootstrap_locator_indexes_after_upgrade() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    for service, following_service in (
        ("infinity_context_server", "infinity_context_worker"),
        ("infinity_context_server_full", "infinity_context_worker_full"),
    ):
        service_contract = compose.split(f"  {service}:", maxsplit=1)[1].split(
            f"  {following_service}:", maxsplit=1
        )[0]
        upgrade = service_contract.index("python -m infinity_context_server.db upgrade")
        bootstrap = service_contract.index(
            "python -m infinity_context_server.db bootstrap-locator-indexes"
        )
        runtime = service_contract.index("python -m infinity_context_server.main")

        assert upgrade < bootstrap < runtime


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


def test_ci_runs_isolated_pg16_to_pg18_restore_upgrade() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    job = workflow.split("  selfhost-postgres-upgrade:", maxsplit=1)[1].split(
        "  quality:", maxsplit=1
    )[0]
    quality = workflow.split("  quality:", maxsplit=1)[1].split(
        "  benchmark-contracts:", maxsplit=1
    )[0]

    assert "image: postgres:16-bookworm" in job
    assert "image: postgres:18.4-bookworm" in job
    assert "INFINITY_CONTEXT_SELFHOST_TEST_POSTGRES_URL:" in job
    assert "INFINITY_CONTEXT_SELFHOST_TEST_POSTGRES16_URL:" in job
    assert "INFINITY_CONTEXT_SELFHOST_TEST_PG_DUMP_IMAGE:" in job
    assert "test_pg16_logical_restore_transfers_application_ownership" in job
    assert "- selfhost-postgres-upgrade" in quality
    assert (
        'test "$SELFHOST_POSTGRES_UPGRADE_RESULT" = "success"' in quality
    )
