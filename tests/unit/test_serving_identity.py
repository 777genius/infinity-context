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
            Path("infinity_context_server/__init__.py"),
            Path("infinity_context-0.1.dist-info/METADATA"),
        )

    def locate_file(self, path: object) -> Path:
        return self.root / str(path)


class InfoResponse:
    def __init__(self, payload: dict[str, str], url: str = "http://tei.test/info") -> None:
        self.data = json.dumps(payload).encode()
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.data

    def geturl(self) -> str:
        return self.url


def settings_with_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides
) -> Settings:
    root = tmp_path / "installed"
    module = root / "infinity_context_server" / "__init__.py"
    metadata = root / "infinity_context-0.1.dist-info" / "METADATA"
    module.parent.mkdir(parents=True, exist_ok=True)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    module.write_text("VERSION = 1\n")
    metadata.write_text("Name: infinity-context\n")
    distribution = Distribution(root)
    monkeypatch.setattr(build_identity.importlib.metadata, "distribution", lambda _n: distribution)
    monkeypatch.setattr(
        build_identity.importlib, "import_module", lambda _n: SimpleNamespace(__file__=module)
    )
    source = tmp_path / "source.json"
    source.write_text(json.dumps({
        "schema_version": "infinity-context.source-build.v1",
        "service_revision": SERVICE_SHA,
        "source_tree_digest_sha256": "sha256:" + "c" * 64,
    }))
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
    monkeypatch.setattr(tei_probe, "_open_info", lambda *_a, **_k: InfoResponse(payload))
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
        service_build_identity_path=str(tmp_path / "missing"), embeddings_enabled=True,
        embeddings_model_revision=MODEL_SHA, embeddings_runtime_build_revision=TEI_SHA,
        embeddings_runtime_info_url="http://tei.test/info",
        embeddings_base_url="http://tei.test/v1",
    )
    with pytest.raises(RuntimeError, match="verified service build manifest"):
        build_verified_serving_profile(settings)


def test_info_redirect_and_replaced_runtime_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = tei_probe.TeiProbe.create(
        model_id="model", model_sha=MODEL_SHA, build_sha=TEI_SHA,
        inference_base_url="http://tei.test/v1", info_url="http://tei.test/info",
    )
    payload = {"model_id": "model", "model_sha": MODEL_SHA, "sha": TEI_SHA}
    monkeypatch.setattr(
        tei_probe, "_open_info", lambda *_a, **_k: InfoResponse(payload, "http://evil/info")
    )
    with pytest.raises(RuntimeError, match="redirected"):
        probe.verify()
    payload["sha"] = "f" * 40
    monkeypatch.setattr(tei_probe, "_open_info", lambda *_a, **_k: InfoResponse(payload))
    with pytest.raises(RuntimeError, match="frozen profile"):
        probe.verify()


def test_distribution_rejects_shadow_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "installed"
    module = root / "infinity_context_server" / "__init__.py"
    metadata = root / "infinity_context-0.1.dist-info" / "METADATA"
    module.parent.mkdir(parents=True)
    metadata.parent.mkdir(parents=True)
    module.write_text("ok")
    metadata.write_text("ok")
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
    (tmp_path / "packages" / "code.py").write_text("changed")
    with pytest.raises(RuntimeError, match="does not match"):
        build_manifest.verify(tmp_path, manifest)
