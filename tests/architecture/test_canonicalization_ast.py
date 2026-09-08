"""Mutation fixtures for the bounded ownership checks; no provider imports."""

from __future__ import annotations

import pytest
from canonicalization_ast import (
    ADAPTERS,
    CORE,
    REPO_ROOT,
    SERVER,
    SourceIndex,
    compatibility_imports,
    container_overlaps,
    dormant_edges,
    legacy_execution_edges,
    require_inventory,
    route_edges,
)

ROUTE = REPO_ROOT / f"packages/{SERVER}/{SERVER}/api/v1/facts.py"
SHIM = REPO_ROOT / f"packages/{SERVER}/{SERVER}/api/compatibility.py"
LEGACY = f"{CORE}.application.use_cases.remember_fact.RememberFactUseCase"
FIELDS = {
    "remember_fact": LEGACY,
    "memory_fact_lifecycle": f"{CORE}.features.memory_facts.public.MemoryFactLifecycleUseCases",
    "locator_retrieval": f"{SERVER}.features.context_building.public.LocatorRetrievalService",
}


@pytest.mark.parametrize(
    "access",
    [
        "container.remember_fact.execute(command)",
        "alias = container.remember_fact\n    alias.execute(command)",
        "invoke = container.remember_fact.execute\n    invoke(command)",
        "forward(container.remember_fact, command)",
    ],
)
def test_new_legacy_container_invocation_is_rejected(access: str) -> None:
    source = f"""
from ...composition import Container as Services
async def migrated(container: Services):
    {access}
"""
    index = SourceIndex({ROUTE: source})
    edges = route_edges(index, [ROUTE], FIELDS)
    assert edges
    with pytest.raises(AssertionError, match="New execution debt"):
        require_inventory(edges, set())


def test_annotated_container_local_helper_and_assignment_aliases() -> None:
    source = f"""
from typing import Annotated
from {SERVER}.composition import Container as Services
async def helper(c: Services):
    owner = c.remember_fact
    return await owner.execute(command)
async def endpoint(c: Annotated[Services, Depends(get_container)]):
    return await helper(c)
"""
    index = SourceIndex({ROUTE: source})
    edges = route_edges(index, [ROUTE], FIELDS)
    assert edges == {
        (f"{SERVER}.api.v1.facts.helper", "remember_fact.execute"),
        (f"{SERVER}.api.v1.facts.endpoint", "remember_fact.execute"),
    }


@pytest.mark.parametrize(
    "source",
    [
        f"from {CORE}.application.use_cases.remember_fact import RememberFactUseCase as Old\nOld()",
        f"import {CORE}.application.use_cases.remember_fact as old\nold.RememberFactUseCase()",
        "from ..compatibility import Old\nfactory = Old\nfactory()",
        f"from {CORE}.application.use_cases.remember_fact import RememberFactUseCase\n"
        "def endpoint():\n    owner = RememberFactUseCase()\n    owner.execute(command)",
    ],
)
def test_direct_legacy_construction_cannot_bypass_container(source: str) -> None:
    index = SourceIndex(
        {
            ROUTE: source,
            SHIM: (
                f"from {CORE}.application.use_cases.remember_fact import RememberFactUseCase as Old"
            ),
        }
    )
    edges = legacy_execution_edges(index, [ROUTE])
    assert edges
    with pytest.raises(AssertionError, match="New execution debt"):
        require_inventory(edges, set())


def test_error_and_dto_imports_and_construction_remain_legal() -> None:
    source = f"""
from {CORE}.domain.errors import NotFoundError as Missing
from {CORE}.application.dto import RememberFactCommand as Command
from {CORE}.application.use_cases.remember_fact import RememberFactUseCase

def endpoint():
    request = Command(text='evidence')
    raise Missing('gone')
"""
    index = SourceIndex({ROUTE: source})
    assert len(compatibility_imports(index, ROUTE)) == 2
    assert legacy_execution_edges(index, [ROUTE]) == set()
    assert route_edges(index, [ROUTE], FIELDS) == set()


def test_distinct_locator_owner_is_allowed_without_context_overlap() -> None:
    source = f"""
from {SERVER}.composition import Container
async def endpoint(container: Container):
    return await container.locator_retrieval.execute(query)
"""
    index = SourceIndex({ROUTE: source})
    assert container_overlaps(FIELDS) == {
        ("remember_fact", "memory_fact_lifecycle.remember_fact"),
    }
    assert route_edges(index, [ROUTE], FIELDS) == {
        (f"{SERVER}.api.v1.facts.endpoint", "locator_retrieval.execute"),
    }


def test_new_container_pair_rejected_even_with_different_field_names() -> None:
    recorded = container_overlaps(FIELDS)
    changed = {**FIELDS, "extra_old_writer": LEGACY}
    with pytest.raises(AssertionError, match="extra_old_writer"):
        require_inventory(container_overlaps(changed), recorded)


def test_removed_pair_requires_explicit_inventory_removal() -> None:
    recorded = container_overlaps(FIELDS)
    changed = {name: owner for name, owner in FIELDS.items() if name != "remember_fact"}
    with pytest.raises(AssertionError, match="explicitly remove stale inventory"):
        require_inventory(container_overlaps(changed), recorded)
    require_inventory(container_overlaps(changed), set())


@pytest.mark.parametrize(
    ("module", "symbol"),
    [
        ("document_ingestion.postgres_document_store", "PostgresSourceDocumentStore"),
        ("document_ingestion.postgres_document_store", "PostgresDocumentChunkStore"),
        ("document_ingestion.postgres_document_store", "PostgresDocumentIngestionStore"),
        ("document_ingestion.qdrant_chunk_index", "QdrantDocumentChunkIndex"),
        ("memory_scopes.postgres_scope_store", "PostgresMemoryScopeStore"),
        ("memory_facts.qdrant_fact_projection", "QdrantMemoryFactProjection"),
        ("memory_facts.graphiti_fact_projection", "GraphitiMemoryFactProjection"),
        ("memory_scopes.postgres_scope_store", "create_postgres_memory_scope_unit_of_work_factory"),
    ],
)
@pytest.mark.parametrize("use", ["factory()", "wire(factory)", "alias = factory\nalias()"])
def test_production_placeholder_construction_and_injection_fail(
    module: str,
    symbol: str,
    use: str,
) -> None:
    source = f"from {ADAPTERS}.features.{module} import {symbol} as factory\n{use}"
    index = SourceIndex({ROUTE: source})
    assert dormant_edges(index, [ROUTE]) == {
        (f"{SERVER}.api.v1.facts", f"{ADAPTERS}.features.{module}.{symbol}")
    }


def test_relative_placeholder_reexport_is_resolved_but_export_alone_is_legal() -> None:
    module = f"{ADAPTERS}.features.document_ingestion"
    public = REPO_ROOT / f"packages/{ADAPTERS}/{ADAPTERS}/features/document_ingestion/__init__.py"
    index = SourceIndex(
        {
            public: "from .qdrant_chunk_index import QdrantDocumentChunkIndex as Index",
            SHIM: f"from {module} import Index as Factory",
            ROUTE: "from ..compatibility import Factory\nFactory()",
        }
    )
    assert dormant_edges(index, [public, SHIM]) == set()
    assert dormant_edges(index, [ROUTE])


def test_dormant_module_internal_factories_remain_legal() -> None:
    path = REPO_ROOT / (
        f"packages/{ADAPTERS}/{ADAPTERS}/features/document_ingestion/qdrant_chunk_index.py"
    )
    index = SourceIndex(
        {
            path: "class QdrantDocumentChunkIndex: pass\n"
            "def create(): return QdrantDocumentChunkIndex()"
        }
    )
    assert dormant_edges(index, [path]) == set()


def test_function_alias_does_not_leak_into_another_scope() -> None:
    source = f"""
from {ADAPTERS}.features.document_ingestion.qdrant_chunk_index import QdrantDocumentChunkIndex
def dormant_reference():
    factory = QdrantDocumentChunkIndex

def unrelated(factory):
    factory()
"""
    index = SourceIndex({ROUTE: source})
    assert dormant_edges(index, [ROUTE]) == set()


@pytest.mark.parametrize(
    "body",
    [
        "def helper(value=Factory()): pass",
        "@decorate(Factory())\ndef helper(): pass",
        "class Helper(Factory()): pass",
        "def helper():\n    from infinity_context_adapters.features.document_ingestion "
        "import qdrant_chunk_index as q\n    q.QdrantDocumentChunkIndex()",
    ],
)
def test_placeholder_calls_in_defaults_decorators_bases_and_lazy_imports(body: str) -> None:
    index = SourceIndex(
        {
            ROUTE: f"from {ADAPTERS}.features.document_ingestion.qdrant_chunk_index "
            f"import QdrantDocumentChunkIndex as Factory\n{body}"
        }
    )
    assert dormant_edges(index, [ROUTE])


def test_container_fields_resolve_relative_imports_and_type_aliases() -> None:
    composition = REPO_ROOT / f"packages/{SERVER}/{SERVER}/composition.py"
    index = SourceIndex(
        {
            composition: f"""
from {CORE}.application.use_cases.remember_fact import RememberFactUseCase as Old
from {CORE}.features.memory_facts.public import MemoryFactLifecycleUseCases as New
class Container:
    remember_fact: Old
    another_writer: Old
    memory_fact_lifecycle: New
"""
        }
    )
    with pytest.raises(AssertionError, match="another_writer"):
        require_inventory(
            container_overlaps(index.fields(composition, "Container")), container_overlaps(FIELDS)
        )


def test_typed_injected_legacy_owner_invocation_is_execution_debt() -> None:
    source = f"from {CORE}.application.use_cases.remember_fact import RememberFactUseCase\n"
    source += "def endpoint(owner: RememberFactUseCase):\n    owner.execute(command)"
    index = SourceIndex({ROUTE: source})
    assert legacy_execution_edges(index, [ROUTE])


def test_dormant_export_module_cannot_eagerly_construct_placeholder() -> None:
    path = REPO_ROOT / (
        f"packages/{ADAPTERS}/{ADAPTERS}/features/document_ingestion/qdrant_chunk_index.py"
    )
    index = SourceIndex(
        {path: "class QdrantDocumentChunkIndex: pass\ndefault = QdrantDocumentChunkIndex()"}
    )
    assert dormant_edges(index, [path])


@pytest.mark.parametrize(
    "annotation",
    ['"Services"', '"Annotated[Services, Depends(get_container)]"', 'Optional["Services"]'],
)
def test_quoted_container_annotation_executes(annotation: str) -> None:
    index = SourceIndex(
        {
            ROUTE: f"""
from typing import Annotated, Optional
from {SERVER}.composition import Container as Services
def endpoint(c: {annotation}):
    c.remember_fact.execute(command)
"""
        }
    )
    assert (f"{SERVER}.api.v1.facts.endpoint", "remember_fact.execute") in route_edges(
        index, [ROUTE], FIELDS
    )


def test_quoted_additional_overlap_is_rejected() -> None:
    index = SourceIndex(
        {
            ROUTE: f"""
from {CORE}.application.use_cases.remember_fact import RememberFactUseCase as Old
from {CORE}.features.memory_facts.public import MemoryFactLifecycleUseCases as New
class Container:
    remember_fact: Old
    another_writer: "Old"
    memory_fact_lifecycle: New
"""
        }
    )
    with pytest.raises(AssertionError, match="another_writer"):
        require_inventory(
            container_overlaps(index.fields(ROUTE, "Container")), container_overlaps(FIELDS)
        )


def test_quoted_placeholder_injection_and_ordinary_string_are_distinct() -> None:
    prefix = (
        f"from {ADAPTERS}.features.document_ingestion.qdrant_chunk_index "
        f"import QdrantDocumentChunkIndex as Factory\n"
    )
    index = SourceIndex({ROUTE: prefix + 'def endpoint(x: "Factory"):\n    wire(x)'})
    assert dormant_edges(index, [ROUTE])
    index = SourceIndex({ROUTE: prefix + 'log("Factory()", "Container", "not valid Python !")'})
    assert not dormant_edges(index, [ROUTE])
    assert not route_edges(index, [ROUTE], FIELDS)


@pytest.mark.parametrize(
    "body",
    [
        (
            "def helper(*, services):\n"
            "    services.remember_fact.execute(command)\n"
            "def endpoint(c: Container):\n    helper(services=c)"
        ),
        (
            "def helper(services):\n"
            "    services.remember_fact.execute(command)\n"
            "def endpoint(c: Container):\n    helper(c)"
        ),
        (
            "def inner(*, services):\n"
            "    services.remember_fact.execute(command)\ndef helper(c):\n"
            "    inner(services=c)\ndef endpoint(c: Container):\n    helper(c)"
        ),
        (
            "def endpoint(c: Container):\n    def helper():\n"
            "        c.remember_fact.execute(command)\n    helper()"
        ),
    ],
)
def test_forwarded_container_and_nested_capture_reach_endpoint(body: str) -> None:
    index = SourceIndex({ROUTE: f"from {SERVER}.composition import Container\n{body}"})
    edges = route_edges(index, [ROUTE], FIELDS)
    assert (f"{SERVER}.api.v1.facts.endpoint", "remember_fact.execute") in edges
    with pytest.raises(AssertionError, match="New execution debt"):
        require_inventory(edges, set())


def test_unknown_container_forwarding_fails_closed() -> None:
    index = SourceIndex(
        {
            ROUTE: (
                f"from {SERVER}.composition import Container\n"
                f"def endpoint(c: Container):\n    unknown(services=c)"
            )
        }
    )
    with pytest.raises(AssertionError, match="Unresolved Container forwarding"):
        route_edges(index, [ROUTE], FIELDS)


@pytest.mark.parametrize(
    "registration",
    [
        'router.add_api_route("/new", imported)',
        'router.add_api_route(path="/new", endpoint=imported)',
        "def endpoint():\n    imported()",
        "router.include_router(imported)",
    ],
)
def test_imported_handlers_helpers_and_feature_router_are_followed(registration: str) -> None:
    feature = REPO_ROOT / f"packages/{SERVER}/{SERVER}/features/new_feature/routes.py"
    index = SourceIndex(
        {
            ROUTE: (
                f"from {SERVER}.features.new_feature.routes import endpoint as "
                f"imported\n{registration}"
            ),
            feature: (
                f"from {SERVER}.composition import Container\n"
                f"def endpoint(c: Container):\n    c.remember_fact.execute(command)"
            ),
        }
    )
    edges = route_edges(index, [ROUTE], FIELDS)
    assert (f"{SERVER}.features.new_feature.routes.endpoint", "remember_fact.execute") in edges
    with pytest.raises(AssertionError, match="New execution debt"):
        require_inventory(edges, set())


def test_unknown_registration_is_rejected() -> None:
    index = SourceIndex({ROUTE: 'router.add_api_route("/new", dynamic_handler)'})
    with pytest.raises(AssertionError, match="Unresolved route registration"):
        route_edges(index, [ROUTE], FIELDS)


def test_feature_routes_selected_and_benchmarks_explicitly_excluded(monkeypatch) -> None:
    import canonicalization_ast as analyzer  # noqa: PLC0415

    feature = REPO_ROOT / f"packages/{SERVER}/{SERVER}/features/new_feature/routes.py"
    benchmark = ROUTE.with_name("internal_memory_comparison_runs.py")
    monkeypatch.setattr(analyzer, "_server_route_modules", lambda: [ROUTE, feature, benchmark])
    assert {ROUTE, feature} <= set(analyzer.canonicalization_routes())
    assert benchmark not in analyzer.canonicalization_routes()
    index = SourceIndex(
        {
            ROUTE: "from .internal_memory_comparison_runs import endpoint\nendpoint()",
            benchmark: (
                f"from {SERVER}.composition import Container\n"
                f"def endpoint(c: Container):\n    c.remember_fact.execute(command)"
            ),
        }
    )
    assert not route_edges(index, [ROUTE], FIELDS)


@pytest.mark.parametrize(
    "body, expected",
    [
        ("class Defaults:\n    Factory = int\ndef endpoint():\n    Factory()", True),
        ("def endpoint():\n    def Factory(): pass\n    Factory()", False),
        ("def endpoint():\n    class Factory: pass\n    Factory()", False),
        ("class Defaults:\n    Factory = int\n    value = Factory()", False),
        ("class Defaults:\n    Factory = int\n    def method(self):\n        Factory()", True),
        (
            (
                "def endpoint():\n    def Factory(): pass\n    class Defaults:\n"
                "        def method(self):\n            Factory()"
            ),
            False,
        ),
    ],
)
def test_class_and_function_lexical_bindings(body: str, expected: bool) -> None:
    index = SourceIndex(
        {
            ROUTE: (
                f"from {ADAPTERS}.features.document_ingestion.qdrant_chunk_index "
                f"import QdrantDocumentChunkIndex as Factory\n{body}"
            )
        }
    )
    assert bool(dormant_edges(index, [ROUTE])) is expected


@pytest.mark.parametrize(
    "body, expected",
    [
        ("class Defaults:\n    value = QdrantDocumentChunkIndex()", True),
        ("class Defaults:\n    class Nested:\n        value = QdrantDocumentChunkIndex()", True),
        ("class Defaults:\n    def method(self, value=QdrantDocumentChunkIndex()): pass", True),
        (
            "class Defaults:\n    def method(self):\n        return QdrantDocumentChunkIndex()",
            False,
        ),
        ("def factory():\n    class Defaults:\n        value = QdrantDocumentChunkIndex()", False),
    ],
)
def test_dormant_class_eagerness_is_separate_from_lexical_caller(body: str, expected: bool) -> None:
    path = (
        REPO_ROOT
        / f"packages/{ADAPTERS}/{ADAPTERS}/features/document_ingestion/qdrant_chunk_index.py"
    )
    index = SourceIndex({path: f"class QdrantDocumentChunkIndex: pass\n{body}"})
    assert bool(dormant_edges(index, [path])) is expected


@pytest.mark.parametrize(
    "assignment",
    [
        "factory = create_qdrant_document_chunk_index",
        "factory: object = create_qdrant_document_chunk_index",
    ],
)
def test_valued_reexport_assignments_share_index_extraction(assignment: str) -> None:
    index = SourceIndex(
        {
            SHIM: (
                f"from {ADAPTERS}.features.document_ingestion.qdrant_chunk_index "
                f"import create_qdrant_document_chunk_index\n{assignment}"
            ),
            ROUTE: "from ..compatibility import factory\nfactory()",
        }
    )
    assert not dormant_edges(index, [SHIM])
    assert dormant_edges(index, [ROUTE]) == {
        (
            f"{SERVER}.api.v1.facts",
            (
                f"{ADAPTERS}.features.document_ingestion.qdrant_chunk_index."
                f"create_qdrant_document_chunk_index"
            ),
        )
    }


@pytest.mark.parametrize(
    "mount, export",
    [
        ("router.include_router(imported)", "router"),
        ("router.include_router(imported())", "build_router"),
    ],
)
def test_real_imported_router_and_factory_registration(mount: str, export: str) -> None:
    feature = ROUTE.with_name("new_router.py")
    index = SourceIndex(
        {
            ROUTE: f"from .new_router import {export} as imported\n{mount}",
            feature: f"""
from fastapi import APIRouter
from {SERVER}.composition import Container
router = APIRouter()
def build_router():
    return router
@router.get('/new')
def endpoint(c: Container):
    c.remember_fact.execute(command)
""",
        }
    )
    assert (f"{SERVER}.api.v1.new_router.endpoint", "remember_fact.execute") in route_edges(
        index, [ROUTE], FIELDS
    )


def test_imported_helper_keyword_container_and_direct_legacy_execution() -> None:
    index = SourceIndex(
        {
            ROUTE: f"from {SERVER}.composition import Container\n"
            "from ..compatibility import helper\ndef endpoint(c: Container):\n"
            "    helper(services=c)",
            SHIM: f"from {CORE}.application.use_cases.remember_fact import RememberFactUseCase\n"
            "def helper(*, services):\n    services.remember_fact.execute(command)\n"
            "    RememberFactUseCase()",
        }
    )
    assert (f"{SERVER}.api.v1.facts.endpoint", "remember_fact.execute") in route_edges(
        index, [ROUTE], FIELDS
    )
    assert (f"{SERVER}.api.compatibility.helper", LEGACY) in legacy_execution_edges(index, [ROUTE])


def test_imported_unused_sibling_is_not_a_reachable_helper() -> None:
    index = SourceIndex(
        {
            ROUTE: "from ..compatibility import helper\nhelper()",
            SHIM: f"from {SERVER}.composition import Container\ndef helper(): pass\n"
            "def unused(c: Container):\n    c.remember_fact.execute(command)",
        }
    )
    assert not route_edges(index, [ROUTE], FIELDS)


def test_ambiguous_ownership_annotation_is_explicitly_rejected() -> None:
    index = SourceIndex(
        {
            ROUTE: f"from {SERVER}.composition import Container\n"
            'def endpoint(c: "Container | int"):\n    c.remember_fact.execute(command)'
        }
    )
    with pytest.raises(AssertionError, match="Unresolved ownership-relevant"):
        route_edges(index, [ROUTE], FIELDS)


def test_annotation_uses_defining_scope_before_function_local_shadow() -> None:
    index = SourceIndex(
        {
            ROUTE: f"from {ADAPTERS}.features.document_ingestion.qdrant_chunk_index "
            'import QdrantDocumentChunkIndex as Factory\ndef endpoint(x: "Factory"):\n'
            "    def Factory(): pass\n    wire(x)"
        }
    )
    assert dormant_edges(index, [ROUTE])


def test_keyword_names_are_retained_for_equal_value_sequences() -> None:
    index = SourceIndex(
        {
            ROUTE: f"from {SERVER}.composition import Container\n"
            + """
def helper(*, services, unused):
    services.remember_fact.execute(command)
def endpoint(c: Container, x):
    helper(services=c, unused=x)
    helper(unused=c, services=x)
"""
        }
    )
    assert (f"{SERVER}.api.v1.facts.endpoint", "remember_fact.execute") in route_edges(
        index, [ROUTE], FIELDS
    )


@pytest.mark.parametrize("export", ["missing", "external"])
def test_registered_import_must_resolve_beyond_its_module(export: str) -> None:
    index = SourceIndex(
        {
            ROUTE: f'from ..compatibility import {export}\nrouter.add_api_route("/new", {export})',
            SHIM: "from unavailable_provider import endpoint as external",
        }
    )
    with pytest.raises(AssertionError, match="Unresolved route registration"):
        route_edges(index, [ROUTE], FIELDS)


@pytest.mark.parametrize(
    "future, expected", [("", True), ("from __future__ import annotations\n", False)]
)
def test_annotation_construction_respects_evaluation_context(future: str, expected: bool) -> None:
    path = REPO_ROOT / (
        f"packages/{ADAPTERS}/{ADAPTERS}/features/document_ingestion/qdrant_chunk_index.py"
    )
    index = SourceIndex(
        {
            path: future + "class QdrantDocumentChunkIndex: pass\n"
            "class Defaults:\n    def method(self, x: QdrantDocumentChunkIndex()): pass"
        }
    )
    assert bool(dormant_edges(index, [path])) is expected


@pytest.mark.parametrize("call", ['helper(**{"services": c})', "helper(*[c])"])
def test_unresolved_container_unpacking_is_explicitly_rejected(call: str) -> None:
    index = SourceIndex(
        {
            ROUTE: f"from {SERVER}.composition import Container\n"
            f"def endpoint(c: Container):\n    {call}"
        }
    )
    with pytest.raises(AssertionError, match="Unresolved Container forwarding"):
        route_edges(index, [ROUTE], FIELDS)
