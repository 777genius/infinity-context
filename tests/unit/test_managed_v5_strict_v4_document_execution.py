from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_core.features.projection_receipts import ProjectionReceiptError
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    strict_v4_preparation_key_commitment,
)
from infinity_context_server import (
    memory_comparison_managed_v5_strict_v4_document_execution as execution,
)


class _Keys:
    def __init__(self, key: bytes) -> None:
        self.key = key

    def resolve(self, *, purpose: str, key_id: str) -> bytes:
        assert (purpose, key_id) == ("expected-index", "index-key")
        return self.key


class _Index:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _receipt(tmp_path: Path, key: bytes):
    run = "a" * 64
    path = tmp_path / "index.sqlite3"
    return SimpleNamespace(
        run_id_sha256=run,
        expected_index_path=str(path),
        expected_index_key_id="index-key",
        expected_index_key_commitment_sha256=strict_v4_preparation_key_commitment(
            key,
            purpose="expected-index",
            key_id="index-key",
            artifact_context=f"{run}:{path}",
        ),
        expected_index_terminal_sha256="b" * 64,
        a2_context=object(),
        a2_authority=object(),
    )


def test_document_recovery_pins_one_index_for_corpus_and_document(tmp_path, monkeypatch) -> None:
    asyncio.run(_document_recovery_contract(tmp_path, monkeypatch))


async def _document_recovery_contract(tmp_path, monkeypatch) -> None:
    key = b"k" * 32
    receipt = _receipt(tmp_path, key)
    index = _Index()

    async def recover(**_kwargs):
        return receipt

    class IndexType:
        @staticmethod
        def open(_path, **_kwargs):
            return index

    class CorpusDelegate:
        def __init__(self, **_kwargs):
            pass

        def admit_corpus(self, claim):
            return ("corpus", claim)

    class DocumentDelegate:
        def __init__(self, **_kwargs):
            pass

        def admit_document(self, claim):
            return ("document", claim)

    monkeypatch.setattr(execution, "recover_strict_v4_full_run", recover)
    monkeypatch.setattr(execution, "_validate_execution_projector", lambda *_args: None)
    monkeypatch.setattr(execution, "SQLiteManagedCleanupV3ExpectedRowAuthority", IndexType)
    monkeypatch.setattr(execution, "ExpectedIndexStrictV4FactAuthority", CorpusDelegate)
    monkeypatch.setattr(execution, "ExpectedIndexStrictV4DocumentAuthority", DocumentDelegate)

    authority = await execution.recover_strict_v4_document_authority(
        receipt_store=object(),
        registration_port=object(),
        authenticator=object(),
        key_identity_authority=_Keys(key),
        expected_projector=object(),
    )
    assert authority.receipt is receipt
    assert authority.admit_corpus("claim") == ("corpus", "claim")
    assert authority.admit_document("claim") == ("document", "claim")
    authority.close()
    assert index.closed
    with pytest.raises(ProjectionReceiptError, match="document_authority_closed"):
        authority.admit_document("claim")


def test_document_recovery_rejects_index_key_drift(tmp_path, monkeypatch) -> None:
    asyncio.run(_document_key_drift_contract(tmp_path, monkeypatch))


async def _document_key_drift_contract(tmp_path, monkeypatch) -> None:
    receipt = _receipt(tmp_path, b"a" * 32)

    async def recover(**_kwargs):
        return receipt

    monkeypatch.setattr(execution, "recover_strict_v4_full_run", recover)
    monkeypatch.setattr(execution, "_validate_execution_projector", lambda *_args: None)
    with pytest.raises(ProjectionReceiptError, match="key_binding_invalid"):
        await execution.recover_strict_v4_document_authority(
            receipt_store=object(),
            registration_port=object(),
            authenticator=object(),
            key_identity_authority=_Keys(b"b" * 32),
            expected_projector=object(),
        )


def test_document_projector_binding_rejects_pair_terminal_drift(monkeypatch) -> None:
    class Projector:
        pass

    monkeypatch.setattr(execution, "ManagedV5CleanupV4OperationProjector", Projector)
    bindings = SimpleNamespace(
        run_id="run",
        profile_id="mem0-longmemeval-top50-v1",
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
    projector.original_pair_authority = SimpleNamespace(terminal_commitment_sha256="3" * 64)
    receipt = SimpleNamespace(
        profile_id=bindings.profile_id,
        dataset_sha256=bindings.dataset_sha256,
        run_id_sha256=hashlib.sha256(b"run").hexdigest(),
        binding_commitment_sha256=bindings.binding_commitment_sha256,
        methodology_commitment_sha256=bindings.methodology_commitment_sha256,
        admission_commitment_sha256=projector.admission_commitment_sha256,
        ingestion_root_sha256=projector.manifest_authority.ingestion_root_sha256,
        original_pair_terminal_sha256="0" * 64,
        a2_context=SimpleNamespace(
            case_manifest_sha256=projector.projection.case_manifest_sha256,
            publishable_profile_commitment_sha256=(
                projector.projection.publishable_profile_commitment_sha256
            ),
            infinity_target_identity_sha256="d" * 64,
        ),
    )
    with pytest.raises(ProjectionReceiptError, match="document_projection_invalid"):
        execution._validate_execution_projector(receipt, projector)
