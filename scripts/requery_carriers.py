"""Counters: gold-token coverage added by re-query carriers (Letta-style re-query).

Cheap signal experiment for the scattered class: instead of picking carriers by
QUERY-token overlap (measured dead: 7.3% mean gold coverage added), simulate a
second retrieval hop whose terms come from the FIRST-hop fragments:

1. first hop  - store chunks ranked by naive query-token overlap, top FIRST_HOP;
2. re-query   - distinctive tokens (and optional bigrams) of the pool that are
                absent from the query, scored by pool_df / store_df;
3. carriers   - store chunks ranked by overlap with the re-query term set,
                top K_CAP (chunk text already fully present in the rendered
                pack is skipped);
4. metric     - gold-token coverage of the carrier tail beyond the base render,
                same metric as gold-coverage-carriers.py (query 7.3% / oracle 98.6%).

Prints ONLY counters and opaque case hashes - no question, gold or chunk text.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import pathlib
import pickle

BASE = pathlib.Path("/home/iliya/work/recall-20261021")
ROOT = pathlib.Path("/srv/workers/jobs/discord-meeting/memory-quality-20261010")

spec = importlib.util.spec_from_file_location("probe", BASE / "answer_recall_http_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

SET_DIRS = [("balanced-frozen-20261011", "balanced"), ("heldout48-frozen-20261011", "heldout48")]
FIRST_HOP = 360
TERM_CAPS = (24, 48)
K_CAP = 6


def load(name: str) -> dict[str, dict]:
    path = BASE / name
    return {
        json.loads(line)["cid"]: json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def bigrams(tokens: list[str]) -> list[str]:
    return [f"{a} {b}" for a, b in zip(tokens, tokens[1:], strict=False)]


def distinctiveness(
    token: str,
    pool_df: "collections.Counter[str]",
    store_df: "collections.Counter[str]",
) -> float:
    return pool_df[token] / store_df[token]


def carrier_tail(
    terms: set[str],
    chunk_tokens: dict[str, set[str]],
    rows_data: dict[str, dict],
    rendered_text: str,
    rendered_tokens: set[str],
    gold_tokens: set[str],
) -> tuple[float, float]:
    cands = sorted(
        ((len(terms & chunk_tokens[chunk_id]), chunk_id) for chunk_id in chunk_tokens),
        key=lambda pair: (-pair[0], pair[1]),
    )
    picked: list[str] = []
    for hit, chunk_id in cands:
        if hit == 0:
            break
        text = rows_data[chunk_id]["text"]
        if text.strip() and text.strip() in rendered_text:
            continue
        picked.append(chunk_id)
        if len(picked) >= K_CAP:
            break
    tail_tokens: set[str] = set()
    for chunk_id in picked:
        tail_tokens |= chunk_tokens[chunk_id]
    added = (tail_tokens - rendered_tokens) & gold_tokens
    coverage = len(added) / len(gold_tokens)
    full = len((tail_tokens | rendered_tokens) & gold_tokens) == len(gold_tokens)
    return coverage, (1.0 if full else 0.0)


def main() -> int:
    base_rows = load("scatter-base.jsonl")
    ladder = {
        tag: [
            json.loads(line)["cid"]
            for line in (BASE / f"ladder-{tag}.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("bucket") == "gold_absent_from_store"
        ]
        for _sd, tag in SET_DIRS
    }

    results: dict[str, dict] = collections.defaultdict(dict)
    stats = collections.Counter()

    for set_dir, tag in SET_DIRS:
        cids = [c for c in ladder[tag] if c in base_rows]
        inputs = ROOT / set_dir / "frozen-private"
        pickle_by_cid = {probe._cid(p): p for p in inputs.rglob("*.pickle")}
        by_store: dict[pathlib.Path, list[str]] = collections.defaultdict(list)
        for cid in cids:
            p = pickle_by_cid.get(cid)
            if p is None:
                stats["missing_pickle"] += 1
                continue
            db = ROOT / set_dir / f"{p.parent.name}-exact-pack-state" / "memory.db"
            by_store[db].append(cid)

        for db_path, store_cids in sorted(by_store.items()):
            rows_data = probe._store_rows(db_path)
            chunk_tokens: dict[str, set[str]] = {}
            store_df: collections.Counter = collections.Counter()
            store_bg_df: collections.Counter = collections.Counter()
            for chunk_id, row in rows_data.items():
                toks_list = probe._tokens(row["text"])
                toks = set(toks_list)
                chunk_tokens[chunk_id] = toks
                store_df.update(toks)
                store_bg_df.update(set(bigrams(toks_list)))

            for cid in sorted(store_cids):
                b = base_rows[cid]
                gt = set(probe._tokens(b["gold"]))
                rendered_tokens = set(probe._tokens(b["context"]))
                data = pickle.loads(pickle_by_cid[cid].read_bytes())
                qtoks = set(probe._tokens(data["kwargs"]["query"]))
                if not gt:
                    stats["no_gold_tokens"] += 1
                    continue

                # first hop: naive query-token overlap ranking
                scored = sorted(
                    ((len(qtoks & toks), chunk_id) for chunk_id, toks in chunk_tokens.items()),
                    key=lambda pair: (-pair[0], pair[1]),
                )
                pool = [chunk_id for hit, chunk_id in scored[:FIRST_HOP] if hit > 0]
                pool_df: collections.Counter = collections.Counter()
                pool_unigrams: dict[str, list[str]] = {}
                pool_bg_df: collections.Counter = collections.Counter()
                for chunk_id in pool:
                    toks_list = probe._tokens(rows_data[chunk_id]["text"])
                    pool_unigrams[chunk_id] = toks_list
                    pool_df.update(set(toks_list))
                    pool_bg_df.update(set(bigrams(toks_list)))

                # distinctive re-query terms: high pool concentration, absent from query
                uni_terms = sorted(
                    (t for t in pool_df if t not in qtoks),
                    key=lambda t: (
                        -distinctiveness(t, pool_df, store_df),
                        -pool_df[t],
                        t,
                    ),
                )

                for cap in TERM_CAPS:
                    uni = set(uni_terms[:cap])
                    coverage, full = carrier_tail(
                        uni, chunk_tokens, rows_data, b["context"], rendered_tokens, gt
                    )
                    results[f"uni{cap}"][cid] = (coverage, full)

                    # unigrams + bigrams sharing the cap budget
                    bi_scores: dict[str, float] = {}
                    for bg, pdf in pool_bg_df.items():
                        parts = bg.split(" ")
                        if all(part in qtoks for part in parts):
                            continue
                        bi_scores[bg] = pdf / store_bg_df[bg]
                    bi_sorted = sorted(bi_scores, key=lambda bg: (-bi_scores[bg], bg))
                    mixed: list[str] = []
                    iu, ib = 0, 0
                    while len(mixed) < cap:
                        take_bi = ib < len(bi_sorted) and (
                            iu >= len(uni_terms)
                            or bi_scores[bi_sorted[ib]]
                            >= distinctiveness(uni_terms[iu], pool_df, store_df)
                        )
                        if take_bi:
                            mixed.append(bi_sorted[ib])
                            ib += 1
                        else:
                            mixed.append(uni_terms[iu])
                            iu += 1
                        if iu >= len(uni_terms) and ib >= len(bi_sorted):
                            break
                    cov_b, full_b = carrier_tail(
                        set(mixed), chunk_tokens, rows_data, b["context"], rendered_tokens, gt
                    )
                    results[f"unibi{cap}"][cid] = (cov_b, full_b)
                stats["cases"] += 1

    out_path = BASE / "requery-carriers.jsonl"
    with out_path.open("w", encoding="utf-8") as handle:
        for variant, per_case in sorted(results.items()):
            for cid, (coverage, full) in sorted(per_case.items()):
                handle.write(
                    json.dumps(
                        {"variant": variant, "cid": cid, "cov": round(coverage, 4), "full": full}
                    )
                    + "\n"
                )
    out_path.chmod(0o600)

    summary = {}
    for variant, per_case in sorted(results.items()):
        covs = [coverage for coverage, _ in per_case.values()]
        summary[variant] = {
            "n": len(covs),
            "mean_carrier_gold_cov": round(sum(covs) / len(covs), 3),
            "cases_zero_added": sum(1 for coverage in covs if coverage == 0),
            "cases_full_coverage": sum(1 for _, full in per_case.values() if full),
        }
    print(json.dumps({"stats": dict(stats), "variants": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
