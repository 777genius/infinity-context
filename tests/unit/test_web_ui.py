from fastapi.testclient import TestClient
from memo_stack_server.config import DeployProfile, Settings
from memo_stack_server.main import create_app


def test_web_ui_serves_browser_without_openapi_noise(tmp_path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'ui.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )

    with TestClient(app) as client:
        redirect = client.get("/ui", follow_redirects=False)
        index = client.get("/ui/")
        css = client.get("/ui/assets/memory-browser.css")
        js = client.get("/ui/assets/memory-browser.js")
        openapi = client.get("/openapi.json")

    assert redirect.status_code in {307, 308}
    assert redirect.headers["location"] == "/ui/"
    assert index.status_code == 200
    assert "Memo Stack Browser" in index.text
    assert "memory-browser.js" in index.text
    assert "Bearer " not in index.text
    assert css.status_code == 200
    assert "graph-panel" in css.text
    assert "section-label" in css.text
    assert js.status_code == 200
    assert "localStorage" in js.text
    assert "Authorization" in js.text
    assert "anchorCount" in index.text
    assert "Create Anchor" in index.text
    assert "Backfill Anchors" in index.text
    assert '<option value="anchor">Anchors</option>' in index.text
    assert "/v1/anchors" in js.text
    assert "createAnchor" in js.text
    assert "splitCsv" in js.text
    assert "editAnchor" in js.text
    assert "deleteAnchor" in js.text
    assert "Edit Anchor" in js.text
    assert "Delete Anchor" in js.text
    assert "/v1/anchors/merge-suggestions" in js.text
    assert "backfillAnchors" in js.text
    assert "mergeAnchorSuggestion" in js.text
    assert "Anchor merge reviews" in js.text
    assert "splitAnchorAlias" in js.text
    assert "Split Alias" in js.text
    assert "/split" in js.text
    assert "contextLinkCount" in index.text
    assert "context_link" in index.text
    assert "/v1/context-links" in js.text
    assert "/v1/context-link-suggestions" in js.text
    assert "reviewContextLinkSuggestion" in js.text
    assert "Approve With Edits" in js.text
    assert "Manual Link" in js.text
    assert "Create Link" in js.text
    assert "Use Selected Source" in js.text
    assert "createManualContextLink" in js.text
    assert "Delete Link" in js.text
    assert "deleteContextLink" in js.text
    assert '["active", "deleted"]' in js.text
    assert "/ui/" not in openapi.text


def test_web_ui_can_be_disabled(tmp_path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'ui-disabled.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            ui_enabled=False,
        )
    )

    with TestClient(app) as client:
        response = client.get("/ui/")

    assert response.status_code == 404
