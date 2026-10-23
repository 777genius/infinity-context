"""Replay complete planner outputs frozen before the policy decomposition."""

from __future__ import annotations

import base64
import inspect
import json
import pickle
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
        assert {
            'items': [item.to_payload() for item in result.items],
            'diagnostics': result.to_diagnostics(),
        } == case['expected'], case['source']


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
    assert actual == CONTRACT['dataclasses'][name]


@pytest.mark.parametrize('name', CONTRACT['legacy_pickles'])
def test_pickles_from_original_module_remain_readable(name: str) -> None:
    value = pickle.loads(base64.b64decode(CONTRACT['legacy_pickles'][name]))
    assert type(value) is getattr(planner, name)
    assert pickle.loads(pickle.dumps(value)) == value
    with pytest.raises(FrozenInstanceError):
        value.extra_attribute = True
