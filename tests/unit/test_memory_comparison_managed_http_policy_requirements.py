import pytest
from infinity_context_server.memory_comparison_managed_http_policy_requirements import (
    ManagedPolicyObservationContractError,
    ManagedQdrantDeleteObservation,
    ManagedQdrantDeletePassObservation,
    ManagedQdrantPointIdentity,
)


def _pass(
    pass_index: int,
    *,
    point: ManagedQdrantPointIdentity,
    present_before: tuple[ManagedQdrantPointIdentity, ...],
) -> ManagedQdrantDeletePassObservation:
    return ManagedQdrantDeletePassObservation(
        pass_index=pass_index,
        target_commitment_sha256="a" * 64,
        expected=(point,),
        present_before=present_before,
        remaining=(),
        scoped_point_ids_after=(),
        exact_scoped_count_after=0,
        delete_completed=True,
        verified_absent=True,
    )


def test_qdrant_terminal_observation_rejects_second_pass_reappearance() -> None:
    point = ManagedQdrantPointIdentity("chunk-1", "point-1")

    with pytest.raises(
        ManagedPolicyObservationContractError,
        match="qdrant delete evidence differs",
    ):
        ManagedQdrantDeleteObservation(
            lifecycle_target_identity_sha256="b" * 64,
            ingest_manifest_sha256="c" * 64,
            target_commitment_sha256="a" * 64,
            manifest_binding_sha256="d" * 64,
            expected_chunk_ids=("chunk-1",),
            passes=(
                _pass(1, point=point, present_before=(point,)),
                _pass(2, point=point, present_before=(point,)),
            ),
            verified_absent=True,
        )
