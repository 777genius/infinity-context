from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_docker_runtime_includes_multimodal_system_dependencies() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text()
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text()

    assert 'ARG MEMO_STACK_EXTRAS="qdrant,openai,graphiti,mcp,docling"' in dockerfile
    assert 'ARG MEMO_STACK_PREINSTALL_TORCH_CPU="true"' in dockerfile
    assert 'ARG MEMO_STACK_TORCH_INDEX_URL="https://download.pytorch.org/whl/cpu"' in dockerfile
    assert "ffmpeg tesseract-ocr" in dockerfile
    assert '--index-url "$MEMO_STACK_TORCH_INDEX_URL" torch torchvision' in dockerfile
    assert "MEMO_STACK_EXTRAS: dev,qdrant,openai,graphiti,mcp,docling" in compose
    assert "MEMO_STACK_PREINSTALL_TORCH_CPU: ${MEMO_STACK_PREINSTALL_TORCH_CPU:-true}" in compose
    assert "MEMO_STACK_TORCH_INDEX_URL: ${MEMO_STACK_TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}" in compose
    assert "pip install -e '.[dev,docling]'" in compose
    assert "pip install -e '.[dev,qdrant,openai,graphiti,docling]'" in compose
    assert "MEMORY_TRANSCRIPTION_PROVIDER" in compose
    assert "MEMORY_TRANSCRIPTION_OPENAI_MODEL" in compose
