"""Replay complete planner outputs frozen before the policy decomposition."""

from __future__ import annotations

import base64
import importlib
import inspect
import json
import os
import pickle
import subprocess
import sys
from dataclasses import MISSING, FrozenInstanceError, fields
from pathlib import Path
from typing import get_origin, get_type_hints

import pytest
from infinity_context_server import memory_comparison_bundle_planner as planner

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures/memory_comparison_bundle_policy'
CONTRACT = json.loads((FIXTURES / 'contract.json').read_text())


def _candidate(payload: dict[str, object]) -> planner.EvidenceBundleCandidate:
    annotations = get_type_hints(planner.EvidenceBundleCandidate)
    restored = {
        name: tuple(value) if get_origin(annotations[name]) is tuple else value
        for name, value in payload.items()
    }
    candidate = planner.EvidenceBundleCandidate(**restored)
    for name, annotation in annotations.items():
        if get_origin(annotation) is tuple:
            assert type(getattr(candidate, name)) is tuple
    return candidate


def _sequence(values, kind: str):
    assert kind in {'tuple', 'list'}
    return tuple(values) if kind == 'tuple' else list(values)


@pytest.mark.parametrize('path', sorted(FIXTURES.glob('case_*.json')), ids=lambda p: p.stem)
def test_complete_planner_payload_matches_untouched_base(path: Path) -> None:
    case = json.loads(path.read_text())
    inputs = case['input']
    assert inputs['candidate_tuple_fields_verified'] is True
    candidates = _sequence(
        (_candidate(payload) for payload in inputs['candidates']),
        inputs['candidate_sequence_type'],
    )
    required_roles = _sequence(
        inputs['required_roles'], inputs['required_roles_sequence_type']
    )
    for config in (inputs['config'], *case.get('config_variants', ())):
        instance = planner.EvidenceBundlePlanner(**config)
        assert {
            name: getattr(instance, '_' + name) for name in config
        } == inputs['normalized_config']
        result = instance.plan(
            candidates, case_group=inputs['case_group'], required_roles=required_roles
        )
        assert type(result.items) is tuple
        for item in result.items:
            assert type(item.reason_codes) is tuple
            assert type(item.candidate.required_terms) is frozenset
        actual = {
            'items': [item.to_payload() for item in result.items],
            'diagnostics': result.to_diagnostics(),
        }
        assert json.dumps(actual) == json.dumps(case['expected']), case['source']


def test_original_public_and_private_call_signatures_are_preserved() -> None:
    assert CONTRACT['base_revision'] == '44ac164a8395c5847ae8792dded95d0dfe4526dd'
    assert {
        name: str(inspect.signature(getattr(planner, name)))
        for name in CONTRACT['signatures']
    } == CONTRACT['signatures']
    assert planner.BundleRole is str


@pytest.mark.parametrize('name', CONTRACT['dataclasses'])
def test_dataclass_fields_defaults_and_frozen_contract_are_preserved(name: str) -> None:
    cls = getattr(planner, name)
    actual = {
        'module': cls.__module__,
        'fields': [
            {
                'name': field.name,
                'type': str(field.type),
                'default': repr(field.default) if field.default is not MISSING else '<required>',
            }
            for field in fields(cls)
        ],
        'frozen': cls.__dataclass_params__.frozen,
    }
    expected = CONTRACT['dataclasses'][name]
    if name in {'EvidenceBundleCandidate', 'PlannedEvidenceItem'}:
        assert expected['module'] == 'infinity_context_server.memory_comparison_bundle_planner'
        assert actual['module'] == 'infinity_context_benchmarks.evidence_bundle.models'
        assert {key: value for key, value in actual.items() if key != 'module'} == {
            key: value for key, value in expected.items() if key != 'module'
        }
    else:
        assert actual == expected


@pytest.mark.parametrize('name', CONTRACT['legacy_pickles'])
def test_pickles_from_original_module_remain_readable(name: str) -> None:
    value = pickle.loads(base64.b64decode(CONTRACT['legacy_pickles'][name]))
    assert type(value) is getattr(planner, name)
    assert pickle.loads(pickle.dumps(value)) == value
    with pytest.raises(FrozenInstanceError):
        value.extra_attribute = True


@pytest.mark.parametrize('facade_first', [False, True])
def test_contracts_and_facade_import_in_either_order(facade_first: bool) -> None:
    modules = [
        'infinity_context_benchmarks.evidence_bundle.models',
        'infinity_context_server.memory_comparison_bundle_planner',
    ]
    if facade_first:
        modules.reverse()
    code = (
        'import importlib; '
        f'a, b = [importlib.import_module(name) for name in {modules!r}]; '
        'assert a.EvidenceBundleCandidate is b.EvidenceBundleCandidate; '
        'assert a.PlannedEvidenceItem is b.PlannedEvidenceItem'
    )
    subprocess.run(
        [sys.executable, '-c', code],
        env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)},
        check=True, capture_output=True, text=True,
    )


def test_source_and_public_safety_import_signatures_remain_compatible() -> None:
    contract = json.loads((FIXTURES / 'source_contract.json').read_text())
    for module_name, signatures in contract['signatures'].items():
        module = importlib.import_module(module_name)
        actual = {
            name: str(inspect.signature(getattr(module, name))) for name in signatures
        }
        assert actual == signatures
    for original_name, encoded in contract['legacy_pickles'].items():
        module_name, name = original_name.rsplit('.', 1)
        assert pickle.loads(base64.b64decode(encoded)) is getattr(
            importlib.import_module(module_name), name
        )
    old = importlib.import_module('infinity_context_core.application.sensitive_text')
    public = importlib.import_module('infinity_context_core.sensitive_text')
    assert old.contains_sensitive_text is public.contains_sensitive_text
    assert old.redact_sensitive_text is public.redact_sensitive_text
    assert old._SECRET_PATTERNS is public._SECRET_PATTERNS
    assert old._USERINFO_PATTERN is public._USERINFO_PATTERN
