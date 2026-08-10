from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


class AuthorityBindingError(RuntimeError):
    """A deployment tried to relocate an authority through an unsafe path."""


@runtime_checkable
class AuthorityPathBindingPort(Protocol):
    """Deployment-owned roots for the same immutable Phase-C authority."""

    @property
    def infinity_source_root(self) -> Path: ...

    @property
    def runtime_root(self) -> Path: ...


@dataclass(frozen=True, slots=True)
class ImmutableFile:
    path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class AuthorityContract:
    schema_version: int
    infinity_commit: str
    infinity_source_root: Path
    infinity_release_manifest: ImmutableFile
    runtime_commit: str
    runtime_root: Path
    runtime_artifact_manifest: ImmutableFile
    runtime_release: ImmutableFile
    stateless_base_sha256: str
    runtime_receipt_schema: int
    provider_usage_schema: int
    execution_profile: str
    response_format_type: str
    response_format_sha256: str
    response_schema_sha256: str
    response_format_policy_sha256: str
    model: str
    reasoning_effort: str
    service_tier: str
    requested_output_tokens: int


def immutable_authority(
    *, authority_binding: AuthorityPathBindingPort | None = None
) -> AuthorityContract:
    if authority_binding is None:
        source = Path("/mnt/volume_ams3_1784742570542/infinity-context/sources/9499b9c2")
        runtime = Path(
            "/mnt/volume_ams3_1784742570542/infinity-context/runtimes/subscription-runtime/e904ec95"
        )
    else:
        source, runtime = _bound_roots(authority_binding)
    return AuthorityContract(
        schema_version=1,
        infinity_commit="9499b9c2cf3842c4fe3bbe78a601b278cf00ba43",
        infinity_source_root=source,
        infinity_release_manifest=ImmutableFile(
            source / "attestation/release-files.sha256",
            "10b73e189ab23867b3cf368dd0f961faa19aad7baa94e6c3df48471adf4abe93",
        ),
        runtime_commit="e904ec95fda4b04c333e5a7613c7729bf7abb125",
        runtime_root=runtime,
        runtime_artifact_manifest=ImmutableFile(
            runtime / "artifact-manifest.json",
            "789018b5b15a1299252895babdc550c3d5322c54a1d9c82656f93d31423a0850",
        ),
        runtime_release=ImmutableFile(
            runtime / "release.json",
            "8854ae10ea450fc615af251cdd5eef8812f928b458f710bb84b0cdbdde92fceb",
        ),
        stateless_base_sha256=("5c15d6c502d380282a933d4f20a886a06c9d04d3b5d7c918b95df0b0acf33671"),
        runtime_receipt_schema=2,
        provider_usage_schema=3,
        execution_profile="stateless-completion",
        response_format_type="json_schema",
        response_format_sha256=("812938567c7a81bac6ed3266608adf470dedc57706102e039422f695495322bf"),
        response_schema_sha256=("2461f7a465be82aa67751dc04e0717cde75c69b86e7db54bb306a2e3d1d4d8f0"),
        response_format_policy_sha256=(
            "9d7bcc89f3e8cc3683a18d83d90d6ffde05cdb02358d1cd055bf273f92a772f1"
        ),
        model="gpt-5.6-sol",
        reasoning_effort="high",
        service_tier="default",
        requested_output_tokens=4096,
    )


def _bound_roots(binding: AuthorityPathBindingPort) -> tuple[Path, Path]:
    if not isinstance(binding, AuthorityPathBindingPort):
        raise AuthorityBindingError("immutable authority path binding is invalid")
    source = _real_directory(binding.infinity_source_root)
    runtime = _real_directory(binding.runtime_root)
    if source == runtime or source.is_relative_to(runtime) or runtime.is_relative_to(source):
        raise AuthorityBindingError("immutable authority roots overlap")
    return source, runtime


def _real_directory(value: object) -> Path:
    if not isinstance(value, Path) or not value.is_absolute() or ".." in value.parts:
        raise AuthorityBindingError("immutable authority path binding is invalid")
    try:
        metadata = value.lstat()
        canonical = value.resolve(strict=True)
    except OSError:
        raise AuthorityBindingError("immutable authority path binding is unavailable") from None
    if canonical != value or stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise AuthorityBindingError("immutable authority path binding is invalid")
    return value


__all__ = (
    "AuthorityBindingError",
    "AuthorityContract",
    "AuthorityPathBindingPort",
    "ImmutableFile",
    "immutable_authority",
)
