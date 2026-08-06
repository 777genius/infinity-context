"""Explicit local enrollment of a workspace into AUTO_LOCKED project memory."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from infinity_context_mcp.safe_http import open_without_redirects
from infinity_context_mcp.workspace_binding import (
    GitRepositoryIdentityProbe,
    WorkspaceProbeStatus,
    code_scope_for_probe,
)


def enroll_project(
    *,
    cwd: str,
    api_url: str,
    admin_token: str,
    space_id: str,
    space_slug: str,
    memory_scope_external_ref: str,
    bindings_file: str,
    provider: str = "local",
    safe_label: str | None = None,
    remote_name: str | None = None,
) -> dict[str, object]:
    probe = GitRepositoryIdentityProbe(remote_name=remote_name).probe(cwd)
    if probe.status is not WorkspaceProbeStatus.RESOLVED or not probe.evidence:
        raise ValueError(f"Workspace identity is unresolved: {probe.safe_reason}")
    response = _post_json(
        f"{api_url.rstrip('/')}/v1/code-repositories/resolve",
        token=admin_token,
        payload={
            "space_id": space_id,
            "evidence": [
                {"kind": item.kind.value, "digest": item.digest} for item in probe.evidence
            ],
            "provider": provider,
            "allow_create": True,
            "safe_label": safe_label,
            "initial_code_scope": {
                "scope_level": (
                    "branch"
                    if probe.branch is not None
                    else "commit"
                    if probe.commit_sha is not None
                    else "repository"
                ),
                "branch": probe.branch,
                "commit_sha": probe.commit_sha,
            },
        },
    )
    data = response.get("data")
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("repository_id"), str)
        or not isinstance(data.get("binding_id"), str)
        or not isinstance(data.get("binding_version"), int)
        or not isinstance(data.get("binding_grant"), str)
    ):
        raise RuntimeError("Repository enrollment returned an invalid response")
    repository_id = data["repository_id"]
    scope = code_scope_for_probe(repository_id, probe)
    registered_scope = data.get("initial_code_scope")
    if (
        not isinstance(registered_scope, dict)
        or registered_scope.get("code_scope_id") != scope.code_scope_id
        or registered_scope.get("status") != "active"
    ):
        raise RuntimeError("Repository enrollment did not authorize the probed CodeScope")
    binding = {
        "binding_id": data["binding_id"],
        "binding_version": data["binding_version"],
        "binding_grant": data["binding_grant"],
        "space_slug": space_slug,
        "memory_scope_external_ref": memory_scope_external_ref,
        "repository_id": repository_id,
        "evidence": [{"kind": item.kind.value, "digest": item.digest} for item in probe.evidence],
        "drift_status": "stable",
    }
    _upsert_binding(Path(bindings_file).expanduser(), binding)
    return {
        "status": "enrolled",
        "repository_id": repository_id,
        "binding_id": binding["binding_id"],
        "bindings_file": str(Path(bindings_file).expanduser()),
        "code_scope_id": scope.code_scope_id,
        "next_step": (
            "Create a repository-scoped service token with memory:read and "
            "memory:capture permissions"
        ),
    }


def _post_json(url: str, *, token: str, payload: dict[str, object]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with open_without_redirects(request, timeout=10) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Repository enrollment returned HTTP {exc.code}") from exc
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise RuntimeError("Repository enrollment request failed") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Repository enrollment returned a non-object response")
    return parsed


def _upsert_binding(path: Path, binding: dict[str, object]) -> None:
    payload: dict[str, Any] = {"schema_version": 1, "bindings": []}
    if path.exists():
        stat = path.stat()
        if stat.st_mode & 0o022:
            raise ValueError("Existing project bindings file is group/world writable")
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(parsed, dict)
            or parsed.get("schema_version") != 1
            or not isinstance(parsed.get("bindings"), list)
        ):
            raise ValueError("Existing project bindings file is invalid")
        payload = parsed
    bindings = payload["bindings"]
    evidence = binding["evidence"]
    assert isinstance(bindings, list)
    assert isinstance(evidence, list)
    new_pairs = {
        (item["kind"], item["digest"])
        for item in evidence
        if isinstance(item, dict) and "kind" in item and "digest" in item
    }
    retained = []
    for existing in bindings:
        if not isinstance(existing, dict):
            raise ValueError("Existing project binding is invalid")
        existing_evidence = existing.get("evidence")
        existing_pairs = (
            {
                (item["kind"], item["digest"])
                for item in existing_evidence
                if isinstance(item, dict) and "kind" in item and "digest" in item
            }
            if isinstance(existing_evidence, list)
            else set()
        )
        if new_pairs.intersection(existing_pairs):
            continue
        retained.append(existing)
    payload["bindings"] = [*retained, binding]
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=True, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Enroll a trusted project workspace")
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument(
        "--api-url", default=os.getenv("MEMORY_MCP_API_URL", "http://127.0.0.1:7788")
    )
    parser.add_argument("--space-id", required=True)
    parser.add_argument("--space-slug", required=True)
    parser.add_argument("--memory-scope", required=True)
    parser.add_argument("--bindings-file", required=True)
    parser.add_argument("--provider", default="local")
    parser.add_argument("--safe-label", default=None)
    parser.add_argument("--remote", default=None)
    args = parser.parse_args()
    token = os.getenv("MEMORY_ADMIN_TOKEN") or os.getenv("MEMORY_SERVICE_TOKEN")
    if not token:
        parser.error("MEMORY_ADMIN_TOKEN or MEMORY_SERVICE_TOKEN is required")
    result = enroll_project(
        cwd=args.cwd,
        api_url=args.api_url,
        admin_token=token,
        space_id=args.space_id,
        space_slug=args.space_slug,
        memory_scope_external_ref=args.memory_scope,
        bindings_file=args.bindings_file,
        provider=args.provider,
        safe_label=args.safe_label,
        remote_name=args.remote,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
