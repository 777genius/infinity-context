from __future__ import annotations

import ast
import asyncio
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import infinity_context_core.ports.managed_cleanup_v4_authority as authority_contract
import pytest
from infinity_context_core.application.use_cases.managed_cleanup_v4_legacy_authority import (
    LegacyV2CleanupAuthorityAdapter,
)
from infinity_context_core.application.use_cases.managed_cleanup_v4_lifecycle import (
    ManagedCleanupV4InitiationReceipt,
    ManagedCleanupV4TerminalReceipt,
    build_cleanup_v4_terminal_bindings,
    complete_managed_cleanup_v4,
    initiate_managed_cleanup_v4,
)
from infinity_context_core.features.projection_receipts import ProjectionReceiptAuthenticator
from infinity_context_core.ports.benchmark_cleanup_plan import (
    ManagedBenchmarkCleanupPlan,
    managed_benchmark_cleanup_plan_material_sha256,
)
from infinity_context_core.ports.managed_cleanup_v4_authority import (
    ManagedCleanupV4AuthorityError,
    StrictV4CleanupAuthorityResolver,
    build_legacy_v2_cleanup_authority,
    build_strict_v4_cleanup_authority,
    build_strict_v4_cleanup_authority_readback,
)

RUN = "1" * 64
CONTEXT = "2" * 64
A2 = "3" * 64
INVENTORY = "4" * 64
QDRANT = ("5" * 64, "6" * 64)
GRAPHITI = ("7" * 64, "8" * 64)
COGNEE = "9" * 64
AUTH = ProjectionReceiptAuthenticator(b"managed-cleanup-v4-test-key-material")
AUTH_ARGS = {"authenticator": AUTH, "authentication_key_id": "cleanup-test-key"}
EVIDENCE_ARGS = {
    "preparation_receipt_sha256": "a" * 64,
    "preparation_receipt_mac_sha256": "b" * 64,
    "registration_sha256": "c" * 64,
    "registration_mac_sha256": "d" * 64,
    "writer_authority_sha256": "e" * 64,
    "writer_authority_mac_sha256": "f" * 64,
}


class _StrictReaderWithLegacyTrap:
    def __init__(self, value: object) -> None:
        self.value = value
        self.strict_calls = 0
        self.legacy_calls = 0

    async def read_registered_strict_v4(self, run_id_sha256: str):
        assert run_id_sha256 == RUN
        self.strict_calls += 1
        return self.value

    async def load_cleanup_plan(self, _space_id: str):
        self.legacy_calls += 1
        raise AssertionError("strict resolver called the legacy-v2 cleanup-plan loader")


class _LegacyPlans:
    def __init__(self, plan: ManagedBenchmarkCleanupPlan | None) -> None:
        self.plan = plan
        self.calls: list[str] = []

    async def load_cleanup_plan(self, space_id: str):
        self.calls.append(space_id)
        return self.plan


class _Lifecycle:
    def __init__(self) -> None:
        self.initiation: ManagedCleanupV4InitiationReceipt | None = None
        self.terminal: ManagedCleanupV4TerminalReceipt | None = None
        self.initiation_writes = 0
        self.terminal_writes = 0

    async def read_initiation(self, _run: str):
        return self.initiation

    async def put_initiation(self, receipt: ManagedCleanupV4InitiationReceipt):
        self.initiation_writes += 1
        self.initiation = receipt
        return receipt

    async def read_terminal(self, _run: str):
        return self.terminal

    async def put_terminal(self, receipt: ManagedCleanupV4TerminalReceipt):
        self.terminal_writes += 1
        self.terminal = receipt
        return receipt


def _strict():
    return build_strict_v4_cleanup_authority(
        run_id_sha256=RUN,
        context_sha256=CONTEXT,
        a2_terminal_sha256=A2,
        expected_index_terminal_sha256=A2,
    )


def _run(value):
    return asyncio.run(value)


def _bindings(*, qdrant: tuple[str, str] = QDRANT):
    return build_cleanup_v4_terminal_bindings(
        inventory_terminal_sha256=INVENTORY,
        qdrant_absence_pass_sha256=qdrant,
        graphiti_absence_pass_sha256=GRAPHITI,
        cognee_evidence_sha256=COGNEE,
        context_sha256=CONTEXT,
        a2_terminal_sha256=A2,
    )


def test_strict_resolver_uses_only_registered_a2_and_expected_index() -> None:
    readback = build_strict_v4_cleanup_authority_readback(
        run_id_sha256=RUN,
        context_sha256=CONTEXT,
        a2_terminal_sha256=A2,
        expected_index_terminal_sha256=A2,
        **EVIDENCE_ARGS,
        **AUTH_ARGS,
    )
    reader = _StrictReaderWithLegacyTrap(readback)

    authority = _run(
        StrictV4CleanupAuthorityResolver(run_id_sha256=RUN, reader=reader, **AUTH_ARGS).resolve()
    )

    assert authority == _strict()
    assert reader.strict_calls == 1
    assert reader.legacy_calls == 0


@pytest.mark.parametrize("value", [None, "missing"])
def test_strict_resolver_rejects_missing_readback(value: object) -> None:
    with pytest.raises(ManagedCleanupV4AuthorityError, match="strict_authority_missing"):
        _run(
            StrictV4CleanupAuthorityResolver(
                run_id_sha256=RUN, reader=_StrictReaderWithLegacyTrap(value), **AUTH_ARGS
            ).resolve()
        )


def test_strict_resolver_rejects_tampered_readback() -> None:
    readback = build_strict_v4_cleanup_authority_readback(
        run_id_sha256=RUN,
        context_sha256=CONTEXT,
        a2_terminal_sha256=A2,
        expected_index_terminal_sha256=A2,
        **EVIDENCE_ARGS,
        **AUTH_ARGS,
    )
    object.__setattr__(readback, "context_sha256", "a" * 64)
    with pytest.raises(ManagedCleanupV4AuthorityError, match="strict_readback_invalid"):
        _run(
            StrictV4CleanupAuthorityResolver(
                run_id_sha256=RUN,
                reader=_StrictReaderWithLegacyTrap(readback),
                **AUTH_ARGS,
            ).resolve()
        )


def test_strict_resolver_authenticates_persisted_readback_mac() -> None:
    readback = build_strict_v4_cleanup_authority_readback(
        run_id_sha256=RUN,
        context_sha256=CONTEXT,
        a2_terminal_sha256=A2,
        expected_index_terminal_sha256=A2,
        **EVIDENCE_ARGS,
        **AUTH_ARGS,
    )
    object.__setattr__(readback, "readback_mac_sha256", "a" * 64)
    with pytest.raises(
        ManagedCleanupV4AuthorityError,
        match="strict_readback_authentication_invalid",
    ):
        _run(
            StrictV4CleanupAuthorityResolver(
                run_id_sha256=RUN,
                reader=_StrictReaderWithLegacyTrap(readback),
                **AUTH_ARGS,
            ).resolve()
        )


def test_legacy_adapter_preserves_exact_cleanup_plan_loader() -> None:
    value = {"run_id_sha256": RUN, "space_id": "benchmark-space-test"}
    plan = ManagedBenchmarkCleanupPlan(
        value=value, sha256=managed_benchmark_cleanup_plan_material_sha256(value)
    )
    loader = _LegacyPlans(plan)

    authority = _run(
        LegacyV2CleanupAuthorityAdapter(
            run_id_sha256=RUN,
            space_id="benchmark-space-test",
            cleanup_plans=loader,
        ).resolve()
    )

    assert authority.kind == "legacy_v2_plan"
    assert authority.legacy_plan_sha256 == plan.sha256
    assert loader.calls == ["benchmark-space-test"]


def test_authority_rejects_caller_tamper_and_cross_kind_shape() -> None:
    strict = _strict()
    with pytest.raises(ManagedCleanupV4AuthorityError, match="authority_invalid"):
        replace(strict, authority_sha256="f" * 64)
    with pytest.raises(ManagedCleanupV4AuthorityError, match="digest_invalid"):
        replace(strict, kind="legacy_v2_plan")


def test_strict_authority_import_graph_excludes_legacy_v2_plan_contract() -> None:
    tree = ast.parse(Path(authority_contract.__file__).read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "infinity_context_core.ports.benchmark_cleanup_plan" not in imports
    assert (
        "infinity_context_core.application.use_cases.managed_cleanup_v4_legacy_authority"
        not in imports
    )
    script = """
import sys
from infinity_context_core.ports.managed_cleanup_v4_authority import (
    StrictV4CleanupAuthorityResolver,
)
assert StrictV4CleanupAuthorityResolver
assert (
    'infinity_context_core.application.use_cases.managed_cleanup_v4_legacy_authority'
    not in sys.modules
)
"""
    subprocess.run([sys.executable, "-c", script], check=True)


def test_lifecycle_allows_only_exact_pending_then_complete_transitions() -> None:
    lifecycle = _Lifecycle()
    authority = _strict()

    with pytest.raises(ManagedCleanupV4AuthorityError, match="lifecycle_invalid"):
        _run(
            complete_managed_cleanup_v4(
                authority=authority,
                terminal_bindings=_bindings(),
                lifecycle=lifecycle,
                **AUTH_ARGS,
            )
        )

    first = _run(initiate_managed_cleanup_v4(authority=authority, lifecycle=lifecycle, **AUTH_ARGS))
    replay = _run(
        initiate_managed_cleanup_v4(authority=authority, lifecycle=lifecycle, **AUTH_ARGS)
    )
    assert first.replayed is False
    assert replay.replayed is True
    assert lifecycle.initiation_writes == 1

    completed = _run(
        complete_managed_cleanup_v4(
            authority=authority,
            terminal_bindings=_bindings(),
            lifecycle=lifecycle,
            **AUTH_ARGS,
        )
    )
    completed_replay = _run(
        complete_managed_cleanup_v4(
            authority=authority,
            terminal_bindings=_bindings(),
            lifecycle=lifecycle,
            **AUTH_ARGS,
        )
    )
    assert completed.replayed is False
    assert completed_replay.replayed is True
    assert lifecycle.terminal_writes == 1
    terminal = completed.receipt
    assert isinstance(terminal, ManagedCleanupV4TerminalReceipt)
    assert terminal.terminal_bindings.inventory_terminal_sha256 == INVENTORY
    assert terminal.terminal_bindings.qdrant_absence_pass_sha256 == QDRANT
    assert terminal.terminal_bindings.graphiti_absence_pass_sha256 == GRAPHITI
    assert terminal.terminal_bindings.cognee_evidence_sha256 == COGNEE


def test_cross_kind_replay_and_ordered_absence_tamper_are_rejected() -> None:
    lifecycle = _Lifecycle()
    strict = _strict()
    _run(initiate_managed_cleanup_v4(authority=strict, lifecycle=lifecycle, **AUTH_ARGS))

    legacy = build_legacy_v2_cleanup_authority(run_id_sha256=RUN, legacy_plan_sha256="b" * 64)
    with pytest.raises(ManagedCleanupV4AuthorityError, match="initiation_conflict"):
        _run(initiate_managed_cleanup_v4(authority=legacy, lifecycle=lifecycle, **AUTH_ARGS))

    _run(
        complete_managed_cleanup_v4(
            authority=strict,
            terminal_bindings=_bindings(),
            lifecycle=lifecycle,
            **AUTH_ARGS,
        )
    )
    with pytest.raises(ManagedCleanupV4AuthorityError, match="terminal_conflict"):
        _run(
            complete_managed_cleanup_v4(
                authority=strict,
                terminal_bindings=_bindings(qdrant=tuple(reversed(QDRANT))),
                lifecycle=lifecycle,
                **AUTH_ARGS,
            )
        )


def test_replay_authenticates_mac_and_key_id_before_transition() -> None:
    lifecycle = _Lifecycle()
    authority = _strict()
    _run(initiate_managed_cleanup_v4(authority=authority, lifecycle=lifecycle, **AUTH_ARGS))
    assert lifecycle.initiation is not None
    object.__setattr__(lifecycle.initiation, "receipt_mac_sha256", "a" * 64)
    with pytest.raises(ManagedCleanupV4AuthorityError, match="authentication_invalid"):
        _run(initiate_managed_cleanup_v4(authority=authority, lifecycle=lifecycle, **AUTH_ARGS))


def test_cognee_must_be_not_projected_with_zero_rows() -> None:
    bindings = _bindings()
    with pytest.raises(ManagedCleanupV4AuthorityError, match="absence_terminal_invalid"):
        replace(bindings, cognee_projected_count=1)
    with pytest.raises(ManagedCleanupV4AuthorityError, match="absence_terminal_invalid"):
        replace(bindings, cognee_disposition="projected")
