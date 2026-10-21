"""Localize where the gold fact dies between packer candidates and rendered text.

For every case whose evidence probe said the packed context was insufficient
(plus the other probe groups as controls), re-runs the production packer on the
frozen pickle and applies a nested containment ladder against the gold answer:

- in_rendered             gold survives into rendered_text (probe disagreement
                          or a fact the judge still deemed insufficient)
- truncated_in_pack       gold is in a SELECTED item's full text but the
                          renderer's per-item truncation cut it out
- dropped_by_pack         gold is in some input candidate item, but no
                          gold-bearing item was selected (budget/char/caps/rank)
- absent_from_candidates  gold is in no input item at all (retrieval/admission)

Runs entirely on the measurement host and prints ONLY counters and opaque case
hashes — no question, gold answer or context text ever reaches stdout.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import pickle
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from answer_failure_diagnosis import _norm, _tokens  # noqa: E402

_DROP_KEYS = (
    "dropped_by_budget",
    "dropped_by_char_cap",
    "dropped_by_source_cap",
    "dropped_by_source_group_cap",
    "dropped_by_answer_support_family_duplicate",
)


def _contains(gold: str, blob: str) -> bool:
    norm_gold = _norm(gold)
    if not norm_gold:
        return False
    if norm_gold in _norm(blob):
        return True
    gold_tokens = list(dict.fromkeys(_tokens(gold)))
    if len(gold_tokens) < 2:
        return False
    blob_tokens = set(_tokens(blob))
    return all(token in blob_tokens for token in gold_tokens)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs-root", required=True, type=pathlib.Path)
    parser.add_argument("--set-dir", required=True)
    parser.add_argument("--pack", required=True, type=pathlib.Path)
    parser.add_argument("--evidence", required=True, type=pathlib.Path)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    args = parser.parse_args()

    from infinity_context_core.application.context_packer import ContextPacker

    evidence: dict[str, str] = {}
    for line in args.evidence.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        evidence[rec["cid"]] = rec["evidence"]
    pack: dict[str, dict] = {}
    for line in args.pack.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["cid"] in evidence:
            pack[row["cid"]] = row

    inputs = args.inputs_root / args.set_dir / "frozen-private"
    per_case: dict[str, dict] = {}
    for path in sorted(inputs.rglob("*.pickle")):
        cid = hashlib.sha256(path.stem.encode()).hexdigest()[:12]
        if cid not in pack:
            continue
        gold = pack[cid]["gold"]
        data = pickle.loads(path.read_bytes())
        candidate_texts = [str(getattr(item, "text", "")) for item in data["kwargs"]["items"]]
        bearing = [i for i, text in enumerate(candidate_texts) if _contains(gold, text)]
        if not bearing:
            per_case[cid] = {"bucket": "absent_from_candidates", "bearing_fraction": None}
            continue
        result = ContextPacker().pack(**data["kwargs"])
        selected_texts = [str(getattr(item, "text", "")) for item in result.bundle.items]
        selected_bearing = [text for text in selected_texts if _contains(gold, text)]
        if _contains(gold, result.bundle.rendered_text):
            bucket = "in_rendered"
        elif selected_bearing:
            bucket = "truncated_in_pack"
        else:
            bucket = "dropped_by_pack"
        diag = result.bundle.diagnostics or {}
        total = len(candidate_texts)
        per_case[cid] = {
            "bucket": bucket,
            "bearing_over_2000": int(any(len(text) > 2000 for text in selected_bearing)),
            "bearing_fraction": round(bearing[0] / max(1, total - 1), 3) if total > 1 else 0.0,
            **{key: int(diag.get(key, 0)) for key in _DROP_KEYS},
        }

    buckets: dict[str, collections.Counter] = {}
    drop_reasons: dict[str, collections.Counter] = {}
    truncation_over_2000 = 0
    dropped_positions: list[float] = []
    cids_by_bucket: dict[str, list[str]] = {}
    for cid in pack:
        case = per_case.get(cid, {"bucket": "missing_pickle", "bearing_fraction": None})
        group = "insufficient" if evidence[cid] == "insufficient" else f"probe_{evidence[cid]}"
        bucket = case["bucket"]
        buckets.setdefault(group, collections.Counter())[bucket] += 1
        cids_by_bucket.setdefault(f"{group}:{bucket}", []).append(cid)
        if bucket == "truncated_in_pack":
            truncation_over_2000 += int(case.get("bearing_over_2000", 0))
        if bucket == "dropped_by_pack":
            for key in _DROP_KEYS:
                drop_reasons.setdefault(group, collections.Counter())[key] += int(case.get(key, 0))
            if case["bearing_fraction"] is not None:
                dropped_positions.append(case["bearing_fraction"])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "\n".join(
            json.dumps(
                {"cid": cid, "bucket": per_case.get(cid, {}).get("bucket", "missing_pickle")}
            )
            for cid in sorted(pack)
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "pack": args.pack.name,
                "evidence": args.evidence.name,
                "cases": len(pack),
                "buckets_by_group": {k: dict(v) for k, v in sorted(buckets.items())},
                "drop_reason_sums": {k: dict(v) for k, v in sorted(drop_reasons.items())},
                "truncated_cases_with_bearing_item_over_2000": truncation_over_2000,
                "dropped_case_median_first_bearing_fraction": (
                    round(statistics.median(dropped_positions), 3) if dropped_positions else None
                ),
                "cids_by_bucket": {k: sorted(v) for k, v in sorted(cids_by_bucket.items())},
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
