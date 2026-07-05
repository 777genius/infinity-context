"""Public server seam for the memory_facts feature mirror."""

from __future__ import annotations

import infinity_context_core.features.memory_facts.public as memory_facts

from infinity_context_server.features.memory_facts.composition import (
    MemoryFactsServerComposition,
    MemoryFactsServerFeature,
    build_memory_facts_server_composition,
    build_memory_facts_server_feature,
)
from infinity_context_server.features.memory_facts.contracts import (
    ForgetFactHttpRequest,
    MemoryFactSourceRefHttpRequest,
    RememberFactHttpRequest,
    UpdateFactHttpRequest,
)
from infinity_context_server.features.memory_facts.mappers import (
    evidence_ref_request_to_public,
    evidence_ref_to_response,
    fact_result_to_response,
    fact_to_response,
    forget_fact_command_from_http,
    forget_fact_request_to_command,
    forget_fact_result_to_contract,
    legacy_memory_fact_to_response,
    memory_fact_result_to_response,
    memory_fact_scope_from_contract,
    memory_fact_scope_from_ids,
    memory_fact_snapshot_to_contract,
    memory_fact_snapshot_to_response,
    remember_fact_command_from_contract,
    remember_fact_request_to_command,
    remember_fact_result_to_contract,
    source_ref_request_to_public,
    source_ref_to_contract,
    source_ref_to_response,
    update_fact_command_from_http,
    update_fact_request_to_command,
    update_fact_result_to_contract,
)
from infinity_context_server.features.memory_facts.routes import (
    create_memory_facts_router,
)

FEATURE_ID = memory_facts.FEATURE_ID

__all__ = (
    "ForgetFactHttpRequest",
    "MemoryFactSourceRefHttpRequest",
    "MemoryFactsServerComposition",
    "MemoryFactsServerFeature",
    "RememberFactHttpRequest",
    "UpdateFactHttpRequest",
    "FEATURE_ID",
    "build_memory_facts_server_composition",
    "build_memory_facts_server_feature",
    "create_memory_facts_router",
    "evidence_ref_request_to_public",
    "evidence_ref_to_response",
    "fact_result_to_response",
    "fact_to_response",
    "forget_fact_command_from_http",
    "forget_fact_request_to_command",
    "forget_fact_result_to_contract",
    "legacy_memory_fact_to_response",
    "memory_fact_result_to_response",
    "memory_fact_scope_from_contract",
    "memory_fact_scope_from_ids",
    "memory_fact_snapshot_to_contract",
    "memory_fact_snapshot_to_response",
    "remember_fact_command_from_contract",
    "remember_fact_request_to_command",
    "remember_fact_result_to_contract",
    "source_ref_request_to_public",
    "source_ref_to_contract",
    "source_ref_to_response",
    "update_fact_command_from_http",
    "update_fact_request_to_command",
    "update_fact_result_to_contract",
)
