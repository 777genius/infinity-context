from __future__ import annotations

import json
from pathlib import Path

import pytest
from infinity_context_server.publishable_durable_scheduler.publishable_run_config import (
    load_publishable_run_files,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PUBLISHABLE_RUN_CONFIG_SCHEMA,
    PUBLISHABLE_RUN_SECRETS_SCHEMA,
    PublishableRunError,
)

_KEY_FIELDS = (
    "official_case_authentication_key_hex",
    "locomo_scheduler_authentication_key_hex",
    "longmemeval_scheduler_authentication_key_hex",
    "suite_seal_authentication_key_hex",
    "publication_receipt_authentication_key_hex",
)


def _private_root(tmp_path: Path) -> Path:
    root = tmp_path / "publishable-run"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    state = root / "state"
    state.mkdir(mode=0o700)
    state.chmod(0o700)
    return root


def _config(root: Path) -> dict[str, object]:
    state = root / "state"
    return {
        "adapter": {
            "endpoint": "https://adapter.invalid",
            "options": {"retries": 2},
        },
        "dependency_provider": "tests.publishable",
        "max_dispatches_per_batch": 4,
        "publication_key_id": "publication-key-v1",
        "schema_version": PUBLISHABLE_RUN_CONFIG_SCHEMA,
        "state": {
            "longmemeval_scheduler_database_path": str(state / "longmemeval.sqlite3"),
            "locomo_scheduler_database_path": str(state / "locomo.sqlite3"),
            "official_case_authority_path": str(state / "official-cases.sqlite3"),
            "publication_receipt_path": str(state / "publication-receipt.json"),
            "suite_seal_database_path": str(state / "suite-seals.sqlite3"),
        },
    }


def _secrets() -> dict[str, object]:
    return {
        "adapter": {"credentials": {"provider_value": "private"}},
        "keys": {
            field: (bytes([index]) * 32).hex() for index, field in enumerate(_KEY_FIELDS, start=1)
        },
        "schema_version": PUBLISHABLE_RUN_SECRETS_SCHEMA,
    }


def _json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _private_file(path: Path, value: bytes) -> Path:
    path.write_bytes(value)
    path.chmod(0o600)
    return path


def _files(
    root: Path,
    *,
    config: dict[str, object] | None = None,
    secrets: dict[str, object] | None = None,
    config_raw: bytes | None = None,
    secrets_raw: bytes | None = None,
) -> tuple[Path, Path]:
    config_path = _private_file(
        root / "config.json",
        config_raw if config_raw is not None else _json(config or _config(root)),
    )
    secrets_path = _private_file(
        root / "secrets.json",
        secrets_raw if secrets_raw is not None else _json(secrets or _secrets()),
    )
    return config_path, secrets_path


def _load(root: Path, config_path: Path, secrets_path: Path):
    return load_publishable_run_files(
        private_root=root,
        config_path=config_path,
        secrets_path=secrets_path,
    )


def _raw_with_adapter(root: Path, target: str, adapter_json: str) -> tuple[bytes, bytes]:
    config = _config(root)
    secrets = _secrets()
    payload = config if target == "config" else secrets
    payload["adapter"] = {"replace_me": None}
    marker = b'{"replace_me":null}'
    raw = _json(payload)
    assert raw.count(marker) == 1
    replaced = raw.replace(marker, adapter_json.encode())
    return (replaced, _json(secrets)) if target == "config" else (_json(config), replaced)


def test_loads_distinct_canonical_private_config_and_secrets(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    config_path, secrets_path = _files(root)

    config, secrets = _load(root, config_path, secrets_path)

    state = root / "state"
    assert config.dependency_provider == "tests.publishable"
    assert config.official_case_authority_path == state / "official-cases.sqlite3"
    assert config.scheduler_database_paths == (
        state / "locomo.sqlite3",
        state / "longmemeval.sqlite3",
    )
    assert config.suite_seal_database_path == state / "suite-seals.sqlite3"
    assert config.publication_receipt_path == state / "publication-receipt.json"
    assert config.publication_key_id == "publication-key-v1"
    assert config.max_dispatches_per_batch == 4
    assert config.adapter_config() == {
        "endpoint": "https://adapter.invalid",
        "options": {"retries": 2},
    }
    assert secrets.official_case_authentication_key == bytes([1]) * 32
    assert secrets.scheduler_authentication_keys == (bytes([2]) * 32, bytes([3]) * 32)
    assert secrets.suite_seal_authentication_key == bytes([4]) * 32
    assert secrets.publication_receipt_authentication_key == bytes([5]) * 32
    assert secrets.adapter_secrets() == {"credentials": {"provider_value": "private"}}
    assert root.stat().st_mode & 0o777 == 0o700
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert secrets_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("target", ("config", "secrets"))
def test_duplicate_json_keys_are_rejected_at_nested_levels(
    tmp_path: Path,
    target: str,
) -> None:
    root = _private_root(tmp_path)
    config_raw, secrets_raw = _raw_with_adapter(
        root,
        target,
        '{"outer":{"mode":"first","mode":"second"}}',
    )
    config_path, secrets_path = _files(
        root,
        config_raw=config_raw,
        secrets_raw=secrets_raw,
    )

    with pytest.raises(PublishableRunError, match="publishable_run_private_input_invalid"):
        _load(root, config_path, secrets_path)


@pytest.mark.parametrize("target", ("config", "secrets"))
@pytest.mark.parametrize("literal", ("NaN", "Infinity", "-Infinity", "1e999"))
def test_nonfinite_and_overflow_numbers_are_rejected(
    tmp_path: Path,
    target: str,
    literal: str,
) -> None:
    root = _private_root(tmp_path)
    config_raw, secrets_raw = _raw_with_adapter(
        root,
        target,
        f'{{"outer":[{{"number":{literal}}}]}}',
    )
    config_path, secrets_path = _files(
        root,
        config_raw=config_raw,
        secrets_raw=secrets_raw,
    )

    with pytest.raises(PublishableRunError):
        _load(root, config_path, secrets_path)


@pytest.mark.parametrize("target", ("config", "secrets"))
@pytest.mark.parametrize("kind", ("relative", "noncanonical", "outside", "symlink"))
def test_input_files_must_be_canonical_descendants(
    tmp_path: Path,
    target: str,
    kind: str,
) -> None:
    root = _private_root(tmp_path)
    config_path, secrets_path = _files(root)
    original = config_path if target == "config" else secrets_path
    if kind == "relative":
        candidate = Path(original.name)
    elif kind == "noncanonical":
        nested = root / "nested"
        nested.mkdir(mode=0o700)
        candidate = nested / ".." / original.name
    elif kind == "outside":
        candidate = _private_file(tmp_path / f"outside-{target}.json", original.read_bytes())
    else:
        candidate = root / f"linked-{target}.json"
        candidate.symlink_to(original)
    if target == "config":
        config_path = candidate
    else:
        secrets_path = candidate

    with pytest.raises(PublishableRunError, match="publishable_run_private_input_invalid"):
        _load(root, config_path, secrets_path)


@pytest.mark.parametrize("kind", ("relative", "noncanonical", "outside", "symlink"))
def test_state_files_must_be_canonical_descendants(tmp_path: Path, kind: str) -> None:
    root = _private_root(tmp_path)
    config = _config(root)
    state = config["state"]
    assert isinstance(state, dict)
    if kind == "relative":
        candidate = "state/official-cases.sqlite3"
    elif kind == "noncanonical":
        candidate = str(root / "state" / ".." / "state" / "official-cases.sqlite3")
    elif kind == "outside":
        candidate = str(tmp_path / "outside-state.sqlite3")
    else:
        state_target = _private_file(root / "state" / "target.sqlite3", b"state")
        linked = root / "state" / "linked.sqlite3"
        linked.symlink_to(state_target)
        candidate = str(linked)
    state["official_case_authority_path"] = candidate
    config_path, secrets_path = _files(root, config=config)

    with pytest.raises(PublishableRunError, match="publishable_run_state_path_invalid"):
        _load(root, config_path, secrets_path)


def test_config_and_secrets_paths_must_be_distinct(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    config_path, _ = _files(root)

    with pytest.raises(PublishableRunError, match="publishable_run_input_paths_not_distinct"):
        _load(root, config_path, config_path)


def test_state_paths_must_be_distinct(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    config = _config(root)
    state = config["state"]
    assert isinstance(state, dict)
    state["suite_seal_database_path"] = state["official_case_authority_path"]
    config_path, secrets_path = _files(root, config=config)

    with pytest.raises(PublishableRunError, match="publishable_run_config_invalid"):
        _load(root, config_path, secrets_path)


@pytest.mark.parametrize("suffix", ("-journal", "-shm", "-wal"))
def test_declared_paths_cannot_alias_sqlite_sidecars(tmp_path: Path, suffix: str) -> None:
    root = _private_root(tmp_path)
    config = _config(root)
    state = config["state"]
    assert isinstance(state, dict)
    state["publication_receipt_path"] = f"{state['official_case_authority_path']}{suffix}"
    config_path, secrets_path = _files(root, config=config)

    with pytest.raises(PublishableRunError, match="publishable_run_paths_not_distinct"):
        _load(root, config_path, secrets_path)


def test_authentication_key_materials_must_be_distinct(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    secrets = _secrets()
    keys = secrets["keys"]
    assert isinstance(keys, dict)
    keys["suite_seal_authentication_key_hex"] = keys["official_case_authentication_key_hex"]
    config_path, secrets_path = _files(root, secrets=secrets)

    with pytest.raises(PublishableRunError, match="publishable_run_secrets_invalid"):
        _load(root, config_path, secrets_path)


@pytest.mark.parametrize("secret_name", ("api-key", "clientSecret", "ACCESS-TOKEN"))
def test_secret_named_nested_adapter_config_is_rejected(
    tmp_path: Path,
    secret_name: str,
) -> None:
    root = _private_root(tmp_path)
    config = _config(root)
    config["adapter"] = {"public": [{secret_name: "must-not-be-here"}]}
    config_path, secrets_path = _files(root, config=config)

    with pytest.raises(PublishableRunError, match="publishable_run_config_contains_secret"):
        _load(root, config_path, secrets_path)
