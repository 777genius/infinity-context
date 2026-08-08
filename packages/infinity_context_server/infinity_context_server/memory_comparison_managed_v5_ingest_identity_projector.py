"""Pure exact identity projection for the Infinity + managed Mem0 v5 cutover."""

from __future__ import annotations

from collections.abc import Mapping
from typing import NoReturn

from infinity_context_server.memory_comparison_managed_http_policy_requirements import (
    ManagedIngestIdentityManifest,
)
from infinity_context_server.memory_comparison_managed_infinity_http_lifecycle import (
    ManagedInfinityHttpIngestEvidence,
)
from infinity_context_server.memory_comparison_managed_ingest_manifest import (
    ManagedCorpusIngestIdentity,
    parse_managed_infinity_ingest_result,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_lifecycle import (
    ManagedMem0V5IngestProjection,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5CorpusIngestEvidence,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import canonical_sha256


class ManagedV5IngestIdentityProjectionError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def project_managed_infinity_v5_ingest_identities(
    *,
    composition_binding: ManagedRunnerCompositionBinding,
    cases: tuple[ManagedRunCase, ...],
    infinity_evidence: tuple[ManagedInfinityHttpIngestEvidence, ...],
    mem0_projection: ManagedMem0V5IngestProjection,
) -> tuple[ManagedCorpusIngestIdentity, ...]:
    """Pair exact authenticated lanes without HTTP or legacy Mem0 metadata."""

    corpora = _unique_corpora(cases)
    targets = tuple(
        (item.backend_role, item.target_identity_sha256)
        for item in composition_binding.backend_targets
    )
    if (
        type(composition_binding) is not ManagedRunnerCompositionBinding
        or len(targets) != 2
        or targets[0][0] != "infinity-context"
        or targets[1][0] != "mem0"
        or type(infinity_evidence) is not tuple
        or len(infinity_evidence) != len(corpora)
        or type(mem0_projection) is not ManagedMem0V5IngestProjection
        or len(mem0_projection.evidence) != len(corpora)
    ):
        _fail("managed_v5_ingest_projection_composition_invalid")
    infinity_target = targets[0][1]
    mem0_target = targets[1][1]
    projected: list[ManagedCorpusIngestIdentity] = []
    for case, infinity, mem0 in zip(
        corpora,
        infinity_evidence,
        mem0_projection.evidence,
        strict=True,
    ):
        _validate_exact_pair(
            composition_binding,
            case,
            infinity,
            mem0,
            infinity_target=infinity_target,
            admission_commitment_sha256=(mem0_projection.admission_commitment_sha256),
        )
        parsed = parse_managed_infinity_ingest_result(
            infinity.ingest_result,
            corpus_id=case.corpus_id,
        )
        infinity_sources = tuple(
            zip(parsed.manifest.source_ids, parsed.manifest.source_sha256, strict=True)
        )
        mem0_sources = tuple((unit.source_id, unit.source_sha256) for unit in mem0.units)
        if infinity_sources != mem0_sources:
            _fail("managed_v5_ingest_projection_source_pair_mismatch")
        created_ids = tuple(identity for unit in mem0.units for identity in unit.created_record_ids)
        if not created_ids or len(set(created_ids)) != len(created_ids):
            _fail("managed_v5_ingest_projection_mem0_identity_invalid")
        try:
            manifest = ManagedIngestIdentityManifest(
                corpus_id=case.corpus_id,
                infinity_fact_ids=parsed.manifest.fact_ids,
                infinity_document_ids=parsed.manifest.document_ids,
                infinity_chunk_ids=parsed.manifest.chunk_ids,
                infinity_source_ids=parsed.manifest.source_ids,
                infinity_source_sha256=parsed.manifest.source_sha256,
                mem0_created_memory_ids=created_ids,
                mem0_source_ids=tuple(item[0] for item in mem0_sources),
                mem0_source_sha256=tuple(item[1] for item in mem0_sources),
                operation_count=parsed.manifest.operation_count + len(mem0.units),
                complete=True,
                issues=(),
            )
            projected.append(
                ManagedCorpusIngestIdentity(
                    case_id=case.case_id,
                    corpus_id=case.corpus_id,
                    infinity_target_identity_sha256=infinity_target,
                    mem0_target_identity_sha256=mem0_target,
                    manifest=manifest,
                    scope=parsed.scope,
                    canonical_episode_ids=parsed.canonical_episode_ids,
                )
            )
        except Exception:
            _fail("managed_v5_ingest_projection_manifest_invalid")
    return tuple(projected)


def _validate_exact_pair(
    binding: ManagedRunnerCompositionBinding,
    case: ManagedRunCase,
    infinity: object,
    mem0: object,
    *,
    infinity_target: str,
    admission_commitment_sha256: str,
) -> None:
    if (
        type(infinity) is not ManagedInfinityHttpIngestEvidence
        or type(mem0) is not ManagedMem0V5CorpusIngestEvidence
        or infinity.case_id != case.case_id
        or infinity.corpus_id != case.corpus_id
        or infinity.target_identity_sha256 != infinity_target
        or mem0.run_id != binding.run_id
        or mem0.corpus_id != case.corpus_id
        or mem0.target_identity_sha256
        != canonical_sha256(
            {
                "admission_commitment_sha256": (admission_commitment_sha256),
                "corpus_id": case.corpus_id,
            }
        )
    ):
        _fail("managed_v5_ingest_projection_binding_invalid")


def _unique_corpora(cases: object) -> tuple[ManagedRunCase, ...]:
    if type(cases) is not tuple or not cases or any(type(x) is not ManagedRunCase for x in cases):
        _fail("managed_v5_ingest_projection_cases_invalid")
    seen: dict[str, ManagedRunCase] = {}
    for case in cases:
        previous = seen.get(case.corpus_id)
        if previous is None:
            seen[case.corpus_id] = case
        elif _canonical(previous.record) != _canonical(case.record):
            _fail("managed_v5_ingest_projection_cases_invalid")
    return tuple(seen.values())


def _canonical(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _canonical(item)) for key, item in value.items()))
    if type(value) in {tuple, list}:
        return tuple(_canonical(item) for item in value)
    return value


def _fail(code: str) -> NoReturn:
    raise ManagedV5IngestIdentityProjectionError(code) from None


__all__ = (
    "ManagedV5IngestIdentityProjectionError",
    "project_managed_infinity_v5_ingest_identities",
)
