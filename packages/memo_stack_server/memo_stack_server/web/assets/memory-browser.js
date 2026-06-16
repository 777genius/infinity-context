(() => {
  "use strict";

  const SETTINGS_KEY = "memoStack.browser.settings.v1";
  const GRAPH_NODE_LIMIT = 320;
  const POLL_MS = 5000;
  const CONTEXT_ENDPOINT_TYPES = [
    "anchor",
    "asset",
    "capture",
    "chunk",
    "document",
    "fact",
    "suggestion",
    "thread",
  ];

  const defaults = {
    apiBase: "",
    token: "",
    spaceSlug: "default",
    memoryScopeRef: "default",
    topic: "memory",
  };

  const state = {
    ...defaults,
    health: null,
    capabilities: null,
    adapterDiagnostics: null,
    spaces: [],
    memory_scopes: [],
    facts: [],
    suggestions: [],
    anchors: [],
    anchorMergeSuggestions: [],
    contextLinkSuggestions: [],
    contextLinks: [],
    nodes: [],
    edges: [],
    selectedNodeId: null,
    nodePositions: new Map(),
    paused: false,
    loading: false,
    graphScale: 1,
    graphTruncated: false,
    lastRefreshAt: null,
  };

  const els = {};

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    bindElements();
    loadSettings();
    applySettingsToInputs();
    bindEvents();
    void refreshAll();
    window.setInterval(() => {
      if (!state.paused) {
        void refreshAll({ silent: true });
      }
    }, POLL_MS);
  }

  function bindElements() {
    for (const id of [
      "apiBaseInput",
      "tokenInput",
      "spaceInput",
      "memory_scopeInput",
      "topicInput",
      "saveSettingsButton",
      "refreshButton",
      "pauseButton",
      "graphSearchInput",
      "typeFilter",
      "statusFilter",
      "zoomInButton",
      "zoomOutButton",
      "fitButton",
      "buildDigestButton",
      "runRecallButton",
      "createAnchorButton",
      "backfillAnchorsButton",
      "scopeSummary",
      "liveStatus",
      "serverStatus",
      "adapterStatus",
      "factCount",
      "suggestionCount",
      "linkSuggestionCount",
      "contextLinkCount",
      "anchorCount",
      "sourceCount",
      "pendingCount",
      "lastRefresh",
      "graphSvg",
      "detailsPanel",
      "digestOutput",
      "recallOutput",
      "suggestionList",
      "timelineList",
      "errorOutput",
      "spacesList",
      "memory_scopesList",
    ]) {
      els[id] = document.getElementById(id);
    }
  }

  function bindEvents() {
    els.saveSettingsButton.addEventListener("click", () => {
      readSettingsFromInputs();
      saveSettings();
      void refreshAll();
    });
    els.refreshButton.addEventListener("click", () => void refreshAll());
    els.pauseButton.addEventListener("click", () => {
      state.paused = !state.paused;
      els.pauseButton.textContent = state.paused ? "Resume" : "Pause";
      updateLiveStatus();
    });
    els.buildDigestButton.addEventListener("click", () => void buildDigest());
    els.runRecallButton.addEventListener("click", () => void runRecall());
    els.createAnchorButton.addEventListener("click", () => void createAnchor());
    els.backfillAnchorsButton.addEventListener("click", () => void backfillAnchors());
    els.graphSearchInput.addEventListener("input", renderAll);
    els.typeFilter.addEventListener("change", renderAll);
    els.statusFilter.addEventListener("change", renderAll);
    els.zoomInButton.addEventListener("click", () => {
      state.graphScale = Math.max(0.55, state.graphScale * 0.86);
      renderGraph();
    });
    els.zoomOutButton.addEventListener("click", () => {
      state.graphScale = Math.min(2.4, state.graphScale * 1.16);
      renderGraph();
    });
    els.fitButton.addEventListener("click", () => {
      state.graphScale = 1;
      renderGraph();
    });
    for (const tab of document.querySelectorAll(".tabs button")) {
      tab.addEventListener("click", () => activateTab(tab.dataset.tab));
    }
    bindGraphPointerEvents();
  }

  function loadSettings() {
    try {
      const loaded = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
      Object.assign(state, defaults, loaded);
    } catch {
      Object.assign(state, defaults);
    }
    const params = new URLSearchParams(window.location.search);
    if (params.get("space")) {
      state.spaceSlug = params.get("space");
    }
    if (params.get("memory_scope")) {
      state.memoryScopeRef = params.get("memory_scope");
    }
    if (params.get("topic")) {
      state.topic = params.get("topic");
    }
  }

  function saveSettings() {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({
        apiBase: state.apiBase,
        token: state.token,
        spaceSlug: state.spaceSlug,
        memoryScopeRef: state.memoryScopeRef,
        topic: state.topic,
      }),
    );
  }

  function applySettingsToInputs() {
    els.apiBaseInput.value = state.apiBase || "";
    els.tokenInput.value = state.token || "";
    els.spaceInput.value = state.spaceSlug || defaults.spaceSlug;
    els.memory_scopeInput.value = state.memoryScopeRef || defaults.memoryScopeRef;
    els.topicInput.value = state.topic || defaults.topic;
  }

  function readSettingsFromInputs() {
    state.apiBase = els.apiBaseInput.value.trim().replace(/\/+$/, "");
    state.token = els.tokenInput.value.trim();
    state.spaceSlug = els.spaceInput.value.trim() || defaults.spaceSlug;
    state.memoryScopeRef = els.memory_scopeInput.value.trim() || defaults.memoryScopeRef;
    state.topic = els.topicInput.value.trim() || defaults.topic;
    updateScopeSummary();
  }

  async function refreshAll(options = {}) {
    if (state.loading) {
      return;
    }
    readSettingsFromInputs();
    state.loading = true;
    if (!options.silent) {
      setError("");
    }
    try {
      const healthPromise = apiGet("/v1/health", { authOptional: true }).catch((error) => ({
        status: "unavailable",
        error: error.message,
      }));
      const capabilitiesPromise = apiGet("/v1/capabilities").catch((error) => ({
        error: error.message,
      }));
      const [health, capabilities] = await Promise.all([healthPromise, capabilitiesPromise]);
      state.health = health;
      state.capabilities = capabilities;
      await refreshSpacesAndMemoryScopes();
      const [
        facts,
        suggestions,
        anchors,
        anchorMergeSuggestions,
        contextLinkSuggestions,
        contextLinks,
        diagnostics,
      ] = await Promise.all([
        fetchFacts(),
        fetchSuggestions(),
        fetchAnchors(),
        fetchAnchorMergeSuggestions(),
        fetchContextLinkSuggestions(),
        fetchContextLinks(),
        apiGet("/v1/diagnostics/adapters").catch(() => null),
      ]);
      state.facts = facts;
      state.suggestions = suggestions;
      state.anchors = anchors;
      state.anchorMergeSuggestions = anchorMergeSuggestions;
      state.contextLinkSuggestions = contextLinkSuggestions;
      state.contextLinks = contextLinks;
      state.adapterDiagnostics = diagnostics ? diagnostics.data : null;
      state.lastRefreshAt = new Date();
      renderAll();
    } catch (error) {
      setError(error.message);
      renderStatus();
    } finally {
      state.loading = false;
    }
  }

  async function refreshSpacesAndMemoryScopes() {
    try {
      const spacesResponse = await apiGet("/v1/spaces", { params: { limit: "500" } });
      state.spaces = spacesResponse.data || [];
      renderDatalist(els.spacesList, state.spaces, (space) => space.slug);
      const selectedSpace = state.spaces.find((space) => space.slug === state.spaceSlug);
      if (!selectedSpace) {
        state.memory_scopes = [];
        renderDatalist(els.memory_scopesList, [], () => "");
        return;
      }
      const memory_scopesResponse = await apiGet("/v1/memory-scopes", {
        params: { space_id: selectedSpace.id, limit: "500" },
      });
      state.memory_scopes = memory_scopesResponse.data || [];
      renderDatalist(els.memory_scopesList, state.memory_scopes, (memory_scope) => memory_scope.external_ref);
    } catch {
      state.spaces = [];
      state.memory_scopes = [];
      renderDatalist(els.spacesList, [], () => "");
      renderDatalist(els.memory_scopesList, [], () => "");
    }
  }

  function renderDatalist(list, items, labelFor) {
    list.replaceChildren();
    for (const item of items) {
      const option = document.createElement("option");
      option.value = labelFor(item);
      list.append(option);
    }
  }

  async function fetchFacts() {
    const statuses = ["active", "superseded", "deleted"];
    const batches = await Promise.all(
      statuses.map((status) =>
        apiGet("/v1/facts", {
          params: {
            ...scopeParams(),
            status,
            limit: "500",
          },
        }).catch(() => ({ data: [] })),
      ),
    );
    const byId = new Map();
    for (const batch of batches) {
      for (const fact of batch.data || []) {
        byId.set(fact.id, fact);
      }
    }
    return [...byId.values()].sort(compareUpdatedDesc);
  }

  async function fetchSuggestions() {
    const response = await apiGet("/v1/suggestions", {
      params: {
        ...scopeParams(),
        limit: "500",
      },
    });
    return (response.data || []).sort(compareUpdatedDesc);
  }

  async function fetchAnchors() {
    const statuses = ["active", "deleted"];
    const batches = await Promise.all(
      statuses.map((status) =>
        apiGet("/v1/anchors", {
          params: {
            ...scopeParams(),
            status,
            limit: "500",
          },
        }).catch(() => ({ data: [] })),
      ),
    );
    const byId = new Map();
    for (const batch of batches) {
      for (const anchor of batch.data || []) {
        byId.set(anchor.id, anchor);
      }
    }
    return [...byId.values()].sort(compareUpdatedDesc);
  }

  async function fetchAnchorMergeSuggestions() {
    const response = await apiGet("/v1/anchors/merge-suggestions", {
      params: {
        ...scopeParams(),
        limit: "100",
      },
    }).catch(() => ({ data: { candidates: [] } }));
    return response.data?.candidates || [];
  }

  async function fetchContextLinkSuggestions() {
    const statuses = ["pending", "approved", "rejected", "expired"];
    const batches = await Promise.all(
      statuses.map((status) =>
        apiGet("/v1/context-link-suggestions", {
          params: {
            ...scopeParams(),
            status,
            limit: "200",
          },
        }).catch(() => ({ data: [] })),
      ),
    );
    const byId = new Map();
    for (const batch of batches) {
      for (const suggestion of batch.data || []) {
        byId.set(suggestion.id, suggestion);
      }
    }
    return [...byId.values()].sort(compareUpdatedDesc);
  }

  async function fetchContextLinks() {
    const statuses = ["active", "deleted"];
    const batches = await Promise.all(
      statuses.map((status) =>
        apiGet("/v1/context-links", {
          params: {
            ...scopeParams(),
            status,
            limit: "200",
          },
        }),
      ),
    );
    const byId = new Map();
    for (const response of batches) {
      for (const link of response.data || []) {
        byId.set(link.id, link);
      }
    }
    return [...byId.values()].sort(compareUpdatedDesc);
  }

  async function buildDigest() {
    readSettingsFromInputs();
    saveSettings();
    setError("");
    setText(els.digestOutput, "Building digest...");
    try {
      const response = await apiJson("/v1/digest", {
        method: "POST",
        body: {
          ...scopeBody(),
          topic: state.topic,
          token_budget: 2400,
          max_facts: 24,
          max_chunks: 18,
          max_suggestions: 16,
          include_pending_suggestions: true,
        },
      });
      const data = response.data || {};
      setText(els.digestOutput, data.rendered_markdown || "Digest is empty.");
    } catch (error) {
      setText(els.digestOutput, "Digest failed.");
      setError(error.message);
    }
  }

  async function backfillAnchors() {
    readSettingsFromInputs();
    saveSettings();
    setError("");
    try {
      await apiJson("/v1/anchors/backfill", {
        method: "POST",
        body: {
          ...scopeBody(),
          limit_per_source: 100,
        },
      });
      await refreshAll();
      const firstAnchor = state.anchors.find((anchor) => anchor.status === "active");
      if (firstAnchor) {
        selectNode(`anchor:${firstAnchor.id}`);
      }
    } catch (error) {
      setError(error.message);
    }
  }

  async function createAnchor() {
    readSettingsFromInputs();
    saveSettings();
    const kind = window.prompt("anchor kind: person, event or project", "person");
    if (kind === null) {
      return;
    }
    const label = window.prompt("anchor label", "");
    if (label === null) {
      return;
    }
    const cleanLabel = label.trim();
    if (!cleanLabel) {
      setError("Anchor label is required.");
      return;
    }
    const aliasesInput = window.prompt("aliases, comma separated", "");
    if (aliasesInput === null) {
      return;
    }
    const description = window.prompt("description", "");
    if (description === null) {
      return;
    }
    setError("");
    try {
      const response = await apiJson("/v1/anchors", {
        method: "POST",
        body: withoutEmpty({
          ...scopeBody(),
          kind: kind.trim(),
          label: cleanLabel,
          aliases: splitCsv(aliasesInput),
          description: description.trim(),
          metadata: { ui_created: true },
        }),
      });
      await refreshAll();
      const anchorId = response.data?.id;
      if (anchorId) {
        selectNode(`anchor:${anchorId}`);
      }
    } catch (error) {
      setError(error.message);
    }
  }

  async function editAnchor(anchor) {
    const label = window.prompt("anchor label", anchor.label || "");
    if (label === null) {
      return;
    }
    const cleanLabel = label.trim();
    if (!cleanLabel) {
      setError("Anchor label is required.");
      return;
    }
    const aliasesInput = window.prompt(
      "aliases, comma separated",
      aliasesWithoutLabel(anchor).join(", "),
    );
    if (aliasesInput === null) {
      return;
    }
    const description = window.prompt("description", anchor.description || "");
    if (description === null) {
      return;
    }
    setError("");
    try {
      await apiJson(`/v1/anchors/${encodeURIComponent(anchor.id)}`, {
        method: "PATCH",
        body: withoutEmpty({
          label: cleanLabel,
          aliases: splitCsv(aliasesInput),
          description: description.trim(),
          metadata: { ui_edited: true },
        }),
      });
      await refreshAll();
      selectNode(`anchor:${anchor.id}`);
    } catch (error) {
      setError(error.message);
    }
  }

  async function deleteAnchor(anchor) {
    const reason = window.prompt("delete reason", "deleted in Memo Stack Browser");
    if (reason === null) {
      return;
    }
    setError("");
    try {
      await apiJson(`/v1/anchors/${encodeURIComponent(anchor.id)}`, {
        method: "DELETE",
        body: { reason: reason || "deleted in Memo Stack Browser" },
      });
      await refreshAll();
      selectNode(null);
    } catch (error) {
      setError(error.message);
    }
  }

  async function mergeAnchorSuggestion(candidate) {
    const reason = window.prompt("merge reason", "same anchor confirmed in Memo Stack Browser");
    if (reason === null) {
      return;
    }
    setError("");
    try {
      await apiJson(`/v1/anchors/${encodeURIComponent(candidate.source_anchor.id)}/merge`, {
        method: "POST",
        body: {
          target_anchor_id: candidate.target_anchor.id,
          reason: reason || "same anchor confirmed in Memo Stack Browser",
        },
      });
      await refreshAll();
      selectNode(`anchor:${candidate.target_anchor.id}`);
    } catch (error) {
      setError(error.message);
    }
  }

  async function splitAnchorAlias(anchor) {
    const aliases = anchor.aliases || [];
    const defaultAlias = aliasesWithoutLabel(anchor)[0] || "";
    const alias = window.prompt("alias to split", defaultAlias);
    if (alias === null) {
      return;
    }
    const cleanAlias = alias.trim();
    if (!cleanAlias) {
      setError("Anchor split requires an alias.");
      return;
    }
    const newLabel = window.prompt("new anchor label", cleanAlias);
    if (newLabel === null) {
      return;
    }
    const reason = window.prompt("split reason", "split alias in Memo Stack Browser");
    if (reason === null) {
      return;
    }
    setError("");
    try {
      const response = await apiJson(`/v1/anchors/${encodeURIComponent(anchor.id)}/split`, {
        method: "POST",
        body: withoutEmpty({
          alias: cleanAlias,
          new_label: newLabel.trim(),
          reason: reason || "split alias in Memo Stack Browser",
        }),
      });
      await refreshAll();
      const splitAnchorId = response.data?.id;
      if (splitAnchorId) {
        selectNode(`anchor:${splitAnchorId}`);
      }
    } catch (error) {
      setError(error.message);
    }
  }

  async function runRecall() {
    readSettingsFromInputs();
    saveSettings();
    els.recallOutput.replaceChildren();
    setError("");
    try {
      const response = await apiJson("/v1/search", {
        method: "POST",
        body: {
          ...scopeBody(),
          query: state.topic,
          token_budget: 1600,
          max_facts: 12,
          max_chunks: 12,
        },
      });
      const items = response.data?.items || [];
      if (!items.length) {
        els.recallOutput.append(emptyItem("No recall results."));
        return;
      }
      for (const item of items) {
        els.recallOutput.append(
          listItem({
            title: `${item.item_type} ${scoreLabel(item.score)}`,
            text: item.text,
            meta: item.item_id,
            onClick: () => selectNode(`${item.item_type}:${item.item_id}`),
          }),
        );
      }
    } catch (error) {
      els.recallOutput.append(emptyItem("Recall failed."));
      setError(error.message);
    }
  }

  async function reviewSuggestion(action, suggestionId) {
    const reason = window.prompt(`${action} reason`, `Reviewed in Memo Stack Browser`);
    if (reason === null) {
      return;
    }
    setError("");
    try {
      await apiJson(`/v1/suggestions/${encodeURIComponent(suggestionId)}/${action}`, {
        method: "POST",
        body: { reason: reason || `Reviewed in Memo Stack Browser` },
      });
      await refreshAll();
    } catch (error) {
      setError(error.message);
    }
  }

  async function reviewContextLinkSuggestion(action, suggestionId, overrides = {}) {
    let reason = overrides.reason;
    if (!Object.hasOwn(overrides, "reason")) {
      reason = window.prompt(`${action} link reason`, `Reviewed in Memo Stack Browser`);
      if (reason === null) {
        return;
      }
    }
    setError("");
    try {
      await apiJson(`/v1/context-link-suggestions/${encodeURIComponent(suggestionId)}/review`, {
        method: "POST",
        body: withoutEmpty({
          action,
          reason: reason || `Reviewed in Memo Stack Browser`,
          target_type: overrides.target_type,
          target_id: overrides.target_id,
          relation_type: overrides.relation_type,
          confidence: overrides.confidence,
          link_reason: overrides.link_reason,
        }),
      });
      await refreshAll();
    } catch (error) {
      setError(error.message);
    }
  }

  async function createManualContextLink(payload) {
    const body = withoutEmpty({
      ...scopeBody(),
      source_type: payload.source_type,
      source_id: payload.source_id,
      target_type: payload.target_type,
      target_id: payload.target_id,
      relation_type: payload.relation_type || "related_to",
      confidence: payload.confidence || "medium",
      reason: payload.reason,
      metadata: {
        created_from: "memory_browser_manual",
      },
    });
    if (
      !body.source_type ||
      !body.source_id ||
      !body.target_type ||
      !body.target_id ||
      !body.reason
    ) {
      setError("Manual link requires source, target, and reason.");
      return;
    }
    setError("");
    try {
      const response = await apiJson("/v1/context-links", {
        method: "POST",
        body,
      });
      await refreshAll();
      const linkId = response.data?.id;
      if (linkId) {
        selectNode(`context_link:${linkId}`);
      }
    } catch (error) {
      setError(error.message);
    }
  }

  async function deleteContextLink(linkId) {
    if (!window.confirm("Delete this context link?")) {
      return;
    }
    setError("");
    try {
      await apiJson(`/v1/context-links/${encodeURIComponent(linkId)}`, {
        method: "DELETE",
      });
      await refreshAll();
    } catch (error) {
      setError(error.message);
    }
  }

  function apiUrl(path, params = {}) {
    const base = state.apiBase || window.location.origin;
    const url = new URL(path, base.endsWith("/") ? base : `${base}/`);
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, value);
      }
    }
    return url;
  }

  async function apiGet(path, options = {}) {
    return apiJson(path, { ...options, method: "GET" });
  }

  async function apiJson(path, options = {}) {
    const headers = { Accept: "application/json" };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    if (state.token) {
      headers.Authorization = `Bearer ${state.token}`;
    }
    const response = await window.fetch(apiUrl(path, options.params), {
      method: options.method || "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json().catch(() => ({}))
      : {};
    if (!response.ok) {
      const detail = payload.detail || payload.error || response.statusText;
      throw new Error(`${response.status} ${path}: ${safeDetail(detail)}`);
    }
    return payload;
  }

  function scopeParams() {
    return {
      space_slug: state.spaceSlug,
      memory_scope_external_ref: state.memoryScopeRef,
    };
  }

  function scopeBody() {
    return {
      space_slug: state.spaceSlug,
      memory_scope_external_ref: state.memoryScopeRef,
    };
  }

  function renderAll() {
    updateScopeSummary();
    renderStatus();
    renderMetrics();
    buildGraphData();
    renderGraph();
    renderDetails();
    renderSuggestionList();
    renderTimeline();
  }

  function renderStatus() {
    const healthOk = state.health?.status === "ok";
    setStatusChip(
      els.serverStatus,
      healthOk ? "Server ok" : "Server degraded",
      healthOk ? "ok" : "bad",
    );
    const adapters = state.capabilities?.adapters || {};
    const adapterNames = Object.keys(adapters);
    const healthyCount = adapterNames.filter((name) => adapters[name]?.healthy).length;
    const enabledCount = adapterNames.filter((name) => adapters[name]?.enabled).length;
    const adapterText = adapterNames.length
      ? `${healthyCount}/${enabledCount || adapterNames.length} adapters`
      : "Adapters unknown";
    setStatusChip(els.adapterStatus, adapterText, healthyCount ? "ok" : "warn");
    updateLiveStatus();
  }

  function updateLiveStatus() {
    setStatusChip(els.liveStatus, state.paused ? "Paused" : "Live", state.paused ? "warn" : "ok");
  }

  function setStatusChip(element, text, statusClass) {
    element.textContent = text;
    element.className = `status-chip ${statusClass}`;
  }

  function renderMetrics() {
    const sourceIds = new Set();
    for (const fact of state.facts) {
      for (const ref of fact.source_refs || []) {
        sourceIds.add(sourceKey(ref));
      }
    }
    for (const suggestion of state.suggestions) {
      for (const ref of suggestion.source_refs || []) {
        sourceIds.add(sourceKey(ref));
      }
    }
    for (const suggestion of state.contextLinkSuggestions) {
      sourceIds.add(`${suggestion.source_type}:${suggestion.source_id}`);
    }
    const activeContextLinks = state.contextLinks.filter((link) => link.status === "active");
    const activeAnchors = state.anchors.filter((anchor) => anchor.status === "active");
    for (const link of activeContextLinks) {
      sourceIds.add(`${link.source_type}:${link.source_id}`);
    }
    setText(els.factCount, String(state.facts.length));
    setText(els.suggestionCount, String(state.suggestions.length));
    setText(els.linkSuggestionCount, String(state.contextLinkSuggestions.length));
    setText(els.contextLinkCount, String(activeContextLinks.length));
    setText(els.anchorCount, String(activeAnchors.length));
    setText(els.sourceCount, String(sourceIds.size));
    setText(
      els.pendingCount,
      String(
        state.suggestions.filter((suggestion) => suggestion.status === "pending").length +
          state.contextLinkSuggestions.filter((suggestion) => suggestion.status === "pending").length,
      ),
    );
    setText(els.lastRefresh, state.lastRefreshAt ? formatShortTime(state.lastRefreshAt) : "Never");
  }

  function updateScopeSummary() {
    setText(els.scopeSummary, `${state.spaceSlug || "default"} / ${state.memoryScopeRef || "default"}`);
  }

  function buildGraphData() {
    const graph = { nodes: new Map(), edges: [] };
    const relationNodes = new Set();
    const visibleMemory = [];
    const search = (els.graphSearchInput.value || "").trim().toLowerCase();
    const typeFilter = els.typeFilter.value;
    const statusFilter = els.statusFilter.value;
    const memoryItems = [
      ...state.facts.map((fact) => ({ type: "fact", item: fact, updated_at: fact.updated_at })),
      ...state.suggestions.map((suggestion) => ({
        type: "suggestion",
        item: suggestion,
        updated_at: suggestion.updated_at,
      })),
      ...state.anchors.map((anchor) => ({
        type: "anchor",
        item: anchor,
        updated_at: anchor.updated_at,
      })),
      ...state.contextLinkSuggestions.map((suggestion) => ({
        type: "context_link_suggestion",
        item: suggestion,
        updated_at: suggestion.updated_at,
      })),
      ...state.contextLinks.map((link) => ({
        type: "context_link",
        item: link,
        updated_at: link.updated_at,
      })),
    ].sort(compareUpdatedDesc);

    for (const memory of memoryItems) {
      if (visibleMemory.length >= GRAPH_NODE_LIMIT) {
        state.graphTruncated = true;
        break;
      }
      if (!memoryMatchesFilters(memory, search, typeFilter, statusFilter)) {
        continue;
      }
      visibleMemory.push(memory);
      if (memory.type === "fact") {
        addFactGraph(graph, memory.item, relationNodes);
      } else if (memory.type === "suggestion") {
        addSuggestionGraph(graph, memory.item, relationNodes);
      } else if (memory.type === "anchor") {
        addAnchorGraph(graph, memory.item, relationNodes);
      } else if (memory.type === "context_link_suggestion") {
        addContextLinkSuggestionGraph(graph, memory.item, relationNodes);
      } else {
        addContextLinkGraph(graph, memory.item, relationNodes);
      }
    }
    if (visibleMemory.length < GRAPH_NODE_LIMIT) {
      state.graphTruncated = false;
    }

    if (
      typeFilter !== "all" &&
      !["fact", "suggestion", "anchor", "context_link_suggestion", "context_link"].includes(typeFilter)
    ) {
      for (const node of [...graph.nodes.values()]) {
        if (node.type !== typeFilter && !relationNodes.has(node.id)) {
          graph.nodes.delete(node.id);
        }
      }
      graph.edges = graph.edges.filter(
        (edge) => graph.nodes.has(edge.from) && graph.nodes.has(edge.to),
      );
    }

    state.nodes = [...graph.nodes.values()];
    state.edges = graph.edges.filter((edge) => graph.nodes.has(edge.from) && graph.nodes.has(edge.to));
  }

  function addFactGraph(graph, fact, relationNodes) {
    const nodeId = `fact:${fact.id}`;
    addNode(graph, {
      id: nodeId,
      type: "fact",
      status: fact.status,
      label: compactLabel(fact.text),
      text: fact.text,
      data: fact,
      degree: 0,
    });
    addRelation(graph, nodeId, `kind:${fact.kind}`, "kind", fact.kind, relationNodes);
    if (fact.thread_id) {
      addRelation(graph, nodeId, `thread:${fact.thread_id}`, "thread", fact.thread_id, relationNodes);
    }
    for (const ref of fact.source_refs || []) {
      addSourceRelation(graph, nodeId, ref, relationNodes);
    }
  }

  function addSuggestionGraph(graph, suggestion, relationNodes) {
    const nodeId = `suggestion:${suggestion.id}`;
    addNode(graph, {
      id: nodeId,
      type: "suggestion",
      status: suggestion.status,
      label: compactLabel(suggestion.candidate_text),
      text: suggestion.candidate_text,
      data: suggestion,
      degree: 0,
    });
    addRelation(
      graph,
      nodeId,
      `status:${suggestion.status}`,
      "status",
      suggestion.status,
      relationNodes,
    );
    addRelation(graph, nodeId, `kind:${suggestion.kind}`, "kind", suggestion.kind, relationNodes);
    if (suggestion.target_fact_id) {
      const targetId = `fact:${suggestion.target_fact_id}`;
      if (!graph.nodes.has(targetId)) {
        addNode(graph, {
          id: targetId,
          type: "fact",
          status: "target",
          label: `target ${suggestion.target_fact_id.slice(0, 8)}`,
          text: suggestion.target_fact_id,
          data: { id: suggestion.target_fact_id },
          degree: 0,
        });
      }
      addEdge(graph, nodeId, targetId, "target", true);
    }
    for (const tag of suggestion.tags || []) {
      addRelation(graph, nodeId, `tag:${tag}`, "tag", tag, relationNodes);
    }
    for (const ref of suggestion.source_refs || []) {
      addSourceRelation(graph, nodeId, ref, relationNodes);
    }
  }

  function addAnchorGraph(graph, anchor, relationNodes) {
    const nodeId = `anchor:${anchor.id}`;
    addNode(graph, {
      id: nodeId,
      type: "anchor",
      status: anchor.status,
      label: compactLabel(`${anchor.kind}: ${anchor.label}`),
      text: anchor.description || anchor.label,
      data: anchor,
      degree: 0,
    });
    addRelation(graph, nodeId, `status:${anchor.status}`, "status", anchor.status, relationNodes);
    addRelation(graph, nodeId, `kind:${anchor.kind}`, "kind", anchor.kind, relationNodes);
    for (const alias of anchor.aliases || []) {
      addRelation(graph, nodeId, `alias:${anchor.kind}:${alias}`, "alias", alias, relationNodes);
    }
  }

  function addContextLinkSuggestionGraph(graph, suggestion, relationNodes) {
    const nodeId = `context_link_suggestion:${suggestion.id}`;
    const targetLabel = suggestion.metadata?.target_label || suggestion.target_type;
    addNode(graph, {
      id: nodeId,
      type: "context_link_suggestion",
      status: suggestion.status,
      label: compactLabel(`${suggestion.source_type} -> ${targetLabel}`),
      text: suggestion.reason,
      data: suggestion,
      degree: 0,
    });
    addRelation(
      graph,
      nodeId,
      `status:${suggestion.status}`,
      "status",
      suggestion.status,
      relationNodes,
    );
    addRelation(
      graph,
      nodeId,
      `relation:${suggestion.relation_type}`,
      "kind",
      suggestion.relation_type,
      relationNodes,
    );
    const sourceNodeId = contextObjectNodeId(suggestion.source_type, suggestion.source_id);
    const targetNodeId = contextObjectNodeId(suggestion.target_type, suggestion.target_id);
    addContextObjectNode(graph, sourceNodeId, suggestion.source_type, suggestion.source_id, "source");
    addContextObjectNode(
      graph,
      targetNodeId,
      suggestion.target_type,
      suggestion.target_id,
      "target",
      suggestion.metadata?.target_label,
    );
    addEdge(graph, nodeId, sourceNodeId, "source", false);
    addEdge(graph, nodeId, targetNodeId, "target", true);
    for (const reason of arrayOf(suggestion.metadata?.reasons)) {
      addRelation(graph, nodeId, `reason:${reason}`, "kind", reason, relationNodes);
    }
  }

  function addContextLinkGraph(graph, link, relationNodes) {
    const nodeId = `context_link:${link.id}`;
    addNode(graph, {
      id: nodeId,
      type: "context_link",
      status: link.status,
      label: compactLabel(`${link.source_type} -> ${link.target_type}`),
      text: link.reason,
      data: link,
      degree: 0,
    });
    addRelation(graph, nodeId, `status:${link.status}`, "status", link.status, relationNodes);
    addRelation(
      graph,
      nodeId,
      `relation:${link.relation_type}`,
      "kind",
      link.relation_type,
      relationNodes,
    );
    const sourceNodeId = contextObjectNodeId(link.source_type, link.source_id);
    const targetNodeId = contextObjectNodeId(link.target_type, link.target_id);
    addContextObjectNode(graph, sourceNodeId, link.source_type, link.source_id, "source");
    addContextObjectNode(graph, targetNodeId, link.target_type, link.target_id, "target");
    addEdge(graph, nodeId, sourceNodeId, "source", false);
    addEdge(graph, nodeId, targetNodeId, "target", true);
  }

  function contextObjectNodeId(objectType, objectId) {
    if (objectType === "fact") {
      return `fact:${objectId}`;
    }
    return `context-object:${objectType}:${objectId}`;
  }

  function addContextObjectNode(graph, nodeId, objectType, objectId, roleLabel, displayLabel = "") {
    if (graph.nodes.has(nodeId)) {
      return;
    }
    addNode(graph, {
      id: nodeId,
      type: objectType || "source",
      status: roleLabel,
      label: compactLabel(displayLabel || `${objectType}:${shortId(objectId)}`),
      text: `${objectType}:${objectId}`,
      data: { id: objectId, type: objectType, role: roleLabel },
      degree: 0,
    });
  }

  function addSourceRelation(graph, fromNodeId, ref, relationNodes) {
    const key = sourceKey(ref);
    const label = `${ref.source_type}:${ref.source_id}`;
    addRelation(graph, fromNodeId, `source:${key}`, "source", label, relationNodes);
  }

  function addRelation(graph, from, to, type, label, relationNodes) {
    relationNodes.add(to);
    addNode(graph, {
      id: to,
      type,
      status: type,
      label: compactLabel(label),
      text: String(label),
      data: { label },
      degree: 0,
    });
    addEdge(graph, from, to, type, false);
  }

  function addNode(graph, node) {
    if (!graph.nodes.has(node.id)) {
      graph.nodes.set(node.id, node);
    }
  }

  function addEdge(graph, from, to, label, strong) {
    graph.edges.push({ id: `${from}->${to}:${label}`, from, to, label, strong });
    const fromNode = graph.nodes.get(from);
    const toNode = graph.nodes.get(to);
    if (fromNode) {
      fromNode.degree += 1;
    }
    if (toNode) {
      toNode.degree += 1;
    }
  }

  function renderGraph() {
    const svg = els.graphSvg;
    const width = svg.clientWidth || 1000;
    const height = svg.clientHeight || 620;
    const scaledWidth = width * state.graphScale;
    const scaledHeight = height * state.graphScale;
    svg.setAttribute("viewBox", `0 0 ${scaledWidth} ${scaledHeight}`);
    svg.replaceChildren();

    if (!state.nodes.length) {
      const empty = svgEl("text", {
        x: scaledWidth / 2,
        y: scaledHeight / 2,
        "text-anchor": "middle",
        fill: "#64738a",
      });
      empty.textContent = "No graph data";
      svg.append(empty);
      return;
    }

    layoutGraph(scaledWidth, scaledHeight);
    const edgeLayer = svgEl("g", {});
    const nodeLayer = svgEl("g", {});
    svg.append(edgeLayer, nodeLayer);
    const positionById = new Map(state.nodes.map((node) => [node.id, state.nodePositions.get(node.id)]));

    for (const edge of state.edges) {
      const from = positionById.get(edge.from);
      const to = positionById.get(edge.to);
      if (!from || !to) {
        continue;
      }
      const line = svgEl("line", {
        class: edge.strong ? "edge strong" : "edge",
        x1: from.x,
        y1: from.y,
        x2: to.x,
        y2: to.y,
      });
      edgeLayer.append(line);
    }

    for (const node of state.nodes) {
      const pos = positionById.get(node.id);
      if (!pos) {
        continue;
      }
      const group = svgEl("g", {
        class: node.id === state.selectedNodeId ? "node selected" : "node",
        transform: `translate(${pos.x},${pos.y})`,
        "data-node-id": node.id,
        tabindex: "0",
      });
      const radius = Math.min(26, 11 + Math.sqrt(node.degree || 1) * 3.4);
      const circle = svgEl("circle", {
        r: radius,
        fill: nodeColor(node),
      });
      const label = svgEl("text", {
        x: radius + 5,
        y: 4,
      });
      label.textContent = node.label;
      const title = svgEl("title", {});
      title.textContent = `${node.type}: ${node.text}`;
      group.append(circle, label, title);
      group.addEventListener("click", () => selectNode(node.id));
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectNode(node.id);
        }
      });
      group.addEventListener("pointerdown", (event) => {
        state.dragging = { nodeId: node.id, pointerId: event.pointerId };
        group.setPointerCapture(event.pointerId);
      });
      nodeLayer.append(group);
    }
  }

  function layoutGraph(width, height) {
    const center = { x: width / 2, y: height / 2 };
    const radiusX = Math.max(180, width * 0.34);
    const radiusY = Math.max(150, height * 0.34);
    const nodes = state.nodes;
    const indexById = new Map(nodes.map((node, index) => [node.id, index]));
    for (const [index, node] of nodes.entries()) {
      if (!state.nodePositions.has(node.id)) {
        const angle = (hashCode(node.id) % 6283) / 1000;
        const ring =
          node.type === "fact" ||
          node.type === "suggestion" ||
          node.type === "context_link_suggestion" ||
          node.type === "context_link"
            ? 1
            : 0.62;
        state.nodePositions.set(node.id, {
          x: center.x + Math.cos(angle + index * 0.17) * radiusX * ring,
          y: center.y + Math.sin(angle + index * 0.17) * radiusY * ring,
        });
      }
    }

    const positions = nodes.map((node) => state.nodePositions.get(node.id));
    for (let step = 0; step < 70; step += 1) {
      for (let i = 0; i < positions.length; i += 1) {
        for (let j = i + 1; j < positions.length; j += 1) {
          const a = positions[i];
          const b = positions[j];
          const dx = a.x - b.x || 0.01;
          const dy = a.y - b.y || 0.01;
          const distanceSq = dx * dx + dy * dy;
          const force = Math.min(8, 1800 / Math.max(60, distanceSq));
          const distance = Math.sqrt(distanceSq);
          const moveX = (dx / distance) * force;
          const moveY = (dy / distance) * force;
          a.x += moveX;
          a.y += moveY;
          b.x -= moveX;
          b.y -= moveY;
        }
      }
      for (const edge of state.edges) {
        const fromIndex = indexById.get(edge.from);
        const toIndex = indexById.get(edge.to);
        if (fromIndex === undefined || toIndex === undefined) {
          continue;
        }
        const a = positions[fromIndex];
        const b = positions[toIndex];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const target = edge.strong ? 130 : 105;
        const distance = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (distance - target) * 0.015;
        const moveX = (dx / distance) * force;
        const moveY = (dy / distance) * force;
        a.x += moveX;
        a.y += moveY;
        b.x -= moveX;
        b.y -= moveY;
      }
      for (const pos of positions) {
        pos.x += (center.x - pos.x) * 0.004;
        pos.y += (center.y - pos.y) * 0.004;
        pos.x = clamp(pos.x, 40, width - 160);
        pos.y = clamp(pos.y, 40, height - 50);
      }
    }
  }

  function bindGraphPointerEvents() {
    els.graphSvg.addEventListener("pointermove", (event) => {
      if (!state.dragging) {
        return;
      }
      const point = svgPoint(event);
      state.nodePositions.set(state.dragging.nodeId, point);
      renderGraph();
    });
    els.graphSvg.addEventListener("pointerup", () => {
      state.dragging = null;
    });
    els.graphSvg.addEventListener("pointercancel", () => {
      state.dragging = null;
    });
  }

  function svgPoint(event) {
    const svg = els.graphSvg;
    const rect = svg.getBoundingClientRect();
    const viewBox = svg.viewBox.baseVal;
    return {
      x: ((event.clientX - rect.left) / rect.width) * viewBox.width + viewBox.x,
      y: ((event.clientY - rect.top) / rect.height) * viewBox.height + viewBox.y,
    };
  }

  function selectNode(nodeId) {
    state.selectedNodeId = nodeId;
    renderGraph();
    renderDetails();
    activateTab("details");
  }

  function renderDetails() {
    const panel = els.detailsPanel;
    panel.replaceChildren();
    const node = state.nodes.find((candidate) => candidate.id === state.selectedNodeId) || preferredNode();
    if (!node) {
      panel.append(emptyItem("Select a memory node."));
      return;
    }
    state.selectedNodeId = node.id;
    const title = document.createElement("h2");
    title.className = "detail-title";
    title.textContent = nodeTitle(node);
    const meta = document.createElement("div");
    meta.className = "detail-meta";
    meta.append(pill(node.type), pill(node.status || "n/a", statusClass(node.status)));
    if (node.data?.kind) {
      meta.append(pill(node.data.kind));
    }
    if (node.data?.confidence) {
      meta.append(pill(`confidence ${node.data.confidence}`));
    }
    const text = document.createElement("div");
    text.className = "text-block";
    text.textContent = node.text || "";
    panel.append(title, meta, text);
    if (node.type === "fact" || node.type === "suggestion") {
      panel.append(sourceSection(node.data?.source_refs || []));
    }
    if (node.type === "anchor") {
      panel.append(anchorSection(node.data));
    }
    if (node.type === "anchor" && node.data?.status === "active" && (node.data?.aliases || []).length) {
      const actions = document.createElement("div");
      actions.className = "action-row";
      actions.append(
        actionButton("Edit Anchor", () => editAnchor(node.data), "primary-button"),
        actionButton("Split Alias", () => splitAnchorAlias(node.data)),
        actionButton("Delete Anchor", () => deleteAnchor(node.data)),
      );
      panel.append(actions);
    }
    if (node.type === "context_link_suggestion") {
      panel.append(contextLinkSuggestionSection(node.data));
    }
    if (node.type === "context_link") {
      panel.append(contextLinkSection(node.data));
    }
    if (node.type === "context_link" && node.data?.status === "active") {
      const actions = document.createElement("div");
      actions.className = "action-row one-action";
      actions.append(actionButton("Delete Link", () => deleteContextLink(node.data.id)));
      panel.append(actions);
    }
    if (node.type === "suggestion" && node.data?.status === "pending") {
      const actions = document.createElement("div");
      actions.className = "action-row";
      actions.append(
        actionButton("Approve", () => reviewSuggestion("approve", node.data.id), "primary-button"),
        actionButton("Reject", () => reviewSuggestion("reject", node.data.id)),
        actionButton("Expire", () => reviewSuggestion("expire", node.data.id)),
      );
      panel.append(actions);
    }
    if (node.type === "context_link_suggestion" && node.data?.status === "pending") {
      const actions = document.createElement("div");
      actions.className = "action-row two-actions";
      actions.append(
        actionButton(
          "Approve",
          () => reviewContextLinkSuggestion("approve", node.data.id),
          "primary-button",
        ),
        actionButton("Reject", () => reviewContextLinkSuggestion("reject", node.data.id)),
      );
      panel.append(actions);
      panel.append(contextLinkEditForm(node.data));
    }
  }

  function contextLinkSuggestionSection(suggestion) {
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
      keyValueItem("Reason", suggestion.reason),
      keyValueItem("Target preview", suggestion.metadata?.target_preview || ""),
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

  function anchorSection(anchor) {
    const section = document.createElement("section");
    section.className = "source-list";
    const heading = document.createElement("h3");
    heading.className = "detail-title";
    heading.textContent = "Anchor";
    const metadataReason = anchor.metadata?.reason || anchor.metadata?.canonical_key || "";
    section.append(heading);
    section.append(
      keyValueItem("Kind", anchor.kind),
      keyValueItem("Key", anchor.normalized_key),
      keyValueItem("Aliases", (anchor.aliases || []).join(", ") || "none"),
      keyValueItem("Description", anchor.description || ""),
      keyValueItem("Metadata", metadataReason),
      keyValueItem("Updated", formatDate(anchor.updated_at)),
    );
    return section;
  }

  function contextLinkSection(link) {
    const section = document.createElement("section");
    section.className = "source-list";
    const heading = document.createElement("h3");
    heading.className = "detail-title";
    heading.textContent = "Link";
    section.append(heading);
    section.append(
      keyValueItem("Source", `${link.source_type}:${link.source_id}`),
      keyValueItem("Target", `${link.target_type}:${link.target_id}`),
      keyValueItem("Relation", link.relation_type),
      keyValueItem("Reason", link.reason),
      keyValueItem("Created", formatDate(link.created_at)),
    );
    if (link.metadata?.approved_from_suggestion_id) {
      section.append(
        keyValueItem("Approved from", String(link.metadata.approved_from_suggestion_id)),
      );
    }
    return section;
  }

  function keyValueItem(title, text) {
    return listItem({
      title,
      text,
    });
  }

  function contextLinkEditForm(suggestion) {
    const form = document.createElement("section");
    form.className = "edit-form";
    const heading = document.createElement("h3");
    heading.className = "detail-title";
    heading.textContent = "Edit target";
    const targetType = formInput("Target type", suggestion.target_type);
    const targetId = formInput("Target id", suggestion.target_id);
    const relationType = formInput("Relation", suggestion.relation_type);
    const confidence = formSelect("Confidence", ["low", "medium", "high"], suggestion.confidence);
    const linkReason = formInput("Link reason", suggestion.reason);
    const reviewNote = formInput("Review note", "approved with edited target");
    const submit = actionButton(
      "Approve With Edits",
      () =>
        reviewContextLinkSuggestion("approve", suggestion.id, {
          reason: reviewNote.input.value.trim() || "approved with edited target",
          target_type: targetType.input.value.trim(),
          target_id: targetId.input.value.trim(),
          relation_type: relationType.input.value.trim(),
          confidence: confidence.input.value,
          link_reason: linkReason.input.value.trim(),
        }),
      "primary-button",
    );
    form.append(
      heading,
      targetType.element,
      targetId.element,
      relationType.element,
      confidence.element,
      linkReason.element,
      reviewNote.element,
      submit,
    );
    return form;
  }

  function manualContextLinkForm() {
    const form = document.createElement("section");
    form.className = "edit-form manual-link-form";
    const heading = document.createElement("h3");
    heading.className = "detail-title";
    heading.textContent = "Manual Link";
    const sourceType = formSelect("Source type", CONTEXT_ENDPOINT_TYPES, "capture");
    const sourceId = formInput("Source id", "");
    const targetType = formSelect("Target type", CONTEXT_ENDPOINT_TYPES, "fact");
    const targetId = formInput("Target id", "");
    const relationType = formInput("Relation", "related_to");
    const confidence = formSelect("Confidence", ["low", "medium", "high"], "medium");
    const reason = formInput("Reason", "manual reviewer link");
    const useSelectedSource = actionButton("Use Selected Source", () => {
      applyEndpointToForm(selectedContextEndpoint(), sourceType.input, sourceId.input);
    });
    const useSelectedTarget = actionButton("Use Selected Target", () => {
      applyEndpointToForm(selectedContextEndpoint(), targetType.input, targetId.input);
    });
    const submit = actionButton(
      "Create Link",
      () =>
        createManualContextLink({
          source_type: sourceType.input.value.trim(),
          source_id: sourceId.input.value.trim(),
          target_type: targetType.input.value.trim(),
          target_id: targetId.input.value.trim(),
          relation_type: relationType.input.value.trim(),
          confidence: confidence.input.value,
          reason: reason.input.value.trim(),
        }),
      "primary-button",
    );
    const actions = document.createElement("div");
    actions.className = "action-row";
    actions.append(useSelectedSource, useSelectedTarget, submit);
    form.append(
      heading,
      sourceType.element,
      sourceId.element,
      targetType.element,
      targetId.element,
      relationType.element,
      confidence.element,
      reason.element,
      actions,
    );
    return form;
  }

  function selectedContextEndpoint() {
    const node = state.nodes.find((candidate) => candidate.id === state.selectedNodeId);
    if (!node) {
      return null;
    }
    if (!CONTEXT_ENDPOINT_TYPES.includes(node.type)) {
      return null;
    }
    const type = node.data?.type || node.type;
    const id = node.data?.id;
    if (!type || !id || !CONTEXT_ENDPOINT_TYPES.includes(type)) {
      return null;
    }
    return { type, id };
  }

  function applyEndpointToForm(endpoint, typeInput, idInput) {
    if (!endpoint) {
      setError("Selected node cannot be used as a context link endpoint.");
      return;
    }
    typeInput.value = endpoint.type;
    idInput.value = endpoint.id;
    setError("");
  }

  function formInput(labelText, value) {
    const label = document.createElement("label");
    const span = document.createElement("span");
    span.textContent = labelText;
    const input = document.createElement("input");
    input.value = value || "";
    label.append(span, input);
    return { element: label, input };
  }

  function formSelect(labelText, values, selected) {
    const label = document.createElement("label");
    const span = document.createElement("span");
    span.textContent = labelText;
    const input = document.createElement("select");
    for (const value of values) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      option.selected = value === selected;
      input.append(option);
    }
    label.append(span, input);
    return { element: label, input };
  }

  function sourceSection(sourceRefs) {
    const section = document.createElement("section");
    section.className = "source-list";
    const heading = document.createElement("h3");
    heading.className = "detail-title";
    heading.textContent = "Sources";
    section.append(heading);
    if (!sourceRefs.length) {
      section.append(emptyItem("No source refs."));
      return section;
    }
    for (const ref of sourceRefs) {
      section.append(
        listItem({
          title: `${ref.source_type}:${ref.source_id}`,
          text: ref.quote_preview || ref.chunk_id || "source ref",
          meta: ref.chunk_id || "",
          onClick: () => selectNode(`source:${sourceKey(ref)}`),
        }),
      );
    }
    return section;
  }

  function renderSuggestionList() {
    els.suggestionList.replaceChildren();
    els.suggestionList.append(manualContextLinkForm());
    if (!state.anchorMergeSuggestions.length && !state.contextLinkSuggestions.length && !state.suggestions.length) {
      els.suggestionList.append(emptyItem("No review items."));
      return;
    }
    if (state.anchorMergeSuggestions.length) {
      els.suggestionList.append(sectionLabel("Anchor merge reviews"));
    }
    for (const candidate of state.anchorMergeSuggestions.slice(0, 80)) {
      const item = listItem({
        title: `${candidate.source_anchor.label} -> ${candidate.target_anchor.label} / ${candidate.confidence}`,
        text: (candidate.reasons || []).join(", ") || "possible duplicate anchor",
        meta: `${scoreLabel(candidate.score)} ${candidate.source_anchor.kind}`,
        onClick: () => selectNode(`anchor:${candidate.source_anchor.id}`),
      });
      const actions = document.createElement("div");
      actions.className = "action-row one-action";
      actions.append(
        actionButton("Merge", () => mergeAnchorSuggestion(candidate), "primary-button"),
      );
      item.append(actions);
      els.suggestionList.append(item);
    }
    if (state.contextLinkSuggestions.length) {
      els.suggestionList.append(sectionLabel("Link reviews"));
    }
    for (const suggestion of state.contextLinkSuggestions.slice(0, 160)) {
      const item = listItem({
        title: `${suggestion.source_type} -> ${suggestion.target_type} / ${suggestion.status}`,
        text: suggestion.metadata?.target_preview || suggestion.reason,
        meta: `${scoreLabel(suggestion.score)} ${formatDate(suggestion.updated_at)}`,
        onClick: () => selectNode(`context_link_suggestion:${suggestion.id}`),
      });
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
        item.append(actions);
      }
      els.suggestionList.append(item);
    }
    if (state.suggestions.length) {
      els.suggestionList.append(sectionLabel("Fact suggestions"));
    }
    for (const suggestion of state.suggestions.slice(0, 160)) {
      const item = listItem({
        title: `${suggestion.operation} / ${suggestion.status}`,
        text: suggestion.candidate_text,
        meta: formatDate(suggestion.updated_at),
        onClick: () => selectNode(`suggestion:${suggestion.id}`),
      });
      if (suggestion.status === "pending") {
        const actions = document.createElement("div");
        actions.className = "action-row";
        actions.append(
          actionButton("Approve", () => reviewSuggestion("approve", suggestion.id), "primary-button"),
          actionButton("Reject", () => reviewSuggestion("reject", suggestion.id)),
          actionButton("Expire", () => reviewSuggestion("expire", suggestion.id)),
        );
        item.append(actions);
      }
      els.suggestionList.append(item);
    }
  }

  function renderTimeline() {
    els.timelineList.replaceChildren();
    const items = [
      ...state.facts.map((fact) => ({
        id: `fact:${fact.id}`,
        title: `fact / ${fact.status}`,
        text: fact.text,
        updated_at: fact.updated_at,
      })),
      ...state.suggestions.map((suggestion) => ({
        id: `suggestion:${suggestion.id}`,
        title: `suggestion / ${suggestion.status}`,
        text: suggestion.candidate_text,
        updated_at: suggestion.updated_at,
      })),
      ...state.anchors.map((anchor) => ({
        id: `anchor:${anchor.id}`,
        title: `anchor / ${anchor.status}`,
        text: `${anchor.kind}: ${anchor.label}`,
        updated_at: anchor.updated_at,
      })),
      ...state.contextLinkSuggestions.map((suggestion) => ({
        id: `context_link_suggestion:${suggestion.id}`,
        title: `link review / ${suggestion.status}`,
        text: `${suggestion.source_type}:${shortId(suggestion.source_id)} -> ${suggestion.target_type}:${shortId(
          suggestion.target_id,
        )}`,
        updated_at: suggestion.updated_at,
      })),
      ...state.contextLinks.map((link) => ({
        id: `context_link:${link.id}`,
        title: `link / ${link.status}`,
        text: `${link.source_type}:${shortId(link.source_id)} -> ${link.target_type}:${shortId(
          link.target_id,
        )}`,
        updated_at: link.updated_at,
      })),
    ].sort(compareUpdatedDesc);
    if (!items.length) {
      els.timelineList.append(emptyItem("No timeline entries."));
      return;
    }
    for (const item of items.slice(0, 220)) {
      els.timelineList.append(
        listItem({
          title: item.title,
          text: item.text,
          meta: formatDate(item.updated_at),
          onClick: () => selectNode(item.id),
        }),
      );
    }
  }

  function preferredNode() {
    return (
      state.nodes.find((node) => node.type === "context_link_suggestion" && node.status === "pending") ||
      state.nodes.find((node) => node.type === "context_link" && node.status === "active") ||
      state.nodes.find((node) => node.type === "anchor" && node.status === "active") ||
      state.nodes.find((node) => node.type === "suggestion" && node.status === "pending") ||
      state.nodes.find((node) => node.type === "fact") ||
      state.nodes[0]
    );
  }

  function memoryMatchesFilters(memory, search, typeFilter, statusFilter) {
    if (
      typeFilter !== "all" &&
      memory.type !== typeFilter &&
      ["fact", "suggestion", "anchor", "context_link_suggestion", "context_link"].includes(typeFilter)
    ) {
      return false;
    }
    const status = memory.item.status || "";
    if (statusFilter !== "all" && status !== statusFilter) {
      return false;
    }
    if (!search) {
      return true;
    }
    const haystack = [
      memory.item.text,
      memory.item.candidate_text,
      memory.item.kind,
      memory.item.label,
      memory.item.normalized_key,
      memory.item.description,
      memory.item.status,
      memory.item.operation,
      memory.item.source_type,
      memory.item.source_id,
      memory.item.target_type,
      memory.item.target_id,
      memory.item.reason,
      memory.item.relation_type,
      memory.item.metadata?.target_label,
      memory.item.metadata?.target_preview,
      ...(memory.item.tags || []),
      ...(memory.item.aliases || []),
      ...arrayOf(memory.item.metadata?.reasons),
      ...arrayOf(memory.item.metadata?.matched_terms),
      ...(memory.item.source_refs || []).map((ref) => `${ref.source_type}:${ref.source_id}`),
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(search);
  }

  function nodeTitle(node) {
    if (node.type === "fact") {
      return `Fact ${node.data?.id || ""}`.trim();
    }
    if (node.type === "suggestion") {
      return `Suggestion ${node.data?.id || ""}`.trim();
    }
    if (node.type === "anchor") {
      return `Anchor ${node.data?.label || node.data?.id || ""}`.trim();
    }
    if (node.type === "context_link_suggestion") {
      return `Link review ${node.data?.id || ""}`.trim();
    }
    if (node.type === "context_link") {
      return `Link ${node.data?.id || ""}`.trim();
    }
    return `${node.type}: ${node.text}`;
  }

  function nodeColor(node) {
    if (node.type === "fact") {
      if (node.status === "deleted") {
        return "#c2413b";
      }
      if (node.status === "superseded") {
        return "#8b96a8";
      }
      return "#2563eb";
    }
    if (node.type === "suggestion") {
      if (node.status === "pending") {
        return "#c76b14";
      }
      if (node.status === "approved") {
        return "#16835f";
      }
      if (node.status === "rejected") {
        return "#8b96a8";
      }
      return "#7c3aed";
    }
    if (node.type === "context_link_suggestion") {
      if (node.status === "pending") {
        return "#0e7490";
      }
      if (node.status === "approved") {
        return "#16835f";
      }
      if (node.status === "rejected") {
        return "#8b96a8";
      }
      return "#64738a";
    }
    if (node.type === "context_link") {
      return node.status === "active" ? "#16835f" : "#64738a";
    }
    if (node.type === "anchor") {
      if (node.status === "deleted") {
        return "#8b96a8";
      }
      if (node.data?.kind === "person") {
        return "#7c3aed";
      }
      if (node.data?.kind === "project") {
        return "#0e7490";
      }
      if (node.data?.kind === "event") {
        return "#c76b14";
      }
      return "#16835f";
    }
    if (node.type === "thread") {
      return "#7c3aed";
    }
    if (node.type === "document" || node.type === "chunk") {
      return "#2563eb";
    }
    if (node.type === "asset" || node.type === "capture") {
      return "#0e7490";
    }
    if (node.type === "source") {
      return "#0e7490";
    }
    if (node.type === "tag") {
      return "#7c3aed";
    }
    if (node.type === "kind") {
      return "#16835f";
    }
    if (node.type === "status") {
      return "#c76b14";
    }
    return "#64738a";
  }

  function statusClass(status) {
    if (status === "active" || status === "approved" || status === "target") {
      return "green";
    }
    if (status === "pending" || status === "source") {
      return "orange";
    }
    if (status === "deleted" || status === "rejected") {
      return "red";
    }
    if (status === "expired" || status === "superseded") {
      return "purple";
    }
    return "";
  }

  function activateTab(name) {
    for (const tab of document.querySelectorAll(".tabs button")) {
      tab.classList.toggle("active", tab.dataset.tab === name);
    }
    for (const panel of document.querySelectorAll(".tab-panel")) {
      panel.classList.toggle("active", panel.id === `${name}Panel`);
    }
  }

  function listItem({ title, text, meta, onClick }) {
    const item = document.createElement("div");
    item.className = "list-item";
    if (onClick) {
      item.tabIndex = 0;
      item.setAttribute("role", "button");
      item.addEventListener("click", onClick);
      item.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onClick();
        }
      });
    }
    const titleEl = document.createElement("div");
    titleEl.className = "list-item-title";
    titleEl.textContent = title || "";
    const textEl = document.createElement("div");
    textEl.className = "list-item-text";
    textEl.textContent = text || "";
    item.append(titleEl, textEl);
    if (meta) {
      const metaEl = document.createElement("div");
      metaEl.className = "pill";
      metaEl.textContent = meta;
      item.append(metaEl);
    }
    return item;
  }

  function sectionLabel(text) {
    const element = document.createElement("div");
    element.className = "section-label";
    element.textContent = text;
    return element;
  }

  function emptyItem(text) {
    const item = document.createElement("div");
    item.className = "empty-state";
    item.textContent = text;
    return item;
  }

  function pill(text, className = "") {
    const element = document.createElement("span");
    element.className = className ? `pill ${className}` : "pill";
    element.textContent = text || "n/a";
    return element;
  }

  function shortId(value) {
    const text = String(value || "");
    return text.length > 12 ? text.slice(0, 8) : text;
  }

  function actionButton(text, handler, className = "") {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    if (className) {
      button.className = className;
    }
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      void handler();
    });
    return button;
  }

  function setError(message) {
    els.errorOutput.textContent = message || "";
  }

  function setText(element, text) {
    element.textContent = text;
  }

  function svgEl(name, attrs) {
    const element = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (const [key, value] of Object.entries(attrs)) {
      element.setAttribute(key, String(value));
    }
    return element;
  }

  function compactLabel(value) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    return text.length > 42 ? `${text.slice(0, 39)}...` : text || "n/a";
  }

  function sourceKey(ref) {
    return `${ref.source_type || "unknown"}:${ref.source_id || "unknown"}:${ref.chunk_id || ""}`;
  }

  function compareUpdatedDesc(a, b) {
    const aTime = Date.parse(a.updated_at || a.item?.updated_at || 0);
    const bTime = Date.parse(b.updated_at || b.item?.updated_at || 0);
    return bTime - aTime;
  }

  function formatShortTime(date) {
    return new Intl.DateTimeFormat(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(date);
  }

  function formatDate(value) {
    if (!value) {
      return "";
    }
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value));
  }

  function scoreLabel(score) {
    return typeof score === "number" ? score.toFixed(2) : "n/a";
  }

  function arrayOf(value) {
    return Array.isArray(value) ? value : [];
  }

  function aliasesWithoutLabel(anchor) {
    const label = String(anchor?.label || "").toLowerCase();
    return arrayOf(anchor?.aliases).filter((item) => String(item).toLowerCase() !== label);
  }

  function splitCsv(value) {
    return String(value || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function withoutEmpty(payload) {
    return Object.fromEntries(
      Object.entries(payload).filter(([_key, value]) => value !== undefined && value !== null && value !== ""),
    );
  }

  function safeDetail(detail) {
    if (typeof detail === "string") {
      return detail;
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return String(detail);
    }
  }

  function hashCode(value) {
    let hash = 0;
    for (let index = 0; index < value.length; index += 1) {
      hash = (hash << 5) - hash + value.charCodeAt(index);
      hash |= 0;
    }
    return Math.abs(hash);
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }
})();
