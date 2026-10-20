"""Paired answer-quality eval: same answerer model, WITH vs WITHOUT context.

Answerer  = qodercli -m <--answerer-model, default Qwen3.8-Flash> (no tools);
            --reasoning-effort xhigh is passed only for the default answerer;
            --answerer-runner codex runs the same prompt through `codex exec`
Judge     = qodercli -m mimo-v2.6-flash, blind to the arm, verdicts
            correct | missing | incorrect (overridable via --judge-model /
            --judge-runner when the default judge provider is unavailable)

The design isolates the contribution of the packed memory context: one model,
one question, two arms (real rendered context vs empty context), one blind
judge against the reference answer. Inputs and per-case outputs are private
data and stay on the measurement host; only aggregate.json (counts and rates)
is meant to be published.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import time

ANSWERER_MODEL = "Qwen3.8-Flash"
JUDGE_MODEL = "mimo-v2.6-flash"
EMPTY_CONTEXT = "(empty: no memory retrieved)"

ANSWERER_TEMPLATE = (
    "You are answering a question about one user's personal history using retrieved memory "
    "context.\n"
    "Rules:\n"
    "- Use only the context below. Do not guess.\n"
    "- Answer in one short line (a phrase or one sentence).\n"
    "- If the context does not contain the answer, reply exactly: I don't know\n"
    "\n"
    "CONTEXT:\n"
    "<<<\n"
    "{context}\n"
    ">>>\n"
    "\n"
    "QUESTION: {question}\n"
    "\n"
    "ANSWER:"
)

JUDGE_TEMPLATE = (
    "You grade one candidate answer against a reference answer. Judge factual equivalence only.\n"
    "Verdicts:\n"
    "- correct: the candidate states the same fact as the reference. Paraphrase, extra detail "
    "and different formatting are allowed; contradicting the reference is not. If the reference "
    "itself says the question cannot be answered, a candidate that declines to invent an answer "
    "is correct.\n"
    "- missing: the candidate refuses or claims it does not know, while the reference gives a "
    "real answer.\n"
    "- incorrect: anything else.\n"
    "Reply with exactly one JSON object on a single line and nothing else, for example "
    '{{"verdict": "correct"}}\n'
    "\n"
    "QUESTION: {question}\n"
    "REFERENCE ANSWER: {gold}\n"
    "CANDIDATE ANSWER: {candidate}"
)

_write_lock = threading.Lock()

# Service-layer messages that qodercli may print on stdout; they must never be
# graded as answers (they were observed as a 126-char identical blob under
# provider rate limiting).
_ERROR_PATTERN = re.compile(
    r"(?i)(\berror\b|\brate ?limit|\b429\b|too many requests|quota|usage limit|"
    r"temporarily unavailable|internal server error|api error|authentication|"
    r"exceeded|try again)"
)


def _qodercli_once(model: str, prompt: str, reasoning_effort: str | None) -> str | None:
    proc = subprocess.run(
        [
            "qodercli",
            "-p",
            prompt,
            "-m",
            model,
            "--tools",
            "",
            "--no-session-persistence",
            *(["--reasoning-effort", reasoning_effort] if reasoning_effort else []),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        env=os.environ,
    )
    text = (proc.stdout or "").strip()
    if proc.returncode != 0 and not text:
        return None
    return text


def _codex_once(model: str, prompt: str) -> str | None:
    last_message = pathlib.Path(tempfile.mkstemp(prefix="eval-last-", suffix=".txt")[1])
    try:
        proc = subprocess.run(
            [
                "codex",
                "exec",
                "--skip-git-repo-check",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--color",
                "never",
                "-m",
                model,
                "-o",
                str(last_message),
                "-",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,
            env=os.environ,
        )
        if proc.returncode != 0:
            return None
        text = last_message.read_text(encoding="utf-8").strip()
        return text or None
    finally:
        last_message.unlink(missing_ok=True)


def _call(
    model: str,
    prompt: str,
    attempts: int | None = None,
    reasoning_effort: str | None = None,
    runner: str = "qodercli",
) -> tuple[str, int, int]:
    # codex bursts hit HTTP 429 quickly and the cooldown window is longer than
    # the qodercli one, so give it more, slower retries.
    if attempts is None:
        attempts = 5 if runner == "codex" else 3
    failures = 0
    started = time.time()
    for attempt in range(attempts):
        try:
            if runner == "codex":
                text = _codex_once(model, prompt)
            else:
                text = _qodercli_once(model, prompt, reasoning_effort)
        except subprocess.TimeoutExpired:
            failures += 1
            time.sleep(5 * (attempt + 1))
            continue
        if text:
            text = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", text).strip()
            if text and not _ERROR_PATTERN.search(text):
                return text, failures, int((time.time() - started) * 1000)
        failures += 1
        time.sleep((10 if runner == "codex" else 3) * (attempt + 1))
    return "", failures, int((time.time() - started) * 1000)


def _verdict(raw: str) -> str:
    match = re.search(r'\{"verdict"\s*:\s*"([a-z_]+)"', raw)
    if match:
        return match.group(1)
    # Word boundaries matter: "incorrect" contains the substring "correct".
    fallback = re.search(r"\b(incorrect|missing|correct)\b", raw.lower())
    return fallback.group(1) if fallback else "unparsed"


def _judge(
    question: str,
    gold: str,
    candidate: str,
    judge_model: str = JUDGE_MODEL,
    judge_runner: str = "qodercli",
) -> tuple[str, str, int, int]:
    if not candidate.strip():
        return "call_failed", "", 1, 0
    raw, failures, elapsed = _call(
        judge_model,
        JUDGE_TEMPLATE.format(question=question, gold=gold, candidate=candidate[:900]),
        runner=judge_runner,
    )
    return _verdict(raw), hashlib.sha256(candidate.encode()).hexdigest()[:12], failures, elapsed


def _median(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True, type=pathlib.Path)
    parser.add_argument("--out-dir", required=True, type=pathlib.Path)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--answerer-model", default=ANSWERER_MODEL)
    parser.add_argument("--answerer-runner", choices=("qodercli", "codex"), default="qodercli")
    parser.add_argument("--judge-model", default=JUDGE_MODEL)
    parser.add_argument("--judge-runner", choices=("qodercli", "codex"), default="qodercli")
    args = parser.parse_args()
    answerer_effort = (
        "xhigh"
        if args.answerer_runner == "qodercli" and args.answerer_model == ANSWERER_MODEL
        else None
    )

    rows = [json.loads(line) for line in args.pack.read_text(encoding="utf-8").splitlines()]
    rows.sort(key=lambda row: row["cid"])
    if args.limit:
        rows = rows[: args.limit]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    results_path = args.out_dir / "results.jsonl"

    done = set()
    if results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # torn trailing line from an interrupted run
            done.add((record["cid"], record["arm"]))
    pending = []
    for row in rows:
        for arm in ("with", "without"):
            if (row["cid"], arm) not in done:
                pending.append((row, arm))
    print(f"cases={len(rows)} pending_arms={len(pending)} already_done={len(done)}", flush=True)

    def run_one(item: tuple[dict, str]) -> dict:
        row, arm = item
        context = row["context"] if arm == "with" else EMPTY_CONTEXT
        candidate, answer_failures, answer_ms = _call(
            args.answerer_model,
            ANSWERER_TEMPLATE.format(context=context, question=row["question"]),
            reasoning_effort=answerer_effort,
            runner=args.answerer_runner,
        )
        verdict, candidate_hash, judge_failures, judge_ms = _judge(
            row["question"],
            row["gold"],
            candidate,
            judge_model=args.judge_model,
            judge_runner=args.judge_runner,
        )
        return {
            "cid": row["cid"],
            "qtype": row["qtype"],
            "arm": arm,
            "coverage_complete": row["coverage_complete"],
            "verdict": verdict,
            "candidate_sha": candidate_hash,
            "candidate_chars": len(candidate),
            "call_failures": answer_failures + judge_failures,
            "answer_ms": answer_ms,
            "judge_ms": judge_ms,
        }

    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for index, record in enumerate(pool.map(run_one, pending), start=1):
            with _write_lock, results_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            if index % 10 == 0 or index == len(pending):
                print(
                    f"progress {index}/{len(pending)} elapsed={time.time() - started:.0f}s",
                    flush=True,
                )

    wanted = {row["cid"] for row in rows}
    records = []
    for line in results_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue  # torn trailing line from an interrupted run
        if record["cid"] in wanted:
            records.append(record)
    aggregate: dict[str, object] = {
        "cases": len(rows),
        "answerer": args.answerer_model,
        "answerer_runner": args.answerer_runner,
        "judge": args.judge_model,
        "judge_runner": args.judge_runner,
    }

    def _rate(arm: str) -> dict[str, int]:
        counts = {"correct": 0, "incorrect": 0, "missing": 0, "unparsed": 0, "call_failed": 0}
        for record in records:
            if record["arm"] == arm:
                counts[record["verdict"]] = counts.get(record["verdict"], 0) + 1
        return counts

    for arm in ("with", "without"):
        aggregate[f"{arm}_counts"] = _rate(arm)
    by_cid: dict[str, dict[str, str]] = {}
    for record in records:
        by_cid.setdefault(record["cid"], {})[record["arm"]] = record["verdict"]
    aggregate["paired"] = {
        "memory_helped": sum(
            1
            for pair in by_cid.values()
            if pair.get("with") == "correct" and pair.get("without") != "correct"
        ),
        "memory_hurt": sum(
            1
            for pair in by_cid.values()
            if pair.get("without") == "correct" and pair.get("with") != "correct"
        ),
        "both_correct": sum(
            1
            for pair in by_cid.values()
            if pair.get("with") == "correct" and pair.get("without") == "correct"
        ),
        "neither": sum(
            1
            for pair in by_cid.values()
            if pair.get("with") != "correct" and pair.get("without") != "correct"
        ),
    }
    aggregate["by_qtype"] = {
        qtype: {
            "with_correct": sum(
                1
                for record in records
                if record["arm"] == "with"
                and record["verdict"] == "correct"
                and record["qtype"] == qtype
            ),
            "without_correct": sum(
                1
                for record in records
                if record["arm"] == "without"
                and record["verdict"] == "correct"
                and record["qtype"] == qtype
            ),
            "cases": sum(1 for row in rows if row["qtype"] == qtype),
        }
        for qtype in sorted({row["qtype"] for row in rows})
    }
    aggregate["by_coverage"] = {
        str(flag): {
            "with_correct": sum(
                1
                for record in records
                if record["arm"] == "with"
                and record["verdict"] == "correct"
                and record["coverage_complete"] is flag
            ),
            "cases": sum(1 for row in rows if row["coverage_complete"] is flag),
        }
        for flag in (True, False)
    }
    aggregate["call_failures_total"] = sum(record["call_failures"] for record in records)
    long_dupes = collections.Counter(
        record["candidate_sha"] for record in records if record["candidate_chars"] > 20
    )
    aggregate["largest_repeated_long_candidate"] = max(long_dupes.values(), default=0)
    aggregate["answer_ms_median"] = {
        arm: _median([record["answer_ms"] for record in records if record["arm"] == arm])
        for arm in ("with", "without")
    }
    aggregate["judge_ms_median"] = _median([record["judge_ms"] for record in records])
    aggregate["unresolved_verdicts"] = sum(
        1 for record in records if record["verdict"] in ("unparsed", "call_failed")
    )
    (args.out_dir / "aggregate.json").write_text(json.dumps(aggregate, indent=2), encoding="utf-8")
    print(json.dumps(aggregate, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
