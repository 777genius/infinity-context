"""Explicit import policy for optional Infinity Context integration contracts."""

from __future__ import annotations

import importlib
import os
from types import ModuleType

import pytest

_REQUIRE_ROOT_CONTRACTS_ENV = "MEM0_ADAPTER_REQUIRE_ROOT_CONTRACTS"


def import_root_contract(
    module_name: str,
    *,
    allow_module_level: bool = False,
) -> ModuleType:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if os.getenv(_REQUIRE_ROOT_CONTRACTS_ENV) == "1":
            raise RuntimeError(
                f"required Infinity Context contract could not import: {module_name}"
            ) from exc
        pytest.skip(
            f"standalone adapter run has no root contract: {module_name}",
            allow_module_level=allow_module_level,
        )
