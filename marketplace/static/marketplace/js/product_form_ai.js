/**
 * product_form_ai.js
 * ------------------
 * Producer quality workflow:
 * - Add page: preview-only scan for unsaved listings.
 * - Edit page: batch intake scan + atomic batch commit (AI or manual).
 */
document.addEventListener("DOMContentLoaded", function () {
  /* ── Helpers ────────────────────────────────────────────── */
  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  function makeIdempotencyKey() {
    if (window.crypto && window.crypto.randomUUID) {
      return window.crypto.randomUUID();
    }
    return `fallback-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function getScanButtonLabel(isCreateMode) {
    return isCreateMode ? "🤖 AI Preview Scan" : "🤖 AI Quality Scan";
  }

  function getLotQuantity() {
    if (!lotQuantityInput) return null;
    const parsed = parseInt(lotQuantityInput.value, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }

  function getBatchScanFiles() {
    if (!batchImagesInput || !batchImagesInput.files) {
      return [];
    }
    return Array.from(batchImagesInput.files);
  }

  function showInlineMessage(type, title, message) {
    const palettes = {
      error: {
        wrapper: "#fef2f2",
        border: "#fca5a5",
        title: "#991b1b",
        text: "#7f1d1d",
      },
      warn: {
        wrapper: "#fffbeb",
        border: "#fde68a",
        title: "#92400e",
        text: "#78350f",
      },
      info: {
        wrapper: "#eff6ff",
        border: "#bfdbfe",
        title: "#1e40af",
        text: "#1e3a8a",
      },
      success: {
        wrapper: "#f0fdf4",
        border: "#bbf7d0",
        title: "#166534",
        text: "#14532d",
      },
    };

    const palette = palettes[type] || palettes.info;
    resultsPanel.innerHTML = `
      <div style="background:${palette.wrapper}; border:1px solid ${palette.border}; border-radius:8px; padding:16px; margin-top:16px;">
        <p style="color:${palette.title}; font-weight:bold; margin:0 0 4px;">${title}</p>
        <p style="color:${palette.text}; margin:0; font-size:13px;">${message}</p>
      </div>`;
    resultsPanel.classList.remove("hidden");
  }

  /* ── DOM references ─────────────────────────────────────── */
  const aiBtn = document.getElementById("ai-scan-btn");
  const manualEntryBtn = document.getElementById("ai-manual-entry-btn");
  const resultsPanel = document.getElementById("ai-results-panel");
  const imageInput = document.querySelector('input[type="file"]');
  const productForm = aiBtn ? aiBtn.closest("form") : null;
  const startBatchScanField = document.getElementById("start-batch-scan-field");
  const batchIntakePanel = document.getElementById("batch-intake-panel");
  const lotQuantityInput = document.getElementById("batch-intake-quantity");
  const modelNameSelect = document.getElementById("ai-model-name-select");
  const modelVersionSelect = document.getElementById("ai-model-version-select");
  const modelSelectionHint = document.getElementById("ai-model-selection-hint");
  const useExistingStockCheckbox = document.getElementById(
    "batch-use-existing-stock",
  );
  const batchImagesInput = document.getElementById("batch-intake-images");

  if (!aiBtn || !resultsPanel || !imageInput || !productForm) return;

  /* ── State ──────────────────────────────────────────────── */
  let currentLogId = null;
  let inFlightCommitKey = null;
  const modelCatalog = new Map();
  const currentProductId = aiBtn.dataset.productId || "";
  const productHasImage = aiBtn.dataset.hasImage === "1";
  const unbatchedStockQuantity = Math.max(
    parseInt(aiBtn.dataset.unbatchedStock || "0", 10) || 0,
    0,
  );
  const prefillFromCreate = aiBtn.dataset.prefillFromCreate === "1";
  const isCreateMode = !currentProductId;

  function setModelHint(message, isWarning = false) {
    if (!modelSelectionHint) return;
    modelSelectionHint.textContent = message;
    modelSelectionHint.style.color = isWarning ? "#92400e" : "#64748b";
  }

  function resetModelVersionOptions(disabled = true) {
    if (!modelVersionSelect) return;
    modelVersionSelect.innerHTML =
      '<option value="">Auto (active version for selected model)</option>';
    modelVersionSelect.disabled = disabled;
  }

  function refreshModelVersionOptions() {
    if (!modelNameSelect || !modelVersionSelect) return;

    const selectedModelName = (modelNameSelect.value || "").trim();
    if (!selectedModelName) {
      resetModelVersionOptions(true);
      setModelHint(
        "Leave blank to use the latest activated model. Choose a model name to pin scans.",
      );
      return;
    }

    const versions = [...(modelCatalog.get(selectedModelName) || [])];
    versions.sort((left, right) => {
      if (left.is_active !== right.is_active) {
        return left.is_active ? -1 : 1;
      }
      return (right.created_at || "").localeCompare(left.created_at || "");
    });

    modelVersionSelect.disabled = false;
    modelVersionSelect.innerHTML =
      '<option value="">Auto (active version for selected model)</option>';

    versions.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.model_version;
      option.textContent = item.is_active
        ? `${item.model_version} (active)`
        : item.model_version;
      modelVersionSelect.appendChild(option);
    });

    const activeVersion = versions.find((item) => item.is_active);
    if (activeVersion) {
      setModelHint(
        `Active version for ${selectedModelName}: ${activeVersion.model_version}`,
      );
    } else {
      setModelHint(
        `No active version found for ${selectedModelName}. Choose a version explicitly or activate one in AI Lifecycle.`,
        true,
      );
    }
  }

  async function loadModelChoices() {
    if (!modelNameSelect || !modelVersionSelect || !modelSelectionHint) {
      return;
    }

    setModelHint("Loading available models...");
    modelNameSelect.disabled = true;
    resetModelVersionOptions(true);

    try {
      const response = await fetch("/api/ai/producer-quality/models/", {
        method: "GET",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`Server returned ${response.status}`);
      }

      const payload = await response.json();
      const items = Array.isArray(payload)
        ? payload
        : Array.isArray(payload.results)
          ? payload.results
          : [];

      modelCatalog.clear();
      items.forEach((item) => {
        if (!item || !item.model_name || !item.model_version) {
          return;
        }
        const existing = modelCatalog.get(item.model_name) || [];
        existing.push(item);
        modelCatalog.set(item.model_name, existing);
      });

      modelNameSelect.innerHTML =
        '<option value="">Auto (latest activated)</option>';
      [...modelCatalog.keys()]
        .sort((left, right) => left.localeCompare(right))
        .forEach((modelName) => {
          const option = document.createElement("option");
          option.value = modelName;

          const versions = modelCatalog.get(modelName) || [];
          const activeCount = versions.filter((item) => item.is_active).length;
          option.textContent =
            activeCount > 0
              ? `${modelName} (${activeCount} active)`
              : modelName;

          modelNameSelect.appendChild(option);
        });

      modelNameSelect.disabled = false;
      resetModelVersionOptions(true);

      if (items.length === 0) {
        setModelHint(
          "No model versions available yet. Upload and activate a model in AI Lifecycle first.",
          true,
        );
      } else {
        setModelHint(
          "Choose a model to pin scans. Leave both fields blank to use the latest activated model.",
        );
      }
    } catch (error) {
      modelNameSelect.disabled = false;
      resetModelVersionOptions(true);
      setModelHint(
        "Could not load model choices. Scans will still work using automatic active-model selection.",
        true,
      );
    }
  }

  function scrollToBatchIntakePanel() {
    if (!batchIntakePanel) {
      return;
    }
    window.setTimeout(() => {
      batchIntakePanel.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 120);
  }

  function shouldAllocateFromExistingStock() {
    return Boolean(
      useExistingStockCheckbox &&
      useExistingStockCheckbox.checked &&
      unbatchedStockQuantity > 0,
    );
  }

  function validateAllocationSelection(lotQuantity, msgEl) {
    if (!shouldAllocateFromExistingStock()) {
      return true;
    }

    if (lotQuantity > unbatchedStockQuantity) {
      if (msgEl) {
        msgEl.innerHTML = `<div style="background:#fffbeb; border:1px solid #fde68a; border-radius:6px; padding:10px; color:#92400e; font-size:13px;">Lot quantity exceeds available ungraded stock (${unbatchedStockQuantity}). Lower the quantity or untick existing-stock allocation.</div>`;
      }
      return false;
    }

    return true;
  }

  aiBtn.textContent = getScanButtonLabel(isCreateMode);

  const pageUrl = new URL(window.location.href);
  const autoScanRequested = pageUrl.searchParams.get("auto_ai_scan") === "1";
  if (autoScanRequested) {
    pageUrl.searchParams.delete("auto_ai_scan");
    const cleanQuery = pageUrl.searchParams.toString();
    const cleanUrl = cleanQuery
      ? `${pageUrl.pathname}?${cleanQuery}`
      : pageUrl.pathname;
    window.history.replaceState({}, "", cleanUrl);
  }

  if (modelNameSelect) {
    modelNameSelect.addEventListener("change", refreshModelVersionOptions);
  }
  loadModelChoices();

  /* ── Button handlers ────────────────────────────────────── */
  aiBtn.addEventListener("click", async function (e) {
    e.preventDefault();
    await runScan({ autoTriggered: false });
  });

  if (manualEntryBtn && !isCreateMode) {
    manualEntryBtn.addEventListener("click", function (e) {
      e.preventDefault();
      renderManualEntryPanel();
    });
  }

  if (autoScanRequested && !isCreateMode) {
    if (prefillFromCreate && lotQuantityInput && !lotQuantityInput.value) {
      lotQuantityInput.value = String(unbatchedStockQuantity);
    }
    scrollToBatchIntakePanel();
    runScan({ autoTriggered: true });
  }

  async function runScan({ autoTriggered = false } = {}) {
    const lotQuantity = getLotQuantity();
    if (!isCreateMode && !lotQuantity) {
      scrollToBatchIntakePanel();
      showInlineMessage(
        "warn",
        "Lot Quantity Required",
        "Enter the lot quantity before running a batch intake scan.",
      );
      return;
    }

    const batchFiles = getBatchScanFiles();
    const hasListingImageSelection = Boolean(
      imageInput.files && imageInput.files.length > 0,
    );
    const hasSelectedImage = hasListingImageSelection || batchFiles.length > 0;
    const canUseSavedImage = Boolean(
      currentProductId && productHasImage && !hasSelectedImage,
    );

    if (!hasSelectedImage && !canUseSavedImage) {
      if (autoTriggered) {
        showInlineMessage(
          "warn",
          "AI Batch Scan Not Started",
          "No image is saved for this product yet. Upload an image and run AI Quality Scan.",
        );
      } else {
        showInlineMessage(
          "warn",
          "Image Required",
          "Select at least one image (or use a saved product image) before running the AI scan.",
        );
      }
      return;
    }

    const selectedModelName = modelNameSelect
      ? (modelNameSelect.value || "").trim()
      : "";
    const selectedModelVersion = modelVersionSelect
      ? (modelVersionSelect.value || "").trim()
      : "";

    if (selectedModelVersion && !selectedModelName) {
      showInlineMessage(
        "warn",
        "Model Selection Incomplete",
        "Select a model name before selecting a specific model version.",
      );
      return;
    }

    aiBtn.disabled = true;
    aiBtn.textContent = "Scanning…";
    resultsPanel.classList.add("hidden");

    if (autoTriggered) {
      scrollToBatchIntakePanel();
      showInlineMessage(
        "info",
        "Running Batch Intake Scan",
        "Saved listing detected. Running batch-linked scan using the product's saved image.",
      );
    }

    const formData = new FormData();
    if (batchFiles.length > 0) {
      batchFiles.forEach((file) => {
        formData.append("images", file);
      });
      formData.append("image", batchFiles[0]);
    } else if (hasListingImageSelection) {
      formData.append("image", imageInput.files[0]);
    }

    formData.append("scan_mode", isCreateMode ? "preview" : "batch_intake");
    if (!isCreateMode && lotQuantity) {
      formData.append("lot_quantity", String(lotQuantity));
    }
    if (currentProductId) {
      formData.append("product_id", currentProductId);
    }
    if (selectedModelName) {
      formData.append("model_name", selectedModelName);
    }
    if (selectedModelVersion) {
      formData.append("model_version", selectedModelVersion);
    }

    try {
      const resp = await fetch("/api/ai/producer-quality/predict/", {
        method: "POST",
        headers: { "X-CSRFToken": getCsrfToken() },
        body: formData,
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Server returned ${resp.status}`);
      }

      const data = await resp.json();
      currentLogId = data.id;
      renderResults(data);
    } catch (err) {
      showInlineMessage("error", "AI Scan Failed", err.message);
    } finally {
      aiBtn.disabled = false;
      aiBtn.textContent = getScanButtonLabel(isCreateMode);
    }
  }

  /* ── Render the XAI results panel ───────────────────────── */
  function renderResults(data) {
    const previewMode = isCreateMode;
    const xai = data.explanation_payload || {};
    const scores = xai.score_breakdown || {};
    const gradeDerivation = xai.grade_derivation || "";
    const recDerivation = xai.recommendation_derivation || "";
    const colorScoreValue =
      scores.color != null ? parseFloat(scores.color).toFixed(1) : "N/A";
    const sizeScoreValue =
      scores.size != null ? parseFloat(scores.size).toFixed(1) : "N/A";
    const ripenessScoreValue =
      scores.ripeness != null ? parseFloat(scores.ripeness).toFixed(1) : "N/A";

    // Grade badge colour
    const gradeColors = { A: "#15803d", B: "#ca8a04", C: "#dc2626" };
    const gradeColor = gradeColors[data.authoritative_grade] || "#6b7280";

    resultsPanel.innerHTML = `
            <div style="background:white; border:1px solid #d1d5db; border-radius:10px; padding:20px; margin-top:16px; box-shadow:0 2px 8px rgba(0,0,0,0.06);">

                <!-- Header -->
                <div style="display:flex; align-items:center; gap:12px; margin-bottom:16px;">
                    <span style="font-size:28px;">🤖</span>
                    <div>
                    <h3 style="margin:0; font-size:16px; font-weight:bold; color:#111;">${previewMode ? "AI Quality Preview" : "AI Quality Assessment"}</h3>
                        <p style="margin:2px 0 0; font-size:12px; color:#6b7280;">Model ${data.model_name_used || "produce-quality"} v${data.model_version_used || "unknown"} · Confidence ${parseFloat(data.confidence || 0).toFixed(1)}%</p>
                    </div>
                    <div style="margin-left:auto; display:flex; align-items:center; gap:12px;">
                        <span style="background:#f3f4f6; color:#374151; font-weight:bold; font-size:14px; padding:6px 12px; border-radius:16px; border:1px solid #d1d5db; text-transform:capitalize;">
                            ${(data.predicted_class || "Unknown").replace(/_/g, " ")}
                        </span>
                        <span style="background:${gradeColor}; color:white; font-weight:bold; font-size:22px; width:44px; height:44px; border-radius:50%; display:flex; align-items:center; justify-content:center;">
                            ${data.authoritative_grade || "?"}
                        </span>
                    </div>
                </div>

                <!-- Score Bars -->
                <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; margin-bottom:14px;">
                    ${scoreBar("Colour", scores.color)}
                    ${scoreBar("Size", scores.size)}
                    ${scoreBar("Ripeness", scores.ripeness)}
                </div>

                <!-- XAI Derivation -->
                <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:6px; padding:10px 14px; margin-bottom:10px; font-size:13px; color:#166534;">
                    <strong>Grade Derivation:</strong> ${gradeDerivation}
                </div>
                <div style="background:#fffbeb; border:1px solid #fde68a; border-radius:6px; padding:10px 14px; margin-bottom:12px; font-size:13px; color:#92400e;">
                    <strong>Recommendation:</strong> ${data.recommendation_action || "N/A"}<br>
                    <span style="font-size:12px; color:#78350f;">${recDerivation}</span>
                </div>

                <!-- Academic Disclosure Note -->
                <div style="margin-bottom:16px; font-size:12px; color:#6b7280; font-style:italic; padding-left:4px; border-left:3px solid #d1d5db;">
                    <strong>Note on Stock:</strong> This AI assessment serves as a <em>representative sample grade</em> for the entire listed batch. For the most accurate batch grading, ensure the image captures a fair representation of the total stock.
                </div>

                ${
                  previewMode
                    ? `
                <div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:6px; padding:10px 14px; margin-bottom:12px; font-size:13px; color:#1e40af; font-weight:600;">
                  Preview only: this scan is not yet linked to a saved product batch.
                </div>`
                    : ""
                }

                <!-- Action Buttons -->
                <div style="display:flex; gap:10px; flex-wrap:wrap;">
                    <button type="button" id="ai-accept-btn"
                        style="flex:1; padding:10px; background:#15803d; color:white; border:none; border-radius:6px; font-weight:bold; cursor:pointer; font-size:14px; transition:background .2s;">
                    ✓ Accept &amp; Create Batch
                    </button>
                    <button type="button" id="ai-override-toggle"
                        style="flex:1; padding:10px; background:#f5f5f5; color:#333; border:1px solid #d1d5db; border-radius:6px; font-weight:bold; cursor:pointer; font-size:14px; transition:background .2s;">
                    ✎ Manual Grade Entry
                    </button>
                  <button type="button" id="ai-save-continue-btn"
                    style="display:none; width:100%; padding:10px; background:#1e40af; color:white; border:none; border-radius:6px; font-weight:bold; cursor:pointer; font-size:14px; transition:background .2s;">
                    Save Listing &amp; Start Batch Scan
                  </button>
                </div>

                <!-- Override Panel (hidden by default) -->
                <div id="ai-override-panel" style="display:none; margin-top:14px; background:#fafafa; border:1px solid #e5e7eb; border-radius:8px; padding:14px;">
                  <p style="margin:0 0 10px; font-size:12px; color:#6b7280;">
                    AI scores: Colour ${colorScoreValue} · Size ${sizeScoreValue} · Ripeness ${ripenessScoreValue}
                  </p>
                  <p style="margin:0 0 12px; font-size:12px; color:#6b7280;">
                    Adjust any score you disagree with. The grade will auto-calculate when a score is overridden.
                  </p>
                  <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px;">
                    <div>
                      <label style="font-weight:bold; font-size:13px; display:block; margin-bottom:6px;">Colour accepted?</label>
                      <select id="ai-override-color-accepted" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px; font-size:14px;">
                        <option value="true">Yes</option>
                        <option value="false">No</option>
                      </select>
                    </div>
                    <div>
                      <label style="font-weight:bold; font-size:13px; display:block; margin-bottom:6px;">Override Colour (0-100)</label>
                      <input id="ai-override-color" type="number" step="0.01" placeholder="0-100"
                        style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px; font-size:14px; box-sizing:border-box;" />
                    </div>
                  </div>
                  <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px;">
                    <div>
                      <label style="font-weight:bold; font-size:13px; display:block; margin-bottom:6px;">Size accepted?</label>
                      <select id="ai-override-size-accepted" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px; font-size:14px;">
                        <option value="true">Yes</option>
                        <option value="false">No</option>
                      </select>
                    </div>
                    <div>
                      <label style="font-weight:bold; font-size:13px; display:block; margin-bottom:6px;">Override Size (0-100)</label>
                      <input id="ai-override-size" type="number" step="0.01" placeholder="0-100"
                        style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px; font-size:14px; box-sizing:border-box;" />
                    </div>
                  </div>
                  <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px;">
                    <div>
                      <label style="font-weight:bold; font-size:13px; display:block; margin-bottom:6px;">Ripeness accepted?</label>
                      <select id="ai-override-ripeness-accepted" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px; font-size:14px;">
                        <option value="true">Yes</option>
                        <option value="false">No</option>
                      </select>
                    </div>
                    <div>
                      <label style="font-weight:bold; font-size:13px; display:block; margin-bottom:6px;">Override Ripeness (0-100)</label>
                      <input id="ai-override-ripeness" type="number" step="0.01" placeholder="0-100"
                        style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px; font-size:14px; box-sizing:border-box;" />
                    </div>
                  </div>
                  <label style="font-weight:bold; font-size:13px; display:block; margin-bottom:6px;">Your Grade (optional)</label>
                  <select id="ai-override-grade" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px; margin-bottom:10px; font-size:14px;">
                    <option value="">Auto-calculate from overrides</option>
                    <option value="A">A – Premium</option>
                    <option value="B">B – Standard</option>
                    <option value="C">C – Economy</option>
                  </select>
                  <label style="font-weight:bold; font-size:13px; display:block; margin-bottom:6px;">Reason for override:</label>
                  <textarea id="ai-override-reason" rows="2"
                    style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px; font-size:14px; box-sizing:border-box;"
                    placeholder="e.g. Product was freshly harvested today"></textarea>
                  <button type="button" id="ai-override-submit"
                    style="margin-top:10px; width:100%; padding:10px; background:#ca8a04; color:white; border:none; border-radius:6px; font-weight:bold; cursor:pointer; font-size:14px;">
                    Create Manual Batch
                  </button>
                </div>

                <!-- Status message area -->
                <div id="ai-feedback-msg" style="margin-top:10px;"></div>
            </div>`;

    resultsPanel.classList.remove("hidden");

    const acceptBtn = document.getElementById("ai-accept-btn");
    const overrideToggle = document.getElementById("ai-override-toggle");
    const saveContinueBtn = document.getElementById("ai-save-continue-btn");

    if (!previewMode) {
      acceptBtn.addEventListener("click", submitAiCommit);

      overrideToggle.addEventListener("click", function () {
        const panel = document.getElementById("ai-override-panel");
        panel.style.display = panel.style.display === "none" ? "block" : "none";
      });

      document
        .getElementById("ai-override-submit")
        .addEventListener("click", function () {
          const grade = document.getElementById("ai-override-grade").value;
          const reason = document
            .getElementById("ai-override-reason")
            .value.trim();
          if (!reason) {
            alert("Please provide a reason for the override.");
            return;
          }
          submitManualCommit(grade, reason);
        });
    } else {
      saveContinueBtn.style.display = "block";
      saveContinueBtn.addEventListener("click", submitForBatchScan);

      acceptBtn.disabled = true;
      acceptBtn.style.opacity = "0.6";
      acceptBtn.style.cursor = "not-allowed";

      overrideToggle.disabled = true;
      overrideToggle.style.opacity = "0.6";
      overrideToggle.style.cursor = "not-allowed";

      const msgEl = document.getElementById("ai-feedback-msg");
      msgEl.innerHTML = `<div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:6px; padding:10px; color:#1e40af; font-size:13px; font-weight:600;">
                Save the listing, then continue to an automatic batch-linked scan.</div>`;
    }
  }

  function renderManualEntryPanel() {
    if (isCreateMode) {
      showInlineMessage(
        "info",
        "Manual Grade Entry",
        "Manual batch grading is available after the listing is saved.",
      );
      return;
    }

    resultsPanel.innerHTML = `
      <div style="background:white; border:1px solid #d1d5db; border-radius:10px; padding:20px; margin-top:16px; box-shadow:0 2px 8px rgba(0,0,0,0.06);">
        <h3 style="margin:0 0 10px; font-size:16px; font-weight:bold; color:#111;">Manual Grade Entry</h3>
        <p style="margin:0 0 12px; font-size:13px; color:#374151;">Use this path to create a lot without AI grading.</p>
        <label style="font-weight:bold; font-size:13px; display:block; margin-bottom:6px;">Grade</label>
        <select id="manual-grade-select" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px; margin-bottom:10px; font-size:14px;">
          <option value="A">A – Premium</option>
          <option value="B">B – Standard</option>
          <option value="C">C – Economy</option>
        </select>
        <label style="font-weight:bold; font-size:13px; display:block; margin-bottom:6px;">Reason</label>
        <textarea id="manual-grade-reason" rows="2" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px; font-size:14px; box-sizing:border-box;" placeholder="Why this lot should be graded manually"></textarea>
        <button type="button" id="manual-grade-submit" style="margin-top:10px; width:100%; padding:10px; background:#ca8a04; color:white; border:none; border-radius:6px; font-weight:bold; cursor:pointer; font-size:14px;">
          Create Manual Batch
        </button>
        <div id="ai-feedback-msg" style="margin-top:10px;"></div>
      </div>`;
    resultsPanel.classList.remove("hidden");

    const submitBtn = document.getElementById("manual-grade-submit");
    submitBtn.addEventListener("click", function () {
      const grade = document.getElementById("manual-grade-select").value;
      const reason = document
        .getElementById("manual-grade-reason")
        .value.trim();
      if (!reason) {
        alert("Please provide a reason for the manual grade.");
        return;
      }
      submitManualCommit(grade, reason);
    });
  }

  function submitForBatchScan() {
    if (startBatchScanField) {
      startBatchScanField.value = "1";
    }

    if (!productForm.reportValidity()) {
      if (startBatchScanField) {
        startBatchScanField.value = "";
      }
      return;
    }

    productForm.submit();
  }

  /* ── Score bar helper ───────────────────────────────────── */
  function scoreBar(label, value) {
    const pct = value != null ? parseFloat(value).toFixed(1) : "–";
    const barWidth = value != null ? Math.min(parseFloat(value), 100) : 0;
    const barColor =
      barWidth >= 80 ? "#22c55e" : barWidth >= 65 ? "#eab308" : "#ef4444";
    return `
            <div>
                <div style="display:flex; justify-content:space-between; font-size:12px; font-weight:600; color:#374151; margin-bottom:3px;">
                    <span>${label}</span><span>${pct}%</span>
                </div>
                <div style="background:#e5e7eb; border-radius:999px; height:8px; overflow:hidden;">
                    <div style="width:${barWidth}%; height:100%; background:${barColor}; border-radius:999px; transition:width .4s;"></div>
                </div>
            </div>`;
  }

  function getOverrideAttributes() {
    const colorAccepted = document.getElementById("ai-override-color-accepted");
    const colorScore = document.getElementById("ai-override-color");
    const sizeAccepted = document.getElementById("ai-override-size-accepted");
    const sizeScore = document.getElementById("ai-override-size");
    const ripenessAccepted = document.getElementById(
      "ai-override-ripeness-accepted",
    );
    const ripenessScore = document.getElementById("ai-override-ripeness");

    if (!colorAccepted || !sizeAccepted || !ripenessAccepted) {
      return null;
    }

    return {
      color_accepted: colorAccepted.value === "true",
      size_accepted: sizeAccepted.value === "true",
      ripeness_accepted: ripenessAccepted.value === "true",
      override_color_score:
        colorScore && colorScore.value !== "" ? Number(colorScore.value) : null,
      override_size_score:
        sizeScore && sizeScore.value !== "" ? Number(sizeScore.value) : null,
      override_ripeness_score:
        ripenessScore && ripenessScore.value !== ""
          ? Number(ripenessScore.value)
          : null,
    };
  }

  async function maybeLogAiRejection(
    overrideGrade,
    overrideReason,
    attributeOverrides,
  ) {
    if (!currentLogId) {
      return null;
    }

    const body = {
      inference_log_id: currentLogId,
      accepted_recommendation: false,
      override_reason: overrideReason,
      ...(attributeOverrides || {}),
    };

    if (overrideGrade) {
      body.override_grade = overrideGrade;
    }

    const resp = await fetch("/api/ai/producer-quality/override/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify(body),
    });

    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(payload.detail || "Failed to log AI rejection");
    }
    return payload;
  }

  async function commitIntake(payload) {
    const msgEl = document.getElementById("ai-feedback-msg");
    const idempotencyKey = inFlightCommitKey || makeIdempotencyKey();
    inFlightCommitKey = idempotencyKey;

    const requestBody = {
      ...payload,
      product_id: parseInt(currentProductId, 10),
      idempotency_key: idempotencyKey,
    };

    const resp = await fetch("/api/ai/producer-quality/intake/commit/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify(requestBody),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to create batch");
    }

    const batchData = await resp.json();
    if (msgEl) {
      msgEl.innerHTML = `<div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:6px; padding:10px; color:#166534; font-size:13px; font-weight:600;">
        ✓ Batch Created! Grade ${batchData.grade} lot generated with a ${batchData.discount_percent}% discount. Final Price: £${batchData.final_price}<br>
        <span style="font-weight:500;">Refreshing batch table…</span></div>`;
    }

    const acceptBtn = document.getElementById("ai-accept-btn");
    const overrideBtn = document.getElementById("ai-override-submit");
    if (acceptBtn) {
      acceptBtn.disabled = true;
      acceptBtn.style.opacity = "0.5";
    }
    if (overrideBtn) {
      overrideBtn.disabled = true;
      overrideBtn.style.opacity = "0.5";
    }

    inFlightCommitKey = null;
    window.setTimeout(() => {
      window.location.reload();
    }, 450);

    return batchData;
  }

  async function submitAiCommit() {
    const msgEl = document.getElementById("ai-feedback-msg");
    if (!currentLogId) {
      if (msgEl) {
        msgEl.innerHTML = `<div style="background:#fef2f2; border:1px solid #fca5a5; border-radius:6px; padding:10px; color:#991b1b; font-size:13px;">Run an AI scan before accepting.</div>`;
      }
      return;
    }

    const lotQuantity = getLotQuantity();
    if (!lotQuantity) {
      if (msgEl) {
        msgEl.innerHTML = `<div style="background:#fffbeb; border:1px solid #fde68a; border-radius:6px; padding:10px; color:#92400e; font-size:13px;">Enter lot quantity before committing the batch.</div>`;
      }
      return;
    }

    try {
      if (!validateAllocationSelection(lotQuantity, msgEl)) {
        return;
      }

      await commitIntake({
        lot_quantity: lotQuantity,
        allocate_from_unbatched: shouldAllocateFromExistingStock(),
        grade_source: "ai",
        inference_log_id: currentLogId,
        accept_recommendation: true,
      });
    } catch (err) {
      if (msgEl) {
        msgEl.innerHTML = `<div style="background:#fef2f2; border:1px solid #fca5a5; border-radius:6px; padding:10px; color:#991b1b; font-size:13px;">Commit failed: ${err.message}</div>`;
      }
      inFlightCommitKey = null;
    }
  }

  async function submitManualCommit(grade, reason) {
    const msgEl = document.getElementById("ai-feedback-msg");
    const lotQuantity = getLotQuantity();

    if (!lotQuantity) {
      if (msgEl) {
        msgEl.innerHTML = `<div style="background:#fffbeb; border:1px solid #fde68a; border-radius:6px; padding:10px; color:#92400e; font-size:13px;">Enter lot quantity before creating a manual batch.</div>`;
      }
      return;
    }

    try {
      if (!validateAllocationSelection(lotQuantity, msgEl)) {
        return;
      }

      const attributeOverrides = getOverrideAttributes();
      const overrideEvent = await maybeLogAiRejection(
        grade,
        reason,
        attributeOverrides,
      );

      const computedGrade = overrideEvent && overrideEvent.override_grade;
      const finalGrade = computedGrade || grade;
      if (!finalGrade) {
        throw new Error(
          "Select a manual grade or override at least one AI attribute to compute a grade.",
        );
      }

      await commitIntake({
        lot_quantity: lotQuantity,
        allocate_from_unbatched: shouldAllocateFromExistingStock(),
        grade_source: "manual",
        manual_grade: finalGrade,
        manual_reason: reason,
        ...(currentLogId ? { inference_log_id: currentLogId } : {}),
      });

      if (msgEl && !currentLogId) {
        msgEl.innerHTML = `<div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:6px; padding:10px; color:#166534; font-size:13px; font-weight:600;">
          ✓ Manual batch created successfully.</div>`;
      }
    } catch (err) {
      if (msgEl) {
        msgEl.innerHTML = `<div style="background:#fef2f2; border:1px solid #fca5a5; border-radius:6px; padding:10px; color:#991b1b; font-size:13px;">Manual commit failed: ${err.message}</div>`;
      }
      inFlightCommitKey = null;
    }
  }
});
