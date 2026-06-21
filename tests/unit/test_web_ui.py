import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app


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
        capture_js = client.get("/ui/assets/memory-browser-capture.js")
        review_js = client.get("/ui/assets/memory-browser-review.js")
        operations_js = client.get("/ui/assets/memory-browser-operations.js")
        openapi = client.get("/openapi.json")

    assert redirect.status_code in {307, 308}
    assert redirect.headers["location"] == "/ui/"
    assert index.status_code == 200
    assert "Infinity Context Browser" in index.text
    assert "Capture" in index.text
    assert "Overview" in index.text
    assert "capturePanel" in index.text
    assert "overviewPanel" in index.text
    assert "captureTextInput" in index.text
    assert "assetFileInput" in index.text
    assert "Save Note" in index.text
    assert "Upload File" in index.text
    assert "memory-browser.js" in index.text
    assert "memory-browser-capture.js" in index.text
    assert "memory-browser-review.js" in index.text
    assert "memory-browser-operations.js" in index.text
    assert "Operations" in index.text
    assert "operationsList" in index.text
    assert "Bearer " not in index.text
    assert css.status_code == 200
    assert "graph-panel" in css.text
    assert "capture-grid" in css.text
    assert "capture-status" in css.text
    assert "overview-grid" in css.text
    assert "overview-card" in css.text
    assert "section-label" in css.text
    assert js.status_code == 200
    assert capture_js.status_code == 200
    assert review_js.status_code == 200
    assert operations_js.status_code == 200
    assert "localStorage" in js.text
    assert "Authorization" in js.text
    assert "infinityContextBrowser" in js.text
    assert "infinityContextCapture" in capture_js.text
    assert "saveQuickCapture" in capture_js.text
    assert "uploadAssetEvidence" in capture_js.text
    assert "/v1/captures" in capture_js.text
    assert "/v1/assets" in capture_js.text
    assert "apiRaw" in capture_js.text
    assert "requestExtractionForAsset" in capture_js.text
    assert "retryExtractionJob" in capture_js.text
    assert "cancelExtractionJob" in capture_js.text
    assert "extraction_job" in js.text
    assert "renderOverview" in js.text
    assert "Visual Memory" in js.text
    assert "Review Queue" in js.text
    assert "Recent Memory" in js.text
    assert "Anchor Map" in js.text
    assert "Source Mix" in js.text
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
    assert "event.preventDefault();" in review_js.text
    assert "previousModalFocus.isConnected" in review_js.text
    assert "els.reviewModal.contains(document.activeElement)" in review_js.text
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
    assert "infinityContextOperations" in operations_js.text
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


def test_review_modal_focus_trap_and_escape_keyboard_flow() -> None:
    node = shutil.which("node")
    if not node:
        return
    review_js = (
        Path(__file__).resolve().parents[2]
        / (
            "packages/infinity_context_server/infinity_context_server/web/assets/"
            "memory-browser-review.js"
        )
    )
    script = r"""
const fs = require("fs");
const vm = require("vm");
const reviewJsPath = process.argv[1];

class Element {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.hidden = false;
    this.disabled = false;
    this.isConnected = true;
    this.textContent = "";
    this.className = "";
    this.attributes = {};
    this.listeners = {};
  }
  append(...children) {
    for (const child of children.flat()) {
      if (!child) {
        continue;
      }
      child.parentNode = this;
      this.children.push(child);
    }
  }
  replaceChildren(...children) {
    for (const child of this.children) {
      child.parentNode = null;
      child.isConnected = false;
    }
    this.children = [];
    this.append(...children);
  }
  addEventListener(type, handler) {
    this.listeners[type] = this.listeners[type] || [];
    this.listeners[type].push(handler);
  }
  dispatchEvent(event) {
    for (const handler of this.listeners[event.type] || []) {
      handler(event);
    }
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }
  contains(target) {
    let current = target;
    while (current) {
      if (current === this) {
        return true;
      }
      current = current.parentNode;
    }
    return false;
  }
  focus() {
    document.activeElement = this;
  }
  getClientRects() {
    return [{}];
  }
  querySelectorAll() {
    const results = [];
    const visit = (node) => {
      for (const child of node.children) {
        if (child.tagName === "BUTTON" && !child.disabled) {
          results.push(child);
        }
        visit(child);
      }
    };
    visit(this);
    return results;
  }
}

const document = {
  activeElement: null,
  createElement: (tagName) => new Element(tagName),
};
const window = {
  listeners: {},
  addEventListener(type, handler) {
    this.listeners[type] = this.listeners[type] || [];
    this.listeners[type].push(handler);
  },
  dispatchEvent(event) {
    for (const handler of this.listeners[event.type] || []) {
      handler(event);
    }
  },
  setTimeout(callback) {
    callback();
  },
};

const modal = new Element("div");
modal.hidden = true;
const close = new Element("button");
const title = new Element("h2");
const body = new Element("div");
modal.append(close, title, body);
const opener = new Element("button");
document.activeElement = opener;

function actionButton(text, handler, className = "") {
  const button = new Element("button");
  button.textContent = text;
  button.className = className;
  button.addEventListener("click", handler);
  return button;
}

window.infinityContextBrowser = {
  els: {
    reviewModal: modal,
    reviewModalClose: close,
    reviewModalTitle: title,
    reviewModalBody: body,
  },
  state: {
    anchors: [],
    chunks: [],
    contextLinks: [],
    contextLinkSuggestions: [],
    documents: [],
    episodes: [],
    facts: [],
    suggestions: [],
    memoryBrowser: {},
  },
  actionButton,
  arrayOf: (value) => Array.isArray(value) ? value : [],
  contextLinkEditForm: () => new Element("form"),
  emptyItem: (text) => {
    const item = new Element("div");
    item.textContent = text;
    return item;
  },
  formatContextLinkReviewAudit: () => "created by policy",
  formatDate: (value) => value || "",
  keyValueItem: (key, value) => {
    const item = new Element("div");
    item.textContent = `${key}: ${value}`;
    return item;
  },
  scoreLabel: (score) => String(score),
  shortId: (value) => String(value).slice(0, 8),
  sourceSection: () => new Element("section"),
  temporalWindowLabel: () => "",
  reviewContextLinkSuggestion: () => {},
};

const context = { window, document, console };
context.globalThis = context;
vm.runInNewContext(fs.readFileSync(reviewJsPath, "utf8"), context);
window.infinityContextReview.bindModalEvents();
window.infinityContextReview.openContextLinkReviewModal({
  id: "suggestion_123456",
  source_type: "asset",
  source_id: "asset_1",
  target_type: "fact",
  target_id: "fact_1",
  relation_type: "supports",
  status: "pending",
  confidence: "medium",
  score: 0.9,
  reason: "bbox evidence matched",
  metadata: { target_preview: "Target fact preview" },
  review_audit: [{ action: "created" }],
  updated_at: "2026-06-18T00:00:00Z",
});

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}
function keydown(key, shiftKey = false) {
  const event = {
    type: "keydown",
    key,
    shiftKey,
    defaultPrevented: false,
    preventDefault() {
      this.defaultPrevented = true;
    },
  };
  window.dispatchEvent(event);
  return event;
}

assert(modal.hidden === false, "modal should open");
assert(document.activeElement === close, "first modal control should receive focus");
const focusable = modal.querySelectorAll();
const first = focusable[0];
const last = focusable[focusable.length - 1];
last.focus();
assert(keydown("Tab").defaultPrevented === true, "tab on last control should be trapped");
assert(document.activeElement === first, "tab on last control should wrap to first");
first.focus();
assert(
  keydown("Tab", true).defaultPrevented === true,
  "shift-tab on first control should be trapped",
);
assert(document.activeElement === last, "shift-tab on first control should wrap to last");
opener.focus();
assert(keydown("Tab").defaultPrevented === true, "tab from outside modal should be trapped");
assert(document.activeElement === first, "outside tab should return to modal");
const escape = keydown("Escape");
assert(escape.defaultPrevented === true, "escape should prevent default");
assert(modal.hidden === true, "escape should close modal");
assert(document.activeElement === opener, "close should restore previous focus");
"""
    subprocess.run(
        [node, "-e", script, str(review_js)],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_review_actions_keep_confirmed_refresh_and_bounded_batch_contract() -> None:
    js = (
        Path(__file__).resolve().parents[2]
        / "packages/infinity_context_server/infinity_context_server/web/assets/memory-browser.js"
    ).read_text()

    assert "async function withReviewActionLock" in js
    assert js.index("inFlightReviewActions.add(lockKey)") < js.index("await handler();")
    assert js.index("finally") < js.index("inFlightReviewActions.delete(lockKey);")

    review_context_link = _function_body(js, "reviewContextLinkSuggestion")
    assert review_context_link.index("await apiJson") < review_context_link.index(
        "await refreshAll();"
    )
    assert review_context_link.index("await refreshAll();") < review_context_link.index(
        "closeReviewModal"
    )
    assert "withReviewActionLock(`context-link-suggestion:${suggestionId}`" in (
        review_context_link
    )

    batch_review = _function_body(js, "reviewPendingContextLinkSuggestionsBatch")
    assert "window.infinityContextReview.visiblePendingContextLinkReviews()" in batch_review
    assert "pending.slice(0, 50)" in batch_review
    assert "if (!visibleFilter)" in batch_review
    assert "visible_filter: visibleFilter" in batch_review
    assert batch_review.index("window.prompt") < batch_review.index("apiJson")
    assert batch_review.index("window.confirm") < batch_review.index("apiJson")


def _function_body(source: str, name: str) -> str:
    start = source.index(f"async function {name}")
    next_function = source.find("\n  async function ", start + 1)
    if next_function < 0:
        next_function = source.find("\n  function ", start + 1)
    return source[start:next_function]
