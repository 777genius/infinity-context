from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase

from scripts import mem0_v5_live_micro_canary as subject
from scripts.mem0_v5_live_container_copy_contract import (
    ADAPTER_SECRET_NAMES,
    validate_private_credentials,
    verify_container_copy_authority,
)
from scripts.mem0_v5_live_micro_canary import (
    LiveRuntimeAuthority,
    MicroCanaryInputs,
    execute_micro_canary,
)
from scripts.mem0_v5_live_project_one_unit import (
    OneUnitProjection,
    materialize_projection,
    project_one_unit,
)

ROOT = Path(__file__).resolve().parents[2]
UNIT_TEST_ROOT = Path(__file__).resolve().parent
if str(UNIT_TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(UNIT_TEST_ROOT))

from _phase_c_hermetic import install_hermetic_phase_c_authority  # noqa: E402

SHA = "a" * 64
RUNTIME_BASE_SHA256 = "5c15d6c502d380282a933d4f20a886a06c9d04d3b5d7c918b95df0b0acf33671"
EXTRACTION_PROMPT_SHA256 = "ad19187a37813ef77ee156e714c0650e6ec749e0264bdc07d499bc9b24115155"
RESPONSE_FORMAT_SHA256 = "f45055c9f24f763294c0c96c3d71cd3ae494d96376596f34a6203cf171f9a516"
RESPONSE_SCHEMA_SHA256 = "17c002c4bc8c4aa9d9131253ef0763fd5769c039985c65885e5877fda443120b"
RUNTIME_RESPONSE_FORMAT_SHA256 = "812938567c7a81bac6ed3266608adf470dedc57706102e039422f695495322bf"
RUNTIME_RESPONSE_SCHEMA_SHA256 = "2461f7a465be82aa67751dc04e0717cde75c69b86e7db54bb306a2e3d1d4d8f0"


@pytest.fixture(autouse=True)
def _hermetic_phase_c_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[object, Path]:
    return install_hermetic_phase_c_authority(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        phase_c_root=ROOT / "benchmarks" / "phase-c-canary",
    )


def test_live_unit_binding_uses_exact_class_without_hosting_composition(
    _hermetic_phase_c_authority: tuple[object, Path],
) -> None:
    reference, artifact = _hermetic_phase_c_authority
    from phase_c_canary.runtime_binding import RuntimeBindingComposition

    binding = RuntimeBindingComposition.compose_phase_c_canary().issue()
    assert type(binding) is type(reference)
    assert binding.commitment_sha256 == reference.commitment_sha256
    assert artifact.parent.name == "hermetic-phase-c"
    assert "/mnt/volume_ams3_" not in str(artifact)


@dataclass(frozen=True)
class _Request:
    request_body_sha256: str = "1" * 64
    response_format_sha256: str = RESPONSE_FORMAT_SHA256
    response_schema_sha256: str = RESPONSE_SCHEMA_SHA256
    max_tokens: int = 4096


@dataclass(frozen=True)
class _Seal:
    admission_commitment_sha256: str = "4" * 64
    commitment_sha256: str = "5" * 64
    operation_root_sha256: str = "6" * 64
    provider_observed_extraction_calls: int = 1
    provider_observed_request_tokens: int = 101
    provider_observed_response_tokens: int = 23


@dataclass(frozen=True)
class _Terminal:
    terminal_state: str
    commitment_sha256: str = "7" * 64
    provider_observed_extraction_calls: int = 1
    provider_observed_request_tokens: int = 101
    provider_observed_response_tokens: int = 23


@dataclass(frozen=True)
class _Search:
    records: tuple[object, ...] = (object(),)
    result_root_sha256: str = "8" * 64
    evidence_commitment_sha256: str = "9" * 64


class _Coordinator:
    def __init__(
        self,
        calls: dict[str, int],
        *,
        dispatch_fails: bool = False,
        restore_fails: bool = False,
        record_count: int = 1,
        search_count: int = 1,
    ) -> None:
        self.calls = calls
        self.dispatch_fails = dispatch_fails
        self.restore_fails = restore_fails
        self._record_count = record_count
        self._search_count = search_count

    @property
    def budget(self):
        return SimpleNamespace(total_call_count=5)

    @property
    def storage_observations(self):
        return (
            SimpleNamespace(
                created_record_ids=tuple(f"record-{i}" for i in range(self._record_count))
            ),
        )

    @property
    def terminal_evidence(self) -> _Terminal:
        return _Terminal("deleted")

    def admit(self, *, authority, request, budget_policy) -> None:
        del authority, request
        assert budget_policy.maximum_total_call_count == 5
        self.calls["admit"] = self.calls.get("admit", 0) + 1

    def dispatch_pending(self) -> _Seal:
        self.calls["dispatch"] = self.calls.get("dispatch", 0) + 1
        if self.dispatch_fails:
            raise RuntimeError("must-not-leak")
        return _Seal()

    def restore(self, *, authority, request, budget_policy) -> object:
        del authority, request
        assert budget_policy.maximum_total_call_count == 5
        self.calls["restore"] = self.calls.get("restore", 0) + 1
        if self.restore_fails:
            raise RuntimeError("must-not-leak")
        return object()

    def seal_restored_completed(self) -> _Seal:
        self.calls["seal_restored"] = self.calls.get("seal_restored", 0) + 1
        return _Seal()

    def search_evidence(self, *, corpus_id: str, query: str, limit: int) -> _Search:
        assert corpus_id.startswith("locomo-corpus-")
        assert query == "What tea does Alice like?"
        assert limit == 10
        self.calls["search"] = self.calls.get("search", 0) + 1
        return _Search(records=tuple(object() for _ in range(self._search_count)))

    def cleanup(self) -> _Terminal:
        self.calls["cleanup"] = self.calls.get("cleanup", 0) + 1
        return _Terminal("deleted")

    def abort(self) -> _Terminal:
        self.calls["abort"] = self.calls.get("abort", 0) + 1
        return _Terminal("aborted")


@dataclass
class _Composition:
    coordinator: _Coordinator
    authority: object = object()
    request: object = object()


def _case_payload(*, second_session: bool = False) -> dict[str, object]:
    memories = [
        {
            "kind": "fact",
            "role": "user",
            "session_alias": "session-0001",
            "source_alias": "memory-000001",
            "speaker": "Alice",
            "session_date": "2024-03-10",
            "text": "Alice likes jasmine tea.",
            "timestamp": 1,
        }
    ]
    if second_session:
        memories.append(
            {
                **memories[0],
                "session_alias": "session-0002",
                "source_alias": "memory-000002",
                "session_date": "2024-03-11",
                "timestamp": 2,
            }
        )
    corpus = f"locomo-corpus-{'a' * 64}"
    return {
        "case_id": "live-one-unit",
        "corpus_id": corpus,
        "record": {
            "schema_version": "memory-comparison-managed-corpus.v2",
            "benchmark": "locomo",
            "corpus_id": corpus,
            "thread_id": f"locomo-thread-{'b' * 64}",
            "memories": memories,
            "documents": [],
            "conversations": [],
        },
        "search_query": "What tea does Alice like?",
    }


def _projection() -> OneUnitProjection:
    payload = _case_payload()
    case = ManagedRunCase(payload["case_id"], payload["corpus_id"], payload["record"])
    authority = ManagedMem0V5ManifestProjector().project((case,), current_date="2026-08-07")
    return OneUnitProjection(
        cases=(case,),
        authority=authority,
        request_body_sha256="1" * 64,
        response_format_sha256=RESPONSE_FORMAT_SHA256,
        response_schema_sha256=RESPONSE_SCHEMA_SHA256,
        requested_output_tokens=4096,
        case_file_sha256="0" * 64,
        search_query=payload["search_query"],
    )


def _runtime() -> LiveRuntimeAuthority:
    return LiveRuntimeAuthority(
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        service_tier="priority",
        runtime_source_revision="release-r1",
        runtime_source_sha256="a" * 64,
        runtime_base_sha256="b" * 64,
        route_binding_sha256="c" * 64,
        base_instructions_sha256=RUNTIME_BASE_SHA256,
        extraction_system_prompt_sha256=EXTRACTION_PROMPT_SHA256,
        account_binding_hmac_sha256="e" * 64,
        response_format_type="json_schema",
        response_format_sha256=RUNTIME_RESPONSE_FORMAT_SHA256,
        response_schema_sha256=RUNTIME_RESPONSE_SCHEMA_SHA256,
        extraction_response_format_sha256=RESPONSE_FORMAT_SHA256,
        extraction_response_schema_sha256=RESPONSE_SCHEMA_SHA256,
        requested_output_tokens=4096,
    )


def _inputs(*, restore: bool = False, orphan: bool = False) -> MicroCanaryInputs:
    return MicroCanaryInputs(_projection(), _runtime(), restore, orphan)


def test_extraction_projection_is_bound_separately_from_runtime_base() -> None:
    projection = replace(_projection(), response_format_sha256="f" * 64)
    with pytest.raises(ValueError, match="mem0_v5_live_inputs_invalid"):
        MicroCanaryInputs(projection, _runtime(), False)


def test_projector_materializes_exact_private_one_unit(tmp_path: Path) -> None:
    case = tmp_path / "case.json"
    raw = json.dumps(_case_payload(), sort_keys=True, separators=(",", ":")).encode()
    case.write_bytes(raw)
    os.chmod(case, 0o400)
    projection = project_one_unit(
        case_file=case,
        expected_case_sha256=hashlib.sha256(raw).hexdigest(),
        current_date="2026-08-07",
        extraction_projector=lambda *_args, **_kwargs: _Request(),
    )
    target = tmp_path / "input"
    target.mkdir(mode=0o700)
    materialize_projection(projection, input_root=target)
    assert projection.authority.operation_count == 1
    assert json.loads((target / "manifest.json").read_bytes())["units"][0]["sequence"] == 0
    assert stat_mode(target / "manifest.json") == 0o400
    assert stat_mode(target / "one-unit-authority.json") == 0o400


def test_projector_rejects_multiple_units(tmp_path: Path) -> None:
    case = tmp_path / "case.json"
    raw = json.dumps(
        _case_payload(second_session=True), sort_keys=True, separators=(",", ":")
    ).encode()
    case.write_bytes(raw)
    os.chmod(case, 0o400)
    with pytest.raises(ValueError, match="exactly_one_unit"):
        project_one_unit(
            case_file=case,
            expected_case_sha256=hashlib.sha256(raw).hexdigest(),
            current_date="2026-08-07",
            extraction_projector=lambda *_args, **_kwargs: _Request(),
        )


def test_fresh_go_uses_one_dispatch_search_and_terminal_cleanup() -> None:
    calls: dict[str, int] = {}
    coordinator = _Coordinator(calls)
    report = execute_micro_canary(
        inputs=_inputs(), composition_factory=lambda: _Composition(coordinator)
    )
    assert report["outcome"] == "GO"
    assert calls == {"admit": 1, "dispatch": 1, "search": 1, "cleanup": 1}
    assert report["usage"] == {
        "prompt_tokens": 101,
        "completion_tokens": 23,
        "total_tokens": 124,
        "extraction_calls": 1,
    }
    assert report["authenticated_storage_record_count"] == 1
    assert report["budget"] == {
        "coordinator_full_plan_total_calls": 5,
        "hard_dispatch_guard_max": 1,
        "benchmark_calls_executed": 0,
        "answer_calls_executed": 0,
        "judge_calls_executed": 0,
    }
    assert report["release"] == {"account": "<redacted>", "runtime": "<redacted>"}


def test_unknown_outcome_uses_fresh_status_restore_and_never_redispatches() -> None:
    calls: dict[str, int] = {}
    coordinators = [
        _Coordinator(calls, dispatch_fails=True),
        _Coordinator(calls),
    ]
    report = execute_micro_canary(
        inputs=_inputs(),
        composition_factory=lambda: _Composition(coordinators.pop(0)),
    )
    assert report["outcome"] == "GO"
    assert calls["dispatch"] == 1
    assert calls["restore"] == 1
    assert calls["seal_restored"] == 1
    assert calls["search"] == 1
    assert calls["cleanup"] == 1


def test_unavailable_status_fails_closed_without_second_dispatch() -> None:
    calls: dict[str, int] = {}
    coordinators = [
        _Coordinator(calls, dispatch_fails=True),
        _Coordinator(calls, restore_fails=True),
    ]
    report = execute_micro_canary(
        inputs=_inputs(),
        composition_factory=lambda: _Composition(coordinators.pop(0)),
    )
    assert report["outcome"] == "NO-GO"
    assert report["failure_code"] == "dispatch_status_unavailable"
    assert calls["dispatch"] == 1
    assert calls["restore"] == 1
    assert calls["abort"] == 1
    assert "must-not-leak" not in json.dumps(report)


def test_zero_memory_fails_closed_and_aborts_before_search() -> None:
    calls: dict[str, int] = {}
    report = execute_micro_canary(
        inputs=_inputs(),
        composition_factory=lambda: _Composition(_Coordinator(calls, record_count=0)),
    )
    assert report["failure_code"] == "zero_authenticated_memories"
    assert calls["dispatch"] == 1
    assert calls["cleanup"] == 1
    assert "abort" not in calls
    assert "search" not in calls


def test_existing_checkpoint_restores_and_never_dispatches() -> None:
    calls: dict[str, int] = {}
    report = execute_micro_canary(
        inputs=_inputs(restore=True),
        composition_factory=lambda: _Composition(_Coordinator(calls)),
    )
    assert report["outcome"] == "GO"
    assert "dispatch" not in calls
    assert calls["restore"] == 1
    assert calls["seal_restored"] == 1


def test_orphan_guard_is_no_go_before_composition() -> None:
    created = 0

    def forbidden() -> _Composition:
        nonlocal created
        created += 1
        raise AssertionError

    report = execute_micro_canary(inputs=_inputs(orphan=True), composition_factory=forbidden)
    assert report["failure_code"] == "orphan_dispatch_claim"
    assert created == 0


@pytest.mark.parametrize(
    ("name", "raw", "accepted"),
    (
        ("runtime-transport-origin", b"http://127.0.0.1:8891", True),
        ("runtime-transport-origin", b"http://127.0.0.1:8892", False),
        ("ingress-bearer", b"x" * 32, True),
        ("ingress-bearer", b"x" * 31, False),
    ),
)
def test_private_file_uses_semantic_transport_origin_policy(
    tmp_path: Path, name: str, raw: bytes, accepted: bool
) -> None:
    root = tmp_path / "secrets"
    root.mkdir(mode=0o700)
    path = root / name
    path.write_bytes(raw)
    path.chmod(0o600)

    if accepted:
        assert subject._read_private_file(path, parent=root) == raw
    else:
        with pytest.raises(ValueError, match="private_file_invalid"):
            subject._read_private_file(path, parent=root)


def test_runtime_attestation_secret_must_be_distinct_from_every_private_secret(
    tmp_path: Path,
) -> None:
    root = tmp_path / "secrets"
    root.mkdir(mode=0o700)
    runner_paths: dict[str, Path] = {}
    names = (*ADAPTER_SECRET_NAMES, "checkpoint-signing-key", "checkpoint-head-key")
    for index, name in enumerate(names):
        path = root / name
        raw = (
            b"http://127.0.0.1:8891"
            if name == "runtime-transport-origin"
            else (f"private-{index}-" + "x" * 64).encode()
        )
        path.write_bytes(raw)
        path.chmod(0o600)
        runner_paths[name] = path
    evidence_sha256 = hashlib.sha256((root / "result-hmac").read_bytes()).hexdigest()
    validate_private_credentials(
        secret_root=root,
        runner_paths=runner_paths,
        evidence_key_sha256=evidence_sha256,
        read_private=subject._read_private_file,
    )
    (root / "runtime-attestation-secret").write_bytes((root / "ingress-bearer").read_bytes())
    (root / "runtime-attestation-secret").chmod(0o600)
    with pytest.raises(ValueError, match="runtime_attestation_secret_not_distinct"):
        validate_private_credentials(
            secret_root=root,
            runner_paths=runner_paths,
            evidence_key_sha256=evidence_sha256,
            read_private=subject._read_private_file,
        )


def test_production_factory_composes_observed_authority_and_durable_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sys.path.insert(0, str(ROOT / "benchmarks" / "phase-c-canary"))
    from infinity_context_server import (
        memory_comparison_managed_mem0_v5_composition as composition_subject,
    )
    from infinity_context_server import (
        memory_comparison_mem0_oss_v5_observed_receipt as observed_subject,
    )
    from phase_c_canary.runtime_binding import RuntimeBindingComposition

    monkeypatch.setattr(
        composition_subject,
        "require_mem0_v5_observed_extraction_receipt_boundary",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        observed_subject,
        "require_mem0_v5_observed_extraction_receipt_boundary",
        lambda **_kwargs: None,
    )

    binding = RuntimeBindingComposition.compose_phase_c_canary().issue()
    projection = _projection()
    base = _runtime()
    runtime = LiveRuntimeAuthority(
        model=base.model,
        reasoning_effort=base.reasoning_effort,
        service_tier=base.service_tier,
        runtime_source_revision=base.runtime_source_revision,
        runtime_source_sha256=binding.runtime_source_sha256,
        runtime_base_sha256=base.runtime_base_sha256,
        route_binding_sha256=binding.route_binding_sha256,
        base_instructions_sha256=base.base_instructions_sha256,
        extraction_system_prompt_sha256=base.extraction_system_prompt_sha256,
        account_binding_hmac_sha256=base.account_binding_hmac_sha256,
        response_format_type=base.response_format_type,
        response_format_sha256=base.response_format_sha256,
        response_schema_sha256=base.response_schema_sha256,
        extraction_response_format_sha256=base.extraction_response_format_sha256,
        extraction_response_schema_sha256=base.extraction_response_schema_sha256,
        requested_output_tokens=4096,
    )
    state = tmp_path / "state"
    secrets = tmp_path / "secrets"
    state.mkdir(mode=0o700)
    secrets.mkdir(mode=0o700)
    secret_paths = {}
    for index, name in enumerate(("bearer", "evidence", "receipt", "signing", "head")):
        path = secrets / name
        path.write_bytes((f"private-{name}-{index}-" + "x" * 48).encode())
        os.chmod(path, 0o600)
        secret_paths[name] = path
    runtime_repo = tmp_path / "runtime" / "repo"
    runtime_repo.mkdir(parents=True)
    node = tmp_path / "node"
    node.write_text("unused")
    args = SimpleNamespace(
        phase_c_package_root=ROOT / "benchmarks" / "phase-c-canary",
        runtime_repo=runtime_repo,
        node_executable=node,
        node_executable_sha256=("b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"),
        run_id="managed-v5-live-factory-contract",
        evidence_key_file=secret_paths["evidence"],
        evidence_key_sha256=hashlib.sha256(secret_paths["evidence"].read_bytes()).hexdigest(),
        ingress_bearer_file=secret_paths["bearer"],
        receipt_secret_file=secret_paths["receipt"],
        checkpoint_signing_key_file=secret_paths["signing"],
        checkpoint_head_key_file=secret_paths["head"],
        state_root=state,
        dispatch_journal=state / "dispatch-claim.json",
        current_date="2026-08-07",
        adapter_port=19091,
        timeout_seconds=1.0,
    )
    contract = subject._build_public_contract(
        args=args,
        projection=projection,
        runtime=runtime,
    )
    composition = subject._production_factory(
        args=args,
        projection=projection,
        contract=contract,
    )()
    assert composition.authority.operation_count == 1
    assert composition.request.expected_operation_count == 1
    assert not args.dispatch_journal.exists()


def test_runner_imports_no_benchmark_answer_judge_or_readiness_modules() -> None:
    path = ROOT / "scripts" / "mem0_v5_live_micro_canary.py"
    tree = ast.parse(path.read_text())
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any(
        marker in name
        for name in imported
        for marker in ("public_benchmark", "readiness", "answer", "judge")
    )


def test_invalid_runtime_binding_precedes_every_private_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = SimpleNamespace(
        phase_c_package_root=ROOT / "benchmarks" / "phase-c-canary",
    )

    def private_read_forbidden(*_args, **_kwargs):
        raise AssertionError("private credential opened before public trust preflight")

    monkeypatch.setattr(subject, "_read_private_file", private_read_forbidden)
    with pytest.raises(ValueError, match="runtime_binding_differs"):
        subject._build_public_contract(
            args=args,
            projection=_projection(),
            runtime=_runtime(),
        )


def test_container_copy_authority_requires_exact_uid_modes_and_digests(
    tmp_path: Path,
) -> None:
    digests = {name: hashlib.sha256(name.encode()).hexdigest() for name in ADAPTER_SECRET_NAMES}
    payload = {
        "schema_version": "managed-mem0-v5-container-copy.v1",
        "container_uid": 65532,
        "container_gid": 65532,
        "directory_mode": "0700",
        "input": {
            "manifest.json": {
                "source_sha256": "f" * 64,
                "prepared_sha256": "f" * 64,
                "mode": "0400",
            }
        },
        "secrets": {
            name: {
                "source_sha256": digest,
                "prepared_sha256": digest,
                "mode": "0600",
            }
            for name, digest in sorted(digests.items())
        },
        "state": {
            name: {"uid": 65532, "gid": 65532, "mode": "0700"} for name in ("adapter", "qdrant")
        },
    }
    authority = tmp_path / "container-copy-authority.json"
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    authority.write_bytes(raw)
    os.chmod(authority, 0o444)
    args = SimpleNamespace(
        container_copy_authority_file=authority,
        container_copy_authority_sha256=hashlib.sha256(raw).hexdigest(),
        input_manifest_sha256="f" * 64,
    )
    verify_container_copy_authority(
        path=args.container_copy_authority_file,
        expected_sha256=args.container_copy_authority_sha256,
        input_manifest_sha256=args.input_manifest_sha256,
        secret_digests=digests,
        maximum_bytes=64 * 1024,
    )
    payload["container_uid"] = 0
    tampered = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    authority.unlink()
    authority.write_bytes(tampered)
    os.chmod(authority, 0o444)
    args.container_copy_authority_sha256 = hashlib.sha256(tampered).hexdigest()
    with pytest.raises(ValueError, match="container_copy_authority_invalid"):
        verify_container_copy_authority(
            path=args.container_copy_authority_file,
            expected_sha256=args.container_copy_authority_sha256,
            input_manifest_sha256=args.input_manifest_sha256,
            secret_digests=digests,
            maximum_bytes=64 * 1024,
        )


@pytest.mark.parametrize(
    "script_name",
    ("mem0_v5_live_project_one_unit.py", "mem0_v5_live_micro_canary.py"),
)
def test_direct_cli_help_bootstraps_repository_paths(script_name: str) -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script_name), "--help"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout


def test_direct_cli_invalid_node_is_no_go_without_secret_files(tmp_path: Path) -> None:
    roots: dict[str, Path] = {}
    for name in ("input", "state", "secrets", "reports"):
        root = tmp_path / name
        root.mkdir(mode=0o700)
        roots[name] = root
    runtime_repo = tmp_path / "runtime" / "repo"
    runtime_repo.mkdir(parents=True)
    artifact = runtime_repo.parent / "artifact-manifest.json"
    artifact.write_text("{}")
    os.chmod(artifact, 0o444)
    node = tmp_path / "unreviewed-node"
    node.write_text("unreviewed")
    os.chmod(node, 0o755)
    report_file = roots["reports"] / "report.json"
    command = [
        sys.executable,
        str(ROOT / "scripts" / "mem0_v5_live_micro_canary.py"),
        "--run-id",
        "invalid-node-no-secret-open",
        "--case-file",
        str(tmp_path / "case.json"),
        "--case-sha256",
        "1" * 64,
        "--current-date",
        "2026-08-07",
        "--input-root",
        str(roots["input"]),
        "--input-manifest-sha256",
        "2" * 64,
        "--one-unit-authority-sha256",
        "3" * 64,
        "--runtime-authority-file",
        str(tmp_path / "runtime-authority.json"),
        "--runtime-authority-sha256",
        "4" * 64,
        "--extraction-contract-file",
        str(tmp_path / "extraction-contract.py"),
        "--extraction-contract-sha256",
        "9" * 64,
        "--state-root",
        str(roots["state"]),
        "--secret-root",
        str(roots["secrets"]),
        "--report-root",
        str(roots["reports"]),
        "--report-file",
        str(report_file),
        "--dispatch-journal",
        str(roots["state"] / "dispatch-claim.json"),
        "--ingress-bearer-file",
        str(roots["secrets"] / "ingress-bearer"),
        "--evidence-key-file",
        str(roots["secrets"] / "result-hmac"),
        "--evidence-key-sha256",
        "5" * 64,
        "--runtime-attestation-secret-file",
        str(roots["secrets"] / "runtime-attestation-secret"),
        "--receipt-secret-file",
        str(roots["secrets"] / "runtime-receipt-secret"),
        "--checkpoint-signing-key-file",
        str(roots["secrets"] / "checkpoint-signing-key"),
        "--checkpoint-head-key-file",
        str(roots["secrets"] / "checkpoint-head-key"),
        "--phase-c-package-root",
        str(tmp_path),
        "--runtime-repo",
        str(runtime_repo),
        "--runtime-artifact-manifest",
        str(artifact),
        "--runtime-artifact-manifest-sha256",
        hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "--node-executable",
        str(node),
        "--node-executable-sha256",
        hashlib.sha256(node.read_bytes()).hexdigest(),
        "--container-copy-authority-file",
        str(tmp_path / "container-copy-authority.json"),
        "--container-copy-authority-sha256",
        "6" * 64,
        "--adapter-image-id",
        "sha256:" + "7" * 64,
        "--qdrant-image-id",
        "sha256:" + "8" * 64,
        "--adapter-port",
        "19091",
        "--qdrant-port",
        "6334",
        "--preflight-only",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["outcome"] == "NO-GO"
    assert json.loads(report_file.read_bytes())["failure_code"] == (
        "live_micro_canary_preflight_failed"
    )
    assert not tuple(roots["secrets"].iterdir())


def test_compose_override_is_cached_image_tcp_only() -> None:
    path = ROOT / "benchmarks" / "mem0-oss-adapter-v5" / ("compose.live-micro-canary.override.yaml")
    content = path.read_text()
    assert "build:" not in content
    assert content.count("pull_policy: never") == 3
    assert "socket.create_connection" in content
    assert "urllib" not in content
    assert "curl" not in content
    assert 'user: "0:0"' in content
    assert content.count('user: "65532:65532"') == 2
    assert "service_completed_successfully" in content
    assert "source_sha != prepared_sha" in content
    assert "container_copy_ownership_failed" in content
    assert "container_copy_roots_overlap" in content
    assert "MEM0_V5_HOST_SECRET_DIR" in content
    assert "MEM0_V5_CONTAINER_SECRET_DIR" in content
    assert "MEM0_V5_HOST_INPUT_DIR" in content
    assert "MEM0_V5_CONTAINER_INPUT_DIR" in content
    assert "0o700" in content and "0o600" in content and "0o400" in content


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777
