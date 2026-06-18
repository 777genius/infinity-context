from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "multimodal_production_goal_audit.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("multimodal_production_goal_audit", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_multimodal_production_goal_audit_accepts_complete_proof(tmp_path: Path) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    frontend_report.write_text(json.dumps(_frontend_report()), encoding="utf-8")
    docker_report.write_text(json.dumps(_docker_report()), encoding="utf-8")
    provider_report.write_text(json.dumps(_provider_report()), encoding="utf-8")

    result = module.run_goal_audit(
        root=tmp_path,
        frontend_report=frontend_report.relative_to(tmp_path),
        docker_report=docker_report.relative_to(tmp_path),
        provider_report=provider_report.relative_to(tmp_path),
        require_clean_git=False,
        git={"commit": "abc", "short_commit": "abc", "dirty": False},
    )

    payload = result.as_dict()
    assert result.ok is True
    assert result.failures == ()
    assert all(result.checks.values())
    assert payload["suite"] == "memo-stack-multimodal-production-goal-audit"
    assert payload["secrets_redacted"] is True


def test_multimodal_production_goal_audit_rejects_degraded_external_proofs(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    frontend_report.write_text(json.dumps(_frontend_report()), encoding="utf-8")
    docker_report.write_text(
        json.dumps(
            {
                "suite": "memo-stack-multimodal-docker-live-proof",
                "ok": False,
                "git": {"commit": "abc", "short_commit": "abc", "dirty": False},
                "components": {
                    "docker_daemon": {
                        "status": "degraded",
                        "reason": "docker_daemon_timeout",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    provider_report.write_text(
        json.dumps(
            {
                "suite": "memo-stack-multimodal-live-provider-canary",
                "ok": False,
                "git": {"commit": "abc", "short_commit": "abc", "dirty": False},
                "provider_key_present": False,
                "components": {
                    "provider_key": {
                        "status": "degraded",
                        "reason": "provider_credential_missing",
                    },
                    "vision": {"status": "skipped"},
                    "transcription": {"status": "skipped"},
                },
            }
        ),
        encoding="utf-8",
    )

    result = module.run_goal_audit(
        root=tmp_path,
        frontend_report=frontend_report.relative_to(tmp_path),
        docker_report=docker_report.relative_to(tmp_path),
        provider_report=provider_report.relative_to(tmp_path),
        require_clean_git=False,
        git={"commit": "abc", "short_commit": "abc", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["docker_live_proof_passed"] is False
    assert result.checks["live_provider_proof_passed"] is False
    assert result.checks["live_provider_clean_commit"] is True
    assert result.checks["live_provider_key_present"] is False
    assert any("Docker multimodal live proof" in failure for failure in result.failures)
    assert any("Live provider canary" in failure for failure in result.failures)


def test_multimodal_production_goal_audit_rejects_frontend_runtime_log_failure(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    frontend = _frontend_report()
    frontend["components"]["flutter_runtime_log"] = {
        "status": "failed",
        "forbidden_marker_count": 1,
        "markers": [
            {
                "marker": "RenderFlex overflowed",
                "snippet": "A RenderFlex overflowed by 42 pixels.",
            }
        ],
    }
    frontend_report.write_text(json.dumps(frontend), encoding="utf-8")
    docker_report.write_text(json.dumps(_docker_report()), encoding="utf-8")
    provider_report.write_text(json.dumps(_provider_report()), encoding="utf-8")

    result = module.run_goal_audit(
        root=tmp_path,
        frontend_report=frontend_report.relative_to(tmp_path),
        docker_report=docker_report.relative_to(tmp_path),
        provider_report=provider_report.relative_to(tmp_path),
        require_clean_git=False,
        git={"commit": "abc", "short_commit": "abc", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["frontend_marionette_components_succeeded"] is False
    assert any("runtime log component failed" in failure for failure in result.failures)


def test_multimodal_production_goal_audit_rejects_provider_proof_without_git(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    provider = _provider_report()
    provider.pop("git")
    frontend_report.write_text(json.dumps(_frontend_report()), encoding="utf-8")
    docker_report.write_text(json.dumps(_docker_report()), encoding="utf-8")
    provider_report.write_text(json.dumps(provider), encoding="utf-8")

    result = module.run_goal_audit(
        root=tmp_path,
        frontend_report=frontend_report.relative_to(tmp_path),
        docker_report=docker_report.relative_to(tmp_path),
        provider_report=provider_report.relative_to(tmp_path),
        require_clean_git=False,
        git={"commit": "abc", "short_commit": "abc", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["live_provider_clean_commit"] is False
    assert any("Live provider proof must be tied" in failure for failure in result.failures)


def test_multimodal_production_goal_audit_rejects_core_boundary_and_secret_leak(
    tmp_path: Path,
) -> None:
    module = _load_module()
    core = tmp_path / "packages/memo_stack_core/memo_stack_core"
    core.mkdir(parents=True)
    (core / "bad.py").write_text("from fastapi import FastAPI\n", encoding="utf-8")
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    frontend = _frontend_report()
    frontend["leaked"] = "Bearer sk-test-secret"
    frontend_report.write_text(json.dumps(frontend), encoding="utf-8")
    docker_report.write_text(json.dumps(_docker_report()), encoding="utf-8")
    provider_report.write_text(json.dumps(_provider_report()), encoding="utf-8")

    result = module.run_goal_audit(
        root=tmp_path,
        frontend_report=frontend_report.relative_to(tmp_path),
        docker_report=docker_report.relative_to(tmp_path),
        provider_report=provider_report.relative_to(tmp_path),
        require_clean_git=False,
        git={"commit": "abc", "short_commit": "abc", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["core_boundary_clean"] is False
    assert result.checks["proof_reports_do_not_leak_secrets"] is False
    assert any("memo_stack_core imports forbidden" in failure for failure in result.failures)
    assert any("secret-like value" in failure for failure in result.failures)


def test_makefile_exposes_multimodal_production_goal_audit_target() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert ".PHONY: memo-stack-multimodal-production-goal-audit" in makefile
    assert "$(PYTHON) scripts/multimodal_production_goal_audit.py" in makefile


def _write_core(root: Path) -> None:
    core = root / "packages/memo_stack_core/memo_stack_core"
    core.mkdir(parents=True)
    (core / "__init__.py").write_text("# clean core\n", encoding="utf-8")


def _frontend_report() -> dict[str, object]:
    return {
        "suite": "memo-stack-frontend-marionette-local-e2e",
        "ok": True,
        "git": {"commit": "abc", "short_commit": "abc", "dirty": False},
        "components": {
            "server": {"status": "succeeded"},
            "worker": {"status": "succeeded"},
            "flutter_marionette": {"status": "succeeded"},
            "flutter_runtime_log": {"status": "succeeded"},
        },
        "flow_coverage": {
            "status": "succeeded",
            "completed_flows": [
                "memory_scope_management",
                "capture_link_approve",
                "context_link_reject",
                "attachment_capture_extraction",
                "manual_context_link_override",
                "anchor_lifecycle_cleanup",
            ],
        },
    }


def _docker_report() -> dict[str, object]:
    return {
        "suite": "memo-stack-multimodal-docker-live-proof",
        "ok": True,
        "git": {"commit": "abc", "short_commit": "abc", "dirty": False},
        "components": {
            "docker_daemon": {"status": "succeeded"},
            "compose_config": {"status": "succeeded"},
            "compose_stack": {"status": "succeeded"},
            "container_dependencies": {"status": "succeeded"},
            "health": {"status": "succeeded"},
            "capabilities": {"status": "succeeded"},
            "cleanup": {"status": "succeeded"},
            "extraction_flow": {
                "status": "succeeded",
                "cases": [
                    {"filename": "docker-proof.txt"},
                    {"filename": "docker-proof.pdf"},
                    {"filename": "docker-proof.png"},
                    {"filename": "docker-proof.wav"},
                    {"filename": "docker-proof.mp4"},
                ],
            },
        },
    }


def _provider_report() -> dict[str, object]:
    return {
        "suite": "memo-stack-multimodal-live-provider-canary",
        "ok": True,
        "git": {"commit": "abc", "short_commit": "abc", "dirty": False},
        "provider_key_present": True,
        "components": {
            "provider_key": {"status": "configured"},
            "vision": {"status": "succeeded"},
            "transcription": {"status": "succeeded"},
        },
    }
