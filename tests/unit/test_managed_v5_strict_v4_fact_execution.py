from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_core.features.projection_receipts import ProjectionReceiptError
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    strict_v4_preparation_key_commitment,
)
from infinity_context_server import (
    memory_comparison_managed_v5_strict_v4_fact_execution as execution,
)


class _Keys:
    def __init__(self, key: bytes) -> None:
        self.key = key
        self.calls = []

    def resolve(self, *, purpose: str, key_id: str) -> bytes:
        self.calls.append((purpose, key_id))
        return self.key


class _Index:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _receipt(tmp_path: Path, key: bytes):
    run = "a" * 64
    path = tmp_path / "expected.sqlite3"
    key_id = "expected-index-key"
    return SimpleNamespace(
        run_id_sha256=run,
        expected_index_path=str(path),
        expected_index_key_id=key_id,
        expected_index_key_commitment_sha256=strict_v4_preparation_key_commitment(
            key,
            purpose="expected-index",
            key_id=key_id,
            artifact_context=f"{run}:{path}",
        ),
        expected_index_terminal_sha256="b" * 64,
        a2_context=object(),
        a2_authority=object(),
    )


def test_recovery_pins_index_and_closes_owned_capability(tmp_path, monkeypatch) -> None:
    asyncio.run(_recovery_pins_index_and_closes_owned_capability(tmp_path, monkeypatch))


async def _recovery_pins_index_and_closes_owned_capability(tmp_path, monkeypatch) -> None:
    key = b"k" * 32
    receipt = _receipt(tmp_path, key)
    index = _Index()
    captured = {}

    async def recover(**kwargs):
        captured["recovery"] = kwargs
        return receipt

    class IndexType:
        @staticmethod
        def open(path, **kwargs):
            captured["open"] = (path, kwargs)
            return index

    class Delegate:
        def __init__(self, **kwargs):
            captured["delegate"] = kwargs

        def admit_fact(self, claim):
            return ("admitted", claim)

    monkeypatch.setattr(execution, "recover_strict_v4_full_run", recover)
    monkeypatch.setattr(execution, "SQLiteManagedCleanupV3ExpectedRowAuthority", IndexType)
    monkeypatch.setattr(execution, "ExpectedIndexStrictV4FactAuthority", Delegate)
    keys = _Keys(key)

    authority = await execution.recover_strict_v4_fact_authority(
        receipt_store="receipt-store",
        registration_port="registration-port",
        authenticator="authenticator",
        key_identity_authority=keys,
    )
    assert keys.calls == [("expected-index", receipt.expected_index_key_id)]
    assert captured["open"] == (
        receipt.expected_index_path,
        {
            "context": receipt.a2_context,
            "authority": receipt.a2_authority,
            "authentication_key": key,
        },
    )
    assert captured["delegate"]["lookup"] is index
    assert authority.receipt is receipt
    assert authority.admit_fact("claim") == ("admitted", "claim")
    authority.close()
    assert index.closed
    with pytest.raises(ProjectionReceiptError, match="fact_authority_closed"):
        authority.admit_fact("claim")
    with pytest.raises(ProjectionReceiptError, match="fact_authority_closed"):
        _ = authority.receipt


def test_recovery_rejects_key_drift_before_open(tmp_path, monkeypatch) -> None:
    asyncio.run(_recovery_rejects_key_drift_before_open(tmp_path, monkeypatch))


async def _recovery_rejects_key_drift_before_open(tmp_path, monkeypatch) -> None:
    receipt = _receipt(tmp_path, b"a" * 32)

    async def recover(**_kwargs):
        return receipt

    monkeypatch.setattr(execution, "recover_strict_v4_full_run", recover)
    with pytest.raises(ProjectionReceiptError, match="key_binding_invalid"):
        await execution.recover_strict_v4_fact_authority(
            receipt_store=object(),
            registration_port=object(),
            authenticator=object(),
            key_identity_authority=_Keys(b"b" * 32),
        )


def test_execution_projector_binding_rejects_case_manifest_drift(monkeypatch) -> None:
    class Projector:
        pass

    monkeypatch.setattr(execution, "ManagedV5CleanupV4OperationProjector", Projector)
    bindings = SimpleNamespace(
        run_id="run",
        profile_id="mem0-locomo-top50-v1",
        dataset_sha256="a" * 64,
        binding_commitment_sha256="b" * 64,
        methodology_commitment_sha256="c" * 64,
        backend_targets=(
            SimpleNamespace(backend_role="infinity-context", target_identity_sha256="d" * 64),
        ),
    )
    projector = Projector()
    projector.profile_id = bindings.profile_id
    projector.admission_commitment_sha256 = "e" * 64
    projector.projection = SimpleNamespace(
        bindings=bindings,
        case_manifest_sha256="f" * 64,
        publishable_profile_commitment_sha256="1" * 64,
    )
    projector.manifest_authority = SimpleNamespace(ingestion_root_sha256="2" * 64)
    receipt = SimpleNamespace(
        profile_id=bindings.profile_id,
        dataset_sha256=bindings.dataset_sha256,
        run_id_sha256=execution.hashlib.sha256(b"run").hexdigest(),
        binding_commitment_sha256=bindings.binding_commitment_sha256,
        methodology_commitment_sha256=bindings.methodology_commitment_sha256,
        admission_commitment_sha256=projector.admission_commitment_sha256,
        ingestion_root_sha256=projector.manifest_authority.ingestion_root_sha256,
        a2_context=SimpleNamespace(
            case_manifest_sha256="0" * 64,
            publishable_profile_commitment_sha256=(
                projector.projection.publishable_profile_commitment_sha256
            ),
            infinity_target_identity_sha256="d" * 64,
        ),
    )
    with pytest.raises(ProjectionReceiptError, match="fact_projection_invalid"):
        execution._validate_execution_projector(receipt, projector)
