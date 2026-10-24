"""Static acceptance must compare with the event's base, not a moving branch."""

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/infinity-context-ci.yml"


def test_pr_base_fetch_uses_immutable_event_revision():
    source = WORKFLOW.read_text(encoding="utf-8")
    step = source.split("- name: Fetch pull request base\n", 1)[1].split("\n      - name:", 1)[0]
    assert "PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}" in step
    assert 'git fetch --no-tags origin "$PR_BASE_SHA"' in step
    assert "github.base_ref" not in step


def test_file_size_guard_uses_same_pinned_pr_base():
    source = WORKFLOW.read_text(encoding="utf-8")
    value = source.split("FILE_SIZE_BASE_REF: ", 1)[1].splitlines()[0]
    assert "github.event_name == 'pull_request' && github.event.pull_request.base.sha" in value
    assert "origin/" not in value


def test_push_still_compares_against_previous_head():
    source = WORKFLOW.read_text(encoding="utf-8")
    value = source.split("FILE_SIZE_BASE_REF: ", 1)[1].splitlines()[0]
    assert "github.event_name == 'push' && github.event.before" in value
