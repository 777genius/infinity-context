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
    assert result.blocked_requirements == ()
    assert result.not_evaluable_checks == ()
    assert payload["blocked_requirements"] == []
    assert payload["not_evaluable_checks"] == []
    assert all(result.checks.values())
    assert payload["suite"] == "infinity-context-multimodal-production-goal-audit"
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
                "suite": "infinity-context-multimodal-docker-live-proof",
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
                "suite": "infinity-context-multimodal-live-provider-canary",
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
    blocked_by_area = {item["area"]: item for item in result.blocked_requirements}
    assert blocked_by_area["docker_live_proof"]["reason"] == "docker_daemon_timeout"
    assert blocked_by_area["docker_live_proof"]["operator_action"] is None
    assert blocked_by_area["live_provider_proof"]["reason"] == "provider_credential_missing"
    assert "docker_live_extraction_cases_complete" in result.not_evaluable_checks
    assert "docker_live_capabilities_audio_upload_limit_present" in (result.not_evaluable_checks)
    assert "docker_live_capabilities_vision_payload_limits_present" in (result.not_evaluable_checks)
    assert "docker_live_capabilities_provider_contract_present" in (result.not_evaluable_checks)
    assert "live_provider_components_succeeded" in result.not_evaluable_checks
    assert any("Docker multimodal live proof" in failure for failure in result.failures)
    assert any("Live provider canary" in failure for failure in result.failures)
    assert any("docker_daemon_timeout" in failure for failure in result.failures)
    assert any("provider_credential_missing" in failure for failure in result.failures)


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


def test_multimodal_production_goal_audit_reports_frontend_runtime_blocker(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    frontend = _frontend_report()
    frontend["ok"] = False
    frontend["failure"] = {
        "component": "flutter_pub_get",
        "degraded": True,
        "operator_action": "install_flutter_sdk_or_set_FLUTTER",
        "reason": "flutter_runtime_missing",
        "user_retryable": False,
    }
    frontend["components"]["flutter_pub_get"] = {
        "status": "degraded",
        "reason": "flutter_runtime_missing",
    }
    frontend["components"]["flutter_marionette"] = {
        "status": "skipped",
        "reason": "flutter_runtime_missing",
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

    blocked_by_area = {item["area"]: item for item in result.blocked_requirements}

    assert result.ok is False
    assert result.checks["frontend_marionette_passed"] is False
    assert blocked_by_area["frontend_marionette_proof"]["component"] == "flutter_pub_get"
    assert (
        blocked_by_area["frontend_marionette_proof"]["operator_action"]
        == "install_flutter_sdk_or_set_FLUTTER"
    )
    assert "frontend_marionette_flows_complete" in result.not_evaluable_checks
    assert any("flutter_runtime_missing" in failure for failure in result.failures)


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


def test_multimodal_production_goal_audit_rejects_stale_report_commits(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    frontend = _frontend_report()
    docker = _docker_report()
    provider = _provider_report()
    frontend["git"] = {"commit": "old", "short_commit": "old", "dirty": False}
    docker["git"] = {"commit": "old", "short_commit": "old", "dirty": False}
    provider["git"] = {"commit": "old", "short_commit": "old", "dirty": False}
    frontend_report.write_text(json.dumps(frontend), encoding="utf-8")
    docker_report.write_text(json.dumps(docker), encoding="utf-8")
    provider_report.write_text(json.dumps(provider), encoding="utf-8")

    result = module.run_goal_audit(
        root=tmp_path,
        frontend_report=frontend_report.relative_to(tmp_path),
        docker_report=docker_report.relative_to(tmp_path),
        provider_report=provider_report.relative_to(tmp_path),
        require_clean_git=False,
        git={"commit": "current", "short_commit": "current", "dirty": False},
    )

    assert result.ok is False
    assert result.checks["frontend_marionette_current_commit"] is False
    assert result.checks["docker_live_current_commit"] is False
    assert result.checks["live_provider_current_commit"] is False
    assert any(
        "Frontend Marionette proof must be generated" in failure for failure in result.failures
    )
    assert any("Docker live proof must be generated" in failure for failure in result.failures)
    assert any("Live provider proof must be generated" in failure for failure in result.failures)


def test_multimodal_production_goal_audit_rejects_stale_provider_contract(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    provider = _provider_report()
    provider["provider_contract"] = {
        "transcription": {
            "endpoint": "/v1/audio/transcriptions",
            "max_upload_bytes": 25 * 1024 * 1024,
            "supported_file_types": [".mp3", ".wav"],
        },
        "vision": {
            "endpoint_family": "responses",
            "supported_file_types": [".jpg", ".png"],
        },
    }
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
    assert result.checks["live_provider_contract_present"] is True
    assert result.checks["live_provider_transcription_contract_docs_aligned"] is False
    assert result.checks["live_provider_vision_contract_docs_aligned"] is False
    assert result.checks["live_provider_vision_detail_contract_docs_aligned"] is False
    assert result.checks["live_provider_vision_binary_limit_present"] is False
    assert result.checks["live_provider_contract_includes_current_audio_suffixes"] is False
    assert result.checks["live_provider_contract_requires_wav_mp3_proof"] is False
    assert any("transcription contract" in failure for failure in result.failures)
    assert any("vision contract" in failure for failure in result.failures)
    assert any("current OpenAI audio suffixes" in failure for failure in result.failures)


def test_multimodal_production_goal_audit_rejects_bad_provider_failure_policy(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    provider = _provider_report()
    provider["failure_policy_contract"]["rate_limited"] = {
        "operator_action": "inspect_provider_canary",
        "reason": "asset_extraction.transcription.rate_limited",
        "status": "failed",
        "user_retryable": False,
    }
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
    assert result.checks["live_provider_failure_policy_contract_present"] is True
    assert result.checks["live_provider_failure_policy_rate_limited"] is False
    assert result.checks["live_provider_failure_policy_invalid_api_key"] is True
    assert any("failure policy for rate_limited" in failure for failure in result.failures)


def test_multimodal_production_goal_audit_rejects_missing_provider_proof_matrix(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    provider = _provider_report()
    provider.pop("proof_matrix")
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
    assert result.checks["live_provider_proof_matrix_present"] is False
    assert result.checks["live_provider_proof_matrix_vision_real_provider"] is False
    assert any("provider proof matrix" in failure for failure in result.failures)


def test_multimodal_production_goal_audit_requires_live_invalid_key_probe(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    provider = _provider_report()
    proof_matrix = provider["proof_matrix"]
    assert isinstance(proof_matrix, dict)
    requirements = proof_matrix["requirements"]
    assert isinstance(requirements, dict)
    requirements["invalid_key_live_probe"] = {
        "ok": False,
        "proof": "live_invalid_credential_call",
        "reason": "invalid_key_probe_not_requested",
        "requires_provider_key": False,
        "status": "skipped",
    }
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
    assert result.checks["live_provider_proof_matrix_invalid_key_live_probe"] is False
    assert result.checks["live_provider_proof_matrix_invalid_key_live_probe_observed"] is False
    assert (
        result.checks[
            "live_provider_proof_matrix_invalid_key_probe_covers_vision_and_transcription"
        ]
        is False
    )
    assert any("invalid-key probe" in failure for failure in result.failures)


def test_multimodal_production_goal_audit_rejects_docker_without_provider_contract(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    docker = _docker_report()
    docker["components"]["capabilities"] = {
        "status": "succeeded",
        "contract_names": ["evidence_contract", "manifest_contract"],
    }
    frontend_report.write_text(json.dumps(_frontend_report()), encoding="utf-8")
    docker_report.write_text(json.dumps(docker), encoding="utf-8")
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
    assert result.checks["docker_live_components_succeeded"] is True
    assert result.checks["docker_live_capabilities_provider_contract_present"] is False
    assert result.checks["docker_live_capabilities_provider_contract_docs_aligned"] is False
    assert result.checks["docker_live_capabilities_audio_upload_limit_present"] is False
    assert result.checks["docker_live_capabilities_vision_detail_contract_docs_aligned"] is False
    assert result.checks["docker_live_capabilities_vision_binary_limit_present"] is False
    assert result.checks["docker_live_capabilities_vision_payload_limits_present"] is False
    assert any("provider capability contract" in failure for failure in result.failures)


def test_multimodal_production_goal_audit_rejects_core_boundary_and_secret_leak(
    tmp_path: Path,
) -> None:
    module = _load_module()
    core = tmp_path / "packages/infinity_context_core/infinity_context_core"
    core.mkdir(parents=True)
    (core / "bad.py").write_text("from fastapi import FastAPI\n", encoding="utf-8")
    (core / "adapter_bad.py").write_text(
        "from infinity_context_adapters.noop import adapters\n",
        encoding="utf-8",
    )
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
    assert any("infinity_context_core imports forbidden" in failure for failure in result.failures)
    assert any("secret-like value" in failure for failure in result.failures)


def test_makefile_exposes_multimodal_production_goal_audit_target() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert ".PHONY: infinity-context-multimodal-production-goal-audit" in makefile
    assert "$(PYTHON) scripts/multimodal_production_goal_audit.py" in makefile


def _write_core(root: Path) -> None:
    core = root / "packages/infinity_context_core/infinity_context_core"
    core.mkdir(parents=True)
    (core / "__init__.py").write_text("# clean core\n", encoding="utf-8")


def _frontend_report() -> dict[str, object]:
    return {
        "suite": "infinity-context-frontend-marionette-local-e2e",
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
        "suite": "infinity-context-multimodal-docker-live-proof",
        "ok": True,
        "git": {"commit": "abc", "short_commit": "abc", "dirty": False},
        "components": {
            "docker_daemon": {"status": "succeeded"},
            "docker_disk_preflight": {"status": "succeeded"},
            "compose_config": {"status": "succeeded"},
            "compose_stack": {"status": "succeeded"},
            "container_dependencies": {"status": "succeeded"},
            "health": {"status": "succeeded"},
            "capabilities": {
                "status": "succeeded",
                "contract_names": [
                    "evidence_contract",
                    "feature_contract",
                    "file_type_detection",
                    "manifest_contract",
                    "provider_contract",
                ],
                "provider_contract": {
                    "ok": True,
                    "transcription_endpoint": "/v1/audio/transcriptions",
                    "transcription_max_provider_upload_bytes": 25 * 1024 * 1024,
                    "transcription_effective_max_upload_bytes": 25 * 1024 * 1024,
                    "transcription_supported_file_types": [
                        ".m4a",
                        ".mp3",
                        ".mp4",
                        ".mpeg",
                        ".mpga",
                        ".wav",
                        ".webm",
                    ],
                    "vision_endpoint_family": "responses",
                    "vision_model": "gpt-4.1-mini",
                    "vision_detail_levels": ["low", "high", "auto"],
                    "vision_max_provider_binary_upload_bytes": 402650094,
                    "vision_max_provider_payload_bytes": 536870912,
                    "vision_max_images_per_request": 1500,
                    "vision_effective_max_upload_bytes": 25 * 1024 * 1024,
                    "vision_supported_file_types": [
                        ".gif",
                        ".jpeg",
                        ".jpg",
                        ".png",
                        ".webp",
                    ],
                },
            },
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
        "suite": "infinity-context-multimodal-live-provider-canary",
        "ok": True,
        "git": {"commit": "abc", "short_commit": "abc", "dirty": False},
        "provider_key_present": True,
        "failure_policy_contract": _failure_policy_contract(),
        "proof_matrix": _provider_proof_matrix(),
        "provider_contract": {
            "external_ai_required": True,
            "timeout_seconds": 60.0,
            "transcription": {
                "docs_url": "https://developers.openai.com/api/docs/guides/speech-to-text",
                "endpoint": "/v1/audio/transcriptions",
                "max_upload_bytes": 25 * 1024 * 1024,
                "model": "gpt-4o-mini-transcribe",
                "required_live_file_types": [".mp3", ".wav"],
                "supported_file_types": [
                    ".m4a",
                    ".mp3",
                    ".mp4",
                    ".mpeg",
                    ".mpga",
                    ".wav",
                    ".webm",
                ],
            },
            "vision": {
                "detail": "low",
                "detail_levels": ["low", "high", "auto"],
                "docs_url": "https://developers.openai.com/api/docs/guides/images-vision",
                "endpoint_family": "responses",
                "max_provider_binary_upload_bytes": 402650094,
                "model": "gpt-4.1-mini",
                "supported_file_types": [".gif", ".jpeg", ".jpg", ".png", ".webp"],
            },
        },
        "components": {
            "provider_key": {"status": "configured"},
            "vision": {"status": "succeeded"},
            "transcription": {"status": "succeeded"},
        },
    }


def _provider_proof_matrix() -> dict[str, object]:
    return {
        "schema_version": "multimodal-provider-proof-matrix-v1",
        "requirements": {
            "vision_real_provider": {
                "status": "succeeded",
                "proof": "live_provider_call",
                "requires_provider_key": True,
                "ok": True,
            },
            "audio_transcription_real_provider": {
                "status": "succeeded",
                "proof": "live_provider_call",
                "requires_provider_key": True,
                "ok": True,
            },
            "audio_transcription_format_matrix": {
                "status": "succeeded",
                "proof": "live_provider_format_matrix",
                "requires_provider_key": True,
                "ok": True,
                "required_suffixes": [".mp3", ".wav"],
                "covered_suffixes": [".mp3", ".wav"],
            },
            "invalid_key_live_probe": {
                "status": "succeeded",
                "proof": "live_invalid_credential_call",
                "requires_provider_key": False,
                "ok": True,
                "observed_reason": (
                    "vision:asset_extraction.vision.invalid_api_key; "
                    "transcription:asset_extraction.transcription.invalid_api_key"
                ),
                "observed_reasons": {
                    "vision": "asset_extraction.vision.invalid_api_key",
                    "transcription": "asset_extraction.transcription.invalid_api_key",
                },
                "provider_probe_count": 2,
            },
            "vision_fixture_contract": {
                "status": "contract_covered",
                "proof": "local_fixture_contract",
                "requires_provider_key": True,
                "ok": True,
                "suffix": ".png",
                "content_type": "image/png",
            },
            "audio_fixture_contract": {
                "status": "contract_covered",
                "proof": "local_fixture_contract",
                "requires_provider_key": True,
                "ok": True,
                "suffix": ".wav",
                "content_type": "audio/wav",
            },
            "audio_fixture_format_coverage": {
                "status": "contract_covered",
                "proof": "local_fixture_format_matrix",
                "requires_provider_key": False,
                "ok": True,
                "required_suffixes": [".mp3", ".wav"],
                "covered_suffixes": [".mp3", ".wav"],
            },
            "invalid_key_classification": {
                "status": "contract_covered",
                "proof": "adapter_contract_test",
                "requires_provider_key": False,
                "ok": True,
                "operator_action": "replace_provider_credential",
                "reason": "asset_extraction.vision.invalid_api_key",
                "user_retryable": False,
            },
            "rate_limit_classification": {
                "status": "contract_covered",
                "proof": "adapter_contract_test",
                "requires_provider_key": False,
                "ok": True,
                "operator_action": "retry_later",
                "reason": "asset_extraction.transcription.rate_limited",
                "user_retryable": True,
            },
            "timeout_classification": {
                "status": "contract_covered",
                "proof": "adapter_contract_test",
                "requires_provider_key": False,
                "ok": True,
                "operator_action": "retry_later",
                "reason": "asset_extraction.vision.timeout",
                "user_retryable": True,
            },
            "no_secret_leak_guard": {
                "status": "contract_covered",
                "proof": "bounded_report_redaction",
                "requires_provider_key": False,
                "ok": True,
            },
        },
        "summary": {
            "live_requirements_passed": 5,
            "live_requirements_total": 5,
            "contract_requirements_passed": 5,
            "contract_requirements_total": 5,
        },
    }


def _failure_policy_contract() -> dict[str, dict[str, object]]:
    return {
        "provider_credential_missing": {
            "operator_action": "configure_provider_credential",
            "reason": "provider_credential_missing",
            "status": "degraded",
            "user_retryable": False,
        },
        "invalid_api_key": {
            "operator_action": "replace_provider_credential",
            "reason": "asset_extraction.vision.invalid_api_key",
            "status": "failed",
            "user_retryable": False,
        },
        "quota_exceeded": {
            "operator_action": "check_provider_billing",
            "reason": "asset_extraction.transcription.quota_exceeded",
            "status": "failed",
            "user_retryable": False,
        },
        "rate_limited": {
            "operator_action": "retry_later",
            "reason": "asset_extraction.transcription.rate_limited",
            "status": "failed",
            "user_retryable": True,
        },
        "timeout": {
            "operator_action": "retry_later",
            "reason": "asset_extraction.vision.timeout",
            "status": "failed",
            "user_retryable": True,
        },
    }
