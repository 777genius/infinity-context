from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from publishable_mem0_v5.config import (
    PROTECTED_ACCOUNT_I_AUTH_ROOT,
    PROTECTED_R16_ROOT,
    DeploymentConfigError,
    load_provider_free_project_lane_config,
)

from tools.build_provider_free_project import (
    ProviderFreeProjectBuildError,
    ProviderFreeProjectInputs,
    build_provider_free_project_bundle,
)


def _inputs() -> ProviderFreeProjectInputs:
    return ProviderFreeProjectInputs(
        adapter_image_id="sha256:" + "a" * 64,
        host_adapter_port=29192,
        bridge_bindings=("1" * 64, "2" * 64, "3" * 64),
        config_hmac_sha256="4" * 64,
        deployment_closure_sha256="5" * 64,
        deployment_closure_hmac_sha256="6" * 64,
        server_closure_sha256="7" * 64,
        server_closure_hmac_sha256="8" * 64,
        codex_executable_sha256="9" * 64,
    )


def test_builds_only_acceptance_project_v1(tmp_path: Path) -> None:
    authority = tmp_path / "authority"
    authority.mkdir()
    bundle = build_provider_free_project_bundle(
        project_name="mem0-v5-publishable-provider-free-test",
        output_root=tmp_path / "output",
        authority_root=authority,
        inputs=_inputs(),
    )
    config = load_provider_free_project_lane_config(bundle.config_path)
    rendered = json.dumps(dict(bundle.payload()))
    assert config.project_isolation_authority is not None
    assert config.account_i_r16_fence is None
    assert set(bundle.payload()) == {"acceptance", "config_path", "status"}
    for forbidden in ("run_2040", "fresh", "prepare_inputs", "allow-live", "secrets"):
        assert forbidden not in rendered


@pytest.mark.parametrize("name", ("../escape", "/tmp/escape", "account-i"))
def test_invalid_project_name_fails_before_mutation(tmp_path: Path, name: str) -> None:
    authority = tmp_path / "authority"
    authority.mkdir()
    output = tmp_path / "output"
    with pytest.raises(ProviderFreeProjectBuildError, match="project_name_invalid"):
        build_provider_free_project_bundle(
            project_name=name,
            output_root=output,
            authority_root=authority,
            inputs=_inputs(),
        )
    assert not output.exists()


def test_symlinked_authority_fails_before_output(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    authority = tmp_path / "authority"
    authority.symlink_to(actual, target_is_directory=True)
    output = tmp_path / "output"
    with pytest.raises(ProviderFreeProjectBuildError, match="authority_unsafe"):
        build_provider_free_project_bundle(
            project_name="mem0-v5-publishable-provider-free-test",
            output_root=output,
            authority_root=authority,
            inputs=_inputs(),
        )
    assert not output.exists()


def test_symlinked_output_parent_fails_before_mutation(tmp_path: Path) -> None:
    authority = tmp_path / "authority"
    authority.mkdir()
    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    output = alias / "output"
    with pytest.raises(ProviderFreeProjectBuildError, match=r"output_unsafe|authority_unsafe"):
        build_provider_free_project_bundle(
            project_name="mem0-v5-publishable-provider-free-test",
            output_root=output,
            authority_root=authority,
            inputs=_inputs(),
        )
    assert not (actual / "output").exists()


@pytest.mark.parametrize(
    "inputs",
    (
        replace(_inputs(), adapter_image_id="sha256:bad"),
        replace(_inputs(), config_hmac_sha256="bad"),
        replace(_inputs(), host_adapter_port=True),
        replace(_inputs(), host_adapter_port=8891),
    ),
)
def test_invalid_inputs_fail_before_mutation(
    tmp_path: Path, inputs: ProviderFreeProjectInputs
) -> None:
    authority = tmp_path / "authority"
    authority.mkdir()
    output = tmp_path / "output"
    with pytest.raises(ProviderFreeProjectBuildError):
        build_provider_free_project_bundle(
            project_name="mem0-v5-publishable-provider-free-test",
            output_root=output,
            authority_root=authority,
            inputs=inputs,
        )
    assert not output.exists()


def test_wrong_input_object_fails_before_mutation(tmp_path: Path) -> None:
    authority = tmp_path / "authority"
    authority.mkdir()
    output = tmp_path / "output"
    with pytest.raises(ProviderFreeProjectBuildError, match="inputs_invalid"):
        build_provider_free_project_bundle(
            project_name="mem0-v5-publishable-provider-free-test",
            output_root=output,
            authority_root=authority,
            inputs=object(),  # type: ignore[arg-type]
        )
    assert not output.exists()


@pytest.mark.parametrize("nested", (False, True))
def test_project_config_rejects_extra_keys(tmp_path: Path, nested: bool) -> None:
    authority = tmp_path / "authority"
    authority.mkdir()
    bundle = build_provider_free_project_bundle(
        project_name="mem0-v5-publishable-provider-free-test",
        output_root=tmp_path / "output",
        authority_root=authority,
        inputs=_inputs(),
    )
    payload = json.loads(bundle.config_path.read_bytes())
    if nested:
        payload["project_isolation_authority"]["extra"] = True
        expected = "project_isolation_authority_fields_invalid"
    else:
        payload["extra"] = True
        expected = "root_fields_invalid"
    path = tmp_path / f"tampered-{nested}.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(DeploymentConfigError, match=expected):
        load_provider_free_project_lane_config(path)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("project_name", 1),
        ("pid_mode", []),
        ("daemon_global_observation", 0),
        ("daemon_global_observation", None),
        ("host_process_observation", 0),
        ("host_process_observation", None),
    ),
)
def test_project_config_rejects_malformed_authority_types(
    tmp_path: Path, field: str, value: object
) -> None:
    authority = tmp_path / "authority"
    authority.mkdir()
    bundle = build_provider_free_project_bundle(
        project_name="mem0-v5-publishable-provider-free-test",
        output_root=tmp_path / "output",
        authority_root=authority,
        inputs=_inputs(),
    )
    payload = json.loads(bundle.config_path.read_bytes())
    payload["project_isolation_authority"][field] = value
    path = tmp_path / f"malformed-{field}.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(DeploymentConfigError, match="project_isolation_authority"):
        load_provider_free_project_lane_config(path)


@pytest.mark.parametrize("protected", (PROTECTED_ACCOUNT_I_AUTH_ROOT, PROTECTED_R16_ROOT))
def test_direct_protected_paths_fail_without_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    protected: Path,
) -> None:
    original_lstat = Path.lstat
    original_resolve = Path.resolve

    def forbidden_lstat(path: Path):
        if path == protected or protected in path.parents:
            raise AssertionError("protected lstat")
        return original_lstat(path)

    def forbidden_resolve(path: Path, *args: object, **kwargs: object):
        if path == protected or protected in path.parents:
            raise AssertionError("protected resolve")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", forbidden_lstat)
    monkeypatch.setattr(Path, "resolve", forbidden_resolve)
    with pytest.raises(ProviderFreeProjectBuildError, match="path_collision"):
        build_provider_free_project_bundle(
            project_name="mem0-v5-publishable-provider-free-test",
            output_root=protected / "provider-free-output",
            authority_root=tmp_path,
            inputs=_inputs(),
        )
