from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from infinity_context_server.memory_comparison_mem0_contract import (
    evaluate_mem0_runtime_capabilities,
    public_mem0_runtime_manifest,
)
from infinity_context_server.memory_comparison_mem0_oss_contract import (
    evaluate_mem0_oss_runtime_capabilities,
    public_mem0_oss_runtime_manifest,
)
from infinity_context_server.memory_comparison_mem0_oss_manifest import (
    REVIEWED_MEM0_OSS_LOCK_SHA256,
    REVIEWED_MEM0_OSS_RUNTIME_PIN_SHA256,
    REVIEWED_MEM0_OSS_WRAPPER_SOURCE_REVISION,
    REVIEWED_MEM0_OSS_WRAPPER_SOURCE_SHA256,
)
from infinity_context_server.memory_comparison_mem0_oss_v4_manifest import (
    MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V4,
    MEM0_OSS_V4_CAPABILITIES,
    MEM0_OSS_V4_USAGE_EVIDENCE,
    REVIEWED_MEM0_OSS_V4_LOCK_SHA256,
    REVIEWED_MEM0_OSS_V4_RUNTIME_PIN_SHA256,
    REVIEWED_MEM0_OSS_V4_WRAPPER_SOURCE_REVISION,
    REVIEWED_MEM0_OSS_V4_WRAPPER_SOURCE_SHA256,
    mem0_oss_v4_runtime_manifest_sha256,
)
from test_memory_comparison_mem0_oss_contract import deep_copied_v3_capabilities


def test_v4_reviewed_exact_binding_constants_are_pinned() -> None:
    assert REVIEWED_MEM0_OSS_V4_WRAPPER_SOURCE_REVISION == (
        "6dcdb1339f7af7010bb027d8fdd881a726a4e824"
    )
    assert REVIEWED_MEM0_OSS_V4_WRAPPER_SOURCE_SHA256 == (
        "9109c2fdc554b86e213773aa40bd29816082199681dabb4ac3246b33ca5814fe"
    )
    assert REVIEWED_MEM0_OSS_V4_RUNTIME_PIN_SHA256 == (
        "075ec6cf7d5691fa388e2c413fa34e48cbf7cbb14b3b037fbc18fe9a8cf0d17c"
    )


def test_v3_reviewed_exact_binding_constants_are_unchanged() -> None:
    assert (
        REVIEWED_MEM0_OSS_WRAPPER_SOURCE_REVISION,
        REVIEWED_MEM0_OSS_WRAPPER_SOURCE_SHA256,
        REVIEWED_MEM0_OSS_RUNTIME_PIN_SHA256,
        REVIEWED_MEM0_OSS_LOCK_SHA256,
    ) == (
        "10a7572007055ac9791b35d571a7844a432fe862",
        "bc84ec6d608568cceb0aa23f92990018ddfba9e4cb8b575608a55d7dd1f58ba9",
        "efa3a315048f6c117d61295be42af0d9cc36ecb1b627d4456a31da0764754f5a",
        "70a54d810222b68f1f8b76f1fcf9c4332875f3fc242682fee3b5779db122f73d",
    )


def test_v4_exact_binding_matches_tracked_adapter_artifacts() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    adapter_root = repository_root / "benchmarks" / "mem0-oss-adapter"
    runtime_pin = json.loads((adapter_root / "runtime-pin.json").read_text(encoding="utf-8"))
    assert isinstance(runtime_pin, dict)

    assert runtime_pin["wrapper_source_revision"] == REVIEWED_MEM0_OSS_V4_WRAPPER_SOURCE_REVISION
    assert runtime_pin["wrapper_source_sha256"] == REVIEWED_MEM0_OSS_V4_WRAPPER_SOURCE_SHA256
    assert runtime_pin["runtime_lock_sha256"] == REVIEWED_MEM0_OSS_V4_LOCK_SHA256

    wrapper_digest = hashlib.sha256()
    wrapper_sources = sorted((adapter_root / "mem0_oss_adapter").glob("*.py"))
    assert wrapper_sources
    for source_path in wrapper_sources:
        wrapper_digest.update(source_path.name.encode())
        wrapper_digest.update(source_path.read_bytes())
    assert wrapper_digest.hexdigest() == REVIEWED_MEM0_OSS_V4_WRAPPER_SOURCE_SHA256

    assert _canonical_json_sha256(runtime_pin) == REVIEWED_MEM0_OSS_V4_RUNTIME_PIN_SHA256
    runtime_lock = json.loads((adapter_root / "runtime-lock.json").read_text(encoding="utf-8"))
    assert isinstance(runtime_lock, dict)
    assert _canonical_json_sha256(runtime_lock) == REVIEWED_MEM0_OSS_V4_LOCK_SHA256


def test_v4_profile_is_accepted_by_oss_and_generic_contract_dispatch() -> None:
    manifest = valid_v4_capabilities()

    assert evaluate_mem0_oss_runtime_capabilities(manifest, require_timestamp=True) == ()
    assert evaluate_mem0_runtime_capabilities(manifest, require_timestamp=True) == ()
    assert public_mem0_runtime_manifest(manifest) == public_mem0_oss_runtime_manifest(manifest)
    assert public_mem0_runtime_manifest(manifest)["extraction"]["usage_evidence"] == (
        MEM0_OSS_V4_USAGE_EVIDENCE
    )


def test_v4_rejects_a_resealed_usage_evidence_downgrade() -> None:
    manifest = valid_v4_capabilities()
    extraction = manifest["extraction"]
    assert isinstance(extraction, dict)
    usage_evidence = extraction["usage_evidence"]
    assert isinstance(usage_evidence, dict)
    usage_evidence["probe_token_required"] = False
    _seal_v4(manifest)

    assert "oss_v4_usage_evidence_invalid" in evaluate_mem0_oss_runtime_capabilities(
        manifest,
        require_timestamp=True,
    )


def test_v4_rejects_a_resealed_cross_version_provenance_tuple() -> None:
    manifest = valid_v4_capabilities()
    manifest["wrapper_source_revision"] = "10a7572007055ac9791b35d571a7844a432fe862"
    _seal_v4(manifest)

    public = public_mem0_runtime_manifest(manifest)

    assert "oss_v4_wrapper_source_revision_mismatch" in evaluate_mem0_runtime_capabilities(
        manifest,
        require_timestamp=True,
    )
    assert public["wrapper_source_revision"] == "invalid"


def valid_v4_capabilities() -> dict[str, object]:
    """Adapt the independently tested v3 fixture into the additive v4 shape."""

    manifest = deepcopy(deep_copied_v3_capabilities())
    manifest["schema_version"] = MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V4
    manifest["wrapper_source_revision"] = REVIEWED_MEM0_OSS_V4_WRAPPER_SOURCE_REVISION
    manifest["wrapper_source_sha256"] = REVIEWED_MEM0_OSS_V4_WRAPPER_SOURCE_SHA256
    manifest["capabilities"] = list(MEM0_OSS_V4_CAPABILITIES)
    extraction = manifest["extraction"]
    integrity = manifest["integrity"]
    assert isinstance(extraction, dict)
    assert isinstance(integrity, dict)
    extraction["usage_evidence"] = dict(MEM0_OSS_V4_USAGE_EVIDENCE)
    integrity["runtime_pin_sha256"] = REVIEWED_MEM0_OSS_V4_RUNTIME_PIN_SHA256
    integrity["lock_sha256"] = REVIEWED_MEM0_OSS_V4_LOCK_SHA256
    _seal_v4(manifest)
    return manifest


def _seal_v4(manifest: dict[str, object]) -> None:
    integrity = manifest["integrity"]
    assert isinstance(integrity, dict)
    checksum = mem0_oss_v4_runtime_manifest_sha256(manifest)
    assert checksum is not None
    integrity["manifest_sha256"] = checksum


def _canonical_json_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
