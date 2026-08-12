"""Provider-free contracts for the fresh-chain production input envelope."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server.publishable_durable_scheduler.publishable_run_config import (
    load_publishable_run_files,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PUBLISHABLE_RUN_CONFIG_SCHEMA,
    PUBLISHABLE_RUN_SECRETS_SCHEMA,
    PublishableRunError,
    PublishableRunProviderInputs,
)
from publishable_mem0_v5 import fresh_chain_provider_config as subject


def _key(label: str) -> bytes:
    return hashlib.sha256(f"fresh-chain-test:{label}".encode()).digest()


def _json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _fresh_config() -> dict[str, object]:
    return {
        "fresh_chain": {
            "current_date": "2026-08-12",
            "managed_v5_live_config_path": "/private/managed-v5-live.json",
            "infinity_retrieval_database_path": "/private/fresh-infinity.sqlite3",
            "operator_extraction_ceiling": 8_000,
            "operator_total_ceiling": 40_000,
            "request_timeout_seconds": 30,
        },
        "run_provider": {"opaque_run_provider_config": True},
        "schema_version": subject.FRESH_CHAIN_PROVIDER_CONFIG_SCHEMA,
    }


def _fresh_secrets() -> dict[str, object]:
    return {
        "fresh_chain": {
            "infinity_auth_token": "provider-free-infinity-auth-token",
            "one_shot_hmac_key_hex": _key("one-shot").hex(),
        },
        "run_provider": {"opaque_run_provider_secrets": True},
        "schema_version": subject.FRESH_CHAIN_PROVIDER_SECRETS_SCHEMA,
    }


def _run_secrets() -> SimpleNamespace:
    return SimpleNamespace(
        extraction_authentication_keys=(_key("extract-a"), _key("extract-b")),
        retrieval_authentication_key=_key("retrieval"),
        bridge_journal_authentication_key=_key("bridge-journal"),
        output_cipher_key=_key("output"),
        runtime_attestation_root_secret=_key("runtime-root"),
        bridges=tuple(
            SimpleNamespace(
                attestation_secret=_key(f"attestation-{index}"),
                launcher_receipt_key=_key(f"launcher-{index}"),
                authorization_bearer=(f"provider-free-bridge-authorization-{index}-value"),
            )
            for index in range(3)
        ),
    )


def _inputs(
    tmp_path: Path,
    *,
    config: dict[str, object] | None = None,
    secrets: dict[str, object] | None = None,
) -> PublishableRunProviderInputs:
    state = _private_directory(tmp_path / "provider-state")
    return PublishableRunProviderInputs(
        state_root=state,
        adapter_config_json=_json(_fresh_config() if config is None else config),
        adapter_secrets_json=_json(_fresh_secrets() if secrets is None else secrets),
    )


def _install_run_parser(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    observed = SimpleNamespace(calls=[])
    run_secrets = _run_secrets()

    def parse(inputs: PublishableRunProviderInputs):
        observed.calls.append(inputs)
        assert inputs.adapter_config() == {"opaque_run_provider_config": True}
        assert inputs.adapter_secrets() == {"opaque_run_provider_secrets": True}
        return object(), run_secrets

    monkeypatch.setattr(subject, "parse_run_provider_inputs", parse)
    observed.run_secrets = run_secrets
    return observed


def test_fresh_chain_provider_parser_accepts_exact_token_neutral_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = _install_run_parser(monkeypatch)

    config, secrets = subject.parse_fresh_chain_provider_inputs(_inputs(tmp_path))

    assert len(observed.calls) == 1
    assert observed.calls[0].state_root == tmp_path / "provider-state"
    assert config.managed_v5_live_config_path == Path("/private/managed-v5-live.json")
    assert config.infinity_retrieval_database_path == Path("/private/fresh-infinity.sqlite3")
    assert config.current_date == "2026-08-12"
    assert config.request_timeout_seconds == 30.0
    assert config.operator_extraction_token_ceiling == 8_000
    assert config.operator_total_token_ceiling == 40_000
    assert secrets.one_shot_hmac_key == _key("one-shot")
    assert "private" not in repr(secrets).casefold()


@pytest.mark.parametrize(
    ("target", "mutation"),
    (
        ("config-root", lambda value: value.update({"extra": True})),
        ("config-fresh", lambda value: value["fresh_chain"].pop("current_date")),
        ("secrets-root", lambda value: value.update({"extra": True})),
        (
            "secrets-fresh",
            lambda value: value["fresh_chain"].update({"extra": True}),
        ),
    ),
)
def test_fresh_chain_provider_parser_rejects_non_exact_nested_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    mutation: object,
) -> None:
    _install_run_parser(monkeypatch)
    config = _fresh_config()
    secrets = _fresh_secrets()
    selected = config if target.startswith("config") else secrets
    mutation(selected)  # type: ignore[operator]

    with pytest.raises(PublishableRunError, match="fresh_chain_provider_material_invalid"):
        subject.parse_fresh_chain_provider_inputs(_inputs(tmp_path, config=config, secrets=secrets))


@pytest.mark.parametrize(
    ("extraction", "total"),
    (
        (0, 40_000),
        (4_095, 40_000),
        (True, 40_000),
        (8_000, 7_999),
        (10_000_001, 40_000_000),
        (8_000, 50_000_001),
    ),
)
def test_fresh_chain_provider_parser_rejects_invalid_operator_ceilings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extraction: object,
    total: object,
) -> None:
    _install_run_parser(monkeypatch)
    config = _fresh_config()
    fresh = config["fresh_chain"]
    assert type(fresh) is dict
    fresh["operator_extraction_ceiling"] = extraction
    fresh["operator_total_ceiling"] = total

    with pytest.raises(PublishableRunError, match="fresh_chain_provider_config_invalid"):
        subject.parse_fresh_chain_provider_inputs(_inputs(tmp_path, config=config))


def test_fresh_chain_provider_parser_rejects_secret_role_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = _install_run_parser(monkeypatch)
    secrets = _fresh_secrets()
    fresh = secrets["fresh_chain"]
    assert type(fresh) is dict
    fresh["one_shot_hmac_key_hex"] = observed.run_secrets.retrieval_authentication_key.hex()

    with pytest.raises(PublishableRunError, match="fresh_chain_provider_secret_reuse"):
        subject.parse_fresh_chain_provider_inputs(_inputs(tmp_path, secrets=secrets))


def _outer_documents(root: Path) -> tuple[dict[str, object], dict[str, object]]:
    state = root / "state"
    config = {
        "adapter": _fresh_config(),
        "dependency_provider": "mem0-infinity-production-v1",
        "max_dispatches_per_batch": 5,
        "publication_key_id": "fresh-chain-activation-only",
        "schema_version": PUBLISHABLE_RUN_CONFIG_SCHEMA,
        "state": {
            "longmemeval_scheduler_database_path": str(state / "longmemeval.sqlite3"),
            "locomo_scheduler_database_path": str(state / "locomo.sqlite3"),
            "official_case_authority_path": str(state / "official.sqlite3"),
            "publication_receipt_path": str(state / "activation-evidence.json"),
            "suite_seal_database_path": str(state / "suite.sqlite3"),
        },
    }
    key_names = (
        "official_case_authentication_key_hex",
        "locomo_scheduler_authentication_key_hex",
        "longmemeval_scheduler_authentication_key_hex",
        "suite_seal_authentication_key_hex",
        "publication_receipt_authentication_key_hex",
    )
    secrets = {
        "adapter": _fresh_secrets(),
        "keys": {name: _key(f"outer-{index}").hex() for index, name in enumerate(key_names)},
        "schema_version": PUBLISHABLE_RUN_SECRETS_SCHEMA,
    }
    return config, secrets


def _write_private(path: Path, value: object) -> Path:
    path.write_bytes(_json(value))
    os.chmod(path, 0o600)
    return path


def test_outer_loader_admits_exact_fresh_chain_config_field_names(tmp_path: Path) -> None:
    root = _private_directory(tmp_path / "private")
    _private_directory(root / "state")
    config, secrets = _outer_documents(root)
    config_path = _write_private(root / "config.json", config)
    secrets_path = _write_private(root / "secrets.json", secrets)

    loaded, _loaded_secrets = load_publishable_run_files(
        private_root=root,
        config_path=config_path,
        secrets_path=secrets_path,
    )

    fresh = loaded.adapter_config()["fresh_chain"]
    assert type(fresh) is dict
    assert "operator_extraction_ceiling" in fresh
    assert "operator_total_ceiling" in fresh
    assert all("token" not in name for name in fresh)


def test_outer_loader_rejects_old_secret_looking_ceiling_name(tmp_path: Path) -> None:
    root = _private_directory(tmp_path / "private")
    _private_directory(root / "state")
    config, secrets = _outer_documents(root)
    hostile = copy.deepcopy(config)
    adapter = hostile["adapter"]
    assert type(adapter) is dict
    fresh = adapter["fresh_chain"]
    assert type(fresh) is dict
    fresh["operator_total_token_ceiling"] = fresh.pop("operator_total_ceiling")
    config_path = _write_private(root / "config.json", hostile)
    secrets_path = _write_private(root / "secrets.json", secrets)

    with pytest.raises(PublishableRunError, match="publishable_run_config_contains_secret"):
        load_publishable_run_files(
            private_root=root,
            config_path=config_path,
            secrets_path=secrets_path,
        )
