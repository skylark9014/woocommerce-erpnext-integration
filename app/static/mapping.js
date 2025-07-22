
// =============================
// mapping.js - Admin Panel Logic
// =============================

document.addEventListener("DOMContentLoaded", () => {
    const previewBtn = document.getElementById("preview-sync");
    const createBtn = document.getElementById("sync-create");
    const updateBtn = document.getElementById("sync-update");
    const deleteBtn = document.getElementById("sync-delete");
    const previewTable = document.getElementById("preview-table");
    const statusDiv = document.getElementById("status-msg");

    const previewBody = document.querySelector("#preview-table tbody");

    async function postJson(url) {
        const res = await fetch(url, { method: "POST" });
        if (!res.ok) throw new Error(await res.text());
        return await res.json();
    }

    function showStatus(msg, type = "info") {
        statusDiv.textContent = msg;
        statusDiv.className = `alert alert-${type}`;
        statusDiv.style.display = "block";
        setTimeout(() => { statusDiv.style.display = "none"; }, 5000);
    }

    function renderPreview(data) {
        previewBody.innerHTML = "";

        const appendRows = (arr, label, className) => {
            for (const code of arr) {
                const row = document.createElement("tr");
                row.innerHTML = `
                    <td>${code}</td>
                    <td>${label}</td>
                `;
                row.classList.add(className);
                previewBody.appendChild(row);
            }
        };

        appendRows(data.actions.create, "Create", "table-success");
        appendRows(data.actions.update, "Update", "table-warning");
        appendRows(data.actions.delete, "Delete", "table-danger");
    }

    previewBtn?.addEventListener("click", async () => {
        try {
            showStatus("Previewing changes...", "secondary");
            const data = await postJson("/admin/api/preview-sync");
            renderPreview(data);
            showStatus(`Preview ready. Create: ${data.counts.create}, Update: ${data.counts.update}, Delete: ${data.counts.delete}`, "info");
        } catch (e) {
            showStatus("Failed to preview sync: " + e.message, "danger");
        }
    });

    createBtn?.addEventListener("click", async () => {
        try {
            showStatus("Creating products...");
            const res = await postJson("/api/sync/create");
            showStatus("Created: " + res.created.length + ", Failed: " + res.failed.length, res.failed.length ? "warning" : "success");
        } catch (e) {
            showStatus("Create failed: " + e.message, "danger");
        }
    });

    updateBtn?.addEventListener("click", async () => {
        try {
            showStatus("Updating products...");
            const res = await postJson("/api/sync/update");
            showStatus("Updated: " + res.updated.length + ", Failed: " + res.failed.length, res.failed.length ? "warning" : "success");
        } catch (e) {
            showStatus("Update failed: " + e.message, "danger");
        }
    });

    deleteBtn?.addEventListener("click", async () => {
        try {
            showStatus("Deleting products...");
            const res = await postJson("/api/sync/delete");
            showStatus("Deleted: " + res.deleted.length + ", Failed: " + res.failed.length, res.failed.length ? "warning" : "success");
        } catch (e) {
            showStatus("Delete failed: " + e.message, "danger");
        }
    });
});


document.addEventListener("DOMContentLoaded", function () {
  const previewTable = document.getElementById("preview-table");
  const resultContainer = document.getElementById("result");

  async function fetchPreview() {
    resultContainer.textContent = "Fetching preview...";
    const res = await fetch("/admin/api/preview-sync", {
      method: "POST",
    });
    const data = await res.json();

    resultContainer.textContent = "";
    previewTable.innerHTML = "";

    const { create, update, delete: del } = data.actions;
    const counts = data.counts;

    if (!create.length && !update.length && !del.length) {
      previewTable.innerHTML = "<tr><td colspan='3'>✅ No sync actions needed.</td></tr>";
      return;
    }

    for (const code of create) {
      previewTable.innerHTML += `<tr><td>${code}</td><td>Create</td><td><button class='btn btn-sm btn-success' onclick="syncSingle('create', '${code}')">▶</button></td></tr>`;
    }
    for (const code of update) {
      previewTable.innerHTML += `<tr><td>${code}</td><td>Update</td><td><button class='btn btn-sm btn-warning' onclick="syncSingle('update', '${code}')">▶</button></td></tr>`;
    }
    for (const code of del) {
      previewTable.innerHTML += `<tr><td>${code}</td><td>Delete</td><td><button class='btn btn-sm btn-danger' onclick="syncSingle('delete', '${code}')">▶</button></td></tr>`;
    }
  }

  window.syncSingle = async function (action, code) {
    alert(`This demo does not support single ${action} for: ${code}`);
    // You can implement single item sync using a custom API.
  };

  async function bulkSync(action) {
    resultContainer.textContent = `Processing ${action.toUpperCase()}...`;
    const res = await fetch(`/api/sync/${action}`, {
      method: "POST",
    });
    const data = await res.json();
    resultContainer.textContent = JSON.stringify(data, null, 2);
    fetchPreview(); // Refresh table
  }

  document.getElementById("sync-create").addEventListener("click", () => bulkSync("create"));
  document.getElementById("sync-update").addEventListener("click", () => bulkSync("update"));
  document.getElementById("sync-delete").addEventListener("click", () => bulkSync("delete"));

  fetchPreview();
});

