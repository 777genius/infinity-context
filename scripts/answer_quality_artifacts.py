"""Private, single-writer artifacts for the Linux paired-answer measurement CLI."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pathlib
import stat
import tempfile
from collections.abc import Iterator

RESOLVED_VERDICTS = frozenset({"correct", "incorrect", "missing"})
VERDICTS = RESOLVED_VERDICTS | {"unparsed", "call_failed"}
_RECORD_KEYS = frozenset(
    {
        "run_sha256",
        "cid",
        "qtype",
        "arm",
        "coverage_complete",
        "verdict",
        "candidate",
        "candidate_sha",
        "candidate_chars",
        "call_failures",
        "answer_ms",
        "judge_ms",
    }
)


class ArtifactError(ValueError):
    """A safe diagnostic containing no private input or model output."""


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactError("duplicate_json_key")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise ArtifactError("nonfinite_json_number")


def strict_json(raw: str | bytes) -> object:
    return json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def load_pack(path: pathlib.Path, *, limit: int) -> list[dict]:
    if limit < 0:
        raise ArtifactError("limit_must_be_nonnegative")
    rows = []
    seen = set()
    for number, raw in enumerate(path.read_bytes().splitlines(), start=1):
        try:
            row = strict_json(raw)
        except (ValueError, UnicodeError) as exc:
            raise ArtifactError(f"invalid_pack_json_line_{number}") from exc
        if (
            not isinstance(row, dict)
            or any(
                not isinstance(row.get(key), str)
                for key in ("cid", "question", "gold", "context", "qtype")
            )
            or type(row.get("coverage_complete")) is not bool
        ):
            raise ArtifactError(f"invalid_pack_schema_line_{number}")
        if not row["cid"] or row["cid"] in seen:
            raise ArtifactError(f"invalid_or_duplicate_case_id_line_{number}")
        seen.add(row["cid"])
        rows.append(row)
    rows.sort(key=lambda row: row["cid"])
    selected = rows[:limit] if limit else rows
    if not selected:
        raise ArtifactError("empty_case_selection")
    return selected


def run_manifest(rows: list[dict], configuration: dict, evaluator: pathlib.Path) -> dict:
    identity = {
        "schema_version": 2,
        "selected_input_sha256": hashlib.sha256(canonical_json(rows)).hexdigest(),
        "case_count": len(rows),
        "configuration": configuration,
        "source_sha256": {
            evaluator.name: hashlib.sha256(evaluator.read_bytes()).hexdigest(),
            pathlib.Path(__file__).name: hashlib.sha256(
                pathlib.Path(__file__).read_bytes()
            ).hexdigest(),
        },
    }
    return {**identity, "run_sha256": hashlib.sha256(canonical_json(identity)).hexdigest()}


def _check_path(path: pathlib.Path, *, directory: bool = False) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not valid_type or info.st_uid != os.getuid():
        raise ArtifactError("unsafe_artifact_path")
    path.chmod(0o700 if directory else 0o600)


def _open_private(path: pathlib.Path, *, append: bool = False) -> int:
    _check_path(path)
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    if append:
        flags |= os.O_APPEND
    descriptor = os.open(path, flags, 0o600)
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        os.close(descriptor)
        raise ArtifactError("unsafe_artifact_file")
    os.fchmod(descriptor, 0o600)
    return descriptor


@contextlib.contextmanager
def private_run_directory(path: pathlib.Path) -> Iterator[None]:
    if os.name != "posix":
        raise ArtifactError("private_run_requires_posix_locking")
    import fcntl

    _check_path(path, directory=True)
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    _check_path(path, directory=True)
    descriptor = _open_private(path / ".run.lock")
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ArtifactError("run_directory_busy") from exc
        for name in ("manifest.json", "results.jsonl", "aggregate.json"):
            _check_path(path / name)
        yield
    finally:
        os.close(descriptor)


def atomic_json(path: pathlib.Path, value: object) -> None:
    _check_path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".publish-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        pathlib.Path(temporary).unlink(missing_ok=True)


def bind_manifest(directory: pathlib.Path, expected: dict) -> None:
    path = directory / "manifest.json"
    if path.exists():
        try:
            actual = strict_json(path.read_bytes())
        except (ValueError, UnicodeError) as exc:
            raise ArtifactError("invalid_run_manifest") from exc
        if actual != expected:
            raise ArtifactError("incompatible_run_identity_use_new_output_directory")
        return
    for name in ("results.jsonl", "aggregate.json"):
        other = directory / name
        if other.exists() and other.stat().st_size:
            raise ArtifactError("unbound_historical_results_use_new_output_directory")
    atomic_json(path, expected)


def validate_record(record: object, rows: dict[str, dict], run_sha256: str) -> dict:
    if not isinstance(record, dict) or set(record) != _RECORD_KEYS:
        raise ArtifactError("invalid_result_schema")
    cid = record["cid"]
    if not isinstance(cid, str) or cid not in rows:
        raise ArtifactError("unknown_result_case")
    row = rows[cid]
    if record["run_sha256"] != run_sha256 or record["arm"] not in ("with", "without"):
        raise ArtifactError("invalid_result_identity")
    if record["qtype"] != row["qtype"] or type(record["coverage_complete"]) is not bool:
        raise ArtifactError("invalid_result_metadata")
    if record["coverage_complete"] != row["coverage_complete"]:
        raise ArtifactError("invalid_result_metadata")
    if not isinstance(record["verdict"], str) or record["verdict"] not in VERDICTS:
        raise ArtifactError("invalid_result_verdict")
    candidate = record["candidate"]
    if not isinstance(candidate, str):
        raise ArtifactError("invalid_private_candidate")
    if any(
        type(record[key]) is not int or record[key] < 0
        for key in ("candidate_chars", "call_failures", "answer_ms", "judge_ms")
    ):
        raise ArtifactError("invalid_result_counter")
    digest = hashlib.sha256(candidate.encode()).hexdigest()[:12] if candidate.strip() else ""
    if record["candidate_sha"] != digest or record["candidate_chars"] != len(candidate):
        raise ArtifactError("invalid_private_candidate_identity")
    return record


def read_results(path: pathlib.Path, rows: list[dict], run_sha256: str) -> list[dict]:
    """Validate first; repair only an unterminated JSON/UTF-8 fragment under the lock."""
    if not path.exists():
        return []
    _check_path(path)
    content = path.read_bytes()
    lines = content.splitlines(keepends=True)
    by_cid = {row["cid"]: row for row in rows}
    records = []
    seen = set()
    offset = 0
    truncate_at = None
    append_delimiter = False
    for index, line in enumerate(lines):
        terminal_fragment = index == len(lines) - 1 and not line.endswith(b"\n")
        try:
            record = strict_json(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            if terminal_fragment and line.strip():
                truncate_at = offset
                break
            raise ArtifactError(f"corrupt_result_json_line_{index + 1}") from exc
        except ArtifactError as exc:
            raise ArtifactError(f"corrupt_result_json_line_{index + 1}") from exc
        try:
            validate_record(record, by_cid, run_sha256)
        except ArtifactError as exc:
            raise ArtifactError(f"invalid_result_line_{index + 1}") from exc
        key = (record["cid"], record["arm"])
        if key in seen:
            raise ArtifactError(f"duplicate_result_line_{index + 1}")
        seen.add(key)
        records.append(record)
        offset += len(line)
        append_delimiter = terminal_fragment
    if truncate_at is not None or append_delimiter:
        with os.fdopen(_open_private(path), "r+b") as stream:
            if truncate_at is not None:
                stream.truncate(truncate_at)
            else:
                stream.seek(0, os.SEEK_END)
                stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    return records


def append_result(path: pathlib.Path, record: dict) -> None:
    with os.fdopen(_open_private(path, append=True), "ab") as stream:
        stream.write(canonical_json(record) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def _fraction(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "fraction": numerator / denominator if denominator else None,
    }


def public_counts(rows: list[dict], records: list[dict]) -> dict:
    """Only this explicit projection of private inputs is publishable."""
    pairs = {row["cid"]: {} for row in rows}
    output = {"cases": len(rows)}
    arm_metrics = {}
    for record in records:
        pairs[record["cid"]][record["arm"]] = record["verdict"]
    for arm in ("with", "without"):
        counts = dict.fromkeys(sorted(VERDICTS), 0)
        for record in records:
            if record["arm"] == arm:
                counts[record["verdict"]] += 1
        observed = sum(counts.values())
        resolved = sum(counts[key] for key in RESOLVED_VERDICTS)
        output[f"{arm}_counts"] = counts
        arm_metrics[arm] = {
            "expected": len(rows),
            "observed": observed,
            "resolved": resolved,
            "unresolved": observed - resolved,
            "absent": len(rows) - observed,
            "correct_per_expected": _fraction(counts["correct"], len(rows)),
            "correct_per_resolved": _fraction(counts["correct"], resolved),
            "incorrect_per_resolved": _fraction(counts["incorrect"], resolved),
        }
    complete = [pair for pair in pairs.values() if len(pair) == 2]
    resolved_pairs = [pair for pair in complete if set(pair.values()) <= RESOLVED_VERDICTS]
    paired = dict.fromkeys(("memory_helped", "memory_hurt", "both_correct", "neither"), 0)
    for pair in resolved_pairs:
        flags = (pair["with"] == "correct", pair["without"] == "correct")
        key = {
            (True, False): "memory_helped",
            (False, True): "memory_hurt",
            (True, True): "both_correct",
            (False, False): "neither",
        }[flags]
        paired[key] += 1
    output.update(
        {
            "arm_metrics": arm_metrics,
            "paired": paired,
            "pair_counts": {
                "expected": len(rows),
                "complete": len(complete),
                "resolved": len(resolved_pairs),
                "incomplete": len(rows) - len(complete),
                "complete_but_unresolved": len(complete) - len(resolved_pairs),
            },
            "status": (
                "incomplete"
                if len(complete) < len(rows)
                else "complete_with_unresolved"
                if len(resolved_pairs) < len(complete)
                else "complete"
            ),
        }
    )
    output["by_qtype"] = {
        hashlib.sha256(qtype.encode()).hexdigest(): _group_counts(
            [row for row in rows if row["qtype"] == qtype],
            records,
        )
        for qtype in sorted({row["qtype"] for row in rows})
    }
    output["by_coverage"] = {
        str(flag): _group_counts([row for row in rows if row["coverage_complete"] is flag], records)
        for flag in (True, False)
    }
    return output


def _group_counts(rows: list[dict], records: list[dict]) -> dict:
    wanted = {row["cid"] for row in rows}
    group = [record for record in records if record["cid"] in wanted]
    return {
        "cases": len(rows),
        **{
            f"{arm}_{suffix}": sum(
                record["arm"] == arm and record["verdict"] in verdicts for record in group
            )
            for arm in ("with", "without")
            for suffix, verdicts in (("correct", {"correct"}), ("resolved", RESOLVED_VERDICTS))
        },
    }
