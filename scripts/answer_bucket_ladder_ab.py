"""Bucket ladder on rebuilt item texts, A/B against the snippet overlay.

Same rebuild path as answer_snippet_rebuild_ab (texts re-derived from the
seeded store with the currently loaded snippet module), then the nested
containment ladder from answer_evidence_gap_probe:

- in_rendered             gold survives into rendered_text
- truncated_in_pack        gold is in a selected item but the renderer cut it
- dropped_by_pack          gold-bearing item exists but was not selected
- absent_from_candidates   gold is in no rebuilt candidate item

For absent cases the seeded store is checked for a gold-bearing chunk:
- absent_snippet_cut       the chunk was retrieved (its id is among the
                           candidates) but its snippet drops the gold
- absent_not_retrieved     a gold-bearing store chunk exists but was never
                           retrieved into candidates
- absent_no_carrier        no store chunk contains the gold at all

Runs on the measurement host. Prints ONLY counters and opaque case hashes.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import pickle
import sys
from dataclasses import replace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from answer_snippet_rebuild_ab import _contains, _store_texts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True, type=pathlib.Path)
    parser.add_argument("--results", type=pathlib.Path)
    parser.add_argument("--inputs-root", required=True, type=pathlib.Path)
    parser.add_argument("--store-root", required=True, type=pathlib.Path)
    parser.add_argument("--set-dir", required=True)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--snippet-overlay", type=pathlib.Path)
    args = parser.parse_args()

    if args.snippet_overlay is not None:
        from answer_snippet_rebuild_ab import _preload_snippet_overlay

        _preload_snippet_overlay(args.snippet_overlay)

    from infinity_context_core.application.context_packer import ContextPacker
    from infinity_context_core.application.context_snippets import query_focused_snippet

    gold_by_cid: dict[str, str] = {}
    for line in args.pack.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        gold_by_cid[row["cid"]] = row["gold"]

    verdict_group: dict[str, str] = {}
    if args.results is not None:
        for line in args.results.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec["arm"] == "with" and rec["cid"] in gold_by_cid:
                verdict_group[rec["cid"]] = "failure" if rec["verdict"] != "correct" else "control"

    inputs = args.inputs_root / args.set_dir / "frozen-private"
    store_cache: dict[pathlib.Path, dict[str, str]] = {}
    rows = []
    for path in sorted(inputs.rglob("*.pickle")):
        cid = hashlib.sha256(path.stem.encode()).hexdigest()[:12]
        if cid not in gold_by_cid:
            continue
        gold = gold_by_cid[cid]
        data = pickle.loads(path.read_bytes())
        qtype = path.parent.name
        db_path = args.store_root / args.set_dir / f"{qtype}-exact-pack-state" / "memory.db"
        if db_path not in store_cache:
            store_cache[db_path] = _store_texts(db_path)
        texts = store_cache[db_path]
        query = data["kwargs"]["query"]

        new_items = []
        for item in data["kwargs"]["items"]:
            store_text = texts.get(item.item_id)
            if store_text is None:
                new_items.append(item)
                continue
            snippet = query_focused_snippet(query=query, text=store_text)
            new_items.append(replace(item, text=snippet.text if snippet else store_text))

        candidate_ids = {item.item_id for item in new_items}
        candidate_texts = [str(getattr(item, "text", "")) for item in new_items]
        if not any(_contains(gold, text) for text in candidate_texts):
            gold_store_ids = sorted(
                item_id for item_id, text in texts.items() if _contains(gold, text)
            )
            if not gold_store_ids:
                sub = "absent_no_carrier"
            elif any(item_id in candidate_ids for item_id in gold_store_ids):
                sub = "absent_snippet_cut"
            else:
                sub = "absent_not_retrieved"
            rows.append({"cid": cid, "bucket": "absent_from_candidates", "sub": sub})
            continue

        result = ContextPacker().pack(**dict(data["kwargs"], items=new_items))
        selected_texts = [str(getattr(item, "text", "")) for item in result.bundle.items]
        if _contains(gold, result.bundle.rendered_text):
            bucket = "in_rendered"
        elif any(_contains(gold, text) for text in selected_texts):
            bucket = "truncated_in_pack"
        else:
            bucket = "dropped_by_pack"
        rows.append({"cid": cid, "bucket": bucket, "sub": None})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    buckets: dict[str, collections.Counter] = {}
    absent_subs: dict[str, collections.Counter] = {}
    for row in rows:
        group = verdict_group.get(row["cid"], "no_results")
        buckets.setdefault(group, collections.Counter())[row["bucket"]] += 1
        if row["sub"] is not None:
            absent_subs.setdefault(group, collections.Counter())[row["sub"]] += 1
    print(
        json.dumps(
            {
                "set_dir": args.set_dir,
                "out": str(args.out),
                "cases": len(rows),
                "buckets_by_group": {k: dict(v) for k, v in sorted(buckets.items())},
                "absent_subs_by_group": {k: dict(v) for k, v in sorted(absent_subs.items())},
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
