"""Additive feature relation exports stay typed and provider independent."""

from __future__ import annotations

import importlib
import inspect
from typing import get_type_hints


def test_relation_public_symbols_resolve_to_their_feature_layers():
    root = "infinity_context_core.features.memory_facts"
    public = importlib.import_module(f"{root}.public")
    exports = {
        "domain": (
            "FactRelationConflict",
            "FactRelationSnapshot",
            "FactRelationStatus",
            "FactRelationType",
        ),
        "ports": ("FactRelationRepositoryPort",),
        "application": (
            "LinkFactsCommand",
            "LinkFactsHandler",
            "ListFactRelationsQuery",
            "ListFactRelationsHandler",
            "UnlinkFactRelationCommand",
            "UnlinkFactRelationHandler",
            "FactRelationResult",
            "FactRelationItem",
            "FactRelationsResult",
            "link_facts_in_transaction",
        ),
    }
    for layer, names in exports.items():
        module = importlib.import_module(f"{root}.{layer}")
        for name in names:
            value = getattr(public, name)
            assert value is getattr(module, name)
            assert name in public.__all__
            assert value.__module__.startswith(f"{root}.{layer}.")
            if inspect.isclass(value):
                assert all("Any" not in str(hint) for hint in get_type_hints(value).values())
    assert (
        get_type_hints(public.MemoryFactTransactionPort)["relations"]
        is public.FactRelationRepositoryPort
    )
