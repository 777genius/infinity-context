#!/usr/bin/env python3
"""Canonical content manifest for isolated Retrieval V2 lifecycle evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

_DIRECTORIES = (
    ".github",
    "docker",
    "docs",
    "examples",
    "frontend",
    "packages",
    "plugins",
    "scripts",
    "tests",
)
_TOP_LEVEL = (
    "AGENTS.md",
    "CHANGELOG.md",
    "Dockerfile",
    "Makefile",
    "README.md",
    "docker-compose.selfhost.yml",
    "docker-compose.yml",
    "pyproject.toml",
    "uv.lock",
)
_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
    }
)
_SOURCE_SUFFIXES = frozenset(
    {
        ".css",
        ".html",
        ".js",
        ".json",
        ".lock",
        ".md",
        ".mjs",
        ".py",
        ".pyi",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsx",
        ".yaml",
        ".yml",
    }
)


def build_manifest(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    candidates = [root / name for name in _TOP_LEVEL]
    for directory in _DIRECTORIES:
        candidates.extend((root / directory).rglob("*"))
    files = sorted(
        {
            path.resolve(strict=True)
            for path in candidates
            if path.is_file()
            and path.suffix in _SOURCE_SUFFIXES
            and not any(part in _EXCLUDED_PARTS for part in path.parts)
            and not path.name.startswith(".env")
        },
        key=lambda path: path.relative_to(root).as_posix(),
    )
    if not files or any(not path.is_relative_to(root) for path in files):
        raise RuntimeError("retrieval lifecycle manifest scope is invalid")
    entries = []
    canonical = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        file_digest = hashlib.sha256(data).hexdigest()
        entry = {"path": relative, "sha256": file_digest, "size": len(data)}
        entries.append(entry)
        canonical.update(
            json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        canonical.update(b"\n")
    return {
        "schema": "infinity-context-reviewed-content-manifest.v1",
        "file_count": len(entries),
        "manifest_sha256": canonical.hexdigest(),
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = build_manifest(args.root)
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "file_count": manifest["file_count"],
                "manifest_sha256": manifest["manifest_sha256"],
                "schema": manifest["schema"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
