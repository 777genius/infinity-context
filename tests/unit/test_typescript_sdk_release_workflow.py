from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github/workflows/typescript-sdk-release.yml"
PUBLISH_HELPER = ROOT / "packages/infinity_context_ts_sdk/scripts/sdk-release-publish.sh"
RECEIPT_CLI = ROOT / "packages/infinity_context_ts_sdk/scripts/sdk-release-receipt.mjs"
MANIFEST_CLI = ROOT / "packages/infinity_context_ts_sdk/scripts/sdk-release-manifest.mjs"
ARTIFACT = "infinity-context-sdk-0.2.1.tgz"
MANIFEST = "infinity-context-sdk-release-manifest.json"
COMMIT = "a" * 40
TAG_OBJECT = "b" * 40


def _workflow() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _document() -> dict[str, object]:
    return yaml.safe_load(_workflow())


def _steps(job: str) -> list[dict[str, object]]:
    return _document()["jobs"][job]["steps"]


def _step_run(job: str, name: str) -> str:
    matches = [step for step in _steps(job) if step.get("name") == name]
    assert len(matches) == 1
    run = matches[0].get("run")
    assert isinstance(run, str)
    return run


def test_workflow_is_exact_tag_manual_only_and_actions_are_pinned() -> None:
    workflow = _workflow()
    event = workflow.split("permissions: {}", maxsplit=1)[0]
    assert "workflow_dispatch:" in event
    assert "sdk_tag:" in event
    assert "reconcile_only:" in event
    for forbidden in ("push:", "pull_request:", "workflow_run:", "schedule:"):
        assert forbidden not in event
    assert "^sdk-v[0-9]+\\.[0-9]+\\.[0-9]+$" in workflow
    uses = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", workflow, flags=re.MULTILINE)
    assert uses and all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", use) for use in uses)


def test_exact_annotated_tag_workflow_sha_pack_once_and_two_assets_remain_bound() -> None:
    workflow = _workflow()
    resolve = _step_run("build", "Resolve protected annotated tag and repository policy")
    source = _step_run("build", "Revalidate clean source, repository, tag, and package identity")
    assert '"${EXECUTED_REF}" != "refs/tags/${SDK_TAG}"' in resolve
    assert "@refs/tags/${SDK_TAG}" in resolve
    assert '"${EXECUTED_WORKFLOW_SHA}" != "${commit}"' in resolve
    assert 'test "$(git rev-parse "${SDK_TAG}^{tag}")" = "${EXPECTED_TAG_OBJECT}"' in source
    assert "sha256sum .github/workflows/typescript-sdk-release.yml" in source
    assert workflow.count("npm pack --json") == 1
    assert "expected exactly one pack result" in workflow
    consumer = _step_run("build", "Test the same packed tarball and its local attestation")
    assert shlex.split(consumer) == [
        "node",
        "scripts/check-consumer-install.mjs",
        "--artifact",
        "${{ steps.pack.outputs.artifact_name }}",
        "--manifest",
        "${GITHUB_WORKSPACE}/release-bundle/infinity-context-sdk-release-manifest.json",
    ]
    assert workflow.count("find release-bundle -maxdepth 1 -type f") == 2
    assert "--clobber" not in workflow
    assert "npm publish" not in workflow


def test_admin_secret_isolated_in_one_minimal_read_only_protected_job() -> None:
    document = _document()
    jobs = document["jobs"]
    policy = jobs["policy_preflight"]
    publish = jobs["publish"]
    build = jobs["build"]
    assert policy["needs"] == "build"
    assert policy["permissions"] == {}
    assert policy["environment"]["name"] == "sdk-release-policy"
    assert len(policy["steps"]) == 1
    assert "uses" not in policy["steps"][0]
    assert build["permissions"] == {"contents": "read"}
    assert publish["permissions"] == {"contents": "write"}
    assert publish["needs"] == ["build", "policy_preflight"]
    assert "environment" not in publish
    secret = "${{ secrets.SDK_RELEASE_ADMIN_READ_TOKEN }}"
    assert _workflow().count(secret) == 1
    assert secret in yaml.safe_dump(policy)
    assert "SDK_RELEASE_ADMIN_READ_TOKEN" not in yaml.safe_dump(publish)
    assert "actions: write" not in _workflow()
    for forbidden in ("packages: write", "id-token: write", "attestations: write"):
        assert forbidden not in _workflow()


@pytest.mark.parametrize(
    ("token", "body", "curl_status", "expected"),
    [
        ("", '{"enabled":true}', 0, 1),
        ("admin-read", '{"enabled":false}', 0, 1),
        ("admin-read", "not-json", 0, 1),
        ("admin-read", '{"enabled":true}', 22, 1),
        ("admin-read", '{"enabled":true}', 0, 0),
    ],
)
def test_admin_policy_preflight_executes_exact_authenticated_get(
    tmp_path: Path, token: str, body: str, curl_status: int, expected: int
) -> None:
    log = tmp_path / "curl.json"
    fake_curl = tmp_path / "curl"
    fake_curl.write_text(
        """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
Path(os.environ["FAKE_CURL_LOG"]).write_text(json.dumps(sys.argv[1:]))
print(os.environ["FAKE_CURL_BODY"])
raise SystemExit(int(os.environ["FAKE_CURL_STATUS"]))
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "ADMIN_READ_TOKEN": token,
            "FAKE_CURL_BODY": body,
            "FAKE_CURL_LOG": str(log),
            "FAKE_CURL_STATUS": str(curl_status),
            "GITHUB_REPOSITORY": "777genius/infinity-context",
            "PATH": f"{tmp_path}:{env['PATH']}",
        }
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            _step_run(
                "policy_preflight",
                "Read immutable-release policy with isolated administration token",
            ),
        ],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == expected
    if token:
        args = json.loads(log.read_text(encoding="utf-8"))
        assert args.count("GET") == 1
        assert args[args.index("--request") + 1] == "GET"
        assert "Accept: application/vnd.github+json" in args
        assert "X-GitHub-Api-Version: 2026-03-10" in args
        assert f"Authorization: Bearer {token}" in args
        assert args[-1] == (
            "https://api.github.com/repos/777genius/infinity-context/immutable-releases"
        )


def test_no_release_effect_precedes_every_workflow_prerequisite() -> None:
    names = [str(step.get("name")) for step in _steps("publish")]
    effect = names.index("Publish once or reconcile exact published evidence")
    for prerequisite in (
        "Checkout exact release source for semantic verification",
        "Set up exact Node.js",
        "Download exact two-file transport",
        "Rehash and semantically revalidate transported evidence",
        "Preflight GitHub CLI release verification syntax",
    ):
        assert names.index(prerequisite) < effect
    prior = "\n".join(str(step.get("run", "")) for step in _steps("publish")[:effect])
    for forbidden in ("gh release create", "gh release upload", "gh release edit"):
        assert forbidden not in prior
    assert "|| true" not in _workflow() + PUBLISH_HELPER.read_text(encoding="utf-8")


def test_verification_cli_json_contract_is_preflighted_and_not_ignored() -> None:
    script = _step_run("publish", "Preflight GitHub CLI release verification syntax")
    assert script.count("gh release verify --help") == 1
    assert script.count("gh release verify-asset --help") == 1
    assert script.count("--format[ =]") == 2
    helper = PUBLISH_HELPER.read_text(encoding="utf-8")
    assert 'gh release verify "${RELEASE_TAG}"' in helper
    assert 'gh release verify-asset "${RELEASE_TAG}"' in helper
    assert helper.count("--format json") == 2
    assert "release-attestation.json" in helper
    assert RECEIPT_CLI.exists() and MANIFEST_CLI.exists()


def _release(state: str, artifact_bytes: bytes, manifest_bytes: bytes) -> dict[str, object]:
    release = {
        "id": 41,
        "tag_name": "sdk-v0.2.1",
        "name": "Infinity Context TypeScript SDK 0.2.1",
        "draft": state == "draft",
        "prerelease": False,
        "immutable": state == "published",
        "html_url": ("https://github.com/777genius/infinity-context/releases/tag/sdk-v0.2.1"),
        "assets": [
            {
                "id": 51,
                "name": ARTIFACT,
                "digest": f"sha256:{hashlib.sha256(artifact_bytes).hexdigest()}",
            },
            {
                "id": 52,
                "name": MANIFEST,
                "digest": f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}",
            },
        ],
    }
    return release


def _fake_gh_source() -> str:
    return r"""#!/usr/bin/env python3
import json, os, shutil, sys
from pathlib import Path

state_path = Path(os.environ["FAKE_GH_STATE"])
log_path = Path(os.environ["FAKE_GH_LOG"])
remote = Path(os.environ["FAKE_GH_REMOTE"])
args = sys.argv[1:]
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\n")

def load(): return json.loads(state_path.read_text())
def save(value): state_path.write_text(json.dumps(value))
def release_for(name):
    value = json.loads(os.environ["FAKE_RELEASE_JSON"])
    value["draft"] = name == "draft"
    value["immutable"] = name == "published"
    return value

if args[0] == "api":
    if "--method" not in args or args[args.index("--method") + 1] != "GET":
        raise SystemExit("API call was not an explicit GET")
    endpoint = args[-1]
    if "/git/ref/tags/" in endpoint:
        kind = os.environ.get("FAKE_TAG_KIND", "tag")
        print(json.dumps({"object": {"type": kind, "sha": os.environ["TAG_OBJECT"]}}))
    elif "/git/tags/" in endpoint:
        print(json.dumps({"object": {"type": "commit", "sha": os.environ["RELEASE_COMMIT"]}}))
    elif "rulesets?" in endpoint:
        print(json.dumps([[{"id": 7}]]))
    elif "/rulesets/7?" in endpoint:
        print(json.dumps({"target":"tag","enforcement":"active","rules":[
          {"type":"creation"},{"type":"update"},{"type":"deletion"}],
          "conditions":{"ref_name":{"exclude":[],"include":["refs/tags/sdk-v*"]}}}))
    elif "/releases?" in endpoint:
        state = load()
        if state == "absent": print("[]")
        elif state == "malformed":
            print(json.dumps([release_for("published"), release_for("published")]))
        else: print(json.dumps([release_for(state)]))
    else: raise SystemExit(f"unexpected api endpoint: {endpoint}")
elif args[:2] == ["release", "create"]:
    save("draft")
elif args[:2] == ["release", "upload"]:
    pass
elif args[:2] == ["release", "download"]:
    pattern = args[args.index("--pattern") + 1]
    destination = Path(args[args.index("--dir") + 1])
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(remote / pattern, destination / pattern)
elif args[:2] == ["release", "edit"]:
    save("published")
    if os.environ.get("FAKE_EDIT_AMBIGUOUS") == "true": raise SystemExit(1)
elif args[:2] in (["release", "verify"], ["release", "verify-asset"]):
    if os.environ.get("FAKE_VERIFY_FAIL") == "true": raise SystemExit(1)
    print(os.environ["FAKE_ATTESTATION_JSON"])
else: raise SystemExit(f"unexpected gh invocation: {args}")
"""


def _attestation(artifact_bytes: bytes, manifest_bytes: bytes) -> dict[str, object]:
    return {
        "attestation": {"bundle": {"mediaType": "test"}},
        "verificationResult": {
            "signature": {"certificate": {}},
            "statement": {
                "predicateType": "https://in-toto.io/attestation/release/v0.1",
                "predicate": {
                    "releaseId": "41",
                    "repository": "777genius/infinity-context",
                    "tag": "sdk-v0.2.1",
                },
                "subject": [
                    {"uri": "pkg:github/repo@tag", "digest": {"sha1": COMMIT}},
                    {
                        "name": ARTIFACT,
                        "digest": {"sha256": hashlib.sha256(artifact_bytes).hexdigest()},
                    },
                    {
                        "name": MANIFEST,
                        "digest": {"sha256": hashlib.sha256(manifest_bytes).hexdigest()},
                    },
                ],
            },
        },
    }


def _run_helper(
    tmp_path: Path,
    state: str,
    *,
    ambiguous: bool = False,
    reconcile_only: bool = False,
    tag_kind: str = "tag",
    verify_fail: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], Path]:
    artifact_bytes = b"exact pack-once bytes\n"
    manifest_bytes = b'{"build_workflow_run_attempt":2,"build_workflow_run_id":12345}\n'
    transported_manifest = (
        b'{"build_workflow_run_attempt":9,"build_workflow_run_id":99999}\n'
        if state == "published"
        else manifest_bytes
    )
    bundle = tmp_path / "release-bundle"
    remote = tmp_path / "remote"
    fake_bin = tmp_path / "bin"
    for directory in (bundle, remote, fake_bin):
        directory.mkdir()
    (bundle / ARTIFACT).write_bytes(artifact_bytes)
    (bundle / MANIFEST).write_bytes(transported_manifest)
    (remote / ARTIFACT).write_bytes(artifact_bytes)
    (remote / MANIFEST).write_bytes(manifest_bytes)
    gh = fake_bin / "gh"
    gh.write_text(_fake_gh_source(), encoding="utf-8")
    gh.chmod(0o755)
    node = fake_bin / "node"
    node.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    node.chmod(0o755)
    packages = tmp_path / "packages"
    packages.symlink_to(ROOT / "packages", target_is_directory=True)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    log_path = tmp_path / "gh.log"
    output_path = tmp_path / "github-output"
    env = os.environ.copy()
    env.update(
        {
            "FAKE_ATTESTATION_JSON": json.dumps(_attestation(artifact_bytes, manifest_bytes)),
            "FAKE_EDIT_AMBIGUOUS": str(ambiguous).lower(),
            "FAKE_GH_LOG": str(log_path),
            "FAKE_GH_REMOTE": str(remote),
            "FAKE_GH_STATE": str(state_path),
            "FAKE_RELEASE_JSON": json.dumps(_release(state, artifact_bytes, manifest_bytes)),
            "FAKE_TAG_KIND": tag_kind,
            "FAKE_VERIFY_FAIL": str(verify_fail).lower(),
            "GITHUB_OUTPUT": str(output_path),
            "GITHUB_REPOSITORY": "777genius/infinity-context",
            "GITHUB_RUN_ATTEMPT": "2",
            "GITHUB_RUN_ID": "12345",
            "GITHUB_WORKSPACE": str(tmp_path),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "RECONCILE_ONLY": str(reconcile_only).lower(),
            "RELEASE_COMMIT": COMMIT,
            "RELEASE_POLL_SECONDS": "0",
            "RELEASE_TAG": "sdk-v0.2.1",
            "SDK_ARTIFACT": ARTIFACT,
            "SDK_VERSION": "0.2.1",
            "TAG_OBJECT": TAG_OBJECT,
            "WORKFLOW_SHA256": "c" * 64,
        }
    )
    result = subprocess.run(
        ["bash", str(PUBLISH_HELPER)],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    calls = (
        [json.loads(line) for line in log_path.read_text().splitlines()]
        if log_path.exists()
        else []
    )
    return result, calls, state_path


def _effects(calls: list[list[str]]) -> list[list[str]]:
    return [
        call
        for call in calls
        if call[:2] in (["release", "create"], ["release", "upload"], ["release", "edit"])
    ]


def test_publish_executes_hostile_preconditions_before_each_effect(tmp_path: Path) -> None:
    result, calls, state = _run_helper(tmp_path, "absent")
    assert result.returncode == 0, result.stderr
    assert json.loads(state.read_text()) == "published"
    create_index = calls.index(next(call for call in calls if call[:2] == ["release", "create"]))
    edit_index = calls.index(next(call for call in calls if call[:2] == ["release", "edit"]))
    before_create = calls[:create_index]
    between = calls[create_index:edit_index]
    assert any("/git/ref/tags/" in call[-1] for call in before_create)
    assert any("rulesets?targets=tag" in call[-1] for call in before_create)
    assert any("/git/ref/tags/" in call[-1] for call in between)
    assert any("rulesets?targets=tag" in call[-1] for call in between)
    assert len([call for call in calls if call[:2] == ["release", "upload"]]) == 2
    assert all("--clobber" not in call for call in calls)


def test_uncertain_publish_outcome_is_reconciled_and_evidenced(tmp_path: Path) -> None:
    result, calls, state = _run_helper(tmp_path, "absent", ambiguous=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(state.read_text()) == "published"
    assert len([call for call in calls if call[:2] == ["release", "edit"]]) == 1
    assert any(call[:2] == ["release", "verify"] for call in calls)
    assert len([call for call in calls if call[:2] == ["release", "verify-asset"]]) == 2
    assert (tmp_path / "verification-receipt/release.json").is_file()


def test_exact_published_release_reconciles_without_any_effect(tmp_path: Path) -> None:
    result, calls, _ = _run_helper(tmp_path, "published", reconcile_only=True)
    assert result.returncode == 0, result.stderr
    assert _effects(calls) == []
    assert any(call[:2] == ["release", "download"] for call in calls)
    assert any(call[:2] == ["release", "verify"] for call in calls)


@pytest.mark.parametrize("state", ["draft", "malformed"])
def test_non_resumable_release_states_fail_without_effects(tmp_path: Path, state: str) -> None:
    result, calls, _ = _run_helper(tmp_path, state)
    assert result.returncode != 0
    assert _effects(calls) == []


def test_reconcile_only_absence_and_hostile_tag_fail_before_effects(tmp_path: Path) -> None:
    absent = tmp_path / "absent"
    absent.mkdir()
    result, calls, _ = _run_helper(absent, "absent", reconcile_only=True)
    assert result.returncode != 0
    assert _effects(calls) == []
    hostile = tmp_path / "hostile"
    hostile.mkdir()
    result, calls, _ = _run_helper(hostile, "absent", tag_kind="commit")
    assert result.returncode != 0
    assert _effects(calls) == []


def test_failed_attestation_verification_is_not_ignored(tmp_path: Path) -> None:
    result, calls, _ = _run_helper(tmp_path, "published", verify_fail=True)
    assert result.returncode != 0
    assert _effects(calls) == []
    assert any(call[:2] == ["release", "verify"] for call in calls)


def _receipt_fixture(tmp_path: Path) -> tuple[list[str], Path, dict[str, object]]:
    asset_dir = tmp_path / "evidence"
    asset_dir.mkdir(parents=True)
    artifact_bytes = b"receipt artifact bytes\n"
    manifest = {
        "artifact_name": ARTIFACT,
        "build_workflow_run_attempt": 2,
        "build_workflow_run_id": 12345,
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (asset_dir / ARTIFACT).write_bytes(artifact_bytes)
    (asset_dir / MANIFEST).write_bytes(manifest_bytes)
    release = _release("published", artifact_bytes, manifest_bytes)
    (asset_dir / "release.json").write_text(json.dumps(release), encoding="utf-8")
    attestation = _attestation(artifact_bytes, manifest_bytes)
    (asset_dir / "release-attestation.json").write_text(json.dumps(attestation), encoding="utf-8")
    for name in (ARTIFACT, MANIFEST):
        (asset_dir / f"{name}.attestation.json").write_text(
            json.dumps(attestation), encoding="utf-8"
        )
    output = asset_dir / "infinity-context-sdk-release-verification-receipt.json"
    args = [
        "node",
        str(RECEIPT_CLI),
        "--asset-dir",
        str(asset_dir),
        "--output",
        str(output),
        "--output-root",
        str(asset_dir),
        "--release-attestation-json",
        str(asset_dir / "release-attestation.json"),
        "--release-commit",
        COMMIT,
        "--release-json",
        str(asset_dir / "release.json"),
        "--repository",
        "777genius/infinity-context",
        "--tag",
        "sdk-v0.2.1",
    ]
    return args, output, attestation


def test_receipt_parses_attestations_and_binds_commit_assets_and_origin_run(tmp_path: Path) -> None:
    args, output, _ = _receipt_fixture(tmp_path)
    subprocess.run(args, check=True, capture_output=True, text=True)
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["run_id"] == 12345
    assert receipt["run_attempt"] == 2
    assert receipt["release_attestation_verified"] is True
    assert [item["name"] for item in receipt["assets"]] == sorted([ARTIFACT, MANIFEST])
    assert all(item["attestation_verified"] is True for item in receipt["assets"])

    retry_args, retry_output, _ = _receipt_fixture(tmp_path / "retry")
    subprocess.run(retry_args, check=True, capture_output=True, text=True)
    assert retry_output.read_bytes() == output.read_bytes()


@pytest.mark.parametrize("tamper", ["commit", "asset", "predicate"])
def test_receipt_rejects_hostile_attestation_output(tmp_path: Path, tamper: str) -> None:
    args, output, attestation = _receipt_fixture(tmp_path)
    statement = attestation["verificationResult"]["statement"]
    if tamper == "commit":
        statement["subject"][0]["digest"]["sha1"] = "d" * 40
    elif tamper == "asset":
        statement["subject"][1]["digest"]["sha256"] = "e" * 64
    else:
        statement["predicate"]["tag"] = "sdk-v9.9.9"
    evidence = tmp_path / "evidence"
    for path in evidence.glob("*attestation.json"):
        path.write_text(json.dumps(attestation), encoding="utf-8")
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    assert result.returncode != 0
    assert not output.exists()


def test_runbook_and_retention_contract() -> None:
    runbook = (ROOT / "docs/typescript-sdk-release.md").read_text(encoding="utf-8")
    normalized = " ".join(runbook.split())
    assert "--ref sdk-v0.2.3" in runbook
    assert "--ref <DEFAULT_BRANCH>" not in runbook
    assert "sdk-release-policy" in runbook
    assert "Administration: read-only" in runbook
    assert "reconcile_only=true" in runbook
    assert "90-day receipt" in runbook
    assert "retention-days: 90" in _workflow()
    assert "configure no required reviewers or self-review prevention" in normalized
    assert "does not wait for human approval" in normalized
    assert "required independent review" not in normalized
    assert "Approve `sdk-release-policy`" not in runbook


def test_release_files_do_not_reintroduce_service_quality_or_public_api_changes() -> None:
    for forbidden in (
        "3x240",
        "human adjudication",
        "qualification manifest",
        "service revision",
        "capability fingerprint",
    ):
        assert forbidden not in _workflow().lower()
    assert not (ROOT / "scripts/verify_retrieval_release_qualification.py").exists()
