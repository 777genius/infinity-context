"""HTTP clean-state sessions kept separate from benchmark retrieval adapters."""

from __future__ import annotations

import httpx

from infinity_context_server.memory_comparison_clean_state import (
    BackendCleanStateProof,
    CleanStateProofError,
    fresh_namespace_clean_state_proof,
    mem0_delete_clean_state_proof,
    skipped_mem0_clean_state_proof,
)


class InfinityCleanStateSession:
    """Own the fresh namespace evidence for one Infinity benchmark run."""

    def __init__(self, *, backend: str) -> None:
        self._backend = backend
        self._proof: BackendCleanStateProof | None = None

    def reset(
        self,
        client: httpx.Client,
        *,
        run_id: str,
        slug: str,
        corpus_identity_sha256: str,
        expected_scope_count: int,
        attestation_key: bytes,
    ) -> BackendCleanStateProof:
        try:
            response = client.post("/v1/spaces", json={"slug": slug, "name": slug})
        except httpx.HTTPError:
            raise CleanStateProofError("clean_state_namespace_request_failed") from None
        try:
            payload: object = response.json()
        except ValueError:
            raise CleanStateProofError("clean_state_namespace_ack_malformed") from None
        proof = fresh_namespace_clean_state_proof(
            backend=self._backend,
            run_id=run_id,
            expected_slug=slug,
            corpus_identity_sha256=corpus_identity_sha256,
            expected_scope_count=expected_scope_count,
            status_code=response.status_code,
            payload=payload,
            attestation_key=attestation_key,
        )
        self._proof = proof
        return proof

    def proof_for_ingest(self) -> BackendCleanStateProof:
        if self._proof is None:
            raise CleanStateProofError("clean_state_namespace_proof_missing")
        return self._proof

    def proofs(self) -> tuple[BackendCleanStateProof, ...]:
        return (self._proof,) if self._proof is not None else ()


class Mem0CleanStateSession:
    """Own authenticated delete/readback evidence for Mem0 ingestion scopes."""

    def __init__(self, *, reset_enabled: bool) -> None:
        self._reset_enabled = reset_enabled
        self._used: list[BackendCleanStateProof] = []

    def reset_scope(
        self,
        client: httpx.Client,
        *,
        user_id: str,
        run_id: str,
        corpus_identity_sha256: str,
        expected_scope_count: int,
        attestation_key: bytes,
        record: bool = False,
    ) -> BackendCleanStateProof:
        if not self._reset_enabled:
            proof = skipped_mem0_clean_state_proof(
                run_id=run_id,
                scope_identity=user_id,
                corpus_identity_sha256=corpus_identity_sha256,
                expected_scope_count=expected_scope_count,
                attestation_key=attestation_key,
            )
        else:
            try:
                response = client.delete(
                    "/memories",
                    params={"user_id": user_id, "run_id": run_id},
                )
            except httpx.HTTPError:
                raise CleanStateProofError("mem0_delete_request_failed") from None
            payload: object = None
            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    raise CleanStateProofError("mem0_delete_ack_malformed") from None
            proof = mem0_delete_clean_state_proof(
                run_id=run_id,
                scope_identity=user_id,
                corpus_identity_sha256=corpus_identity_sha256,
                expected_scope_count=expected_scope_count,
                status_code=response.status_code,
                payload=payload,
                attestation_key=attestation_key,
            )
        if record:
            self._used.append(proof)
        return proof

    def clear(self) -> None:
        self._used.clear()

    def proofs(self) -> tuple[BackendCleanStateProof, ...]:
        return tuple(self._used)
