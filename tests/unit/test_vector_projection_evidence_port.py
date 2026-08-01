import hashlib
from dataclasses import fields

import pytest
from infinity_context_core.ports.vector_projection_evidence import (
    VectorProjectionDeleteEvidence,
    VectorProjectionPointIdentity,
    VectorProjectionPresenceEvidence,
    VectorProjectionScope,
)


def _scope() -> VectorProjectionScope:
    return VectorProjectionScope(
        space_id="space_1",
        memory_scope_id="memory_scope_1",
        thread_id=None,
        projection_version="v1",
    )


def test_vector_projection_evidence_accepts_only_identity_safe_fields() -> None:
    target = hashlib.sha256(b"qdrant\x00collection_1").hexdigest()
    point = VectorProjectionPointIdentity("chunk_1", "point_1")

    presence = VectorProjectionPresenceEvidence(
        scope=_scope(),
        target_commitment_sha256=target,
        expected=(point,),
        observed=(point,),
        scoped_point_ids=("point_1",),
        exact_scoped_count=1,
    )
    deletion = VectorProjectionDeleteEvidence(
        scope=_scope(),
        target_commitment_sha256=target,
        pass_index=2,
        expected=(point,),
        present_before=(),
        remaining=(),
        scoped_point_ids_after=(),
        exact_scoped_count_after=0,
        delete_completed=True,
    )

    assert presence.complete is True
    assert deletion.verified_absent is True
    assert presence.target_commitment_sha256 == deletion.target_commitment_sha256
    assert {field.name for field in fields(VectorProjectionPointIdentity)} == {
        "chunk_id",
        "point_id",
    }
    assert "text" not in {field.name for field in fields(VectorProjectionPresenceEvidence)}
    assert "vector" not in {field.name for field in fields(VectorProjectionPresenceEvidence)}


def test_vector_projection_evidence_rejects_unbound_or_inexact_claims() -> None:
    point = VectorProjectionPointIdentity("chunk_1", "point_1")

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        VectorProjectionPresenceEvidence(
            scope=_scope(),
            target_commitment_sha256="collection_1",
            expected=(point,),
            observed=(point,),
            scoped_point_ids=("point_1",),
            exact_scoped_count=1,
        )

    incomplete = VectorProjectionPresenceEvidence(
        scope=_scope(),
        target_commitment_sha256="0" * 64,
        expected=(point,),
        observed=(),
        scoped_point_ids=(),
        exact_scoped_count=0,
        issues=("qdrant.evidence_expected_points_missing",),
    )

    assert incomplete.complete is False
