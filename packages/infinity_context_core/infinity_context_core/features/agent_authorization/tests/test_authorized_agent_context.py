"""Authorization invariants for agent-controlled request parameters."""

from __future__ import annotations

import asyncio

import pytest

from infinity_context_core.features.agent_authorization.public import (
    AgentAccessPolicy,
    AgentScopeResolutionEvidence,
    AgentScopeResolutionMethod,
    AuthorizeAgentRequestCommand,
    AuthorizeAgentRequestHandler,
    AuthorizedAgentContext,
    WorkspaceScopeClaim,
    decode_workspace_scope_claim,
    encode_workspace_scope_claim,
)


def test_locked_context_authorizes_only_its_canonical_space_scope_and_repository() -> None:
    context = _context()

    authorized = asyncio.run(
        AuthorizeAgentRequestHandler(context).execute(
            AuthorizeAgentRequestCommand(
                requested_space_id="space-1",
                requested_memory_scope_ids=("scope-1",),
                requested_repository_id="repo-1",
                requested_code_scope_id="code-scope-1",
                required_permission="memory:read",
            )
        )
    )

    assert authorized.space_id == "space-1"
    assert authorized.repository_id == "repo-1"
    assert authorized.code_scope_id == "code-scope-1"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("requested_space_id", "space-2", "MemorySpace"),
        ("requested_memory_scope_ids", ("scope-2",), "MemoryScope"),
        ("requested_repository_id", "repo-2", "CodeRepository"),
        ("requested_code_scope_id", "code-scope-2", "CodeScope"),
        ("required_permission", "memory:write", "required permission"),
    ),
)
def test_prompt_controlled_values_cannot_widen_locked_context(
    field: str,
    value: object,
    message: str,
) -> None:
    values: dict[str, object] = {
        "requested_space_id": "space-1",
        "requested_memory_scope_ids": ("scope-1",),
        "requested_repository_id": "repo-1",
        "requested_code_scope_id": "code-scope-1",
        "required_permission": "memory:read",
    }
    values[field] = value

    with pytest.raises(PermissionError, match=message):
        _context().authorize(**values)  # type: ignore[arg-type]


def test_resolution_evidence_rejects_raw_path_or_remote_url() -> None:
    with pytest.raises(ValueError, match="opaque identifier"):
        AgentScopeResolutionEvidence(
            method=AgentScopeResolutionMethod.TRUSTED_BINDING,
            binding_id="/Users/alice/project",
            binding_version=1,
        )


def test_workspace_scope_claim_codec_is_strict_and_round_trips() -> None:
    claim = WorkspaceScopeClaim(
        issued_at_epoch_seconds=1_800_000_000,
        repository_id="repo-1",
        code_scope_id="code-scope-1",
        resolution_method=AgentScopeResolutionMethod.TRUSTED_BINDING,
        binding_id="binding-1",
        binding_version=2,
    )

    assert decode_workspace_scope_claim(encode_workspace_scope_claim(claim)) == claim
    with pytest.raises(ValueError, match="Invalid workspace scope claim"):
        decode_workspace_scope_claim("not-valid-base64")


def _context() -> AuthorizedAgentContext:
    return AuthorizedAgentContext(
        actor_id="agent-1",
        space_id="space-1",
        memory_scope_ids=("scope-1",),
        permissions=frozenset({"memory:read"}),
        repository_id="repo-1",
        code_scope_id="code-scope-1",
        access_policy=AgentAccessPolicy.LOCKED_PROJECT,
        resolution=AgentScopeResolutionEvidence(
            method=AgentScopeResolutionMethod.TRUSTED_BINDING,
            binding_id="binding-1",
            binding_version=1,
        ),
    )
