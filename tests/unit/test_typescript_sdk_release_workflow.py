from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
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


def _steps(job: str) -> list[dict[str, object]]:
    document = yaml.safe_load(_workflow())
    return document["jobs"][job]["steps"]


def _step_run(job: str, name: str) -> str:
    matches = [step for step in _steps(job) if step.get("name") == name]
    assert len(matches) == 1
    run = matches[0].get("run")
    assert isinstance(run, str)
    return run


def _assert_immediate_revalidation(script: str, effect: str) -> None:
    assert script[: script.index(effect)].rstrip().endswith(
        "revalidate_tag_and_ruleset"
    )


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


def test_dispatch_and_executed_workflow_are_bound_to_exact_annotated_tag_commit() -> None:
    workflow = _workflow()
    resolve = _step_run("build", "Resolve protected annotated tag and repository policy")
    source = _step_run(
        "build", "Revalidate clean source, repository, tag, and package identity"
    )
    assert "EXECUTED_REF: ${{ github.ref }}" in workflow
    assert "EXECUTED_WORKFLOW_REF: ${{ github.workflow_ref }}" in workflow
    assert "EXECUTED_WORKFLOW_SHA: ${{ github.workflow_sha }}" in workflow
    assert '"${EXECUTED_REF}" != "refs/tags/${SDK_TAG}"' in resolve
    assert "@refs/tags/${SDK_TAG}" in resolve
    assert '"${EXECUTED_WORKFLOW_SHA}" != "${commit}"' in resolve
    assert workflow.index('ref: ${{ steps.resolve.outputs.commit }}') > workflow.index(
        '"${EXECUTED_WORKFLOW_SHA}" != "${commit}"'
    )
    assert 'test "$(git rev-parse HEAD^{commit})" = "${EXPECTED_COMMIT}"' in source
    assert (
        'sha256sum .github/workflows/typescript-sdk-release.yml' in source
    )
    assert workflow.count(
        "WORKFLOW_SHA256: ${{ steps.source.outputs.workflow_sha256 }}"
    ) == 1
    assert workflow.count(
        "WORKFLOW_SHA256: ${{ needs.build.outputs.workflow_sha256 }}"
    ) == 1

    # Hostile default-branch dispatch or a generic event SHA must not satisfy policy.
    assert "--ref <DEFAULT_BRANCH>" not in (ROOT / "docs/typescript-sdk-release.md").read_text()
    assert "github.sha }}" not in workflow


def test_permissions_actions_and_environment_are_least_privilege() -> None:
    workflow = _workflow()
    build = _job(workflow, "build", "publish")
    publish = _job(workflow, "publish")
    assert "permissions: {}" in workflow
    assert re.search(r"permissions:\n      contents: read\n", build)
    assert "contents: write" in publish
    assert "actions: write" not in workflow
    assert "environment:\n      name: sdk-release" in publish
    for forbidden in ("packages: write", "id-token: write", "attestations: write"):
        assert forbidden not in workflow


def test_every_action_is_pinned_to_a_full_commit() -> None:
    uses = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", _workflow(), flags=re.MULTILINE)
    assert uses
    assert all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", use) for use in uses)


def test_preflight_proves_repository_tag_rules_and_immutable_releases() -> None:
    workflow = _workflow()
    build = _job(workflow, "build", "publish")
    publish = _job(workflow, "publish")
    assert workflow.count("777genius/infinity-context") >= 2
    assert 'object.type' in workflow
    assert '!= "tag"' in workflow
    assert "rulesets?targets=tag" in workflow
    for rule in ('index("creation")', 'index("update")', 'index("deletion")'):
        assert workflow.count(rule) == 2
    endpoint = '"repos/${GITHUB_REPOSITORY}/immutable-releases"'
    assert workflow.count(endpoint) == 1
    assert build.count(endpoint) == 0
    assert publish.count(endpoint) == 1
    assert 'type == "object" and .enabled == true' in publish
    assert "SDK_RELEASE_ADMIN_READ_TOKEN" not in build
    assert workflow.count("${{ secrets.SDK_RELEASE_ADMIN_READ_TOKEN }}") == 1
    assert "immutable_releases == true" not in workflow
    assert "immutable_releases_enabled == true" not in workflow
    assert publish.index(endpoint) < publish.index('gh release create "${RELEASE_TAG}"')
    assert workflow.count("releases?per_page=100") == 2
    assert "refusing to resume" in workflow.lower()
    assert "persist-credentials: false" in workflow


@pytest.mark.parametrize(
    ("token", "response", "exit_code"),
    [
        ("", "enabled", 1),
        ("admin-read", "denied", 1),
        ("admin-read", "malformed", 1),
        ("admin-read", "disabled", 1),
        ("admin-read", "enabled", 0),
    ],
)
def test_admin_policy_preflight_fails_closed(
    tmp_path: Path, token: str, response: str, exit_code: int
) -> None:
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "${FAKE_GH_RESPONSE}" in
  denied) exit 1 ;;
  malformed) printf '%s\\n' 'not-json' ;;
  disabled) printf '%s\\n' '{"enabled":false}' ;;
  enabled) printf '%s\\n' '{"enabled":true}' ;;
esac
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_GH_RESPONSE": response,
            "GH_TOKEN": token,
            "GITHUB_REPOSITORY": "777genius/infinity-context",
            "PATH": f"{tmp_path}:{environment['PATH']}",
        }
    )
    result = subprocess.run(
        ["bash", "-c", _step_run(
            "publish",
            "Confirm immutable-release policy with administration-read token",
        )],
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == exit_code


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


def test_tag_and_ruleset_drift_is_rejected_at_both_effect_boundaries() -> None:
    effect = _step_run(
        "publish", "Create one draft, upload exact assets, verify, and publish once"
    )
    create = 'gh release create "${RELEASE_TAG}"'
    publish = 'gh release edit "${RELEASE_TAG}"'
    assert effect.count("revalidate_tag_and_ruleset") == 3  # definition plus two calls
    assert 'test "$(jq -er \'.object.type\' <<<"${ref}")" = tag' in effect
    assert 'test "$(jq -er \'.object.sha\' <<<"${ref}")" = "${TAG_OBJECT}"' in effect
    assert 'test "$(jq -er \'.object.type\' <<<"${tag_json}")" = commit' in effect
    assert (
        'test "$(jq -er \'.object.sha\' <<<"${tag_json}")" = "${RELEASE_COMMIT}"'
        in effect
    )
    assert '.enforcement == "active"' in effect
    _assert_immediate_revalidation(effect, create)
    _assert_immediate_revalidation(effect, publish)
    for hostile in (
        effect.replace(f"revalidate_tag_and_ruleset\n{create}", f":\n{create}"),
        effect.replace(f"revalidate_tag_and_ruleset\n{publish}", f":\n{publish}"),
    ):
        with pytest.raises(AssertionError):
            _assert_immediate_revalidation(hostile, create)
            _assert_immediate_revalidation(hostile, publish)


def test_no_release_effect_precedes_every_required_preflight() -> None:
    names = [str(step.get("name")) for step in _steps("publish")]
    effect_name = "Create one draft, upload exact assets, verify, and publish once"
    effect_index = names.index(effect_name)
    for prerequisite in (
        "Rehash and semantically revalidate transported evidence",
        "Preflight GitHub CLI release verification syntax",
        "Confirm immutable-release policy with administration-read token",
        "Refuse pre-existing release state",
    ):
        assert names.index(prerequisite) < effect_index
    assert names[effect_index - 1] == (
        "Confirm immutable-release policy with administration-read token"
    )
    prior_scripts = "\n".join(
        str(step.get("run", "")) for step in _steps("publish")[:effect_index]
    )
    for forbidden in ("gh release create", "gh release upload", "gh release edit"):
        assert forbidden not in prior_scripts


def test_verification_command_syntax_is_preflighted_before_any_release_effect() -> None:
    publish = _job(_workflow(), "publish")
    verify_help = "gh release verify --help"
    verify_asset_help = "gh release verify-asset --help"
    assert publish.count(verify_help) == 1
    assert publish.count(verify_asset_help) == 1
    assert "gh release verify [<tag>] [flags]" in publish
    assert "gh release verify-asset [<tag>] <file-path> [flags]" in publish
    assert publish.count("grep -Eq -- '(^|[[:space:]])(-R, )?--repo[ =]'") == 2

    first_effect = min(
        publish.index(command)
        for command in (
            'gh release create "${RELEASE_TAG}"',
            'gh release upload "${RELEASE_TAG}"',
            'gh release edit "${RELEASE_TAG}"',
        )
    )
    assert publish.index(verify_help) < first_effect
    assert publish.index(verify_asset_help) < first_effect


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


def test_runbook_requires_protected_exact_ref_and_receipt_export() -> None:
    runbook = (ROOT / "docs/typescript-sdk-release.md").read_text(encoding="utf-8")
    assert "--ref sdk-v0.2.1" in runbook
    assert "--ref <DEFAULT_BRANCH>" not in runbook
    assert "SDK_RELEASE_ADMIN_READ_TOKEN" in runbook
    assert "Administration: read-only" in runbook
    assert "protected `sdk-release` environment" in runbook
    assert "creation/update/deletion ruleset" in runbook
    assert "gh run download <RUN_ID>" in runbook
    assert "90-day receipt" in runbook
    assert "retention-days: 90" in _workflow()


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
