"""Public and private compatibility seams pinned before policy extraction."""

from __future__ import annotations

import base64
import importlib
import inspect
import json
import pickle
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest
from infinity_context_core.application import context_domain_rerank_signals as legacy
from infinity_context_core.application import context_domain_rerank_types as alternate
from infinity_context_core.application import context_identity_rerank as identity
from infinity_context_core.application.context_causal_reason_rerank import (
    DomainRerankSignal as CausalSignal,
)

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "context_policy_refactor" / "contracts.json"
_CONTRACT = json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("module_name", tuple(_CONTRACT["signatures"]))
def test_original_function_imports_and_signatures_remain_available(module_name: str) -> None:
    module = importlib.import_module(module_name)
    for name, signature in _CONTRACT["signatures"][module_name].items():
        assert str(inspect.signature(getattr(module, name))) == signature, name


def test_both_preexisting_signal_type_families_retain_identity_and_defaults() -> None:
    assert legacy.DomainRerankSignal is CausalSignal
    assert alternate.DomainRerankSignal is identity.DomainRerankSignal
    assert legacy.DomainRerankSignal is not alternate.DomainRerankSignal
    assert legacy.DomainRerankSignal() != alternate.DomainRerankSignal()
    assert legacy.DomainRerankSignal() == legacy.DomainRerankSignal()
    assert alternate.DomainRerankSignal() == alternate.DomainRerankSignal()
    assert legacy.DomainRerankSignal.__module__ == _CONTRACT["legacy_module"]
    assert alternate.DomainRerankSignal.__module__ == _CONTRACT["alternate_module"]
    for signal_type in (legacy.DomainRerankSignal, alternate.DomainRerankSignal):
        assert [[f.name, str(f.type), f.default] for f in fields(signal_type)] == (
            _CONTRACT["fields"]
        )
        with pytest.raises(FrozenInstanceError):
            signal_type().boost = 1.0


def test_legacy_pickle_captured_before_extraction_still_resolves_original_type() -> None:
    # Fixed synthetic bytes, never user-controlled pickle input.
    restored = pickle.loads(base64.b64decode(_CONTRACT["legacy_pickle"]))
    assert type(restored) is legacy.DomainRerankSignal
    assert restored == legacy.DomainRerankSignal(boost=0.03, reason="baseline_legacy")
    assert pickle.loads(pickle.dumps(restored)) == restored


@pytest.mark.parametrize("reverse", (False, True))
def test_policy_imports_succeed_in_fresh_processes_in_both_orders(reverse: bool) -> None:
    application_path = Path(legacy.__file__).parent
    modules = sorted(
        {
            "infinity_context_core.application.context_packer",
            "infinity_context_core.application.context_domain_rerank_apply",
            *(
                f"infinity_context_core.application.{path.stem}"
                for pattern in ("context_domain_rerank_*.py", "context_packer_answer_support*.py")
                for path in application_path.glob(pattern)
            ),
        },
        reverse=reverse,
    )
    # pytest's configured source paths must also be visible to child interpreters.
    script = (
        "import importlib,sys; sys.path[:0]=" + repr(sys.path) + "; "
        "[importlib.import_module(name) for name in " + repr(modules) + "]"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False, timeout=30
    )
    assert result.returncode == 0, result.stderr
