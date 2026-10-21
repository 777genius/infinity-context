"""Re-render frozen pack contexts through /v1/context on a store copy.

Reads an existing pack jsonl (cid/qtype/question/gold plus the rendered
context captured earlier), replays each case's request against a temp copy
of the seeded memory.db — scope from the frozen candidate rows with a
gold-row fallback, token_budget from the frozen kwargs — and writes a pack
jsonl whose context/item_count/ctx_chars are refreshed under the currently
loaded product code. Rows without a frozen pickle pass through unchanged;
empty rendered contexts overwrite the stale context (empty is a valid
result of the code under test), while failed replays keep the stale row
and gain a `repack_error` marker so downstream scoring can skip them.

Prints ONLY counters — no question, gold answer or context text ever
reaches stdout.
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
import tempfile
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


def _store_rows(db_path: pathlib.Path) -> dict[str, tuple]:
    import sqlite3

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT id, space_id, memory_scope_id, thread_id, text FROM memory_chunks"
        )
        return {row[0]: (row[1], row[2], row[3], row[4]) for row in rows.fetchall()}
    finally:
        conn.close()


def _majority_scope(item_ids: set[str], store_rows: dict[str, tuple]) -> tuple | None:
    seen = collections.Counter(
        store_rows[item_id][:3] for item_id in item_ids if item_id in store_rows
    )
    if not seen:
        return None
    return seen.most_common(1)[0][0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True, type=pathlib.Path)
    parser.add_argument("--inputs-root", required=True, type=pathlib.Path)
    parser.add_argument("--store-root", required=True, type=pathlib.Path)
    parser.add_argument("--set-dir", required=True)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.pack.read_text(encoding="utf-8").splitlines()]
    rows_by_cid = {row["cid"]: row for row in rows}

    pickles: dict[str, pathlib.Path] = {}
    for path in sorted((args.inputs_root / args.set_dir / "frozen-private").rglob("*.pickle")):
        cid = _cid(path)
        if cid in rows_by_cid:
            pickles[cid] = path

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

    from fastapi.testclient import TestClient
    from infinity_context_server.config import DeployProfile, Settings
    from infinity_context_server.main import create_app

    counters: collections.Counter[str] = collections.Counter()
    refreshed: dict[str, dict] = {}
    for db_path, cids in sorted(by_store.items()):
        store_rows = _store_rows(db_path)
        with tempfile.TemporaryDirectory(prefix="repack-") as tmp:
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
                    if scope is None:
                        gold = rows_by_cid[cid]["gold"]
                        gold_ids = {
                            item_id
                            for item_id, row in store_rows.items()
                            if _contains(gold, row[3])
                        }
                        scope = _majority_scope(gold_ids, store_rows)
                    body: dict = {"query": kwargs["query"], "token_budget": kwargs["token_budget"]}
                    if scope is not None:
                        body.update(
                            space_id=scope[0], memory_scope_ids=[scope[1]], thread_id=scope[2]
                        )
                    response = client.post(
                        "/v1/context",
                        json=body,
                        headers={"Authorization": "Bearer diagnostic-local-only"},
                    )
                    payload = (
                        response.json()
                        if response.headers.get("content-type", "").startswith("application/json")
                        else {}
                    )
                    bundle = payload.get("data") or {}
                    rendered = str(bundle.get("rendered_text") or "")
                    if response.status_code != 200:
                        counters[f"http_{response.status_code}"] += 1
                        refreshed[cid] = {"repack_error": f"http_{response.status_code}"}
                        continue
                    refreshed[cid] = {
                        "context": rendered,
                        "ctx_chars": len(rendered),
                        "item_count": len(bundle.get("items") or []),
                    }
                    if not rendered:
                        counters["empty_rendered"] += 1
                        continue
                    counters["replayed"] += 1
                    if _contains(rows_by_cid[cid]["gold"], rendered):
                        counters["gold_in_rendered"] += 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in rows:
            update = refreshed.get(row["cid"])
            if update is not None and "repack_error" in update:
                counters["replay_failed_stale"] += 1
                row = {**row, **update}
            elif update is not None:
                row = {**row, **update}
            else:
                counters["passthrough"] += 1
            handle.write(json.dumps(row) + "\n")

    print(
        json.dumps(
            {
                "set_dir": args.set_dir,
                "pack_rows": len(rows),
                "pickles": len(pickles),
                "counters": dict(counters),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
