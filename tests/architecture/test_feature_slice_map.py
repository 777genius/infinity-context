"""Feature-slice ownership map for bounded-context architecture guardrails."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

CORE = "packages/infinity_context_core/infinity_context_core"
APPLICATION = f"{CORE}/application"
USE_CASES = f"{APPLICATION}/use_cases"
DOMAIN = f"{CORE}/domain"
PORTS = f"{CORE}/ports"

ADAPTERS = "packages/infinity_context_adapters/infinity_context_adapters"
POSTGRES = f"{ADAPTERS}/postgres"
SERVER_API_V1 = "packages/infinity_context_server/infinity_context_server/api/v1"

PYTHON_SDK = "packages/infinity_context_sdk/infinity_context_sdk"
MCP = "packages/infinity_context_mcp/infinity_context_mcp"
CLI = "packages/infinity_context_cli/infinity_context_cli"
OBSIDIAN = "packages/infinity_context_obsidian/infinity_context_obsidian"
CONTRACTS = "packages/infinity_context_contracts/infinity_context_contracts"
TYPESCRIPT_SDK = "packages/infinity_context_ts_sdk/src"
OBSIDIAN_PLUGIN = "packages/infinity_context_obsidian_plugin"

SOURCE_SUFFIXES = (".py", ".js", ".ts", ".tsx", ".sql")
IGNORED_PATH_PARTS = {"__pycache__", "node_modules"}
IGNORED_PREFIXES = (f"{OBSIDIAN_PLUGIN}/test/",)

KEY_PACKAGE_ROOTS = (
    CORE,
    ADAPTERS,
    SERVER_API_V1,
    PYTHON_SDK,
    MCP,
    CLI,
    OBSIDIAN,
    CONTRACTS,
    TYPESCRIPT_SDK,
    OBSIDIAN_PLUGIN,
)

REQUIRED_BOUNDED_CONTEXTS = frozenset(
    {
        "canonical_memory_lifecycle",
        "spaces_scopes_users_usage",
        "captures_episodes",
        "documents_chunks_rag",
        "context_builder_ranking",
        "assets_extraction",
        "context_links_anchors_suggestions",
        "digest_export",
        "derived_projections",
        "sdk_mcp_connectors",
    }
)


@dataclass(frozen=True)
class SliceSelector:
    include: str
    excludes: tuple[str, ...] = ()


FEATURE_SLICE_MAP: dict[str, tuple[SliceSelector, ...]] = {
    "canonical_memory_lifecycle": (
        SliceSelector(f"{DOMAIN}/entities.py"),
        SliceSelector(f"{DOMAIN}/errors.py"),
        SliceSelector(f"{DOMAIN}/events.py"),
        SliceSelector(f"{DOMAIN}/idempotency.py"),
        SliceSelector(f"{DOMAIN}/taxonomy.py"),
        SliceSelector(f"{APPLICATION}/auto_apply.py"),
        SliceSelector(f"{APPLICATION}/auto_memory.py"),
        SliceSelector(f"{APPLICATION}/normalize.py"),
        SliceSelector(f"{APPLICATION}/related_facts.py"),
        SliceSelector(f"{APPLICATION}/review_payloads.py"),
        SliceSelector(f"{APPLICATION}/safe_payload.py"),
        SliceSelector(f"{APPLICATION}/semantic_dedupe.py"),
        SliceSelector(f"{APPLICATION}/sensitive_text.py"),
        SliceSelector(f"{APPLICATION}/source_refs.py"),
        SliceSelector(f"{APPLICATION}/temporal_validity.py"),
        SliceSelector(f"{USE_CASES}/delete_thread_memory.py"),
        SliceSelector(f"{USE_CASES}/duplicate_merge_resolution.py"),
        SliceSelector(f"{USE_CASES}/fact_relations.py"),
        SliceSelector(f"{USE_CASES}/forget_fact.py"),
        SliceSelector(f"{USE_CASES}/memory_browser.py"),
        SliceSelector(f"{USE_CASES}/operations_console.py"),
        SliceSelector(f"{USE_CASES}/query_facts.py"),
        SliceSelector(f"{USE_CASES}/related_facts.py"),
        SliceSelector(f"{USE_CASES}/remember_fact.py"),
        SliceSelector(f"{USE_CASES}/update_fact.py"),
        SliceSelector(f"{PORTS}/repositories.py"),
        SliceSelector(f"{PORTS}/unit_of_work.py"),
        SliceSelector(f"{POSTGRES}/fact_repositories.py"),
        SliceSelector(f"{POSTGRES}/mappers.py"),
        SliceSelector(f"{POSTGRES}/models.py"),
        SliceSelector(f"{POSTGRES}/repositories.py"),
        SliceSelector(f"{POSTGRES}/repository_helpers.py"),
        SliceSelector(f"{POSTGRES}/unit_of_work.py"),
        SliceSelector(f"{POSTGRES}/migrations/0001_core_facts.sql"),
        SliceSelector(f"{POSTGRES}/migrations/0009_outbox_lifecycle_hardening.sql"),
        SliceSelector(f"{POSTGRES}/migrations/0010_fact_taxonomy.sql"),
        SliceSelector(f"{SERVER_API_V1}/facts.py"),
        SliceSelector(f"{SERVER_API_V1}/source_refs.py"),
        SliceSelector(f"{SERVER_API_V1}/thread_memory.py"),
    ),
    "spaces_scopes_users_usage": (
        SliceSelector(f"{DOMAIN}/usage.py"),
        SliceSelector(f"{USE_CASES}/ensure_scope.py"),
        SliceSelector(f"{USE_CASES}/get_capabilities.py"),
        SliceSelector(f"{USE_CASES}/spaces_memory_scopes.py"),
        SliceSelector(f"{USE_CASES}/usage.py"),
        SliceSelector(f"{USE_CASES}/users.py"),
        SliceSelector(f"{PORTS}/auth.py"),
        SliceSelector(f"{PORTS}/capabilities.py"),
        SliceSelector(f"{PORTS}/clock.py"),
        SliceSelector(f"{PORTS}/ids.py"),
        SliceSelector(f"{PORTS}/usage.py"),
        SliceSelector(f"{POSTGRES}/scope_repositories.py"),
        SliceSelector(f"{POSTGRES}/usage_repositories.py"),
        SliceSelector(f"{POSTGRES}/user_repositories.py"),
        SliceSelector(f"{POSTGRES}/migrations/0004_service_tokens.sql"),
        SliceSelector(f"{POSTGRES}/migrations/0005_data_classification_lite.sql"),
        SliceSelector(f"{POSTGRES}/migrations/0006_service_token_usage_metadata.sql"),
        SliceSelector(f"{POSTGRES}/migrations/0007_service_token_permissions.sql"),
        SliceSelector(f"{POSTGRES}/migrations/0008_service_token_memory_scope.sql"),
        SliceSelector(f"{POSTGRES}/migrations/0012_usage_governance.sql"),
        SliceSelector(f"{POSTGRES}/migrations/0015_users_acl.sql"),
        SliceSelector(f"{SERVER_API_V1}/capabilities.py"),
        SliceSelector(f"{SERVER_API_V1}/scope_resolution.py"),
        SliceSelector(f"{SERVER_API_V1}/spaces_memory_scopes.py"),
        SliceSelector(f"{SERVER_API_V1}/usage.py"),
        SliceSelector(f"{SERVER_API_V1}/users.py"),
    ),
    "captures_episodes": (
        SliceSelector(f"{DOMAIN}/capture.py"),
        SliceSelector(f"{APPLICATION}/capture_policy.py"),
        SliceSelector(f"{USE_CASES}/consolidate_capture.py"),
        SliceSelector(f"{USE_CASES}/get_capture.py"),
        SliceSelector(f"{USE_CASES}/get_session_status.py"),
        SliceSelector(f"{USE_CASES}/ingest_episode.py"),
        SliceSelector(f"{USE_CASES}/list_captures.py"),
        SliceSelector(f"{USE_CASES}/purge_capture.py"),
        SliceSelector(f"{USE_CASES}/receive_capture.py"),
        SliceSelector(f"{PORTS}/auto_memory.py"),
        SliceSelector(f"{PORTS}/captures.py"),
        SliceSelector(f"{SERVER_API_V1}/captures.py"),
        SliceSelector(f"{SERVER_API_V1}/episodes.py"),
    ),
    "documents_chunks_rag": (
        SliceSelector(f"{APPLICATION}/chunker.py"),
        SliceSelector(f"{APPLICATION}/document_fragments.py"),
        SliceSelector(f"{APPLICATION}/document_text.py"),
        SliceSelector(f"{USE_CASES}/delete_document.py"),
        SliceSelector(f"{USE_CASES}/ingest_document.py"),
        SliceSelector(f"{USE_CASES}/process_document.py"),
        SliceSelector(f"{USE_CASES}/query_documents.py"),
        SliceSelector(f"{POSTGRES}/migrations/0002_threads_documents_chunks.sql"),
        SliceSelector(f"{SERVER_API_V1}/documents.py"),
    ),
    "context_builder_ranking": (
        SliceSelector(
            f"{APPLICATION}/context_*.py",
            excludes=(
                f"{APPLICATION}/context_anchor*.py",
                f"{APPLICATION}/context_link_*.py",
            ),
        ),
        SliceSelector(f"{USE_CASES}/build_context.py"),
        SliceSelector(f"{SERVER_API_V1}/context.py"),
        SliceSelector(f"{SERVER_API_V1}/diagnostics.py"),
    ),
    "assets_extraction": (
        SliceSelector(f"{DOMAIN}/assets.py"),
        SliceSelector(f"{DOMAIN}/extraction.py"),
        SliceSelector(f"{APPLICATION}/asset_*.py"),
        SliceSelector(f"{APPLICATION}/extraction_*.py"),
        SliceSelector(f"{APPLICATION}/extractor.py"),
        SliceSelector(f"{APPLICATION}/multimodal_manifest.py"),
        SliceSelector(f"{APPLICATION}/storage_key_safety.py"),
        SliceSelector(f"{USE_CASES}/asset_*.py"),
        SliceSelector(f"{USE_CASES}/assets.py"),
        SliceSelector(f"{USE_CASES}/blob_storage_*.py"),
        SliceSelector(f"{PORTS}/assets.py"),
        SliceSelector(f"{PORTS}/extraction.py"),
        SliceSelector(f"{PORTS}/transcription.py"),
        SliceSelector(f"{PORTS}/vision.py"),
        SliceSelector(f"{ADAPTERS}/extraction/**"),
        SliceSelector(f"{ADAPTERS}/local_blob.py"),
        SliceSelector(f"{ADAPTERS}/s3_blob.py"),
        SliceSelector(f"{POSTGRES}/asset_repositories.py"),
        SliceSelector(f"{POSTGRES}/migrations/0011_asset_extractions.sql"),
        SliceSelector(f"{POSTGRES}/migrations/0012_asset_extraction_execution_hardening.sql"),
        SliceSelector(f"{SERVER_API_V1}/assets.py"),
    ),
    "context_links_anchors_suggestions": (
        SliceSelector(f"{APPLICATION}/anchor_*.py"),
        SliceSelector(f"{APPLICATION}/context_anchor*.py"),
        SliceSelector(f"{APPLICATION}/context_link_*.py"),
        SliceSelector(f"{APPLICATION}/observed_anchor_resolution.py"),
        SliceSelector(f"{USE_CASES}/anchors.py"),
        SliceSelector(f"{USE_CASES}/context_link_*.py"),
        SliceSelector(f"{USE_CASES}/context_links.py"),
        SliceSelector(f"{USE_CASES}/expire_suggestions.py"),
        SliceSelector(f"{USE_CASES}/suggestions.py"),
        SliceSelector(f"{POSTGRES}/migrations/0003_suggestions.sql"),
        SliceSelector(f"{POSTGRES}/migrations/0013_context_link_suggestions.sql"),
        SliceSelector(f"{POSTGRES}/migrations/0014_memory_anchors.sql"),
        SliceSelector(f"{SERVER_API_V1}/anchors.py"),
        SliceSelector(f"{SERVER_API_V1}/context_links.py"),
        SliceSelector(f"{SERVER_API_V1}/suggestions.py"),
    ),
    "digest_export": (
        SliceSelector(f"{CORE}/memory_scope_snapshot_preview.py"),
        SliceSelector(f"{CORE}/memory_scope_snapshots.py"),
        SliceSelector(f"{CORE}/reporting.py"),
        SliceSelector(f"{APPLICATION}/memory_digest_renderer.py"),
        SliceSelector(f"{USE_CASES}/build_memory_digest.py"),
        SliceSelector(f"{USE_CASES}/build_memory_insights.py"),
        SliceSelector(f"{USE_CASES}/export_graph.py"),
        SliceSelector(f"{SERVER_API_V1}/digest.py"),
        SliceSelector(f"{SERVER_API_V1}/export.py"),
        SliceSelector(f"{SERVER_API_V1}/insights.py"),
    ),
    "derived_projections": (
        SliceSelector(f"{PORTS}/adapters.py"),
        SliceSelector(f"{ADAPTERS}/cognee/**"),
        SliceSelector(f"{ADAPTERS}/embeddings/**"),
        SliceSelector(f"{ADAPTERS}/graphiti/**"),
        SliceSelector(f"{ADAPTERS}/noop/**"),
        SliceSelector(f"{ADAPTERS}/provider_errors.py"),
        SliceSelector(f"{ADAPTERS}/qdrant/**"),
    ),
    "sdk_mcp_connectors": (
        SliceSelector(f"{CORE}/agent_behavior_contract.py"),
        SliceSelector(f"{PYTHON_SDK}/**"),
        SliceSelector(f"{MCP}/**"),
        SliceSelector(f"{CLI}/**"),
        SliceSelector(f"{OBSIDIAN}/**"),
        SliceSelector(f"{TYPESCRIPT_SDK}/**"),
        SliceSelector(f"{OBSIDIAN_PLUGIN}/*.js"),
        SliceSelector(f"{OBSIDIAN_PLUGIN}/*.ts"),
    ),
    "architecture_support": (
        SliceSelector(f"{CORE}/__init__.py"),
        SliceSelector(f"{APPLICATION}/__init__.py"),
        SliceSelector(f"{APPLICATION}/dto.py"),
        SliceSelector(f"{USE_CASES}/__init__.py"),
        SliceSelector(f"{DOMAIN}/__init__.py"),
        SliceSelector(f"{PORTS}/__init__.py"),
        SliceSelector(f"{ADAPTERS}/__init__.py"),
        SliceSelector(f"{POSTGRES}/__init__.py"),
        SliceSelector(f"{CONTRACTS}/**"),
        SliceSelector(f"{SERVER_API_V1}/__init__.py"),
        SliceSelector(f"{SERVER_API_V1}/health.py"),
        SliceSelector(f"{SERVER_API_V1}/memory_browser.py"),
        SliceSelector(f"{SERVER_API_V1}/operations.py"),
    ),
}


def test_feature_slice_map_declares_required_bounded_contexts() -> None:
    missing = REQUIRED_BOUNDED_CONTEXTS - FEATURE_SLICE_MAP.keys()

    assert not missing, "Missing bounded-context slices: " + ", ".join(sorted(missing))


def test_key_package_source_files_have_exactly_one_feature_slice_owner() -> None:
    uncategorized: list[str] = []
    duplicate_owners: list[str] = []

    for relative_path in _key_source_files():
        owners = _owners_for(relative_path)
        if not owners:
            uncategorized.append(relative_path)
        elif len(owners) > 1:
            duplicate_owners.append(f"{relative_path}: {', '.join(owners)}")

    assert not uncategorized, "Uncategorized source files:\n" + "\n".join(uncategorized)
    assert not duplicate_owners, "Source files with multiple owners:\n" + "\n".join(
        duplicate_owners
    )


def test_feature_slice_selectors_stay_reviewable_and_current() -> None:
    source_files = _key_source_files()
    stale_selectors: list[str] = []

    for context, selectors in FEATURE_SLICE_MAP.items():
        for selector in selectors:
            if not any(_matches_selector(selector, relative_path) for relative_path in source_files):
                stale_selectors.append(f"{context}: {selector.include}")

    assert not stale_selectors, "Feature-slice selectors match no source files:\n" + "\n".join(
        stale_selectors
    )


def _key_source_files() -> list[str]:
    files: list[str] = []
    for root_name in KEY_PACKAGE_ROOTS:
        root = REPO_ROOT / root_name
        assert root.exists(), f"Missing feature-slice root: {root_name}"
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            relative_path = path.relative_to(REPO_ROOT).as_posix()
            if IGNORED_PATH_PARTS.intersection(path.parts):
                continue
            if any(relative_path.startswith(prefix) for prefix in IGNORED_PREFIXES):
                continue
            files.append(relative_path)
    return sorted(set(files))


def _owners_for(relative_path: str) -> list[str]:
    return [
        context
        for context, selectors in FEATURE_SLICE_MAP.items()
        if any(_matches_selector(selector, relative_path) for selector in selectors)
    ]


def _matches_selector(selector: SliceSelector, relative_path: str) -> bool:
    return _matches_pattern(selector.include, relative_path) and not any(
        _matches_pattern(exclude, relative_path) for exclude in selector.excludes
    )


def _matches_pattern(pattern: str, relative_path: str) -> bool:
    if pattern.endswith("/**"):
        prefix = pattern.removesuffix("/**")
        return relative_path == prefix or relative_path.startswith(f"{prefix}/")
    return fnmatch.fnmatchcase(relative_path, pattern)
