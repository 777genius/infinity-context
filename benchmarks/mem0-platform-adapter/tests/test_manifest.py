from __future__ import annotations

import json
import tomllib
from copy import deepcopy
from pathlib import Path

import pytest
from root_contract_import import import_root_contract

from mem0_platform_adapter import manifest
from mem0_platform_adapter.models import TimestampAttestation
from mem0_platform_adapter.service import PollingPolicy


def _capabilities() -> dict[str, object]:
    return manifest.capabilities_manifest(
        configured=True,
        attestation=TimestampAttestation(
            status="passed",
            cleanup_succeeded=True,
        ),
        policy=PollingPolicy(),
    )


class FakeDistribution:
    def __init__(self, version: str, direct_url: object) -> None:
        self.version = version
        self._direct_url = direct_url

    def read_text(self, filename: str) -> str | None:
        assert filename == "direct_url.json"
        return json.dumps(self._direct_url) if self._direct_url is not None else None


def _install_evidence(
    version: str = "2.0.14",
    sha256: str | None = None,
    url: str = "file:///private/build/mem0ai-2.0.14-py3-none-any.whl",
) -> FakeDistribution:
    observed = sha256 or manifest.RUNTIME_PIN.wheel_sha256
    return FakeDistribution(
        version,
        {
            "archive_info": {"hashes": {"sha256": observed}},
            "url": url,
        },
    )


def test_manifest_attests_exact_installed_sdk_pin(monkeypatch) -> None:
    monkeypatch.setattr(manifest, "installed_distribution", lambda _: _install_evidence())

    payload = _capabilities()
    sdk = payload["sdk"]

    assert sdk == {
        "distribution": "mem0ai",
        "version": "2.0.14",
        "expected_version": "2.0.14",
        "pin_matches": True,
        "source_revision": "b357a5a1b03c299ec8229c268e63cfac0f7c6566",
        "artifact_sha256": "9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f",
        "verification": {
            "method": "direct_url_archive_info_sha256",
            "observed_sha256": ("9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"),
            "passed": True,
        },
    }
    assert payload["timestamp"]["sdk_forwarding_supported"] is True
    assert "private/build" not in str(payload)


def test_manifest_fails_closed_on_installed_sdk_version_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        manifest,
        "installed_distribution",
        lambda _: _install_evidence(version="2.0.13"),
    )

    payload = _capabilities()
    sdk = payload["sdk"]

    assert sdk["version"] == "2.0.13"
    assert sdk["expected_version"] == "2.0.14"
    assert sdk["pin_matches"] is False
    assert sdk["source_revision"] is None
    assert sdk["artifact_sha256"] is None
    assert sdk["verification"]["observed_sha256"] == manifest.RUNTIME_PIN.wheel_sha256
    assert sdk["verification"]["passed"] is False
    assert payload["timestamp"]["sdk_forwarding_supported"] is False


def test_manifest_fails_closed_without_matching_local_wheel_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        manifest,
        "installed_distribution",
        lambda _: _install_evidence(sha256="f" * 64),
    )

    sdk = _capabilities()["sdk"]

    assert sdk["pin_matches"] is False
    assert sdk["source_revision"] is None
    assert sdk["artifact_sha256"] is None
    assert sdk["verification"] == {
        "method": "direct_url_archive_info_sha256",
        "observed_sha256": "f" * 64,
        "passed": False,
    }


def test_manifest_fails_closed_when_direct_url_evidence_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        manifest,
        "installed_distribution",
        lambda _: FakeDistribution("2.0.14", None),
    )

    sdk = _capabilities()["sdk"]

    assert sdk["source_revision"] is None
    assert sdk["artifact_sha256"] is None
    assert sdk["verification"]["observed_sha256"] is None
    assert sdk["verification"]["passed"] is False


@pytest.mark.parametrize(
    "url",
    (
        "https://evil.example/mem0ai-2.0.14-py3-none-any.whl",
        "file:///private/build/renamed-mem0ai.whl",
        "file:///private/build/mem0ai-2.0.14-py3-none-any.whl?untrusted=1",
    ),
)
def test_manifest_rejects_untrusted_direct_url_even_with_matching_hash(
    monkeypatch,
    url: str,
) -> None:
    monkeypatch.setattr(
        manifest,
        "installed_distribution",
        lambda _: _install_evidence(url=url),
    )

    sdk = _capabilities()["sdk"]

    assert sdk["pin_matches"] is False
    assert sdk["verification"]["observed_sha256"] is None


@pytest.mark.contract
def test_generated_passed_manifest_satisfies_main_v2_validator(monkeypatch) -> None:
    contract = import_root_contract(
        "infinity_context_server.memory_comparison_mem0_contract",
    )
    monkeypatch.setattr(manifest, "installed_distribution", lambda _: _install_evidence())
    payload = manifest.capabilities_manifest(
        configured=True,
        attestation=TimestampAttestation(
            status="passed",
            checked_at="2026-07-29T10:00:00Z",
            input_epoch_seconds=1672531200,
            expected_created_at="2023-01-01T00:00:00Z",
            event_terminal_status="SUCCEEDED",
            readback_result_count=1,
            persisted_created_at="2023-01-01T00:00:00Z",
            delta_seconds=0.0,
            cleanup_succeeded=True,
            failure_code=None,
        ),
        policy=PollingPolicy(),
    )

    assert contract.evaluate_mem0_runtime_capabilities(payload, require_timestamp=True) == ()


def test_generated_manifest_binds_exact_tracked_wrapper_profile(monkeypatch) -> None:
    monkeypatch.setattr(manifest, "installed_distribution", lambda _: _install_evidence())

    payload = _capabilities()

    assert payload["wrapper_source_revision"] == manifest.RUNTIME_PIN.wrapper_source_revision
    assert payload["wrapper_source_sha256"] == manifest.RUNTIME_PIN.wrapper_source_sha256
    assert manifest.manifest_is_ready(payload) is True


def test_runtime_pin_loader_fails_closed_on_invalid_or_extra_fields(tmp_path: Path) -> None:
    invalid_pin = tmp_path / "runtime-pin.json"
    payload = {
        field: getattr(manifest.RUNTIME_PIN, field)
        for field in manifest.RuntimePin.__dataclass_fields__
    }
    payload["wheel_sha256"] = "not-a-sha"
    payload["unexpected"] = "value"
    invalid_pin.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="runtime pin"):
        manifest.load_runtime_pin(invalid_pin)


def test_manifest_readiness_requires_every_provenance_invariant(monkeypatch) -> None:
    monkeypatch.setattr(manifest, "installed_distribution", lambda _: _install_evidence())
    payload = manifest.capabilities_manifest(
        configured=True,
        attestation=TimestampAttestation(
            status="passed",
            checked_at="2026-07-29T10:00:00Z",
            cleanup_succeeded=True,
        ),
        policy=PollingPolicy(),
    )

    assert manifest.manifest_is_ready(payload) is True
    mutations = (
        ("configured", False),
        ("wrapper_source_revision", None),
        ("wrapper_source_sha256", "f" * 64),
    )
    for key, value in mutations:
        candidate = deepcopy(payload)
        candidate[key] = value
        assert manifest.manifest_is_ready(candidate) is False
    for key, value in (
        ("pin_matches", False),
        ("pin_matches", None),
    ):
        candidate = deepcopy(payload)
        candidate["sdk"][key] = value
        assert manifest.manifest_is_ready(candidate) is False
    for key, value in (
        ("status", "failed"),
        ("checked_at", None),
        ("cleanup_succeeded", False),
    ):
        candidate = deepcopy(payload)
        candidate["timestamp"]["attestation"][key] = value
        assert manifest.manifest_is_ready(candidate) is False


def test_dependency_metadata_has_no_second_mem0_version_source() -> None:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = {
        line.strip()
        for line in (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    project_dependencies = set(project["project"]["dependencies"])
    mem0_dependencies = {
        dependency
        for dependency in project_dependencies
        if dependency.casefold().startswith("mem0ai")
    }
    assert mem0_dependencies == {"mem0ai"}
    assert all(not requirement.casefold().startswith("mem0ai") for requirement in requirements)
    assert requirements == project_dependencies - {"mem0ai"}
