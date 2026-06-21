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
    assert result.checks["live_provider_proof_matrix_timeout_live_probe"] is True
    assert result.checks["live_provider_proof_matrix_timeout_live_probe_observed"] is True
    assert payload["suite"] == "infinity-context-multimodal-production-goal-audit"
    assert payload["secrets_redacted"] is True


def test_multimodal_production_goal_audit_rejects_incomplete_frontend_proof(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    frontend = _frontend_report()
    flow = frontend["flow_coverage"]
    assert isinstance(flow, dict)
    flow["attachment_modalities"] = [
        item
        for item in flow["attachment_modalities"]
        if isinstance(item, dict) and item.get("modality") != "video"
    ]
    flow["context_link_review_actions"] = {"approve": 1}
    flow["anchor_lifecycle_checks"] = ["create", "cleanup"]
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
    assert result.checks["frontend_marionette_attachment_modalities_complete"] is False
    assert result.checks["frontend_marionette_attachment_artifacts_verified"] is False
    assert result.checks["frontend_marionette_context_review_actions_complete"] is False
    assert result.checks["frontend_marionette_anchor_lifecycle_complete"] is False
    assert any("text/image/audio/video" in failure for failure in result.failures)
    assert any("approve/reject/manual-link" in failure for failure in result.failures)


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
    assert blocked_by_area["live_provider_proof"]["blocking_requirements"] == []
    assert "docker_live_extraction_cases_complete" in result.not_evaluable_checks
    assert "docker_live_capabilities_audio_upload_limit_present" in (result.not_evaluable_checks)
    assert "docker_live_capabilities_vision_payload_limits_present" in (result.not_evaluable_checks)
    assert "docker_live_capabilities_provider_contract_present" in (result.not_evaluable_checks)
    assert "docker_live_capabilities_storage_readiness_contract_present" in (
        result.not_evaluable_checks
    )
    assert "live_provider_components_succeeded" in result.not_evaluable_checks
    assert "live_provider_proof_matrix_vision_real_provider" in result.not_evaluable_checks
    assert "live_provider_proof_matrix_vision_response_evidence" in (
        result.not_evaluable_checks
    )
    assert "live_provider_proof_matrix_transcription_response_artifact" in (
        result.not_evaluable_checks
    )
    assert (
        "live_provider_proof_matrix_audio_transcription_format_matrix"
        in result.not_evaluable_checks
    )
    assert "live_provider_proof_matrix_invalid_key_live_probe" in result.not_evaluable_checks
    assert "live_provider_proof_matrix_timeout_live_probe" in result.not_evaluable_checks
    assert any("Docker multimodal live proof" in failure for failure in result.failures)
    assert any("Live provider canary" in failure for failure in result.failures)
    assert any("docker_daemon_timeout" in failure for failure in result.failures)
    assert any("provider_credential_missing" in failure for failure in result.failures)


def test_multimodal_production_goal_audit_rejects_missing_quality_scorecard(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    quality_report = tmp_path / ".e2e-artifacts" / "memory-quality-scorecard.json"
    quality_report.unlink()
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

    assert result.ok is False
    assert result.checks["memory_quality_scorecard_report_present"] is False
    assert any("Missing memory quality scorecard" in failure for failure in result.failures)


def test_multimodal_production_goal_audit_rejects_failed_quality_scorecard(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    quality_report = tmp_path / ".e2e-artifacts" / "memory-quality-scorecard.json"
    quality = _quality_scorecard_report()
    quality["ok"] = False
    quality["status"] = "failed"
    quality["score"]["maturity_score_10"] = 8.75
    quality["gates"]["all_capabilities_ok"] = False
    quality["capabilities"]["semantic_linking"] = {
        "ok": False,
        "failed_checks": ["ranking_accuracy"],
    }
    quality["metrics"]["safety_leak_count"] = 1
    quality_report.write_text(json.dumps(quality), encoding="utf-8")
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

    assert result.ok is False
    assert result.checks["memory_quality_scorecard_passed"] is False
    assert result.checks["memory_quality_scorecard_maturity_score"] is False
    assert result.checks["memory_quality_scorecard_gate_all_capabilities_ok"] is False
    assert result.checks["memory_quality_scorecard_capability_semantic_linking"] is False
    assert result.checks["memory_quality_scorecard_no_safety_leaks"] is False
    assert result.reports["quality_scorecard"]["score"]["maturity_score_10"] == 8.75
    assert any("semantic_linking" in failure for failure in result.failures)


def test_multimodal_production_goal_audit_carries_provider_readiness_blockers(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    provider = _provider_report()
    provider["ok"] = False
    provider["provider_key_present"] = False
    provider["components"]["provider_key"] = {
        "status": "degraded",
        "reason": "provider_credential_missing",
        "operator_action": "configure_provider_credential",
    }
    provider["readiness"] = {
        "status": "blocked_by_provider_credential",
        "production_ready": False,
        "blocking_requirements": [
            "vision_real_provider",
            "audio_transcription_format_matrix",
        ],
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

    blocked_by_area = {item["area"]: item for item in result.blocked_requirements}
    provider_summary = result.reports["provider"]

    assert result.ok is False
    assert blocked_by_area["live_provider_proof"]["blocking_requirements"] == [
        "vision_real_provider",
        "audio_transcription_format_matrix",
    ]
    assert "live_provider_proof_matrix_vision_real_provider" in result.not_evaluable_checks
    assert (
        "live_provider_proof_matrix_audio_transcription_format_matrix"
        in result.not_evaluable_checks
    )
    assert "live_provider_proof_matrix_invalid_key_live_probe" not in (
        result.not_evaluable_checks
    )
    assert provider_summary["readiness"] == {
        "blocking_requirements": [
            "vision_real_provider",
            "audio_transcription_format_matrix",
        ],
        "production_ready": False,
        "status": "blocked_by_provider_credential",
    }


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


def test_multimodal_production_goal_audit_rejects_failed_provider_report_safety(
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
    requirements["report_safety_contract"] = {
        "failed_checks": ["no_raw_provider_payloads"],
        "ok": False,
        "proof": "bounded_report_surface",
        "requires_provider_key": False,
        "status": "failed",
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
    assert result.checks["live_provider_proof_matrix_report_safety_contract"] is False
    assert any("report_safety_contract" in failure for failure in result.failures)


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


def test_multimodal_production_goal_audit_requires_live_timeout_probe(
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
    requirements["timeout_live_probe"] = {
        "ok": False,
        "observed_reason": "asset_extraction.vision.rate_limited",
        "proof": "live_timeout_call",
        "requires_provider_key": True,
        "status": "failed",
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
    assert result.checks["live_provider_proof_matrix_timeout_live_probe"] is False
    assert result.checks["live_provider_proof_matrix_timeout_live_probe_observed"] is False
    assert any("timeout probe" in failure for failure in result.failures)


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
    assert result.checks["docker_live_capabilities_file_type_detection_present"] is False
    assert result.checks["docker_live_capabilities_resource_policy_present"] is False
    assert result.checks["docker_live_capabilities_upload_security_fields_present"] is False
    assert result.checks["docker_live_capabilities_archive_limits_present"] is False
    assert result.checks["docker_live_capabilities_image_pixel_limit_present"] is False
    assert result.checks["docker_live_capabilities_media_duration_limit_present"] is False
    assert result.checks["docker_live_capabilities_parser_timeout_present"] is False
    assert result.checks[
        "docker_live_capabilities_manifest_evidence_contracts_present"
    ] is False
    assert result.checks[
        "docker_live_capabilities_storage_readiness_contract_present"
    ] is False
    assert any("provider capability contract" in failure for failure in result.failures)


def test_multimodal_production_goal_audit_rejects_docker_without_resource_security(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    docker = _docker_report()
    docker_capabilities = docker["components"]["capabilities"]
    assert isinstance(docker_capabilities, dict)
    docker_capabilities["contract_names"] = [
        "evidence_contract",
        "feature_contract",
        "manifest_contract",
        "provider_contract",
    ]
    docker_capabilities.pop("file_type_detection", None)
    docker_capabilities["resource_policy"] = {"ok": False}
    docker_capabilities["limits"] = {"max_media_seconds": None}
    docker_capabilities["manifest_contract_present"] = False
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
    assert result.checks["docker_live_capabilities_provider_contract_present"] is True
    assert result.checks["docker_live_capabilities_file_type_detection_present"] is False
    assert result.checks["docker_live_capabilities_resource_policy_present"] is False
    assert result.checks["docker_live_capabilities_archive_limits_present"] is False
    assert result.checks["docker_live_capabilities_image_pixel_limit_present"] is False
    assert result.checks["docker_live_capabilities_media_duration_limit_present"] is False
    assert result.checks["docker_live_capabilities_parser_timeout_present"] is False
    assert result.checks[
        "docker_live_capabilities_manifest_evidence_contracts_present"
    ] is False
    assert any("resource policy" in failure for failure in result.failures)


def test_multimodal_production_goal_audit_rejects_docker_without_storage_readiness(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    docker = _docker_report()
    docker_capabilities = docker["components"]["capabilities"]
    assert isinstance(docker_capabilities, dict)
    docker_capabilities.pop("storage_readiness", None)
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
    assert result.checks[
        "docker_live_capabilities_storage_readiness_contract_present"
    ] is False
    assert any("storage deployment readiness" in failure for failure in result.failures)


def test_multimodal_production_goal_audit_rejects_docker_without_storage_production_targets(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _write_core(tmp_path)
    frontend_report = tmp_path / "frontend.json"
    docker_report = tmp_path / "docker.json"
    provider_report = tmp_path / "provider.json"
    docker = _docker_report()
    docker_capabilities = docker["components"]["capabilities"]
    assert isinstance(docker_capabilities, dict)
    storage_readiness = docker_capabilities["storage_readiness"]
    assert isinstance(storage_readiness, dict)
    storage_readiness.pop("production_readiness", None)
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
    assert result.checks[
        "docker_live_capabilities_storage_production_readiness_contract_present"
    ] is False
    assert any("storage production readiness" in failure for failure in result.failures)


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
    assert "infinity-context-quality-scorecard" in makefile
    assert "--report-out .e2e-artifacts/memory-quality-scorecard.json" in makefile


def _write_core(root: Path) -> None:
    core = root / "packages/infinity_context_core/infinity_context_core"
    core.mkdir(parents=True)
    (core / "__init__.py").write_text("# clean core\n", encoding="utf-8")
    evidence = root / ".e2e-artifacts"
    evidence.mkdir(parents=True)
    (evidence / "memory-quality-scorecard.json").write_text(
        json.dumps(_quality_scorecard_report()),
        encoding="utf-8",
    )


def _quality_scorecard_report() -> dict[str, object]:
    capabilities = {
        "canonical_recall_precision": {"ok": True, "failed_checks": []},
        "retrieval_context_memory_layer": {"ok": True, "failed_checks": []},
        "longitudinal_memory": {"ok": True, "failed_checks": []},
        "auto_memory_admission": {"ok": True, "failed_checks": []},
        "semantic_linking": {"ok": True, "failed_checks": []},
        "dedup_merge_conflict_resolution": {"ok": True, "failed_checks": []},
        "multimodal_evidence_retrieval": {"ok": True, "failed_checks": []},
        "graph_native_recall": {"ok": True, "failed_checks": []},
        "scope_and_safety": {"ok": True, "failed_checks": []},
        "prompt_context_contract": {"ok": True, "failed_checks": []},
    }
    return {
        "suite": "memory-quality-scorecard",
        "status": "ok",
        "ok": True,
        "score": {
            "passed_checks": 19,
            "total_checks": 19,
            "score_percent": 1.0,
            "maturity_score_10": 10.0,
            "minimum_maturity_score_10": 9.0,
        },
        "gates": {
            "required_suites_present": True,
            "all_suites_ok": True,
            "all_capabilities_ok": True,
            "maturity_score_min": True,
        },
        "capabilities": capabilities,
        "metrics": {
            "quality_recall_at_5": 0.96,
            "quality_precision_at_5": 0.95,
            "semantic_linking_ranking_accuracy": 1.0,
            "multimodal_offline_pass_rate": 1.0,
            "safety_leak_count": 0,
        },
        "failures": [],
    }


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
            "attachment_modalities": [
                {
                    "modality": "text",
                    "parser_name": "simple_text",
                    "artifact_types": ["markdown"],
                    "document_created": True,
                },
                {
                    "modality": "image",
                    "parser_name": "image_metadata",
                    "artifact_types": ["image_regions", "markdown"],
                    "document_created": True,
                },
                {
                    "modality": "audio",
                    "parser_name": "media_metadata",
                    "artifact_types": ["markdown", "media_manifest"],
                    "document_created": True,
                },
                {
                    "modality": "video",
                    "parser_name": "media_metadata",
                    "artifact_types": [
                        "keyframe",
                        "markdown",
                        "media_manifest",
                        "video_frame_timeline",
                    ],
                    "document_created": True,
                },
            ],
            "context_link_review_actions": {
                "approve": 1,
                "reject": 1,
                "manual_link": 1,
            },
            "anchor_lifecycle_checks": [
                "create",
                "update",
                "split_alias",
                "merge_duplicate",
                "cleanup",
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
                    "policy",
                    "provider_contract",
                    "resource_policy",
                ],
                "provider_contract": {
                    "ok": True,
                    "transcription_endpoint": "/v1/audio/transcriptions",
                    "transcription_max_provider_upload_bytes": 25 * 1024 * 1024,
                    "transcription_effective_max_upload_bytes": 25 * 1024 * 1024,
                    "transcription_supported_file_types": [
                        ".flac",
                        ".m4a",
                        ".mp3",
                        ".mp4",
                        ".mpeg",
                        ".mpga",
                        ".ogg",
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
                "file_type_detection": {
                    "ok": True,
                    "declared_content_type_trusted": False,
                    "filename_extension_trusted": False,
                    "empty_upload_policy": "reject_at_upload",
                    "upload_body_stream_limited": True,
                    "archive_policy_complete": True,
                    "image_policy_complete": True,
                    "diagnostics_complete": True,
                },
                "resource_policy": {
                    "ok": True,
                    "limits_normalized_before_provider": True,
                    "rejects_oversized_asset_before_blob_read": True,
                    "revalidates_upload_policy_after_blob_read": True,
                    "inspects_zip_central_directory_before_provider": True,
                    "archive_rejection_policy_complete": True,
                    "diagnostics_complete": True,
                    "hard_caps_present": True,
                },
                "limits": {
                    "ok": True,
                    "max_bytes": 25 * 1024 * 1024,
                    "max_media_seconds": 600,
                    "max_image_pixels": 20_000_000,
                    "max_archive_entries": 1000,
                    "max_archive_uncompressed_bytes": 100 * 1024 * 1024,
                    "max_archive_single_entry_bytes": 50 * 1024 * 1024,
                    "max_archive_compression_ratio": 100.0,
                    "parser_timeout_seconds": 120,
                    "subprocess_timeout_seconds": 60,
                    "provider_timeout_seconds": 60,
                },
                "policy": {
                    "ok": True,
                    "source_text_policy": "untrusted_evidence",
                    "provider_payloads_bounded": True,
                    "sensitive_data_in_diagnostics": False,
                },
                "storage_readiness": {
                    "ok": True,
                    "schema_version": "asset-storage-deployment-readiness-v2",
                    "asset_backend": "local",
                    "asset_external": False,
                    "self_host_ready": True,
                    "hosted_team_ready": False,
                    "self_host_production_ready": False,
                    "hosted_team_production_ready": False,
                    "schema_management_mode": "auto_create",
                    "auto_create_schema_enabled": True,
                    "auto_create_schema_allowed_in_server_profile": False,
                    "migration_runner_required": False,
                    "migration_runner_service": "infinity_context_migrate",
                    "migration_strategy": "external_forward_migrations",
                    "recommended_hosted_backend": "s3",
                    "blob_identity": "sha256",
                    "duplicate_detection": "exact_sha256",
                    "scope_storage_quota_enforced": True,
                    "scope_storage_quota_bytes": 5 * 1024 * 1024 * 1024,
                    "scope_storage_quota_unlimited_when_zero": True,
                    "storage_cleanup_supported": True,
                    "maintenance_enabled": False,
                    "cleanup_apply_enabled": False,
                    "backup_policy_configured": False,
                    "object_lifecycle_policy_configured": False,
                    "safe_diagnostics": True,
                    "degraded_reasons": [],
                    "warnings": [
                        "hosted_team_deployments_should_use_s3_compatible_storage",
                        "asset_storage_backup_policy_not_confirmed",
                        "asset_storage_maintenance_not_enabled",
                    ],
                    "production_readiness": {
                        "schema_version": "asset-storage-production-readiness-v1",
                        "requirement_status": {
                            "asset_storage_configured": True,
                            "asset_storage_ready": True,
                            "s3_compatible_backend": False,
                            "external_migration_runner": False,
                            "backup_policy": False,
                            "object_lifecycle_policy": False,
                            "maintenance_worker": False,
                            "cleanup_apply": False,
                            "s3_region": False,
                        },
                        "self_host": {
                            "production_ready": False,
                            "blocking_requirements": [
                                "external_migration_runner",
                                "backup_policy",
                                "maintenance_worker",
                                "cleanup_apply",
                            ],
                            "operator_actions": [
                                "disable_auto_schema_and_run_migrations",
                                "configure_asset_storage_backup_policy",
                                "enable_asset_storage_maintenance_worker",
                                "enable_asset_storage_cleanup_apply",
                            ],
                        },
                        "hosted_team": {
                            "production_ready": False,
                            "blocking_requirements": [
                                "s3_compatible_backend",
                                "external_migration_runner",
                                "backup_policy",
                                "object_lifecycle_policy",
                                "maintenance_worker",
                                "cleanup_apply",
                                "s3_region",
                            ],
                            "operator_actions": [
                                "use_s3_compatible_asset_storage",
                                "disable_auto_schema_and_run_migrations",
                                "configure_asset_storage_backup_policy",
                                "configure_s3_object_lifecycle_policy",
                                "enable_asset_storage_maintenance_worker",
                                "enable_asset_storage_cleanup_apply",
                                "configure_s3_region",
                            ],
                        },
                    },
                },
                "manifest_contract_present": True,
                "evidence_contract_present": True,
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
                    ".flac",
                    ".m4a",
                    ".mp3",
                    ".mp4",
                    ".mpeg",
                    ".mpga",
                    ".ogg",
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
            "vision_response_evidence": {
                "status": "succeeded",
                "proof": "live_provider_evidence_shape",
                "requires_provider_key": True,
                "ok": True,
                "visible_text_count": 1,
                "summary_chars": 40,
            },
            "transcription_response_artifact": {
                "status": "succeeded",
                "proof": "live_provider_artifact_shape",
                "requires_provider_key": True,
                "ok": True,
                "response_format": "json",
                "transcript_chars": 80,
                "segment_count": 0,
                "word_count": 0,
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
            "timeout_live_probe": {
                "status": "succeeded",
                "proof": "live_timeout_call",
                "requires_provider_key": True,
                "ok": True,
                "observed_reason": "asset_extraction.vision.timeout",
                "timeout_seconds": 0.001,
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
            "transcription_request_contract": {
                "status": "contract_covered",
                "proof": "adapter_request_contract",
                "requires_provider_key": False,
                "ok": True,
                "response_format": "json",
                "supports_prompt": True,
                "supports_segment_timestamps": False,
                "requires_chunking_strategy": False,
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
            "report_safety_contract": {
                "status": "contract_covered",
                "proof": "bounded_report_surface",
                "requires_provider_key": False,
                "ok": True,
                "failed_checks": [],
                "max_depth": 12,
                "max_string_chars": 4096,
            },
        },
        "summary": {
            "live_requirements_passed": 7,
            "live_requirements_total": 7,
            "contract_requirements_passed": 9,
            "contract_requirements_total": 9,
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
