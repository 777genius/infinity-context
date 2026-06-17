from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

DEFAULT_DOCLING_MIN_TEMP_BYTES = 1_000_000_000


def apply_stable_ml_env(temp_dir: Path | None = None) -> None:
    if temp_dir is not None:
        temp_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("TMPDIR", str(temp_dir))
        os.environ.setdefault("TMP", str(temp_dir))
        os.environ.setdefault("TEMP", str(temp_dir))
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def skip_if_low_temp_space(
    temp_path: Path,
    *,
    label: str = "Docling e2e",
) -> None:
    threshold = int(
        os.environ.get(
            "MEMO_STACK_DOCLING_E2E_MIN_TEMP_BYTES",
            str(DEFAULT_DOCLING_MIN_TEMP_BYTES),
        )
    )
    available = shutil.disk_usage(temp_path).free
    if available < threshold:
        pytest.skip(
            f"{label} needs enough temp disk for ML/OpenMP and SQLite artifacts: "
            f"available={available}, required={threshold}"
        )


def docling_worker_timeout_seconds(env: dict[str, str]) -> int:
    parser_timeout = int(float(env.get("MEMORY_EXTRACTION_PARSER_TIMEOUT_SECONDS", "300")))
    configured = int(os.environ.get("MEMO_STACK_DOCLING_E2E_WORKER_TIMEOUT_SECONDS", "0"))
    return max(configured, parser_timeout + 120, 180)
