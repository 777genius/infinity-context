"""Estimate lexical-recall headroom for absent_not_retrieved cases.

For every case the bucket ladder marked `absent_not_retrieved` (a store chunk
contains the gold, but no candidate did), all store chunks are ranked by a
naive query-token overlap score and the best rank of a gold-bearing chunk is
recorded. A gold chunk in the lexical top ranks means a lexical recall channel
would plausibly have surfaced it; a deep rank means semantic recall or query
rewriting is required.

The score is intentionally naive (fraction of query content tokens present, no
IDF) — this measures headroom, not production ranking quality.

Runs on the measurement host. Prints ONLY counters, opaque case hashes and
ranks — no question, gold answer or chunk text ever reaches stdout.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import pickle
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from answer_failure_diagnosis import _tokens  # noqa: E402
from answer_snippet_rebuild_ab import _contains  # noqa: E402

_TOPS = (1, 3, 25, 75, 150, 1000)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True, type=pathlib.Path)
    parser.add_argument("--ladder", required=True, type=pathlib.Path)
    parser.add_argument("--inputs-root", required=True, type=pathlib.Path)
    parser.add_argument("--store-root", required=True, type=pathlib.Path)
    parser.add_argument("--set-dir", required=True)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    args = parser.parse_args()

    gold_by_cid: dict[str, str] = {}
    for line in args.pack.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        gold_by_cid[row["cid"]] = row["gold"]

    targets: set[str] = set()
    for line in args.ladder.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("sub") == "absent_not_retrieved" and row["cid"] in gold_by_cid:
            targets.add(row["cid"])

    inputs = args.inputs_root / args.set_dir / "frozen-private"
    store_cache: dict[pathlib.Path, list[tuple[str, str]]] = {}
    rows = []
    for path in sorted(inputs.rglob("*.pickle")):
        cid = hashlib.sha256(path.stem.encode()).hexdigest()[:12]
        if cid not in targets:
            continue
        data = pickle.loads(path.read_bytes())
        query_tokens = set(_tokens(data["kwargs"]["query"]))
        db_path = (
            args.store_root / args.set_dir / f"{path.parent.name}-exact-pack-state" / "memory.db"
        )
        if db_path not in store_cache:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                store_cache[db_path] = conn.execute("SELECT id, text FROM memory_chunks").fetchall()
            finally:
                conn.close()
        store_rows = store_cache[db_path]

        scored: list[tuple[float, int, int]] = []
        gold_positions: list[int] = []
        for position, (_chunk_id, text) in enumerate(store_rows):
            text_tokens = set(_tokens(text))
            overlap = len(query_tokens & text_tokens)
            scored.append((-overlap / max(1, len(query_tokens)), -overlap, position))
            if _contains(gold_by_cid[cid], text):
                gold_positions.append(position)
        scored.sort()
        rank_by_position = {position: rank for rank, (_, _, position) in enumerate(scored)}
        best_rank = min((rank_by_position[p] for p in gold_positions), default=None)
        rows.append(
            {
                "cid": cid,
                "store_chunks": len(store_rows),
                "gold_chunks": len(gold_positions),
                "gold_lexical_rank": best_rank,
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    ranks = [row["gold_lexical_rank"] for row in rows if row["gold_lexical_rank"] is not None]
    in_top: collections.Counter = collections.Counter()
    for top in _TOPS:
        in_top[f"top_{top}"] = sum(1 for rank in ranks if rank < top)
    print(
        json.dumps(
            {
                "set_dir": args.set_dir,
                "out": str(args.out),
                "cases": len(rows),
                "cases_without_gold_chunk": len(rows) - len(ranks),
                "gold_chunk_in": dict(in_top),
                "best_ranks": sorted(ranks),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
