#!/usr/bin/env python3
"""Build-time cache staging for the exact FastEmbed-resolved offline artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download

from mem0_oss_adapter.embedding import verify_pinned_model_directory
from mem0_oss_adapter.runtime_pin import RUNTIME_PIN

_REQUIRED_FILES = (
    "config.json",
    "model_optimized.onnx",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=RUNTIME_PIN.embedding_source_repository,
        revision=RUNTIME_PIN.embedding_model_revision,
        local_dir=destination,
        allow_patterns=list(_REQUIRED_FILES),
    )
    verify_pinned_model_directory(destination)


if __name__ == "__main__":
    main()
