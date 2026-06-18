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
        review_js = client.get("/ui/assets/memory-browser-review.js")
        operations_js = client.get("/ui/assets/memory-browser-operations.js")
        openapi = client.get("/openapi.json")

    assert redirect.status_code in {307, 308}
    assert redirect.headers["location"] == "/ui/"
    assert index.status_code == 200
    assert "Memo Stack Browser" in index.text
    assert "memory-browser.js" in index.text
    assert "memory-browser-review.js" in index.text
    assert "memory-browser-operations.js" in index.text
    assert "Operations" in index.text
    assert "operationsList" in index.text
    assert "Bearer " not in index.text
    assert css.status_code == 200
    assert "graph-panel" in css.text
    assert "section-label" in css.text
    assert js.status_code == 200
    assert review_js.status_code == 200
    assert operations_js.status_code == 200
    assert "localStorage" in js.text
    assert "Authorization" in js.text
    assert "memoStackBrowser" in js.text
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
    assert "Anchor merge reviews" in review_js.text
    assert "splitAnchorAlias" in js.text
    assert "Split Alias" in js.text
    assert "/split" in js.text
    assert "evidence_refs" in js.text
    assert "temporalWindowLabel" in js.text
    assert "Validity" in js.text
    assert "contextLinkCount" in index.text
    assert "context_link" in index.text
    assert "/v1/context-links" in js.text
    assert "/v1/context-link-suggestions" in js.text
    assert "/v1/context-link-suggestions/review-batch" in js.text
    assert "reviewContextLinkSuggestion" in js.text
    assert "reviewPendingContextLinkSuggestionsBatch" in js.text
    assert "withReviewActionLock" in js.text
    assert "Review action is already in progress." in js.text
    assert "contextLinkBatchVisibleFilter" in js.text
    assert "visible_filter: visibleFilter" in js.text
    assert "Clear the review target filter before batch review." in js.text
    assert "Approve Pending" in review_js.text
    assert "Batch review is disabled while target search is active." in review_js.text
    assert "Approve With Edits" in js.text
    assert "Manual Link" in js.text
    assert "Create Link" in js.text
    assert "reviewStatusFilter" in index.text
    assert "reviewTypeFilter" in index.text
    assert "reviewRelationFilter" in index.text
    assert "reviewTargetFilter" in index.text
    assert "reviewModal" in index.text
    assert "reviewModalBody" in index.text
    assert "reviewTypeMatches" in review_js.text
    assert "reviewStatusMatches" in review_js.text
    assert "reviewRelationMatches" in review_js.text
    assert "reviewTargetMatches" in review_js.text
    assert "visiblePendingContextLinkReviews" in review_js.text
    assert "openContextLinkReviewModal" in review_js.text
    assert "openAnchorMergeReviewModal" in review_js.text
    assert "openFactSuggestionReviewModal" in review_js.text
    assert "Source evidence" in review_js.text
    assert "Target preview" in review_js.text
    assert "Review history" in js.text
    assert "Review history" in review_js.text
    assert "formatContextLinkReviewAudit" in js.text
    assert "trapModalFocus" in review_js.text
    assert "modal-overlay" in css.text
    assert "review-grid" in css.text
    assert "white-space: pre-wrap" in css.text
    assert "Edit Link" in js.text
    assert "Save Link" in js.text
    assert "Edit history" in js.text
    assert "editContextLink" in js.text
    assert "Use Selected Source" in js.text
    assert "createManualContextLink" in js.text
    assert "Delete Link" in js.text
    assert "deleteContextLink" in js.text
    assert '["active", "deleted"]' in js.text
    assert "/v1/operations-console" in js.text
    assert "/retry" in operations_js.text
    assert "/cancel" in operations_js.text
    assert "renderOperations" in operations_js.text
    assert "memoStackOperations" in operations_js.text
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
