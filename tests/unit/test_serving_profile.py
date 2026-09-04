import json
from pathlib import Path
from types import SimpleNamespace

import infinity_context_server.build_identity as build_identity
import infinity_context_server.tei_probe as tei_probe
import pytest
from infinity_context_server.config import Settings
from infinity_context_server.serving_profile import build_verified_serving_profile

from scripts import build_manifest

SERVICE_SHA = "8" * 40
MODEL_SHA = "a" * 40
TEI_SHA = "b" * 40


class Distribution:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.files = (
            Path("infinity_context_adapters/__init__.py"),
            Path("infinity_context_contracts/__init__.py"),
            Path("infinity_context_core/__init__.py"),
            Path("infinity_context_server/__init__.py"),
            Path("infinity_context-0.1.dist-info/METADATA"),
            Path("../../../bin/infinity-context"),
        )

    def locate_file(self, path: object) -> Path:
        return self.root / str(path)


class InfoResponse:
    def __init__(self, payload: dict[str, str], url: str = "http://tei.test/info") -> None:
        self.data = json.dumps(payload).encode()
        self.content = self.data
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.data

    def geturl(self) -> str:
        return self.url


class SyncClient:
    def __init__(self, response: InfoResponse) -> None:
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, _url: str) -> InfoResponse:
        return self.response


def settings_with_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides
) -> Settings:
    prefix = tmp_path / "prefix"
    root = prefix / "lib" / "python" / "site-packages"
    modules = {name: root / name / "__init__.py" for name in build_identity._RUNTIME_PACKAGES}
    metadata = root / "infinity_context-0.1.dist-info" / "METADATA"
    script = prefix / "bin" / "infinity-context"
    for module in modules.values():
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("VERSION = 1\n")
    metadata.parent.mkdir(parents=True, exist_ok=True)
    script.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text("Name: infinity-context\n")
    script.write_text("#!/bin/sh\n")
    distribution = Distribution(root)
    monkeypatch.setattr(build_identity.sys, "prefix", str(prefix))
    monkeypatch.setattr(build_identity.importlib.metadata, "distribution", lambda _n: distribution)
    monkeypatch.setattr(
        build_identity.importlib,
        "import_module",
        lambda name: SimpleNamespace(__file__=modules[name]),
    )
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "infinity-context.source-build.v1",
                "service_revision": SERVICE_SHA,
                "source_tree_digest_sha256": "sha256:" + "c" * 64,
            }
        )
    )
    installed = tmp_path / "installed.json"
    build_identity.write_installed_build_identity(source_manifest=source, output_path=installed)
    values = {
        "service_build_identity_path": str(installed),
        "embeddings_enabled": True,
        "embeddings_provider": "openai",
        "embeddings_model": "sentence-transformers/multilingual-mini",
        "embeddings_model_revision": MODEL_SHA,
        "embeddings_runtime_build_revision": TEI_SHA,
        "embeddings_runtime_info_url": "http://tei.test/info",
        "embeddings_base_url": "http://tei.test/v1/",
        "embeddings_dimensions": 384,
        "qdrant_enabled": True,
    }
    values.update(overrides)
    payload = {"model_id": values["embeddings_model"], "model_sha": MODEL_SHA, "sha": TEI_SHA}
    monkeypatch.setattr(tei_probe, "_resolve_host", lambda *_a: "127.0.0.1")
    monkeypatch.setattr(
        tei_probe,
        "_sync_client",
        lambda *_a: SyncClient(InfoResponse(payload, "http://127.0.0.1/info")),
    )
    return Settings(**values)


def test_dense_profile_is_frozen_and_uses_observed_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_with_identity(tmp_path, monkeypatch)
    profile = build_verified_serving_profile(settings)
    digest = profile.embedding_profile_digest_sha256
    settings.embeddings_dimensions = 999
    settings.embeddings_model = "mutated"
    assert profile.service_revision == SERVICE_SHA
    assert profile.embedding_profile_id == (
        "tei-sentence-transformers-multilingual-mini-384d-dense.v1"
    )
    assert profile.embedding_profile_digest_sha256 == digest
    assert profile.inference_base_url == "http://tei.test/v1"
    alternate_name = build_verified_serving_profile(
        settings_with_identity(tmp_path, monkeypatch, qdrant_dense_vector_name="ignored")
    )
    assert alternate_name.embedding_profile_digest_sha256 == digest


def test_hybrid_runtime_is_operational_but_publicly_unqualified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = build_verified_serving_profile(
        settings_with_identity(tmp_path, monkeypatch, qdrant_hybrid_sparse_enabled=True)
    )
    assert profile.embedding_profile_id is None
    assert profile.embedding_profile_digest_sha256 is None
    profile.verify_runtime()


def test_missing_manifest_fails_closed_for_requested_attestation(tmp_path: Path) -> None:
    settings = Settings(
        service_build_identity_path=str(tmp_path / "missing"),
        embeddings_enabled=True,
        embeddings_model_revision=MODEL_SHA,
        embeddings_runtime_build_revision=TEI_SHA,
        embeddings_runtime_info_url="http://tei.test/info",
        embeddings_base_url="http://tei.test/v1",
    )
    with pytest.raises(RuntimeError, match="verified service build manifest"):
        build_verified_serving_profile(settings)


def test_empty_compose_attestation_values_are_unset(tmp_path: Path) -> None:
    settings = Settings(
        service_build_identity_path=str(tmp_path / "missing"),
        embeddings_model_revision="",
        embeddings_runtime_build_revision="",
        embeddings_runtime_info_url="",
        embeddings_base_url="",
    )
    assert settings.embeddings_model_revision is None
    assert settings.embeddings_runtime_build_revision is None
    assert build_verified_serving_profile(settings).embedding_profile_id is None


def test_info_redirect_and_replaced_runtime_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tei_probe, "_resolve_host", lambda *_a: "127.0.0.1")
    probe = tei_probe.TeiProbe.create(
        model_id="model",
        model_sha=MODEL_SHA,
        build_sha=TEI_SHA,
        inference_base_url="http://tei.test/v1",
        info_url="http://tei.test/info",
    )
    payload = {"model_id": "model", "model_sha": MODEL_SHA, "sha": TEI_SHA}
    monkeypatch.setattr(
        tei_probe,
        "_sync_client",
        lambda *_a: SyncClient(InfoResponse(payload, "http://evil/info")),
    )
    with pytest.raises(RuntimeError, match="redirected"):
        probe.verify()
    payload["sha"] = "f" * 40
    monkeypatch.setattr(
        tei_probe,
        "_sync_client",
        lambda *_a: SyncClient(InfoResponse(payload, "http://127.0.0.1/info")),
    )
    with pytest.raises(RuntimeError, match="frozen profile"):
        probe.verify()


def test_runtime_network_identity_is_pinned_and_connection_change_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolutions: list[tuple[str, int]] = []
    monkeypatch.setattr(
        tei_probe,
        "_resolve_host",
        lambda host, port: resolutions.append((host, port)) or "192.0.2.10",
    )
    probe = tei_probe.TeiProbe.create(
        model_id="model",
        model_sha=MODEL_SHA,
        build_sha=TEI_SHA,
        inference_base_url="https://tei.test:8443/v1",
        info_url="https://tei.test:8443/info",
    )
    assert resolutions == [("tei.test", 8443)]
    assert probe.pinned_inference_base_url == "https://192.0.2.10:8443/v1"
    assert probe.authority == "tei.test:8443"
    tracker = tei_probe._ConnectionTracker()
    stream = object()
    tracker.observe(SimpleNamespace(extensions={"network_stream": stream}))
    tracker.observe(SimpleNamespace(extensions={"network_stream": stream}))
    tracker.assert_reused()
    with pytest.raises(RuntimeError, match="connection changed"):
        tracker.observe(SimpleNamespace(extensions={"network_stream": object()}))


def test_distribution_rejects_shadow_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = tmp_path / "prefix"
    root = prefix / "lib" / "python" / "site-packages"
    module = root / "infinity_context_server" / "__init__.py"
    metadata = root / "infinity_context-0.1.dist-info" / "METADATA"
    module.parent.mkdir(parents=True)
    metadata.parent.mkdir(parents=True)
    module.write_text("ok")
    metadata.write_text("ok")
    monkeypatch.setattr(build_identity.sys, "prefix", str(prefix))
    monkeypatch.setattr(
        build_identity.importlib.metadata, "distribution", lambda _n: Distribution(root)
    )
    shadow = tmp_path / "shadow.py"
    shadow.write_text("bad")
    monkeypatch.setattr(
        build_identity.importlib, "import_module", lambda _n: SimpleNamespace(__file__=shadow)
    )
    with pytest.raises(RuntimeError, match="outside installed distribution"):
        build_identity.installed_distribution_digest()


def test_source_manifest_rejects_dirty_or_changed_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "packages").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "docker").mkdir()
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    (tmp_path / "LICENSE").write_text("license\n")
    (tmp_path / "README.md").write_text("readme\n")
    (tmp_path / "docker" / "infinity-context-entrypoint.sh").write_text("#!/bin/sh\n")
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    (tmp_path / "scripts" / "build_manifest.py").write_text("trusted\n")
    monkeypatch.setattr(build_manifest, "_git", lambda *_a: " M packages/code.py")
    with pytest.raises(RuntimeError, match="dirty"):
        build_manifest.generate(tmp_path, tmp_path / "manifest.json")
    monkeypatch.setattr(
        build_manifest, "_git", lambda *_a: "" if _a[1] == "status" else SERVICE_SHA
    )
    manifest = tmp_path / "manifest.json"
    build_manifest.generate(tmp_path, manifest)
    ignored = tmp_path / "packages" / "sdk" / "node_modules" / "generated.js"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("machine-local")
    build_manifest.verify(tmp_path, manifest)
    payload = json.loads(manifest.read_text())
    payload["service_revision"] = "f" * 40
    manifest.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="does not match"):
        build_manifest.verify(tmp_path, manifest)
    build_manifest.generate(tmp_path, manifest)
    (tmp_path / "packages" / "code.py").write_text("changed")
    with pytest.raises(RuntimeError, match="does not match"):
        build_manifest.verify(tmp_path, manifest)
    (tmp_path / "packages" / "code.py").unlink()
    build_manifest.generate(tmp_path, manifest)
    (tmp_path / "docker" / "infinity-context-entrypoint.sh").write_text("changed\n")
    with pytest.raises(RuntimeError, match="does not match"):
        build_manifest.verify(tmp_path, manifest)
    (tmp_path / "docker" / "infinity-context-entrypoint.sh").write_text("#!/bin/sh\n")
    build_manifest.generate(tmp_path, manifest)
    (tmp_path / "README.md").write_text("changed\n")
    with pytest.raises(RuntimeError, match="does not match"):
        build_manifest.verify(tmp_path, manifest)
