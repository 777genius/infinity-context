"""Complete pre-source contracts for the root and application compatibility APIs."""

from __future__ import annotations

import base64
import dataclasses
import importlib
import json
import pickle
from pathlib import Path

import pytest

from scripts.freeze_core_compatibility_exports import describe

FIXTURE = Path(__file__).parents[1] / "fixtures/core_compatibility_exports/contracts.json"
CONTRACT = json.loads(FIXTURE.read_text())
PACKAGES = CONTRACT["packages"]
EXPORTS = tuple((package, name) for package, record in PACKAGES.items() for name in record["all"])


@pytest.mark.parametrize(("package", "name"), EXPORTS)
def test_complete_export_contract_and_original_reference_identity(package, name):
    module = importlib.import_module(package)
    expected = PACKAGES[package]["exports"][name]
    value = getattr(module, name)
    route_module, attribute = expected["route"]
    defining = importlib.import_module(route_module)
    assert value is (getattr(defining, attribute) if attribute else defining)
    assert describe(value) == {key: item for key, item in expected.items() if key != "route"}
    if "reference_pickle" in expected:
        assert pickle.loads(base64.b64decode(expected["reference_pickle"])) is value
        assert pickle.loads(pickle.dumps(value)) is value


@pytest.mark.parametrize("package", PACKAGES)
def test_all_order_dir_from_import_and_star_import(package):
    module = importlib.import_module(package)
    expected = PACKAGES[package]
    assert type(module.__all__).__name__ == expected["all_type"] == "list"
    assert module.__all__ == expected["all"]
    assert set(expected["all"]) <= set(dir(module))
    imported = {}
    exec(f"from {package} import " + ", ".join(expected["all"]), imported)
    starred = {}
    exec(f"from {package} import *", starred)
    assert [key for key in starred if key != "__builtins__"] == expected["all"]
    for name in expected["all"]:
        assert imported[name] is starred[name] is getattr(module, name)


@pytest.mark.parametrize("package", PACKAGES)
def test_unknown_attribute_preserves_original_error(package):
    missing = PACKAGES[package]["missing"]
    with pytest.raises(AttributeError) as caught:
        getattr(importlib.import_module(package), missing["name"])
    assert list(caught.value.args) == missing["args"]


def test_overlapping_export_names_are_the_same_objects():
    core = importlib.import_module("infinity_context_core")
    application = importlib.import_module("infinity_context_core.application")
    for name in set(core.__all__) & set(application.__all__):
        assert getattr(core, name) is getattr(application, name)


@pytest.mark.parametrize("sample", CONTRACT["instances"].values())
def test_old_domain_dto_and_error_instance_pickles_remain_valid(sample):
    value = pickle.loads(base64.b64decode(sample["pickle"]))
    module = importlib.import_module(sample["module"])
    cls = getattr(module, sample["qualname"])
    assert type(value) is cls
    restored = pickle.loads(pickle.dumps(value))
    assert type(restored) is cls
    if dataclasses.is_dataclass(value):
        assert json.loads(json.dumps(dataclasses.asdict(value))) == sample["fields"]
        assert restored == value
    else:
        assert list(value.args) == list(restored.args) == sample["args"]
