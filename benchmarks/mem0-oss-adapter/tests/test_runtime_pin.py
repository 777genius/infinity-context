from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from mem0_oss_adapter.embedding import verify_pinned_model_directory
from mem0_oss_adapter.manifest import capabilities_manifest, manifest_is_ready, seal_manifest
from mem0_oss_adapter.models import TimestampAttestation
from mem0_oss_adapter.runtime_lock import load_runtime_lock
from mem0_oss_adapter.runtime_pin import RUNTIME_PIN


def test_runtime_lock_is_exactly_bound_to_the_runtime_pin() -> None:
    root = Path(__file__).resolve().parents[1]
    runtime_lock = load_runtime_lock(root / "runtime-lock.json", pin=RUNTIME_PIN)

    assert len(runtime_lock.artifacts) == 57
    assert RUNTIME_PIN.mem0ai_version == "2.0.15"
    assert RUNTIME_PIN.fastembed_version == "0.8.0"
    assert RUNTIME_PIN.qdrant_client_version == "1.18.0"


def test_actual_fastembed_resolution_is_not_the_direct_baai_onnx_artifact() -> None:
    assert RUNTIME_PIN.embedding_source_repository == "qdrant/bge-small-en-v1.5-onnx-q"
    assert RUNTIME_PIN.embedding_model_revision == "52398278842ec682c6f32300af41344b1c0b0bb2"
    assert RUNTIME_PIN.embedding_onnx_sha256 != (
        "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35"
    )


def test_model_directory_rejects_a_direct_baai_artifact_mismatch(tmp_path: Path) -> None:
    for filename in (
        "config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.txt",
    ):
        (tmp_path / filename).write_text("{}")
    (tmp_path / "model_optimized.onnx").write_bytes(b"not-the-pinned-onnx")

    with pytest.raises(RuntimeError, match="does not match runtime pin"):
        verify_pinned_model_directory(tmp_path)


def test_runtime_pin_has_no_endpoint_or_secret_fields() -> None:
    payload = json.loads((Path(__file__).resolve().parents[1] / "runtime-pin.json").read_text())

    assert not {"url", "token", "secret", "endpoint"}.intersection(payload)


def test_manifest_readiness_rejects_a_zero_or_mismatched_wrapper_hash() -> None:
    manifest = capabilities_manifest(
        configured=True,
        extraction_mode="raw_passthrough",
        timestamp_attestation=TimestampAttestation(
            status="passed",
            checked_at="2026-08-04T12:34:56Z",
            metadata_created_at_roundtrip_attested=True,
            cleanup_succeeded=True,
        ),
        source_identity_attested=True,
    )
    assert manifest_is_ready(manifest) is True

    for replacement in ("0" * 64, "f" * 64):
        mutated = deepcopy(manifest)
        mutated["wrapper_source_sha256"] = replacement
        mutated = seal_manifest(mutated)
        assert manifest_is_ready(mutated) is False
