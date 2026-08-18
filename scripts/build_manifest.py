"""Generate or verify the trusted source manifest used by the Docker build."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

EXCLUDED_PARTS = {"__pycache__", ".wdio", "dist", "node_modules"}
SCHEMA = "infinity-context.source-build.v1"
GIT_SHA = re.compile(r"^[a-f0-9]{40}$")
ROOTS = (
    "Dockerfile",
    "docker/infinity-context-entrypoint.sh",
    "pyproject.toml",
    "packages",
    "scripts/build_manifest.py",
)


def source_digest(repo: Path, *, service_revision: str) -> str:
    digest = hashlib.sha256()
    digest.update(b"service_revision\0")
    digest.update(service_revision.encode("ascii"))
    digest.update(b"\0")
    files = sorted(
        path
        for root in ROOTS
        for path in (repo / root).glob("**/*")
        if (
            path.is_file()
            and not EXCLUDED_PARTS.intersection(path.relative_to(repo).parts)
            and path.name != ".DS_Store"
        )
    )
    files.extend(repo / root for root in ROOTS if (repo / root).is_file())
    for path in sorted(set(files)):
        relative = path.relative_to(repo).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def generate(repo: Path, output: Path) -> None:
    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all", "--", *ROOTS)
    if status:
        raise RuntimeError("trusted source inputs are dirty")
    revision = _git(repo, "rev-parse", "HEAD")
    if GIT_SHA.fullmatch(revision) is None:
        raise RuntimeError("trusted source revision is not an immutable Git SHA")
    payload = {
        "schema_version": SCHEMA,
        "service_revision": revision,
        "source_tree_digest_sha256": source_digest(repo, service_revision=revision),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def verify(repo: Path, manifest: Path) -> None:
    payload = json.loads(manifest.read_text())
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "service_revision",
        "source_tree_digest_sha256",
    }:
        raise RuntimeError("source build manifest has an unsupported contract")
    if payload["schema_version"] != SCHEMA:
        raise RuntimeError("source build manifest schema is unsupported")
    revision = payload["service_revision"]
    if not isinstance(revision, str) or GIT_SHA.fullmatch(revision) is None:
        raise RuntimeError("source build manifest revision is invalid")
    if payload["source_tree_digest_sha256"] != source_digest(repo, service_revision=revision):
        raise RuntimeError("source build manifest does not match Docker build inputs")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(repo), *args), check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("generate", "verify"))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--manifest", type=Path, default=Path("build/infinity-context-source-manifest.json")
    )
    args = parser.parse_args()
    if args.action == "generate":
        generate(args.repo, args.manifest)
    else:
        verify(args.repo, args.manifest)


if __name__ == "__main__":
    main()
