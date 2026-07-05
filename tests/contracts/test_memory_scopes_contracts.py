from __future__ import annotations

import json

from infinity_context_contracts.features import memory_scopes
from infinity_context_contracts.features.memory_scopes import (
    ArchiveMemoryScopeRequestDto,
    ArchiveMemoryScopeResultDto,
    FEATURE_ID,
    MemoryScopeDescriptorDto,
    RestoreMemoryScopeRequestDto,
    RestoreMemoryScopeResultDto,
    ScopeIdentityDto,
)


def test_memory_scopes_feature_module_is_publicly_importable() -> None:
    assert memory_scopes.FEATURE_ID == "memory_scopes"
    assert FEATURE_ID == "memory_scopes"
    assert "ArchiveMemoryScopeRequestDto" in memory_scopes.__all__
    assert "RestoreMemoryScopeResultDto" in memory_scopes.__all__


def test_memory_scope_archive_contract_uses_feature_identity_fields() -> None:
    archived_scope = MemoryScopeDescriptorDto(
        identity=ScopeIdentityDto(
            id="memory_scope_default",
            space_id="space_client_app",
            external_ref="default",
        ),
        name="Default",
        status="archived",
        policy_mode="manual_only",
        metadata={"owner": "client-app"},
    )
    request = ArchiveMemoryScopeRequestDto(
        space_id="space_client_app",
        memory_scope_id="memory_scope_default",
        expected_status="active",
        reason="project completed",
        idempotency_key="archive_scope_1",
        metadata={"ticket": "MEM-1"},
    )
    result = ArchiveMemoryScopeResultDto(
        scope=archived_scope,
        previous_status="active",
    )

    assert request.to_dict() == {
        "space_id": "space_client_app",
        "memory_scope_id": "memory_scope_default",
        "expected_status": "active",
        "reason": "project completed",
        "idempotency_key": "archive_scope_1",
        "metadata": {"ticket": "MEM-1"},
    }
    assert "scope_id" not in request.to_dict()
    assert result.to_dict() == {
        "data": {
            "scope": {
                "id": "memory_scope_default",
                "space_id": "space_client_app",
                "external_ref": "default",
                "name": "Default",
                "description": None,
                "status": "archived",
                "policy_mode": "manual_only",
                "created_at": None,
                "updated_at": None,
                "metadata": {"owner": "client-app"},
            },
            "previous_status": "active",
            "archived": True,
        }
    }
    json.dumps(result.to_dict(), sort_keys=True)


def test_memory_scope_restore_contract_uses_feature_identity_fields() -> None:
    restored_scope = MemoryScopeDescriptorDto(
        identity=ScopeIdentityDto(
            id="memory_scope_default",
            space_id="space_client_app",
            external_ref="default",
        ),
        name="Default",
        status="active",
        policy_mode="manual_only",
    )
    request = RestoreMemoryScopeRequestDto(
        space_id="space_client_app",
        memory_scope_id="memory_scope_default",
        expected_status="archived",
        reason="project restarted",
        idempotency_key="restore_scope_1",
    )
    result = RestoreMemoryScopeResultDto(
        scope=restored_scope,
        previous_status="archived",
    )

    assert request.to_dict() == {
        "space_id": "space_client_app",
        "memory_scope_id": "memory_scope_default",
        "expected_status": "archived",
        "reason": "project restarted",
        "idempotency_key": "restore_scope_1",
        "metadata": {},
    }
    assert "scope_id" not in request.to_dict()
    assert result.to_dict()["data"] == {
        "scope": {
            "id": "memory_scope_default",
            "space_id": "space_client_app",
            "external_ref": "default",
            "name": "Default",
            "description": None,
            "status": "active",
            "policy_mode": "manual_only",
            "created_at": None,
            "updated_at": None,
            "metadata": {},
        },
        "previous_status": "archived",
        "restored": True,
    }
    json.dumps(result.to_dict(), sort_keys=True)
