from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_docker_runtime_includes_multimodal_system_dependencies() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text()
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text()
    entrypoint = (PROJECT_ROOT / "docker/infinity-context-entrypoint.sh").read_text()

    assert 'ARG INFINITY_CONTEXT_EXTRAS="qdrant,openai,graphiti,mcp,docling,s3"' in dockerfile
    assert 'ARG INFINITY_CONTEXT_PREINSTALL_TORCH_CPU="true"' in dockerfile
    assert (
        'ARG INFINITY_CONTEXT_TORCH_INDEX_URL="https://download.pytorch.org/whl/cpu"'
        in dockerfile
    )
    assert "ffmpeg gosu tesseract-ocr" in dockerfile
    assert 'ENTRYPOINT ["infinity-context-entrypoint"]' in dockerfile
    assert 'exec gosu memo "$@"' in entrypoint
    assert '--index-url "$INFINITY_CONTEXT_TORCH_INDEX_URL" torch torchvision' in dockerfile
    assert (
        "INFINITY_CONTEXT_EXTRAS: "
        "${INFINITY_CONTEXT_DOCKER_BUILD_EXTRAS:-dev,qdrant,openai,graphiti,mcp,docling}" in compose
    )
    assert (
        "INFINITY_CONTEXT_PREINSTALL_TORCH_CPU: "
        "${INFINITY_CONTEXT_PREINSTALL_TORCH_CPU:-true}" in compose
    )
    assert (
        "INFINITY_CONTEXT_TORCH_INDEX_URL: "
        "${INFINITY_CONTEXT_TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}" in compose
    )
    assert '${INFINITY_CONTEXT_LITE_RUNTIME_EXTRAS:-dev}' in compose
    assert '${INFINITY_CONTEXT_LITE_RUNTIME_EXTRAS:-dev,docling}' not in compose
    assert "pip install -e '.[dev,qdrant,openai,graphiti,docling]'" in compose
    assert "MEMORY_TRANSCRIPTION_PROVIDER: ${MEMORY_TRANSCRIPTION_PROVIDER:-disabled}" in compose
    assert (
        compose.count("MEMORY_TRANSCRIPTION_PROVIDER: ${MEMORY_TRANSCRIPTION_PROVIDER:-openai}")
        == 3
    )
    assert (
        "MEMORY_EXTRACTION_CANCELLATION_POLL_SECONDS: "
        "${MEMORY_EXTRACTION_CANCELLATION_POLL_SECONDS:-1}" in compose
    )
    assert (
        "MEMORY_EXTRACTION_HEARTBEAT_SECONDS: "
        "${MEMORY_EXTRACTION_HEARTBEAT_SECONDS:-15}" in compose
    )
    assert "MEMORY_TRANSCRIPTION_OPENAI_MODEL" in compose
