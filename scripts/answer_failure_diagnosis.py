"""Classify with-arm answer failures by whether the gold fact is in context.

Runs entirely on the measurement host: reads the private pack plus the frozen
results, and prints ONLY counters and opaque case hashes — no question, gold
answer or context text ever leaves stdout.

Buckets every with-arm record whose verdict is not `correct`:
- gold_in_context       the normalized gold answer appears verbatim in the
                        rendered context (missed evidence / presentation)
- gold_tokens_in_context all gold content tokens appear somewhere in the
                        context, but not as a contiguous span (scattered or
                        rephrased evidence)
- gold_absent           the gold fact is not in the rendered context at all,
                        despite coverage_complete (source present, fact not
                        rendered)
- short_gold            gold answer is too short (< 2 content tokens) for the
                        containment tests to mean anything
Correct with-arm records are bucketed the same way as a control group.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import unicodedata


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text)).lower()
    text = re.sub(r"[^0-9a-zа-яё]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    return [token for token in _norm(text).split() if len(token) > 1]


def classify(gold: str, context: str) -> str:
    gold_tokens = _tokens(gold)
    if len(gold_tokens) < 2:
        return "short_gold"
    norm_gold = _norm(gold)
    norm_context = _norm(context)
    if norm_gold and norm_gold in norm_context:
        return "gold_in_context"
    context_tokens = set(_tokens(context))
    if all(token in context_tokens for token in dict.fromkeys(gold_tokens)):
        return "gold_tokens_in_context"
    return "gold_absent"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True, type=pathlib.Path)
    parser.add_argument("--results", required=True, type=pathlib.Path)
    args = parser.parse_args()

    pack = {}
    for line in args.pack.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        pack[row["cid"]] = row

    counts: dict[str, collections.Counter] = {"correct": collections.Counter()}
    per_verdict: dict[str, collections.Counter] = {}
    per_qtype: dict[str, collections.Counter] = {}
    failed_cids: dict[str, list[str]] = {}
    matched = 0
    with_correct = 0

    for line in args.results.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec["arm"] != "with" or rec["cid"] not in pack:
            continue
        bucket = classify(pack[rec["cid"]]["gold"], pack[rec["cid"]]["context"])
        verdict = rec["verdict"]
        if verdict == "correct":
            with_correct += 1
            counts["correct"][bucket] += 1
            continue
        matched += 1
        counts.setdefault("failed", collections.Counter())[bucket] += 1
        per_verdict.setdefault(verdict, collections.Counter())[bucket] += 1
        per_qtype.setdefault(rec["qtype"], collections.Counter())[bucket] += 1
        failed_cids.setdefault(bucket, []).append(rec["cid"])

    print(
        json.dumps(
            {
                "pack": args.pack.name,
                "results": args.results.name,
                "with_correct": with_correct,
                "with_failed": matched,
                "failed_by_bucket": dict(counts.get("failed", {})),
                "correct_control_by_bucket": dict(counts["correct"]),
                "failed_by_verdict": {k: dict(v) for k, v in per_verdict.items()},
                "failed_by_qtype": {k: dict(v) for k, v in per_qtype.items()},
                "failed_cids_by_bucket": {k: sorted(v) for k, v in sorted(failed_cids.items())},
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
