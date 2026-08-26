from __future__ import annotations

import ast
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest
from infinity_context_core.ports.managed_cleanup_v3_contracts import PROFILE_ORACLES
from infinity_context_core.ports.original_pair_identity_authority import (
    LONGMEMEVAL_OMITTED_ORIGINAL_PAIR_IDENTITY_ROOT_SHA256,
)
from infinity_context_server.memory_comparison_full_profiles import (
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    build_managed_public_run_projection,
)
from infinity_context_server.memory_comparison_managed_v5_cleanup_v4_projector import (
    ManagedV5CleanupV4OperationProjector,
    ManagedV5CleanupV4ProjectionError,
    _pair_authority_valid,
    managed_v5_a1_operation_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import canonical_sha256
from infinity_context_server.original_pair_identity_authority import (
    SQLiteOriginalPairIdentityAuthority,
)

ADMISSION = "a" * 64
PROJECTOR_MODULE = (
    Path(__file__).parents[2]
    / "packages/infinity_context_server/infinity_context_server"
    / "memory_comparison_managed_v5_cleanup_v4_projector.py"
)


class _PairAuthority:
    profile_id = "mem0-longmemeval-top50-v1"
    dataset_sha256 = PROFILE_ORACLES[profile_id]["dataset_sha256"]
    operation_count = PROFILE_ORACLES[profile_id]["operation_count"]
    original_pair_slot_count = PROFILE_ORACLES[profile_id]["original_pair_slot_count"]
    omitted_source_identity_count = PROFILE_ORACLES[profile_id]["omitted_source_identity_count"]
    omitted_source_identity_root_sha256 = PROFILE_ORACLES[profile_id][
        "omitted_source_identity_root_sha256"
    ]
    omitted_original_pair_identity_root_sha256 = (
        LONGMEMEVAL_OMITTED_ORIGINAL_PAIR_IDENTITY_ROOT_SHA256
    )
    original_pair_slot_root_sha256 = "6" * 64
    ordered_mapping_root_sha256 = "7" * 64
    terminal_commitment_sha256 = "8" * 64

    def lookup(self, *, sequence: int, corpus_id: str, normalized_source_id: str) -> str:
        del sequence, corpus_id, normalized_source_id
        return "9" * 64


def _targets() -> tuple[FullComparisonBackendTarget, ...]:
    return (
        FullComparisonBackendTarget("infinity-context", "4" * 64),
        FullComparisonBackendTarget("mem0", "5" * 64),
    )


def _official_path(env_name: str, fallback: str) -> Path:
    path = Path(os.environ.get(env_name, fallback))
    if not path.is_file():
        pytest.skip(f"{env_name} official dataset is not staged")
    return path


@lru_cache(maxsize=2)
def _material(profile_id: str, path_value: str):
    path = Path(path_value)
    profile = resolve_full_comparison_profile(profile_id)
    assert profile is not None
    projection = build_managed_public_run_projection(
        run_id="cleanup-v4-projector-test",
        run_nonce_commitment_sha256="1" * 64,
        runtime_probe_nonce_sha256="2" * 64,
        profile=profile,
        dataset_bytes=path.read_bytes(),
        backend_targets=_targets(),
        scope="full",
    )
    manifest = ManagedMem0V5ManifestProjector().project(projection.cases, current_date="2026-08-09")
    return projection, manifest


def test_a1_operation_identity_is_exact_production_formula() -> None:
    assert managed_v5_a1_operation_sha256(
        admission_commitment_sha256=ADMISSION,
        unit_index=17,
        unit_identity_sha256="b" * 64,
    ) == canonical_sha256(
        {
            "admission_commitment_sha256": ADMISSION,
            "unit_index": 17,
            "unit_identity_sha256": "b" * 64,
        }
    )


def test_a1_stream_uses_manifest_units_without_full_operation_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _official_path(
        "MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET",
        "/tmp/locomo10.ingestion-manifest-r1.json",
    )
    projection, manifest = _material("mem0-locomo-top50-v1", str(path))
    projector = ManagedV5CleanupV4OperationProjector(
        projection=projection,
        manifest_authority=manifest,
        admission_commitment_sha256=ADMISSION,
        profile_id="mem0-locomo-top50-v1",
    )

    def forbidden_full_materialization(_self):
        raise AssertionError("A1 rebuilt full Infinity operation material")

    monkeypatch.setattr(
        ManagedV5CleanupV4OperationProjector,
        "_iterate",
        forbidden_full_materialization,
    )

    observed = tuple(projector.iter_a1_operation_sha256())
    expected = tuple(
        managed_v5_a1_operation_sha256(
            admission_commitment_sha256=ADMISSION,
            unit_index=sequence,
            unit_identity_sha256=unit.unit_identity_sha256,
        )
        for sequence, unit in enumerate(manifest.units)
    )
    assert observed == expected


def test_strict_v4_projector_import_graph_excludes_legacy_materializing_projection() -> None:
    tree = ast.parse(PROJECTOR_MODULE.read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "infinity_context_server.memory_comparison_managed_v5_operation_material" in imports
    assert (
        "infinity_context_server.memory_comparison_managed_v5_infinity_cleanup_projection"
        not in imports
    )
    script = r"""
import sys

class Trap:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.endswith("memory_comparison_managed_v5_infinity_cleanup_projection"):
            raise RuntimeError(fullname)
        return None

sys.meta_path.insert(0, Trap())
import infinity_context_server.memory_comparison_managed_v5_cleanup_v4_projector
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("omitted_source_identity_count", True),
        ("operation_count", True),
        ("original_pair_slot_count", True),
        ("omitted_original_pair_identity_root_sha256", "f" * 64),
    ),
)
def test_pair_authority_rejects_non_exact_scalars_and_omitted_root(
    field: str, value: object
) -> None:
    authority = _PairAuthority()
    setattr(authority, field, value)
    assert not _pair_authority_valid(authority, PROFILE_ORACLES["mem0-longmemeval-top50-v1"])


def test_full_official_locomo_streams_exact_5882_operations() -> None:
    path = _official_path(
        "MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET",
        "/tmp/locomo10.ingestion-manifest-r1.json",
    )
    projection, manifest = _material(
        "mem0-locomo-top50-v1",
        str(path),
    )
    projector = ManagedV5CleanupV4OperationProjector(
        projection=projection,
        manifest_authority=manifest,
        admission_commitment_sha256=ADMISSION,
        profile_id="mem0-locomo-top50-v1",
    )
    first_iterator = projector.iter_operations()
    assert iter(first_iterator) is first_iterator
    count = valid_messages = 0
    corpora: set[str] = set()
    for operation in first_iterator:
        assert operation.sequence == count
        assert operation.lane == "fact"
        assert operation.original_pair_identity_sha256 is None
        assert len(operation.ordered_source_ref_descriptor_sha256) == 1
        assert operation.ordered_fragment_descriptor_sha256 == ()
        assert operation.a1_operation_sha256 == managed_v5_a1_operation_sha256(
            admission_commitment_sha256=ADMISSION,
            unit_index=count,
            unit_identity_sha256=manifest.units[count].unit_identity_sha256,
        )
        corpora.add(operation.corpus_identity_sha256)
        valid_messages += operation.valid_message_count
        count += 1
    oracle = PROFILE_ORACLES["mem0-locomo-top50-v1"]
    assert count == oracle["operation_count"] == 5_882
    assert valid_messages == oracle["valid_message_count"] == 5_882
    assert len(corpora) == oracle["corpus_count"] == 10
    assert projector.iter_operations() is not first_iterator


def test_longmemeval_rejects_missing_original_pair_authority_before_iteration() -> None:
    path = _official_path(
        "MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET",
        "/tmp/infinity_context_longmemeval_s_cleaned.json",
    )
    projection, manifest = _material(
        "mem0-longmemeval-top50-v1",
        str(path),
    )
    with pytest.raises(
        ManagedV5CleanupV4ProjectionError,
        match="pair_authority_invalid",
    ):
        ManagedV5CleanupV4OperationProjector(
            projection=projection,
            manifest_authority=manifest,
            admission_commitment_sha256=ADMISSION,
            profile_id="mem0-longmemeval-top50-v1",
        )


def test_full_official_longmemeval_streams_exact_124344_operations(tmp_path: Path) -> None:
    path = _official_path(
        "MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET",
        "/tmp/infinity_context_longmemeval_s_cleaned.json",
    )
    projection, manifest = _material("mem0-longmemeval-top50-v1", str(path))
    pair_authority = SQLiteOriginalPairIdentityAuthority.create(
        tmp_path / "original-pairs.sqlite3",
        dataset_bytes=path.read_bytes(),
        authentication_key=b"cleanup-v4-projector-test-key" * 2,
    )
    try:
        projector = ManagedV5CleanupV4OperationProjector(
            projection=projection,
            manifest_authority=manifest,
            admission_commitment_sha256=ADMISSION,
            profile_id="mem0-longmemeval-top50-v1",
            original_pair_authority=pair_authority,
        )
        count = valid_messages = fragments = source_refs = 0
        corpora: set[str] = set()
        for operation in projector.iter_operations():
            assert operation.sequence == count
            assert operation.lane == "document"
            assert operation.original_pair_identity_sha256 is not None
            assert len(operation.ordered_source_ref_descriptor_sha256) == (
                operation.valid_message_count + 2
            )
            assert operation.ordered_fragment_descriptor_sha256
            corpora.add(operation.corpus_identity_sha256)
            valid_messages += operation.valid_message_count
            fragments += len(operation.ordered_fragment_descriptor_sha256)
            source_refs += len(operation.ordered_source_ref_descriptor_sha256)
            count += 1
        oracle = PROFILE_ORACLES["mem0-longmemeval-top50-v1"]
        assert count == oracle["operation_count"] == 124_344
        assert valid_messages == oracle["valid_message_count"] == 246_738
        assert fragments == oracle["fragment_count"] == 366_440
        assert source_refs == oracle["document_source_ref_count"] == 495_426
        assert len(corpora) == oracle["corpus_count"] == 500
    finally:
        pair_authority.close()
