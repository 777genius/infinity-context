"""Frozen public identity for the active dense embedding profile."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from infinity_context_server.build_identity import verify_installed_build_identity
from infinity_context_server.tei_probe import TeiProbe

if TYPE_CHECKING:
    from infinity_context_server.config import Settings

_GIT_SHA = re.compile(r"^[a-f0-9]{40}$")
_PROFILE_COMPONENT = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class VerifiedServingProfile:
    service_revision: str | None
    embedding_profile_id: str | None
    embedding_profile_digest_sha256: str | None
    inference_base_url: str | None
    runtime_probe: TeiProbe | None

    def verify_runtime(self) -> None:
        if self.runtime_probe is not None:
            self.runtime_probe.verify()


def build_verified_serving_profile(settings: Settings) -> VerifiedServingProfile:
    build = verify_installed_build_identity(settings.service_build_identity_path)
    revision = build.service_revision if build else None
    pins = (
        settings.embeddings_model_revision,
        settings.embeddings_runtime_build_revision,
        settings.embeddings_runtime_info_url,
        settings.embeddings_base_url,
    )
    if not settings.embeddings_enabled:
        if any(value is not None for value in pins):
            raise RuntimeError("embedding identity pins require MEMORY_EMBEDDINGS_ENABLED=true")
        return VerifiedServingProfile(revision, None, None, None, None)
    if not any(value is not None for value in pins):
        return VerifiedServingProfile(revision, None, None, settings.embeddings_base_url, None)
    if build is None:
        raise RuntimeError("embedding attestation requires a verified service build manifest")
    model_sha, runtime_sha, info_url, base_url = pins
    if not _git_sha(model_sha):
        raise RuntimeError("MEMORY_EMBEDDINGS_MODEL_REVISION must be an immutable Git SHA")
    if not _git_sha(runtime_sha):
        raise RuntimeError("MEMORY_EMBEDDINGS_RUNTIME_BUILD_REVISION must be an immutable Git SHA")
    if not isinstance(info_url, str) or not isinstance(base_url, str):
        raise RuntimeError("embedding runtime info and inference URLs are required")
    probe = TeiProbe.create(
        model_id=settings.embeddings_model, model_sha=model_sha, build_sha=runtime_sha,
        inference_base_url=base_url, info_url=info_url,
    )
    observed = probe.verify()
    if settings.qdrant_hybrid_sparse_enabled:
        return VerifiedServingProfile(revision, None, None, observed.inference_base_url, probe)
    canonical: dict[str, Any] = {
        "dimensions": settings.embeddings_dimensions,
        "inference_base_url": observed.inference_base_url,
        "model": settings.embeddings_model,
        "model_sha": observed.model_sha,
        "provider": "tei-openai-compatible",
        "schema_version": "infinity-context.embedding-profile.v1",
        "tei_build_sha": observed.build_sha,
    }
    if settings.qdrant_enabled:
        canonical["vector_index"] = {
            "dense_vector_name": settings.qdrant_dense_vector_name,
            "distance_metric": "cosine",
        }
    encoded = json.dumps(canonical, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    model = _PROFILE_COMPONENT.sub("-", settings.embeddings_model.lower()).strip("-")
    profile_id = f"tei-{model}-{settings.embeddings_dimensions}d-dense.v1"
    return VerifiedServingProfile(
        revision, profile_id, f"sha256:{digest}", observed.inference_base_url, probe
    )


def _git_sha(value: object) -> bool:
    return isinstance(value, str) and _GIT_SHA.fullmatch(value) is not None
