// ------------- helpers -------------
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function esc(str) {
  return String(str ?? "").replace(/[&<>"']/g, s =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[s])
  );
}

function showAlert(kind, msg) {
  const box = $("#sync-alert");
  box.className = `alert alert-${kind}`;
  box.textContent = msg;
  box.classList.remove("d-none");
  setTimeout(() => box.classList.add("d-none"), 5000);
}

// ------------- state -------------
let mappingData = { auto: [], overrides: [] };
let previewData = { actions: { create: [], update: [], delete: [] }, counts: {} };

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
    const unmatched = !r.wc_product_id || (r.status && r.status !== 'matched');
    return `
      <tr class="${unmatched ? 'unmatched' : ''}">
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
      <td class="td-sm text-right">
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

  tbody.innerHTML = rows.map(r => `
    <tr>
      <td class="td-sm code">${esc(r.code)}</td>
      <td class="td-sm action-${r.action} text-capitalize">${esc(r.action)}</td>
    </tr>
  `).join("");
}

// ------------- API -------------
async function loadMapping() {
  const { data } = await axios.get("/admin/api/mapping");
  mappingData = data || { auto: [], overrides: [] };
  renderMappingTables();
}
async function saveMapping(newData) {
  await axios.put("/admin/api/mapping", newData);
  await loadMapping();
}
async function runPreview() {
  try {
    const { data } = await axios.post("/admin/api/preview-sync");
    previewData = data;
    renderPreviewTable();
    showAlert("info", "Preview refreshed");
  } catch (e) {
    console.error(e);
    showAlert("danger", "Failed to run preview");
  }
}
async function triggerBulk(action) {
  try {
    const { data } = await axios.post(`/api/sync/${action}`);
    const ok = Object.values(data)[0] || [];
    const failed = data.failed || [];
    showAlert(failed.length ? "warning" : "success",
      `${action.toUpperCase()}: OK=${ok.length} Failed=${failed.length}`);
    await Promise.all([loadMapping(), runPreview()]);
  } catch (e) {
    console.error(e);
    showAlert("danger", `Bulk ${action} failed`);
  }
}

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
  const payload = { auto: mappingData.auto, overrides };
  try {
    await saveMapping(payload);
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

// ------------- expose globals -------------
window.runPreview = runPreview;
window.triggerBulk = triggerBulk;
window.addOverrideRow = addOverrideRow;
window.removeOverrideRow = removeOverrideRow;
window.saveOverrides = saveOverrides;
window.reloadMapping = reloadMapping;

// ------------- init -------------
document.addEventListener("DOMContentLoaded", async () => {
  await loadMapping();
  await runPreview();
  initTooltips();
});
