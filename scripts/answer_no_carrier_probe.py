"""Explain absent_no_carrier failures: split fact vs missing fact.

For every case the bucket ladder marked `absent_no_carrier` (no single store
chunk contains the gold), the seeded store is checked for weaker signals:

- split_across_adjacent  two adjacent chunks of the same scope contain the
                         full normalized gold as a contiguous span
- scattered              >= SCATTER_THRESHOLD of gold tokens exist in the
                         store union but no chunk/pair holds the full span
- missing_tokens         less than the threshold of gold tokens exists at all
                         (the fact is genuinely absent from memory)

Runs on the measurement host. Prints ONLY counters, opaque case hashes and
ratios — no question, gold answer or chunk text ever reaches stdout.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from answer_failure_diagnosis import _norm, _tokens  # noqa: E402

SCATTER_THRESHOLD = 0.9


def _store_rows(db_path: pathlib.Path) -> list[tuple[str, str | None, int | None, str]]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT id, memory_scope_id, char_start, text FROM memory_chunks"
        ).fetchall()
    finally:
        conn.close()


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
        if row.get("sub") == "absent_no_carrier" and row["cid"] in gold_by_cid:
            targets.add(row["cid"])

    inputs = args.inputs_root / args.set_dir / "frozen-private"
    store_cache: dict[pathlib.Path, list[tuple[str, str | None, int | None, str]]] = {}
    rows = []
    for path in sorted(inputs.rglob("*.pickle")):
        cid = hashlib.sha256(path.stem.encode()).hexdigest()[:12]
        if cid not in targets:
            continue
        gold = gold_by_cid[cid]
        qtype = path.parent.name
        db_path = args.store_root / args.set_dir / f"{qtype}-exact-pack-state" / "memory.db"
        if db_path not in store_cache:
            store_cache[db_path] = _store_rows(db_path)
        store_rows = store_cache[db_path]

        gold_tokens = list(dict.fromkeys(_tokens(gold)))
        norm_gold = _norm(gold)
        union: set[str] = set()
        best_chunk = 0
        by_scope: dict[str | None, list[tuple[int, str]]] = {}
        for _cid, scope, char_start, text in store_rows:
            present = [token for token in gold_tokens if token in _norm(text)]
            union.update(present)
            best_chunk = max(best_chunk, len(present))
            by_scope.setdefault(scope, []).append((char_start or 0, text))

        split_adjacent = False
        for chunks in by_scope.values():
            chunks.sort()
            for (_, left), (_, right) in zip(chunks, chunks[1:], strict=False):
                if norm_gold and norm_gold in _norm(left + " " + right):
                    split_adjacent = True
                    break
            if split_adjacent:
                break

        union_ratio = len(union) / len(gold_tokens) if gold_tokens else 0.0
        if split_adjacent:
            verdict = "split_across_adjacent"
        elif union_ratio >= SCATTER_THRESHOLD:
            verdict = "scattered"
        else:
            verdict = "missing_tokens"
        rows.append(
            {
                "cid": cid,
                "verdict": verdict,
                "union_ratio": round(union_ratio, 3),
                "best_chunk_ratio": round(best_chunk / len(gold_tokens), 3) if gold_tokens else 0.0,
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    counts: collections.Counter = collections.Counter(row["verdict"] for row in rows)
    print(
        json.dumps(
            {
                "set_dir": args.set_dir,
                "out": str(args.out),
                "cases": len(rows),
                "verdicts": dict(counts),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
