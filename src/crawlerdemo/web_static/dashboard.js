const LS_THEME = "crawler-theme";

let page = 1;
let pageSize = 20;
let lastPayload = null;
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
const themeToggle = document.getElementById("themeToggle");
const crawlNowBtn = document.getElementById("crawlNowBtn");
const crawlStatusEl = document.getElementById("crawlStatus");

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

async function parseFetchBody(res) {
  const text = await res.text();
  if (!text.trim()) {
    return { text, data: null, jsonOk: false };
  }
  try {
    return { text, data: JSON.parse(text), jsonOk: true };
  } catch {
    return { text, data: null, jsonOk: false };
  }
}

function httpNonJsonMessage(status, text) {
  const preview = text.replace(/\s+/g, " ").trim().slice(0, 240);
  return `HTTP ${status}: không phải JSON${preview ? ` — ${preview}` : ""}`;
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

function formatRel(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return esc(iso);
  const now = Date.now();
  const diff = Math.floor((now - d.getTime()) / 1000);
  if (diff < 60) return `${diff}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)} phút`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} giờ`;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function renderRow(a) {
  const rawTitle = (a.title || "").trim();
  const missing = !rawTitle;
  const headline = esc(a.display_title || rawTitle || "Không tiêu đề");
  const sum = esc((a.summary || "").replace(/\s+/g, " ").trim());
  return `
    <tr data-id="${esc(String(a.id))}">
      <td class="col-id">${esc(String(a.id))}</td>
      <td class="title-cell">
        <strong>${headline}</strong>${missing ? '<span class="title-badge" title="Suy ra từ summary/URL">*</span>' : ""}
        ${sum ? `<p class="snippet">${sum}</p>` : ""}
      </td>
      <td class="col-source">${esc(a.source)}</td>
      <td class="col-dt">${formatRel(a.published_at)}</td>
      <td class="col-dt">${formatRel(a.fetched_at)}</td>
      <td class="col-actions">
        <div class="action-row">
          <button type="button" class="btn btn-ghost btn-icon" data-detail="${esc(String(a.id))}">Chi tiết</button>
          <a class="btn btn-ghost btn-icon" href="${esc(a.canonical_url)}" target="_blank" rel="noopener noreferrer">Mở</a>
          <button type="button" class="btn btn-ghost btn-icon" data-copy="${esc(a.canonical_url)}">Copy URL</button>
        </div>
      </td>
    </tr>
  `;
}

function renderKpis(stats) {
  kpiRoot.innerHTML = `
    <div class="kpi">
      <div class="kpi-label">Tổng bài</div>
      <div class="kpi-value">${Number(stats.total).toLocaleString()}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Fetch 24h</div>
      <div class="kpi-value">${Number(stats.fetched_last_24h).toLocaleString()}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Fetch gần nhất</div>
      <div class="kpi-value" style="font-size:1rem">${stats.last_fetched_at ? formatRel(stats.last_fetched_at) : "—"}</div>
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
    kpiRoot.innerHTML = `<div class="kpi kpi-wide"><div class="kpi-meta">Không tải thống kê: ${esc(String(e))}</div></div>`;
  }
}

async function loadSources() {
  try {
    const res = await fetch("/api/sources");
    if (!res.ok) throw new Error();
    const data = await res.json();
    const items = data.items || [];
    const current = sourceEl.value;
    sourceEl.innerHTML = '<option value="">Tất cả</option>';
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
      statusText.textContent = "DB OK";
      statusDot.className = "dot ok";
      return;
    }
  } catch {
    /* fallthrough */
  }
  statusText.textContent = "Không kết nối DB";
  statusDot.className = "dot err";
}

function wireTableActions() {
  tbodyEl.querySelectorAll("button[data-copy]").forEach((btn) => {
    btn.addEventListener("click", () => copyText(btn.getAttribute("data-copy")));
  });
  tbodyEl.querySelectorAll("button[data-detail]").forEach((btn) => {
    btn.addEventListener("click", () => openArticleModal(btn.getAttribute("data-detail")));
  });
}

async function openArticleModal(id) {
  articleModal.hidden = false;
  modalTitle.textContent = "Chi tiết";
  modalBody.innerHTML = '<p class="muted">Đang tải…</p>';
  document.body.style.overflow = "hidden";
  try {
    const res = await fetch(`/api/articles/${encodeURIComponent(id)}`);
    if (!res.ok) {
      modalBody.innerHTML = `<p class="muted">Lỗi ${res.status}</p>`;
      return;
    }
    const a = await res.json();
    modalTitle.textContent = a.display_title || a.title || "Chi tiết";
    const sum = (a.summary || "").trim() || "—";
    modalBody.innerHTML = `
      <div class="meta-grid">
        <div>ID: ${esc(String(a.id))}</div>
        <div>Nguồn: ${esc(a.source)}</div>
        <div>Publish: ${esc(a.published_at || "—")}</div>
        <div>Fetch: ${esc(a.fetched_at || "—")}</div>
        <div style="grid-column:1/-1;word-break:break-all;">URL: <a href="${esc(a.canonical_url)}" target="_blank" rel="noopener noreferrer">${esc(a.canonical_url)}</a></div>
      </div>
      <p class="field-label" style="margin-bottom:0.35rem">Tóm tắt</p>
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

async function loadData() {
  tbodyEl.innerHTML = '<tr><td colspan="6" class="empty">Đang tải…</td></tr>';
  const res = await fetch(`/api/articles?${buildParams().toString()}`);
  if (!res.ok) {
    const txt = await res.text();
    tbodyEl.innerHTML = `<tr><td colspan="6" class="empty">Lỗi: ${esc(txt)}</td></tr>`;
    summaryEl.textContent = "";
    return;
  }
  const data = await res.json();
  lastPayload = data;
  const items = data.items || [];

  const totalPages = Math.max(1, Math.ceil(Number(data.total) / Number(data.page_size)));
  pageInfoEl.textContent = `${data.page} / ${totalPages}`;
  document.getElementById("prevBtn").disabled = data.page <= 1;
  document.getElementById("nextBtn").disabled = data.page >= totalPages;

  summaryEl.textContent = `${items.length.toLocaleString()} / ${Number(data.total).toLocaleString()} bài (trang ${data.page_size})`;

  tbodyEl.innerHTML = items.length
    ? items.map(renderRow).join("")
    : '<tr><td colspan="6" class="empty">Không có bản ghi — thử bỏ bộ lọc.</td></tr>';

  wireTableActions();
}

function scheduleLoad() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    page = 1;
    loadData();
  }, 420);
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

/** sessionStorage: sau khi bấm Tải, ~1 giờ ẩn nút Tải (presigned hết hạn theo quy ước UI). */
const S3_PRESIGN_AT_PREFIX = "crawler_s3_presign_at_";
const S3_PRESIGN_TTL_MS = 3600 * 1000;

function s3PresignStorageKey(objectKey) {
  return S3_PRESIGN_AT_PREFIX + objectKey;
}

function s3PresignCooldownLeftMs(objectKey) {
  try {
    const raw = sessionStorage.getItem(s3PresignStorageKey(objectKey));
    if (!raw) return 0;
    const at = Number(raw);
    if (Number.isNaN(at)) return 0;
    const left = S3_PRESIGN_TTL_MS - (Date.now() - at);
    return left > 0 ? left : 0;
  } catch {
    return 0;
  }
}

function formatPresignCooldownShort(ms) {
  const m = Math.ceil(ms / 60000);
  return m < 1 ? "<1 phút" : `~${m} phút`;
}

function renderS3ActionCell(objectKey) {
  const left = s3PresignCooldownLeftMs(objectKey);
  if (left > 0) {
    return `<span class="muted" title="Link presigned thường ~1 giờ; sau đó bấm Lấy link mới.">Đã tạo (${formatPresignCooldownShort(left)})</span> <button type="button" class="btn btn-ghost btn-sm" data-s3-renew="${esc(objectKey)}">Lấy link mới</button>`;
  }
  return `<button type="button" class="btn btn-ghost btn-sm" data-s3-dl="${esc(objectKey)}">Tải</button>`;
}

async function openS3Presign(objectKey) {
  const pr = await fetch(
    `/api/s3/exports/presign?key=${encodeURIComponent(objectKey)}&expires_seconds=3600`,
    { headers: { Accept: "application/json" } },
  );
  const { text: pt, data: pd, jsonOk: pj } = await parseFetchBody(pr);
  if (!pj) {
    showToast(httpNonJsonMessage(pr.status, pt));
    return;
  }
  if (!pr.ok) {
    showToast(typeof pd.detail === "string" ? pd.detail : "Presign failed");
    return;
  }
  window.open(pd.url, "_blank", "noopener,noreferrer");
  try {
    sessionStorage.setItem(s3PresignStorageKey(objectKey), String(Date.now()));
  } catch {
    /* quota / private mode */
  }
  loadS3Exports(false);
}

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
    res = await fetch(`/api/s3/exports?${params}`, { headers: { Accept: "application/json" } });
  } catch (e) {
    s3tbody.innerHTML = `<tr><td colspan="4" class="empty">Lỗi mạng: ${esc(String(e))}</td></tr>`;
    s3summary.textContent = "";
    s3MoreBtn.hidden = true;
    return;
  }
  const { text, data, jsonOk } = await parseFetchBody(res);
  if (!jsonOk) {
    s3tbody.innerHTML = `<tr><td colspan="4" class="empty">${esc(httpNonJsonMessage(res.status, text))}</td></tr>`;
    s3summary.textContent = "";
    s3MoreBtn.hidden = true;
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
      <td class="col-actions">${renderS3ActionCell(key)}</td>
    </tr>`;
  });
  if (!append && !rows.length) {
    s3tbody.innerHTML = '<tr><td colspan="4" class="empty">Bucket trống hoặc không khớp prefix.</td></tr>';
  } else {
    s3tbody.insertAdjacentHTML("beforeend", rows.join(""));
  }

  s3NextToken = data.next_continuation_token || null;
  s3MoreBtn.hidden = !data.is_truncated || !s3NextToken;
  s3summary.textContent = `Bucket: ${esc(data.bucket || "")} · ${(data.items || []).length} object — sau khi bấm Tải, ~1 giờ không hiện lại Tải (dùng Lấy link mới nếu cần)`;
}

s3tbody.addEventListener("click", async (ev) => {
  const renew = ev.target.closest("[data-s3-renew]");
  if (renew) {
    const key = renew.getAttribute("data-s3-renew");
    if (key) {
      try {
        sessionStorage.removeItem(s3PresignStorageKey(key));
      } catch {
        /* ignore */
      }
      loadS3Exports(false);
    }
    return;
  }
  const dl = ev.target.closest("[data-s3-dl]");
  if (!dl) return;
  const key = dl.getAttribute("data-s3-dl");
  if (!key) return;
  try {
    await openS3Presign(key);
  } catch (e) {
    showToast(String(e));
  }
});

s3RefreshBtn.addEventListener("click", () => loadS3Exports(false));
s3MoreBtn.addEventListener("click", () => loadS3Exports(true));
s3PrefixEl.addEventListener("change", () => loadS3Exports(false));

function setCrawlUi(busy, message) {
  if (crawlNowBtn) crawlNowBtn.disabled = !!busy;
  if (crawlStatusEl) crawlStatusEl.textContent = message || "";
}

/** Sau khi worker gửi SQS, Lambda ghi DB lệch vài giây — làm mới thêm vài lần. */
async function refreshAfterIngestDelays() {
  const delays = [4000, 10000, 20000];
  for (const ms of delays) {
    await new Promise((r) => setTimeout(r, ms));
    await loadStats();
    await loadData();
  }
}

async function pollCrawlUntilDone() {
  for (let i = 0; i < 600; i += 1) {
    await new Promise((r) => setTimeout(r, 1000));
    let st;
    try {
      st = await fetch("/api/crawl/status", { headers: { Accept: "application/json" } });
    } catch {
      setCrawlUi(false, "Không kiểm tra được trạng thái crawl.");
      return;
    }
    const { data, jsonOk } = await parseFetchBody(st);
    if (!jsonOk || !st.ok) {
      setCrawlUi(false, "Lỗi kiểm tra trạng thái crawl.");
      return;
    }
    if (!data.busy) {
      if (data.last_error) {
        showToast(`Crawl lỗi: ${data.last_error}`);
        setCrawlUi(false, "");
      } else {
        setCrawlUi(false, "Đã gửi queue — đợi Lambda ghi DB…");
        await loadStats();
        await loadData();
        await refreshAfterIngestDelays();
        setCrawlUi(false, "");
        showToast(
          "Đã làm mới bảng. Không thấy bài mới? Thường do URL trùng (đã có trong DB) hoặc nguồn không có tin mới.",
        );
      }
      return;
    }
    setCrawlUi(true, "Đang crawl (gửi nguồn → SQS)…");
  }
  setCrawlUi(false, "Hết thời gian chờ (thử làm mới trang).");
}

async function triggerCrawl() {
  if (!crawlNowBtn) return;
  setCrawlUi(true, "Đang crawl…");
  try {
    const res = await fetch("/api/crawl", { method: "POST", headers: { Accept: "application/json" } });
    const { text, data, jsonOk } = await parseFetchBody(res);
    if (res.status === 409) {
      showToast(typeof data?.detail === "string" ? data.detail : "Đang crawl rồi.");
      await pollCrawlUntilDone();
      return;
    }
    if (!jsonOk || !res.ok) {
      setCrawlUi(false, "");
      showToast(jsonOk && data?.detail ? String(data.detail) : httpNonJsonMessage(res.status, text));
      return;
    }
    showToast(data.message || "Đã bắt đầu crawl.");
    await pollCrawlUntilDone();
  } catch (e) {
    setCrawlUi(false, "");
    showToast(String(e));
  }
}

if (crawlNowBtn) {
  crawlNowBtn.addEventListener("click", () => {
    triggerCrawl();
  });
}

initTheme();
loadStats();
loadSources();
loadStatus();
loadData();
loadS3Exports(false);
