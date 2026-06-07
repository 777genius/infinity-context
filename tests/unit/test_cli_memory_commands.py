from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from memo_stack_cli import cli
from memo_stack_cli.config import init_local_config


class FakeMemoStackClient:
    instances: list[FakeMemoStackClient] = []

    def __init__(self, *, base_url: str, token: str, **_kwargs: Any) -> None:
        self.base_url = base_url
        self.token = token
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.instances.append(self)

    def build_insights(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("build_insights", kwargs))
        return {
            "data": {
                "insights_id": "ins_cli",
                "health_score": 91.5,
                "metrics": {
                    "facts": {"expired_active": 1},
                    "documents": {"without_chunks": 2},
                    "suggestions": {"pending": 3},
                },
                "action_items": [{"id": "mai_1"}],
                "consolidation_plan": [
                    {
                        "plan_type": "similar_fact_review",
                        "canonical_candidate_id": "fact_1",
                        "candidate_fact_ids": ["fact_2"],
                    }
                ],
            }
        }

    def export_profile_snapshot(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("export_profile_snapshot", kwargs))
        return {
            "data": {
                "schema_version": 1,
                "space": {"slug": kwargs["space_slug"]},
                "profile": {"external_ref": kwargs["profile_external_ref"]},
                "facts": [{"id": "fact_1", "text": None if kwargs["redacted"] else "raw"}],
                "redacted": kwargs["redacted"],
            },
            "status": "ok",
        }

    def import_profile_snapshot(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("import_profile_snapshot", kwargs))
        return {
            "data": {
                "status": "ok",
                "dry_run": kwargs["dry_run"],
                "merge_strategy": kwargs["merge_strategy"],
            }
        }

    def preview_profile_snapshot_import(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("preview_profile_snapshot_import", kwargs))
        return {
            "data": {
                "status": "ok",
                "dry_run": True,
                "conflict_count": 1,
                "preview": {
                    "conflict_count": 1,
                    "would_import": {"facts": 2, "documents": 1},
                    "would_skip": {"facts": 1, "documents": 0},
                    "would_supersede": {"facts": 1, "fact_ids": ["fact_old"]},
                    "warnings": ["conflicts_block_import"],
                },
            }
        }


def test_cli_insights_prints_summary_and_uses_default_scope(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "MemoStackClient", FakeMemoStackClient)
    FakeMemoStackClient.instances.clear()

    exit_code = cli.main(["insights", "--max-activity", "9"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "health_score: 91.5" in captured.out
    assert "pending_suggestions: 3" in captured.out
    assert "consolidation_plan: 1" in captured.out
    assert "similar_fact_review: fact_1 <- fact_2" in captured.out
    call_name, kwargs = FakeMemoStackClient.instances[0].calls[0]
    assert call_name == "build_insights"
    assert kwargs["scope"].space_slug == "default"
    assert kwargs["scope"].profile_external_ref == "default"
    assert kwargs["max_activity"] == 9


def test_cli_profile_export_is_redacted_by_default(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "MemoStackClient", FakeMemoStackClient)
    FakeMemoStackClient.instances.clear()
    out_path = tmp_path / "snapshot.json"

    exit_code = cli.main(["profile-export", "--out", str(out_path)])

    captured = capsys.readouterr()
    written = json.loads(out_path.read_text(encoding="utf-8"))
    manifest_path = tmp_path / "snapshot.json.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert str(out_path) in captured.out
    assert str(manifest_path) in captured.out
    assert written["redacted"] is True
    assert written["facts"][0]["text"] is None
    assert manifest["schema_version"] == "memo_stack.profile_snapshot_manifest.v1"
    assert manifest["snapshot_file"] == "snapshot.json"
    assert manifest["redacted"] is True
    assert manifest["snapshot_sha256"]
    call_name, kwargs = FakeMemoStackClient.instances[0].calls[0]
    assert call_name == "export_profile_snapshot"
    assert kwargs["redacted"] is True


def test_cli_profile_verify_accepts_manifest_and_rejects_tamper(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "MemoStackClient", FakeMemoStackClient)
    FakeMemoStackClient.instances.clear()
    out_path = tmp_path / "snapshot.json"

    export_exit = cli.main(["profile-export", "--out", str(out_path)])
    capsys.readouterr()
    verify_exit = cli.main(["profile-verify", "--snapshot", str(out_path), "--json"])
    verify_output = capsys.readouterr()

    assert export_exit == 0
    assert verify_exit == 0
    assert json.loads(verify_output.out)["ok"] is True

    out_path.write_text('{"tampered": true}\n', encoding="utf-8")
    tampered_exit = cli.main(["profile-verify", "--snapshot", str(out_path)])
    tampered_output = capsys.readouterr()

    assert tampered_exit == 1
    assert "snapshot_sha256_mismatch" in tampered_output.out


def test_cli_profile_import_dry_run_and_apply_confirmation(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "MemoStackClient", FakeMemoStackClient)
    FakeMemoStackClient.instances.clear()
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

    dry_run_exit = cli.main(["profile-import", "--in", str(snapshot_path)])
    rejected_exit = cli.main(["profile-import", "--in", str(snapshot_path), "--apply"])
    apply_exit = cli.main(
        ["profile-import", "--in", str(snapshot_path), "--apply", "--confirmed"]
    )

    captured = capsys.readouterr()
    assert dry_run_exit == 0
    assert rejected_exit == 1
    assert apply_exit == 0
    assert "requires --confirmed" in captured.err
    first_call = FakeMemoStackClient.instances[0].calls[0]
    second_call = FakeMemoStackClient.instances[1].calls[0]
    assert first_call[0] == "import_profile_snapshot"
    assert first_call[1]["dry_run"] is True
    assert second_call[1]["dry_run"] is False
    assert second_call[1]["confirmed"] is True


def test_cli_profile_import_verifies_manifest_before_client_call(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "MemoStackClient", FakeMemoStackClient)
    FakeMemoStackClient.instances.clear()
    out_path = tmp_path / "snapshot.json"
    manifest_path = tmp_path / "snapshot.json.manifest.json"

    export_exit = cli.main(["profile-export", "--out", str(out_path)])
    capsys.readouterr()
    import_exit = cli.main(
        [
            "profile-import",
            "--in",
            str(out_path),
            "--manifest",
            str(manifest_path),
        ]
    )
    good_output = capsys.readouterr()

    assert export_exit == 0
    assert import_exit == 0
    assert '"dry_run": true' in good_output.out
    assert FakeMemoStackClient.instances[-1].calls[0][0] == "import_profile_snapshot"

    client_count = len(FakeMemoStackClient.instances)
    out_path.write_text('{"tampered": true}\n', encoding="utf-8")
    tampered_exit = cli.main(
        [
            "profile-import",
            "--in",
            str(out_path),
            "--manifest",
            str(manifest_path),
        ]
    )
    tampered_output = capsys.readouterr()

    assert tampered_exit == 1
    assert "manifest verification failed" in tampered_output.err
    assert "snapshot_sha256_mismatch" in tampered_output.err
    assert len(FakeMemoStackClient.instances) == client_count


def test_cli_profile_import_preview_uses_read_only_preview_endpoint(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "MemoStackClient", FakeMemoStackClient)
    FakeMemoStackClient.instances.clear()
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

    exit_code = cli.main(
        [
            "profile-import-preview",
            "--in",
            str(snapshot_path),
            "--merge-strategy",
            "supersede_matching_facts",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "status: ok" in captured.out
    assert "dry_run: True" in captured.out
    assert "would_import:" in captured.out
    assert "would_supersede:" in captured.out
    assert "conflicts_block_import" in captured.out
    call_name, kwargs = FakeMemoStackClient.instances[0].calls[0]
    assert call_name == "preview_profile_snapshot_import"
    assert kwargs["merge_strategy"] == "supersede_matching_facts"
    assert kwargs["manifest"] is None


def test_cli_profile_import_preview_verifies_manifest_before_client_call(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "MemoStackClient", FakeMemoStackClient)
    FakeMemoStackClient.instances.clear()
    out_path = tmp_path / "snapshot.json"
    manifest_path = tmp_path / "snapshot.json.manifest.json"

    export_exit = cli.main(["profile-export", "--out", str(out_path)])
    capsys.readouterr()
    preview_exit = cli.main(
        [
            "profile-import-preview",
            "--in",
            str(out_path),
            "--manifest",
            str(manifest_path),
            "--json",
        ]
    )
    preview_output = capsys.readouterr()

    assert export_exit == 0
    assert preview_exit == 0
    assert '"dry_run": true' in preview_output.out
    preview_call = FakeMemoStackClient.instances[-1].calls[0]
    assert preview_call[0] == "preview_profile_snapshot_import"
    assert isinstance(preview_call[1]["manifest"], dict)

    client_count = len(FakeMemoStackClient.instances)
    out_path.write_text('{"tampered": true}\n', encoding="utf-8")
    tampered_exit = cli.main(
        [
            "profile-import-preview",
            "--in",
            str(out_path),
            "--manifest",
            str(manifest_path),
        ]
    )
    tampered_output = capsys.readouterr()

    assert tampered_exit == 1
    assert "manifest verification failed" in tampered_output.err
    assert "snapshot_sha256_mismatch" in tampered_output.err
    assert len(FakeMemoStackClient.instances) == client_count


def _configure(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    init_local_config(home=home, repo_dir=repo)
    monkeypatch.setenv("MEMO_STACK_HOME", str(home))
