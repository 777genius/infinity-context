"""Immutable reviewed-file authority for the native Mem0 v5 projector."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_projection import (
    MEM0_V5_EXTRACTION_IMPLEMENTATION_DOMAIN,
    MEM0_V5_EXTRACTION_IMPLEMENTATION_SHA256,
    MEM0_V5_EXTRACTION_MAX_TOKENS,
    MEM0_V5_EXTRACTION_MODEL,
    MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256,
    MEM0_V5_EXTRACTION_SCHEMA_SHA256,
    MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    canonical_sha256,
    is_sha256,
)

REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SHA256 = (
    "577f40e8f4121a4d337dfcf21fdeb82f8eb093695952e2e3c582df272224ff79"
)
REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SIZE_BYTES = 20_996
_PUBLIC_SOURCE_MODES = frozenset({0o400, 0o440, 0o444})
_BINDING_SEAL = object()


class ManagedMem0V5ExtractionContractBindingError(ValueError):
    """The deployed extraction contract is not the reviewed native authority."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True, init=False)
class ManagedMem0V5ExtractionContractBinding:
    """Nominal binding issued only after stable reviewed source-file validation."""

    contract_file_sha256: str
    implementation_domain: str
    implementation_sha256: str
    system_prompt_sha256: str
    response_format_sha256: str
    response_schema_sha256: str
    model: str
    requested_output_tokens: int
    commitment_sha256: str
    _seal: object = field(repr=False, compare=False)

    def __init__(self, contract_file: Path, expected_sha256: str) -> None:
        if not isinstance(contract_file, Path) or not is_sha256(expected_sha256):
            _fail("managed_mem0_v5_extraction_contract_binding_invalid")
        observed_sha256 = _read_reviewed_contract_sha256(contract_file)
        if (
            observed_sha256 != REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SHA256
            or expected_sha256 != REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SHA256
            or observed_sha256 != expected_sha256
        ):
            _fail("managed_mem0_v5_extraction_contract_file_invalid")
        values = {
            "contract_file_sha256": observed_sha256,
            "implementation_domain": MEM0_V5_EXTRACTION_IMPLEMENTATION_DOMAIN,
            "implementation_sha256": MEM0_V5_EXTRACTION_IMPLEMENTATION_SHA256,
            "system_prompt_sha256": MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256,
            "response_format_sha256": MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256,
            "response_schema_sha256": MEM0_V5_EXTRACTION_SCHEMA_SHA256,
            "model": MEM0_V5_EXTRACTION_MODEL,
            "requested_output_tokens": MEM0_V5_EXTRACTION_MAX_TOKENS,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "commitment_sha256", canonical_sha256(values))
        object.__setattr__(self, "_seal", _BINDING_SEAL)
        require_managed_mem0_v5_extraction_contract_binding(self)


def require_managed_mem0_v5_extraction_contract_binding(
    binding: ManagedMem0V5ExtractionContractBinding,
) -> None:
    """Reject forged, substituted or mutated extraction bindings."""

    expected = {
        "contract_file_sha256": REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SHA256,
        "implementation_domain": MEM0_V5_EXTRACTION_IMPLEMENTATION_DOMAIN,
        "implementation_sha256": MEM0_V5_EXTRACTION_IMPLEMENTATION_SHA256,
        "system_prompt_sha256": MEM0_V5_EXTRACTION_SYSTEM_PROMPT_SHA256,
        "response_format_sha256": MEM0_V5_EXTRACTION_RESPONSE_FORMAT_SHA256,
        "response_schema_sha256": MEM0_V5_EXTRACTION_SCHEMA_SHA256,
        "model": MEM0_V5_EXTRACTION_MODEL,
        "requested_output_tokens": MEM0_V5_EXTRACTION_MAX_TOKENS,
    }
    try:
        valid = (
            type(binding) is ManagedMem0V5ExtractionContractBinding
            and binding._seal is _BINDING_SEAL
            and all(getattr(binding, name) == value for name, value in expected.items())
            and binding.commitment_sha256 == canonical_sha256(expected)
        )
    except (AttributeError, TypeError, ValueError):
        valid = False
    if not valid:
        _fail("managed_mem0_v5_extraction_contract_binding_invalid")


def _read_reviewed_contract_sha256(path: Path) -> str:
    descriptor: int | None = None
    try:
        if not path.is_absolute() or path.resolve(strict=True) != path or path.is_symlink():
            raise ValueError
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        before = os.lstat(path)
        identity = _identity(opened)
        if (
            identity != _identity(before)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_uid not in {0, os.geteuid()}
            or stat.S_IMODE(opened.st_mode) not in _PUBLIC_SOURCE_MODES
            or opened.st_nlink != 1
            or opened.st_size != REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SIZE_BYTES
        ):
            raise ValueError
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, 65_536):
            digest.update(chunk)
            size += len(chunk)
            if size > REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SIZE_BYTES:
                raise ValueError
        final = os.fstat(descriptor)
        after = os.lstat(path)
        if (
            size != REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SIZE_BYTES
            or identity != _identity(final)
            or identity != _identity(after)
        ):
            raise ValueError
        return digest.hexdigest()
    except (OSError, ValueError):
        _fail("managed_mem0_v5_extraction_contract_file_invalid")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _fail(code: str) -> None:
    raise ManagedMem0V5ExtractionContractBindingError(code) from None


__all__ = (
    "ManagedMem0V5ExtractionContractBinding",
    "ManagedMem0V5ExtractionContractBindingError",
    "REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SHA256",
    "REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SIZE_BYTES",
    "require_managed_mem0_v5_extraction_contract_binding",
)
