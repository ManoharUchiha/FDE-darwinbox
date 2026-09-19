async function j(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) { const t = await res.text(); throw new Error(t); }
  return res.json();
}

async function runAgent() {
  document.getElementById("runBtn").disabled = true;
  await j("/api/run", { method: "POST" });
  await refreshAll();
  document.getElementById("runBtn").disabled = false;
}

async function refreshAll() {
  const [log, escalations, records, audit, pushResults] = await Promise.all([
    j("/api/log"), j("/api/escalations"), j("/api/records"), j("/api/audit"), j("/api/push_results"),
  ]);
  renderLog(log);
  renderEscalations(escalations);
  renderRecords(records);
  renderAudit(audit);
  renderPushResults(pushResults);

  const pending = escalations.filter(e => e.status === "pending").length;
  document.getElementById("pushBtn").disabled = pending > 0 || Object.keys(records).length === 0;
}

function renderLog(log) {
  const el = document.getElementById("log");
  el.innerHTML = log.map(l => `<div class="log-line ${l.level}">[${l.ts.split("T")[1].split(".")[0]}] ${escapeHtml(l.message)}</div>`).join("") || '<div class="empty">No activity yet.</div>';
  el.scrollTop = el.scrollHeight;
}

function renderEscalations(escalations) {
  const el = document.getElementById("escalations");
  const pending = escalations.filter(e => e.status === "pending");
  document.getElementById("escCount").textContent = pending.length;
  if (!pending.length) {
    el.innerHTML = '<div class="empty">No pending escalations.</div>';
    return;
  }
  el.innerHTML = pending.map(e => `
    <div class="esc-card">
      <div class="meta">${e.type.toUpperCase()} &middot; id ${e.id.slice(0,8)}</div>
      <div class="ctx">${escapeHtml(e.context)}</div>
      <div class="esc-actions">
        <input placeholder="corrected value" id="input-${e.id}">
        <button onclick="resolve('${e.id}', 'approve')">Approve</button>
        <button class="secondary" onclick="resolveCorrect('${e.id}')">Correct</button>
        <button class="danger" onclick="resolve('${e.id}', 'reject')">Reject</button>
      </div>
    </div>
  `).join("");
}

async function resolve(id, decision) {
  await j(`/api/escalations/${id}/resolve`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
  await refreshAll();
}

async function resolveCorrect(id) {
  const value = document.getElementById(`input-${id}`).value;
  await j(`/api/escalations/${id}/resolve`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision: "correct", value }),
  });
  await refreshAll();
}

function renderRecords(records) {
  const el = document.getElementById("records");
  const ids = Object.keys(records);
  if (!ids.length) { el.innerHTML = '<div class="empty">No records yet.</div>'; return; }
  const fields = ["employee_id", "full_name", "department", "status", "email"];
  el.innerHTML = `<table><tr>${fields.map(f => `<th>${f}</th>`).join("")}</tr>` +
    ids.map(id => `<tr>${fields.map(f => `<td>${escapeHtml(records[id][f] ?? "")}</td>`).join("")}</tr>`).join("") +
    `</table>`;
}

function renderAudit(audit) {
  const el = document.getElementById("audit");
  if (!audit.length) { el.innerHTML = '<div class="empty">No activity yet.</div>'; return; }
  el.innerHTML = `<table><tr><th>Time</th><th>Action</th><th>Employee</th><th>Detail</th></tr>` +
    audit.slice().reverse().map(a => `<tr><td>${(a.ts||"").split("T")[1]?.split(".")[0] ?? ""}</td><td>${a.action}</td><td>${a.employee_id ?? ""}</td><td>${escapeHtml(JSON.stringify(a.detail ?? a.employee_id ?? ""))}</td></tr>`).join("") +
    `</table>`;
}

function renderPushResults(results) {
  const el = document.getElementById("pushResults");
  const ids = Object.keys(results);
  if (!ids.length) { el.innerHTML = '<div class="empty">Not pushed yet.</div>'; return; }
  el.innerHTML = `<table><tr><th>Employee</th><th>Status</th><th>Reason</th><th>Actions</th></tr>` +
    ids.map(id => {
      const r = results[id];
      const pill = r.status === "success" ? "success" : "failure";
      return `<tr>
        <td>${id}</td>
        <td><span class="pill ${pill}">${r.status}</span></td>
        <td>${r.reason ?? ""}</td>
        <td>
          ${r.status !== "success" ? `<button onclick="retryPush('${id}')">Retry</button>` : `<button class="danger" onclick="rollbackPush('${id}')">Rollback</button>`}
        </td>
      </tr>`;
    }).join("") + `</table>`;
}

async function pushAll() {
  await j("/api/push", { method: "POST" });
  await refreshAll();
}

async function retryPush(id) {
  await j(`/api/push/${id}/retry`, { method: "POST" });
  await refreshAll();
}

async function rollbackPush(id) {
  await j(`/api/push/${id}/rollback`, { method: "POST" });
  await refreshAll();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
