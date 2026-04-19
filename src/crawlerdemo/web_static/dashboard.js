const LS_FAV = "crawler-favorites-v1";
const LS_FILTERS = "crawler-saved-filters-v1";
const LS_THEME = "crawler-theme";

let page = 1;
let pageSize = 20;
let lastPayload = null;
let lastRawItems = [];
let lastDisplayItems = [];
let debounceTimer = null;

const qEl = document.getElementById("q");
const sourceEl = document.getElementById("source");
const sortByEl = document.getElementById("sortBy");
const sortOrderEl = document.getElementById("sortOrder");
const pageSizeEl = document.getElementById("pageSize");
const fetchedFromEl = document.getElementById("fetchedFrom");
const fetchedToEl = document.getElementById("fetchedTo");
const publishedFromEl = document.getElementById("publishedFrom");
const publishedToEl = document.getElementById("publishedTo");
const favoritesOnlyEl = document.getElementById("favoritesOnly");
const tbodyEl = document.getElementById("tbody");
const summaryEl = document.getElementById("summary");
const pageInfoEl = document.getElementById("pageInfo");
const kpiRoot = document.getElementById("kpiRoot");
const statusText = document.getElementById("statusText");
const statusDot = document.getElementById("statusDot");
const toastEl = document.getElementById("toast");
const articleModal = document.getElementById("articleModal");
const modalBody = document.getElementById("modalBody");
const modalTitle = document.getElementById("modalTitle");
const modalBackdrop = document.getElementById("modalBackdrop");
const modalClose = document.getElementById("modalClose");
const savedFilterSelect = document.getElementById("savedFilterSelect");
const themeToggle = document.getElementById("themeToggle");

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

function loadFavoriteSet() {
  try {
    const raw = localStorage.getItem(LS_FAV);
    const arr = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(arr) ? arr.map(Number) : []);
  } catch {
    return new Set();
  }
}

let favoriteIds = loadFavoriteSet();

function persistFavorites() {
  localStorage.setItem(LS_FAV, JSON.stringify([...favoriteIds]));
}

function toggleFavorite(id) {
  const n = Number(id);
  if (favoriteIds.has(n)) favoriteIds.delete(n);
  else favoriteIds.add(n);
  persistFavorites();
}

function isFavorite(id) {
  return favoriteIds.has(Number(id));
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    showToast("Đã copy vào clipboard");
  } catch {
    showToast("Không copy được (HTTPS hoặc quyền trình duyệt)");
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
  if (fetchedFromEl.value) params.set("fetched_from", fetchedFromEl.value);
  if (fetchedToEl.value) params.set("fetched_to", fetchedToEl.value);
  if (publishedFromEl.value) params.set("published_from", publishedFromEl.value);
  if (publishedToEl.value) params.set("published_to", publishedToEl.value);
  return params;
}

function getFilterState() {
  return {
    q: qEl.value,
    source: sourceEl.value,
    sortBy: sortByEl.value,
    sortOrder: sortOrderEl.value,
    pageSize: pageSizeEl.value,
    fetchedFrom: fetchedFromEl.value,
    fetchedTo: fetchedToEl.value,
    publishedFrom: publishedFromEl.value,
    publishedTo: publishedToEl.value,
  };
}

function applyFilterState(s) {
  qEl.value = s.q ?? "";
  sourceEl.value = s.source ?? "";
  sortByEl.value = s.sortBy ?? "fetched_at";
  sortOrderEl.value = s.sortOrder ?? "desc";
  pageSizeEl.value = String(s.pageSize ?? "20");
  pageSize = Number(pageSizeEl.value) || 20;
  fetchedFromEl.value = s.fetchedFrom ?? "";
  fetchedToEl.value = s.fetchedTo ?? "";
  publishedFromEl.value = s.publishedFrom ?? "";
  publishedToEl.value = s.publishedTo ?? "";
}

function loadSavedFilters() {
  try {
    const raw = localStorage.getItem(LS_FILTERS);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function saveSavedFilters(list) {
  localStorage.setItem(LS_FILTERS, JSON.stringify(list));
}

function refreshSavedFilterDropdown() {
  const list = loadSavedFilters();
  const cur = savedFilterSelect.value;
  savedFilterSelect.innerHTML = '<option value="">— Chưa chọn —</option>';
  for (const entry of list) {
    const opt = document.createElement("option");
    opt.value = entry.id;
    opt.textContent = entry.name;
    savedFilterSelect.appendChild(opt);
  }
  if (cur && list.some((x) => x.id === cur)) savedFilterSelect.value = cur;
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
  const fav = isFavorite(a.id);
  return `
    <tr data-id="${esc(String(a.id))}">
      <td class="col-star">
        <button type="button" class="star-btn ${fav ? "on" : ""}" data-star="${esc(String(a.id))}" title="Yêu thích" aria-pressed="${fav}">★</button>
      </td>
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
          <button type="button" class="btn btn-ghost btn-icon" data-detail="${esc(String(a.id))}">Chi tiết</button>
          <a class="btn btn-ghost btn-icon" href="${esc(a.canonical_url)}" target="_blank" rel="noopener noreferrer">Mở link</a>
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
  statusText.textContent = "Database unreachable";
  statusDot.className = "dot err";
}

function wireTableActions() {
  tbodyEl.querySelectorAll("button[data-copy]").forEach((btn) => {
    btn.addEventListener("click", () => copyText(btn.getAttribute("data-copy")));
  });
  tbodyEl.querySelectorAll("button[data-star]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const id = btn.getAttribute("data-star");
      toggleFavorite(id);
      btn.classList.toggle("on", isFavorite(id));
      btn.setAttribute("aria-pressed", String(isFavorite(id)));
      showToast(isFavorite(id) ? "Đã thêm vào yêu thích" : "Đã bỏ yêu thích");
    });
  });
  tbodyEl.querySelectorAll("button[data-detail]").forEach((btn) => {
    btn.addEventListener("click", () => openArticleModal(btn.getAttribute("data-detail")));
  });
}

async function openArticleModal(id) {
  articleModal.hidden = false;
  modalTitle.textContent = "Chi tiết bài";
  modalBody.innerHTML = '<p class="muted">Đang tải…</p>';
  document.body.style.overflow = "hidden";
  try {
    const res = await fetch(`/api/articles/${encodeURIComponent(id)}`);
    if (!res.ok) {
      modalBody.innerHTML = `<p class="muted">Lỗi ${res.status}</p>`;
      return;
    }
    const a = await res.json();
    modalTitle.textContent = a.display_title || a.title || "Chi tiết bài";
    const sum = (a.summary || "").trim() || "—";
    modalBody.innerHTML = `
      <div class="meta-grid">
        <div>ID: ${esc(String(a.id))}</div>
        <div>Source: ${esc(a.source)}</div>
        <div>Published: ${esc(a.published_at || "—")}</div>
        <div>Fetched: ${esc(a.fetched_at || "—")}</div>
        <div style="grid-column:1/-1;word-break:break-all;">URL: <a href="${esc(a.canonical_url)}" target="_blank" rel="noopener noreferrer">${esc(a.canonical_url)}</a></div>
      </div>
      <p class="field-label" style="margin-bottom:0.35rem">Summary / nội dung</p>
      <div class="full-summary">${esc(sum)}</div>
    `;
  } catch (e) {
    modalBody.innerHTML = `<p class="muted">${esc(String(e))}</p>`;
  }
}

function closeArticleModal() {
  articleModal.hidden = true;
  document.body.style.overflow = "";
}

function exportCsv() {
  if (!lastDisplayItems.length) {
    showToast("Không có dữ liệu để export");
    return;
  }
  const rows = [["id", "display_title", "source", "canonical_url", "published_at", "fetched_at"]];
  for (const a of lastDisplayItems) {
    const cells = [
      a.id,
      a.display_title ?? "",
      a.source ?? "",
      a.canonical_url ?? "",
      a.published_at ?? "",
      a.fetched_at ?? "",
    ].map((c) => {
      const s = String(c);
      if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
      return s;
    });
    rows.push(cells);
  }
  const blob = new Blob([rows.map((r) => r.join(",")).join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `articles-page-${page}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
  showToast("Đã tải CSV");
}

async function loadData() {
  tbodyEl.innerHTML = '<tr><td colspan="7" class="empty">Loading…</td></tr>';
  const res = await fetch(`/api/articles?${buildParams().toString()}`);
  if (!res.ok) {
    const txt = await res.text();
    tbodyEl.innerHTML = `<tr><td colspan="7" class="empty">Lỗi API: ${esc(txt)}</td></tr>`;
    summaryEl.textContent = "";
    return;
  }
  const data = await res.json();
  lastPayload = data;
  lastRawItems = data.items || [];
  let items = lastRawItems;
  const favOnly = favoritesOnlyEl.checked;
  if (favOnly) {
    items = items.filter((a) => isFavorite(a.id));
  }
  lastDisplayItems = items;

  const totalPages = Math.max(1, Math.ceil(Number(data.total) / Number(data.page_size)));
  pageInfoEl.textContent = `Page ${data.page} / ${totalPages}`;
  document.getElementById("prevBtn").disabled = data.page <= 1;
  document.getElementById("nextBtn").disabled = data.page >= totalPages;

  if (favOnly) {
    summaryEl.textContent = `Yêu thích trên trang này: ${items.length} / ${lastRawItems.length} bài · Tổng DB (filter): ${Number(data.total).toLocaleString()}`;
  } else {
    summaryEl.textContent = `Hiển thị ${data.items.length.toLocaleString()} / ${Number(data.total).toLocaleString()} bài · page size ${data.page_size}`;
  }

  tbodyEl.innerHTML = items.length
    ? items.map(renderRow).join("")
    : `<tr><td colspan="7" class="empty">${
        favOnly ? "Không có bài yêu thích trên trang này — bỏ tick hoặc sang trang khác." : "Không có bản ghi. Thử bỏ filter hoặc đổi từ khóa."
      }</td></tr>`;

  wireTableActions();
}

function scheduleLoad() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    page = 1;
    loadData();
  }, 420);
}

function setDateRangeDays(days) {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - (days - 1));
  const fmt = (d) => d.toISOString().slice(0, 10);
  fetchedFromEl.value = fmt(start);
  fetchedToEl.value = fmt(end);
  publishedFromEl.value = "";
  publishedToEl.value = "";
  sortByEl.value = "fetched_at";
  sortOrderEl.value = "desc";
  page = 1;
  loadData();
}

function initTheme() {
  const t = localStorage.getItem(LS_THEME);
  if (t === "light" || t === "dark") {
    document.documentElement.setAttribute("data-theme", t);
  } else if (window.matchMedia("(prefers-color-scheme: light)").matches) {
    document.documentElement.setAttribute("data-theme", "light");
  } else {
    document.documentElement.setAttribute("data-theme", "dark");
  }
}

themeToggle.addEventListener("click", () => {
  const isLight = document.documentElement.getAttribute("data-theme") === "light";
  const next = isLight ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem(LS_THEME, next);
  showToast(next === "light" ? "Giao diện sáng" : "Giao diện tối");
});

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
  fetchedFromEl.value = "";
  fetchedToEl.value = "";
  publishedFromEl.value = "";
  publishedToEl.value = "";
  favoritesOnlyEl.checked = false;
  page = 1;
  loadData();
});

document.getElementById("exportBtn").addEventListener("click", () => {
  if (!lastPayload) {
    showToast("Chưa có dữ liệu để export");
    return;
  }
  const payload = {
    ...lastPayload,
    items: lastDisplayItems,
    export_note: favoritesOnlyEl.checked ? "items_filtered_favorites_on_this_page" : "full_page",
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `articles-page-${lastPayload.page}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
  showToast("Đã tải JSON");
});

document.getElementById("exportCsvBtn").addEventListener("click", exportCsv);

document.getElementById("range7d").addEventListener("click", () => setDateRangeDays(7));
document.getElementById("range30d").addEventListener("click", () => setDateRangeDays(30));
document.getElementById("clearDates").addEventListener("click", () => {
  fetchedFromEl.value = "";
  fetchedToEl.value = "";
  publishedFromEl.value = "";
  publishedToEl.value = "";
  page = 1;
  loadData();
});

document.getElementById("saveFilterBtn").addEventListener("click", () => {
  const name = window.prompt("Tên bộ lọc (vd. Tin 7 ngày):");
  if (!name || !name.trim()) return;
  const list = loadSavedFilters();
  list.push({ id: `f-${Date.now()}`, name: name.trim(), state: getFilterState() });
  saveSavedFilters(list);
  refreshSavedFilterDropdown();
  savedFilterSelect.value = list[list.length - 1].id;
  showToast("Đã lưu bộ lọc");
});

document.getElementById("deleteFilterBtn").addEventListener("click", () => {
  const id = savedFilterSelect.value;
  if (!id) {
    showToast("Chọn bộ lọc cần xóa");
    return;
  }
  const list = loadSavedFilters().filter((x) => x.id !== id);
  saveSavedFilters(list);
  refreshSavedFilterDropdown();
  showToast("Đã xóa");
});

savedFilterSelect.addEventListener("change", () => {
  const id = savedFilterSelect.value;
  if (!id) return;
  const entry = loadSavedFilters().find((x) => x.id === id);
  if (!entry) return;
  applyFilterState(entry.state);
  page = 1;
  loadData();
});

favoritesOnlyEl.addEventListener("change", () => {
  page = 1;
  loadData();
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

[fetchedFromEl, fetchedToEl, publishedFromEl, publishedToEl, sourceEl, sortByEl, sortOrderEl].forEach((el) => {
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

modalClose.addEventListener("click", closeArticleModal);
modalBackdrop.addEventListener("click", closeArticleModal);

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && !articleModal.hidden) {
    closeArticleModal();
    return;
  }
  if (ev.key === "/" && document.activeElement !== qEl && !ev.ctrlKey && !ev.metaKey) {
    const t = ev.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
    ev.preventDefault();
    qEl.focus();
  }
});

const s3tbody = document.getElementById("s3tbody");
const s3PrefixEl = document.getElementById("s3Prefix");
const s3RefreshBtn = document.getElementById("s3RefreshBtn");
const s3MoreBtn = document.getElementById("s3MoreBtn");
const s3summary = document.getElementById("s3summary");

let s3NextToken = null;

function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

async function loadS3Exports(append) {
  if (append && !s3NextToken) return;
  if (!append) {
    s3tbody.innerHTML = '<tr><td colspan="4" class="empty">Đang tải…</td></tr>';
    s3NextToken = null;
  }
  const params = new URLSearchParams({ max_keys: "40" });
  if (s3PrefixEl.value.trim()) params.set("prefix", s3PrefixEl.value.trim());
  if (append && s3NextToken) params.set("continuation_token", s3NextToken);

  let res;
  try {
    res = await fetch(`/api/s3/exports?${params}`);
  } catch (e) {
    s3tbody.innerHTML = `<tr><td colspan="4" class="empty">Lỗi mạng: ${esc(String(e))}</td></tr>`;
    s3summary.textContent = "";
    s3MoreBtn.hidden = true;
    return;
  }
  let data;
  try {
    data = await res.json();
  } catch {
    s3tbody.innerHTML = '<tr><td colspan="4" class="empty">Phản hồi không phải JSON</td></tr>';
    return;
  }
  if (!res.ok) {
    const msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data);
    s3tbody.innerHTML = `<tr><td colspan="4" class="empty">${esc(msg)}</td></tr>`;
    s3summary.textContent = "";
    s3MoreBtn.hidden = true;
    return;
  }

  if (!append) s3tbody.innerHTML = "";
  const rows = (data.items || []).map((obj) => {
    const key = obj.key;
    const lm = obj.last_modified ? formatRel(obj.last_modified) : "—";
    return `<tr>
      <td class="s3-key"><code>${esc(key)}</code></td>
      <td class="col-s3-size">${formatBytes(obj.size || 0)}</td>
      <td class="col-dt">${lm}</td>
      <td class="col-actions"><button type="button" class="btn btn-ghost btn-sm" data-s3-dl="${esc(key)}">Tải</button></td>
    </tr>`;
  });
  if (!append && !rows.length) {
    s3tbody.innerHTML = '<tr><td colspan="4" class="empty">Bucket trống hoặc không có object khớp prefix.</td></tr>';
  } else {
    s3tbody.insertAdjacentHTML("beforeend", rows.join(""));
  }

  s3tbody.querySelectorAll("button[data-s3-dl]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const key = btn.getAttribute("data-s3-dl");
      try {
        const pr = await fetch(`/api/s3/exports/presign?key=${encodeURIComponent(key)}`);
        const pd = await pr.json();
        if (!pr.ok) {
          showToast(typeof pd.detail === "string" ? pd.detail : "Presign failed");
          return;
        }
        window.open(pd.url, "_blank", "noopener,noreferrer");
      } catch (e) {
        showToast(String(e));
      }
    });
  });

  s3NextToken = data.next_continuation_token || null;
  s3MoreBtn.hidden = !data.is_truncated || !s3NextToken;
  s3summary.textContent = `Bucket: ${esc(data.bucket || "")} · prefix: ${esc(data.prefix || "")} · ${(data.items || []).length} object(s) trên trang này`;
}

s3RefreshBtn.addEventListener("click", () => loadS3Exports(false));
s3MoreBtn.addEventListener("click", () => loadS3Exports(true));
s3PrefixEl.addEventListener("change", () => loadS3Exports(false));

const crawlNowBtn = document.getElementById("crawlNowBtn");
const crawlStatus = document.getElementById("crawlStatus");
let crawlPollTimer = null;

async function refreshCrawlStatus() {
  try {
    const res = await fetch("/api/crawl/status");
    const data = await res.json();
    const running = Boolean(data.manual_running);
    crawlNowBtn.disabled = running;
    crawlStatus.textContent = running ? "Đang chạy crawl thủ công…" : "Sẵn sàng.";
    crawlStatus.classList.toggle("is-busy", running);
    return running;
  } catch {
    crawlStatus.textContent = "Không đọc được trạng thái.";
    return false;
  }
}

crawlNowBtn.addEventListener("click", async () => {
  crawlNowBtn.disabled = true;
  crawlStatus.textContent = "Đang gửi yêu cầu…";
  try {
    const res = await fetch("/api/crawl/now", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data);
      showToast(msg);
      crawlNowBtn.disabled = false;
      crawlStatus.textContent = "Sẵn sàng.";
      return;
    }
    showToast(data.message || "Đã bắt đầu crawl");
    crawlStatus.textContent = "Đang chạy crawl thủ công…";
    crawlStatus.classList.add("is-busy");
    if (crawlPollTimer) clearInterval(crawlPollTimer);
    let n = 0;
    crawlPollTimer = setInterval(async () => {
      n += 1;
      const still = await refreshCrawlStatus();
      if (!still || n > 600) {
        clearInterval(crawlPollTimer);
        crawlPollTimer = null;
        if (n > 600) crawlStatus.textContent = "Hết thời gian chờ — kiểm tra log worker.";
      }
    }, 2000);
  } catch (e) {
    showToast(String(e));
    crawlNowBtn.disabled = false;
    crawlStatus.textContent = "Sẵn sàng.";
  }
});

refreshCrawlStatus();

initTheme();
refreshSavedFilterDropdown();
loadStats();
loadSources();
loadStatus();
loadData();
loadS3Exports(false);
