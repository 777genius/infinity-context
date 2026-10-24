"""Build and exercise benchmark, server and bundled wheels without source fallback."""

from __future__ import annotations

import argparse
import dataclasses
import gzip
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import pickle
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import get_origin, get_type_hints


def _run(command: list[str], *, cwd: Path) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"{command!r} failed:\n{result.stdout}\n{result.stderr}")


def _probe(target: Path, mode: str, fixtures: Path) -> None:
    # Invoked with -I -S: only stdlib and this explicit wheel installation exist.
    sys.path.insert(0, str(target))
    from infinity_context_benchmarks import evidence_bundle as evidence
    from infinity_context_benchmarks import retrieval_intent, source_identity

    intent_fixtures = fixtures.parent / "benchmark_retrieval_intent"
    intent_contract = json.loads((intent_fixtures / "contract.json").read_text())
    raw = gzip.decompress((intent_fixtures / "cases.json.gz").read_bytes())
    assert hashlib.sha256(raw).hexdigest() == intent_contract["cases_sha256"]
    replay = runpy.run_path(
        str(Path(__file__).with_name("benchmark_policy_contract_inventory.py"))
    )["replay_intent_case"]
    intent_cases = json.loads(raw)
    for case in intent_cases:
        assert replay(case, retrieval_intent) == {
            key: case[key] for key in ("intent", "diagnostics", "profile")
        }
    assert get_type_hints(retrieval_intent.RetrievalIntent)
    if mode != "standalone":
        import base64

        from infinity_context_server import memory_comparison_intent as legacy_intent
        from infinity_context_server.memory_comparison_rerank import query_retrieval_intent

        for name, encoded in intent_contract["legacy_reference_pickles"].items():
            assert pickle.loads(base64.b64decode(encoded)) is getattr(legacy_intent, name)
        for name, encoded in intent_contract["legacy_pickles"].items():
            value = pickle.loads(base64.b64decode(encoded))
            assert type(value) is getattr(retrieval_intent, name)
            assert pickle.loads(pickle.dumps(value)) == value
        for case in intent_cases:
            result = query_retrieval_intent(
                SimpleNamespace(
                    question=case["intent"]["question"], metadata={"category": case["category"]}
                )
            )
            actual = {
                "intent": dataclasses.asdict(result),
                "diagnostics": result.to_diagnostics(),
                "profile": result.to_query_profile(),
            }
            assert json.loads(json.dumps(actual)) == {
                key: case[key] for key in ("intent", "diagnostics", "profile")
            }

    annotations = get_type_hints(evidence.EvidenceBundleCandidate)
    assert get_type_hints(evidence.PlannedEvidenceItem)["candidate"] is (
        evidence.EvidenceBundleCandidate
    )
    fixture = json.loads((fixtures / "case_000.json").read_text())
    candidates = tuple(
        evidence.EvidenceBundleCandidate(
            **{
                name: tuple(value) if get_origin(annotations[name]) is tuple else value
                for name, value in payload.items()
            }
        )
        for payload in fixture["input"]["candidates"]
    )
    item = evidence.PlannedEvidenceItem(candidates[0], "primary", ("smoke",))
    for value in (candidates[0], item):
        assert pickle.loads(pickle.dumps(value)) == value
    assert (
        evidence.role_for_candidate(
            candidates[0], primary=candidates[0], case_group="single", required_roles=()
        )
        == "primary"
    )
    assert (
        evidence.bundle_quality_diagnostics((item,), missing_required_roles=())[
            "selected_item_count"
        ]
        == 1
    )
    assert source_identity.safe_source_label_for_output("provider:private-token") is None
    assert source_identity.safe_source_label_for_output("raw_turn") == "raw_turn"
    if mode == "standalone":
        assert importlib.util.find_spec("infinity_context_server") is None
        assert importlib.util.find_spec("infinity_context_adapters") is None
    else:
        from infinity_context_server import memory_comparison_bundle_planner as planner

        assert planner.EvidenceBundleCandidate is evidence.EvidenceBundleCandidate
        assert planner.PlannedEvidenceItem is evidence.PlannedEvidenceItem
        contract = json.loads((fixtures / "contract.json").read_text())
        import base64

        for name, encoded in contract["legacy_pickles"].items():
            assert type(pickle.loads(base64.b64decode(encoded))) is getattr(planner, name)
        result = planner.EvidenceBundlePlanner(**fixture["input"]["config"]).plan(
            candidates,
            case_group=fixture["input"]["case_group"],
            required_roles=tuple(fixture["input"]["required_roles"]),
        )
        actual = {
            "items": [selected.to_payload() for selected in result.items],
            "diagnostics": result.to_diagnostics(),
        }
        assert json.dumps(actual) == json.dumps(fixture["expected"])
    requirements = {}
    if mode != "bundle":
        names = ["infinity-context-benchmarks"]
        if mode == "server":
            names.append("infinity-context-server")
        requirements = {
            name: importlib.metadata.distribution(name).requires or [] for name in names
        }
        assert "infinity-context-core==0.1.0" in requirements["infinity-context-benchmarks"]
        if mode == "server":
            assert "infinity-context-benchmarks==0.1.0" in requirements["infinity-context-server"]
    origins = {
        name: str(Path(module.__file__).resolve())
        for name, module in sys.modules.items()
        if name.startswith("infinity_context_") and getattr(module, "__file__", None)
    }
    assert origins and all(Path(origin).is_relative_to(target) for origin in origins.values())
    assert dataclasses.is_dataclass(evidence.EvidenceBundleCandidate)
    print(json.dumps({"mode": mode, "origins": origins, "requirements": requirements}))


def _ignored(_directory: str, names: list[str]) -> set[str]:
    excluded = {"__pycache__", "node_modules", "build", "dist"}
    return {name for name in names if name.startswith(".") or name in excluded}


def _build_and_smoke(output: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output.mkdir(parents=True, exist_ok=True)
    stage = output / "source"
    wheels = output / "wheels"
    for directory in (stage, wheels):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(root / name, stage / name)
    shutil.copytree(root / "packages", stage / "packages", ignore=_ignored)
    deployment = Path("benchmarks/mem0-oss-adapter-v5/deployment")
    shutil.copytree(root / deployment, stage / deployment, ignore=_ignored)
    projects = (
        "infinity_context_core",
        "infinity_context_benchmarks",
        "infinity_context_runtime_bridge",
        "infinity_context_server",
    )
    command = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-index",
        "--no-deps",
        "--no-build-isolation",
        "--wheel-dir",
        str(wheels),
    ]
    # Build the bundle before per-project setuptools build/lib trees exist;
    # namespace discovery must not mistake those intermediate trees for packages.
    _run(command + [str(stage)], cwd=stage)
    _run(command + [str(stage / "packages" / project) for project in projects], cwd=stage)
    built = {path.name.split("-0.1.0-", 1)[0]: path for path in wheels.glob("*.whl")}
    assert set(built) == {*projects, "infinity_context"}, set(built)
    contexts = {
        "standalone": ("infinity_context_core", "infinity_context_benchmarks"),
        "server": projects,
        "bundle": ("infinity_context",),
    }
    reports = []
    fixture_path = root / "tests/fixtures/memory_comparison_bundle_policy"
    for mode, distributions in contexts.items():
        target = output / mode
        if target.exists():
            shutil.rmtree(target)
        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                "--target",
                str(target),
                *(str(built[name]) for name in distributions),
            ],
            cwd=output,
        )
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(Path(__file__).resolve()),
                "--probe",
                mode,
                "--target",
                str(target),
                "--fixtures",
                str(fixture_path),
            ],
            cwd=output,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(f"{mode} isolated smoke failed:\n{result.stdout}\n{result.stderr}")
        reports.append(json.loads(result.stdout))
        print(f"{mode}: isolated wheel contracts passed")
    report = {
        "wheels": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in built.values()
        },
        "contexts": reports,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(output / "report.json"), "wheel_count": len(built)}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--probe", choices=("standalone", "server", "bundle"))
    parser.add_argument("--target", type=Path)
    parser.add_argument("--fixtures", type=Path)
    arguments = parser.parse_args()
    if arguments.probe:
        assert sys.flags.isolated and sys.flags.no_site
        _probe(arguments.target.resolve(), arguments.probe, arguments.fixtures.resolve())
    else:
        if arguments.output is None:
            parser.error("--output is required")
        _build_and_smoke(arguments.output.resolve())


if __name__ == "__main__":
    main()
