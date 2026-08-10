"""Secure strict-JSON loading for the publishable-run composition root."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from infinity_context_server.features.subscription_runtime_bridge.json_boundary import (
    exact_object,
    strict_json_loads,
)
from infinity_context_server.features.subscription_runtime_bridge.secure_secret_file import (
    SecureSecretFileReader,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PUBLISHABLE_RUN_CONFIG_BYTES_LIMIT,
    PUBLISHABLE_RUN_CONFIG_SCHEMA,
    PUBLISHABLE_RUN_SECRETS_BYTES_LIMIT,
    PUBLISHABLE_RUN_SECRETS_SCHEMA,
    PublishableRunConfig,
    PublishableRunError,
    PublishableRunSecrets,
    canonical_adapter_json,
)

_CONFIG_KEYS = frozenset(
    {
        "adapter",
        "dependency_provider",
        "max_dispatches_per_batch",
        "publication_key_id",
        "schema_version",
        "state",
    }
)
_STATE_KEYS = frozenset(
    {
        "longmemeval_scheduler_database_path",
        "locomo_scheduler_database_path",
        "official_case_authority_path",
        "publication_receipt_path",
        "suite_seal_database_path",
    }
)
_SECRETS_KEYS = frozenset({"adapter", "keys", "schema_version"})
_KEYS_KEYS = frozenset(
    {
        "longmemeval_scheduler_authentication_key_hex",
        "locomo_scheduler_authentication_key_hex",
        "official_case_authentication_key_hex",
        "publication_receipt_authentication_key_hex",
        "suite_seal_authentication_key_hex",
    }
)
_HEX = re.compile(r"[0-9a-f]{64,2048}\Z")
_SENSITIVE_CONFIG_KEYS = (
    "api_key",
    "bearer",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)


def load_publishable_run_files(
    *,
    private_root: Path,
    config_path: Path,
    secrets_path: Path,
) -> tuple[PublishableRunConfig, PublishableRunSecrets]:
    """Read two distinct descriptor-bound 0600 files beneath one 0700 root."""

    try:
        root = _canonical_private_root(private_root)
        config_file = _canonical_input_path(root, config_path)
        secrets_file = _canonical_input_path(root, secrets_path)
        if config_file == secrets_file:
            _fail("publishable_run_input_paths_not_distinct")
        config_reader = SecureSecretFileReader(
            private_root=root,
            path=config_file,
            maximum_bytes=PUBLISHABLE_RUN_CONFIG_BYTES_LIMIT,
        )
        secrets_reader = SecureSecretFileReader(
            private_root=root,
            path=secrets_file,
            maximum_bytes=PUBLISHABLE_RUN_SECRETS_BYTES_LIMIT,
        )
        with config_reader.read() as config_contents, secrets_reader.read() as secret_contents:
            if config_contents.snapshot.file[:2] == secret_contents.snapshot.file[:2]:
                _fail("publishable_run_input_paths_not_distinct")
            config_raw = strict_json_loads(
                bytes(config_contents.value),
                maximum_bytes=PUBLISHABLE_RUN_CONFIG_BYTES_LIMIT,
            )
            secrets_raw = strict_json_loads(
                bytes(secret_contents.value),
                maximum_bytes=PUBLISHABLE_RUN_SECRETS_BYTES_LIMIT,
            )
        config = _config(config_raw, private_root=root)
        secrets = _secrets(secrets_raw)
        sqlite_paths = (
            config.official_case_authority_path,
            *config.scheduler_database_paths,
            config.suite_seal_database_path,
        )
        all_paths = (
            config_file,
            secrets_file,
            *sqlite_paths,
            config.publication_receipt_path,
        )
        _validate_path_set(
            root,
            *all_paths,
        )
        _validate_sqlite_sidecar_separation(sqlite_paths=sqlite_paths, all_paths=all_paths)
        return config, secrets
    except PublishableRunError:
        raise
    except Exception:
        _fail("publishable_run_private_input_invalid")


def _config(value: object, *, private_root: Path) -> PublishableRunConfig:
    try:
        raw = exact_object(value, required=_CONFIG_KEYS, label="publishable_run_config")
        if raw["schema_version"] != PUBLISHABLE_RUN_CONFIG_SCHEMA:
            _fail("publishable_run_config_invalid")
        state = exact_object(
            raw["state"],
            required=_STATE_KEYS,
            label="publishable_run_state",
        )
        adapter = raw["adapter"]
        _reject_config_secrets(adapter)
        paths = {name: _state_path(private_root, state[name]) for name in _STATE_KEYS}
        return PublishableRunConfig(
            dependency_provider=_string(raw["dependency_provider"]),
            official_case_authority_path=paths["official_case_authority_path"],
            scheduler_database_paths=(
                paths["locomo_scheduler_database_path"],
                paths["longmemeval_scheduler_database_path"],
            ),
            suite_seal_database_path=paths["suite_seal_database_path"],
            publication_receipt_path=paths["publication_receipt_path"],
            publication_key_id=_string(raw["publication_key_id"]),
            max_dispatches_per_batch=raw["max_dispatches_per_batch"],
            adapter_config_json=canonical_adapter_json(adapter, secret=False),
        )
    except PublishableRunError:
        raise
    except Exception:
        _fail("publishable_run_config_invalid")


def _secrets(value: object) -> PublishableRunSecrets:
    try:
        raw = exact_object(value, required=_SECRETS_KEYS, label="publishable_run_secrets")
        if raw["schema_version"] != PUBLISHABLE_RUN_SECRETS_SCHEMA:
            _fail("publishable_run_secrets_invalid")
        keys = exact_object(raw["keys"], required=_KEYS_KEYS, label="publishable_run_keys")
        return PublishableRunSecrets(
            official_case_authentication_key=_key(keys["official_case_authentication_key_hex"]),
            scheduler_authentication_keys=(
                _key(keys["locomo_scheduler_authentication_key_hex"]),
                _key(keys["longmemeval_scheduler_authentication_key_hex"]),
            ),
            suite_seal_authentication_key=_key(keys["suite_seal_authentication_key_hex"]),
            publication_receipt_authentication_key=_key(
                keys["publication_receipt_authentication_key_hex"]
            ),
            adapter_secrets_json=canonical_adapter_json(raw["adapter"], secret=True),
        )
    except PublishableRunError:
        raise
    except Exception:
        _fail("publishable_run_secrets_invalid")


def _canonical_private_root(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        _fail("publishable_run_private_root_invalid")
    try:
        resolved = path.resolve(strict=True)
        value = path.lstat()
    except OSError:
        _fail("publishable_run_private_root_invalid")
    if (
        resolved != path
        or stat.S_ISLNK(value.st_mode)
        or not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        _fail("publishable_run_private_root_invalid")
    return path


def _canonical_input_path(root: Path, path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        _fail("publishable_run_private_input_invalid")
    try:
        if path.resolve(strict=True) != path:
            _fail("publishable_run_private_input_invalid")
        path.relative_to(root)
    except (OSError, ValueError):
        _fail("publishable_run_private_input_invalid")
    return path


def _state_path(root: Path, value: object) -> Path:
    if type(value) is not str or not value:
        _fail("publishable_run_state_path_invalid")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path.resolve(strict=False) != path:
        _fail("publishable_run_state_path_invalid")
    try:
        relative = path.relative_to(root)
    except ValueError:
        _fail("publishable_run_state_path_invalid")
    if not relative.parts or path.name in {"", ".", ".."}:
        _fail("publishable_run_state_path_invalid")
    _private_directory_chain(root, path.parent)
    if path.exists() or path.is_symlink():
        _private_existing_state_file(path)
    return path


def _private_directory_chain(root: Path, parent: Path) -> None:
    try:
        relative = parent.relative_to(root)
    except ValueError:
        _fail("publishable_run_state_path_invalid")
    current = root
    for part in relative.parts:
        current /= part
        try:
            value = current.lstat()
        except OSError:
            _fail("publishable_run_state_parent_invalid")
        if (
            stat.S_ISLNK(value.st_mode)
            or not stat.S_ISDIR(value.st_mode)
            or value.st_uid != os.geteuid()
            or stat.S_IMODE(value.st_mode) != 0o700
        ):
            _fail("publishable_run_state_parent_invalid")


def _private_existing_state_file(path: Path) -> None:
    try:
        value = path.lstat()
    except OSError:
        _fail("publishable_run_state_path_invalid")
    if (
        stat.S_ISLNK(value.st_mode)
        or not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.geteuid()
        or value.st_nlink != 1
        or stat.S_IMODE(value.st_mode) != 0o600
    ):
        _fail("publishable_run_state_path_invalid")


def _validate_path_set(root: Path, *paths: Path) -> None:
    if len(set(paths)) != len(paths):
        _fail("publishable_run_paths_not_distinct")
    identities: set[tuple[int, int]] = set()
    for path in paths:
        try:
            path.relative_to(root)
        except ValueError:
            _fail("publishable_run_state_path_invalid")
        if not path.exists():
            continue
        value = path.stat(follow_symlinks=False)
        identity = (value.st_dev, value.st_ino)
        if identity in identities:
            _fail("publishable_run_paths_not_distinct")
        identities.add(identity)


def _validate_sqlite_sidecar_separation(
    *,
    sqlite_paths: tuple[Path, ...],
    all_paths: tuple[Path, ...],
) -> None:
    declared = set(all_paths)
    for database_path in sqlite_paths:
        sidecars = (Path(f"{database_path}{suffix}") for suffix in ("-journal", "-shm", "-wal"))
        if any(path in declared for path in sidecars):
            _fail("publishable_run_paths_not_distinct")


def _reject_config_secrets(value: object) -> None:
    if type(value) is not dict:
        _fail("publishable_run_adapter_config_invalid")
    stack: list[object] = [value]
    while stack:
        current = stack.pop()
        if type(current) is dict:
            for key, item in current.items():
                if type(key) is not str:
                    _fail("publishable_run_adapter_config_invalid")
                normalized = key.casefold().replace("-", "_")
                if any(marker in normalized for marker in _SENSITIVE_CONFIG_KEYS):
                    _fail("publishable_run_config_contains_secret")
                stack.append(item)
        elif type(current) is list:
            stack.extend(current)


def _key(value: object) -> bytes:
    if type(value) is not str or _HEX.fullmatch(value) is None or len(value) % 2:
        _fail("publishable_run_secret_key_invalid")
    try:
        key = bytes.fromhex(value)
    except ValueError:
        _fail("publishable_run_secret_key_invalid")
    if not 32 <= len(key) <= 1024:
        _fail("publishable_run_secret_key_invalid")
    return key


def _string(value: object) -> str:
    if type(value) is not str:
        _fail("publishable_run_config_invalid")
    return value


def _fail(code: str) -> None:
    raise PublishableRunError(code) from None


__all__ = ("load_publishable_run_files",)
