from __future__ import annotations

# ruff: noqa: E402 - pinned upstream is an explicit test-only parity dependency.
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER_ROOT = ROOT / "benchmarks" / "mem0-oss-adapter-v5"
CONTRACT_FILE = (ADAPTER_ROOT / "mem0_oss_adapter_v5" / "extraction_contract.py").resolve()
sys.path.insert(0, str(ADAPTER_ROOT))

from infinity_context_server import (
    memory_comparison_managed_mem0_v5_extraction_contract_binding as subject,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_projection import (
    MEM0_V5_EXTRACTION_IMPLEMENTATION_DOMAIN,
    MEM0_V5_EXTRACTION_IMPLEMENTATION_SHA256,
    MEM0_V5_EXTRACTION_MAX_TOKENS,
    MEM0_V5_EXTRACTION_MODEL,
    MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256,
    MEM0_V5_EXTRACTION_SCHEMA_SHA256,
    MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256,
)
from mem0_oss_adapter_v5 import extraction_contract


def _readonly_contract(tmp_path: Path) -> Path:
    target = tmp_path / "extraction_contract.py"
    target.write_bytes(CONTRACT_FILE.read_bytes())
    target.chmod(0o444)
    return target.resolve()


def test_reviewed_deployed_contract_binds_exact_native_projection_authority(
    tmp_path: Path,
) -> None:
    reviewed_file = _readonly_contract(tmp_path)
    binding = subject.ManagedMem0V5ExtractionContractBinding(
        reviewed_file,
        subject.REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SHA256,
    )

    assert hashlib.sha256(reviewed_file.read_bytes()).hexdigest() == binding.contract_file_sha256
    assert binding.implementation_domain == MEM0_V5_EXTRACTION_IMPLEMENTATION_DOMAIN
    assert binding.implementation_sha256 == MEM0_V5_EXTRACTION_IMPLEMENTATION_SHA256
    assert binding.system_prompt_sha256 == MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256
    assert binding.system_prompt_sha256 == extraction_contract.EXTRACTION_SYSTEM_PROMPT_SHA256
    assert binding.response_format_sha256 == MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256
    assert binding.response_format_sha256 == extraction_contract.EXTRACTION_RESPONSE_FORMAT_SHA256
    assert binding.response_schema_sha256 == MEM0_V5_EXTRACTION_SCHEMA_SHA256
    assert binding.response_schema_sha256 == extraction_contract.EXTRACTION_SCHEMA_SHA256
    assert binding.model == MEM0_V5_EXTRACTION_MODEL
    assert binding.requested_output_tokens == MEM0_V5_EXTRACTION_MAX_TOKENS
    subject.require_managed_mem0_v5_extraction_contract_binding(binding)
    assert not hasattr(binding, "contract_file")


def test_wrong_caller_hash_is_not_a_dead_field_and_file_is_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_bytes = 0
    original_read = subject.os.read

    def tracked_read(descriptor: int, size: int) -> bytes:
        nonlocal read_bytes
        chunk = original_read(descriptor, size)
        read_bytes += len(chunk)
        return chunk

    monkeypatch.setattr(subject.os, "read", tracked_read)
    reviewed_file = _readonly_contract(tmp_path)
    with pytest.raises(
        subject.ManagedMem0V5ExtractionContractBindingError,
        match="contract_file_invalid",
    ):
        subject.ManagedMem0V5ExtractionContractBinding(reviewed_file, "f" * 64)
    assert read_bytes == subject.REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SIZE_BYTES


def test_wrong_file_content_and_symlink_are_rejected(tmp_path: Path) -> None:
    raw = bytearray(CONTRACT_FILE.read_bytes())
    raw[-1] ^= 1
    wrong = tmp_path / "extraction_contract.py"
    wrong.write_bytes(raw)
    wrong.chmod(0o444)
    with pytest.raises(subject.ManagedMem0V5ExtractionContractBindingError):
        subject.ManagedMem0V5ExtractionContractBinding(
            wrong.resolve(),
            subject.REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SHA256,
        )

    symlink = tmp_path / "contract-link.py"
    symlink.symlink_to(CONTRACT_FILE)
    with pytest.raises(subject.ManagedMem0V5ExtractionContractBindingError):
        subject.ManagedMem0V5ExtractionContractBinding(
            symlink.absolute(),
            subject.REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SHA256,
        )


def test_writable_public_mode_is_rejected(tmp_path: Path) -> None:
    copied = tmp_path / "extraction_contract.py"
    copied.write_bytes(CONTRACT_FILE.read_bytes())
    copied.chmod(0o666)
    with pytest.raises(subject.ManagedMem0V5ExtractionContractBindingError):
        subject.ManagedMem0V5ExtractionContractBinding(
            copied.resolve(),
            subject.REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SHA256,
        )
