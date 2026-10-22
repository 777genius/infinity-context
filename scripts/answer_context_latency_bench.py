"""Replay frozen queries through /v1/context and measure per-phase latency.

Same replay shape as answer_repack_contexts.py (frozen pickles -> temp copy
of the seeded memory.db -> provider-free TEST-profile app -> POST
/v1/context), instrumented with perf_counter wrappers around the keyword
lane, the admission gate, the snippet renderer and ContextPacker.pack.

Prints ONLY timing counters and opaque case hashes — no question, gold
answer or context text ever reaches stdout.
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
import time
from unittest import mock


def _cid(path: pathlib.Path) -> str:
    return hashlib.sha256(path.stem.encode()).hexdigest()[:12]


def _majority_scope(frozen_ids: set[str], store_rows: dict) -> str | None:
    counts: collections.Counter[str] = collections.Counter()
    for item_id in frozen_ids:
        row = store_rows.get(item_id)
        if row is None:
            continue
        space, scope, thread = row[0], row[1], row[2]
        counts[(space, scope, thread)] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs-root", type=pathlib.Path, required=True)
    parser.add_argument("--set-dir", required=True)
    parser.add_argument("--store-root", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    args = parser.parse_args()

    pickles: dict[str, pathlib.Path] = {}
    inputs = args.inputs_root / args.set_dir / "frozen-private"
    for path in sorted(inputs.rglob("*.pickle")):
        pickles[_cid(path)] = path
    if args.limit:
        pickles = dict(sorted(pickles.items())[: args.limit])

    by_store: dict[pathlib.Path, list[str]] = {}
    for cid, path in pickles.items():
        db_path = (
            args.store_root / args.set_dir / f"{path.parent.name}-exact-pack-state" / "memory.db"
        )
        by_store.setdefault(db_path, []).append(cid)

    missing_stores = sorted(str(path) for path in by_store if not path.is_file())
    if missing_stores:
        print(json.dumps({"missing_stores": missing_stores, "pickles": len(pickles)}, indent=2))
        return 2

    import infinity_context_core.application.context_collectors as collectors_mod
    import infinity_context_core.application.use_cases.build_context as bc_module
    from fastapi.testclient import TestClient
    from infinity_context_core.application.context_packer import ContextPacker
    from infinity_context_server.config import DeployProfile, Settings
    from infinity_context_server.main import create_app

    def _store_rows(db_path: pathlib.Path) -> dict[str, tuple]:
        import sqlite3

        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT id, space_id, memory_scope_id, thread_id, text FROM memory_chunks"
            ).fetchall()
        finally:
            conn.close()
        return {row[0]: (row[1], row[2], row[3], row[4]) for row in rows}

    phase_ms: dict[str, float] = collections.defaultdict(float)
    phase_calls: collections.Counter = collections.Counter()

    def timed(name: str, fn):
        def wrapper(*call_args, **call_kwargs):
            start = time.perf_counter()
            try:
                return fn(*call_args, **call_kwargs)
            finally:
                phase_ms[name] += (time.perf_counter() - start) * 1000.0
                phase_calls[name] += 1

        return wrapper

    def atimed(name: str, fn):
        async def wrapper(*call_args, **call_kwargs):
            start = time.perf_counter()
            try:
                return await fn(*call_args, **call_kwargs)
            finally:
                phase_ms[name] += (time.perf_counter() - start) * 1000.0
                phase_calls[name] += 1

        return wrapper

    originals = {
        "pack": ContextPacker.pack,
        "keyword_lane": collectors_mod._keyword_search_chunks,
        "admit": bc_module.admit_keyword_chunk,
        "snippet": collectors_mod.query_focused_snippet,
    }

    cases: list[dict] = []
    with (
        mock.patch.object(ContextPacker, "pack", timed("pack", originals["pack"])),
        mock.patch.object(
            collectors_mod,
            "_keyword_search_chunks",
            atimed("keyword_lane", originals["keyword_lane"]),
        ),
        mock.patch.object(bc_module, "admit_keyword_chunk", timed("admit", originals["admit"])),
        mock.patch.object(
            collectors_mod, "query_focused_snippet", timed("snippet", originals["snippet"])
        ),
    ):
        for db_path, cids in sorted(by_store.items()):
            store_rows = _store_rows(db_path)
            with tempfile.TemporaryDirectory(prefix="latbench-") as tmp:
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
                        scope = _majority_scope(frozen_ids, store_rows)
                        body: dict = {"query": kwargs["query"], "token_budget": kwargs["token_budget"]}
                        if scope is not None:
                            body.update(space_id=scope[0], memory_scope_ids=[scope[1]], thread_id=scope[2])

                        def fire() -> tuple[int, float]:
                            start = time.perf_counter()
                            response = client.post(
                                "/v1/context",
                                json=body,
                                headers={"Authorization": "Bearer diagnostic-local-only"},
                            )
                            return response.status_code, (time.perf_counter() - start) * 1000.0

                        for _ in range(max(1, args.warmup)):
                            fire()
                        totals: list[float] = []
                        status = 0
                        for _ in range(max(1, args.repeat)):
                            status, total_ms = fire()
                            totals.append(total_ms)
                        cases.append(
                            {
                                "cid": cid,
                                "status": status,
                                "total_ms": round(statistics.median(totals), 3),
                                "total_ms_min": round(min(totals), 3),
                                "total_ms_max": round(max(totals), 3),
                            }
                        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in cases:
            handle.write(json.dumps(row) + "\n")

    ok_totals = sorted(row["total_ms"] for row in cases if row["status"] == 200)

    def _pct(values: list[float], q: float) -> float | None:
        if not values:
            return None
        index = min(len(values) - 1, max(0, round(q * (len(values) - 1))))
        return round(values[index], 2)

    print(
        json.dumps(
            {
                "set_dir": args.set_dir,
                "cases": len(cases),
                "http_200": len(ok_totals),
                "repeat": args.repeat,
                "warmup": args.warmup,
                "total_ms": {
                    "p50": _pct(ok_totals, 0.50),
                    "p90": _pct(ok_totals, 0.90),
                    "p95": _pct(ok_totals, 0.95),
                    "mean": round(statistics.fmean(ok_totals), 2) if ok_totals else None,
                },
                "phases_ms_total": {name: round(value, 1) for name, value in sorted(phase_ms.items())},
                "phase_calls": dict(phase_calls),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
