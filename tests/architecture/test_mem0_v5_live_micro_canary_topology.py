from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from scripts import mem0_v5_live_micro_canary as subject


def _command(*topology: str) -> list[str]:
    root = Path("/tmp/mem0-v5-topology-test")
    return [
        "--run-id",
        "publishable-isolated-lane",
        "--case-file",
        str(root / "case.json"),
        "--case-sha256",
        "1" * 64,
        "--current-date",
        "2026-08-10",
        "--input-root",
        str(root / "input"),
        "--input-manifest-sha256",
        "2" * 64,
        "--one-unit-authority-sha256",
        "3" * 64,
        "--runtime-authority-file",
        str(root / "runtime-authority.json"),
        "--runtime-authority-sha256",
        "4" * 64,
        "--extraction-contract-file",
        str(root / "extraction-contract.py"),
        "--extraction-contract-sha256",
        "5" * 64,
        "--state-root",
        str(root / "state"),
        "--secret-root",
        str(root / "secrets"),
        "--report-root",
        str(root / "reports"),
        "--report-file",
        str(root / "reports" / "report.json"),
        "--dispatch-journal",
        str(root / "state" / "dispatch.json"),
        "--ingress-bearer-file",
        str(root / "secrets" / "ingress-bearer"),
        "--evidence-key-file",
        str(root / "secrets" / "result-hmac"),
        "--evidence-key-sha256",
        "6" * 64,
        "--runtime-attestation-secret-file",
        str(root / "secrets" / "runtime-attestation-secret"),
        "--receipt-secret-file",
        str(root / "secrets" / "runtime-receipt-secret"),
        "--checkpoint-signing-key-file",
        str(root / "secrets" / "checkpoint-signing-key"),
        "--checkpoint-head-key-file",
        str(root / "secrets" / "checkpoint-head-key"),
        "--phase-c-package-root",
        str(root / "phase-c"),
        "--runtime-repo",
        str(root / "runtime" / "repo"),
        "--runtime-artifact-manifest",
        str(root / "runtime" / "artifact-manifest.json"),
        "--runtime-artifact-manifest-sha256",
        "7" * 64,
        "--node-executable",
        str(root / "node"),
        "--node-executable-sha256",
        "8" * 64,
        "--container-copy-authority-file",
        str(root / "container-copy-authority.json"),
        "--container-copy-authority-sha256",
        "9" * 64,
        "--adapter-image-id",
        "sha256:" + "a" * 64,
        "--qdrant-image-id",
        "sha256:" + "b" * 64,
        "--adapter-port",
        "29197",
        *topology,
    ]


def test_parser_accepts_publishable_relay_with_internal_only_qdrant() -> None:
    args = subject._parse_args(_command("--qdrant-internal-only"))

    assert args.adapter_port == 29197
    assert args.qdrant_port is None
    assert args.qdrant_internal_only is True
    assert subject._host_endpoint_topology(args).qdrant_topology == "internal-only"


def test_parser_preserves_legacy_host_probe_only_with_explicit_port() -> None:
    args = subject._parse_args(_command("--qdrant-port", "30197"))

    assert args.qdrant_port == 30197
    assert args.qdrant_internal_only is False
    assert subject._host_endpoint_topology(args).qdrant_topology == "loopback-host"


@pytest.mark.parametrize(
    "topology",
    (
        (),
        ("--qdrant-port", "30197", "--qdrant-internal-only"),
        ("--qdrant-port", "29197"),
    ),
)
def test_parser_rejects_implicit_ambiguous_or_colliding_topology(
    topology: tuple[str, ...],
) -> None:
    with pytest.raises(SystemExit) as raised:
        subject._parse_args(_command(*topology))

    assert raised.value.code == 2


@pytest.mark.parametrize(
    ("topology", "expected_ports", "expected_qdrant_topology"),
    (
        (("--qdrant-internal-only",), [29197], "internal-only"),
        (("--qdrant-port", "30197"), [29197, 30197], "loopback-host"),
    ),
)
def test_live_command_probes_only_explicit_host_endpoints(
    monkeypatch: pytest.MonkeyPatch,
    topology: tuple[str, ...],
    expected_ports: list[int],
    expected_qdrant_topology: str,
) -> None:
    probes: list[int] = []
    reports: list[dict[str, object]] = []

    monkeypatch.setattr(subject, "_preflight", lambda _args: (object(), object(), object()))
    monkeypatch.setattr(
        subject,
        "_tcp_probe",
        lambda port, _timeout: probes.append(port) is None,
    )
    monkeypatch.setattr(subject, "MicroCanaryInputs", lambda **_kwargs: object())
    monkeypatch.setattr(subject, "_read_private_file", lambda *_args, **_kwargs: b"k" * 32)
    monkeypatch.setattr(
        subject,
        "LiveCanaryRecoverySession",
        lambda **_kwargs: nullcontext(object()),
    )
    monkeypatch.setattr(
        subject,
        "execute_micro_canary",
        lambda **_kwargs: {"ok": True, "commitments": {}},
    )
    monkeypatch.setattr(
        subject,
        "_write_report",
        lambda _path, _root, report: reports.append(report),
    )

    assert subject.main(_command(*topology)) == 0
    assert probes == expected_ports
    assert reports[0]["qdrant_topology"] == expected_qdrant_topology


def test_terminal_recovery_does_not_require_live_tcp_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes: list[int] = []
    reports: list[dict[str, object]] = []
    real_exists = Path.exists

    monkeypatch.setattr(subject, "_preflight", lambda _args: (object(), object(), object()))
    monkeypatch.setattr(
        subject,
        "_tcp_probe",
        lambda port, _timeout: probes.append(port) is None,
    )
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: path.name == "checkpoint.json" or real_exists(path),
    )
    monkeypatch.setattr(subject, "MicroCanaryInputs", lambda **_kwargs: object())
    monkeypatch.setattr(subject, "_read_private_file", lambda *_args, **_kwargs: b"k" * 32)
    monkeypatch.setattr(
        subject,
        "LiveCanaryRecoverySession",
        lambda **_kwargs: nullcontext(object()),
    )
    monkeypatch.setattr(
        subject,
        "execute_micro_canary",
        lambda **_kwargs: {"ok": True, "commitments": {}},
    )
    monkeypatch.setattr(
        subject,
        "_write_report",
        lambda _path, _root, report: reports.append(report),
    )

    assert subject.main(_command("--qdrant-internal-only")) == 0
    assert probes == []
    assert reports[0]["qdrant_topology"] == "internal-only"


def test_runner_source_contains_no_legacy_host_port_constants() -> None:
    source = Path(subject.__file__).read_text()
    legacy_host_ports = {str(19_000 + 91), str(6_300 + 34)}

    assert all(port not in source for port in legacy_host_ports)
