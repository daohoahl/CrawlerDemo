let page = 1;
const pageSize = 20;

const qEl = document.getElementById("q");
const sourceEl = document.getElementById("source");
const sortByEl = document.getElementById("sortBy");
const sortOrderEl = document.getElementById("sortOrder");
const resultsEl = document.getElementById("results");
const summaryEl = document.getElementById("summary");
const pageInfoEl = document.getElementById("pageInfo");

function esc(s) {
  return (s || "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
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

function renderItem(a) {
  return `
    <article class="item">
      <h3>${esc(a.title || "(No title)")}</h3>
      <div class="meta-line">source: ${esc(a.source)} | fetched_at: ${esc(a.fetched_at || "-")} | published_at: ${esc(a.published_at || "-")}</div>
      <p>${esc((a.summary || "").slice(0, 300))}</p>
      <a href="${esc(a.canonical_url)}" target="_blank" rel="noopener noreferrer">${esc(a.canonical_url)}</a>
    </article>
  `;
}

async function loadData() {
  resultsEl.innerHTML = "Loading...";
  const res = await fetch(`/api/articles?${buildParams().toString()}`);
  if (!res.ok) {
    const txt = await res.text();
    resultsEl.innerHTML = `<div class="item">Error: ${esc(txt)}</div>`;
    return;
  }
  const data = await res.json();
  summaryEl.textContent = `Total ${data.total} articles`;
  pageInfoEl.textContent = `Page ${data.page}`;
  resultsEl.innerHTML = data.items.length ? data.items.map(renderItem).join("") : '<div class="item">No data found.</div>';
}

document.getElementById("searchBtn").addEventListener("click", () => {
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

loadData();
