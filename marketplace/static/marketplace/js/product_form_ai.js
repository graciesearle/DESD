/**
 * product_form_ai.js
 * ------------------
 * Handles the "AI Quality Scan" workflow on the Add/Edit Product form.
 *
 * When the producer clicks "AI Quality Scan", this script:
 *   1. Grabs the image from the file input.
 *   2. POSTs it to /api/ai/producer-quality/predict/.
 *   3. Renders an XAI overlay showing Grade, Derivation, and Action.
 *   4. Provides Accept / Override buttons that POST to /api/ai/producer-quality/override/.
 */
document.addEventListener("DOMContentLoaded", function () {

    /* ── Helpers ────────────────────────────────────────────── */
    function getCsrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute("content") : "";
    }

    /* ── DOM references ─────────────────────────────────────── */
    const aiBtn        = document.getElementById("ai-scan-btn");
    const resultsPanel = document.getElementById("ai-results-panel");
    const imageInput   = document.querySelector('input[type="file"]');

    if (!aiBtn || !resultsPanel || !imageInput) return;  // guard: not on the product form

    /* ── State ──────────────────────────────────────────────── */
    let currentLogId = null;  // stores the InferenceRequestLog PK for override calls

    /* ── AI Scan click handler ──────────────────────────────── */
    aiBtn.addEventListener("click", async function (e) {
        e.preventDefault();

        // Validate that an image has been selected
        if (!imageInput.files || imageInput.files.length === 0) {
            alert("Please select a product image first before running the AI scan.");
            return;
        }

        // Show loading state
        aiBtn.disabled = true;
        aiBtn.textContent = "Scanning…";
        resultsPanel.classList.add("hidden");

        const formData = new FormData();
        formData.append("image", imageInput.files[0]);

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
            resultsPanel.innerHTML = `
                <div style="background:#fef2f2; border:1px solid #fca5a5; border-radius:8px; padding:16px;">
                    <p style="color:#991b1b; font-weight:bold; margin:0 0 4px;">AI Scan Failed</p>
                    <p style="color:#7f1d1d; margin:0; font-size:13px;">${err.message}</p>
                </div>`;
            resultsPanel.classList.remove("hidden");
        } finally {
            aiBtn.disabled = false;
            aiBtn.textContent = "🤖 AI Quality Scan";
        }
    });

    /* ── Render the XAI results panel ───────────────────────── */
    function renderResults(data) {
        const xai = data.explanation_payload || {};
        const scores = xai.score_breakdown || {};
        const gradeDerivation = xai.grade_derivation || "";
        const recDerivation = xai.recommendation_derivation || "";

        // Grade badge colour
        const gradeColors = { A: "#15803d", B: "#ca8a04", C: "#dc2626" };
        const gradeColor = gradeColors[data.authoritative_grade] || "#6b7280";

        resultsPanel.innerHTML = `
            <div style="background:white; border:1px solid #d1d5db; border-radius:10px; padding:20px; margin-top:16px; box-shadow:0 2px 8px rgba(0,0,0,0.06);">

                <!-- Header -->
                <div style="display:flex; align-items:center; gap:12px; margin-bottom:16px;">
                    <span style="font-size:28px;">🤖</span>
                    <div>
                        <h3 style="margin:0; font-size:16px; font-weight:bold; color:#111;">AI Quality Assessment</h3>
                        <p style="margin:2px 0 0; font-size:12px; color:#6b7280;">Model v${data.model_version_used || "unknown"} · Confidence ${parseFloat(data.confidence || 0).toFixed(1)}%</p>
                    </div>
                    <span style="margin-left:auto; background:${gradeColor}; color:white; font-weight:bold; font-size:22px; width:44px; height:44px; border-radius:50%; display:flex; align-items:center; justify-content:center;">
                        ${data.authoritative_grade || "?"}
                    </span>
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

                <!-- Action Buttons -->
                <div style="display:flex; gap:10px; flex-wrap:wrap;">
                    <button type="button" id="ai-accept-btn"
                        style="flex:1; padding:10px; background:#15803d; color:white; border:none; border-radius:6px; font-weight:bold; cursor:pointer; font-size:14px; transition:background .2s;">
                        ✓ Accept Recommendation
                    </button>
                    <button type="button" id="ai-override-toggle"
                        style="flex:1; padding:10px; background:#f5f5f5; color:#333; border:1px solid #d1d5db; border-radius:6px; font-weight:bold; cursor:pointer; font-size:14px; transition:background .2s;">
                        ✎ Override Grade
                    </button>
                </div>

                <!-- Override Panel (hidden by default) -->
                <div id="ai-override-panel" style="display:none; margin-top:14px; background:#fafafa; border:1px solid #e5e7eb; border-radius:8px; padding:14px;">
                    <label style="font-weight:bold; font-size:13px; display:block; margin-bottom:6px;">Your Grade:</label>
                    <select id="ai-override-grade" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px; margin-bottom:10px; font-size:14px;">
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
                        Submit Override
                    </button>
                </div>

                <!-- Status message area -->
                <div id="ai-feedback-msg" style="margin-top:10px;"></div>
            </div>`;

        resultsPanel.classList.remove("hidden");

        // Wire up Accept button
        document.getElementById("ai-accept-btn").addEventListener("click", () => submitOverride(true, null, ""));

        // Wire up Override toggle
        document.getElementById("ai-override-toggle").addEventListener("click", function () {
            const panel = document.getElementById("ai-override-panel");
            panel.style.display = panel.style.display === "none" ? "block" : "none";
        });

        // Wire up Override submit
        document.getElementById("ai-override-submit").addEventListener("click", function () {
            const grade = document.getElementById("ai-override-grade").value;
            const reason = document.getElementById("ai-override-reason").value.trim();
            if (!reason) {
                alert("Please provide a reason for the override.");
                return;
            }
            submitOverride(false, grade, reason);
        });
    }

    /* ── Score bar helper ───────────────────────────────────── */
    function scoreBar(label, value) {
        const pct = value != null ? parseFloat(value).toFixed(1) : "–";
        const barWidth = value != null ? Math.min(parseFloat(value), 100) : 0;
        const barColor = barWidth >= 80 ? "#22c55e" : barWidth >= 65 ? "#eab308" : "#ef4444";
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

    /* ── Submit override (accept or reject) ─────────────────── */
    async function submitOverride(accepted, overrideGrade, overrideReason) {
        if (!currentLogId) return;

        const msgEl = document.getElementById("ai-feedback-msg");

        const body = {
            inference_log_id: currentLogId,
            accepted_recommendation: accepted,
        };
        if (!accepted) {
            body.override_grade = overrideGrade;
            body.override_reason = overrideReason;
        }

        try {
            const resp = await fetch("/api/ai/producer-quality/override/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken(),
                },
                body: JSON.stringify(body),
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || JSON.stringify(err));
            }

            if (accepted) {
                msgEl.innerHTML = `<div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:6px; padding:10px; color:#166534; font-size:13px; font-weight:600;">
                    ✓ Recommendation accepted and logged successfully.</div>`;
            } else {
                msgEl.innerHTML = `<div style="background:#fffbeb; border:1px solid #fde68a; border-radius:6px; padding:10px; color:#92400e; font-size:13px; font-weight:600;">
                    ✎ Override submitted (Grade ${overrideGrade}). Logged for retraining.</div>`;
            }

            // Disable buttons after feedback
            const acceptBtn = document.getElementById("ai-accept-btn");
            const overrideBtn = document.getElementById("ai-override-submit");
            if (acceptBtn) { acceptBtn.disabled = true; acceptBtn.style.opacity = "0.5"; }
            if (overrideBtn) { overrideBtn.disabled = true; overrideBtn.style.opacity = "0.5"; }

        } catch (err) {
            msgEl.innerHTML = `<div style="background:#fef2f2; border:1px solid #fca5a5; border-radius:6px; padding:10px; color:#991b1b; font-size:13px;">
                Override failed: ${err.message}</div>`;
        }
    }
});
