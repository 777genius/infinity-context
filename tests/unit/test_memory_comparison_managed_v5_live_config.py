from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_server import memory_comparison_managed_v5_live_config as subject
from infinity_context_server.memory_comparison_managed_v5_live_config import (
    ManagedV5LiveConfig,
    ManagedV5LiveConfigError,
    ManagedV5LiveFilesystemConfig,
    ManagedV5LiveRuntimeConfig,
    parse_managed_v5_live_runtime_authority,
    validate_managed_v5_live_public_config,
)

ROOT = Path(__file__).resolve().parents[2]
PHASE_C_SOURCE = ROOT / "benchmarks" / "phase-c-canary" / "phase_c_canary"
_REAL_PHASE_C_TREE_VALIDATOR = subject._validate_reviewed_phase_c_python_tree


def _authority_payload() -> dict[str, object]:
    return {
        "schema_version": "managed-mem0-v5-live-runtime-authority.v1",
        "model": "gpt-5.4-mini",
        "reasoning_effort": "medium",
        "service_tier": "priority",
        "runtime_source_revision": "phase-c-reviewed-r1",
        "runtime_source_sha256": "1" * 64,
        "runtime_base_sha256": "2" * 64,
        "route_binding_sha256": "3" * 64,
        "base_instructions_sha256": "4" * 64,
        "account_binding_hmac_sha256": "5" * 64,
        "response_format_type": "json_schema",
        "response_format_sha256": "6" * 64,
        "response_schema_sha256": "7" * 64,
        "requested_output_tokens": 4096,
    }


def _write(path: Path, raw: bytes, mode: int) -> str:
    path.write_bytes(raw)
    path.chmod(mode)
    return hashlib.sha256(raw).hexdigest()


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ManagedV5LiveConfig:
    monkeypatch.setattr(subject, "_validate_reviewed_phase_c_python_tree", lambda *_v: None)
    private = tmp_path / "private"
    public = tmp_path / "public"
    private.mkdir(mode=0o755)
    public.mkdir(mode=0o755)
    roots: dict[str, Path] = {}
    for name in ("state", "secrets", "reports"):
        root = private / name
        root.mkdir(mode=0o700)
        roots[name] = root
    credentials: dict[str, Path] = {}
    for name in (
        "bearer",
        "evidence",
        "receipt",
        "signing",
        "head",
        "operation-journal-signer",
        "durable-clean-state-hmac",
    ):
        path = roots["secrets"] / name
        _write(path, ("SECRET:" + name + ":" + "x" * 64).encode(), 0o600)
        credentials[name] = path

    authority = public / "runtime-authority.json"
    authority_sha256 = _write(
        authority,
        json.dumps(_authority_payload(), sort_keys=True, separators=(",", ":")).encode(),
        0o444,
    )
    phase_c = public / "phase-c-package"
    phase_c.mkdir(mode=0o755)
    runtime_parent = public / "phase-c-runtime"
    runtime_repo = runtime_parent / "repo"
    runtime_repo.mkdir(parents=True, mode=0o755)
    manifest = runtime_parent / "artifact-manifest.json"
    manifest_sha256 = _write(manifest, b'{"reviewed":true}', 0o444)
    node = public / "node"
    node_sha256 = _write(node, b"reviewed-node", 0o555)
    monkeypatch.setattr(subject, "_REVIEWED_NODE_SHA256", node_sha256)
    monkeypatch.setattr(subject, "_REVIEWED_NODE_SIZE_BYTES", node.stat().st_size)

    filesystem = ManagedV5LiveFilesystemConfig(
        state_root=roots["state"],
        secret_root=roots["secrets"],
        report_root=roots["reports"],
        report_file=roots["reports"] / "report.json",
        dispatch_journal=roots["state"] / "dispatch.json",
        operation_journal=roots["state"] / "operations.sqlite3",
        durable_clean_state=roots["state"] / "durable-clean-state.json",
        ingress_bearer_file=credentials["bearer"],
        evidence_key_file=credentials["evidence"],
        evidence_key_sha256="8" * 64,
        receipt_secret_file=credentials["receipt"],
        checkpoint_signing_key_file=credentials["signing"],
        checkpoint_head_key_file=credentials["head"],
        operation_journal_signer_secret_file=credentials["operation-journal-signer"],
        durable_clean_state_hmac_secret_file=credentials["durable-clean-state-hmac"],
        runtime_authority_file=authority,
        runtime_authority_sha256=authority_sha256,
        phase_c_package_root=phase_c,
        runtime_repo=runtime_repo,
        runtime_artifact_manifest=manifest,
        runtime_artifact_manifest_sha256=manifest_sha256,
        node_executable=node,
        node_executable_sha256=node_sha256,
    )
    return ManagedV5LiveConfig(
        filesystem=filesystem,
        runtime=ManagedV5LiveRuntimeConfig(mem0_adapter_origin="http://127.0.0.1:19091"),
    )


def test_public_validation_returns_exact_authority_without_reading_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    secret_paths = {
        path
        for path in (
            config.filesystem.ingress_bearer_file,
            config.filesystem.evidence_key_file,
            config.filesystem.receipt_secret_file,
            config.filesystem.checkpoint_signing_key_file,
            config.filesystem.checkpoint_head_key_file,
            config.filesystem.operation_journal_signer_secret_file,
            config.filesystem.durable_clean_state_hmac_secret_file,
        )
    }
    real_open = subject.os.open

    def guarded_open(path: str | os.PathLike[str], *args: object) -> int:
        assert Path(path) not in secret_paths
        return real_open(path, *args)

    monkeypatch.setattr(subject.os, "open", guarded_open)
    authority = validate_managed_v5_live_public_config(config)
    assert authority.model == "gpt-5.4-mini"
    assert authority.route_binding_sha256 == "3" * 64
    assert authority.requested_output_tokens == 4096


@pytest.mark.parametrize(
    ("change", "code"),
    (
        (
            lambda fs, tmp: replace(fs, state_root=Path("relative-state")),
            "managed_v5_live_private_root_invalid",
        ),
        (
            lambda fs, tmp: replace(fs, report_root=fs.state_root / "nested"),
            "managed_v5_live_private_root_invalid",
        ),
        (
            lambda fs, tmp: replace(fs, runtime_authority_sha256="a" * 64),
            "managed_v5_live_runtime_authority_file_invalid",
        ),
        (
            lambda fs, tmp: replace(fs, runtime_artifact_manifest_sha256="b" * 64),
            "managed_v5_live_runtime_artifact_invalid",
        ),
        (
            lambda fs, tmp: replace(fs, node_executable_sha256="c" * 64),
            "managed_v5_live_node_authority_invalid",
        ),
        (
            lambda fs, tmp: replace(
                fs, runtime_artifact_manifest=tmp / "public" / "wrong-manifest.json"
            ),
            "managed_v5_live_runtime_artifact_path_invalid",
        ),
    ),
)
def test_public_validation_rejects_path_digest_and_pin_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change,
    code: str,
) -> None:
    config = _config(tmp_path, monkeypatch)
    changed = replace(config, filesystem=change(config.filesystem, tmp_path))
    with pytest.raises(ManagedV5LiveConfigError) as captured:
        validate_managed_v5_live_public_config(changed)
    assert captured.value.code == code


def test_nested_private_roots_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path, monkeypatch)
    nested = config.filesystem.state_root / "reports"
    nested.mkdir(mode=0o700)
    changed = replace(
        config,
        filesystem=replace(
            config.filesystem,
            report_root=nested,
            report_file=nested / "report.json",
        ),
    )
    with pytest.raises(ManagedV5LiveConfigError) as captured:
        validate_managed_v5_live_public_config(changed)
    assert captured.value.code == "managed_v5_live_private_roots_overlap"


def test_symlink_and_mode_mismatch_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    credential = config.filesystem.receipt_secret_file
    target = credential.with_name("receipt-target")
    credential.rename(target)
    credential.symlink_to(target)
    with pytest.raises(ManagedV5LiveConfigError) as captured:
        validate_managed_v5_live_public_config(config)
    assert captured.value.code == "managed_v5_live_credential_paths_invalid"

    credential.unlink()
    target.rename(credential)
    credential.chmod(0o640)
    with pytest.raises(ManagedV5LiveConfigError) as captured:
        validate_managed_v5_live_public_config(config)
    assert captured.value.code == "managed_v5_live_credential_paths_invalid"


def test_private_factory_secret_and_state_paths_are_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    reused_secret = replace(
        config,
        filesystem=replace(
            config.filesystem,
            operation_journal_signer_secret_file=config.filesystem.receipt_secret_file,
        ),
    )
    with pytest.raises(ManagedV5LiveConfigError) as captured:
        validate_managed_v5_live_public_config(reused_secret)
    assert captured.value.code == "managed_v5_live_credential_paths_invalid"

    reused_state = replace(
        config,
        filesystem=replace(
            config.filesystem,
            durable_clean_state=config.filesystem.operation_journal,
        ),
    )
    with pytest.raises(ManagedV5LiveConfigError) as captured:
        validate_managed_v5_live_public_config(reused_state)
    assert captured.value.code == "managed_v5_live_state_paths_invalid"


def test_runtime_authority_parser_is_exact_and_bounded() -> None:
    payload = _authority_payload()
    raw = json.dumps(payload).encode()
    assert parse_managed_v5_live_runtime_authority(raw).service_tier == "priority"

    payload["unexpected"] = True
    with pytest.raises(ManagedV5LiveConfigError, match="runtime_authority_invalid"):
        parse_managed_v5_live_runtime_authority(json.dumps(payload).encode())
    payload.pop("unexpected")
    payload["requested_output_tokens"] = 2048
    with pytest.raises(ManagedV5LiveConfigError, match="runtime_authority_invalid"):
        parse_managed_v5_live_runtime_authority(json.dumps(payload).encode())
    with pytest.raises(ManagedV5LiveConfigError, match="runtime_authority_invalid"):
        parse_managed_v5_live_runtime_authority(b"x" * (64 * 1024 + 1))
    with pytest.raises(ManagedV5LiveConfigError) as duplicate:
        parse_managed_v5_live_runtime_authority(raw[:-1] + b',"model":"ambiguous"}')
    assert duplicate.value.code == "managed_v5_live_runtime_authority_invalid"
    assert duplicate.value.__cause__ is None


def test_mem0_adapter_origin_has_no_permissive_fallback() -> None:
    with pytest.raises(ManagedV5LiveConfigError) as captured:
        ManagedV5LiveRuntimeConfig(mem0_adapter_origin="http://127.0.0.1:19092")
    assert captured.value.code == "managed_v5_live_mem0_adapter_origin_invalid"


def _reviewed_phase_c_tree(root: Path) -> Path:
    package_root = root / "phase-c-package"
    shutil.copytree(
        PHASE_C_SOURCE,
        package_root / "phase_c_canary",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return package_root


def test_reviewed_phase_c_tree_matches_baked_manifest(tmp_path: Path) -> None:
    root = _reviewed_phase_c_tree(tmp_path / "valid")
    before = _REAL_PHASE_C_TREE_VALIDATOR(
        root,
        subject._REVIEWED_PHASE_C_PYTHON_TREE_SHA256,
    )
    authority = root / "phase_c_canary" / "authority.py"
    raw = authority.read_bytes()
    authority.unlink()
    authority.write_bytes(raw)
    authority.chmod(0o644)
    after = _REAL_PHASE_C_TREE_VALIDATOR(
        root,
        subject._REVIEWED_PHASE_C_PYTHON_TREE_SHA256,
    )
    assert before != after


def test_phase_c_tree_rejects_extra_missing_symlink_and_writable_source(
    tmp_path: Path,
) -> None:
    roots = tuple(
        _reviewed_phase_c_tree(tmp_path / label) for label in ("extra", "missing", "link", "mode")
    )
    (roots[0] / "phase_c_canary" / "extra.py").write_text("ATTACK = True\n")
    (roots[1] / "phase_c_canary" / "strict_schema.py").unlink()
    linked = roots[2] / "phase_c_canary" / "authority.py"
    linked.unlink()
    linked.symlink_to(PHASE_C_SOURCE / "authority.py")
    (roots[3] / "phase_c_canary" / "authority.py").chmod(0o666)
    for root in roots:
        with pytest.raises(ManagedV5LiveConfigError) as captured:
            _REAL_PHASE_C_TREE_VALIDATOR(
                root,
                subject._REVIEWED_PHASE_C_PYTHON_TREE_SHA256,
            )
        assert captured.value.code == "managed_v5_live_phase_c_tree_invalid"


@pytest.mark.parametrize(
    ("relative", "mode"),
    (("foreign.pyc", 0o444), ("foreign.so", 0o444), ("executable-helper", 0o555)),
)
def test_phase_c_tree_rejects_unreviewed_importable_and_executable_artifacts(
    tmp_path: Path,
    relative: str,
    mode: int,
) -> None:
    root = _reviewed_phase_c_tree(tmp_path / relative)
    artifact = root / "phase_c_canary" / relative
    artifact.write_bytes(b"unreviewed artifact")
    artifact.chmod(mode)

    with pytest.raises(ManagedV5LiveConfigError) as captured:
        _REAL_PHASE_C_TREE_VALIDATOR(
            root,
            subject._REVIEWED_PHASE_C_PYTHON_TREE_SHA256,
        )
    assert captured.value.code == "managed_v5_live_phase_c_tree_invalid"


def test_phase_c_malicious_init_is_not_executed_on_tree_mismatch(tmp_path: Path) -> None:
    root = _reviewed_phase_c_tree(tmp_path / "malicious")
    sentinel = tmp_path / "phase-c-init-executed"
    initializer = root / "phase_c_canary" / "__init__.py"
    initializer.write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\n"
    )
    with pytest.raises(ManagedV5LiveConfigError) as captured:
        _REAL_PHASE_C_TREE_VALIDATOR(
            root,
            subject._REVIEWED_PHASE_C_PYTHON_TREE_SHA256,
        )
    assert captured.value.code == "managed_v5_live_phase_c_tree_invalid"
    assert not sentinel.exists()


def test_config_rejects_caller_selected_phase_c_tree_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    with pytest.raises(ManagedV5LiveConfigError) as captured:
        replace(
            config.filesystem,
            phase_c_python_tree_sha256="f" * 64,
        )
    assert captured.value.code == "managed_v5_live_filesystem_config_invalid"
