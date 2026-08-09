from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import mem0_v5_live_micro_canary as subject
from scripts.mem0_v5_live_runtime_authority import LiveRuntimeAuthority

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_BASE_SHA256 = "5c15d6c502d380282a933d4f20a886a06c9d04d3b5d7c918b95df0b0acf33671"
EXTRACTION_PROMPT_SHA256 = "ad19187a37813ef77ee156e714c0650e6ec749e0264bdc07d499bc9b24115155"
RESPONSE_FORMAT_SHA256 = "f45055c9f24f763294c0c96c3d71cd3ae494d96376596f34a6203cf171f9a516"
RESPONSE_SCHEMA_SHA256 = "17c002c4bc8c4aa9d9131253ef0763fd5769c039985c65885e5877fda443120b"


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
        response_format_sha256=RESPONSE_FORMAT_SHA256,
        response_schema_sha256=RESPONSE_SCHEMA_SHA256,
        requested_output_tokens=4096,
    )


def _payload(runtime: LiveRuntimeAuthority) -> dict[str, object]:
    return {
        "schema_version": "managed-mem0-v5-live-runtime-authority.v2",
        **{field: getattr(runtime, field) for field in runtime.__dataclass_fields__},
    }


def _contract_args(tmp_path: Path) -> SimpleNamespace:
    source = (
        ROOT
        / "benchmarks"
        / "mem0-oss-adapter-v5"
        / "mem0_oss_adapter_v5"
        / "extraction_contract.py"
    )
    contract = tmp_path / "extraction_contract.py"
    contract.write_bytes(source.read_bytes())
    contract.chmod(0o444)
    return SimpleNamespace(
        extraction_contract_file=contract,
        extraction_contract_sha256=hashlib.sha256(contract.read_bytes()).hexdigest(),
    )


def test_runtime_authority_is_exact_and_requires_4096() -> None:
    runtime = _runtime()
    payload = _payload(runtime)
    assert LiveRuntimeAuthority.parse(json.dumps(payload).encode()) == runtime
    payload["requested_output_tokens"] = 2048
    with pytest.raises(ValueError, match="runtime_authority_invalid"):
        LiveRuntimeAuthority.parse(json.dumps(payload).encode())


@pytest.mark.parametrize("value", (4096.0, True))
def test_runtime_authority_requires_exact_integer_output_tokens(value: object) -> None:
    payload = _payload(_runtime())
    payload["requested_output_tokens"] = value
    with pytest.raises(ValueError, match="runtime_authority_invalid"):
        LiveRuntimeAuthority.parse(json.dumps(payload).encode())


def test_runtime_authority_rejects_duplicate_json_keys() -> None:
    encoded = json.dumps(_payload(_runtime())).encode()
    duplicate = encoded[:-1] + b',"model":"gpt-5.6-sol"}'
    with pytest.raises(ValueError, match="runtime_authority_invalid"):
        LiveRuntimeAuthority.parse(duplicate)


@pytest.mark.parametrize("mutation", ("missing", "swapped", "equalized", "v1"))
def test_runtime_authority_rejects_conflated_instruction_authority(mutation: str) -> None:
    payload = _payload(_runtime())
    if mutation == "missing":
        payload.pop("extraction_system_prompt_sha256")
    elif mutation == "swapped":
        payload["base_instructions_sha256"], payload["extraction_system_prompt_sha256"] = (
            payload["extraction_system_prompt_sha256"],
            payload["base_instructions_sha256"],
        )
    elif mutation == "equalized":
        payload["extraction_system_prompt_sha256"] = payload["base_instructions_sha256"]
    else:
        payload["schema_version"] = "managed-mem0-v5-live-runtime-authority.v1"
    with pytest.raises(ValueError, match="runtime_authority_invalid"):
        LiveRuntimeAuthority.parse(json.dumps(payload).encode())


@pytest.mark.parametrize(
    "runtime",
    (
        replace(
            _runtime(),
            base_instructions_sha256=EXTRACTION_PROMPT_SHA256,
            extraction_system_prompt_sha256=RUNTIME_BASE_SHA256,
        ),
        replace(_runtime(), extraction_system_prompt_sha256=RUNTIME_BASE_SHA256),
    ),
)
def test_pinned_extraction_contract_rejects_swapped_or_equalized_authority(
    tmp_path: Path,
    runtime: LiveRuntimeAuthority,
) -> None:
    args = _contract_args(tmp_path)
    with pytest.raises(ValueError, match="extraction_authority_differs"):
        subject.require_extraction_authority(
            runtime=runtime,
            contract_file=args.extraction_contract_file,
            contract_sha256=args.extraction_contract_sha256,
        )


def test_pinned_extraction_contract_validates_independently_from_runtime_base(
    tmp_path: Path,
) -> None:
    args = _contract_args(tmp_path)
    subject.require_extraction_authority(
        runtime=_runtime(),
        contract_file=args.extraction_contract_file,
        contract_sha256=args.extraction_contract_sha256,
    )
    assert _runtime().base_instructions_sha256 != _runtime().extraction_system_prompt_sha256


def test_attacker_node_fails_before_private_credentials_are_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = {}
    for name in ("input", "state", "secrets", "reports"):
        path = tmp_path / name
        path.mkdir(mode=0o700)
        roots[name] = path
    runtime_repo = tmp_path / "runtime" / "repo"
    runtime_repo.mkdir(parents=True)
    artifact = runtime_repo.parent / "artifact-manifest.json"
    artifact.write_text("{}")
    artifact.chmod(0o444)
    node = tmp_path / "attacker-node"
    node.write_text("#!/bin/sh\nexit 0\n")
    node.chmod(0o755)
    args = SimpleNamespace(
        input_root=roots["input"],
        state_root=roots["state"],
        secret_root=roots["secrets"],
        report_root=roots["reports"],
        dispatch_journal=roots["state"] / "dispatch-claim.json",
        case_file=tmp_path / "case.json",
        runtime_authority_file=tmp_path / "runtime-authority.json",
        extraction_contract_file=tmp_path / "extraction-contract.py",
        extraction_contract_sha256="f" * 64,
        phase_c_package_root=tmp_path,
        runtime_repo=runtime_repo,
        runtime_artifact_manifest=artifact,
        runtime_artifact_manifest_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
        node_executable=node,
        node_executable_sha256=hashlib.sha256(node.read_bytes()).hexdigest(),
        adapter_image_id="sha256:" + "a" * 64,
        qdrant_image_id="sha256:" + "b" * 64,
        adapter_port=19091,
        qdrant_port=6334,
        timeout_seconds=1.0,
        ingress_bearer_file=roots["secrets"] / "bearer",
        evidence_key_file=roots["secrets"] / "evidence",
        evidence_key_sha256="a" * 64,
        receipt_secret_file=roots["secrets"] / "receipt",
        checkpoint_signing_key_file=roots["secrets"] / "signing",
        checkpoint_head_key_file=roots["secrets"] / "head",
        container_copy_authority_file=tmp_path / "container-copy-authority.json",
        container_copy_authority_sha256="b" * 64,
    )

    monkeypatch.setattr(
        subject,
        "_read_private_file",
        lambda *_args, **_kwargs: pytest.fail("private credential opened before Node rejection"),
    )
    with pytest.raises(ValueError, match="node_authority_invalid"):
        subject._preflight(args)


def test_reviewed_node_uses_exact_reviewed_binary_size_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = tmp_path / "reviewed-node"
    node.write_text("reviewed")
    node.chmod(0o555)
    observed: dict[str, object] = {}

    def capture(path: Path, expected: str, *, executable: bool, maximum_bytes: int) -> None:
        observed.update(
            path=path,
            expected=expected,
            executable=executable,
            maximum_bytes=maximum_bytes,
        )

    monkeypatch.setattr(subject, "_verify_public_immutable", capture)
    subject._verify_reviewed_node(node, subject._REVIEWED_NODE_SHA256)
    assert observed == {
        "path": node,
        "expected": subject._REVIEWED_NODE_SHA256,
        "executable": True,
        "maximum_bytes": 123_438_592,
    }
