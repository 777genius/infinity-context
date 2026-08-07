"""Generate Pin B from the exact Docker source closure at an archived Git commit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SCHEMA = "mem0-oss-adapter-v5.source-authority.v1"
CLOSURE_ALGORITHM = "sha256(sorted(path + NUL + size + NUL + sha256 + LF))"
SHA1 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

EXACT_COPIES = (
    ("benchmarks/mem0-oss-adapter-v5/README.md", "README.md"),
    ("benchmarks/mem0-oss-adapter-v5/Dockerfile", "deploy/Dockerfile"),
    (
        "benchmarks/mem0-oss-adapter-v5/compose.hosted-canary.yaml",
        "deploy/compose.hosted-canary.yaml",
    ),
    ("benchmarks/mem0-oss-adapter-v5/pyproject.toml", "pyproject.toml"),
    ("benchmarks/mem0-oss-adapter-v5/runtime-lock.json", "runtime-lock.json"),
    ("benchmarks/mem0-oss-adapter-v5/uv.lock", "uv.lock"),
    ("benchmarks/mem0-oss-adapter/runtime-pin.json", "runtime-pin.json"),
    (
        "benchmarks/mem0-oss-adapter/scripts/stage_fastembed_model.py",
        "scripts/stage_fastembed_model.py",
    ),
)
TREE_COPIES = (
    (
        "benchmarks/mem0-oss-adapter-v5/mem0_oss_adapter_v5",
        "mem0_oss_adapter_v5",
    ),
    ("benchmarks/mem0-oss-adapter/mem0_oss_adapter", "mem0_oss_adapter"),
    ("benchmarks/phase-c-canary/phase_c_canary", "phase_c_canary"),
)


@dataclass(frozen=True, slots=True)
class PhaseCAuthority:
    infinity_commit_sha1: str
    infinity_tree_sha1: str
    release_manifest_sha256: str

    def __post_init__(self) -> None:
        if (
            SHA1.fullmatch(self.infinity_commit_sha1) is None
            or SHA1.fullmatch(self.infinity_tree_sha1) is None
            or SHA256.fullmatch(self.release_manifest_sha256) is None
        ):
            raise ValueError("phase_c_source_authority_invalid")

    def payload(self) -> dict[str, str]:
        return {
            "infinity_commit_sha1": self.infinity_commit_sha1,
            "infinity_tree_sha1": self.infinity_tree_sha1,
            "release_manifest_sha256": self.release_manifest_sha256,
        }


def phase_c_authority(root: Path) -> PhaseCAuthority:
    root = root.resolve(strict=True)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("phase_c_source_authority_invalid")
    attestation = root / "attestation"
    commit = _read_small_text(attestation / "commit.txt")
    tree = _read_small_text(attestation / "tree.txt")
    release = _read_regular_file(attestation / "release-files.sha256", maximum=8 << 20)
    return PhaseCAuthority(
        infinity_commit_sha1=commit,
        infinity_tree_sha1=tree,
        release_manifest_sha256=hashlib.sha256(release).hexdigest(),
    )


def source_manifest(
    repository: Path,
    revision: str,
    phase_c: PhaseCAuthority,
) -> tuple[dict[str, object], dict[str, bytes]]:
    repository = repository.resolve(strict=True)
    commit = _git_text(repository, "rev-parse", f"{revision}^{{commit}}")
    tree = _git_text(repository, "rev-parse", f"{commit}^{{tree}}")
    if SHA1.fullmatch(commit) is None or SHA1.fullmatch(tree) is None:
        raise ValueError("source_authority_revision_invalid")

    staged: dict[str, bytes] = {}
    for source, target in EXACT_COPIES:
        _add_staged(staged, target, _git_bytes(repository, "show", f"{commit}:{source}"))
    for source_root, target_root in TREE_COPIES:
        for source, blob in _tree_blobs(repository, commit, source_root):
            relative = PurePosixPath(source).relative_to(source_root).as_posix()
            _add_staged(staged, f"{target_root}/{relative}", blob)

    files = []
    rows = []
    for relative, content in sorted(staged.items()):
        digest = hashlib.sha256(content).hexdigest()
        size = len(content)
        files.append({"path": relative, "sha256": digest, "size": size})
        rows.append(f"{relative}\0{size}\0{digest}\n")
    manifest: dict[str, object] = {
        "closure_algorithm": CLOSURE_ALGORITHM,
        "closure_sha256": hashlib.sha256("".join(rows).encode()).hexdigest(),
        "files": files,
        "phase_c_authority": phase_c.payload(),
        "schema_version": SCHEMA,
        "source_commit_sha1": commit,
        "source_tree_sha1": tree,
    }
    return manifest, staged


def encoded_manifest(manifest: dict[str, object]) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()


def write_authority(
    *,
    authority_directory: Path,
    runtime_pin_file: Path,
    manifest: dict[str, object],
) -> str:
    authority_directory = authority_directory.resolve(strict=True)
    runtime_pin_file = runtime_pin_file.resolve(strict=True)
    encoded = encoded_manifest(manifest)
    digest = hashlib.sha256(encoded).hexdigest()
    _atomic_write(authority_directory / "manifest.json", encoded)
    _atomic_write(authority_directory / "manifest.sha256", f"{digest}\n".encode())

    runtime_pin = json.loads(runtime_pin_file.read_bytes())
    source_a = runtime_pin.get("source_a")
    if type(source_a) is not dict or set(source_a) != {
        "closure_algorithm",
        "closure_sha256",
        "commit_sha1",
        "manifest_file_count",
        "manifest_sha256",
        "tree_sha1",
    }:
        raise ValueError("runtime_pin_source_authority_invalid")
    files = manifest["files"]
    assert type(files) is list
    runtime_pin["source_a"] = {
        "closure_algorithm": manifest["closure_algorithm"],
        "closure_sha256": manifest["closure_sha256"],
        "commit_sha1": manifest["source_commit_sha1"],
        "manifest_file_count": len(files),
        "manifest_sha256": digest,
        "tree_sha1": manifest["source_tree_sha1"],
    }
    _atomic_write(
        runtime_pin_file,
        (json.dumps(runtime_pin, indent=2, sort_keys=True) + "\n").encode(),
    )
    return digest


def _tree_blobs(
    repository: Path,
    commit: str,
    source_root: str,
) -> tuple[tuple[str, bytes], ...]:
    raw = _git_bytes(repository, "ls-tree", "-r", "-z", commit, "--", source_root)
    result = []
    for encoded_entry in raw.split(b"\0"):
        if not encoded_entry:
            continue
        metadata, encoded_path = encoded_entry.split(b"\t", 1)
        mode, kind, object_id = metadata.decode().split()
        source = encoded_path.decode()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError("source_authority_non_regular_file")
        result.append((source, _git_bytes(repository, "cat-file", "blob", object_id)))
    if not result:
        raise ValueError("source_authority_tree_empty")
    return tuple(result)


def _add_staged(staged: dict[str, bytes], relative: str, content: bytes) -> None:
    path = PurePosixPath(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("source_authority_target_invalid")
    normalized = path.as_posix()
    if normalized in staged:
        raise ValueError("source_authority_target_duplicate")
    staged[normalized] = content


def _git_bytes(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
    ).stdout


def _git_text(repository: Path, *arguments: str) -> str:
    return _git_bytes(repository, *arguments).decode().strip()


def _read_small_text(path: Path) -> str:
    return _read_regular_file(path, maximum=128).decode().strip()


def _read_regular_file(path: Path, *, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("source_authority_input_invalid")
    raw = path.read_bytes()
    if not 1 <= len(raw) <= maximum:
        raise ValueError("source_authority_input_invalid")
    return raw


def _atomic_write(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--phase-c-authority-root", required=True, type=Path)
    parser.add_argument("--authority-directory", required=True, type=Path)
    parser.add_argument("--runtime-pin-file", required=True, type=Path)
    args = parser.parse_args()
    manifest, _ = source_manifest(
        args.repository,
        args.source_revision,
        phase_c_authority(args.phase_c_authority_root),
    )
    digest = write_authority(
        authority_directory=args.authority_directory,
        runtime_pin_file=args.runtime_pin_file,
        manifest=manifest,
    )
    print(
        json.dumps(
            {
                "manifest_file_count": len(manifest["files"]),
                "manifest_sha256": digest,
                "source_commit_sha1": manifest["source_commit_sha1"],
                "source_tree_sha1": manifest["source_tree_sha1"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
