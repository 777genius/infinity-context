"""Measurement artifacts must reject mixed runs and preserve interrupted records."""

from __future__ import annotations

import hashlib
import json
import os
import stat

import pytest

from scripts.answer_quality_artifacts import (
    ArtifactError,
    append_result,
    atomic_json,
    bind_manifest,
    canonical_json,
    load_pack,
    private_run_directory,
    public_counts,
    read_results,
    run_manifest,
    validate_record,
)


def _row(cid="one", **changes):
    return {
        "cid": cid,
        "question": "PRIVATE_QUESTION",
        "gold": "PRIVATE_GOLD",
        "context": "PRIVATE_CONTEXT",
        "qtype": "PRIVATE_QTYPE",
        "coverage_complete": True,
        **changes,
    }


def _record(cid="one", arm="with", verdict="correct", **changes):
    candidate = "PRIVATE_ANSWER"
    return {
        "run_sha256": "a" * 64,
        "cid": cid,
        "qtype": "PRIVATE_QTYPE",
        "arm": arm,
        "coverage_complete": True,
        "verdict": verdict,
        "candidate": candidate,
        "candidate_sha": hashlib.sha256(candidate.encode()).hexdigest()[:12],
        "candidate_chars": len(candidate),
        "call_failures": 0,
        "answer_ms": 1,
        "judge_ms": 2,
        **changes,
    }


def test_manifest_binds_selected_content_config_and_actual_source_bytes(tmp_path):
    evaluator = tmp_path / "runner.py"
    evaluator.write_text("original evaluator")
    manifest = run_manifest([_row()], {"model": "m1", "prompt": "p1"}, evaluator)
    assert manifest == run_manifest([_row()], {"prompt": "p1", "model": "m1"}, evaluator)
    assert manifest != run_manifest(
        [_row(context="changed")], {"model": "m1", "prompt": "p1"}, evaluator
    )
    assert manifest != run_manifest([_row()], {"model": "m2", "prompt": "p1"}, evaluator)
    assert manifest != run_manifest([_row()], {"model": "m1", "prompt": "p2"}, evaluator)
    evaluator.write_text("dirty evaluator")
    assert manifest != run_manifest([_row()], {"model": "m1", "prompt": "p1"}, evaluator)
    serialized = json.dumps(manifest)
    assert "PRIVATE_" not in serialized
    assert "answer_quality_artifacts.py" in manifest["source_sha256"]


def test_pack_sorts_cases_and_accepts_but_binds_historical_extra_fields(tmp_path):
    path = tmp_path / "pack.jsonl"
    rows = [_row("two", duplicated_question="legacy"), _row("one")]
    path.write_bytes(b"\n".join(canonical_json(row) for row in rows) + b"\n")
    assert load_pack(path, limit=0) == list(reversed(rows))
    assert load_pack(path, limit=1) == [_row("one")]


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\n",
        b"{}\n",
        b'{"cid":"a","cid":"b"}\n',
        canonical_json(_row(coverage_complete=1)) + b"\n",
        canonical_json(_row()) + b"\n" + canonical_json(_row()) + b"\n",
        canonical_json(_row(cid="")) + b"\n",
    ],
)
def test_invalid_packs_fail_without_echoing_input(tmp_path, content):
    path = tmp_path / "pack.jsonl"
    path.write_bytes(content)
    with pytest.raises(ArtifactError) as error:
        load_pack(path, limit=0)
    assert "PRIVATE_" not in str(error.value)


def test_legacy_results_are_never_silently_bound(tmp_path):
    (tmp_path / "results.jsonl").write_text('{"cid":"old"}\n')
    with pytest.raises(ArtifactError, match="unbound_historical"):
        bind_manifest(tmp_path, {"run_sha256": "new"})
    assert not (tmp_path / "manifest.json").exists()


def test_bound_manifest_refuses_changed_identity(tmp_path):
    bind_manifest(tmp_path, {"run_sha256": "one"})
    bind_manifest(tmp_path, {"run_sha256": "one"})
    with pytest.raises(ArtifactError, match="incompatible_run_identity"):
        bind_manifest(tmp_path, {"run_sha256": "two"})


@pytest.mark.parametrize("tail", [b'{"cid":', b"\xff", b'{"candidate":"\xd0'])
def test_torn_byte_tail_recovers_without_swallowing_next_record(tmp_path, tail):
    path = tmp_path / "results.jsonl"
    first = _record()
    prefix = canonical_json(first) + b"\n"
    path.write_bytes(prefix + tail)
    assert read_results(path, [_row()], "a" * 64) == [first]
    assert path.read_bytes() == prefix
    second = _record(arm="without")
    append_result(path, second)
    assert read_results(path, [_row()], "a" * 64) == [first, second]


def test_valid_terminal_record_gets_delimiter_and_is_not_recalled(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_bytes(canonical_json(_record()))
    assert read_results(path, [_row()], "a" * 64) == [_record()]
    assert path.read_bytes().endswith(b"\n")


@pytest.mark.parametrize(
    "content",
    [
        b'{"cid":\n',
        b'{"cid":\n' + canonical_json(_record()) + b"\n",
        b"{}",
        b"null",
        b"\n",
        b" ",
        b'{"cid":"one","cid":"one"}',
        canonical_json(_record(run_sha256="wrong")),
        canonical_json(_record()) + b"\n" + canonical_json(_record()) + b"\n",
    ],
)
def test_corruption_is_rejected_without_rewriting_good_or_bad_bytes(tmp_path, content):
    path = tmp_path / "results.jsonl"
    path.write_bytes(content)
    with pytest.raises(ArtifactError):
        read_results(path, [_row()], "a" * 64)
    assert path.read_bytes() == content


@pytest.mark.parametrize(
    "changes",
    [
        {"run_sha256": "other"},
        {"cid": "unknown"},
        {"arm": "bogus"},
        {"qtype": "wrong"},
        {"coverage_complete": 1},
        {"coverage_complete": False},
        {"verdict": "invented"},
        {"candidate_sha": "wrong"},
        {"candidate": "changed"},
        {"candidate_chars": True},
        {"call_failures": -1},
        {"answer_ms": 1.5},
        {"judge_ms": False},
        {"unexpected": "field"},
    ],
)
def test_resumed_records_validate_all_authoritative_fields(changes):
    with pytest.raises(ArtifactError):
        validate_record(_record(**changes), {"one": _row()}, "a" * 64)


def test_resolved_pair_partition_and_denominators_exclude_incomplete_errors():
    verdicts = ("correct", "incorrect", "missing")
    rows, records = [], []
    for first in verdicts:
        for second in verdicts:
            cid = f"{first}-{second}"
            rows.append(_row(cid))
            records.extend((_record(cid, "with", first), _record(cid, "without", second)))
    rows.extend((_row("error"), _row("incomplete")))
    records.extend(
        (
            _record("error", "with", "correct"),
            _record("error", "without", "call_failed"),
            _record("incomplete", "with", "correct"),
        )
    )
    result = public_counts(rows, records)
    assert result["paired"] == {
        "memory_helped": 2,
        "memory_hurt": 2,
        "both_correct": 1,
        "neither": 4,
    }
    assert result["pair_counts"] == {
        "expected": 11,
        "complete": 10,
        "resolved": 9,
        "incomplete": 1,
        "complete_but_unresolved": 1,
    }
    assert result["arm_metrics"]["without"]["resolved"] == 9
    assert result["arm_metrics"]["without"]["correct_per_expected"] == {
        "numerator": 3,
        "denominator": 11,
        "fraction": 3 / 11,
    }
    assert result["arm_metrics"]["without"]["incorrect_per_resolved"] == {
        "numerator": 3,
        "denominator": 9,
        "fraction": 1 / 3,
    }
    assert result["status"] == "incomplete"
    assert "PRIVATE_" not in json.dumps(result)


def test_empty_and_unresolved_denominators_do_not_report_false_precision():
    result = public_counts([_row()], [_record(verdict="unparsed"), _record(arm="without")])
    assert result["status"] == "complete_with_unresolved"
    assert sum(result["paired"].values()) == 0
    assert result["arm_metrics"]["with"]["correct_per_resolved"]["fraction"] is None
    assert public_counts([], [])["arm_metrics"]["with"]["correct_per_expected"]["fraction"] is None


@pytest.mark.skipif(os.name != "posix", reason="Linux measurement artifact contract")
def test_private_run_tightens_owned_modes_and_publishes_private_files(tmp_path):
    directory = tmp_path / "run"
    directory.mkdir(mode=0o755)
    (directory / "results.jsonl").write_text("")
    (directory / "results.jsonl").chmod(0o644)
    with private_run_directory(directory):
        bind_manifest(directory, {"run_sha256": "one"})
        append_result(directory / "results.jsonl", _record())
        atomic_json(directory / "aggregate.json", {"cases": 1})
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for path in directory.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("name", ["manifest.json", "results.jsonl", "aggregate.json", ".run.lock"])
def test_symlink_artifacts_rejected_before_write(tmp_path, name):
    directory = tmp_path / "run"
    directory.mkdir()
    target = tmp_path / "do-not-touch"
    target.write_text("unchanged")
    (directory / name).symlink_to(target)
    with (
        pytest.raises(ArtifactError, match="unsafe_artifact"),
        private_run_directory(directory),
    ):
        pytest.fail("symlink must fail preflight")
    assert target.read_text() == "unchanged"


def test_symlink_output_directory_is_rejected(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ArtifactError, match="unsafe_artifact"), private_run_directory(link):
        pytest.fail("symlink directory must fail preflight")


def test_atomic_publication_failure_preserves_previous_complete_json(tmp_path, monkeypatch):
    path = tmp_path / "aggregate.json"
    atomic_json(path, {"cases": 1})

    def fail_replace(*_args):
        raise OSError("simulated disk error")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError):
        atomic_json(path, {"cases": 2})
    assert json.loads(path.read_bytes()) == {"cases": 1}
    assert list(tmp_path.iterdir()) == [path]
