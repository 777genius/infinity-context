from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
from infinity_context_server.publishable_input_preparation import (
    PublishableInputPreparationError,
    PublishableInputPreparationProviderInputs,
)
from publishable_mem0_v5 import input_provider as subject
from publishable_mem0_v5.input_provider_config import (
    INPUT_PREPARATION_PROVIDER_CONFIG_SCHEMA,
    INPUT_PREPARATION_PROVIDER_SECRETS_SCHEMA,
    parse_publishable_input_preparation_inputs,
)


def _json(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _provider_documents(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    def run(name: str) -> dict[str, object]:
        return {
            "managed_v5_live_config_path": str(tmp_path / f"{name}-live.json"),
            "operator_extraction_token_ceiling": 1_000_000,
            "operator_total_token_ceiling": 2_000_000,
            "strict_keyring_path": str(tmp_path / f"{name}-keyring.json"),
            "strict_receipt_key_path": str(tmp_path / f"{name}-receipt.key"),
            "strict_receipt_path": str(tmp_path / f"{name}-receipt.sqlite3"),
            "strict_registration_postgres_dsn_path": str(tmp_path / "postgres.dsn"),
            "strict_request_path": str(tmp_path / f"{name}-request.json"),
        }

    config = {
        "fleet_mode": "resume",
        "request_timeout_seconds": 5.0,
        "runs": {"locomo": run("locomo"), "longmemeval": run("longmemeval")},
        "schema_version": INPUT_PREPARATION_PROVIDER_CONFIG_SCHEMA,
    }
    counter = 0

    def secrets() -> dict[str, str]:
        nonlocal counter
        values = {}
        for name in (
            "journal_hmac_key_hex",
            "ledger_hmac_key_hex",
            "operation_receipt_hmac_key_hex",
        ):
            counter += 1
            values[name] = f"{counter:064x}"
        return values

    private = {
        "infinity_auth_token": "infinity-auth-token-with-at-least-32-bytes",
        "runs": {"locomo": secrets(), "longmemeval": secrets()},
        "schema_version": INPUT_PREPARATION_PROVIDER_SECRETS_SCHEMA,
    }
    return config, private


def _inputs(
    tmp_path: Path,
    *,
    config: dict[str, object] | None = None,
    secrets: dict[str, object] | None = None,
) -> PublishableInputPreparationProviderInputs:
    state = tmp_path / "state"
    state.mkdir(mode=0o700, exist_ok=True)
    state.chmod(0o700)
    default_config, default_secrets = _provider_documents(tmp_path)
    return PublishableInputPreparationProviderInputs(
        state_root=state.resolve(strict=True),
        run_adapter_config_json=b"{}",
        run_adapter_secrets_json=b"{}",
        input_config_json=_json(config or default_config),
        input_secrets_json=_json(secrets or default_secrets),
    )


def test_provider_material_is_strict_redacted_and_role_separated(tmp_path: Path) -> None:
    config, secrets = parse_publishable_input_preparation_inputs(_inputs(tmp_path))

    assert config.fleet_mode == "resume"
    assert config.locomo.strict_registration_postgres_dsn_path == (
        config.longmemeval.strict_registration_postgres_dsn_path
    )
    assert len({*secrets.locomo.keys, *secrets.longmemeval.keys}) == 6
    assert "infinity-auth-token" not in repr(secrets)


def test_installed_input_provider_entrypoint_has_one_exact_target() -> None:
    root = Path(__file__).resolve().parents[3]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    group = project["project"]["entry-points"][
        "infinity_context.publishable_input_preparation_dependencies"
    ]

    assert group == {
        "mem0-infinity-production-v1": (
            "publishable_mem0_v5.input_provider:"
            "Mem0InfinityPublishableInputPreparationDependencyFactory"
        )
    }
    installed = tuple(
        importlib.metadata.entry_points(
            group="infinity_context.publishable_input_preparation_dependencies",
            name="mem0-infinity-production-v1",
        )
    )
    assert len(installed) == 1
    assert installed[0].load() is subject.Mem0InfinityPublishableInputPreparationDependencyFactory


@pytest.mark.parametrize("failure", ["missing", "duplicate", "path-cross-wire", "key-reuse"])
def test_provider_material_rejects_missing_tamper_and_cross_wire(
    tmp_path: Path,
    failure: str,
) -> None:
    config, secrets = _provider_documents(tmp_path)
    if failure == "missing":
        del config["request_timeout_seconds"]
        inputs = _inputs(tmp_path, config=config, secrets=secrets)
    elif failure == "duplicate":
        inputs = _inputs(tmp_path, config=config, secrets=secrets)
        object.__setattr__(
            inputs,
            "input_config_json",
            b'{"fleet_mode":"resume","fleet_mode":"create"}',
        )
    elif failure == "path-cross-wire":
        runs = config["runs"]
        assert type(runs) is dict
        locomo = runs["locomo"]
        longmemeval = runs["longmemeval"]
        assert type(locomo) is dict and type(longmemeval) is dict
        longmemeval["strict_request_path"] = locomo["strict_request_path"]
        inputs = _inputs(tmp_path, config=config, secrets=secrets)
    else:
        runs = secrets["runs"]
        assert type(runs) is dict
        locomo = runs["locomo"]
        longmemeval = runs["longmemeval"]
        assert type(locomo) is dict and type(longmemeval) is dict
        longmemeval["journal_hmac_key_hex"] = locomo["journal_hmac_key_hex"]
        inputs = _inputs(tmp_path, config=config, secrets=secrets)

    with pytest.raises(PublishableInputPreparationError):
        parse_publishable_input_preparation_inputs(inputs)


class _Strict:
    def __init__(self, name: str) -> None:
        self.name = name
        self.receipt = SimpleNamespace(name=name)
        self.receipt_store = SimpleNamespace(name=f"{name}-store")
        self.registration_port = SimpleNamespace(name=f"{name}-registration")
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _Infinity:
    instances: ClassVar[list[_Infinity]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.close_calls = 0
        self.instances.append(self)

    def close(self) -> None:
        self.close_calls += 1


def _install_factory_fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    run_config = SimpleNamespace(
        locomo_dataset=SimpleNamespace(path=tmp_path / "locomo.json"),
        longmemeval_dataset=SimpleNamespace(path=tmp_path / "longmemeval.json"),
        suite=SimpleNamespace(
            locomo_run_id="locomo-run",
            longmemeval_run_id="longmemeval-run",
            infinity_base_url="http://127.0.0.1:19090",
        ),
        extraction_terminal_paths=(tmp_path / "locomo-terminal", tmp_path / "long-terminal"),
        retrieval_database_path=tmp_path / "retrieval.sqlite3",
        retrieval_authority_root_sha256="a" * 64,
    )
    run_secrets = SimpleNamespace(
        extraction_authentication_keys=(b"x" * 32, b"y" * 32),
        retrieval_authentication_key=b"z" * 32,
    )
    strict = [_Strict("locomo"), _Strict("longmemeval")]
    opened: list[str] = []
    composed: list[str] = []
    dispatch_calls: list[object] = []

    async def open_strict(*, source, config):
        del config
        opened.append(source.path.name)
        return strict[(len(opened) - 1) % 2]

    def compose_run(**kwargs):
        composed.append(kwargs["run_id"])
        return SimpleNamespace(run_id=kwargs["run_id"])

    class Official:
        @staticmethod
        def load(_config):
            return SimpleNamespace(name="official")

    suite = SimpleNamespace(
        bridge_boot=SimpleNamespace(runtime_authority_sha256="b" * 64),
    )
    monkeypatch.setattr(
        subject, "parse_run_provider_inputs", lambda _inputs: (run_config, run_secrets)
    )
    monkeypatch.setattr(subject, "_validate_provider_cross_wiring", lambda **_kwargs: None)
    monkeypatch.setattr(subject, "_open_strict_run", open_strict)
    monkeypatch.setattr(subject, "OfficialCaseProjection", Official)
    monkeypatch.setattr(subject, "_validate_official_case_bridge", lambda **_kwargs: None)
    monkeypatch.setattr(subject, "preflight_run_provider", lambda **_kwargs: SimpleNamespace())
    monkeypatch.setattr(
        subject, "build_publishable_suite_from_prepared_receipts", lambda **_kwargs: suite
    )
    monkeypatch.setattr(subject, "_validate_backend_target_bridge", lambda **_kwargs: None)
    monkeypatch.setattr(subject, "_compose_extraction_run", compose_run)
    monkeypatch.setattr(
        subject,
        "PublishableFullExtractionSuiteConfiguration",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        subject,
        "PublishableExtractionTerminalFileStore",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        subject,
        "PublishableStrictV4RecoveryCapabilities",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(subject, "InfinityContextHttpComparisonBackend", _Infinity)
    monkeypatch.setattr(
        subject,
        "OpenedPublishableInputPreparationSession",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        subject, "compose_managed_mem0_v5_extraction_capabilities", dispatch_calls.append
    )
    return strict, opened, composed, dispatch_calls


def test_factory_reopen_composes_exact_pair_with_zero_provider_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Infinity.instances.clear()
    strict, opened, composed, dispatch_calls = _install_factory_fakes(monkeypatch, tmp_path)
    factory = subject.Mem0InfinityPublishableInputPreparationDependencyFactory()

    first = asyncio.run(factory.open_session(inputs=_inputs(tmp_path)))
    second = asyncio.run(factory.open_session(inputs=_inputs(tmp_path)))

    assert opened == ["locomo.json", "longmemeval.json"] * 2
    assert composed == ["locomo-run", "longmemeval-run"] * 2
    assert dispatch_calls == []
    assert first.process_lock_path == second.process_lock_path
    for callback in first.close_callbacks + second.close_callbacks:
        callback()
    assert [item.close_calls for item in strict] == [2, 2]
    assert [item.close_calls for item in _Infinity.instances] == [1, 1]


def test_factory_closes_first_strict_authority_when_second_open_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strict, _opened, _composed, _dispatch = _install_factory_fakes(monkeypatch, tmp_path)
    calls = 0

    async def fail_second(*, source, config):
        nonlocal calls
        del source, config
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic second-open failure")
        return strict[0]

    monkeypatch.setattr(subject, "_open_strict_run", fail_second)

    with pytest.raises(RuntimeError, match="second-open"):
        asyncio.run(
            subject.Mem0InfinityPublishableInputPreparationDependencyFactory().open_session(
                inputs=_inputs(tmp_path)
            )
        )

    assert strict[0].close_calls == 1


@pytest.mark.parametrize("cross_wire", ["path", "hardlink"])
def test_provider_outer_sqlite_cross_wire_rejects_before_open(
    tmp_path: Path,
    cross_wire: str,
) -> None:
    inputs = _inputs(tmp_path)
    provider_config, provider_secrets = parse_publishable_input_preparation_inputs(inputs)
    for path in {*provider_config.locomo.paths, *provider_config.longmemeval.paths}:
        path.touch()
    provider_path = provider_config.locomo.strict_request_path
    official_path = provider_path
    if cross_wire == "hardlink":
        official_path = tmp_path / "official-hardlink.sqlite3"
        os.link(provider_path, official_path)
    run_config = SimpleNamespace(
        locomo_dataset=SimpleNamespace(path=tmp_path / "locomo.json"),
        longmemeval_dataset=SimpleNamespace(path=tmp_path / "longmemeval.json"),
        extraction_terminal_paths=(tmp_path / "locomo-terminal", tmp_path / "long-terminal"),
        official_case_authority_path=official_path,
        scheduler_database_paths=(tmp_path / "scheduler-0", tmp_path / "scheduler-1"),
        suite_seal_database_path=tmp_path / "suite-seal.sqlite3",
        retrieval_database_path=tmp_path / "retrieval.sqlite3",
        publication_receipt_path=tmp_path / "publication.json",
    )

    with pytest.raises(PublishableInputPreparationError) as error:
        subject._validate_provider_cross_wiring(
            inputs=inputs,
            provider_config=provider_config,
            provider_secrets=provider_secrets,
            run_config=run_config,
            run_secrets=SimpleNamespace(),
        )

    assert error.value.code == "publishable_input_provider_path_cross_wire"


def test_official_count_alias_bridge_accepts_both_digest_domains_and_rejects_cross_wire() -> None:
    locomo_sha = "1" * 64
    longmemeval_sha = "2" * 64
    run_config = SimpleNamespace(
        locomo_dataset=SimpleNamespace(sha256=locomo_sha),
        longmemeval_dataset=SimpleNamespace(sha256=longmemeval_sha),
        suite=SimpleNamespace(
            locomo_run_id="locomo-run",
            longmemeval_run_id="longmemeval-run",
        ),
    )

    def strict(profile, run_id: str, dataset_sha256: str, prefix: str):
        aliases = tuple(f"{prefix}-{index}" for index in range(profile.case_count))
        return SimpleNamespace(
            receipt=SimpleNamespace(
                profile_id=profile.profile_id,
                dataset_sha256=dataset_sha256,
                run_id_sha256=hashlib.sha256(run_id.encode()).hexdigest(),
                a2_context=SimpleNamespace(case_manifest_sha256="a" * 64),
            ),
            projection=SimpleNamespace(
                cases=tuple(SimpleNamespace(case_id=value) for value in aliases),
                bindings=SimpleNamespace(
                    profile_id=profile.profile_id,
                    dataset_sha256=dataset_sha256,
                    run_id=run_id,
                ),
            ),
            manifest=SimpleNamespace(case_count=profile.case_count),
        ), aliases

    locomo, locomo_aliases = strict(
        subject.LOCOMO_PROFILE,
        "locomo-run",
        locomo_sha,
        "locomo",
    )
    longmemeval, longmemeval_aliases = strict(
        subject.LONGMEMEVAL_PROFILE,
        "longmemeval-run",
        longmemeval_sha,
        "longmemeval",
    )
    official = SimpleNamespace(
        identities=(
            tuple(SimpleNamespace(case_alias=value) for value in locomo_aliases),
            tuple(SimpleNamespace(case_alias=value) for value in longmemeval_aliases),
        )
    )

    subject._validate_official_case_bridge(
        strict_pair=(locomo, longmemeval),
        official=official,
        run_config=run_config,
    )
    assert locomo.receipt.a2_context.case_manifest_sha256 != "b" * 64

    official.identities[1][499].case_alias = "cross-wired-alias"
    with pytest.raises(PublishableInputPreparationError):
        subject._validate_official_case_bridge(
            strict_pair=(locomo, longmemeval),
            official=official,
            run_config=run_config,
        )
