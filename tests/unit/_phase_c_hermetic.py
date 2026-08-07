"""Hermetic exact-class Phase-C authority for ordinary unit tests."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace


def install_hermetic_phase_c_authority(
    *, monkeypatch: object, tmp_path: Path, phase_c_root: Path
) -> tuple[object, Path]:
    if str(phase_c_root) not in sys.path:
        sys.path.insert(0, str(phase_c_root))
    from phase_c_canary import runtime_binding as runtime_binding_subject
    from phase_c_canary.runtime_binding import (
        PinnedRuntimeBindingService,
        RuntimeBindingComposition,
        TrustedRuntimeBinding,
    )

    artifact = tmp_path / "hermetic-phase-c" / "artifact-manifest.json"
    artifact.parent.mkdir()
    raw = b'{"schema_version":"hermetic-unit-runtime.v1"}'
    artifact.write_bytes(raw)
    reviewed = SimpleNamespace(
        runtime_artifact_manifest=SimpleNamespace(
            path=artifact,
            sha256=hashlib.sha256(raw).hexdigest(),
        ),
        runtime_commit="hermetic-unit-runtime-commit",
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        runtime_binding_subject,
        "immutable_authority",
        lambda: reviewed,
    )
    service = RuntimeBindingComposition.compose_phase_c_canary()
    binding = service.issue()
    assert type(service) is PinnedRuntimeBindingService
    assert type(binding) is TrustedRuntimeBinding
    assert artifact.is_relative_to(tmp_path)
    assert "/mnt/volume_ams3_" not in str(artifact)
    return binding, artifact


__all__ = ("install_hermetic_phase_c_authority",)
