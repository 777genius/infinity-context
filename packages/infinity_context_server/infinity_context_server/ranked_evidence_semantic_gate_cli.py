"""Local-only CLI for the ranked-evidence semantic publication gate."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from infinity_context_server.ranked_evidence_semantic_gate import (
    run_ranked_evidence_semantic_gate,
)

_DEFAULT_CUTOFFS = (10, 20, 50, 200)
_INTERNAL_FAILURE = {
    "ok": False,
    "schema_version": "ranked-evidence-semantic-gate.v1",
    "status": "internal_failure",
}
_INVALID_ARGUMENTS = {
    "ok": False,
    "schema_version": "ranked-evidence-semantic-gate.v1",
    "status": "invalid_arguments",
}
_INTERRUPTED = {
    "ok": False,
    "schema_version": "ranked-evidence-semantic-gate.v1",
    "status": "interrupted",
}


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        _emit(_INVALID_ARGUMENTS)
        self.exit(2)


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description=(
            "Run the provider-free ranked-evidence semantic gate against a local in-process server."
        )
    )
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument(
        "--case-id",
        action="append",
        required=True,
        help="Selected benchmark case id. Repeat for multiple cases.",
    )
    parser.add_argument(
        "--cutoff",
        action="append",
        type=int,
        default=None,
        help="Ranked evidence cutoff. Repeat to replace the default cutoffs.",
    )
    parser.add_argument("--reference-cutoff", type=int, default=200)
    parser.add_argument("--token-budget", type=int, default=25_600)
    parser.add_argument("--max-facts", type=int, default=200)
    parser.add_argument("--max-chunks", type=int, default=200)
    parser.add_argument(
        "--locomo-ingest-mode",
        choices=("official-turns", "rich-documents"),
        default="official-turns",
    )
    parser.add_argument(
        "--local-database-url",
        default=None,
        help="Optional local SQLite URL. The value is never included in output.",
    )
    parser.add_argument("--report-out", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cutoffs = tuple(args.cutoff) if args.cutoff is not None else _DEFAULT_CUTOFFS
    try:
        result = run_ranked_evidence_semantic_gate(
            dataset_path=args.dataset,
            benchmark=args.benchmark,
            case_ids=tuple(args.case_id),
            cutoffs=cutoffs,
            reference_cutoff=args.reference_cutoff,
            token_budget=args.token_budget,
            max_facts=args.max_facts,
            max_chunks=args.max_chunks,
            locomo_ingest_mode=args.locomo_ingest_mode,
            local_database_url=args.local_database_url,
            report_out=args.report_out,
        )
    except KeyboardInterrupt:
        _emit(_INTERRUPTED)
        return 130
    except Exception:
        _emit(_INTERNAL_FAILURE)
        return 1

    payload = _safe_payload(result, database_url=args.local_database_url)
    _emit(payload)
    return 0 if payload.get("ok") is True else 1


def _safe_payload(
    result: object,
    *,
    database_url: str | None,
) -> Mapping[str, object]:
    if not isinstance(result, Mapping):
        return _INTERNAL_FAILURE
    payload = dict(result)
    try:
        rendered = _render(payload)
    except (TypeError, ValueError):
        return _INTERNAL_FAILURE
    if database_url and database_url in rendered:
        return _INTERNAL_FAILURE
    return payload


def _render(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _emit(payload: Mapping[str, object]) -> None:
    print(_render(payload))


if __name__ == "__main__":
    raise SystemExit(main())
