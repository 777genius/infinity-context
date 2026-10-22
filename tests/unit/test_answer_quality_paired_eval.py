"""Exercise the real resumable CLI with a local deterministic runner, no provider calls."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import answer_quality_paired_eval as paired_eval
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


@pytest.mark.parametrize(
    ("failure_at", "error_type"),
    [
        ("result", RuntimeError),
        ("append", OSError),
        ("append", KeyboardInterrupt),
        ("submit", RuntimeError),
    ],
)
def test_failure_cancels_queued_arms_and_joins_running_arms(
    tmp_path, monkeypatch, failure_at, error_type
):
    failure = error_type("controlled evaluation failure")
    rows = [
        {
            "cid": f"case-{index}",
            "question": f"question-{index}",
            "gold": "answer",
            "context": f"context-{index}",
            "qtype": "test",
            "coverage_complete": True,
        }
        for index in range(4)
    ]
    prompts = {
        paired_eval.ANSWERER_TEMPLATE.format(
            context=row["context"] if arm == "with" else paired_eval.EMPTY_CONTEXT,
            question=row["question"],
        ): index
        for index, (row, arm) in enumerate(
            (row, arm) for row in rows for arm in ("with", "without")
        )
    }
    first_queued = 2 if failure_at == "submit" else 3
    submitted_count = 6 if failure_at == "submit" else 8
    running_started = threading.Event()
    release_running = threading.Event()
    queued_cancelled = threading.Event()
    evaluator_done = threading.Event()
    state_lock = threading.Lock()
    started, completed, cancelled, submitted, outcomes = [], [], [], [], []
    real_executor = concurrent.futures.ThreadPoolExecutor
    real_as_completed = concurrent.futures.as_completed

    def call(_model, prompt, **_kwargs):
        index = prompts[prompt]
        with state_lock:
            started.append(index)
        if index == 0 and failure_at != "submit":
            if failure_at == "result":
                raise failure
        else:
            with state_lock:
                if len(started) == first_queued:
                    running_started.set()
            assert release_running.wait(10), "running arms were not released"
            with state_lock:
                completed.append(index)
        return "answer", 0, 1

    def capture_cancellation(index, future):
        if index >= first_queued and future.cancelled():
            with state_lock:
                cancelled.append(index)
                if len(cancelled) == submitted_count - first_queued:
                    queued_cancelled.set()

    class ObservedExecutor(real_executor):
        def submit(self, fn, /, *args, **kwargs):
            if failure_at == "submit" and len(submitted) == submitted_count:
                assert running_started.wait(5), "worker slots were not occupied"
                raise failure
            index = len(submitted)
            future = super().submit(fn, *args, **kwargs)
            submitted.append(future)
            future.add_done_callback(lambda done: capture_cancellation(index, done))
            return future

    def as_completed(futures):
        # Hold result consumption until both workers block and only the trigger arm is done.
        assert running_started.wait(5), "worker slots were not occupied"
        assert [index for index, future in enumerate(futures) if future.done()] == [0]
        return real_as_completed(futures)

    def append_failure(*_args):
        raise failure

    def evaluate():
        try:
            paired_eval._run_evaluation(
                SimpleNamespace(
                    out_dir=tmp_path,
                    workers=2,
                    answerer_model="local",
                    answerer_runner="qodercli",
                    judge_model="local",
                    judge_runner="qodercli",
                ),
                rows,
                {"run_sha256": "a" * 64},
                None,
            )
        except BaseException as error:
            with state_lock:
                outcomes.append((error, list(completed)))
        finally:
            evaluator_done.set()

    monkeypatch.setattr(paired_eval, "_call", call)
    monkeypatch.setattr(
        paired_eval,
        "_judge",
        lambda *_args, **_kwargs: ("correct", hashlib.sha256(b"answer").hexdigest()[:12], 0, 1),
    )
    monkeypatch.setattr(paired_eval.concurrent.futures, "ThreadPoolExecutor", ObservedExecutor)
    monkeypatch.setattr(paired_eval.concurrent.futures, "as_completed", as_completed)
    if failure_at == "append":
        monkeypatch.setattr(paired_eval, "append_result", append_failure)
    evaluator = threading.Thread(target=evaluate)
    evaluator.start()
    try:
        assert queued_cancelled.wait(5), "queued arms were not cancelled"
        assert not evaluator_done.wait(0.05), "evaluator returned before running arms finished"
        assert not completed
    finally:
        release_running.set()
        evaluator.join(timeout=10)
    assert not evaluator.is_alive()
    assert len(outcomes) == 1
    assert outcomes[0][0] is failure
    assert set(outcomes[0][1]) == set(range(first_queued - 2, first_queued))
    assert set(started) == set(range(first_queued))
    assert all(future.cancelled() for future in submitted[first_queued:])
