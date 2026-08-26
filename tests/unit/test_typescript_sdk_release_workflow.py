from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github/workflows/typescript-sdk-release.yml"
GENERAL_WORKFLOW = ROOT / ".github/workflows/release.yml"
MANIFEST_CLI = (
    ROOT
    / "packages/infinity_context_ts_sdk/scripts/sdk-release-manifest.mjs"
)
RECEIPT_CLI = (
    ROOT
    / "packages/infinity_context_ts_sdk/scripts/sdk-release-receipt.mjs"
)


def _workflow() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _job(text: str, name: str, next_name: str | None = None) -> str:
    marker = f"  {name}:\n"
    assert text.count(marker) == 1
    body = text.split(marker, maxsplit=1)[1]
    if next_name:
        body = body.split(f"  {next_name}:\n", maxsplit=1)[0]
    return body


def test_workflow_yaml_parses_and_is_exact_tag_manual_only() -> None:
    document = yaml.safe_load(_workflow())
    assert isinstance(document, dict)
    assert "jobs" in document
    event = _workflow().split("permissions: {}", maxsplit=1)[0]
    assert "workflow_dispatch:" in event
    assert "sdk_tag:" in event
    assert "qualification_run_id" not in event
    for forbidden in ("push:", "pull_request:", "workflow_run:", "schedule:"):
        assert forbidden not in event
    assert "^sdk-v[0-9]+\\.[0-9]+\\.[0-9]+$" in _workflow()


def test_permissions_actions_and_environment_are_least_privilege() -> None:
    workflow = _workflow()
    build = _job(workflow, "build", "publish")
    publish = _job(workflow, "publish")
    assert "permissions: {}" in workflow
    assert re.search(r"permissions:\n      contents: read\n", build)
    assert "actions: write" in publish
    assert "contents: write" in publish
    assert "environment:\n      name: sdk-release" in publish
    for forbidden in ("packages: write", "id-token: write", "attestations: write"):
        assert forbidden not in workflow


def test_every_action_is_pinned_to_a_full_commit() -> None:
    uses = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", _workflow(), flags=re.MULTILINE)
    assert uses
    assert all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", use) for use in uses)


def test_preflight_proves_repository_tag_rules_and_immutable_releases() -> None:
    workflow = _workflow()
    assert workflow.count("777genius/infinity-context") >= 2
    assert 'object.type' in workflow
    assert '!= "tag"' in workflow
    assert "rulesets?targets=tag" in workflow
    for rule in ('index("creation")', 'index("update")', 'index("deletion")'):
        assert rule in workflow
    assert "immutable_releases == true" in workflow
    assert "immutable_releases_enabled == true" in workflow
    assert workflow.count("releases?per_page=100") == 2
    assert "refusing to resume" in workflow.lower()
    assert "persist-credentials: false" in workflow


def test_exact_node_pack_once_and_same_tarball_consumer_contract() -> None:
    workflow = _workflow()
    assert workflow.count('node-version: "24.18.0"') == 2
    assert workflow.count("npm pack --json") == 1
    assert (
        'node scripts/check-consumer-install.mjs --artifact '
        '"${{ steps.pack.outputs.artifact_name }}"'
    ) in workflow
    build = _job(workflow, "build", "publish")
    for command in (
        "npm ci",
        "npm run lint",
        "npm run check:architecture",
        "npm run check:retrieval-v2-parity",
        "npm run check:parity",
        "npm run typecheck",
        "npm run test",
        "npm run build",
        "npm run check:exports",
    ):
        assert command in build


def test_manifest_cli_is_flag_only_and_invoked_for_create_and_verify() -> None:
    workflow = _workflow()
    cli_command = (
        "node packages/infinity_context_ts_sdk/scripts/sdk-release-manifest.mjs"
    )
    assert workflow.count(cli_command) == 2
    for flag in (
        "--artifact",
        "--artifact-root",
        "--build-profile",
        "--node-version",
        "--output-root",
        "--package-root",
        "--repository",
        "--repository-root",
        "--tag",
        "--workflow-path",
        "--workflow-run-attempt",
        "--workflow-run-id",
        "--workflow-sha256",
    ):
        assert workflow.count(flag) >= 2
    assert "--output " in workflow
    assert "--manifest " in workflow
    source = MANIFEST_CLI.read_text(encoding="utf-8")
    for forbidden in (
        "service_revision",
        "capability_fingerprint",
        "qualification",
        "discord",
        "corpus",
        "manual-revision",
    ):
        assert forbidden not in source.lower()


def test_transport_and_release_policy_are_exactly_two_assets() -> None:
    workflow = _workflow()
    assert "infinity-context-sdk-release-manifest.json" in workflow
    assert "retrieval-v2-qualification-manifest.json" not in workflow
    assert 'assets=("${SDK_ARTIFACT}" infinity-context-sdk-release-manifest.json)' in workflow
    assert workflow.count("find release-bundle -maxdepth 1 -type f") == 2
    assert "expected exactly one pack result" in workflow
    assert "retention-days: 1" in workflow
    assert "overwrite: false" in workflow
    for forbidden in ("npm publish", "ghcr.io", "registry-url"):
        assert forbidden not in workflow
    assert "--clobber" not in workflow + GENERAL_WORKFLOW.read_text(encoding="utf-8")


def test_publication_is_create_only_verified_before_and_after_publish() -> None:
    publish = _job(_workflow(), "publish")
    assert publish.count("gh release create") == 1
    assert publish.count("gh release edit") == 1
    assert "--draft=false" in publish
    assert "cmp \"release-bundle/${asset}\"" in publish
    assert "gh release verify \"${RELEASE_TAG}\"" in publish
    assert "gh release verify-asset \"${RELEASE_TAG}\"" in publish
    assert "gh release delete" not in publish
    assert "isImmutable" not in publish  # REST's immutable boolean is authoritative here.
    assert "'.immutable'" in publish


def test_post_publication_receipt_is_not_a_release_asset() -> None:
    workflow = _workflow()
    publish = _job(workflow, "publish")
    assert "sdk-release-receipt.mjs" in publish
    assert "release-attestation-verified" in publish
    assert "asset-attestations-verified" in publish
    assert "release-verification-receipt.json" in publish
    release_upload = publish.split("gh release upload", maxsplit=1)[1].split(
        "gh release edit", maxsplit=1
    )[0]
    assert "release-verification-receipt" not in release_upload
    assert RECEIPT_CLI.exists()


def test_meeting_quality_release_gate_is_deleted() -> None:
    assert not (ROOT / "scripts/verify_retrieval_v2_release_qualification.py").exists()
    assert not (
        ROOT / "tests/unit/test_verify_retrieval_v2_release_qualification.py"
    ).exists()
    for forbidden in (
        "3x240",
        "human adjudication",
        "qualification manifest",
        "service revision",
        "capability fingerprint",
    ):
        assert forbidden not in _workflow().lower()
