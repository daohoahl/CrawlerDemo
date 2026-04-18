let page = 1;
let pageSize = 20;
let lastPayload = null;
let debounceTimer = null;

const qEl = document.getElementById("q");
const sourceEl = document.getElementById("source");
const sortByEl = document.getElementById("sortBy");
const sortOrderEl = document.getElementById("sortOrder");
const pageSizeEl = document.getElementById("pageSize");
const tbodyEl = document.getElementById("tbody");
const summaryEl = document.getElementById("summary");
const pageInfoEl = document.getElementById("pageInfo");
const kpiRoot = document.getElementById("kpiRoot");
const statusText = document.getElementById("statusText");
const statusDot = document.getElementById("statusDot");
const toastEl = document.getElementById("toast");

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

function showToast(message) {
  toastEl.textContent = message;
  toastEl.hidden = false;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    toastEl.hidden = true;
  }, 2600);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    showToast("Đã copy vào clipboard");
  } catch {
    showToast("Không copy được (trình duyệt chặn — thử HTTPS hoặc copy tay)");
  }
}

function buildParams() {
  const params = new URLSearchParams();
  params.set("page", String(page));
  params.set("page_size", String(pageSize));
  params.set("sort_by", sortByEl.value);
  params.set("sort_order", sortOrderEl.value);
  if (qEl.value.trim()) params.set("q", qEl.value.trim());
  if (sourceEl.value.trim()) params.set("source", sourceEl.value.trim());
  return params;
}

function formatRel(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return esc(iso);
  const now = Date.now();
  const diff = Math.floor((now - d.getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function renderRow(a) {
  const rawTitle = (a.title || "").trim();
  const missing = !rawTitle;
  const headline = esc(a.display_title || rawTitle || "Untitled");
  const sum = esc((a.summary || "").replace(/\s+/g, " ").trim());
  return `
    <tr>
      <td class="col-id">${esc(String(a.id))}</td>
      <td class="title-cell">
        <strong>${headline}</strong>${missing ? '<span class="title-badge" title="DB không có title — đã suy ra từ summary/URL">Inferred</span>' : ""}
        ${sum ? `<p class="snippet">${sum}</p>` : ""}
      </td>
      <td class="col-source">${esc(a.source)}</td>
      <td class="col-dt">${formatRel(a.published_at)}</td>
      <td class="col-dt">${formatRel(a.fetched_at)}</td>
      <td class="col-actions">
        <div class="action-row">
          <a class="btn btn-ghost btn-icon" href="${esc(a.canonical_url)}" target="_blank" rel="noopener noreferrer">Open</a>
          <button type="button" class="btn btn-ghost btn-icon" data-copy="${esc(a.canonical_url)}">Copy URL</button>
        </div>
      </td>
    </tr>
  `;
}

function renderKpis(stats) {
  const chips =
    stats.sources && stats.sources.length
      ? stats.sources
          .slice(0, 12)
          .map((s) => `<span class="kpi-chip">${esc(s.source)} · ${s.count}</span>`)
          .join("")
      : '<span class="kpi-meta">Chưa có dữ liệu nguồn</span>';

  kpiRoot.innerHTML = `
    <div class="kpi">
      <div class="kpi-label">Total articles</div>
      <div class="kpi-value">${Number(stats.total).toLocaleString()}</div>
      <div class="kpi-meta">Trong RDS</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Fetched (24h)</div>
      <div class="kpi-value">${Number(stats.fetched_last_24h).toLocaleString()}</div>
      <div class="kpi-meta">Throughput gần đây</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Last ingest</div>
      <div class="kpi-value" style="font-size:1rem">${stats.last_fetched_at ? formatRel(stats.last_fetched_at) : "—"}</div>
      <div class="kpi-meta">MAX(fetched_at)</div>
    </div>
    <div class="kpi kpi-wide">
      <div class="kpi-label">By source (top)</div>
      <div class="kpi-list">${chips}</div>
    </div>
  `;
}

async function loadStats() {
  try {
    const res = await fetch("/api/stats");
    if (!res.ok) throw new Error(await res.text());
    const stats = await res.json();
    renderKpis(stats);
  } catch (e) {
    kpiRoot.innerHTML = `<div class="kpi kpi-wide"><div class="kpi-meta">Stats không tải được: ${esc(String(e))}</div></div>`;
  }
}

async function loadSources() {
  try {
    const res = await fetch("/api/sources");
    if (!res.ok) throw new Error();
    const data = await res.json();
    const items = data.items || [];
    const current = sourceEl.value;
    sourceEl.innerHTML = '<option value="">All sources</option>';
    for (const name of items) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      sourceEl.appendChild(opt);
    }
    if (current && items.includes(current)) sourceEl.value = current;
  } catch {
    /* optional */
  }
}

async function loadStatus() {
  try {
    const res = await fetch("/health/ready");
    if (res.ok) {
      statusText.textContent = "Database OK";
      statusDot.className = "dot ok";
      return;
    }
  } catch {
    /* fallthrough */
  }
  statusText.textContent = "Database unreachable (check /health/ready)";
  statusDot.className = "dot err";
}

async function loadData() {
  tbodyEl.innerHTML = '<tr><td colspan="6" class="empty">Loading…</td></tr>';
  const res = await fetch(`/api/articles?${buildParams().toString()}`);
  if (!res.ok) {
    const txt = await res.text();
    tbodyEl.innerHTML = `<tr><td colspan="6" class="empty">Lỗi API: ${esc(txt)}</td></tr>`;
    summaryEl.textContent = "";
    return;
  }
  const data = await res.json();
  lastPayload = data;
  summaryEl.textContent = `Hiển thị ${data.items.length.toLocaleString()} / ${Number(data.total).toLocaleString()} bài · page size ${data.page_size}`;
  const totalPages = Math.max(1, Math.ceil(Number(data.total) / Number(data.page_size)));
  pageInfoEl.textContent = `Page ${data.page} / ${totalPages}`;
  document.getElementById("prevBtn").disabled = data.page <= 1;
  document.getElementById("nextBtn").disabled = data.page >= totalPages;

  tbodyEl.innerHTML = data.items.length
    ? data.items.map(renderRow).join("")
    : '<tr><td colspan="6" class="empty">Không có bản ghi. Thử bỏ filter hoặc đổi từ khóa.</td></tr>';

  tbodyEl.querySelectorAll("button[data-copy]").forEach((btn) => {
    btn.addEventListener("click", () => copyText(btn.getAttribute("data-copy")));
  });
}

function scheduleLoad() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    page = 1;
    loadData();
  }, 420);
}

document.getElementById("searchBtn").addEventListener("click", () => {
  page = 1;
  loadData();
});

document.getElementById("resetBtn").addEventListener("click", () => {
  qEl.value = "";
  sourceEl.value = "";
  sortByEl.value = "fetched_at";
  sortOrderEl.value = "desc";
  pageSizeEl.value = "20";
  pageSize = 20;
  page = 1;
  loadData();
});

document.getElementById("exportBtn").addEventListener("click", () => {
  if (!lastPayload) {
    showToast("Chưa có dữ liệu để export");
    return;
  }
  const blob = new Blob([JSON.stringify(lastPayload, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `articles-page-${lastPayload.page}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
  showToast("Đã tải JSON trang hiện tại");
});

document.getElementById("prevBtn").addEventListener("click", () => {
  if (page > 1) {
    page -= 1;
    loadData();
  }
});

document.getElementById("nextBtn").addEventListener("click", () => {
  page += 1;
  loadData();
});

qEl.addEventListener("input", scheduleLoad);

[sourceEl, sortByEl, sortOrderEl].forEach((el) => {
  el.addEventListener("change", () => {
    page = 1;
    loadData();
  });
});

pageSizeEl.addEventListener("change", () => {
  pageSize = Number(pageSizeEl.value) || 20;
  page = 1;
  loadData();
});

loadStats();
loadSources();
loadStatus();
loadData();
