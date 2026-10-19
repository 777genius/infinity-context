"""Build a private answer-eval pack from frozen diagnostic pickles.

For every frozen case: pack the candidate items with the production packer, keep
the rendered context verbatim, and recover the reference answer by joining the
frozen question text against the staged official LongMemEval file
(longmemeval_s_cleaned.json, sha256 d6f21ea9... as pinned in docs).

Stdout carries only counts; questions, gold answers and contexts go to the
output pack file, which is private data and must stay on the measurement host
(mode 0600).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import pickle
import sys
import unicodedata


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text)).strip().lower()


def _as_text(answer: object) -> str:
    if isinstance(answer, (list, tuple)):
        return "; ".join(str(part) for part in answer)
    return str(answer)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs-root", required=True, type=pathlib.Path)
    parser.add_argument("--set-dir", required=True)
    parser.add_argument("--dataset", required=True, type=pathlib.Path)
    parser.add_argument("--coverage", required=True, type=pathlib.Path)
    parser.add_argument("--coverage-key", required=True)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    args = parser.parse_args()

    from infinity_context_core.application.context_packer import ContextPacker

    inputs = args.inputs_root / args.set_dir / "frozen-private"
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    if isinstance(dataset, dict):
        dataset = dataset.get("data", [])
    gold_by_question: dict[str, str] = {}
    for row in dataset:
        gold_by_question.setdefault(_norm(row.get("question", "")), _as_text(row.get("answer", "")))
    print("dataset_rows", len(dataset), "distinct_questions", len(gold_by_question))

    coverage = json.loads(args.coverage.read_text(encoding="utf-8"))[args.coverage_key]["per"]

    matched = 0
    rows = []
    for path in sorted(inputs.rglob("*.pickle")):
        case_hash = hashlib.sha256(path.stem.encode()).hexdigest()[:12]
        data = pickle.loads(path.read_bytes())
        query = data["kwargs"]["query"]
        gold = gold_by_question.get(_norm(query))
        if gold is None:
            continue
        matched += 1
        result = ContextPacker().pack(**data["kwargs"])
        ok, hit = coverage.get(case_hash, (None, None))
        rows.append(
            {
                "cid": case_hash,
                "qtype": path.parent.name,
                "question": query,
                "gold": gold,
                "context": result.bundle.rendered_text,
                "item_count": len(result.bundle.items),
                "ctx_chars": len(result.bundle.rendered_text),
                "gold_sources": len(data["targets"]),
                "sources_covered": hit,
                "coverage_complete": bool(ok),
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    by_type: dict[str, int] = {}
    for row in rows:
        by_type[row["qtype"]] = by_type.get(row["qtype"], 0) + 1
    print(
        "cases",
        len(rows),
        "gold_matched",
        matched,
        "gold_missing",
        len(list(inputs.rglob("*.pickle"))) - matched,
    )
    print("by_type", by_type)
    print(
        "coverage_complete_in_pack",
        sum(1 for row in rows if row["coverage_complete"]),
        "median_ctx_chars",
        sorted(row["ctx_chars"] for row in rows)[len(rows) // 2] if rows else 0,
        "empty_context_cases",
        sum(1 for row in rows if not row["context"]),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
