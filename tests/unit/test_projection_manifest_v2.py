from __future__ import annotations

import hashlib
import json

import pytest
from infinity_context_core.application import validate_projection_manifest
from infinity_context_core.application.use_cases.benchmark_runs import (
    BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256,
)
from infinity_context_core.domain.errors import MemoryValidationError

RUN = "a" * 64
BINDING = "b" * 64
TARGET = "c" * 64
SPACE = "space-1"


def test_v1_manifest_remains_byte_compatible_and_rejects_episode_field() -> None:
    manifest = _manifest("memory-comparison-projection-manifest.v1", episode_ids=None)
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"))

    assert (
        validate_projection_manifest(
            manifest,
            hashlib.sha256(encoded.encode()).hexdigest(),
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            infinity_target_identity_sha256=TARGET,
            space_id=SPACE,
        )
        == manifest
    )
    assert "episode_ids" not in encoded

    manifest["scopes"][0]["episode_ids"] = ["episode-1"]
    with pytest.raises(MemoryValidationError, match="scope is invalid"):
        _validate(manifest)


def test_v2_accepts_exact_sorted_episode_inventory() -> None:
    manifest = _manifest(
        "memory-comparison-projection-manifest.v2",
        episode_ids=["episode-1", "episode-2"],
    )

    assert _validate(manifest) == manifest


def test_v2_accepts_threadless_scope_with_empty_episode_inventory() -> None:
    manifest = _manifest("memory-comparison-projection-manifest.v2", episode_ids=[])
    manifest["scopes"][0]["thread_id"] = None

    assert _validate(manifest) == manifest


def test_v2_rejects_threadless_scope_with_episode_inventory() -> None:
    manifest = _manifest(
        "memory-comparison-projection-manifest.v2",
        episode_ids=["episode-1"],
    )
    manifest["scopes"][0]["thread_id"] = None

    with pytest.raises(MemoryValidationError, match="episode scope is invalid"):
        _validate(manifest)


@pytest.mark.parametrize(
    "episode_ids",
    [
        ["episode-2", "episode-1"],
        ["episode-1", "episode-1"],
    ],
)
def test_v2_rejects_noncanonical_episode_order_or_duplicates(
    episode_ids: list[str],
) -> None:
    with pytest.raises(MemoryValidationError, match="not sorted and unique"):
        _validate(
            _manifest(
                "memory-comparison-projection-manifest.v2",
                episode_ids=episode_ids,
            )
        )


def test_v2_rejects_cross_scope_duplicate_episode_id() -> None:
    manifest = _manifest(
        "memory-comparison-projection-manifest.v2",
        episode_ids=["episode-1"],
    )
    second = dict(manifest["scopes"][0])
    second["memory_scope_id"] = "scope-2"
    second["thread_id"] = "thread-2"
    manifest["scopes"].append(second)

    with pytest.raises(MemoryValidationError, match="globally unique"):
        _validate(manifest)


@pytest.mark.parametrize("field_name", ["chunk_ids", "fact_ids", "document_ids"])
def test_v2_rejects_episode_id_colliding_with_other_canonical_kind(
    field_name: str,
) -> None:
    manifest = _manifest(
        "memory-comparison-projection-manifest.v2",
        episode_ids=["canonical-1"],
    )
    manifest["scopes"][0][field_name] = ["canonical-1"]
    if field_name == "chunk_ids":
        manifest["scopes"][0]["qdrant"] = {
            "target_commitment_sha256": "1" * 64,
            "manifest_binding_sha256": "2" * 64,
        }
    elif field_name == "fact_ids":
        manifest["scopes"][0]["graphiti"] = {
            "target_commitment_sha256": "3" * 64,
            "manifest_binding_sha256": "4" * 64,
            "episode_ids": ["provider-episode-1"],
            "entity_ids": ["provider-entity-1"],
            "mentions_edge_ids": ["provider-mentions-1"],
            "relates_to_edge_ids": ["provider-relates-1"],
        }

    with pytest.raises(MemoryValidationError, match="globally unique"):
        _validate(manifest)


def _validate(manifest: dict[str, object]) -> dict[str, object]:
    digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return validate_projection_manifest(
        manifest,
        digest,
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_id=SPACE,
    )


def _manifest(schema_version: str, *, episode_ids: list[str] | None) -> dict[str, object]:
    scope: dict[str, object] = {
        "memory_scope_id": "scope-1",
        "thread_id": "thread-1",
        "chunk_ids": ["chunk-1"],
        "fact_ids": [],
        "document_ids": [],
        "qdrant": {
            "target_commitment_sha256": "1" * 64,
            "manifest_binding_sha256": "2" * 64,
        },
        "graphiti": None,
        "cognee": {
            "disposition": "not_projected",
            "policy_sha256": BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256,
        },
    }
    if episode_ids is not None:
        scope["episode_ids"] = episode_ids
    return {
        "schema_version": schema_version,
        "run_id_sha256": RUN,
        "binding_commitment_sha256": BINDING,
        "infinity_target_identity_sha256": TARGET,
        "space_id": SPACE,
        "scopes": [scope],
    }
