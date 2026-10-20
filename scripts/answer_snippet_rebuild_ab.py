"""Rebuild frozen item texts from the seeded store, then A/B the snippet.

Frozen pickles carry precomputed ContextItems whose text is an ingestion-time
snippet; packing alone never recomputes it. For every item whose id resolves in
the seeded memory.db this script re-derives the text from the store chunk with
`query_focused_snippet` (the currently loaded module — baseline or overlay),
replaces the item text, re-packs the case, and checks gold containment.

Runs on the measurement host. Prints ONLY counters and opaque case hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import pickle
import sqlite3
import sys
from dataclasses import replace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from answer_failure_diagnosis import _norm, _tokens


def _contains(gold: str, blob: str) -> bool:
    norm_gold = _norm(gold)
    if norm_gold and norm_gold in _norm(blob):
        return True
    gold_tokens = _tokens(gold)
    blob_tokens = set(_tokens(blob))
    return bool(gold_tokens) and all(token in blob_tokens for token in gold_tokens)


def _store_texts(db_path: pathlib.Path) -> dict[str, str]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT id, text FROM memory_chunks").fetchall()
    finally:
        conn.close()
    return {row[0]: row[1] for row in rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True, type=pathlib.Path)
    parser.add_argument("--inputs-root", required=True, type=pathlib.Path)
    parser.add_argument("--store-root", required=True, type=pathlib.Path)
    parser.add_argument("--set-dir", required=True)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--snippet-overlay", type=pathlib.Path)
    args = parser.parse_args()

    if args.snippet_overlay is not None:
        _preload_snippet_overlay(args.snippet_overlay)

    from infinity_context_core.application.context_packer import ContextPacker
    from infinity_context_core.application.context_snippets import query_focused_snippet

    gold_by_cid: dict[str, str] = {}
    for line in args.pack.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        gold_by_cid[row["cid"]] = row["gold"]

    inputs = args.inputs_root / args.set_dir / "frozen-private"
    store_cache: dict[pathlib.Path, dict[str, str]] = {}
    matched = 0
    rebuilt_items = 0
    total_items = 0
    rows = []
    for path in sorted(inputs.rglob("*.pickle")):
        cid = hashlib.sha256(path.stem.encode()).hexdigest()[:12]
        if cid not in gold_by_cid:
            continue
        matched += 1
        data = pickle.loads(path.read_bytes())
        qtype = path.parent.name
        db_path = args.store_root / args.set_dir / f"{qtype}-exact-pack-state" / "memory.db"
        if db_path not in store_cache:
            store_cache[db_path] = _store_texts(db_path)
        texts = store_cache[db_path]
        query = data["kwargs"]["query"]

        new_items = []
        for item in data["kwargs"]["items"]:
            total_items += 1
            store_text = texts.get(item.item_id)
            if store_text is None:
                new_items.append(item)
                continue
            snippet = query_focused_snippet(query=query, text=store_text)
            new_items.append(replace(item, text=snippet.text if snippet else store_text))
            rebuilt_items += 1

        kwargs = dict(data["kwargs"], items=new_items)
        result = ContextPacker().pack(**kwargs)
        rendered = result.bundle.rendered_text
        targets = set(data["targets"])
        covered = {ref.source_id for item in result.bundle.items for ref in item.source_refs}
        rows.append(
            {
                "cid": cid,
                "gold_in": _contains(gold_by_cid[cid], rendered),
                "coverage_complete": targets <= covered,
                "sources_total": len(targets),
                "sources_covered": len(targets & covered),
                "ctx_chars": len(rendered),
                "items": len(result.bundle.items),
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    ctx_chars = sorted(row["ctx_chars"] for row in rows)
    print(
        json.dumps(
            {
                "set_dir": args.set_dir,
                "out": str(args.out),
                "cases": len(rows),
                "pack_matched": matched,
                "gold_in": sum(1 for row in rows if row["gold_in"]),
                "coverage_complete": sum(1 for row in rows if row["coverage_complete"]),
                "sources_total": sum(row["sources_total"] for row in rows),
                "sources_covered": sum(row["sources_covered"] for row in rows),
                "rebuilt_items": rebuilt_items,
                "total_items": total_items,
                "median_ctx_chars": ctx_chars[len(ctx_chars) // 2] if ctx_chars else 0,
                "total_ctx_chars": sum(ctx_chars),
            }
        )
    )
    return 0


def _preload_snippet_overlay(path: pathlib.Path) -> None:
    """Redefine the snippet module in place, then rebind importers.

    The package __init__ pulls the collectors chain in before this runs, so
    modules that did `from ... import query_focused_snippet` still hold the
    old function object — rebind every copy to the patched one.
    """
    import infinity_context_core.application.context_snippets as original

    source = path.read_text(encoding="utf-8")
    exec(compile(source, str(path), "exec"), original.__dict__)
    patched = original.query_focused_snippet
    rebound = 0
    for module in list(sys.modules.values()):
        if getattr(module, "query_focused_snippet", None) is patched:
            continue
        if hasattr(module, "query_focused_snippet"):
            module.query_focused_snippet = patched
            rebound += 1
    if not hasattr(original, "_extend_to_edge_hit_cluster"):
        raise SystemExit(f"overlay {path} lacks the edge-extension patch")
    print(f"overlay applied: rebound {rebound} module(s)", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
