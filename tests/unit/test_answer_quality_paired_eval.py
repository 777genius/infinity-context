"""Exercise the real resumable CLI with a local deterministic runner, no provider calls."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.answer_quality_paired_eval import _verdict

_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"verdict":"correct"}', "correct"),
        ('{"verdict":"incorrect"}', "incorrect"),
        ('{"verdict":"missing"}', "missing"),
        ('{"verdict":"unsupported"} correct', "unparsed"),
        ('{"verdict":true} correct', "unparsed"),
        ('{"verdict":\n} correct', "unparsed"),
        ('{"verdict":"correct","verdict":"incorrect"}', "unparsed"),
        ('{"verdict":"correct"', "unparsed"),
        ('{"verdict":"correct"} {"verdict":"incorrect"}', "unparsed"),
        ('```json\n{"verdict":"correct"}\n```', "correct"),
        ("{'verdict':'correct'} correct", "unparsed"),
        ('{"other":"correct"}', "unparsed"),
        ('["correct"]', "unparsed"),
        ('"correct"', "unparsed"),
        ("The answer is correct or incorrect.", "unparsed"),
        ("The candidate is incorrect.", "incorrect"),
        ("No usable judgment.", "unparsed"),
    ],
)
def test_verdict_allowlist_keeps_explicit_invalid_judgment_unresolved(raw, expected):
    assert _verdict(raw) == expected


@pytest.fixture
def cli(tmp_path):
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    for name in ("answer_quality_paired_eval.py", "answer_quality_artifacts.py"):
        shutil.copyfile(_ROOT / "scripts" / name, script_dir / name)
    executable_dir = tmp_path / "bin"
    executable_dir.mkdir()
    runner = executable_dir / "qodercli"
    runner.write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, pathlib, sys, time
with pathlib.Path(os.environ["ANSWER_EVAL_TEST_CALLS"]).open("a") as stream:
    stream.write("call\\n")
block = os.environ.get("ANSWER_EVAL_TEST_BLOCK")
if block:
    deadline = time.monotonic() + 15
    while pathlib.Path(block).exists() and time.monotonic() < deadline:
        time.sleep(0.01)
prompt = sys.argv[sys.argv.index("-p") + 1]
if prompt.startswith("You grade"):
    verdict = "missing" if "CANDIDATE ANSWER: I don't know" in prompt else "correct"
    print(json.dumps({"verdict": verdict}))
elif "(empty: no memory retrieved)" in prompt:
    print("I don't know")
else:
    print("PRIVATE_ANSWER")
"""
    )
    runner.chmod(0o755)
    pack = tmp_path / "pack.jsonl"
    row = {
        "cid": "case-1",
        "question": "PRIVATE_QUESTION",
        "gold": "PRIVATE_GOLD",
        "context": "PRIVATE_CONTEXT",
        "qtype": "PRIVATE_QTYPE",
        "coverage_complete": True,
        "duplicated_question": "harmless historical extra",
    }
    pack.write_text(json.dumps(row) + "\n")
    output = tmp_path / "output"
    log = tmp_path / "calls.txt"
    env = {
        **os.environ,
        "PATH": str(executable_dir) + os.pathsep + os.environ["PATH"],
        "ANSWER_EVAL_TEST_CALLS": str(log),
    }
    command = [
        sys.executable,
        str(script_dir / "answer_quality_paired_eval.py"),
        "--pack",
        str(pack),
        "--out-dir",
        str(output),
        "--workers",
        "1",
    ]
    return command, env, output, log, pack, script_dir


def _run(cli, *extra, env=None):
    command, original_env, *_ = cli
    return subprocess.run(
        [*command, *extra],
        env=env or original_env,
        capture_output=True,
        text=True,
        timeout=25,
    )


def _calls(log):
    return len(log.read_text().splitlines()) if log.exists() else 0


def test_cli_retains_private_answers_and_resumes_without_recalls(cli):
    first = _run(cli)
    assert first.returncode == 0, first.stderr
    _, _, directory, log, *_ = cli
    assert _calls(log) == 4
    result = json.loads((directory / "aggregate.json").read_text())
    assert result["paired"]["memory_helped"] == 1
    assert result["status"] == "complete"
    assert "PRIVATE_" not in first.stdout + first.stderr + json.dumps(result)
    records = [json.loads(line) for line in (directory / "results.jsonl").read_text().splitlines()]
    assert any(row["candidate"] == "PRIVATE_ANSWER" for row in records)
    assert all(row["run_sha256"] == result["run_sha256"] for row in records)
    second = _run(cli, "--workers", "2")
    assert second.returncode == 0, second.stderr
    assert "pending_arms=0" in second.stdout
    assert _calls(log) == 4


@pytest.mark.parametrize("change", ["pack", "model", "evaluator", "helper"])
def test_cli_rejects_incompatible_resumes_before_new_model_calls(cli, change):
    assert _run(cli).returncode == 0
    _, _, _, log, pack, script_dir = cli
    extra = []
    if change == "pack":
        row = json.loads(pack.read_text())
        row["context"] = "CHANGED_PRIVATE_CONTEXT"
        pack.write_text(json.dumps(row) + "\n")
    elif change == "model":
        extra = ["--answerer-model", "different-model"]
    else:
        name = (
            "answer_quality_paired_eval.py"
            if change == "evaluator"
            else "answer_quality_artifacts.py"
        )
        with (script_dir / name).open("a") as stream:
            stream.write("\n# changed evaluator source\n")
    result = _run(cli, *extra)
    assert result.returncode == 2
    assert "incompatible_run_identity" in result.stderr
    assert "PRIVATE_" not in result.stdout + result.stderr
    assert _calls(log) == 4


def test_cli_recovers_torn_tail_and_reexecutes_only_uncommitted_arm(cli):
    assert _run(cli).returncode == 0
    _, _, directory, log, *_ = cli
    path = directory / "results.jsonl"
    prefix = path.read_bytes().splitlines(keepends=True)[0]
    path.write_bytes(prefix + b'{"candidate":"\xd0')
    result = _run(cli)
    assert result.returncode == 0, result.stderr
    assert _calls(log) == 6
    assert len(path.read_text().splitlines()) == 2
    assert json.loads((directory / "aggregate.json").read_text())["pair_counts"]["resolved"] == 1


def test_cli_single_writer_lock_rejects_second_run_without_provider_call(cli, tmp_path):
    command, env, _, log, *_ = cli
    block = tmp_path / "block"
    block.touch()
    first = subprocess.Popen(
        command,
        env={**env, "ANSWER_EVAL_TEST_BLOCK": str(block)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while _calls(log) == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert _calls(log) == 1
        second = _run(cli)
        assert second.returncode == 2
        assert "run_directory_busy" in second.stderr
        assert _calls(log) == 1
    finally:
        block.unlink(missing_ok=True)
        stdout, stderr = first.communicate(timeout=20)
    assert first.returncode == 0, stderr
    assert "PRIVATE_" not in stdout + stderr


@pytest.mark.parametrize("extra", [("--workers", "0"), ("--limit", "-1")])
def test_cli_invalid_selection_fails_before_runner(cli, extra):
    result = _run(cli, *extra)
    assert result.returncode == 2
    assert _calls(cli[3]) == 0


def test_cli_unresolved_judgment_is_terminal_and_not_a_memory_win(cli):
    _, _, directory, log, _, script_dir = cli
    source = script_dir / "answer_quality_paired_eval.py"
    source.write_text(source.read_text().replace("return _verdict(raw),", 'return "unparsed",'))
    result = _run(cli)
    assert result.returncode == 2, result.stderr
    aggregate = json.loads((directory / "aggregate.json").read_text())
    assert aggregate["status"] == "complete_with_unresolved"
    assert aggregate["pair_counts"]["resolved"] == 0
    assert sum(aggregate["paired"].values()) == 0
    calls = _calls(log)
    resumed = _run(cli)
    assert resumed.returncode == 2
    assert _calls(log) == calls
