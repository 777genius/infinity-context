"""Probe whether the rendered context actually contains the evidence to answer.

For each selected case an independent probe model sees the question, the gold
answer and the rendered context, and classifies evidence as:
- verbatim     the reference answer (or an exact restatement) is present
- derivable    all needed facts are present, the answer must be computed
- insufficient at least one needed fact is missing from the context

Runs on the measurement host; stdout carries only counters and opaque case
hashes. The answerer's candidate is never shown to the probe — this measures
the context, not the answer.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from answer_quality_paired_eval import _call  # noqa: E402

PROBE_TEMPLATE = (
    "You are auditing whether a stored-memory context contains enough evidence "
    "to answer a question. You do NOT answer the question; you classify the "
    "evidence only.\n"
    'Classify as "verbatim" when the reference answer (or an exact restatement '
    'of it) appears in the context; as "derivable" when the context contains '
    "every fact needed to compute the reference answer but not the answer "
    'itself; as "insufficient" when at least one fact needed to answer is '
    "missing from the context.\n"
    "Reply with exactly one JSON object on a single line and nothing else, "
    'for example {{"evidence": "derivable"}}.\n'
    "\n"
    "QUESTION: {question}\n"
    "REFERENCE ANSWER: {gold}\n"
    "MEMORY CONTEXT:\n{context}"
)

LABELS = ("verbatim", "derivable", "insufficient")


def _label(raw: str) -> str:
    candidates = [raw.strip()]
    candidates.extend(line.strip() for line in raw.splitlines())
    for candidate in candidates:
        if not candidate.startswith("{"):
            continue
        try:
            value = json.loads(candidate).get("evidence")
        except (json.JSONDecodeError, AttributeError):
            continue
        if value in LABELS:
            return value
    lowered = raw.lower()
    for label in LABELS:
        if label in lowered and f"not {label}" not in lowered:
            return label
    return "unparsed"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True, type=pathlib.Path)
    parser.add_argument("--results", required=True, type=pathlib.Path)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--model", default="gpt-5.6-terra")
    parser.add_argument("--runner", choices=("qodercli", "codex"), default="codex")
    parser.add_argument("--failures-only", action="store_true")
    parser.add_argument("--control", type=int, default=15)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()

    pack = {}
    for line in args.pack.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        pack[row["cid"]] = row

    records: dict[tuple[str, str], dict] = {}
    for line in args.results.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec["arm"] != "with" or rec["cid"] not in pack:
            continue
        records[(rec["cid"], rec["verdict"])] = rec

    failures = sorted(
        (rec for rec in records.values() if rec["verdict"] != "correct"),
        key=lambda rec: rec["cid"],
    )
    controls = sorted(
        (rec for rec in records.values() if rec["verdict"] == "correct"),
        key=lambda rec: rec["cid"],
    )
    if args.failures_only:
        controls = []
    else:
        step = max(1, len(controls) // args.control)
        controls = controls[::step][: args.control]
    todo = failures + controls

    def run_one(rec: dict) -> dict:
        row = pack[rec["cid"]]
        raw, _failures, _ms = _call(
            args.model,
            PROBE_TEMPLATE.format(
                question=row["question"], gold=row["gold"], context=row["context"]
            ),
            runner=args.runner,
        )
        return {
            "cid": rec["cid"],
            "group": "failure" if rec["verdict"] != "correct" else "control",
            "verdict": rec["verdict"],
            "qtype": rec["qtype"],
            "evidence": _label(raw),
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run_one, todo))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "\n".join(json.dumps(record) for record in results) + "\n", encoding="utf-8"
    )

    summary: dict[str, dict[str, int]] = {}
    for record in results:
        summary.setdefault(record["group"], {}).setdefault(record["evidence"], 0)
        summary[record["group"]][record["evidence"]] += 1
    by_qtype: dict[str, dict[str, int]] = {}
    for record in results:
        if record["group"] != "failure":
            continue
        by_qtype.setdefault(record["qtype"], {}).setdefault(record["evidence"], 0)
        by_qtype[record["qtype"]][record["evidence"]] += 1
    print(
        json.dumps(
            {
                "model": args.model,
                "runner": args.runner,
                "cases": len(results),
                "evidence_by_group": summary,
                "failures_by_qtype": by_qtype,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
