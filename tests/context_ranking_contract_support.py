"""Lossless, test-only values for the frozen ranking policy contracts."""

from __future__ import annotations

import dataclasses
import importlib
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures/context_policy_refactor/wave2_ranking"
BASE_SHA = "b0b87bd774f93c2bca9bec14c0efc072a2ba2de8"


def resolve(module: str, name: str):
    value = importlib.import_module(module)
    for part in name.split("."):
        value = getattr(value, part)
    return value


def encode(value):
    if isinstance(value, Enum):
        return {
            "kind": "enum",
            "module": type(value).__module__,
            "name": type(value).__qualname__,
            "value": encode(value.value),
        }
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            "kind": "dataclass",
            "module": type(value).__module__,
            "name": type(value).__qualname__,
            "fields": {
                field.name: encode(getattr(value, field.name))
                for field in dataclasses.fields(value)
            },
        }
    if isinstance(value, (datetime, date)):
        return {"kind": type(value).__name__, "value": value.isoformat()}
    if isinstance(value, Mapping):
        return {"kind": "mapping", "items": [[encode(k), encode(v)] for k, v in value.items()]}
    if isinstance(value, (tuple, list, set, frozenset)):
        items = [encode(item) for item in value]
        if isinstance(value, (set, frozenset)):
            items.sort(key=repr)
        return {"kind": type(value).__name__, "items": items}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported frozen contract value: {type(value)!r}")


def decode(value):
    if not isinstance(value, dict):
        return value
    kind = value["kind"]
    if kind == "dataclass":
        return resolve(value["module"], value["name"])(
            **{key: decode(item) for key, item in value["fields"].items()}
        )
    if kind == "enum":
        return resolve(value["module"], value["name"])(decode(value["value"]))
    if kind in {"date", "datetime"}:
        return {"date": date, "datetime": datetime}[kind].fromisoformat(value["value"])
    if kind == "mapping":
        return {decode(key): decode(item) for key, item in value["items"]}
    return {"tuple": tuple, "list": list, "set": set, "frozenset": frozenset}[kind](
        decode(item) for item in value["items"]
    )
