"""Explain why the product keyword SQL never matches gold on never_matched cases.

The recall probe labels a target `never_matched` when neither the keyword lane
nor a direct big-limit product query surfaces its gold chunk. This probe takes
those cases and decomposes the exact SQL predicate (`keyword_search_many` over
normalized_text with LIKE substring variants) per gold-bearing store chunk:

- scope       space/scope of the reconstructed request vs the chunk row
- visibility  status == active and classification != restricted
- thread      request thread_id vs chunk thread_id (NULL passes)
- term_match  any `_terms(query)` variant as a substring of normalized_text

It also classifies which query terms the adapter pipeline drops before SQL
(short variants, stopwords, no-variant tokens, the 24-term cap) and checks
whether any dropped term group alone would have matched the gold chunk.

Runs on the measurement host. Prints ONLY counters and opaque case hashes —
no question, gold answer or chunk text ever reaches stdout.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import pickle
import re
import sqlite3
import unicodedata


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text)).lower()
    text = re.sub(r"[^0-9a-zа-яё]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    return [token for token in _norm(text).split() if len(token) > 1]


def _contains(gold: str, blob: str) -> bool:
    norm_gold = _norm(gold)
    if norm_gold and norm_gold in _norm(blob):
        return True
    gold_tokens = _tokens(gold)
    blob_tokens = set(_tokens(blob))
    return bool(gold_tokens) and all(token in blob_tokens for token in gold_tokens)


def _cid(path: pathlib.Path) -> str:
    return hashlib.sha256(path.stem.encode()).hexdigest()[:12]


def _store_rows(db_path: pathlib.Path) -> dict[str, dict]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT id, space_id, memory_scope_id, thread_id, status, classification, "
            "text, normalized_text FROM memory_chunks"
        ).fetchall()
    finally:
        conn.close()
    return {
        row[0]: {
            "space": row[1],
            "scope": row[2],
            "thread": row[3],
            "status": row[4],
            "classification": row[5],
            "text": row[6],
            "norm": row[7] or "",
        }
        for row in rows
    }


def _majority_scope(item_ids: set[str], rows: dict[str, dict]) -> tuple | None:
    seen: collections.Counter[tuple] = collections.Counter(
        (row["space"], row["scope"], row["thread"])
        for item_id, row in rows.items()
        if item_id in item_ids
    )
    if not seen:
        return None
    return seen.most_common(1)[0][0]


def _active_scope_ids(db_path: pathlib.Path, space_id: str) -> set[str]:
    """Scope ids the HTTP contract will accept: memory_scopes.status == active."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT id FROM memory_scopes WHERE space_id = ? AND status = 'active'",
            (space_id,),
        ).fetchall()
    finally:
        conn.close()
    return {row[0] for row in rows}


def _hash(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()[:8]


def _nofilter_gold_hits(
    db_path: pathlib.Path,
    space_id: str,
    scope_ids: tuple[str, ...],
    query_text: str,
    gold_ids: set[str],
) -> set[str]:
    """Product keyword SQL with every scope included and no thread filter."""
    import asyncio
    import shutil
    import tempfile

    from infinity_context_adapters.postgres.canonical_retrieval_batching import (
        keyword_search_many as sql_keyword_search_many,
    )
    from infinity_context_core.ports.repositories import ChunkKeywordSearch
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async def _run(work_db: pathlib.Path) -> set[str]:
        engine = create_async_engine(f"sqlite+aiosqlite:///{work_db}")
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                groups = await sql_keyword_search_many(
                    session,
                    (
                        ChunkKeywordSearch(
                            space_id=space_id,
                            memory_scope_ids=scope_ids,
                            thread_id=None,
                            query=query_text,
                            limit=10000,
                        ),
                    ),
                )
            return {str(chunk.id) for chunk in groups[0]} & gold_ids
        finally:
            await engine.dispose()

    # the SQLAlchemy engine cannot open mode=ro, so run against a temp copy
    with tempfile.TemporaryDirectory(prefix="nofiltersql-") as tmp:
        work_db = pathlib.Path(tmp) / "memory.db"
        shutil.copyfile(db_path, work_db)
        return asyncio.run(_run(work_db))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True, type=pathlib.Path)
    parser.add_argument("--recall", required=True, type=pathlib.Path)
    parser.add_argument("--inputs-root", required=True, type=pathlib.Path)
    parser.add_argument("--store-root", required=True, type=pathlib.Path)
    parser.add_argument("--set-dir", required=True)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    args = parser.parse_args()

    gold_by_cid: dict[str, str] = {}
    for line in args.pack.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        gold_by_cid[row["cid"]] = row["gold"]

    selected: dict[str, str] = {}
    for line in args.recall.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        death = row.get("death")
        if death in ("never_matched", "recovered"):
            selected[row["cid"]] = death

    from infinity_context_adapters.postgres.repository_helpers import _terms
    from infinity_context_core.application.context_lexical import (
        _QUERY_STOPWORDS,
        lexical_variants,
        query_terms,
    )

    rows_out: list[dict] = []
    inputs = args.inputs_root / args.set_dir / "frozen-private"
    store_cache: dict[pathlib.Path, dict[str, dict]] = {}
    for path in sorted(inputs.rglob("*.pickle")):
        cid = _cid(path)
        if cid not in selected:
            continue
        data = pickle.loads(path.read_bytes())
        query_text = data["kwargs"]["query"]
        frozen_ids = {item.item_id for item in data["kwargs"]["items"]}
        db_path = (
            args.store_root / args.set_dir / f"{path.parent.name}-exact-pack-state" / "memory.db"
        )
        if not db_path.is_file():
            continue
        if db_path not in store_cache:
            store_cache[db_path] = _store_rows(db_path)
        rows = store_cache[db_path]

        gold_ids = {
            item_id for item_id, row in rows.items() if _contains(gold_by_cid[cid], row["text"])
        }
        scope = _majority_scope(frozen_ids, rows)
        if scope is None:
            scope = _majority_scope(gold_ids, rows)
        request_thread = scope[2] if scope is not None else None

        capped_terms = _terms(query_text)
        uncapped_terms = tuple(
            term
            for term in query_terms(query_text, max_terms=None)
            if any(len(variant) >= 3 for variant in term.variants)
        )
        capped_raws = {term.raw for term in capped_terms}
        cap_dropped_terms = tuple(
            term
            for term in uncapped_terms
            if term.raw not in capped_raws
            or not any(len(variant) >= 3 for variant in term.variants)
        )

        layer_counts: collections.Counter[str] = collections.Counter()
        naive_buckets: collections.Counter[str] = collections.Counter()
        request_space = scope[0] if scope is not None else None
        active_scopes = (
            _active_scope_ids(db_path, request_space) if request_space is not None else set()
        )
        gold_rows = 0
        for item_id in sorted(gold_ids):
            row = rows[item_id]
            gold_rows += 1
            in_scope = scope is not None and row["space"] == scope[0] and row["scope"] == scope[1]
            visible = row["status"] == "active" and row["classification"] != "restricted"
            thread_ok = row["thread"] is None or row["thread"] == request_thread
            term_hit = any(variant in row["norm"] for term in capped_terms for variant in term.variants)
            uncapped_hit = any(
                variant in row["norm"] for term in uncapped_terms for variant in term.variants
            )
            cap_only_hit = uncapped_hit and not term_hit
            if in_scope:
                layer_counts["scope_ok"] += 1
            elif row["space"] != request_space:
                # gold row lives in another space: unreachable for this request
                layer_counts["scope_miss_space"] += 1
            elif row["scope"] not in active_scopes:
                # archived/deleted scope: unreachable for any HTTP request
                layer_counts["scope_miss_inactive"] += 1
            else:
                # active scope simply absent from the request's scope set
                layer_counts["scope_miss_active"] += 1
            if visible:
                layer_counts["visible_ok"] += 1
            else:
                layer_counts["visible_miss"] += 1
            if thread_ok:
                layer_counts["thread_ok"] += 1
            else:
                layer_counts["thread_miss"] += 1
            if term_hit:
                layer_counts["term_ok"] += 1
            else:
                layer_counts["term_miss"] += 1
            if in_scope and visible and thread_ok:
                layer_counts["filters_ok_no_term" if not term_hit else "full_match"] += 1
            if cap_only_hit:
                layer_counts["cap_only_hit"] += 1

            row_tokens = set(_tokens(row["text"]))
            for token in set(_tokens(query_text)) & row_tokens:
                if len(token) < 3:
                    naive_buckets["dropped_short"] += 1
                elif token in _QUERY_STOPWORDS:
                    naive_buckets["dropped_stopword"] += 1
                elif not lexical_variants(token):
                    naive_buckets["dropped_no_variant"] += 1
                elif token not in capped_raws:
                    naive_buckets["dropped_cap"] += 1
                else:
                    naive_buckets["kept"] += 1

        store_scopes = sorted({(row["space"], row["scope"]) for row in rows.values()})
        item_scope_set = sorted(
            {(rows[i]["space"], rows[i]["scope"]) for i in frozen_ids if i in rows}
        )
        gold_scope_set = sorted({(rows[i]["space"], rows[i]["scope"]) for i in gold_ids})
        gold_thread_set = sorted({rows[i]["thread"] for i in gold_ids})
        if request_space is None:
            request_space = store_scopes[0][0] if store_scopes else None
            active_scopes = (
                _active_scope_ids(db_path, request_space) if request_space is not None else set()
            )
        # upper bound of the keyword SQL lane: every active scope, no thread filter
        nofilter_hits = (
            len(
                _nofilter_gold_hits(
                    db_path,
                    request_space,
                    tuple(sorted(active_scopes)),
                    query_text,
                    gold_ids,
                )
            )
            if gold_ids and request_space is not None and active_scopes
            else 0
        )

        rows_out.append(
            {
                "cid": cid,
                "death": selected[cid],
                "gold_rows": gold_rows,
                "query_terms_capped": len(capped_terms),
                "query_terms_uncapped": len(uncapped_terms),
                "cap_dropped_terms": len(cap_dropped_terms),
                "layers": dict(layer_counts),
                "naive_overlap_buckets": dict(naive_buckets),
                "store_scope_n": len(store_scopes),
                "req_scope_hash": _hash(scope) if scope is not None else None,
                "item_scope_hashes": [_hash(entry) for entry in item_scope_set],
                "gold_scope_hashes": [_hash(entry) for entry in gold_scope_set],
                "gold_scopes_in_items": bool(set(gold_scope_set) & set(item_scope_set)),
                "req_thread_hash": _hash(request_thread),
                "gold_thread_hashes": [_hash(t) for t in gold_thread_set],
                "gold_threads_in_req": request_thread in gold_thread_set
                if request_thread is not None
                else None,
                "nofilter_gold_hits": nofilter_hits,
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in rows_out:
            handle.write(json.dumps(row) + "\n")

    def summarize(group: list[dict]) -> dict:
        layers: collections.Counter[str] = collections.Counter()
        naive: collections.Counter[str] = collections.Counter()
        for row in group:
            layers.update(row["layers"])
            naive.update(row["naive_overlap_buckets"])
        return {
            "cases": len(group),
            "gold_rows": sum(row["gold_rows"] for row in group),
            "layers": dict(layers),
            "naive_overlap_buckets": dict(naive),
            "median_query_terms_capped": sorted(row["query_terms_capped"] for row in group)[
                len(group) // 2
            ]
            if group
            else None,
            "cases_cap_only_hit": sum(1 for row in group if row["layers"].get("cap_only_hit")),
            "cases_filters_ok_no_term": sum(
                1 for row in group if row["layers"].get("filters_ok_no_term")
            ),
            "cases_gold_scope_in_items": sum(
                1 for row in group if row["gold_scopes_in_items"]
            ),
            "cases_gold_thread_in_req": sum(
                1 for row in group if row["gold_threads_in_req"]
            ),
            "cases_nofilter_gold_hit": sum(
                1 for row in group if row["nofilter_gold_hits"] > 0
            ),
            "gold_rows_nofilter_hit": sum(row["nofilter_gold_hits"] for row in group),
            "median_store_scopes": sorted(row["store_scope_n"] for row in group)[
                len(group) // 2
            ]
            if group
            else None,
        }

    never = [row for row in rows_out if row["death"] == "never_matched"]
    recovered = [row for row in rows_out if row["death"] == "recovered"]
    print(
        json.dumps(
            {
                "set_dir": args.set_dir,
                "out": str(args.out),
                "never_matched": summarize(never),
                "recovered_control": summarize(recovered),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
