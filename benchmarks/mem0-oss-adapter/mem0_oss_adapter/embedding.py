"""Offline-only FastEmbed integration for the immutable bundled ONNX artifact."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from mem0.configs.embeddings.base import BaseEmbedderConfig

from mem0_oss_adapter.runtime_pin import RUNTIME_PIN

_DIMENSIONS = 384


class OfflineFastEmbedEmbedding:
    """Mem0-compatible dense embedder that cannot fetch a model at runtime."""

    def __init__(self, config: BaseEmbedderConfig) -> None:
        model = getattr(config, "model", None)
        if model not in {None, RUNTIME_PIN.embedding_model}:
            raise ValueError("FastEmbed model does not match the runtime pin")
        model_dir = Path(os.environ.get("MEM0_OSS_FASTEMBED_MODEL_DIR", ""))
        verify_pinned_model_directory(model_dir)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from fastembed import TextEmbedding

        self.config = config
        self.config.model = RUNTIME_PIN.embedding_model
        self.config.embedding_dims = _DIMENSIONS
        self._model = TextEmbedding(
            model_name=RUNTIME_PIN.embedding_model,
            cache_dir=str(model_dir.parent),
            specific_model_path=str(model_dir),
            local_files_only=True,
            providers=["CPUExecutionProvider"],
            cuda=False,
        )
        if self._model.embedding_size != _DIMENSIONS:
            raise RuntimeError("FastEmbed model dimensions do not match the runtime pin")

    def embed(self, text: str, memory_action: str | None = None) -> list[float]:
        del memory_action
        values = list(self._model.embed([_safe_text(text)]))
        if len(values) != 1:
            raise RuntimeError("FastEmbed returned an unexpected vector count")
        return _vector(values[0])

    def embed_batch(
        self,
        texts: Iterable[str],
        memory_action: str | None = None,
    ) -> list[list[float]]:
        del memory_action
        materialized = [_safe_text(text) for text in texts]
        if not materialized:
            return []
        values = list(self._model.embed(materialized))
        if len(values) != len(materialized):
            raise RuntimeError("FastEmbed returned an unexpected batch vector count")
        return [_vector(value) for value in values]


def verify_pinned_model_directory(model_dir: Path) -> None:
    """Prove the actual FastEmbed-resolved ONNX file is present before inference."""

    if not model_dir.is_dir() or model_dir.is_symlink():
        raise RuntimeError("offline FastEmbed model directory is unavailable")
    required_files = {
        "config.json",
        "model_optimized.onnx",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.txt",
    }
    for filename in required_files:
        candidate = model_dir / filename
        if not candidate.is_file() or candidate.is_symlink():
            raise RuntimeError("offline FastEmbed model files are incomplete")
    onnx_path = model_dir / RUNTIME_PIN.embedding_onnx_filename
    digest = hashlib.sha256(onnx_path.read_bytes()).hexdigest()
    if digest != RUNTIME_PIN.embedding_onnx_sha256:
        raise RuntimeError("offline FastEmbed ONNX artifact does not match runtime pin")


def _safe_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("embedding text must be a non-empty string")
    return value.replace("\n", " ")


def _vector(value: Any) -> list[float]:
    raw = value.tolist() if hasattr(value, "tolist") else list(value)
    if not isinstance(raw, list) or len(raw) != _DIMENSIONS:
        raise RuntimeError("FastEmbed vector dimensions do not match runtime pin")
    return [float(item) for item in raw]
