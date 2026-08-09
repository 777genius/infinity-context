from __future__ import annotations

# ruff: noqa: E402 - the pinned adapter package is an explicit test-only path.
import hashlib
import importlib
import shutil
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER_ROOT = ROOT / "benchmarks" / "mem0-oss-adapter-v5"
sys.path.insert(0, str(ADAPTER_ROOT))

from infinity_context_server import memory_comparison_managed_v5_live_config as config_subject
from infinity_context_server import (
    memory_comparison_managed_v5_live_public_composition as subject,
)
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonBackendTarget,
    create_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
    ManagedMem0V5Preflight,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_contract_binding import (
    REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SHA256,
    ManagedMem0V5ExtractionContractBinding,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_projection import (
    MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256,
    MEM0_V5_EXTRACTION_SCHEMA_SHA256,
    MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    ManagedPublicRunProjection,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_v5_live_config import (
    ManagedV5LiveConfig,
    ManagedV5LiveFilesystemConfig,
    ManagedV5LiveRuntimeAuthority,
    ManagedV5LiveRuntimeConfig,
)
from infinity_context_server.memory_comparison_managed_v5_phase_c_preload import (
    PhaseCPreloadValidationError,
    ReviewedPhaseCPreloadValidator,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionReceiptAuthority,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
)


def _sha(value: object) -> str:
    raw = value if type(value) is bytes else str(value).encode()
    return hashlib.sha256(raw).hexdigest()


def _extraction_binding(tmp_path: Path) -> ManagedMem0V5ExtractionContractBinding:
    reviewed_file = tmp_path / "reviewed-extraction-contract.py"
    reviewed_file.write_bytes(
        (
            ROOT
            / "benchmarks"
            / "mem0-oss-adapter-v5"
            / "mem0_oss_adapter_v5"
            / "extraction_contract.py"
        ).read_bytes()
    )
    reviewed_file.chmod(0o444)
    return ManagedMem0V5ExtractionContractBinding(
        reviewed_file.resolve(),
        REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SHA256,
    )


def _case(index: int) -> ManagedRunCase:
    corpus_id = f"locomo-corpus-{str(index) * 64}"
    record = {
        "schema_version": "memory-comparison-managed-corpus.v2",
        "benchmark": "locomo",
        "corpus_id": corpus_id,
        "thread_id": f"locomo-thread-{str(index + 2) * 64}",
        "memories": [
            {
                "kind": "fact",
                "role": "user",
                "session_alias": "session-0001",
                "source_alias": "memory-000001",
                "speaker": "Alice",
                "session_date": f"2024-03-{10 + index:02d}",
                "text": f"Alice fact {index}.",
                "timestamp": index + 1,
            }
        ],
        "documents": [],
        "conversations": [],
    }
    return ManagedRunCase(f"case-{index}", corpus_id, record)


def _projection():
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    cases = (_case(1), _case(2))
    targets = (
        FullComparisonBackendTarget("infinity-context", _sha("infinity")),
        FullComparisonBackendTarget("mem0", _sha("mem0")),
    )
    bindings = create_full_comparison_run_bindings(
        run_id="live-v5-test",
        run_nonce_commitment_sha256=_sha("nonce"),
        runtime_probe_nonce_sha256=_sha("probe"),
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset_sha256=_sha("dataset"),
        selection_fingerprint_sha256=_sha("selection"),
        backend_targets=targets,
        scope="canary",
    )
    return profile, ManagedPublicRunProjection(cases, bindings)


def _runtime_authority() -> ManagedV5LiveRuntimeAuthority:
    return ManagedV5LiveRuntimeAuthority(
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        service_tier="priority",
        runtime_source_revision="reviewed-runtime-r1",
        runtime_source_sha256=_sha("reviewed-runtime-r1"),
        runtime_base_sha256=_sha("runtime-base"),
        route_binding_sha256=_sha("http://127.0.0.1:8890/v1"),
        base_instructions_sha256=SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
        extraction_system_prompt_sha256=MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256,
        account_binding_hmac_sha256=_sha("account"),
        response_format_type="json_schema",
        response_format_sha256=config_subject._RUNTIME_RESPONSE_FORMAT_SHA256,
        response_schema_sha256=config_subject._RUNTIME_RESPONSE_SCHEMA_SHA256,
        extraction_response_format_sha256=MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256,
        extraction_response_schema_sha256=MEM0_V5_EXTRACTION_SCHEMA_SHA256,
        requested_output_tokens=4096,
    )


def _config(tmp_path: Path) -> ManagedV5LiveConfig:
    state = tmp_path / "state"
    secrets = tmp_path / "secrets"
    reports = tmp_path / "reports"
    for root in (state, secrets, reports):
        root.mkdir(mode=0o700)
    filesystem = ManagedV5LiveFilesystemConfig(
        state_root=state,
        secret_root=secrets,
        report_root=reports,
        report_file=reports / "report.json",
        dispatch_journal=state / "dispatch.json",
        operation_journal=state / "operation-journal.json",
        durable_clean_state=state / "durable-clean-state.json",
        recovery_journal=state / "recovery-journal.json",
        ingress_bearer_file=secrets / "bearer",
        evidence_key_file=secrets / "evidence",
        evidence_key_sha256=_sha("evidence"),
        receipt_secret_file=secrets / "receipt",
        checkpoint_signing_key_file=secrets / "signing",
        checkpoint_head_key_file=secrets / "head",
        operation_journal_signer_secret_file=secrets / "journal-signer",
        durable_clean_state_hmac_secret_file=secrets / "clean-state-hmac",
        runtime_attestation_secret_file=secrets / "runtime-attestation",
        recovery_hmac_secret_file=secrets / "recovery-hmac",
        runtime_attestation_secret_sha256=_sha("runtime-attestation"),
        runtime_authority_file=tmp_path / "runtime-authority.json",
        runtime_authority_sha256=_sha("authority"),
        phase_c_package_root=tmp_path / "phase-c",
        runtime_repo=tmp_path / "runtime" / "repo",
        runtime_artifact_manifest=tmp_path / "runtime" / "artifact-manifest.json",
        runtime_artifact_manifest_sha256=_sha("artifact"),
        node_executable=Path("/usr/local/bin/node"),
        node_executable_sha256=_sha("node"),
        adapter_runtime_pin_file=tmp_path / "adapter-runtime-pin.json",
        adapter_runtime_pin_sha256=_sha("adapter-runtime-pin"),
        recovery_report_file=reports / "recovery-report.json",
    )
    return ManagedV5LiveConfig(
        filesystem=filesystem,
        runtime=ManagedV5LiveRuntimeConfig(mem0_adapter_origin="http://127.0.0.1:19091"),
    )


def _install_public_seams(
    monkeypatch: pytest.MonkeyPatch,
    authority: ManagedV5LiveRuntimeAuthority,
) -> None:
    binding = SimpleNamespace(
        runtime_source_sha256=authority.runtime_source_sha256,
        route_binding_sha256=authority.route_binding_sha256,
    )
    monkeypatch.setattr(subject, "validate_managed_v5_live_public_config", lambda _c: authority)
    monkeypatch.setattr(subject, "_compose_phase_c_boundary", lambda *_v: (binding, object()))

    def preflight(**values: object) -> ManagedMem0V5Preflight:
        manifest = ManagedMem0V5ManifestProjector().project(
            values["cases"], current_date=values["current_date"]
        )
        request = values["request"]
        return ManagedMem0V5Preflight(
            manifest,
            Mem0OssFullRunAdmission(
                request=request,
                ingestion_manifest_sha256=manifest.ingestion_manifest_sha256,
                ingestion_root_sha256=manifest.ingestion_root_sha256,
                ingestion_unit_count=manifest.operation_count,
            ),
        )

    monkeypatch.setattr(subject, "preflight_managed_mem0_v5", preflight)


def _compose(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    profile, projection = _projection()
    authority = _runtime_authority()
    config = _config(tmp_path)
    _install_public_seams(monkeypatch, authority)
    return subject.compose_managed_v5_live_public_inputs(
        projection=projection,
        profile=profile,
        deadline=datetime.now(UTC) + timedelta(minutes=10),
        current_date="2026-08-08",
        extraction_contract_binding=_extraction_binding(tmp_path),
        operator_extraction_token_ceiling=1_000_000,
        operator_total_token_ceiling=2_000_000,
        runtime_authority=authority,
        config=config,
        timeout_seconds=5.0,
    )


def test_multi_unit_order_and_request_hashes_match_pinned_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip(
        "mem0",
        reason="pinned mem0ai is required only for exact upstream parity",
    )
    from mem0_oss_adapter_v5.extraction_contract import build_extraction_request

    result = _compose(tmp_path, monkeypatch)
    assert result.extraction_token_budget.operation_count == len(result.manifest_authority.units)
    assert result.extraction_token_budget.aggregate_request_body_bytes > 0
    assert result.inputs.extraction_token_budget == result.extraction_token_budget
    operations = result.inputs.receipt_authority.operations
    expected = tuple(
        build_extraction_request(
            source_messages=tuple(message.payload() for message in unit.source_messages),
            current_date=result.inputs.current_date,
            timestamp=unit.observation_date,
        ).request_body_sha256
        for unit in result.manifest_authority.units
    )
    assert len(operations) == 2
    assert tuple(item.sequence for item in operations) == (0, 1)
    assert tuple(item.unit_identity_sha256 for item in operations) == tuple(
        item.unit_identity_sha256 for item in result.manifest_authority.units
    )
    assert tuple(item.request_body_sha256 for item in operations) == expected
    assert result.inputs.receipt_authority.base_instructions_sha256 == (
        SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256
    )
    assert result.inputs.receipt_authority.base_instructions_sha256 != (
        MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256
    )
    assert result.inputs.receipt_authority.response_format_sha256 == (
        MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256
    )
    assert result.inputs.receipt_authority.response_schema_sha256 == (
        MEM0_V5_EXTRACTION_SCHEMA_SHA256
    )
    assert result.inputs.receipt_authority.response_format_sha256 != (
        config_subject._RUNTIME_RESPONSE_FORMAT_SHA256
    )
    assert result.inputs.receipt_authority.response_schema_sha256 != (
        config_subject._RUNTIME_RESPONSE_SCHEMA_SHA256
    )
    assert not hasattr(result.inputs, "dispatch_guard")


def test_runtime_authority_cross_wire_fails_before_adapter_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile, projection = _projection()
    authority = _runtime_authority()
    config = _config(tmp_path)
    monkeypatch.setattr(
        subject,
        "validate_managed_v5_live_public_config",
        lambda _config: replace(authority, account_binding_hmac_sha256=_sha("foreign")),
    )
    with pytest.raises(
        subject.ManagedV5LivePublicCompositionError,
        match="managed_v5_live_runtime_authority_cross_wire",
    ):
        subject.compose_managed_v5_live_public_inputs(
            projection=projection,
            profile=profile,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            current_date="2026-08-08",
            extraction_contract_binding=_extraction_binding(tmp_path),
            operator_extraction_token_ceiling=1_000_000,
            operator_total_token_ceiling=2_000_000,
            runtime_authority=authority,
            config=config,
            timeout_seconds=5.0,
        )


@pytest.mark.parametrize(
    "field",
    (
        "extraction_system_prompt_sha256",
        "extraction_response_format_sha256",
        "extraction_response_schema_sha256",
    ),
)
def test_extraction_authority_tamper_fails_before_adapter_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    profile, projection = _projection()
    authority = _runtime_authority()
    object.__setattr__(authority, field, _sha(f"tampered-{field}"))
    _install_public_seams(monkeypatch, authority)
    with pytest.raises(subject.ManagedV5LivePublicCompositionError) as captured:
        subject.compose_managed_v5_live_public_inputs(
            projection=projection,
            profile=profile,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            current_date="2026-08-08",
            extraction_contract_binding=_extraction_binding(tmp_path),
            operator_extraction_token_ceiling=1_000_000,
            operator_total_token_ceiling=2_000_000,
            runtime_authority=authority,
            config=_config(tmp_path),
            timeout_seconds=5.0,
        )
    assert captured.value.code == "managed_v5_live_extraction_authority_cross_wire"


def test_tampered_extraction_binding_fails_before_public_config_or_phase_c(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile, projection = _projection()
    authority = _runtime_authority()
    binding = _extraction_binding(tmp_path)
    object.__setattr__(binding, "implementation_sha256", _sha("tampered-native"))
    monkeypatch.setattr(
        subject,
        "validate_managed_v5_live_public_config",
        lambda _config: pytest.fail("public config ran after extraction binding rejection"),
    )
    monkeypatch.setattr(
        subject,
        "_compose_phase_c_boundary",
        lambda *_values: pytest.fail("Phase C ran after extraction binding rejection"),
    )
    with pytest.raises(subject.ManagedV5LivePublicCompositionError) as captured:
        subject.compose_managed_v5_live_public_inputs(
            projection=projection,
            profile=profile,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            current_date="2026-08-08",
            extraction_contract_binding=binding,
            operator_extraction_token_ceiling=1_000_000,
            operator_total_token_ceiling=2_000_000,
            runtime_authority=authority,
            config=_config(tmp_path),
            timeout_seconds=5.0,
        )
    assert captured.value.code == "managed_v5_live_public_composition_inputs_invalid"


def test_receipt_authority_rejects_multi_unit_reordering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _compose(tmp_path, monkeypatch)
    receipt = result.inputs.receipt_authority
    assert type(receipt) is Mem0V5ObservedExtractionReceiptAuthority
    with pytest.raises(Exception, match="mem0_v5_http_configuration_invalid"):
        replace(receipt, operations=tuple(reversed(receipt.operations)))


def test_foreign_preloaded_phase_c_module_is_rejected_after_tree_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile, projection = _projection()
    authority = _runtime_authority()
    config = _config(tmp_path)
    validation_calls = 0

    def tracked_validation(_config: object) -> object:
        nonlocal validation_calls
        validation_calls += 1
        return authority

    phase_root = ROOT / "benchmarks" / "phase-c-canary"
    config = replace(
        config,
        filesystem=replace(config.filesystem, phase_c_package_root=phase_root),
    )
    monkeypatch.setattr(subject, "validate_managed_v5_live_public_config", tracked_validation)
    monkeypatch.setitem(sys.modules, "phase_c_canary", ModuleType("phase_c_canary"))
    with pytest.raises(subject.ManagedV5LivePublicCompositionError) as captured:
        subject.compose_managed_v5_live_public_inputs(
            projection=projection,
            profile=profile,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            current_date="2026-08-08",
            extraction_contract_binding=_extraction_binding(tmp_path),
            operator_extraction_token_ceiling=1_000_000,
            operator_total_token_ceiling=2_000_000,
            runtime_authority=authority,
            config=config,
            timeout_seconds=5.0,
        )
    assert captured.value.code == "managed_v5_live_phase_c_authority_invalid"
    assert validation_calls == 1


def test_exact_preloaded_phase_c_modules_pass_source_api_fingerprints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    phase_root = tmp_path / "phase-c"
    shutil.copytree(
        ROOT / "benchmarks" / "phase-c-canary" / "phase_c_canary",
        phase_root / "phase_c_canary",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    for name in tuple(sys.modules):
        if name == "phase_c_canary" or name.startswith("phase_c_canary."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.syspath_prepend(str(phase_root))
    try:
        importlib.import_module("phase_c_canary.runtime_receipt_v2")
        binding_module = importlib.import_module("phase_c_canary.runtime_binding")
        tree = config_subject._validate_reviewed_phase_c_python_tree(
            phase_root,
            config_subject._REVIEWED_PHASE_C_PYTHON_TREE_SHA256,
        )
        snapshot = ReviewedPhaseCPreloadValidator().validate(phase_root, tree)
        assert snapshot
        assert snapshot[0][0] == "phase_c_canary"
        service = binding_module.RuntimeBindingComposition.compose_phase_c_canary()
        assert type(service) is binding_module.PinnedRuntimeBindingService
        # Issuance validates a deployment-only artifact path. This portable test
        # covers source/API fingerprints and legitimate service registration.
        assert ReviewedPhaseCPreloadValidator().validate(phase_root, tree) == snapshot
    finally:
        for name in tuple(sys.modules):
            if name == "phase_c_canary" or name.startswith("phase_c_canary."):
                sys.modules.pop(name, None)


def test_phase_c_import_path_is_restored_when_import_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    phase_root = tmp_path / "phase-c"
    shutil.copytree(
        ROOT / "benchmarks" / "phase-c-canary" / "phase_c_canary",
        phase_root / "phase_c_canary",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for name in tuple(sys.modules):
        if name == "phase_c_canary" or name.startswith("phase_c_canary."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.syspath_prepend(str(phase_root))
    before = tuple(sys.path)
    calls = 0

    def reject_import(_name: str) -> object:
        nonlocal calls
        calls += 1
        assert sys.path[0] == str(phase_root)
        raise RuntimeError("import blocked")

    monkeypatch.setattr(subject.importlib, "import_module", reject_import)
    base_config = _config(tmp_path)
    config = replace(
        base_config,
        filesystem=replace(
            base_config.filesystem,
            phase_c_package_root=phase_root,
        ),
    )
    with pytest.raises(subject.ManagedV5LivePublicCompositionError) as captured:
        subject._compose_phase_c_boundary(config, _runtime_authority())

    assert captured.value.code == "managed_v5_live_phase_c_authority_invalid"
    assert calls == 1
    assert tuple(sys.path) == before


def test_tampered_preloaded_phase_c_api_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    phase_root = tmp_path / "phase-c"
    shutil.copytree(
        ROOT / "benchmarks" / "phase-c-canary" / "phase_c_canary",
        phase_root / "phase_c_canary",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    for name in tuple(sys.modules):
        if name == "phase_c_canary" or name.startswith("phase_c_canary."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.syspath_prepend(str(phase_root))
    try:
        authority_module = importlib.import_module("phase_c_canary.authority")
        tree = config_subject._validate_reviewed_phase_c_python_tree(
            phase_root,
            config_subject._REVIEWED_PHASE_C_PYTHON_TREE_SHA256,
        )
        monkeypatch.setattr(authority_module, "immutable_authority", lambda: None)
        with pytest.raises(PhaseCPreloadValidationError, match="phase_c_module_api_invalid"):
            ReviewedPhaseCPreloadValidator().validate(phase_root, tree)
    finally:
        for name in tuple(sys.modules):
            if name == "phase_c_canary" or name.startswith("phase_c_canary."):
                sys.modules.pop(name, None)


def test_malicious_phase_c_init_is_not_executed_when_tree_hash_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile, projection = _projection()
    authority = _runtime_authority()
    config = _config(tmp_path)
    phase_root = tmp_path / "reviewed-phase-c"
    shutil.copytree(
        ROOT / "benchmarks" / "phase-c-canary" / "phase_c_canary",
        phase_root / "phase_c_canary",
    )
    sentinel = tmp_path / "malicious-init-executed"
    (phase_root / "phase_c_canary" / "__init__.py").write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\n"
    )
    config = replace(
        config,
        filesystem=replace(config.filesystem, phase_c_package_root=phase_root),
    )

    def validate_tree_before_return(_config: ManagedV5LiveConfig) -> object:
        config_subject._validate_reviewed_phase_c_python_tree(
            phase_root,
            config_subject._REVIEWED_PHASE_C_PYTHON_TREE_SHA256,
        )
        return authority

    monkeypatch.setattr(
        subject, "validate_managed_v5_live_public_config", validate_tree_before_return
    )
    with pytest.raises(subject.ManagedV5LivePublicCompositionError) as captured:
        subject.compose_managed_v5_live_public_inputs(
            projection=projection,
            profile=profile,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            current_date="2026-08-08",
            extraction_contract_binding=_extraction_binding(tmp_path),
            operator_extraction_token_ceiling=1_000_000,
            operator_total_token_ceiling=2_000_000,
            runtime_authority=authority,
            config=config,
            timeout_seconds=5.0,
        )
    assert captured.value.code == "managed_v5_live_public_config_invalid"
    assert not sentinel.exists()
