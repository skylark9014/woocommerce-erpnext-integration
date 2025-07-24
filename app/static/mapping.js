// app/static/mapping.js
// ------------- helpers -------------
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function esc(str) {
  return String(str ?? "").replace(/[&<>"']/g, s =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[s])
  );
}

// one‑off alerts that auto‑dismiss after 7s
function showAlert(kind, msg) {
  const box = $("#sync-alert");
  box.className = `alert alert-${kind}`;
  box.innerHTML = msg;
  box.classList.remove("d-none");
  setTimeout(() => box.classList.add("d-none"), 7000);
}

// persistent callout: stays until closed
function showCallout(kind, html) {
  const area = $("#manual-delete-callout-area");
  if (!area) return;
  area.innerHTML = `
    <div class="alert alert-${kind} alert-dismissible" role="alert">
      ${html}
      <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    </div>
  `;
}

function showLoader(text = "Working…") {
  const el = $("#global-loader");
  if (!el) return;
  $("#loader-text") && ($("#loader-text").textContent = text);
  el.classList.remove("hidden");
}
function hideLoader() {
  const el = $("#global-loader");
  if (el) el.classList.add("hidden");
}
function disableBtn(btn, txt = "Working…") {
  if (!btn) return;
  btn.dataset.prevText = btn.textContent;
  btn.disabled = true;
  btn.textContent = txt;
}
function enableBtn(btn) {
  if (!btn) return;
  btn.disabled = false;
  if (btn.dataset.prevText) btn.textContent = btn.dataset.prevText;
}

// ------------- state -------------
let mappingData = { auto: [], overrides: [], images: {} };
let previewData = { actions: { create: [], update: [], delete: [] }, reasons: { update: {} } };

// ------------- tooltip utils -------------
function disposeTooltips() {
  $$('[data-bs-toggle="tooltip"]').forEach(el => {
    const inst = bootstrap.Tooltip.getInstance(el);
    if (inst) inst.dispose();
  });
}
function initTooltips() {
  disposeTooltips();
  $$('[data-bs-toggle="tooltip"]').forEach(el => {
    new bootstrap.Tooltip(el, {
      container: 'body',
      trigger: 'hover focus',
      delay: { show: 200, hide: 100 }
    });
  });
}

// ------------- renderers -------------
function renderMappingTables() {
  const autoBody = $("#auto-body");
  const ovBody = $("#overrides-body");
  if (!autoBody || !ovBody) return;

  autoBody.innerHTML = mappingData.auto.map(r => {
    // Highlight only rows with a status other than "matched"
    const highlight = r.status && r.status !== 'matched';
    return `
      <tr class="${highlight ? 'unmatched' : ''}">
        <td class="td-sm code">${esc(r.erp_item_code)}</td>
        <td class="td-sm sku">${esc(r.wc_sku)}</td>
        <td class="td-sm">${esc(r.wc_product_id)}</td>
        <td class="td-sm">${esc(r.status)}</td>
        <td class="td-sm">${esc(r.last_synced)}</td>
        <td class="td-sm">${esc(r.last_price)}</td>
      </tr>
    `;
  }).join("");

  ovBody.innerHTML = mappingData.overrides.map((r, idx) => `
    <tr data-idx="${idx}">
      <td class="td-sm">
        <input type="text" class="form-control form-control-sm" value="${esc(r.erp_item_code)}">
      </td>
      <td class="td-sm">
        <input type="number" class="form-control form-control-sm" value="${esc(r.forced_wc_product_id)}">
      </td>
      <td class="td-sm">
        <input type="text" class="form-control form-control-sm" value="${esc(r.note || '')}">
      </td>
      <td class="td-sm text-end">
        <button class="btn btn-sm btn-outline-danger"
                onclick="removeOverrideRow(${idx})"
                data-bs-toggle="tooltip"
                title="Delete this override row">✖</button>
      </td>
    </tr>
  `).join("");

  initTooltips();
}

function renderPreviewTable() {
  const tbody = $("#preview-body");
  if (!tbody) return;

  const rows = [];
  previewData.actions.create.forEach(code => rows.push({ code, action: "create" }));
  previewData.actions.update.forEach(code => rows.push({ code, action: "update" }));
  previewData.actions.delete.forEach(code => rows.push({ code, action: "delete" }));

  const reasons = previewData.reasons?.update || {};

  tbody.innerHTML = rows.map(r => {
    const rs = reasons[r.code] || {};
    const fields = (rs.fields || []).map(f => `<span class="field-chip">${esc(f)}</span>`).join("");
    const imgFlag = rs.images_changed ? '<span class="img-flag">Yes</span>' : 'No';
    return `
      <tr>
        <td class="td-sm code">${esc(r.code)}</td>
        <td class="td-sm action-${esc(r.action)} text-capitalize">${esc(r.action)}</td>
        <td class="td-sm">${fields || "-"}</td>
        <td class="td-sm">${imgFlag}</td>
      </tr>
    `;
  }).join("");
}

// ------------- API -------------
async function loadMapping() {
  const { data } = await axios.get("/admin/api/mapping");
  mappingData = data || { auto: [], overrides: [], images: {} };
  renderMappingTables();
}
async function saveMapping(newData) {
  await axios.put("/admin/api/mapping", newData);
  await loadMapping();
}

async function doRunPreview(btn) {
  const b = btn || $("#btn-refresh-preview");
  try {
    disableBtn(b, "Refreshing…");
    showLoader("Generating preview…");
    const { data } = await axios.post("/admin/api/preview-sync");
    previewData = data;
    renderPreviewTable();
  } catch (e) {
    console.error(e);
    showAlert("danger", "Failed to run preview");
  } finally {
    enableBtn(b);
    hideLoader();
  }
}

function formatErrors(errs) {
  return Object.entries(errs)
    .map(([code, msg]) => `<div><b>${esc(code)}</b>: ${esc(msg)}</div>`)
    .join("");
}

async function doBulk(action, btn) {
  const b = btn || document.getElementById(`btn-${action}`);
  try {
    // clear any existing manual-delete callout
    const area = $("#manual-delete-callout-area");
    if (area) area.innerHTML = "";

    disableBtn(b, "Working…");
    showLoader(`Running ${action}…`);
    const { data } = await axios.post(`/admin/api/sync/${action}`);
    const ok = data.created || data.updated || data.deleted || [];
    const failed = data.failed || [];
    const errs = data.errors || {};
    const manual = data.manual_delete || [];

    if (failed.length) {
      console.error("Failed items:", errs);
      showAlert("warning",
        `${action.toUpperCase()}: OK=${ok.length} Failed=${failed.length}<br>${formatErrors(errs)}`
      );
    } else {
      showAlert("success", `${action.toUpperCase()}: OK=${ok.length}`);
    }

    // If Create returned ghost‐SKUs, show persistent callout + button
    if (action === "create" && manual.length) {
      const list = manual.map(sku => `<li>${esc(sku)}</li>`).join("");
      showCallout("danger", `
        <strong>Manual deletion required for these SKUs:</strong>
        <ul>${list}</ul>
        <p>Please delete these “ghost” SKUs in WooCommerce (Products → Trash → Permanently Delete), then retry “Create”.</p>
        <div class="mt-2">
          <button onclick="doEmptyTrash(this)" class="btn btn-sm btn-outline-danger">
            🗑️ Empty Woo Trash
          </button>
        </div>
      `);
    }

    await Promise.all([loadMapping(), doRunPreview()]);
  } catch (e) {
    console.error(e);
    showAlert("danger", `Bulk ${action} failed`);
  } finally {
    enableBtn(b);
    hideLoader();
  }
}

// ------------- Empty trash helper -------------
async function doEmptyTrash(btn) {
  const area = $("#manual-delete-callout-area");
  disableBtn(btn, "Emptying…");
  showLoader("Emptying trash…");
  try {
    const { data } = await axios.post("/admin/api/empty-trash");
    showAlert("success", `Emptied trash: ${data.removed.length} products permanently deleted.`);
  } catch (e) {
    console.error(e);
    showAlert("danger", "Failed to empty WooCommerce trash.");
  } finally {
    hideLoader();
    if (area) area.innerHTML = "";
  }
}
window.doEmptyTrash = doEmptyTrash;

// ------------- overrides editing -------------
function addOverrideRow() {
  mappingData.overrides.push({ erp_item_code: "", forced_wc_product_id: "", note: "" });
  renderMappingTables();
}
function removeOverrideRow(idx) {
  mappingData.overrides.splice(idx, 1);
  renderMappingTables();
}
async function saveOverrides() {
  const rows = $$("#overrides-body tr");
  const overrides = rows.map(tr => {
    const [erpEl, wcEl, noteEl] = tr.querySelectorAll("input");
    return {
      erp_item_code: erpEl.value.trim(),
      forced_wc_product_id: wcEl.value ? Number(wcEl.value) : null,
      note: noteEl.value.trim() || undefined,
    };
  });
  try {
    await saveMapping({ auto: mappingData.auto, overrides });
    showAlert("success", "Overrides saved");
  } catch (e) {
    console.error(e);
    showAlert("danger", "Failed to save overrides");
  }
}

async function reloadMapping() {
  await loadMapping();
  showAlert("info", "Mapping reloaded");
}

// ------------- global error hook -------------
window.addEventListener("error", (e) => {
  console.error("JS error:", e.error || e.message);
  showAlert("danger", "A script error occurred. Check console (F12).");
});

// ------------- expose globals -------------
window.runPreview = doRunPreview;
window.triggerBulk = doBulk;
window.addOverrideRow = addOverrideRow;
window.removeOverrideRow = removeOverrideRow;
window.saveOverrides = saveOverrides;
window.reloadMapping = reloadMapping;

// ------------- init -------------
document.addEventListener("DOMContentLoaded", async () => {
  $("#btn-refresh-preview")?.addEventListener("click", (e) => doRunPreview(e.target));
  $("#btn-create")?.addEventListener("click", (e) => doBulk("create", e.target));
  $("#btn-update")?.addEventListener("click", (e) => doBulk("update", e.target));
  $("#btn-delete")?.addEventListener("click", (e) => doBulk("delete", e.target));

  try {
    showLoader("Loading mapping…");
    await loadMapping();
    hideLoader();
    await doRunPreview();
    initTooltips();
  } catch (e) {
    hideLoader();
    console.error(e);
    showAlert("danger", "Initial load failed");
  }
});
