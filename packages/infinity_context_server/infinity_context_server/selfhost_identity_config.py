"""Secret-only configuration boundary for self-host identity administration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from os import environ

from infinity_context_adapters.postgres.selfhost_login_provisioning import (
    SelfHostLoginPasswords,
    provision_selfhost_login_identities,
    rotate_selfhost_login_passwords,
)
from infinity_context_adapters.postgres.unit_of_work import build_async_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

SELFHOST_ADMIN_DATABASE_URL_ENV = "INFINITY_CONTEXT_SELFHOST_ADMIN_DATABASE_URL"
SERVICE_TOKEN_ENV = "MEMORY_SERVICE_TOKEN"
SELFHOST_MIGRATOR_PASSWORD_ENV = "INFINITY_CONTEXT_SELFHOST_MIGRATOR_PASSWORD"
SELFHOST_RUNTIME_PASSWORD_ENV = "INFINITY_CONTEXT_SELFHOST_RUNTIME_PASSWORD"
SELFHOST_CANONICAL_WRITER_PASSWORD_ENV = "INFINITY_CONTEXT_SELFHOST_CANONICAL_WRITER_PASSWORD"
SELFHOST_REGISTRAR_PASSWORD_ENV = "INFINITY_CONTEXT_SELFHOST_REGISTRAR_PASSWORD"
SELFHOST_SEALER_PASSWORD_ENV = "INFINITY_CONTEXT_SELFHOST_SEALER_PASSWORD"


@dataclass(frozen=True, slots=True)
class SelfHostIdentityProvisioningConfig:
    admin_database_url: str
    passwords: SelfHostLoginPasswords


def load_selfhost_identity_provisioning_config(
    environment: Mapping[str, str] | None = None,
) -> SelfHostIdentityProvisioningConfig:
    source = environ if environment is None else environment
    admin_database_url = _required(source, SELFHOST_ADMIN_DATABASE_URL_ENV)
    passwords = SelfHostLoginPasswords(
        migrator=_required(source, SELFHOST_MIGRATOR_PASSWORD_ENV),
        runtime=_required(source, SELFHOST_RUNTIME_PASSWORD_ENV),
        canonical_writer=_required(source, SELFHOST_CANONICAL_WRITER_PASSWORD_ENV),
        registrar=_required(source, SELFHOST_REGISTRAR_PASSWORD_ENV),
        sealer=_required(source, SELFHOST_SEALER_PASSWORD_ENV),
    )
    passwords.validate()
    try:
        admin_url = make_url(admin_database_url)
    except ArgumentError:
        raise RuntimeError("self-host admin database URL is invalid") from None
    if not admin_url.username or not admin_url.password:
        raise RuntimeError("self-host admin database URL must include credentials")
    service_token = _required(source, SERVICE_TOKEN_ENV)
    all_secrets = (service_token, admin_url.password, *passwords.values())
    if any(secret.startswith("change-me") for secret in all_secrets):
        raise RuntimeError("self-host secrets must not use placeholder values")
    if len(set(all_secrets)) != len(all_secrets):
        raise RuntimeError("self-host identity passwords must be distinct")
    return SelfHostIdentityProvisioningConfig(
        admin_database_url=admin_database_url,
        passwords=passwords,
    )


async def apply_selfhost_identity_provisioning(*, rotate_passwords: bool = False) -> None:
    """Apply the explicit administrative identity operation from environment secrets."""

    config = load_selfhost_identity_provisioning_config()
    engine = build_async_engine(config.admin_database_url)
    try:
        operation = (
            rotate_selfhost_login_passwords
            if rotate_passwords
            else provision_selfhost_login_identities
        )
        await operation(engine, config.passwords)
    finally:
        await engine.dispose()


def _required(source: Mapping[str, str], name: str) -> str:
    value = source.get(name, "")
    if not value:
        raise RuntimeError(f"required self-host identity setting is missing: {name}")
    return value


__all__ = (
    "SELFHOST_ADMIN_DATABASE_URL_ENV",
    "SELFHOST_CANONICAL_WRITER_PASSWORD_ENV",
    "SELFHOST_MIGRATOR_PASSWORD_ENV",
    "SELFHOST_REGISTRAR_PASSWORD_ENV",
    "SELFHOST_RUNTIME_PASSWORD_ENV",
    "SELFHOST_SEALER_PASSWORD_ENV",
    "SERVICE_TOKEN_ENV",
    "SelfHostIdentityProvisioningConfig",
    "apply_selfhost_identity_provisioning",
    "load_selfhost_identity_provisioning_config",
)
