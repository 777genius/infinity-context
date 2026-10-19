"""Judge-validity check: agreement between two judges on the same candidates.

Re-runs the answerer on a sampled subset (with-context arm), then grades each
candidate with mimo-v2.6-flash and mimo-v2.6-pro independently. Reports only
the agreement matrix and rates; candidate text never leaves the measurement
host.
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


def grade(model: str, question: str, gold: str, candidate: str) -> str:
    raw, _failures, _ms = _call(
        model, JUDGE_TEMPLATE.format(question=question, gold=gold, candidate=candidate[:900])
    )
    return _verdict(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True, type=pathlib.Path)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.pack.read_text(encoding="utf-8").splitlines()]
    rows.sort(key=lambda row: row["cid"])
    step = max(1, len(rows) // args.sample)
    subset = rows[::step][: args.sample]

    def run_one(row: dict) -> dict:
        candidate, _failures, _ms = _call(
            ANSWERER_MODEL,
            ANSWERER_TEMPLATE.format(context=row["context"], question=row["question"]),
        )
        return {
            "cid": row["cid"],
            "qtype": row["qtype"],
            "coverage_complete": row["coverage_complete"],
            "flash": grade(FLASH, row["question"], row["gold"], candidate),
            "pro": grade(PRO, row["question"], row["gold"], candidate),
            "candidate_chars": len(candidate),
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(run_one, subset))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )

    valid = ("correct", "missing", "incorrect")
    resolved = [record for record in records if record["flash"] in valid and record["pro"] in valid]
    agree = sum(1 for record in resolved if record["flash"] == record["pro"])
    matrix: dict[str, int] = {}
    for record in records:
        key = f"flash={record['flash']}|pro={record['pro']}"
        matrix[key] = matrix.get(key, 0) + 1
    print(
        json.dumps(
            {
                "cases": len(records),
                "resolved": len(resolved),
                "unresolved": len(records) - len(resolved),
                "agreement": agree,
                "both_correct": sum(
                    1 for record in resolved if record["flash"] == "correct" == record["pro"]
                ),
                "flash_correct": sum(1 for record in resolved if record["flash"] == "correct"),
                "pro_correct": sum(1 for record in resolved if record["pro"] == "correct"),
                "matrix": matrix,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
