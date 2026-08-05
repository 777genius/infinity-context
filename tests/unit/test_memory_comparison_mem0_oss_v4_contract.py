from __future__ import annotations

from copy import deepcopy

from infinity_context_server.memory_comparison_mem0_contract import (
    evaluate_mem0_runtime_capabilities,
    public_mem0_runtime_manifest,
)
from infinity_context_server.memory_comparison_mem0_oss_contract import (
    evaluate_mem0_oss_runtime_capabilities,
    public_mem0_oss_runtime_manifest,
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
