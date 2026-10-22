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

# Support both direct script execution and the existing scripts' helper imports.
if __package__:
    from .answer_quality_artifacts import (
        ArtifactError,
        append_result,
        atomic_json,
        bind_manifest,
        load_pack,
        private_run_directory,
        public_counts,
        read_results,
        run_manifest,
        strict_json,
        validate_record,
    )
else:
    from answer_quality_artifacts import (
        ArtifactError,
        append_result,
        atomic_json,
        bind_manifest,
        load_pack,
        private_run_directory,
        public_counts,
        read_results,
        run_manifest,
        strict_json,
        validate_record,
    )

# Service-layer messages that qodercli may print on stdout; they must never be
# graded as answers (they were observed as a 126-char identical blob under
# provider rate limiting). Anchored to service phrasings so ordinary answer
# prose containing words like "quota" or "exceeded" is not rejected.
_ERROR_PATTERN = re.compile(
    r"(?i)(too many requests|rate ?limit(?:ed|ing)?|\b429\b|"
    r"quota (?:exceeded|exhausted|limit)|usage limit|come back tomorrow|"
    r"internal server error|service unavailable|temporarily unavailable|"
    r"authentication (?:error|failed)|api error|exceeded retry limit|"
    r"try again later|queuing failed|model is busy)"
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
    fd, name = tempfile.mkstemp(prefix="eval-last-", suffix=".txt")
    os.close(fd)
    last_message = pathlib.Path(name)
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
    payload = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", payload, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        payload = fenced.group(1)
    if (
        payload.startswith(("{", "[", '"'))
        or fenced
        or re.search(r"[\"']verdict[\"']\s*:", raw, flags=re.IGNORECASE)
    ):
        try:
            parsed = strict_json(payload)
        except (ValueError, UnicodeError):
            return "unparsed"
        value = parsed.get("verdict") if isinstance(parsed, dict) else None
        return value if value in ("correct", "incorrect", "missing") else "unparsed"
    # Word boundaries matter: "incorrect" contains the substring "correct".
    labels = set(re.findall(r"\b(incorrect|missing|correct)\b", raw.lower()))
    return labels.pop() if len(labels) == 1 else "unparsed"


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
    try:
        if args.workers < 1:
            raise ArtifactError("workers_must_be_positive")
        rows = load_pack(args.pack, limit=args.limit)
        answerer_effort = (
            "xhigh"
            if args.answerer_runner == "qodercli" and args.answerer_model == ANSWERER_MODEL
            else None
        )
        manifest = run_manifest(
            rows,
            {
                "answerer": args.answerer_model,
                "answerer_runner": args.answerer_runner,
                "answerer_effort": answerer_effort,
                "judge": args.judge_model,
                "judge_runner": args.judge_runner,
                "answerer_template": ANSWERER_TEMPLATE,
                "judge_template": JUDGE_TEMPLATE,
                "empty_context": EMPTY_CONTEXT,
            },
            pathlib.Path(__file__),
        )
        with private_run_directory(args.out_dir):
            return _run_evaluation(args, rows, manifest, answerer_effort)
    except (ArtifactError, OSError, ValueError) as error:
        # Paths, raw JSON and provider output may contain private text.
        code = (
            str(error) if isinstance(error, ArtifactError) else "evaluation_preflight_or_io_failed"
        )
        print(f"evaluation_error: {code}", file=sys.stderr)
        return 2


def _run_evaluation(args, rows: list[dict], manifest: dict, answerer_effort: str | None) -> int:
    bind_manifest(args.out_dir, manifest)
    run_sha256 = manifest["run_sha256"]
    results_path = args.out_dir / "results.jsonl"
    records = read_results(results_path, rows, run_sha256)
    done = {(record["cid"], record["arm"]) for record in records}
    pending = [
        (row, arm) for row in rows for arm in ("with", "without") if (row["cid"], arm) not in done
    ]
    print(f"cases={len(rows)} pending_arms={len(pending)} already_done={len(done)}", flush=True)
    by_cid = {row["cid"]: row for row in rows}

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
        return validate_record(
            {
                "run_sha256": run_sha256,
                "cid": row["cid"],
                "qtype": row["qtype"],
                "arm": arm,
                "coverage_complete": row["coverage_complete"],
                "verdict": verdict,
                "candidate": candidate,
                "candidate_sha": candidate_hash,
                "candidate_chars": len(candidate),
                "call_failures": answer_failures + judge_failures,
                "answer_ms": answer_ms,
                "judge_ms": judge_ms,
            },
            by_cid,
            run_sha256,
        )

    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one, item) for item in pending]
        for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            record = future.result()
            append_result(results_path, record)
            records.append(record)
            if index % 10 == 0 or index == len(pending):
                print(
                    f"progress {index}/{len(pending)} elapsed={time.time() - started:.0f}s",
                    flush=True,
                )

    aggregate = public_counts(rows, records)
    aggregate.update(
        {
            "schema_version": 2,
            "run_sha256": run_sha256,
            "answerer": args.answerer_model,
            "answerer_runner": args.answerer_runner,
            "judge": args.judge_model,
            "judge_runner": args.judge_runner,
            "call_failures_total": sum(record["call_failures"] for record in records),
            "answer_ms_median": {
                arm: _median([record["answer_ms"] for record in records if record["arm"] == arm])
                for arm in ("with", "without")
            },
            "judge_ms_median": _median([record["judge_ms"] for record in records]),
            "unresolved_verdicts": sum(
                record["verdict"] in ("unparsed", "call_failed") for record in records
            ),
        }
    )
    long_dupes = collections.Counter(
        record["candidate_sha"] for record in records if record["candidate_chars"] > 20
    )
    aggregate["largest_repeated_long_candidate"] = max(long_dupes.values(), default=0)
    atomic_json(args.out_dir / "aggregate.json", aggregate)
    print(json.dumps(aggregate, indent=2))
    return 0 if aggregate["status"] == "complete" else 2


if __name__ == "__main__":
    sys.exit(main())
