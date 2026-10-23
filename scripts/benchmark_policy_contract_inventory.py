"""Executable ownership and binding inventory for mechanical benchmark policy moves."""

from __future__ import annotations
import __future__

import ast
import builtins
import dataclasses
import dis
import inspect
import re
import types
import typing
from collections.abc import Mapping

INTENT_PREFIX = "infinity_context_benchmarks.retrieval_intent."
LEGACY_INTENT = "infinity_context_server.memory_comparison_intent"


def intent_owners(source: str) -> dict[str, str]:
    """Assign each original definition exactly one approved canonical owner."""
    groups = {
        "contracts": {
            "RetrievalEntityIntent",
            "RetrievalTimeIntent",
            "RetrievalRelationIntent",
            "RetrievalIntent",
        },
        "temporal": {"infer_time_intent_kind", "_has_ordinal_event_term"},
        "profile_patterns": {
            "_is_kinship_status_lookup",
            "_has_activity_profile_intent",
            "_has_status_profile_intent",
            "_has_commitment_profile_intent",
            "_has_education_profile_intent",
            "_has_employment_profile_intent",
            "_has_health_profile_intent",
            "_has_contact_profile_intent",
            "_has_diet_profile_intent",
            "_has_pet_profile_intent",
            "_has_skill_profile_intent",
            "_has_vehicle_profile_intent",
            "_has_date_profile_intent",
        },
        "comparison_patterns": {
            "_has_negative_absence_intent",
            "_has_contrast_intent",
            "_has_commonality_intent",
            "_has_explicit_difference_intent",
            "_has_comparative_choice_intent",
            "_has_count_intent",
            "_has_list_intent",
            "_COMMONALITY_INTENT_RE",
            "_EXPLICIT_DIFFERENCE_INTENT_RE",
            "_COMPARATIVE_CHOICE_INTENT_RE",
        },
        "relations": {
            "infer_relation_intents",
            "_relation_facet_reason_codes",
            "_dedupe_relation_intents",
            "_RELATION_FACET_CONFIG",
            "_TEMPORAL_SUPPORT_VARIANTS",
        },
        "evidence": {
            "infer_evidence_need",
            "infer_bundle_evidence_roles",
            "merge_relation_evidence_needs",
            "infer_risk_flags",
        },
    }
    owners = {name: INTENT_PREFIX + owner for owner, names in groups.items() for name in names}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            owners.setdefault(node.name, INTENT_PREFIX + "event_patterns")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    owners.setdefault(target.id, INTENT_PREFIX + "temporal")
    return owners


def public_names() -> tuple[str, ...]:
    return (
        "RetrievalEntityIntent",
        "RetrievalTimeIntent",
        "RetrievalRelationIntent",
        "RetrievalIntent",
        "infer_time_intent_kind",
        "infer_relation_intents",
        "infer_evidence_need",
        "infer_bundle_evidence_roles",
        "merge_relation_evidence_needs",
        "infer_risk_flags",
    )


def value_record(value: object, owners: Mapping[str, str]) -> object:
    if isinstance(value, __future__._Feature):
        return {"future": repr(value)}
    if isinstance(value, re.Pattern):
        return {"regex": value.pattern, "flags": value.flags}
    if isinstance(value, (set, frozenset)):
        return {"set": sorted(value_record(item, owners) for item in value)}
    if isinstance(value, (tuple, list)):
        return [value_record(item, owners) for item in value]
    if isinstance(value, Mapping):
        return {str(key): value_record(item, owners) for key, item in value.items()}
    if isinstance(value, types.ModuleType):
        return {"module": value.__name__}
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    name = getattr(value, "__name__", None)
    module = getattr(value, "__module__", None)
    if name and module:
        if module == LEGACY_INTENT:
            module = owners[name]
        return {"object": f"{module}.{getattr(value, '__qualname__', name)}"}
    raise TypeError(f"Unsupported contract value: {type(value)}")


def _global_names(code: types.CodeType) -> set[str]:
    names = {op.argval for op in dis.get_instructions(code) if op.opname == "LOAD_GLOBAL"}
    for constant in code.co_consts:
        if isinstance(constant, types.CodeType):
            names.update(_global_names(constant))
    return names


def _hint_record(value: object, owners: Mapping[str, str]) -> str:
    rendered = repr(value)
    for name, owner in owners.items():
        rendered = rendered.replace(f"{LEGACY_INTENT}.{name}", f"{owner}.{name}")
    return rendered


def callable_record(function, owners: Mapping[str, str]) -> dict[str, object]:
    bindings = {}
    for name in sorted(_global_names(function.__code__)):
        value = function.__globals__.get(name, getattr(builtins, name, None))
        bindings[name] = value_record(value, owners)
    return {
        "signature": str(inspect.signature(function)),
        "qualname": function.__qualname__,
        "doc": function.__doc__,
        "hints": {
            key: _hint_record(value, owners)
            for key, value in typing.get_type_hints(function).items()
        },
        "globals": bindings,
    }


def binding_inventory(module, owners: Mapping[str, str]) -> dict[str, object]:
    result = {}
    for name, value in vars(module).items():
        if name.startswith("__"):
            continue
        record = {"value": value_record(value, owners)}
        if name in owners:
            record.update(
                {
                    "owner": owners[name],
                    "visibility": "public" if name in public_names() else "compatibility-only",
                }
            )
            if inspect.isfunction(value):
                record["callable"] = callable_record(value, owners)
            elif inspect.isclass(value):
                record["signature"] = str(inspect.signature(value))
                record["fields"] = [field.name for field in dataclasses.fields(value)]
                record["doc"] = value.__doc__
                record["frozen"] = value.__dataclass_params__.frozen
                record["hints"] = {
                    key: _hint_record(item, owners)
                    for key, item in typing.get_type_hints(value).items()
                }
                record["methods"] = {
                    method_name: callable_record(method, owners)
                    for method_name, method in vars(value).items()
                    if inspect.isfunction(method)
                    and method.__code__.co_filename != "<string>"
                    and not method_name.startswith("__")
                }
                record["properties"] = {
                    method_name: callable_record(method.fget, owners)
                    for method_name, method in vars(value).items()
                    if isinstance(method, property)
                }
        else:
            record["visibility"] = "imported-compatibility"
        result[name] = record
    return result
