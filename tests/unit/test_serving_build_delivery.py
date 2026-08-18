from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_selfhost_build_has_explicit_attested_entrypoint() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "self-hosted-team-deployment.md").read_text(
        encoding="utf-8"
    )

    assert "COPY build /opt/infinity-context/source-build" in dockerfile
    assert "if [ -f /opt/infinity-context/source-build/" in dockerfile
    assert "infinity-context-selfhost-up: infinity-context-source-manifest" in makefile
    assert "make infinity-context-selfhost-up" in runbook


def test_local_bind_mount_is_explicitly_unattested() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "MEMORY_SERVICE_BUILD_IDENTITY_PATH: /run/infinity-context/unattested-" in compose
