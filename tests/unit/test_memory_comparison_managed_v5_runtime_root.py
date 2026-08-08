from __future__ import annotations

import ast
from pathlib import Path

import pytest
from infinity_context_server import memory_comparison_managed_production_composition as entry
from infinity_context_server.memory_comparison_managed_v5_owned_resources import (
    ManagedV5OwnedResources,
    ManagedV5OwnedResourcesError,
)


class _Resource:
    def __init__(self, name: str, calls: list[str], *, fail: bool = False) -> None:
        self._name = name
        self._calls = calls
        self._fail = fail

    def close(self) -> None:
        self._calls.append(self._name)
        if self._fail:
            raise RuntimeError("private provider detail")


def test_owned_resources_close_once_in_reverse_order() -> None:
    calls: list[str] = []
    owner = ManagedV5OwnedResources((_Resource("first", calls), _Resource("second", calls)))

    owner.close()
    owner.close()

    assert calls == ["second", "first"]
    assert owner.closed is True


def test_owned_resources_continue_closing_and_redact_failure() -> None:
    calls: list[str] = []
    owner = ManagedV5OwnedResources(
        (_Resource("first", calls), _Resource("second", calls, fail=True))
    )

    with pytest.raises(ManagedV5OwnedResourcesError) as caught:
        owner.close()

    assert caught.value.code == "managed_v5_owned_resources_close_failed"
    assert "private provider detail" not in str(caught.value)
    assert calls == ["second", "first"]
    owner.close()


def test_new_root_has_no_legacy_mixed_adapter_imports() -> None:
    package = Path(__file__).parents[2] / "packages/infinity_context_server/infinity_context_server"
    forbidden = {
        "ManagedComparisonHttpExecutionAdapter",
        "ManagedComparisonHttpLifecycleAdapter",
        "ManagedHttpRunnerAdapter",
        "ManagedComparisonHttpPolicyLifecycleAdapter",
    }
    for name in (
        "memory_comparison_managed_v5_runtime_factory.py",
        "memory_comparison_managed_v5_production_runner.py",
    ):
        tree = ast.parse((package / name).read_text())
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert imported.isdisjoint(forbidden)


def test_public_activation_precedes_runtime_construction() -> None:
    package = Path(__file__).parents[2] / "packages/infinity_context_server/infinity_context_server"
    source = (package / "memory_comparison_managed_v5_production_runner.py").read_text()

    assert source.index("_activate_managed_v5_public_run(") < source.index(
        "create_managed_v5_production_runtime("
    )


@pytest.mark.parametrize(
    "mode,legacy,v5,code",
    (
        (entry.MANAGED_PRODUCTION_EXECUTION_V5, object(), None, "v5_selection_invalid"),
        (
            entry.MANAGED_PRODUCTION_EXECUTION_LEGACY_HTTP,
            None,
            object(),
            "legacy_selection_invalid",
        ),
        ("unknown", None, None, "execution_mode_invalid"),
    ),
)
def test_public_production_selector_never_falls_back(
    mode: str,
    legacy: object | None,
    v5: object | None,
    code: str,
) -> None:
    with pytest.raises(entry.ManagedProductionCompositionError, match=code):
        entry.run_selected_managed_production_comparison(
            execution_mode=mode,
            legacy_prepared=legacy,
            v5_execution=v5,
        )
