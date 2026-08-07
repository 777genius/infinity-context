from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from mem0_oss_adapter_v5.cleanup import seal_cleanup_snapshot
from mem0_oss_adapter_v5.cleanup_evidence import decode, encode
from mem0_oss_adapter_v5.mem0_storage import StorageSnapshot, VectorProjection


def _snapshot() -> StorageSnapshot:
    return StorageSnapshot(
        vectors=(
            VectorProjection(
                provider_memory_id="provider-1",
                extraction_memory_id="memory-1",
                text="Alice likes tea. secret-token",
                attributed_to="user",
                linked_memory_ids=(),
            ),
        ),
        history_memory_ids=("provider-1",),
        message_ids=(),
        entity_links=(),
    )


def test_v2_evidence_is_content_free_authenticated_and_tamper_evident() -> None:
    snapshot = _snapshot()
    seal = seal_cleanup_snapshot(snapshot)
    unit_identity = hashlib.sha256(b"unit").hexdigest()
    encoded = encode(
        unit_identity_sha256=unit_identity,
        before=seal,
        runtime_receipt_sha256=None,
        receipt=None,
        hmac_key=b"k" * 32,
    )

    assert b"Alice likes tea." not in encoded
    assert b"secret-token" not in encoded
    assert (
        decode(json.loads(encoded), unit_identity_sha256=unit_identity, hmac_key=b"k" * 32)[0]
        == seal
    )

    payload = json.loads(encoded)
    payload["cleanup_seal"]["vector_projections"][0]["projection_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="cleanup_evidence_invalid"):
        decode(payload, unit_identity_sha256=unit_identity, hmac_key=b"k" * 32)


def test_vector_text_change_has_a_different_projection_digest() -> None:
    snapshot = _snapshot()
    changed = replace(
        snapshot,
        vectors=(replace(snapshot.vectors[0], text="Alice dislikes tea."),),
    )
    assert (
        seal_cleanup_snapshot(snapshot).vector_projections
        != seal_cleanup_snapshot(changed).vector_projections
    )
