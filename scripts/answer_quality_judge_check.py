"""Judge-validity check: agreement between two judges on the same candidates.

Re-runs the answerer on a sampled subset (with-context arm), then grades each
candidate with two independent judge models (default: mimo-v2.6-flash and
mimo-v2.6-pro; both overridable via --judge-a/--judge-b/--judge-runner when a
provider is unavailable). Reports only the agreement matrix and rates;
candidate text never leaves the measurement host.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from answer_quality_paired_eval import (  # noqa: E402
    ANSWERER_MODEL,
    ANSWERER_TEMPLATE,
    JUDGE_TEMPLATE,
    _call,
    _verdict,
)

FLASH = "mimo-v2.6-flash"
PRO = "mimo-v2.6-pro"


def grade(model: str, question: str, gold: str, candidate: str, runner: str) -> str:
    raw, _failures, _ms = _call(
        model,
        JUDGE_TEMPLATE.format(question=question, gold=gold, candidate=candidate[:900]),
        runner=runner,
    )
    return _verdict(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True, type=pathlib.Path)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--answerer-model", default=ANSWERER_MODEL)
    parser.add_argument("--answerer-runner", choices=("qodercli", "codex"), default="qodercli")
    parser.add_argument("--judge-a", default=FLASH)
    parser.add_argument("--judge-b", default=PRO)
    parser.add_argument("--judge-a-runner", choices=("qodercli", "codex"), default="qodercli")
    parser.add_argument("--judge-b-runner", choices=("qodercli", "codex"), default=None)
    args = parser.parse_args()
    judge_b_runner = args.judge_b_runner or args.judge_a_runner
    answerer_effort = (
        "xhigh"
        if args.answerer_runner == "qodercli" and args.answerer_model == ANSWERER_MODEL
        else None
    )

    rows = [json.loads(line) for line in args.pack.read_text(encoding="utf-8").splitlines()]
    rows.sort(key=lambda row: row["cid"])
    step = max(1, len(rows) // args.sample)
    subset = rows[::step][: args.sample]

    def run_one(row: dict) -> dict:
        candidate, _failures, _ms = _call(
            args.answerer_model,
            ANSWERER_TEMPLATE.format(context=row["context"], question=row["question"]),
            reasoning_effort=answerer_effort,
            runner=args.answerer_runner,
        )
        return {
            "cid": row["cid"],
            "qtype": row["qtype"],
            "coverage_complete": row["coverage_complete"],
            "a": grade(args.judge_a, row["question"], row["gold"], candidate, args.judge_a_runner),
            "b": grade(args.judge_b, row["question"], row["gold"], candidate, judge_b_runner),
            "candidate_chars": len(candidate),
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(run_one, subset))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )

    valid = ("correct", "missing", "incorrect")
    resolved = [record for record in records if record["a"] in valid and record["b"] in valid]
    agree = sum(1 for record in resolved if record["a"] == record["b"])
    matrix: dict[str, int] = {}
    for record in records:
        key = f"a={record['a']}|b={record['b']}"
        matrix[key] = matrix.get(key, 0) + 1
    print(
        json.dumps(
            {
                "cases": len(records),
                "answerer": args.answerer_model,
                "answerer_runner": args.answerer_runner,
                "judge_a": args.judge_a,
                "judge_a_runner": args.judge_a_runner,
                "judge_b": args.judge_b,
                "judge_b_runner": judge_b_runner,
                "resolved": len(resolved),
                "unresolved": len(records) - len(resolved),
                "agreement": agree,
                "both_correct": sum(
                    1 for record in resolved if record["a"] == "correct" == record["b"]
                ),
                "a_correct": sum(1 for record in resolved if record["a"] == "correct"),
                "b_correct": sum(1 for record in resolved if record["b"] == "correct"),
                "matrix": matrix,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
