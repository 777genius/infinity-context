(() => {
  "use strict";

  window.infinityContextReview = {
    bindModalEvents,
    closeReviewModal,
    openAnchorMergeReviewModal,
    openContextLinkReviewModal,
    openFactSuggestionReviewModal,
    renderSuggestionList,
    reviewRelationMatches,
    reviewTargetMatches,
    visiblePendingContextLinkReviews,
  };

  const FOCUSABLE_SELECTOR = [
    "a[href]",
    "button:not([disabled])",
    "input:not([disabled])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    '[tabindex]:not([tabindex="-1"])',
  ].join(",");
  let previousModalFocus = null;

  function browser() {
    return window.infinityContextBrowser;
  }

  function bindModalEvents() {
    const { els } = browser();
    els.reviewModalClose.addEventListener("click", closeReviewModal);
    els.reviewModal.addEventListener("click", (event) => {
      if (event.target === els.reviewModal) {
        closeReviewModal();
      }
    });
    window.addEventListener("keydown", (event) => {
      if (els.reviewModal.hidden) {
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeReviewModal();
        return;
      }
      if (event.key === "Tab") {
        trapModalFocus(event);
      }
    });
  }

  function renderSuggestionList() {
    const {
      actionButton,
      emptyItem,
      els,
      formatDate,
      listItem,
      manualContextLinkForm,
      mergeAnchorSuggestion,
      reviewContextLinkSuggestion,
      reviewPendingContextLinkSuggestionsBatch,
      reviewSuggestion,
      scoreLabel,
      sectionLabel,
      selectNode,
      state,
    } = browser();
    els.suggestionList.replaceChildren();
    els.suggestionList.append(manualContextLinkForm());
    const relationScoped = reviewRelationFilterActive();
    const anchorMergeReviews = reviewTypeMatches("anchor_merge") && !relationScoped
      ? state.anchorMergeSuggestions.filter(
          (candidate) => reviewStatusMatches(candidate, "pending") && reviewTargetMatches(candidate),
        )
      : [];
    const linkReviews = visibleContextLinkReviews();
    const factReviews = reviewTypeMatches("fact") && !relationScoped
      ? state.suggestions.filter(
          (suggestion) => reviewStatusMatches(suggestion, suggestion.status) && reviewTargetMatches(suggestion),
        )
      : [];
    if (!anchorMergeReviews.length && !linkReviews.length && !factReviews.length) {
      els.suggestionList.append(emptyItem("No review items."));
      return;
    }
    if (anchorMergeReviews.length) {
      els.suggestionList.append(sectionLabel("Anchor merge reviews"));
    }
    for (const candidate of anchorMergeReviews.slice(0, 80)) {
      const item = listItem({
        title: `${candidate.source_anchor.label} -> ${candidate.target_anchor.label} / ${candidate.confidence}`,
        text: (candidate.reasons || []).join(", ") || "possible duplicate anchor",
        meta: `${scoreLabel(candidate.score)} ${candidate.source_anchor.kind}`,
        onClick: () => selectNode(`anchor:${candidate.source_anchor.id}`),
      });
      const actions = document.createElement("div");
      actions.className = "action-row two-actions";
      actions.append(
        actionButton("Details", () => openAnchorMergeReviewModal(candidate)),
        actionButton("Merge", () => mergeAnchorSuggestion(candidate), "primary-button"),
      );
      item.append(actions);
      els.suggestionList.append(item);
    }
    if (linkReviews.length) {
      els.suggestionList.append(sectionLabel("Link reviews"));
      const pendingLinkReviews = visiblePendingContextLinkReviews();
      const batchVisibleFilter = browser().contextLinkBatchVisibleFilter();
      if (pendingLinkReviews.length) {
        if (batchVisibleFilter) {
          const batchActions = document.createElement("div");
          batchActions.className = "action-row two-actions";
          batchActions.append(
            actionButton(
              `Approve Pending (${Math.min(pendingLinkReviews.length, 50)})`,
              () => reviewPendingContextLinkSuggestionsBatch("approve"),
              "primary-button",
            ),
            actionButton(
              `Reject Pending (${Math.min(pendingLinkReviews.length, 50)})`,
              () => reviewPendingContextLinkSuggestionsBatch("reject"),
            ),
          );
          els.suggestionList.append(batchActions);
        } else {
          els.suggestionList.append(
            emptyItem("Batch review is disabled while target search is active."),
          );
        }
      }
    }
    for (const suggestion of linkReviews.slice(0, 160)) {
      const item = listItem({
        title: `${suggestion.source_type} -> ${suggestion.target_type} / ${suggestion.status}`,
        text: suggestion.metadata?.target_preview || suggestion.reason,
        meta: `${scoreLabel(suggestion.score)} ${formatDate(suggestion.updated_at)}`,
        onClick: () => selectNode(`context_link_suggestion:${suggestion.id}`),
      });
      if (suggestion.status === "pending") {
        const actions = document.createElement("div");
        actions.className = "action-row";
        actions.append(
          actionButton("Details", () => openContextLinkReviewModal(suggestion)),
          actionButton(
            "Approve",
            () => reviewContextLinkSuggestion("approve", suggestion.id),
            "primary-button",
          ),
          actionButton("Reject", () => reviewContextLinkSuggestion("reject", suggestion.id)),
        );
        item.append(actions);
      } else {
        const actions = document.createElement("div");
        actions.className = "action-row one-action";
        actions.append(actionButton("Details", () => openContextLinkReviewModal(suggestion)));
        item.append(actions);
      }
      els.suggestionList.append(item);
    }
    if (factReviews.length) {
      els.suggestionList.append(sectionLabel("Fact suggestions"));
    }
    for (const suggestion of factReviews.slice(0, 160)) {
      const item = listItem({
        title: [
          suggestion.operation,
          suggestion.status,
          suggestion.review_kind || "review",
        ].join(" / "),
        text: suggestion.candidate_text,
        meta: factSuggestionMeta(suggestion, formatDate),
        onClick: () => selectNode(`suggestion:${suggestion.id}`),
      });
      if (suggestion.status === "pending") {
        const actions = document.createElement("div");
        actions.className = "action-row four-actions";
        actions.append(
          actionButton("Details", () => openFactSuggestionReviewModal(suggestion)),
          actionButton("Approve", () => reviewSuggestion("approve", suggestion.id), "primary-button"),
          actionButton("Reject", () => reviewSuggestion("reject", suggestion.id)),
          actionButton("Expire", () => reviewSuggestion("expire", suggestion.id)),
        );
        item.append(actions);
      } else {
        const actions = document.createElement("div");
        actions.className = "action-row one-action";
        actions.append(actionButton("Details", () => openFactSuggestionReviewModal(suggestion)));
        item.append(actions);
      }
      els.suggestionList.append(item);
    }
  }

  function openReviewModal(title, ...content) {
    const { els } = browser();
    if (!els.reviewModal.contains(document.activeElement)) {
      previousModalFocus = document.activeElement;
    }
    els.reviewModalTitle.textContent = title || "Review details";
    els.reviewModalBody.replaceChildren();
    for (const child of content.flat()) {
      if (child) {
        els.reviewModalBody.append(child);
      }
    }
    els.reviewModal.hidden = false;
    els.reviewModal.setAttribute("role", "dialog");
    els.reviewModal.setAttribute("aria-modal", "true");
    window.setTimeout(() => focusFirstModalControl(), 0);
  }

  function closeReviewModal() {
    const { els } = browser();
    els.reviewModal.hidden = true;
    els.reviewModalBody.replaceChildren();
    if (
      previousModalFocus &&
      previousModalFocus.isConnected &&
      typeof previousModalFocus.focus === "function"
    ) {
      previousModalFocus.focus();
    }
    previousModalFocus = null;
  }

  function openContextLinkReviewModal(suggestion) {
    const {
      actionButton,
      contextLinkEditForm,
      formatContextLinkReviewAudit,
      reviewContextLinkSuggestion,
      shortId,
    } = browser();
    const grid = document.createElement("div");
    grid.className = "review-grid";
    grid.append(
      contextEndpointPreviewSection("Source evidence", suggestion.source_type, suggestion.source_id),
      contextEndpointPreviewSection(
        "Target preview",
        suggestion.target_type,
        suggestion.target_id,
        suggestion.metadata?.target_preview || suggestion.metadata?.target_label || "",
      ),
    );
    const content = [contextLinkSuggestionSection(suggestion), grid];
    const audit = formatContextLinkReviewAudit(suggestion.review_audit);
    if (audit) {
      const history = document.createElement("section");
      history.className = "source-list";
      const heading = document.createElement("h3");
      heading.className = "detail-title";
      heading.textContent = "Review history";
      const body = document.createElement("div");
      body.className = "text-block";
      body.textContent = audit;
      history.append(heading, body);
      content.push(history);
    }
    if (suggestion.status === "pending") {
      const actions = document.createElement("div");
      actions.className = "action-row two-actions";
      actions.append(
        actionButton(
          "Approve",
          () => reviewContextLinkSuggestion("approve", suggestion.id),
          "primary-button",
        ),
        actionButton("Reject", () => reviewContextLinkSuggestion("reject", suggestion.id)),
      );
      content.push(actions, contextLinkEditForm(suggestion));
    }
    openReviewModal(`Link review ${shortId(suggestion.id)}`, content);
  }

  function openAnchorMergeReviewModal(candidate) {
    const { actionButton, arrayOf, keyValueItem, mergeAnchorSuggestion, scoreLabel } = browser();
    const summary = document.createElement("section");
    summary.className = "source-list";
    const heading = document.createElement("h3");
    heading.className = "detail-title";
    heading.textContent = "Merge rationale";
    summary.append(
      heading,
      keyValueItem("Source", `${candidate.source_anchor.kind}:${candidate.source_anchor.label}`),
      keyValueItem("Target", `${candidate.target_anchor.kind}:${candidate.target_anchor.label}`),
      keyValueItem("Confidence", candidate.confidence),
      keyValueItem("Score", scoreLabel(candidate.score)),
      keyValueItem("Why", arrayOf(candidate.reasons).join(", ") || "possible duplicate anchor"),
    );
    const grid = document.createElement("div");
    grid.className = "review-grid";
    grid.append(
      contextEndpointPreviewSection(
        "Source anchor",
        "anchor",
        candidate.source_anchor.id,
        candidate.source_anchor.label,
      ),
      contextEndpointPreviewSection(
        "Target anchor",
        "anchor",
        candidate.target_anchor.id,
        candidate.target_anchor.label,
      ),
    );
    const actions = document.createElement("div");
    actions.className = "action-row one-action";
    actions.append(actionButton("Merge", () => mergeAnchorSuggestion(candidate), "primary-button"));
    openReviewModal("Anchor merge review", summary, grid, actions);
  }

  function openFactSuggestionReviewModal(suggestion) {
    const { actionButton, arrayOf, formatDate, keyValueItem, reviewSuggestion, shortId, sourceSection } =
      browser();
    const section = document.createElement("section");
    section.className = "source-list";
    const heading = document.createElement("h3");
    heading.className = "detail-title";
    heading.textContent = "Fact suggestion";
    section.append(
      heading,
      keyValueItem("Operation", suggestion.operation),
      keyValueItem("Review kind", suggestion.review_kind || "candidate_review"),
      keyValueItem("Status", suggestion.status),
      keyValueItem("Kind", suggestion.kind),
      keyValueItem("Target fact", suggestion.target_fact_id || "new fact"),
      keyValueItem("State", suggestion.review_state_reason || "pending_review"),
      keyValueItem("Candidate", suggestion.candidate_text),
      keyValueItem("Updated", formatDate(suggestion.updated_at)),
    );
    const content = [section];
    const optionsSection = factSuggestionResolutionSection(suggestion);
    if (optionsSection) {
      content.push(optionsSection);
    }
    const refs = arrayOf(suggestion.source_refs);
    if (refs.length) {
      content.push(sourceSection(refs));
    }
    if (suggestion.status === "pending") {
      const actions = document.createElement("div");
      actions.className = "action-row";
      actions.append(
        actionButton("Approve", () => reviewSuggestion("approve", suggestion.id), "primary-button"),
        actionButton("Reject", () => reviewSuggestion("reject", suggestion.id)),
        actionButton("Expire", () => reviewSuggestion("expire", suggestion.id)),
      );
      const conflictActions = factSuggestionConflictActions(suggestion);
      if (conflictActions) {
        actions.append(...conflictActions);
      }
      content.push(actions);
    }
    openReviewModal(`Fact suggestion ${shortId(suggestion.id)}`, content);
  }

  function factSuggestionMeta(suggestion, formatDate) {
    const parts = [
      suggestion.review_kind,
      suggestion.review_state_reason,
      formatDate(suggestion.updated_at),
    ].filter(Boolean);
    return parts.join(" / ");
  }

  function factSuggestionResolutionSection(suggestion) {
    const { arrayOf, keyValueItem } = browser();
    const options = arrayOf(suggestion.review_resolution_options);
    if (!options.length) {
      return null;
    }
    const section = document.createElement("section");
    section.className = "source-list";
    const heading = document.createElement("h3");
    heading.className = "detail-title";
    heading.textContent = "Resolution options";
    section.append(
      heading,
      keyValueItem(
        "Recommended",
        suggestion.review_payload?.recommended_action || "manual_review",
      ),
      keyValueItem(
        "Default",
        suggestion.review_payload?.default_resolution || "review_before_write",
      ),
      keyValueItem(
        "Available actions",
        arrayOf(suggestion.available_review_actions).join(", ") || "none",
      ),
    );
    for (const option of options) {
      section.append(
        keyValueItem(
          optionLabel(option),
          [option.effect, option.availability].filter(Boolean).join(" / "),
        ),
      );
    }
    return section;
  }

  function optionLabel(option) {
    const id = option.id || "resolution";
    const action = option.review_action || "review";
    return `${id} (${action})`;
  }

  function factSuggestionConflictActions(suggestion) {
    const { actionButton, arrayOf, resolveSuggestionConflict } = browser();
    const options = arrayOf(suggestion.review_resolution_options).filter(
      (option) => option.review_action === "resolve_conflict" && option.availability === "available",
    );
    if (!options.length) {
      return null;
    }
    return options.map((option) =>
      actionButton(
        conflictResolutionButtonLabel(option),
        () => resolveSuggestionConflict(option.resolution_action || option.id, suggestion.id),
        option.id === "replace_existing_fact" ? "primary-button" : "",
      ),
    );
  }

  function conflictResolutionButtonLabel(option) {
    if (option.id === "replace_existing_fact") {
      return "Replace existing";
    }
    if (option.id === "mark_existing_disputed") {
      return "Mark disputed";
    }
    return option.id || "Resolve";
  }

  function contextEndpointPreviewSection(title, objectType, objectId, fallbackPreview = "") {
    const { emptyItem, keyValueItem, sourceSection } = browser();
    const section = document.createElement("section");
    section.className = "source-list";
    const heading = document.createElement("h3");
    heading.className = "detail-title";
    heading.textContent = title;
    section.append(heading, keyValueItem("Object", `${objectType}:${objectId}`));
    const object = findContextObject(objectType, objectId);
    if (!object) {
      if (fallbackPreview) {
        section.append(keyValueItem("Preview", fallbackPreview));
      }
      section.append(emptyItem("Object is not loaded in the current scope snapshot."));
      return section;
    }
    section.append(
      keyValueItem("Preview", contextObjectPreview(object) || fallbackPreview || "no preview"),
      ...contextObjectMetaItems(object),
    );
    const refs = contextObjectEvidenceRefs(object);
    if (refs.length) {
      section.append(sourceSection(refs));
    }
    return section;
  }

  function contextLinkSuggestionSection(suggestion) {
    const { arrayOf, formatDate, keyValueItem, scoreLabel } = browser();
    const section = document.createElement("section");
    section.className = "source-list";
    const heading = document.createElement("h3");
    heading.className = "detail-title";
    heading.textContent = "Link";
    section.append(heading);
    section.append(
      keyValueItem("Source", `${suggestion.source_type}:${suggestion.source_id}`),
      keyValueItem("Target", `${suggestion.target_type}:${suggestion.target_id}`),
      keyValueItem("Relation", suggestion.relation_type),
      keyValueItem("Status", suggestion.status),
      keyValueItem("Confidence", suggestion.confidence),
      keyValueItem("Score", scoreLabel(suggestion.score)),
      keyValueItem("Reason", suggestion.reason),
      keyValueItem("Target preview", suggestion.metadata?.target_preview || ""),
      keyValueItem("Updated", formatDate(suggestion.updated_at)),
    );
    const reasons = [
      ...arrayOf(suggestion.metadata?.reasons),
      ...arrayOf(suggestion.metadata?.reason_codes),
    ];
    if (reasons.length) {
      section.append(keyValueItem("Why", reasons.join(", ")));
    }
    const matchedTerms = arrayOf(suggestion.metadata?.matched_terms);
    if (matchedTerms.length) {
      section.append(keyValueItem("Matched", matchedTerms.join(", ")));
    }
    return section;
  }

  function reviewTypeMatches(type) {
    const selected = browser().state.reviewTypeFilter || "all";
    return selected === "all" || selected === type;
  }

  function visibleContextLinkReviews() {
    if (!reviewTypeMatches("link")) {
      return [];
    }
    return browser().state.contextLinkSuggestions.filter(
      (suggestion) =>
        reviewStatusMatches(suggestion, suggestion.status) &&
        reviewRelationMatches(suggestion) &&
        reviewTargetMatches(suggestion),
    );
  }

  function visiblePendingContextLinkReviews() {
    return visibleContextLinkReviews().filter((suggestion) => suggestion.status === "pending");
  }

  function reviewStatusMatches(item, fallbackStatus) {
    const selected = browser().state.reviewStatusFilter || "pending";
    if (selected === "all") {
      return true;
    }
    return String(item?.status || fallbackStatus || "pending") === selected;
  }

  function reviewRelationFilterActive() {
    return (browser().state.reviewRelationFilter || "all") !== "all";
  }

  function reviewRelationMatches(suggestion) {
    const selected = browser().state.reviewRelationFilter || "all";
    return selected === "all" || suggestion.relation_type === selected;
  }

  function reviewTargetMatches(item) {
    const search = (browser().state.reviewTargetFilter || "").trim().toLowerCase();
    if (!search) {
      return true;
    }
    const haystack = reviewSearchTerms(item).join(" ").toLowerCase();
    return haystack.includes(search);
  }

  function reviewSearchTerms(item) {
    const { arrayOf } = browser();
    if (!item) {
      return [];
    }
    const sourceAnchor = item.source_anchor || {};
    const targetAnchor = item.target_anchor || {};
    return [
      item.operation,
      item.status,
      item.kind,
      item.candidate_text,
      item.reason,
      item.relation_type,
      item.source_type,
      item.source_id,
      item.target_type,
      item.target_id,
      item.target_fact_id,
      item.metadata?.target_label,
      item.metadata?.target_preview,
      sourceAnchor.kind,
      sourceAnchor.label,
      sourceAnchor.id,
      targetAnchor.kind,
      targetAnchor.label,
      targetAnchor.id,
      ...arrayOf(item.reasons),
      ...arrayOf(item.metadata?.reasons),
      ...arrayOf(item.metadata?.reason_codes),
      ...arrayOf(item.metadata?.matched_terms),
      ...arrayOf(item.source_refs).map((ref) => `${ref.source_type}:${ref.source_id}`),
      ...arrayOf(item.evidence_refs).map((ref) => `${ref.source_type}:${ref.source_id}`),
    ].filter(Boolean);
  }

  function findContextObject(objectType, objectId) {
    const { arrayOf, state } = browser();
    const collections = {
      anchor: state.anchors,
      chunk: state.chunks,
      context_link: state.contextLinks,
      context_link_suggestion: state.contextLinkSuggestions,
      document: state.documents,
      episode: state.episodes,
      fact: state.facts,
      suggestion: state.suggestions,
    };
    const direct = arrayOf(collections[objectType]).find((item) => item.id === objectId);
    if (direct) {
      return direct;
    }
    const browserCollections = {
      asset: "assets",
      capture: "captures",
      thread: "threads",
    };
    return arrayOf(state.memoryBrowser?.[browserCollections[objectType] || `${objectType}s`]).find(
      (item) => item.id === objectId,
    );
  }

  function contextObjectPreview(object) {
    return (
      object.text ||
      object.candidate_text ||
      object.title ||
      object.label ||
      object.description ||
      object.source_external_id ||
      object.reason ||
      ""
    );
  }

  function contextObjectMetaItems(object) {
    const { formatDate, keyValueItem, temporalWindowLabel } = browser();
    const validity = object.valid_from || object.valid_to
      ? temporalWindowLabel(object.valid_from, object.valid_to)
      : "";
    const entries = [
      ["Status", object.status],
      ["Kind", object.kind],
      ["Thread", object.thread_id],
      ["Confidence", object.confidence],
      ["Observed", formatDate(object.observed_at)],
      ["Validity", validity],
      ["Updated", formatDate(object.updated_at)],
      ["Created", formatDate(object.created_at)],
    ];
    return entries
      .filter(([, value]) => value)
      .map(([title, value]) => keyValueItem(title, String(value)));
  }

  function contextObjectEvidenceRefs(object) {
    const { arrayOf } = browser();
    return [...arrayOf(object.source_refs), ...arrayOf(object.evidence_refs)];
  }

  function focusableModalElements() {
    const { els } = browser();
    return [...els.reviewModal.querySelectorAll(FOCUSABLE_SELECTOR)].filter(
      (element) => element.getClientRects().length > 0,
    );
  }

  function focusFirstModalControl() {
    const { els } = browser();
    const first = focusableModalElements()[0] || els.reviewModalClose;
    if (first && typeof first.focus === "function") {
      first.focus();
    }
  }

  function trapModalFocus(event) {
    const focusable = focusableModalElements();
    if (!focusable.length) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!browser().els.reviewModal.contains(document.activeElement)) {
      event.preventDefault();
      if (event.shiftKey) {
        last.focus();
      } else {
        first.focus();
      }
      return;
    }
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
      return;
    }
    if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
})();
