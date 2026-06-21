(() => {
  "use strict";

  window.infinityContextCapture = {
    bindCaptureEvents,
    cancelExtractionJob,
    requestExtractionForAsset,
    retryExtractionJob,
    saveQuickCapture,
    uploadAssetEvidence,
  };

  document.addEventListener("DOMContentLoaded", bindCaptureEvents);

  function browser() {
    return window.infinityContextBrowser;
  }

  function bindCaptureEvents() {
    const { els } = browser();
    els.saveCaptureButton.addEventListener("click", () => void saveQuickCapture());
    els.uploadAssetButton.addEventListener("click", () => void uploadAssetEvidence());
  }

  async function saveQuickCapture() {
    const { apiJson, els, readSettingsFromInputs, saveSettings, scopeBody, selectNode, setError } =
      browser();
    readSettingsFromInputs();
    saveSettings();
    const text = els.captureTextInput.value.trim();
    if (!text) {
      setCaptureStatus("Quick note text is required.");
      return;
    }
    setError("");
    setCaptureStatus("Saving note...");
    try {
      const response = await apiJson("/v1/captures", {
        method: "POST",
        body: {
          ...scopeBody(),
          source_agent: "memory_browser",
          source_kind: "manual",
          event_type: "memory_browser.quick_note",
          actor_role: "user",
          text,
          source_event_id: `memory-browser:${Date.now()}:${randomSuffix()}`,
          client_instance_id: "memory-browser-ui",
          trust_level: "medium",
          source_authority: "user",
          sensitivity: "medium",
          data_classification: "internal",
          metadata: withoutEmpty({
            topic: browser().state.topic,
            ui_created: true,
          }),
          consolidate: els.captureConsolidateInput.checked,
        },
      });
      els.captureTextInput.value = "";
      await browser().refreshAll({ silent: true });
      const capture = response.data || {};
      setCaptureStatus(
        `Note saved. ${capture.created_suggestions || 0} review suggestions created.`,
      );
      if (capture.id) {
        selectNode(`capture:${capture.id}`);
      }
    } catch (error) {
      setCaptureStatus("Note save failed.");
      setError(error.message);
    }
  }

  async function uploadAssetEvidence() {
    const { els, readSettingsFromInputs, saveSettings, scopeParams, selectNode, setError } =
      browser();
    readSettingsFromInputs();
    saveSettings();
    const file = els.assetFileInput.files?.[0];
    if (!file) {
      setCaptureStatus("Choose a file first.");
      return;
    }
    setError("");
    setCaptureStatus(`Uploading ${file.name || "file"}...`);
    try {
      const params = withoutEmpty({
        ...scopeParams(),
        filename: file.name || "upload.bin",
        content_type: file.type || "application/octet-stream",
        classification: "internal",
        extract: els.assetExtractInput.checked ? "true" : "false",
        parser_profile: els.assetParserProfileInput.value.trim(),
      });
      const response = await apiRaw("/v1/assets", {
        method: "POST",
        params,
        body: file,
        contentType: file.type || "application/octet-stream",
      });
      els.assetFileInput.value = "";
      await browser().refreshAll({ silent: true });
      const asset = response.data || {};
      const extraction = asset.extraction;
      const duplicateText = asset.duplicate ? " Duplicate detected." : "";
      const extractionText = extraction
        ? ` Extraction ${extraction.status}.`
        : asset.extraction_error
          ? ` Extraction skipped: ${asset.extraction_error.message || asset.extraction_error.code}.`
          : "";
      setCaptureStatus(`File uploaded.${duplicateText}${extractionText}`);
      if (extraction?.id) {
        selectNode(`extraction_job:${extraction.id}`);
      } else if (asset.id) {
        selectNode(`asset:${asset.id}`);
      }
    } catch (error) {
      setCaptureStatus("File upload failed.");
      setError(error.message);
    }
  }

  async function requestExtractionForAsset(assetId) {
    const { apiJson, selectNode, setError } = browser();
    setError("");
    setCaptureStatus("Queueing extraction...");
    try {
      const response = await apiJson(`/v1/assets/${encodeURIComponent(assetId)}/extractions`, {
        method: "POST",
      });
      await browser().refreshAll({ silent: true });
      const job = response.data || {};
      setCaptureStatus(`Extraction queued: ${job.status || "pending"}.`);
      if (job.id) {
        selectNode(`extraction_job:${job.id}`);
      }
    } catch (error) {
      setCaptureStatus("Extraction request failed.");
      setError(error.message);
    }
  }

  async function retryExtractionJob(jobId) {
    const { apiJson, selectNode, setError } = browser();
    setError("");
    setCaptureStatus("Retrying extraction...");
    try {
      const response = await apiJson(`/v1/asset-extractions/${encodeURIComponent(jobId)}/retry`, {
        method: "POST",
      });
      await browser().refreshAll({ silent: true });
      const job = response.data || {};
      setCaptureStatus(`Extraction retry queued: ${job.status || "pending"}.`);
      if (job.id) {
        selectNode(`extraction_job:${job.id}`);
      }
    } catch (error) {
      setCaptureStatus("Extraction retry failed.");
      setError(error.message);
    }
  }

  async function cancelExtractionJob(jobId) {
    const { apiJson, selectNode, setError } = browser();
    setError("");
    setCaptureStatus("Canceling extraction...");
    try {
      const response = await apiJson(`/v1/asset-extractions/${encodeURIComponent(jobId)}/cancel`, {
        method: "POST",
      });
      await browser().refreshAll({ silent: true });
      const job = response.data || {};
      setCaptureStatus(`Extraction cancel requested: ${job.status || "pending"}.`);
      if (job.id) {
        selectNode(`extraction_job:${job.id}`);
      }
    } catch (error) {
      setCaptureStatus("Extraction cancel failed.");
      setError(error.message);
    }
  }

  async function apiRaw(path, options = {}) {
    const { state } = browser();
    const headers = {
      Accept: "application/json",
      "Content-Type": options.contentType || "application/octet-stream",
    };
    if (state.token) {
      headers.Authorization = `Bearer ${state.token}`;
    }
    const response = await window.fetch(apiUrl(path, options.params), {
      method: options.method || "POST",
      headers,
      body: options.body,
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

  function apiUrl(path, params = {}) {
    const { state } = browser();
    const base = state.apiBase || window.location.origin;
    const url = new URL(path, base.endsWith("/") ? base : `${base}/`);
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, value);
      }
    }
    return url;
  }

  function setCaptureStatus(message) {
    const { els } = browser();
    els.captureStatusOutput.textContent = message || "";
    els.captureStatusOutput.classList.toggle("empty-state", !message);
  }

  function randomSuffix() {
    if (window.crypto?.getRandomValues) {
      const bytes = new Uint32Array(1);
      window.crypto.getRandomValues(bytes);
      return bytes[0].toString(36);
    }
    return Math.random().toString(36).slice(2, 10);
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
})();
