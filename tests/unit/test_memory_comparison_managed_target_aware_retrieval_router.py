from __future__ import annotations

from dataclasses import replace

import pytest
from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    GoldBlindEvidence,
    gold_blind_evidence_identity,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_paired_bridge import (
    ManagedMem0V5PairedRun,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_runner_adapter import (
    ManagedMem0V5RetrievalAdapter,
)
from infinity_context_server.memory_comparison_managed_retrieval_port import (
    ManagedRetrievalAuthority,
    ManagedRetrievalResult,
    _issue_managed_retrieval_authority,
    _validate_managed_retrieval_authority,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedRunCase,
    _thaw_json,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_managed_target_aware_retrieval_router import (
    ManagedTargetAwareRetrievalRoute,
    ManagedTargetAwareRetrievalRouter,
    ManagedTargetAwareRetrievalRouterError,
    managed_target_aware_retrieval_router_implementation_sha256,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)
from test_memory_comparison_managed_mem0_v5_paired_bridge import _run as _paired_run
from test_memory_comparison_managed_mem0_v5_runner_foundation import (
    _authority_and_case,
    _binding,
)

_INFINITY_ADAPTER_ID = "test.infinity-retrieval.v1"
_MEM0_ADAPTER_ID = "managed-mem0-v5.paired-retrieval.v1"
_INFINITY_IMPLEMENTATION = "1" * 64
_MEM0_IMPLEMENTATION = "2" * 64
_ROUTER_ID = "managed-target-aware-retrieval-router.v1"


class _Delegate:
    def __init__(
        self,
        binding: ManagedRunnerCompositionBinding,
        *,
        adapter_id: str = _INFINITY_ADAPTER_ID,
        implementation_sha256: str = _INFINITY_IMPLEMENTATION,
        evidence: tuple[GoldBlindEvidence, ...] = (),
        fail: bool = False,
        invalid_result: bool = False,
        include_implementation_sha256: bool = True,
        reported_implementation_sha256: str | None = None,
    ) -> None:
        self.composition_binding = binding
        self.adapter_id = adapter_id
        self.implementation_sha256 = implementation_sha256
        self.evidence = evidence
        self.fail = fail
        self.invalid_result = invalid_result
        self.include_implementation_sha256 = include_implementation_sha256
        self.reported_implementation_sha256 = (
            implementation_sha256
            if reported_implementation_sha256 is None
            else reported_implementation_sha256
        )
        self.authority_calls: list[tuple[str, str]] = []
        self.retrieve_calls: list[
            tuple[ManagedRetrievalAuthority, ManagedRunCase, ManagedAnswerCase]
        ] = []

    def authority_for(
        self, *, backend_role: str, target_identity_sha256: str
    ) -> ManagedRetrievalAuthority:
        self.authority_calls.append((backend_role, target_identity_sha256))
        return _issue_managed_retrieval_authority(
            self.composition_binding,
            backend_role=backend_role,
            target_identity_sha256=target_identity_sha256,
        )

    def retrieve(
        self,
        *,
        authority: ManagedRetrievalAuthority,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
    ) -> ManagedRetrievalResult:
        self.retrieve_calls.append((authority, case, query))
        if self.fail:
            raise RuntimeError("delegate secret must not escape")
        if self.invalid_result:
            return object()  # type: ignore[return-value]
        backend_role, target = _validate_managed_retrieval_authority(
            authority,
            composition_binding=self.composition_binding,
        )
        metadata = {
            "adapter_id": self.adapter_id,
            "backend_role": backend_role,
            "target_identity_sha256": target,
            "retrieval_policy": NEUTRAL_COMPARISON_RETRIEVAL_POLICY.telemetry(),
            "gold_fields_forwarded": False,
            "retries": 0,
            "delegate_custom": "preserved-neutral-value",
        }
        if self.include_implementation_sha256:
            metadata["implementation_sha256"] = self.reported_implementation_sha256
        return ManagedRetrievalResult(
            evidence=self.evidence,
            retrieval_identity=gold_blind_evidence_identity(self.evidence),
            metadata=metadata,
        )


def _targets(binding: ManagedRunnerCompositionBinding) -> dict[str, str]:
    return {item.backend_role: item.target_identity_sha256 for item in binding.backend_targets}


def _routes(
    binding: ManagedRunnerCompositionBinding,
    infinity: object,
    mem0: object,
) -> tuple[ManagedTargetAwareRetrievalRoute, ...]:
    targets = _targets(binding)
    return (
        ManagedTargetAwareRetrievalRoute(
            "infinity-context",
            targets["infinity-context"],
            infinity,
            infinity.adapter_id,
            infinity.implementation_sha256,
        ),
        ManagedTargetAwareRetrievalRoute(
            "mem0",
            targets["mem0"],
            mem0,
            mem0.adapter_id,
            mem0.implementation_sha256,
        ),
    )


def _router(
    binding: ManagedRunnerCompositionBinding,
    infinity: object | None = None,
    mem0: object | None = None,
) -> tuple[ManagedTargetAwareRetrievalRouter, _Delegate, _Delegate]:
    infinity_delegate = infinity or _Delegate(binding)
    mem0_delegate = mem0 or _Delegate(
        binding,
        adapter_id=_MEM0_ADAPTER_ID,
        implementation_sha256=_MEM0_IMPLEMENTATION,
    )
    return (
        ManagedTargetAwareRetrievalRouter(
            composition_binding=binding,
            routes=_routes(binding, infinity_delegate, mem0_delegate),
        ),
        infinity_delegate,  # type: ignore[return-value]
        mem0_delegate,  # type: ignore[return-value]
    )


def _case_and_query() -> tuple[ManagedRunCase, ManagedAnswerCase]:
    _authority, case = _authority_and_case()
    return case, ManagedAnswerCase(case.case_id, "What does Alice like?", {})


@pytest.mark.parametrize("backend_role", ["infinity-context", "mem0"])
def test_routes_each_target_once_without_cross_lane_fallback(backend_role: str) -> None:
    binding = _binding()
    evidence = (GoldBlindEvidence("memory-1", "Alice likes tea.", 1, "2024-03-10"),)
    infinity = _Delegate(binding, evidence=evidence)
    mem0 = _Delegate(
        binding,
        adapter_id=_MEM0_ADAPTER_ID,
        implementation_sha256=_MEM0_IMPLEMENTATION,
        evidence=evidence,
    )
    router, _infinity, _mem0 = _router(binding, infinity, mem0)
    target = _targets(binding)[backend_role]
    authority = router.authority_for(
        backend_role=backend_role,
        target_identity_sha256=target,
    )
    case, query = _case_and_query()

    result = router.retrieve(authority=authority, case=case, query=query)

    selected = infinity if backend_role == "infinity-context" else mem0
    unselected = mem0 if backend_role == "infinity-context" else infinity
    assert selected.authority_calls == [(backend_role, target)]
    assert len(selected.retrieve_calls) == 1
    assert unselected.authority_calls == []
    assert unselected.retrieve_calls == []
    assert result.evidence == evidence
    assert result.retrieval_identity == gold_blind_evidence_identity(evidence)


def test_normalizes_route_provenance_and_neutral_policy_metadata() -> None:
    binding = _binding()
    router, infinity, _mem0 = _router(binding)
    target = _targets(binding)["infinity-context"]
    authority = router.authority_for(
        backend_role="infinity-context",
        target_identity_sha256=target,
    )
    case, query = _case_and_query()

    result = router.retrieve(authority=authority, case=case, query=query)

    metadata = dict(result.metadata)
    assert metadata["adapter_id"] == _ROUTER_ID
    assert metadata["implementation_sha256"] == router.implementation_sha256
    assert router.implementation_sha256 == (
        managed_target_aware_retrieval_router_implementation_sha256()
    )
    assert router.implementation_sha256 == (
        "79167a7baa52e696b0a607ea0501775682eed9f9e0eae67c27fbc280299351c7"
    )
    assert metadata["delegate_adapter_id"] == _INFINITY_ADAPTER_ID
    assert metadata["delegate_implementation_sha256"] == _INFINITY_IMPLEMENTATION
    assert metadata["backend_role"] == "infinity-context"
    assert metadata["target_identity_sha256"] == target
    assert _thaw_json(metadata["retrieval_policy"]) == (
        NEUTRAL_COMPARISON_RETRIEVAL_POLICY.telemetry()
    )
    assert metadata["gold_fields_forwarded"] is False
    assert metadata["retries"] == 0
    assert metadata["delegate_custom"] == "preserved-neutral-value"
    assert len(metadata["route_graph_commitment_sha256"]) == 64
    assert infinity.retrieve_calls[0][0] is authority


def test_legacy_metadata_without_implementation_uses_frozen_route_provenance() -> None:
    binding = _binding()
    infinity = _Delegate(binding, include_implementation_sha256=False)
    router, _infinity, _mem0 = _router(binding, infinity=infinity)
    target = _targets(binding)["infinity-context"]
    authority = router.authority_for(
        backend_role="infinity-context",
        target_identity_sha256=target,
    )
    case, query = _case_and_query()

    result = router.retrieve(authority=authority, case=case, query=query)

    assert result.metadata["delegate_implementation_sha256"] == _INFINITY_IMPLEMENTATION


def test_present_delegate_implementation_must_match_frozen_route() -> None:
    binding = _binding()
    infinity = _Delegate(
        binding,
        reported_implementation_sha256="f" * 64,
    )
    router, _infinity, _mem0 = _router(binding, infinity=infinity)
    target = _targets(binding)["infinity-context"]
    authority = router.authority_for(
        backend_role="infinity-context",
        target_identity_sha256=target,
    )
    case, query = _case_and_query()

    with pytest.raises(ManagedTargetAwareRetrievalRouterError, match="result_invalid"):
        router.retrieve(authority=authority, case=case, query=query)


def test_mem0_route_uses_real_v5_adapter_provider_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_authority, coordinator, paired_run = _paired_run()
    binding = _binding(run_id=coordinator.request.run_id)
    evidence = (GoldBlindEvidence("memory-1", "Alice likes tea.", 1, "2024-03-10"),)
    search_calls: list[dict[str, object]] = []

    def search(_self: object, **values: object) -> tuple[GoldBlindEvidence, ...]:
        search_calls.append(values)
        return evidence

    monkeypatch.setattr(ManagedMem0V5PairedRun, "search", search)
    mem0 = ManagedMem0V5RetrievalAdapter(
        composition_binding=binding,
        paired_run=paired_run,
        authority=manifest_authority,
        request=coordinator.request,
    )
    infinity = _Delegate(binding)
    router = ManagedTargetAwareRetrievalRouter(
        composition_binding=binding,
        routes=_routes(binding, infinity, mem0),
    )
    target = _targets(binding)["mem0"]
    authority = router.authority_for(
        backend_role="mem0",
        target_identity_sha256=target,
    )
    case, query = _case_and_query()

    result = router.retrieve(authority=authority, case=case, query=query)

    assert search_calls == [
        {
            "corpus_id": case.corpus_id,
            "query": query.question,
            "top_k": binding.retrieval_top_k,
            "cutoff": binding.answer_cutoff,
        }
    ]
    assert infinity.authority_calls == []
    assert infinity.retrieve_calls == []
    assert result.evidence == evidence
    assert result.metadata["delegate_adapter_id"] == mem0.adapter_id
    assert result.metadata["delegate_implementation_sha256"] == (mem0.implementation_sha256)


def test_requires_exact_ordered_route_graph_and_delegate_binding() -> None:
    binding = _binding()
    infinity = _Delegate(binding)
    mem0 = _Delegate(
        binding,
        adapter_id=_MEM0_ADAPTER_ID,
        implementation_sha256=_MEM0_IMPLEMENTATION,
    )
    routes = _routes(binding, infinity, mem0)

    with pytest.raises(ManagedTargetAwareRetrievalRouterError, match="route_graph_invalid"):
        ManagedTargetAwareRetrievalRouter(
            composition_binding=binding,
            routes=tuple(reversed(routes)),
        )
    with pytest.raises(ManagedTargetAwareRetrievalRouterError, match="route_graph_invalid"):
        ManagedTargetAwareRetrievalRouter(
            composition_binding=binding,
            routes=(routes[0], routes[0]),
        )

    foreign_binding = _binding(run_id="foreign-router-run")
    foreign_delegate = _Delegate(foreign_binding)
    foreign_route = replace(routes[0], delegate=foreign_delegate)
    with pytest.raises(ManagedTargetAwareRetrievalRouterError, match="route_graph_invalid"):
        ManagedTargetAwareRetrievalRouter(
            composition_binding=binding,
            routes=(foreign_route, routes[1]),
        )


def test_detects_route_mutation_after_construction() -> None:
    binding = _binding()
    infinity = _Delegate(binding)
    mem0 = _Delegate(
        binding,
        adapter_id=_MEM0_ADAPTER_ID,
        implementation_sha256=_MEM0_IMPLEMENTATION,
    )
    routes = _routes(binding, infinity, mem0)
    router = ManagedTargetAwareRetrievalRouter(
        composition_binding=binding,
        routes=routes,
    )
    object.__setattr__(routes[0], "delegate", _Delegate(binding))

    with pytest.raises(ManagedTargetAwareRetrievalRouterError, match="route_graph_invalid"):
        router.authority_for(
            backend_role="infinity-context",
            target_identity_sha256=_targets(binding)["infinity-context"],
        )


def test_authority_is_bound_to_issuing_router_but_is_reusable_within_it() -> None:
    binding = _binding()
    shared_infinity = _Delegate(binding)
    shared_mem0 = _Delegate(
        binding,
        adapter_id=_MEM0_ADAPTER_ID,
        implementation_sha256=_MEM0_IMPLEMENTATION,
    )
    routes = _routes(binding, shared_infinity, shared_mem0)
    first = ManagedTargetAwareRetrievalRouter(
        composition_binding=binding,
        routes=routes,
    )
    second = ManagedTargetAwareRetrievalRouter(
        composition_binding=binding,
        routes=routes,
    )
    target = _targets(binding)["infinity-context"]
    authority = first.authority_for(
        backend_role="infinity-context",
        target_identity_sha256=target,
    )
    case, query = _case_and_query()

    first.retrieve(authority=authority, case=case, query=query)
    first.retrieve(authority=authority, case=case, query=query)
    assert len(shared_infinity.retrieve_calls) == 2
    with pytest.raises(ManagedTargetAwareRetrievalRouterError, match="authority_invalid"):
        second.retrieve(authority=authority, case=case, query=query)
    assert len(shared_infinity.retrieve_calls) == 2


def test_rejects_foreign_and_tampered_authority_before_delegate() -> None:
    binding = _binding()
    router, infinity, _mem0 = _router(binding)
    target = _targets(binding)["infinity-context"]
    case, query = _case_and_query()
    foreign = _issue_managed_retrieval_authority(
        binding,
        backend_role="infinity-context",
        target_identity_sha256=target,
    )

    with pytest.raises(ManagedTargetAwareRetrievalRouterError, match="authority_invalid"):
        router.retrieve(authority=foreign, case=case, query=query)
    authority = router.authority_for(
        backend_role="infinity-context",
        target_identity_sha256=target,
    )
    object.__setattr__(authority, "_target_identity", "f" * 64)
    with pytest.raises(ManagedTargetAwareRetrievalRouterError, match="authority_invalid"):
        router.retrieve(authority=authority, case=case, query=query)
    assert infinity.retrieve_calls == []


@pytest.mark.parametrize(
    ("delegate_kwargs", "error_code"),
    [
        ({"fail": True}, "managed_target_retrieval_failed"),
        ({"invalid_result": True}, "managed_target_retrieval_result_invalid"),
    ],
)
def test_delegate_failure_or_invalid_result_has_no_fallback(
    delegate_kwargs: dict[str, bool],
    error_code: str,
) -> None:
    binding = _binding()
    infinity = _Delegate(binding, **delegate_kwargs)
    mem0 = _Delegate(
        binding,
        adapter_id=_MEM0_ADAPTER_ID,
        implementation_sha256=_MEM0_IMPLEMENTATION,
    )
    router, _infinity, _mem0 = _router(binding, infinity, mem0)
    target = _targets(binding)["infinity-context"]
    authority = router.authority_for(
        backend_role="infinity-context",
        target_identity_sha256=target,
    )
    case, query = _case_and_query()

    with pytest.raises(ManagedTargetAwareRetrievalRouterError, match=error_code):
        router.retrieve(authority=authority, case=case, query=query)
    assert len(infinity.retrieve_calls) == 1
    assert mem0.authority_calls == []
    assert mem0.retrieve_calls == []


def test_rejects_mismatched_case_query_before_delegate() -> None:
    binding = _binding()
    router, infinity, _mem0 = _router(binding)
    target = _targets(binding)["infinity-context"]
    authority = router.authority_for(
        backend_role="infinity-context",
        target_identity_sha256=target,
    )
    case, _query = _case_and_query()
    wrong_query = ManagedAnswerCase("other-case", "What does Alice like?", {})

    with pytest.raises(ManagedTargetAwareRetrievalRouterError, match="request_invalid"):
        router.retrieve(authority=authority, case=case, query=wrong_query)
    assert infinity.retrieve_calls == []


def test_public_identity_and_repr_are_stable_and_redacted() -> None:
    binding = _binding(run_id="secret-router-run")
    router, _infinity, _mem0 = _router(binding)

    assert router.composition_binding is binding
    assert router.adapter_id == _ROUTER_ID
    assert len(router.implementation_sha256) == 64
    assert repr(router) in {
        "ManagedTargetAwareRetrievalRouter(<opaque>)",
        "ManagedTargetAwareRetrievalRouter(<redacted>)",
    }
    assert "secret-router-run" not in repr(router)
