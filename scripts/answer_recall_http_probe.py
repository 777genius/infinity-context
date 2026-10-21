"""Replay frozen queries through the product /v1/context path on a store copy.

The frozen pickles were cut at the ContextPacker.pack seam (their kwargs match
its keyword signature exactly) during a /v1/context request, so this probe
reconstructs that request — scope from the frozen candidate rows, token_budget
from the frozen kwargs — against a temp copy of the seeded memory.db with a
provider-free TEST-profile app, intercepts pack(), and compares:

- fidelity   replayed candidate ids vs the frozen candidate ids
- recall     gold-bearing store chunk ids vs replayed candidate ids
             (targets: the absent_not_retrieved class; controls: in_rendered)
- death layer three seams localize where the gold chunk dies:
    never_matched   neither the product keyword lane nor a direct big-limit
                    raw-query SQL search ever surfaces the gold chunk
    baseline_skipped_no_scope  big-limit baseline skipped (no SQL scope)
    baseline_error  big-limit baseline raised; death unobserved, not a miss
    pool_truncated  raw-query SQL matches it but the merged lane pool drops it
    admit_*          admit_keyword_chunk rejects it (project_identity /
                     anchor_conflict / insufficient_relevance), with
                     admit_best_none for the silent best_query-missing path
    lost_after_admit admitted but absent from packer candidates (item stage)
    unattributed     in the pool but no admission record for its text
    http_error       /v1/context returned 5xx for this case

Runs on the measurement host. Prints ONLY counters and opaque case hashes —
no question, gold answer or context text ever reaches stdout.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import pickle
import re
import shutil
import statistics
import tempfile
import unicodedata
from unittest import mock


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
    import sqlite3

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT id, space_id, memory_scope_id, thread_id, text, metadata_json "
            "FROM memory_chunks"
        ).fetchall()
    finally:
        conn.close()
    return {
        row[0]: {
            "space": row[1],
            "scope": row[2],
            "thread": row[3],
            "text": row[4],
            "meta": row[5],
        }
        for row in rows
    }


def _active_scope_ids(db_path: pathlib.Path, space_id: str) -> tuple[str, ...]:
    """Scope ids the HTTP contract will accept: memory_scopes.status == active."""
    import sqlite3

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT id FROM memory_scopes WHERE space_id = ? AND status = 'active'",
            (space_id,),
        ).fetchall()
    finally:
        conn.close()
    return tuple(row[0] for row in rows)


def _majority_scope(item_ids: set[str], rows: dict[str, dict]) -> tuple[tuple | None, bool]:
    seen = collections.Counter(
        (row["space"], row["scope"], row["thread"])
        for row in (rows[item_id] for item_id in item_ids if item_id in rows)
    )
    if not seen:
        return None, False
    scope, count = seen.most_common(1)[0]
    return scope, len(seen) > 1


async def _biglimit_gold_ids(
    db_path: pathlib.Path,
    space_id: str,
    scope_ids: tuple[str, ...],
    thread_id: str | None,
    query_text: str,
    gold_ids: set[str],
) -> tuple[int, set[str]]:
    """Direct product SQL keyword search with a huge limit: (total, gold hits)."""
    from infinity_context_adapters.postgres.canonical_retrieval_batching import (
        keyword_search_many as sql_keyword_search_many,
    )
    from infinity_context_core.ports.repositories import ChunkKeywordSearch
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            groups = await sql_keyword_search_many(
                session,
                (
                    ChunkKeywordSearch(
                        space_id=space_id,
                        memory_scope_ids=scope_ids,
                        thread_id=thread_id,
                        query=query_text,
                        limit=10000,
                    ),
                ),
            )
        matched = {str(chunk.id) for chunk in groups[0]}
        return len(matched), gold_ids & matched
    finally:
        await engine.dispose()


def _conflict_breakdown(anchor_intent, text: str) -> dict:
    """Structural anchor-conflict facts: which kinds conflict, key counts only."""
    from infinity_context_core.application.context_query_intent_matching import (
        _compatible_identity_matches,
        _observed_anchor_identity_keys,
        _text_intent_observed_anchors,
    )
    from infinity_context_core.domain.entities import MemoryAnchorKind

    identity_kinds = (
        MemoryAnchorKind.PERSON,
        MemoryAnchorKind.PROJECT,
        MemoryAnchorKind.ORGANIZATION,
    )
    if anchor_intent.empty:
        return {"conflict_kinds": [], "query_conflict_keys": {}, "observed_keys": {}}
    anchors = _text_intent_observed_anchors(text)
    conflict_kinds: list[str] = []
    query_key_counts: dict[str, int] = {}
    observed_counts: dict[str, int] = {}
    for kind in identity_kinds:
        query_keys = anchor_intent.conflict_keys_for_kind(kind)
        if not query_keys:
            continue
        query_key_counts[kind.value] = len(query_keys)
        observed: set[str] = set()
        for anchor in anchors:
            if anchor.kind == kind:
                observed.update(_observed_anchor_identity_keys(anchor))
        if observed:
            observed_counts[kind.value] = len(observed)
        if observed and not _compatible_identity_matches(observed, query_keys):
            conflict_kinds.append(kind.value)
    return {
        "conflict_kinds": conflict_kinds,
        "query_conflict_keys": query_key_counts,
        "observed_keys": observed_counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True, type=pathlib.Path)
    parser.add_argument("--ladder", required=True, type=pathlib.Path)
    parser.add_argument("--inputs-root", required=True, type=pathlib.Path)
    parser.add_argument("--store-root", required=True, type=pathlib.Path)
    parser.add_argument("--set-dir", required=True)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--control", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-facts", type=int)
    parser.add_argument("--max-chunks", type=int)
    parser.add_argument("--max-evidence-items", type=int)
    parser.add_argument(
        "--scope-set",
        choices=("majority", "all", "oracle"),
        default="majority",
        help="request scope: majority = one scope from frozen items (the frozen "
        "contract); all = every active scope in the space, thread filter omitted; "
        "oracle = majority scope plus the gold chunks' scopes (perfect-knowledge "
        "ceiling), thread filter omitted",
    )
    args = parser.parse_args()

    gold_by_cid: dict[str, str] = {}
    for line in args.pack.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        gold_by_cid[row["cid"]] = row["gold"]

    ladder: dict[str, dict] = {}
    for line in args.ladder.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        ladder[row["cid"]] = row

    targets = sorted(cid for cid, row in ladder.items() if row.get("sub") == "absent_not_retrieved")
    controls = sorted(cid for cid, row in ladder.items() if row.get("bucket") == "in_rendered")
    step = max(1, len(controls) // max(1, args.control))
    selected = set(targets + controls[::step][: args.control])
    if args.limit:
        ordered = targets + [cid for cid in controls[::step][: args.control]]
        selected = set(ordered[: args.limit])

    pickles: dict[str, pathlib.Path] = {}
    inputs = args.inputs_root / args.set_dir / "frozen-private"
    for path in sorted(inputs.rglob("*.pickle")):
        cid = _cid(path)
        if cid in selected:
            pickles[cid] = path

    by_store: dict[pathlib.Path, list[str]] = {}
    for cid, path in pickles.items():
        qtype = path.parent.name
        db_path = args.store_root / args.set_dir / f"{qtype}-exact-pack-state" / "memory.db"
        by_store.setdefault(db_path, []).append(cid)

    missing_stores = sorted(str(path) for path in by_store if not path.is_file())
    if missing_stores:
        print(json.dumps({"missing_stores": missing_stores, "cases": len(pickles)}, indent=2))
        return 2

    import asyncio

    import infinity_context_core.application.context_collectors as collectors_mod
    import infinity_context_core.application.use_cases.build_context as bc_module
    from fastapi.testclient import TestClient
    from infinity_context_core.application.context_packer import ContextPacker
    from infinity_context_core.application.document_text import (
        document_chunk_retrieval_text,
    )
    from infinity_context_server.config import DeployProfile, Settings
    from infinity_context_server.main import create_app

    original_pack = ContextPacker.pack
    captured: list[dict] = []
    biglimit_error_kinds: collections.Counter[str] = collections.Counter()

    def pack_spy(self, *call_args, **call_kwargs):
        captured.append(
            {
                "ids": {item.item_id for item in call_kwargs.get("items", ())},
                "n": len(call_kwargs.get("items", ())),
                "token_budget": call_kwargs.get("token_budget"),
                "max_rendered_chars": call_kwargs.get("max_rendered_chars"),
            }
        )
        return original_pack(self, *call_args, **call_kwargs)

    original_keyword = collectors_mod._keyword_search_chunks
    kw_captured: list[dict] = []

    async def keyword_spy(uow, **call_kwargs):
        chunks = await original_keyword(uow, **call_kwargs)
        kw_captured.append(
            {
                "ids": [str(chunk.id) for chunk in chunks],
                "limit": call_kwargs.get("limit"),
                "queries": len(call_kwargs.get("retrieval_queries") or ()),
            }
        )
        return chunks

    original_admit = bc_module.admit_keyword_chunk
    current_gold_texts: set[str] = set()
    admission_records: list[dict] = []

    def admit_spy(*, query, text, anchor_intent, best_query):
        result = original_admit(
            query=query, text=text, anchor_intent=anchor_intent, best_query=best_query
        )
        if text in current_gold_texts:
            record: dict = {"reason": result.reason, "best_none": result.best_query is None}
            if result.best_query is not None:
                _, expansion_reason, relevance = result.best_query
                record["expansion_reason"] = expansion_reason
                record["distinctive"] = relevance.distinctive_term_hits
                record["unique"] = relevance.unique_term_hits
                record["hit_ratio"] = round(relevance.hit_ratio, 3)
            if result.reason == "anchor_conflict":
                record.update(_conflict_breakdown(anchor_intent, text))
                record["event_only_conflict"] = not record["conflict_kinds"]
            admission_records.append(record)
        return result

    rows: list[dict] = []
    with (
        mock.patch.object(ContextPacker, "pack", pack_spy),
        mock.patch.object(collectors_mod, "_keyword_search_chunks", keyword_spy),
        mock.patch.object(bc_module, "admit_keyword_chunk", admit_spy),
    ):
        for db_path, cids in sorted(by_store.items()):
            rows_data = _store_rows(db_path)
            with tempfile.TemporaryDirectory(prefix="recallprobe-") as tmp:
                work_db = pathlib.Path(tmp) / "memory.db"
                shutil.copyfile(db_path, work_db)
                app = create_app(
                    Settings(
                        deploy_profile=DeployProfile.TEST,
                        database_url=f"sqlite+aiosqlite:///{work_db}",
                        auto_create_schema=True,
                        service_token="diagnostic-local-only",
                        qdrant_enabled=False,
                        graphiti_enabled=False,
                        embeddings_enabled=False,
                    )
                )
                with TestClient(app, raise_server_exceptions=False) as client:
                    for cid in sorted(cids):
                        data = pickle.loads(pickles[cid].read_bytes())
                        kwargs = data["kwargs"]
                        frozen_ids = {item.item_id for item in kwargs["items"]}
                        gold_store_ids = {
                            item_id
                            for item_id, row in rows_data.items()
                            if _contains(gold_by_cid[cid], row["text"])
                        }
                        scope, scope_mixed = _majority_scope(frozen_ids, rows_data)
                        scope_source = "items"
                        if scope is None and gold_store_ids:
                            scope, scope_mixed = _majority_scope(gold_store_ids, rows_data)
                            scope_source = "gold"
                        if scope is None:
                            scope_source = None
                        body: dict = {
                            "query": kwargs["query"],
                            "token_budget": kwargs["token_budget"],
                        }
                        scopes_truncated = False
                        if args.scope_set == "all":
                            store_scopes = sorted(
                                {(row["space"], row["scope"]) for row in rows_data.values()}
                            )
                            request_space = (
                                scope[0]
                                if scope is not None
                                else (store_scopes[0][0] if store_scopes else None)
                            )
                            # canonical_scope_matches rejects the whole set when any
                            # scope is not active, so only active scopes are sent;
                            # the HTTP model caps memory_scope_ids at 20, so a
                            # larger store is truncated (flagged in the row).
                            active_ids_all = (
                                _active_scope_ids(db_path, request_space)
                                if request_space is not None
                                else ()
                            )
                            scopes_truncated = len(active_ids_all) > 20
                            scope_ids_all = active_ids_all[:20]
                            sql_scope = (
                                (request_space, scope_ids_all, None)
                                if request_space is not None and scope_ids_all
                                else None
                            )
                            if sql_scope is not None:
                                body.update(
                                    space_id=request_space,
                                    memory_scope_ids=list(scope_ids_all),
                                )
                        elif args.scope_set == "oracle":
                            # perfect-knowledge ceiling: majority scope plus every
                            # active scope holding a gold chunk; thread omitted
                            # because gold often spans threads. The HTTP model caps
                            # memory_scope_ids at 20, so the set is truncated.
                            gold_scopes = {
                                (rows_data[item_id]["space"], rows_data[item_id]["scope"])
                                for item_id in gold_store_ids
                                if item_id in rows_data
                            }
                            if scope is not None:
                                gold_scopes.add((scope[0], scope[1]))
                            request_space = (
                                scope[0]
                                if scope is not None
                                else (min(gold_scopes)[0] if gold_scopes else None)
                            )
                            active_ids = (
                                set(_active_scope_ids(db_path, request_space))
                                if request_space is not None
                                else set()
                            )
                            oracle_ids_all = tuple(
                                sid
                                for sp, sid in sorted(gold_scopes)
                                if sp == request_space and sid in active_ids
                            )
                            scopes_truncated = len(oracle_ids_all) > 20
                            scope_ids_oracle = oracle_ids_all[:20]
                            sql_scope = (
                                (request_space, scope_ids_oracle, None)
                                if request_space is not None and scope_ids_oracle
                                else None
                            )
                            if sql_scope is not None:
                                body.update(
                                    space_id=request_space,
                                    memory_scope_ids=list(scope_ids_oracle),
                                )
                        else:
                            sql_scope = (
                                None if scope is None else (scope[0], (scope[1],), scope[2])
                            )
                            if scope is not None:
                                body.update(
                                    space_id=scope[0],
                                    memory_scope_ids=[scope[1]],
                                    thread_id=scope[2],
                                )
                        if args.max_facts is not None:
                            body["max_facts"] = args.max_facts
                        if args.max_chunks is not None:
                            body["max_chunks"] = args.max_chunks
                        if args.max_evidence_items is not None:
                            body["max_evidence_items"] = args.max_evidence_items
                        current_gold_texts = {
                            document_chunk_retrieval_text(
                                text=rows_data[item_id]["text"],
                                metadata=json.loads(rows_data[item_id]["meta"] or "{}"),
                            )
                            for item_id in gold_store_ids
                            if item_id in rows_data
                        }
                        admission_records.clear()
                        captured.clear()
                        kw_captured.clear()
                        response = client.post(
                            "/v1/context",
                            json=body,
                            headers={"Authorization": "Bearer diagnostic-local-only"},
                        )
                        payload = (
                            response.json()
                            if response.headers.get("content-type", "").startswith(
                                "application/json"
                            )
                            else {}
                        )
                        bundle_data = payload.get("data") or {}
                        replay_ids: set[str] = set()
                        for call in captured:
                            replay_ids |= call["ids"]
                        kw_ids: set[str] = set()
                        kw_rank: int | None = None
                        for call in kw_captured:
                            for position, chunk_id in enumerate(call["ids"]):
                                kw_ids.add(chunk_id)
                                if chunk_id in gold_store_ids and (
                                    kw_rank is None or position < kw_rank
                                ):
                                    kw_rank = position
                        gold_in_keyword = bool(gold_store_ids & kw_ids)
                        gold_in_replay = bool(gold_store_ids & replay_ids)
                        big_total = -1
                        gold_big: set[str] = set()
                        if sql_scope is not None and gold_store_ids:
                            try:
                                big_total, gold_big = asyncio.run(
                                    _biglimit_gold_ids(
                                        work_db,
                                        sql_scope[0],
                                        sql_scope[1],
                                        sql_scope[2],
                                        kwargs["query"],
                                        gold_store_ids,
                                    )
                                )
                            except Exception as exc:  # noqa: BLE001
                                big_total = -2
                                biglimit_error_kinds[type(exc).__name__] += 1
                        gold_in_big = bool(gold_big)
                        gold_scope_n = len(
                            {
                                (
                                    rows_data[item_id]["space"],
                                    rows_data[item_id]["scope"],
                                    rows_data[item_id]["thread"],
                                )
                                for item_id in gold_store_ids
                                if item_id in rows_data
                            }
                        )
                        if response.status_code >= 500:
                            death = "http_error"
                        elif not gold_store_ids:
                            death = "no_gold_chunk"
                        elif gold_in_replay:
                            death = "recovered"
                        elif not gold_in_keyword and big_total == -1:
                            death = "baseline_skipped_no_scope"
                        elif not gold_in_keyword and big_total == -2:
                            death = "baseline_error"
                        elif not gold_in_keyword and not gold_in_big:
                            death = "never_matched"
                        elif not gold_in_keyword and gold_in_big:
                            death = "pool_truncated"
                        elif admission_records:
                            first = admission_records[0]
                            if first["reason"] != "admitted":
                                death = f"admit_{first['reason']}"
                            elif first["best_none"]:
                                death = "admit_best_none"
                            else:
                                death = "lost_after_admit"
                        else:
                            death = "unattributed"
                        best = max(
                            captured, key=lambda call: len(call["ids"] & frozen_ids), default=None
                        )
                        rows.append(
                            {
                                "cid": cid,
                                "bucket": ladder.get(cid, {}).get("bucket"),
                                "sub": ladder.get(cid, {}).get("sub"),
                                "status": response.status_code,
                                "pack_calls": len(captured),
                                "frozen_n": len(frozen_ids),
                                "replay_n": best["n"] if best else 0,
                                "replay_unique": len(replay_ids),
                                "overlap": len(replay_ids & frozen_ids),
                                "fidelity": round(len(replay_ids & frozen_ids) / len(frozen_ids), 3)
                                if frozen_ids
                                else 0.0,
                                "gold_store_chunks": len(gold_store_ids),
                                "gold_scopes": gold_scope_n,
                                "gold_in_frozen": bool(gold_store_ids & frozen_ids),
                                "gold_in_replay": gold_in_replay,
                                "gold_in_keyword": gold_in_keyword,
                                "gold_keyword_rank": kw_rank,
                                "keyword_calls": len(kw_captured),
                                "keyword_n": len(kw_ids),
                                "keyword_limit_max": max(
                                    (call["limit"] or 0 for call in kw_captured), default=0
                                ),
                                "death": death,
                                "big_total": big_total,
                                "gold_in_big": gold_in_big,
                                "admission": admission_records[0] if admission_records else None,
                                "diagnostics": {
                                    key: value
                                    for key, value in (bundle_data.get("diagnostics") or {}).items()
                                    if isinstance(value, int)
                                    and (key.startswith("keyword_chunks_") or "dropped_by" in key)
                                },
                                "budget_match": bool(captured)
                                and captured[0]["token_budget"] == kwargs["token_budget"],
                                "mrc_match": bool(captured)
                                and captured[0]["max_rendered_chars"]
                                == kwargs["max_rendered_chars"],
                                "scope_mixed": scope_mixed,
                                "scope_source": scope_source,
                                "scope_mode": args.scope_set,
                                "scopes_truncated": scopes_truncated,
                                "scope_missing": scope is None,
                                "selected_n": len(bundle_data.get("items") or []),
                            }
                        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    def group_summary(group_rows: list[dict]) -> dict:
        fidelities = sorted(row["fidelity"] for row in group_rows)
        diag_totals: collections.Counter[str] = collections.Counter()
        for row in group_rows:
            diag_totals.update(row["diagnostics"] or {})
        return {
            "cases": len(group_rows),
            "status": dict(collections.Counter(str(row["status"]) for row in group_rows)),
            "pack_calls_gt0": sum(1 for row in group_rows if row["pack_calls"] > 0),
            "median_fidelity": fidelities[len(fidelities) // 2] if fidelities else None,
            "min_fidelity": fidelities[0] if fidelities else None,
            "budget_match": sum(1 for row in group_rows if row["budget_match"]),
            "mrc_match": sum(1 for row in group_rows if row["mrc_match"]),
            "gold_store_chunks_gt0": sum(1 for row in group_rows if row["gold_store_chunks"] > 0),
            "gold_multi_scope": sum(1 for row in group_rows if row["gold_scopes"] > 1),
            "gold_in_frozen": sum(1 for row in group_rows if row["gold_in_frozen"]),
            "gold_in_replay": sum(1 for row in group_rows if row["gold_in_replay"]),
            "gold_in_keyword": sum(1 for row in group_rows if row["gold_in_keyword"]),
            "gold_in_biglimit": sum(1 for row in group_rows if row["gold_in_big"]),
            "biglimit_errors": sum(1 for row in group_rows if row["big_total"] < 0),
            "admit_reasons": dict(
                collections.Counter(
                    row["admission"]["reason"] for row in group_rows if row["admission"] is not None
                )
            ),
            "diag_totals": {key: total for key, total in sorted(diag_totals.items()) if total > 0},
            "death": dict(collections.Counter(row["death"] for row in group_rows)),
            "median_gold_keyword_rank": (
                statistics.median(
                    row["gold_keyword_rank"]
                    for row in group_rows
                    if row["gold_keyword_rank"] is not None
                )
                if any(row["gold_keyword_rank"] is not None for row in group_rows)
                else None
            ),
            "median_keyword_n": statistics.median(row["keyword_n"] for row in group_rows)
            if group_rows
            else None,
            "scope_source": dict(
                collections.Counter(str(row["scope_source"]) for row in group_rows)
            ),
            "scope_mixed": sum(1 for row in group_rows if row["scope_mixed"]),
            "scope_missing": sum(1 for row in group_rows if row["scope_missing"]),
            "median_replay_n": statistics.median(row["replay_n"] for row in group_rows)
            if group_rows
            else None,
            "median_frozen_n": statistics.median(row["frozen_n"] for row in group_rows)
            if group_rows
            else None,
        }

    target_rows = [row for row in rows if row["sub"] == "absent_not_retrieved"]
    control_rows = [row for row in rows if row["sub"] is None and row["bucket"] == "in_rendered"]
    other_rows = [row for row in rows if row["sub"] not in ("absent_not_retrieved", None)] + [
        row for row in rows if row["sub"] is None and row["bucket"] != "in_rendered"
    ]
    print(
        json.dumps(
            {
                "set_dir": args.set_dir,
                "out": str(args.out),
                "knobs": {
                    "max_facts": args.max_facts,
                    "max_chunks": args.max_chunks,
                    "scope_set": args.scope_set,
                },
                "biglimit_error_kinds": dict(biglimit_error_kinds),
                "not_retrieved": group_summary(target_rows),
                "controls": group_summary(control_rows),
                "other": group_summary(other_rows),
                "worst_fidelity_cids": sorted(row["cid"] for row in rows if row["fidelity"] < 0.5),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
