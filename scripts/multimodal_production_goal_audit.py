#!/usr/bin/env python3
"""Audit proof artifacts for the multimodal production goal."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

SUITE = "infinity-context-multimodal-production-goal-audit"

DEFAULT_FRONTEND_REPORT = ".e2e-artifacts/frontend-marionette-local-e2e.json"
DEFAULT_DOCKER_REPORT = ".e2e-artifacts/multimodal-docker-live-proof.json"
DEFAULT_PROVIDER_REPORT = ".e2e-artifacts/multimodal-live-provider-canary.json"
DEFAULT_QUALITY_SCORECARD_REPORT = ".e2e-artifacts/memory-quality-scorecard.json"

REQUIRED_FRONTEND_FLOWS = frozenset(
    {
        "memory_scope_management",
        "capture_link_approve",
        "context_link_reject",
        "attachment_capture_extraction",
        "manual_context_link_override",
        "anchor_lifecycle_cleanup",
    }
)
REQUIRED_FRONTEND_ATTACHMENT_MODALITIES = frozenset({"text", "image", "audio", "video"})
REQUIRED_FRONTEND_CONTEXT_REVIEW_ACTIONS = frozenset(
    {"approve", "reject", "manual_link"}
)
REQUIRED_FRONTEND_ANCHOR_LIFECYCLE_CHECKS = frozenset(
    {"create", "update", "split_alias", "merge_duplicate", "cleanup"}
)
REQUIRED_DOCKER_COMPONENTS = frozenset(
    {
        "docker_daemon",
        "docker_disk_preflight",
        "compose_config",
        "compose_stack",
        "container_dependencies",
        "health",
        "capabilities",
        "extraction_flow",
        "cleanup",
    }
)
REQUIRED_DOCKER_FILES = frozenset(
    {
        "docker-proof.txt",
        "docker-proof.pdf",
        "docker-proof.png",
        "docker-proof.wav",
        "docker-proof.mp4",
    }
)
REQUIRED_OPENAI_AUDIO_SUFFIXES = frozenset(
    {".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".ogg", ".wav", ".webm"}
)
REQUIRED_OPENAI_VISION_SUFFIXES = frozenset({".gif", ".jpeg", ".jpg", ".png", ".webp"})
REQUIRED_OPENAI_VISION_BASE_DETAIL_LEVELS = frozenset({"low", "high", "auto"})
ALLOWED_OPENAI_VISION_DETAIL_LEVELS = frozenset({"low", "high", "original", "auto"})
CORE_BOUNDARY_RELATIVE_PATHS = (Path("packages/infinity_context_core/infinity_context_core"),)
FORBIDDEN_CORE_IMPORT_MARKERS = (
    "import fastapi",
    "from fastapi",
    "import sqlalchemy",
    "from sqlalchemy",
    "import qdrant",
    "from qdrant",
    "import qdrant_client",
    "from qdrant_client",
    "import graphiti",
    "from graphiti",
    "import openai",
    "from openai",
    "infinity_context_server",
    "infinity_context_adapters",
)
SECRET_MARKERS = ("sk-", "Bearer ")
PROVIDER_REQUIREMENT_CHECKS = {
    "vision_real_provider": "live_provider_proof_matrix_vision_real_provider",
    "vision_response_evidence": "live_provider_proof_matrix_vision_response_evidence",
    "audio_transcription_real_provider": (
        "live_provider_proof_matrix_audio_transcription_real_provider"
    ),
    "transcription_response_artifact": (
        "live_provider_proof_matrix_transcription_response_artifact"
    ),
    "audio_transcription_format_matrix": (
        "live_provider_proof_matrix_audio_transcription_format_matrix"
    ),
    "invalid_key_live_probe": "live_provider_proof_matrix_invalid_key_live_probe",
    "vision_fixture_contract": "live_provider_proof_matrix_vision_fixture_contract",
    "audio_fixture_contract": "live_provider_proof_matrix_audio_fixture_contract",
    "audio_fixture_format_coverage": "live_provider_proof_matrix_audio_fixture_format_coverage",
    "transcription_request_contract": (
        "live_provider_proof_matrix_transcription_request_contract"
    ),
    "invalid_key_classification": "live_provider_proof_matrix_invalid_key_classification",
    "rate_limit_classification": "live_provider_proof_matrix_rate_limit_classification",
    "timeout_classification": "live_provider_proof_matrix_timeout_classification",
    "no_secret_leak_guard": "live_provider_proof_matrix_no_secret_leak_guard",
    "report_safety_contract": "live_provider_proof_matrix_report_safety_contract",
}
REQUIRED_MEMORY_QUALITY_CAPABILITIES = frozenset(
    {
        "canonical_recall_precision",
        "retrieval_context_memory_layer",
        "longitudinal_memory",
        "auto_memory_admission",
        "semantic_linking",
        "dedup_merge_conflict_resolution",
        "multimodal_evidence_retrieval",
        "graph_native_recall",
        "scope_and_safety",
        "prompt_context_contract",
    }
)
MIN_MEMORY_QUALITY_SCORE_10 = 9.0


@dataclass(frozen=True)
class GoalAuditResult:
    ok: bool
    checks: dict[str, bool]
    failures: tuple[str, ...]
    reports: dict[str, object]
    git: dict[str, object]
    blocked_requirements: tuple[dict[str, object], ...] = ()
    not_evaluable_checks: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "suite": SUITE,
            "ok": self.ok,
            "checks": dict(self.checks),
            "failures": list(self.failures),
            "blocked_requirements": list(self.blocked_requirements),
            "not_evaluable_checks": list(self.not_evaluable_checks),
            "reports": dict(self.reports),
            "git": dict(self.git),
            "secrets_redacted": True,
        }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_goal_audit(
        root=Path(args.root),
        frontend_report=Path(args.frontend_report),
        docker_report=Path(args.docker_report),
        provider_report=Path(args.provider_report),
        quality_scorecard_report=Path(args.quality_scorecard_report),
        require_clean_git=not args.allow_dirty,
    )
    payload = result.as_dict()
    if args.report_out:
        report_path = Path(args.report_out)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if result.ok else 1


def run_goal_audit(
    *,
    root: Path,
    frontend_report: Path = Path(DEFAULT_FRONTEND_REPORT),
    docker_report: Path = Path(DEFAULT_DOCKER_REPORT),
    provider_report: Path = Path(DEFAULT_PROVIDER_REPORT),
    quality_scorecard_report: Path = Path(DEFAULT_QUALITY_SCORECARD_REPORT),
    require_clean_git: bool = True,
    git: Mapping[str, object] | None = None,
) -> GoalAuditResult:
    root = root.resolve()
    frontend = _load_report(root / frontend_report)
    docker = _load_report(root / docker_report)
    provider = _load_report(root / provider_report)
    quality_scorecard = _load_report(root / quality_scorecard_report)
    git = dict(git) if git is not None else _git_info(root)

    checks: dict[str, bool] = {}
    failures: list[str] = []

    _check(
        checks,
        failures,
        "git_commit_present",
        bool(git.get("commit")),
        "Current git commit could not be resolved",
    )
    _check(
        checks,
        failures,
        "git_clean",
        (not bool(git.get("dirty"))) if require_clean_git else True,
        "Working tree must be clean for final multimodal production proof",
    )

    core_boundary_ok = _core_boundaries_ok(root)
    _check(
        checks,
        failures,
        "core_boundary_clean",
        core_boundary_ok,
        "infinity_context_core imports forbidden server/adapters/provider dependencies",
    )

    current_commit = str(git.get("commit") or "")
    _audit_frontend_report(
        frontend,
        current_commit=current_commit,
        checks=checks,
        failures=failures,
    )
    _audit_docker_report(docker, current_commit=current_commit, checks=checks, failures=failures)
    _audit_provider_report(
        provider,
        current_commit=current_commit,
        checks=checks,
        failures=failures,
    )
    _audit_quality_scorecard_report(
        quality_scorecard,
        checks=checks,
        failures=failures,
    )

    serialized_reports = json.dumps(
        {
            "frontend": frontend,
            "docker": docker,
            "provider": provider,
            "quality_scorecard": quality_scorecard,
        },
        sort_keys=True,
    )
    _check(
        checks,
        failures,
        "proof_reports_do_not_leak_secrets",
        not any(marker in serialized_reports for marker in SECRET_MARKERS),
        "Proof reports contain a provider credential marker or secret-like value",
    )

    reports = {
        "frontend": _report_summary(frontend),
        "docker": _report_summary(docker),
        "provider": _report_summary(provider),
        "quality_scorecard": _report_summary(quality_scorecard),
    }
    blocked_requirements = _blocked_requirements(
        frontend=frontend,
        docker=docker,
        provider=provider,
    )
    return GoalAuditResult(
        ok=all(checks.values()),
        checks=checks,
        failures=tuple(failures),
        reports=reports,
        git=git,
        blocked_requirements=blocked_requirements,
        not_evaluable_checks=_not_evaluable_checks(blocked_requirements),
    )


def _audit_frontend_report(
    report: Mapping[str, object] | None,
    *,
    current_commit: str,
    checks: dict[str, bool],
    failures: list[str],
) -> None:
    _check(
        checks,
        failures,
        "frontend_marionette_report_present",
        report is not None,
        f"Missing frontend Marionette report at {DEFAULT_FRONTEND_REPORT}",
    )
    if report is None:
        return
    flow = report.get("flow_coverage") if isinstance(report.get("flow_coverage"), dict) else {}
    completed = set(_string_list(flow.get("completed_flows")))
    attachment_modalities = _frontend_attachment_modalities(flow)
    attachment_parser_modalities = _frontend_attachment_parser_modalities(flow)
    review_actions = _frontend_review_actions(flow)
    anchor_checks = set(_string_list(flow.get("anchor_lifecycle_checks")))
    git = report.get("git") if isinstance(report.get("git"), dict) else {}
    components = report.get("components") if isinstance(report.get("components"), dict) else {}
    _check(
        checks,
        failures,
        "frontend_marionette_passed",
        report.get("ok") is True,
        "Frontend Marionette local E2E did not pass"
        + _failure_suffix(report, components, preferred_component="flutter_marionette"),
    )
    _check(
        checks,
        failures,
        "frontend_marionette_clean_commit",
        git.get("dirty") is False and bool(git.get("commit")),
        "Frontend Marionette proof must be tied to a clean git commit",
    )
    _check(
        checks,
        failures,
        "frontend_marionette_current_commit",
        bool(current_commit) and git.get("commit") == current_commit,
        "Frontend Marionette proof must be generated for the current git commit",
    )
    _check(
        checks,
        failures,
        "frontend_marionette_flows_complete",
        flow.get("status") == "succeeded" and REQUIRED_FRONTEND_FLOWS.issubset(completed),
        "Frontend Marionette proof did not complete every required review/capture flow",
    )
    _check(
        checks,
        failures,
        "frontend_marionette_attachment_modalities_complete",
        REQUIRED_FRONTEND_ATTACHMENT_MODALITIES.issubset(attachment_modalities),
        "Frontend Marionette proof did not verify text/image/audio/video attachment extraction",
    )
    _check(
        checks,
        failures,
        "frontend_marionette_attachment_artifacts_verified",
        REQUIRED_FRONTEND_ATTACHMENT_MODALITIES.issubset(attachment_parser_modalities),
        "Frontend Marionette proof did not verify parser, document, and artifacts "
        "for every attachment modality",
    )
    _check(
        checks,
        failures,
        "frontend_marionette_context_review_actions_complete",
        REQUIRED_FRONTEND_CONTEXT_REVIEW_ACTIONS.issubset(review_actions),
        "Frontend Marionette proof did not verify approve/reject/manual-link review actions",
    )
    _check(
        checks,
        failures,
        "frontend_marionette_anchor_lifecycle_complete",
        REQUIRED_FRONTEND_ANCHOR_LIFECYCLE_CHECKS.issubset(anchor_checks),
        "Frontend Marionette proof did not verify create/update/split/merge/cleanup "
        "anchor lifecycle",
    )
    _check(
        checks,
        failures,
        "frontend_marionette_components_succeeded",
        _components_succeeded(
            components,
            {"server", "worker", "flutter_marionette", "flutter_runtime_log"},
        ),
        "Frontend Marionette server, worker, Flutter, or runtime log component failed",
    )


def _frontend_attachment_modalities(flow: Mapping[str, object]) -> set[str]:
    attachments = flow.get("attachment_modalities")
    if not isinstance(attachments, list):
        return set()
    modalities: set[str] = set()
    for item in attachments:
        if not isinstance(item, dict):
            continue
        modality = item.get("modality")
        if isinstance(modality, str) and modality:
            modalities.add(modality)
    return modalities


def _frontend_attachment_parser_modalities(flow: Mapping[str, object]) -> set[str]:
    attachments = flow.get("attachment_modalities")
    if not isinstance(attachments, list):
        return set()
    modalities: set[str] = set()
    for item in attachments:
        if not isinstance(item, dict):
            continue
        modality = item.get("modality")
        parser_name = item.get("parser_name")
        artifact_types = item.get("artifact_types")
        document_created = item.get("document_created")
        if (
            isinstance(modality, str)
            and modality
            and isinstance(parser_name, str)
            and bool(parser_name)
            and isinstance(artifact_types, list)
            and bool(artifact_types)
            and document_created is True
        ):
            modalities.add(modality)
    return modalities


def _frontend_review_actions(flow: Mapping[str, object]) -> set[str]:
    raw_actions = flow.get("context_link_review_actions")
    if not isinstance(raw_actions, dict):
        return set()
    actions: set[str] = set()
    for raw_action, raw_count in raw_actions.items():
        if isinstance(raw_action, str) and isinstance(raw_count, int) and raw_count > 0:
            actions.add(raw_action)
    return actions


def _audit_docker_report(
    report: Mapping[str, object] | None,
    *,
    current_commit: str,
    checks: dict[str, bool],
    failures: list[str],
) -> None:
    _check(
        checks,
        failures,
        "docker_live_report_present",
        report is not None,
        f"Missing Docker live proof report at {DEFAULT_DOCKER_REPORT}",
    )
    if report is None:
        return
    components = report.get("components") if isinstance(report.get("components"), dict) else {}
    capabilities = (
        components.get("capabilities") if isinstance(components.get("capabilities"), dict) else {}
    )
    extraction = components.get("extraction_flow") if isinstance(components, dict) else {}
    raw_cases = extraction.get("cases") if isinstance(extraction, dict) else None
    cases = raw_cases if isinstance(raw_cases, list) else []
    filenames = {str(item.get("filename")) for item in cases if isinstance(item, dict)}
    git = report.get("git") if isinstance(report.get("git"), dict) else {}
    provider_contract = (
        capabilities.get("provider_contract")
        if isinstance(capabilities.get("provider_contract"), dict)
        else {}
    )
    file_type_detection = (
        capabilities.get("file_type_detection")
        if isinstance(capabilities.get("file_type_detection"), dict)
        else {}
    )
    resource_policy = (
        capabilities.get("resource_policy")
        if isinstance(capabilities.get("resource_policy"), dict)
        else {}
    )
    resource_limits = (
        capabilities.get("limits") if isinstance(capabilities.get("limits"), dict) else {}
    )
    extraction_policy = (
        capabilities.get("policy") if isinstance(capabilities.get("policy"), dict) else {}
    )
    storage_readiness = (
        capabilities.get("storage_readiness")
        if isinstance(capabilities.get("storage_readiness"), dict)
        else {}
    )
    contract_names = set(_string_list(capabilities.get("contract_names")))
    _check(
        checks,
        failures,
        "docker_live_proof_passed",
        report.get("ok") is True,
        "Docker multimodal live proof did not pass"
        + _failure_suffix(report, components, preferred_component="docker_daemon"),
    )
    _check(
        checks,
        failures,
        "docker_live_clean_commit",
        git.get("dirty") is False and bool(git.get("commit")),
        "Docker live proof must be tied to a clean git commit",
    )
    _check(
        checks,
        failures,
        "docker_live_current_commit",
        bool(current_commit) and git.get("commit") == current_commit,
        "Docker live proof must be generated for the current git commit",
    )
    _check(
        checks,
        failures,
        "docker_live_components_succeeded",
        _components_succeeded(components, REQUIRED_DOCKER_COMPONENTS),
        "Docker live proof did not succeed for every required runtime component",
    )
    _check(
        checks,
        failures,
        "docker_live_capabilities_provider_contract_present",
        "provider_contract" in contract_names and bool(provider_contract),
        "Docker live proof did not prove the provider capability contract",
    )
    _check(
        checks,
        failures,
        "docker_live_capabilities_provider_contract_docs_aligned",
        provider_contract.get("ok") is True
        and set(_string_list(provider_contract.get("transcription_supported_file_types")))
        == REQUIRED_OPENAI_AUDIO_SUFFIXES
        and provider_contract.get("transcription_max_provider_upload_bytes") == 25 * 1024 * 1024
        and set(_string_list(provider_contract.get("vision_supported_file_types")))
        == REQUIRED_OPENAI_VISION_SUFFIXES,
        "Docker live proof provider contract is not aligned with current media providers",
    )
    _check(
        checks,
        failures,
        "docker_live_capabilities_audio_upload_limit_present",
        provider_contract.get("transcription_max_provider_upload_bytes") == 25 * 1024 * 1024
        and _positive_int(provider_contract.get("transcription_effective_max_upload_bytes"))
        is not None,
        "Docker live proof provider contract is missing OpenAI audio upload limits",
    )
    docker_vision_detail_levels = set(_string_list(provider_contract.get("vision_detail_levels")))
    _check(
        checks,
        failures,
        "docker_live_capabilities_vision_detail_contract_docs_aligned",
        REQUIRED_OPENAI_VISION_BASE_DETAIL_LEVELS.issubset(docker_vision_detail_levels)
        and docker_vision_detail_levels.issubset(ALLOWED_OPENAI_VISION_DETAIL_LEVELS),
        "Docker live proof provider contract is missing current OpenAI vision detail levels",
    )
    _check(
        checks,
        failures,
        "docker_live_capabilities_vision_binary_limit_present",
        _positive_int(provider_contract.get("vision_max_provider_binary_upload_bytes")) is not None,
        "Docker live proof provider contract is missing OpenAI vision binary upload limit",
    )
    _check(
        checks,
        failures,
        "docker_live_capabilities_vision_payload_limits_present",
        _positive_int(provider_contract.get("vision_max_provider_payload_bytes")) is not None
        and _positive_int(provider_contract.get("vision_max_images_per_request")) is not None
        and _positive_int(provider_contract.get("vision_effective_max_upload_bytes")) is not None,
        "Docker live proof provider contract is missing OpenAI vision payload limits",
    )
    _check(
        checks,
        failures,
        "docker_live_capabilities_file_type_detection_present",
        "file_type_detection" in contract_names and file_type_detection.get("ok") is True,
        "Docker live proof did not prove the file type detection contract",
    )
    _check(
        checks,
        failures,
        "docker_live_capabilities_resource_policy_present",
        "resource_policy" in contract_names and resource_policy.get("ok") is True,
        "Docker live proof did not prove the extraction resource policy contract",
    )
    _check(
        checks,
        failures,
        "docker_live_capabilities_upload_security_fields_present",
        extraction_policy.get("source_text_policy") == "untrusted_evidence"
        and extraction_policy.get("provider_payloads_bounded") is True
        and extraction_policy.get("sensitive_data_in_diagnostics") is False
        and file_type_detection.get("declared_content_type_trusted") is False
        and file_type_detection.get("filename_extension_trusted") is False
        and file_type_detection.get("empty_upload_policy") == "reject_at_upload"
        and file_type_detection.get("upload_body_stream_limited") is True
        and resource_policy.get("revalidates_upload_policy_after_blob_read") is True,
        "Docker live proof is missing upload security/trust-boundary fields",
    )
    _check(
        checks,
        failures,
        "docker_live_capabilities_archive_limits_present",
        file_type_detection.get("archive_policy_complete") is True
        and resource_policy.get("archive_rejection_policy_complete") is True
        and resource_policy.get("hard_caps_present") is True
        and _positive_int(resource_limits.get("max_archive_entries")) is not None
        and _positive_int(resource_limits.get("max_archive_uncompressed_bytes")) is not None
        and _positive_float(resource_limits.get("max_archive_compression_ratio")) is not None,
        "Docker live proof is missing archive bomb/resource limits",
    )
    _check(
        checks,
        failures,
        "docker_live_capabilities_image_pixel_limit_present",
        file_type_detection.get("image_policy_complete") is True
        and _positive_int(resource_limits.get("max_image_pixels")) is not None,
        "Docker live proof is missing image pixel bomb limits",
    )
    _check(
        checks,
        failures,
        "docker_live_capabilities_media_duration_limit_present",
        _positive_float(resource_limits.get("max_media_seconds")) is not None,
        "Docker live proof is missing media duration limits",
    )
    _check(
        checks,
        failures,
        "docker_live_capabilities_parser_timeout_present",
        _positive_float(resource_limits.get("parser_timeout_seconds")) is not None
        and _positive_float(resource_limits.get("subprocess_timeout_seconds")) is not None
        and _positive_float(resource_limits.get("provider_timeout_seconds")) is not None,
        "Docker live proof is missing parser/subprocess/provider timeout limits",
    )
    _check(
        checks,
        failures,
        "docker_live_capabilities_manifest_evidence_contracts_present",
        capabilities.get("manifest_contract_present") is True
        and capabilities.get("evidence_contract_present") is True,
        "Docker live proof is missing manifest/evidence capability contracts",
    )
    _check(
        checks,
        failures,
        "docker_live_capabilities_storage_readiness_contract_present",
        storage_readiness.get("ok") is True
        and storage_readiness.get("schema_version")
        == "asset-storage-deployment-readiness-v2"
        and storage_readiness.get("self_host_ready") is True
        and storage_readiness.get("schema_management_mode")
        in {"auto_create", "external_migration_runner"}
        and storage_readiness.get("auto_create_schema_allowed_in_server_profile") is False
        and isinstance(storage_readiness.get("migration_runner_required"), bool)
        and storage_readiness.get("migration_runner_service") == "infinity_context_migrate"
        and storage_readiness.get("migration_strategy") == "external_forward_migrations"
        and storage_readiness.get("recommended_hosted_backend") == "s3"
        and storage_readiness.get("blob_identity") == "sha256"
        and storage_readiness.get("duplicate_detection") == "exact_sha256"
        and storage_readiness.get("scope_storage_quota_enforced") is True
        and _positive_int(storage_readiness.get("scope_storage_quota_bytes")) is not None
        and storage_readiness.get("storage_cleanup_supported") is True
        and storage_readiness.get("safe_diagnostics") is True,
        "Docker live proof is missing asset storage deployment readiness contract",
    )
    _check(
        checks,
        failures,
        "docker_live_extraction_cases_complete",
        REQUIRED_DOCKER_FILES.issubset(filenames),
        "Docker live proof did not extract every required multimodal file type",
    )


def _audit_provider_report(
    report: Mapping[str, object] | None,
    *,
    current_commit: str,
    checks: dict[str, bool],
    failures: list[str],
) -> None:
    _check(
        checks,
        failures,
        "live_provider_report_present",
        report is not None,
        f"Missing live provider canary report at {DEFAULT_PROVIDER_REPORT}",
    )
    if report is None:
        return
    components = report.get("components") if isinstance(report.get("components"), dict) else {}
    git = report.get("git") if isinstance(report.get("git"), dict) else {}
    provider_contract = (
        report.get("provider_contract") if isinstance(report.get("provider_contract"), dict) else {}
    )
    failure_policy_contract = (
        report.get("failure_policy_contract")
        if isinstance(report.get("failure_policy_contract"), dict)
        else {}
    )
    proof_matrix = (
        report.get("proof_matrix") if isinstance(report.get("proof_matrix"), dict) else {}
    )
    _check(
        checks,
        failures,
        "live_provider_proof_passed",
        report.get("ok") is True,
        "Live provider canary did not pass"
        + _failure_suffix(report, components, preferred_component="provider_key"),
    )
    _check(
        checks,
        failures,
        "live_provider_clean_commit",
        git.get("dirty") is False and bool(git.get("commit")),
        "Live provider proof must be tied to a clean git commit",
    )
    _check(
        checks,
        failures,
        "live_provider_current_commit",
        bool(current_commit) and git.get("commit") == current_commit,
        "Live provider proof must be generated for the current git commit",
    )
    _check(
        checks,
        failures,
        "live_provider_key_present",
        report.get("provider_key_present") is True,
        "Live provider proof needs MEMORY_OPENAI_API_KEY or OPENAI_API_KEY",
    )
    _check(
        checks,
        failures,
        "live_provider_components_succeeded",
        _components_succeeded(components, {"vision", "transcription"}),
        "Live provider vision and transcription checks must both succeed",
    )
    _audit_provider_contract(provider_contract, checks=checks, failures=failures)
    _audit_provider_failure_policy(
        failure_policy_contract,
        checks=checks,
        failures=failures,
    )
    _audit_provider_proof_matrix(
        proof_matrix,
        checks=checks,
        failures=failures,
    )


def _audit_provider_contract(
    contract: Mapping[str, object],
    *,
    checks: dict[str, bool],
    failures: list[str],
) -> None:
    transcription = (
        contract.get("transcription") if isinstance(contract.get("transcription"), dict) else {}
    )
    vision = contract.get("vision") if isinstance(contract.get("vision"), dict) else {}
    audio_suffixes = set(_string_list(transcription.get("supported_file_types")))
    required_live_audio_suffixes = set(_string_list(transcription.get("required_live_file_types")))
    vision_suffixes = set(_string_list(vision.get("supported_file_types")))
    vision_detail_levels = set(_string_list(vision.get("detail_levels")))
    _check(
        checks,
        failures,
        "live_provider_contract_present",
        bool(contract),
        "Live provider proof must include a provider capability contract",
    )
    _check(
        checks,
        failures,
        "live_provider_transcription_contract_docs_aligned",
        transcription.get("endpoint") == "/v1/audio/transcriptions"
        and transcription.get("max_upload_bytes") == 25 * 1024 * 1024
        and audio_suffixes == REQUIRED_OPENAI_AUDIO_SUFFIXES,
        "Live provider transcription contract is missing current OpenAI file limits/types",
    )
    _check(
        checks,
        failures,
        "live_provider_vision_contract_docs_aligned",
        vision.get("endpoint_family") == "responses"
        and vision_suffixes == REQUIRED_OPENAI_VISION_SUFFIXES,
        "Live provider vision contract is missing current OpenAI file types",
    )
    _check(
        checks,
        failures,
        "live_provider_vision_detail_contract_docs_aligned",
        REQUIRED_OPENAI_VISION_BASE_DETAIL_LEVELS.issubset(vision_detail_levels)
        and vision_detail_levels.issubset(ALLOWED_OPENAI_VISION_DETAIL_LEVELS),
        "Live provider vision contract is missing current OpenAI vision detail levels",
    )
    _check(
        checks,
        failures,
        "live_provider_vision_binary_limit_present",
        _positive_int(vision.get("max_provider_binary_upload_bytes")) is not None,
        "Live provider vision contract is missing OpenAI vision binary upload limit",
    )
    _check(
        checks,
        failures,
        "live_provider_contract_includes_current_audio_suffixes",
        REQUIRED_OPENAI_AUDIO_SUFFIXES.issubset(audio_suffixes),
        "Live provider transcription contract is missing current OpenAI audio suffixes",
    )
    _check(
        checks,
        failures,
        "live_provider_contract_requires_wav_mp3_proof",
        {".wav", ".mp3"}.issubset(required_live_audio_suffixes),
        "Live provider transcription contract must require wav and mp3 proof",
    )


def _audit_provider_failure_policy(
    contract: Mapping[str, object],
    *,
    checks: dict[str, bool],
    failures: list[str],
) -> None:
    expected = {
        "provider_credential_missing": (False, "configure_provider_credential"),
        "invalid_api_key": (False, "replace_provider_credential"),
        "quota_exceeded": (False, "check_provider_billing"),
        "rate_limited": (True, "retry_later"),
        "timeout": (True, "retry_later"),
    }
    _check(
        checks,
        failures,
        "live_provider_failure_policy_contract_present",
        bool(contract),
        "Live provider proof must include failure policy classification contract",
    )
    for reason, (retryable, action) in expected.items():
        case = contract.get(reason) if isinstance(contract.get(reason), dict) else {}
        _check(
            checks,
            failures,
            f"live_provider_failure_policy_{reason}",
            case.get("reason") is not None
            and case.get("user_retryable") is retryable
            and case.get("operator_action") == action,
            f"Live provider failure policy for {reason} is missing or wrong",
        )


def _audit_provider_proof_matrix(
    matrix: Mapping[str, object],
    *,
    checks: dict[str, bool],
    failures: list[str],
) -> None:
    requirements = (
        matrix.get("requirements") if isinstance(matrix.get("requirements"), dict) else {}
    )
    _check(
        checks,
        failures,
        "live_provider_proof_matrix_present",
        matrix.get("schema_version") == "multimodal-provider-proof-matrix-v1"
        and bool(requirements),
        "Live provider proof must include the multimodal provider proof matrix",
    )
    expected = {
        "vision_real_provider": "succeeded",
        "vision_response_evidence": "succeeded",
        "audio_transcription_real_provider": "succeeded",
        "transcription_response_artifact": "succeeded",
        "audio_transcription_format_matrix": "succeeded",
        "invalid_key_live_probe": "succeeded",
        "vision_fixture_contract": "contract_covered",
        "audio_fixture_contract": "contract_covered",
        "audio_fixture_format_coverage": "contract_covered",
        "transcription_request_contract": "contract_covered",
        "invalid_key_classification": "contract_covered",
        "rate_limit_classification": "contract_covered",
        "timeout_classification": "contract_covered",
        "no_secret_leak_guard": "contract_covered",
        "report_safety_contract": "contract_covered",
    }
    for name, status in expected.items():
        case = requirements.get(name) if isinstance(requirements.get(name), dict) else {}
        _check(
            checks,
            failures,
            f"live_provider_proof_matrix_{name}",
            case.get("status") == status and case.get("ok") is True,
            f"Live provider proof matrix requirement {name} is missing or not proven",
        )
    invalid_key_probe = (
        requirements.get("invalid_key_live_probe")
        if isinstance(requirements.get("invalid_key_live_probe"), dict)
        else {}
    )
    observed_reason = invalid_key_probe.get("observed_reason")
    observed_reasons = (
        invalid_key_probe.get("observed_reasons")
        if isinstance(invalid_key_probe.get("observed_reasons"), dict)
        else {}
    )
    provider_reasons_ok = all(
        isinstance(observed_reasons.get(provider), str)
        and "invalid_api_key" in str(observed_reasons[provider])
        for provider in ("vision", "transcription")
    )
    _check(
        checks,
        failures,
        "live_provider_proof_matrix_invalid_key_live_probe_observed",
        invalid_key_probe.get("proof") == "live_invalid_credential_call"
        and invalid_key_probe.get("requires_provider_key") is False
        and isinstance(observed_reason, str)
        and "invalid_api_key" in observed_reason,
        "Live provider proof matrix invalid-key probe did not prove invalid_api_key classification",
    )
    _check(
        checks,
        failures,
        "live_provider_proof_matrix_invalid_key_probe_covers_vision_and_transcription",
        provider_reasons_ok,
        "Live provider invalid-key probe must cover both vision and transcription endpoints",
    )


def _audit_quality_scorecard_report(
    report: Mapping[str, object] | None,
    *,
    checks: dict[str, bool],
    failures: list[str],
) -> None:
    _check(
        checks,
        failures,
        "memory_quality_scorecard_report_present",
        report is not None,
        f"Missing memory quality scorecard report at {DEFAULT_QUALITY_SCORECARD_REPORT}",
    )
    if report is None:
        return

    score = report.get("score") if isinstance(report.get("score"), dict) else {}
    gates = report.get("gates") if isinstance(report.get("gates"), dict) else {}
    capabilities = (
        report.get("capabilities") if isinstance(report.get("capabilities"), dict) else {}
    )
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    _check(
        checks,
        failures,
        "memory_quality_scorecard_suite_valid",
        report.get("suite") == "memory-quality-scorecard",
        "Memory quality scorecard report has an unexpected suite name",
    )
    _check(
        checks,
        failures,
        "memory_quality_scorecard_passed",
        report.get("ok") is True and report.get("status") == "ok",
        "Memory quality scorecard did not pass",
    )
    _check(
        checks,
        failures,
        "memory_quality_scorecard_maturity_score",
        _positive_float(score.get("maturity_score_10")) is not None
        and float(score["maturity_score_10"]) >= MIN_MEMORY_QUALITY_SCORE_10,
        "Memory quality scorecard maturity score is below production threshold",
    )
    for gate_name in (
        "required_suites_present",
        "all_suites_ok",
        "all_capabilities_ok",
        "maturity_score_min",
    ):
        _check(
            checks,
            failures,
            f"memory_quality_scorecard_gate_{gate_name}",
            gates.get(gate_name) is True,
            f"Memory quality scorecard gate {gate_name} failed",
        )

    present_capabilities = {
        str(name)
        for name, value in capabilities.items()
        if isinstance(name, str) and isinstance(value, dict)
    }
    _check(
        checks,
        failures,
        "memory_quality_scorecard_capabilities_complete",
        REQUIRED_MEMORY_QUALITY_CAPABILITIES.issubset(present_capabilities),
        "Memory quality scorecard is missing required retrieval/linking/safety capabilities",
    )
    for capability_name in sorted(REQUIRED_MEMORY_QUALITY_CAPABILITIES):
        capability = (
            capabilities.get(capability_name)
            if isinstance(capabilities.get(capability_name), dict)
            else {}
        )
        _check(
            checks,
            failures,
            f"memory_quality_scorecard_capability_{capability_name}",
            capability.get("ok") is True,
            f"Memory quality scorecard capability {capability_name} failed",
        )

    _check(
        checks,
        failures,
        "memory_quality_scorecard_no_safety_leaks",
        _non_negative_int(metrics.get("safety_leak_count")) == 0,
        "Memory quality scorecard reported safety leaks",
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(_repository_root()))
    parser.add_argument("--frontend-report", default=DEFAULT_FRONTEND_REPORT)
    parser.add_argument("--docker-report", default=DEFAULT_DOCKER_REPORT)
    parser.add_argument("--provider-report", default=DEFAULT_PROVIDER_REPORT)
    parser.add_argument("--quality-scorecard-report", default=DEFAULT_QUALITY_SCORECARD_REPORT)
    parser.add_argument(
        "--report-out",
        default=os.environ.get(
            "MEMORY_MULTIMODAL_PRODUCTION_GOAL_AUDIT_REPORT_OUT",
            ".e2e-artifacts/multimodal-production-goal-audit.json",
        ),
    )
    parser.add_argument("--allow-dirty", action="store_true")
    return parser.parse_args(argv)


def _load_report(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _core_boundary_ok(path: Path) -> bool:
    if not path.exists():
        return False
    for file_path in path.rglob("*.py"):
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            return False
        lowered = content.lower()
        if any(marker in lowered for marker in FORBIDDEN_CORE_IMPORT_MARKERS):
            return False
    return True


def _core_boundaries_ok(root: Path) -> bool:
    existing = [root / path for path in CORE_BOUNDARY_RELATIVE_PATHS if (root / path).exists()]
    if not existing:
        return False
    return all(_core_boundary_ok(path) for path in existing)


def _components_succeeded(
    components: Mapping[str, object],
    required: set[str] | frozenset[str],
) -> bool:
    for name in required:
        component = components.get(name)
        if not isinstance(component, dict) or component.get("status") != "succeeded":
            return False
    return True


def _check(
    checks: dict[str, bool],
    failures: list[str],
    name: str,
    ok: bool,
    failure: str,
) -> None:
    checks[name] = bool(ok)
    if not ok:
        failures.append(failure)


def _failure_suffix(
    report: Mapping[str, object],
    components: Mapping[str, object],
    *,
    preferred_component: str,
) -> str:
    payload = report.get("failure") if isinstance(report.get("failure"), dict) else None
    if payload is None:
        component = components.get(preferred_component)
        payload = component if isinstance(component, dict) else None
    if payload is None:
        return ""

    reason = payload.get("reason")
    action = payload.get("operator_action")
    message = payload.get("message")
    parts = [
        str(value).strip()
        for value in (reason, action, message)
        if isinstance(value, str) and value.strip()
    ]
    if not parts:
        return ""
    return ": " + "; ".join(_safe_text(part, limit=96) or "" for part in parts[:3])


def _blocked_requirements(
    *,
    frontend: Mapping[str, object] | None,
    docker: Mapping[str, object] | None,
    provider: Mapping[str, object] | None,
) -> tuple[dict[str, object], ...]:
    blocked: list[dict[str, object]] = []
    frontend_blocker = _proof_blocker(
        frontend,
        area="frontend_marionette_proof",
        preferred_component="flutter_marionette",
    )
    if frontend_blocker is not None:
        frontend_blocker["downstream_checks"] = [
            "frontend_marionette_passed",
            "frontend_marionette_flows_complete",
            "frontend_marionette_components_succeeded",
        ]
        blocked.append(frontend_blocker)

    docker_blocker = _proof_blocker(
        docker,
        area="docker_live_proof",
        preferred_component="docker_daemon",
    )
    if docker_blocker is not None:
        docker_blocker["downstream_checks"] = [
            "docker_live_capabilities_provider_contract_present",
            "docker_live_capabilities_provider_contract_docs_aligned",
            "docker_live_capabilities_audio_upload_limit_present",
            "docker_live_capabilities_vision_detail_contract_docs_aligned",
            "docker_live_capabilities_vision_binary_limit_present",
            "docker_live_capabilities_vision_payload_limits_present",
            "docker_live_capabilities_file_type_detection_present",
            "docker_live_capabilities_resource_policy_present",
            "docker_live_capabilities_upload_security_fields_present",
            "docker_live_capabilities_archive_limits_present",
            "docker_live_capabilities_image_pixel_limit_present",
            "docker_live_capabilities_media_duration_limit_present",
            "docker_live_capabilities_parser_timeout_present",
            "docker_live_capabilities_manifest_evidence_contracts_present",
            "docker_live_capabilities_storage_readiness_contract_present",
            "docker_live_extraction_cases_complete",
        ]
        blocked.append(docker_blocker)

    provider_blocker = _proof_blocker(
        provider,
        area="live_provider_proof",
        preferred_component="provider_key",
    )
    if provider_blocker is not None:
        provider_blocker["blocking_requirements"] = list(
            _provider_blocking_requirements(provider)
        )
        provider_blocker["downstream_checks"] = list(_provider_downstream_checks(provider))
        blocked.append(provider_blocker)
    return tuple(blocked)


def _proof_blocker(
    report: Mapping[str, object] | None,
    *,
    area: str,
    preferred_component: str,
) -> dict[str, object] | None:
    if not isinstance(report, Mapping) or report.get("ok") is True:
        return None
    components = report.get("components") if isinstance(report.get("components"), dict) else {}
    failure = report.get("failure") if isinstance(report.get("failure"), dict) else None
    component = components.get(preferred_component)
    component = component if isinstance(component, dict) else None
    payload = failure or component
    if not isinstance(payload, Mapping):
        return None

    status = str(payload.get("status") or "")
    degraded = payload.get("degraded") is True or status in {"degraded", "skipped"}
    reason = _safe_text(payload.get("reason"))
    action = _safe_text(payload.get("operator_action"))
    if not degraded and not reason:
        return None

    return {
        "area": area,
        "component": _safe_text(payload.get("component")) or preferred_component,
        "reason": reason,
        "operator_action": action,
        "user_retryable": payload.get("user_retryable") is True,
    }


def _not_evaluable_checks(
    blocked_requirements: tuple[dict[str, object], ...],
) -> tuple[str, ...]:
    checks: list[str] = []
    for blocker in blocked_requirements:
        downstream = blocker.get("downstream_checks")
        if isinstance(downstream, list):
            checks.extend(str(item) for item in downstream)
    return tuple(dict.fromkeys(checks))


def _provider_downstream_checks(
    report: Mapping[str, object] | None,
) -> tuple[str, ...]:
    checks = ["live_provider_components_succeeded"]
    blocking_requirements = _provider_blocking_requirements(report)
    if blocking_requirements:
        for requirement in blocking_requirements:
            mapped = PROVIDER_REQUIREMENT_CHECKS.get(requirement)
            if mapped:
                checks.append(mapped)
    else:
        checks.extend(PROVIDER_REQUIREMENT_CHECKS.values())
    return tuple(dict.fromkeys(checks))


def _provider_blocking_requirements(
    report: Mapping[str, object] | None,
) -> tuple[str, ...]:
    if not isinstance(report, Mapping):
        return ()
    readiness = report.get("readiness")
    if isinstance(readiness, Mapping):
        configured = _string_list(readiness.get("blocking_requirements"))
        if configured:
            return tuple(configured)
    proof_matrix = report.get("proof_matrix")
    requirements = (
        proof_matrix.get("requirements")
        if isinstance(proof_matrix, Mapping)
        and isinstance(proof_matrix.get("requirements"), Mapping)
        else {}
    )
    return tuple(
        str(name)
        for name, requirement in requirements.items()
        if isinstance(name, str)
        and isinstance(requirement, Mapping)
        and requirement.get("ok") is not True
    )


def _report_summary(report: Mapping[str, object] | None) -> dict[str, object]:
    if report is None:
        return {"present": False}
    summary: dict[str, object] = {
        "present": True,
        "suite": _safe_text(report.get("suite")),
        "ok": report.get("ok") is True,
    }
    git = report.get("git")
    if isinstance(git, dict):
        summary["git"] = {
            "short_commit": _safe_text(git.get("short_commit")),
            "dirty": git.get("dirty") is True,
        }
    readiness = report.get("readiness")
    if isinstance(readiness, dict):
        summary["readiness"] = {
            "status": _safe_text(readiness.get("status")),
            "production_ready": readiness.get("production_ready") is True,
            "blocking_requirements": list(
                _string_list(readiness.get("blocking_requirements"))
            ),
        }
    score = report.get("score")
    if isinstance(score, dict):
        summary["score"] = {
            "maturity_score_10": _positive_float(score.get("maturity_score_10")),
            "minimum_maturity_score_10": _positive_float(
                score.get("minimum_maturity_score_10")
            ),
        }
    gates = report.get("gates")
    if isinstance(gates, dict):
        summary["gates"] = {
            "required_suites_present": gates.get("required_suites_present") is True,
            "all_suites_ok": gates.get("all_suites_ok") is True,
            "all_capabilities_ok": gates.get("all_capabilities_ok") is True,
            "maturity_score_min": gates.get("maturity_score_min") is True,
        }
    return summary


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    return None


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _positive_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float) and value > 0:
        return float(value)
    return None


def _safe_text(value: object, *, limit: int = 160) -> str | None:
    if value is None:
        return None
    return str(value)[:limit]


def _git_info(root: Path) -> dict[str, object]:
    commit = _git_output(root, "rev-parse", "HEAD")
    short_commit = _git_output(root, "rev-parse", "--short", "HEAD")
    dirty = _git_output(root, "status", "--short")
    return {
        "commit": commit,
        "short_commit": short_commit,
        "dirty": bool(dirty),
    }


def _git_output(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
