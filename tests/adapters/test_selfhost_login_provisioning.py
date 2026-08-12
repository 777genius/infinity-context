from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres import selfhost_login_provisioning as subject


def _passwords(**overrides: str) -> subject.SelfHostLoginPasswords:
    values = {
        "migrator": "migrator-secret",
        "runtime": "runtime-secret",
        "canonical_writer": "canonical-secret",
        "registrar": "registrar-secret",
        "sealer": "sealer-secret",
    }
    values.update(overrides)
    return subject.SelfHostLoginPasswords(**values)


def test_packaged_sql_pins_exact_identity_and_membership_topology() -> None:
    sql = subject._LOGIN_SQL_PATH.read_text(encoding="utf-8")

    assert tuple(role for role in subject.SELFHOST_LOGIN_ROLES if role in sql) == (
        subject.SELFHOST_MIGRATOR_ROLE,
        subject.SELFHOST_RUNTIME_ROLE,
        subject.SELFHOST_CANONICAL_WRITER_LOGIN_ROLE,
        subject.SELFHOST_REGISTRAR_LOGIN_ROLE,
        subject.SELFHOST_SEALER_LOGIN_ROLE,
    )
    assert "identity_inherit := identity_capability IS NOT NULL" in sql
    assert "CASE WHEN identity_inherit THEN 'INHERIT' ELSE 'NOINHERIT' END" in sql
    assert "pg_catalog.BOOLEAN" not in sql
    assert sql.count("pg_catalog.BOOL") == 2
    assert "NOREPLICATION NOBYPASSRLS" in sql
    assert "WITH INHERIT TRUE, SET FALSE, ADMIN FALSE" in sql
    assert "identity_capability IS NULL" in sql
    assert "granted_role.rolname <> identity_capability" in sql
    assert "unsafe self-host capability membership topology" in sql
    assert "member_role.rolname <> 'infinity_context_canonical_writer_login'" in sql
    assert "member_role.rolname <> 'infinity_context_strict_v4_registrar_login'" in sql
    assert "member_role.rolname <> 'infinity_context_strict_v4_sealer_login'" in sql
    assert "GRANT CONNECT, CREATE, TEMPORARY ON DATABASE %I" in sql
    assert "GRANT USAGE, CREATE ON SCHEMA public" in sql
    assert "database_owner <> SESSION_USER" in sql
    assert "schema_owner NOT IN (SESSION_USER, 'pg_database_owner')" in sql
    assert "OWNER TO infinity_context_migrator" not in sql


def test_render_quotes_passwords_and_keeps_rotation_explicit() -> None:
    passwords = _passwords(migrator="back\\slash-'quoted")

    provision = subject._render_login_sql(passwords=passwords, rotate=False)
    rotate = subject._render_login_sql(passwords=passwords, rotate=True)

    assert "E'back\\\\slash-''quoted'" in provision
    assert "rotate_passwords pg_catalog.BOOL := FALSE" in provision
    assert "rotate_passwords pg_catalog.BOOL := TRUE" in rotate
    assert not any(placeholder in provision for placeholder in subject._PASSWORD_PLACEHOLDERS)


def test_quote_literal_is_safe_when_standard_conforming_strings_is_off() -> None:
    hostile = "trailing\\'; DROP ROLE infinity_context_runtime; --"

    rendered = subject._quote_literal(hostile)

    assert rendered == "E'trailing\\\\''; DROP ROLE infinity_context_runtime; --'"
    assert subject._quote_literal("\\") == "E'\\\\'"


@pytest.mark.parametrize(
    "passwords",
    (
        _passwords(runtime=""),
        _passwords(runtime="migrator-secret"),
        _passwords(runtime="bad\x00secret"),
    ),
)
def test_password_validation_fails_without_echoing_secret(
    passwords: subject.SelfHostLoginPasswords,
) -> None:
    with pytest.raises(ValueError) as error:
        passwords.validate()

    assert all(value not in str(error.value) for value in passwords.values() if value)


def test_adapter_executes_capabilities_then_logins_in_one_transaction() -> None:
    executed: list[str] = []

    class Driver:
        async def execute(self, sql: str) -> None:
            executed.append(sql)

    class Connection:
        async def get_raw_connection(self):
            return SimpleNamespace(driver_connection=Driver())

    class Begin:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Engine:
        dialect = SimpleNamespace(name="postgresql")

        def begin(self):
            return Begin()

    asyncio.run(subject.provision_selfhost_login_identities(Engine(), _passwords()))

    assert "infinity_context_canonical_writer" in executed[0]
    assert "FALSE" in executed[1]
    assert "migrator-secret" in executed[1]


def test_adapter_redacts_database_failure() -> None:
    secret = "never-echo-this"

    class Driver:
        async def execute(self, _sql: str) -> None:
            raise RuntimeError(secret)

    class Connection:
        async def get_raw_connection(self):
            return SimpleNamespace(driver_connection=Driver())

    class Begin:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Engine:
        dialect = SimpleNamespace(name="postgresql")

        def begin(self):
            return Begin()

    with pytest.raises(RuntimeError) as error:
        asyncio.run(
            subject.provision_selfhost_login_identities(Engine(), _passwords(migrator=secret))
        )

    assert secret not in str(error.value)
    assert error.value.__cause__ is None
