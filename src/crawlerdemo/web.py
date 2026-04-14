from __future__ import annotations

import html
import threading
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from crawlerdemo.config import get_settings
from crawlerdemo.db import init_db, list_recent, make_engine
from crawlerdemo.export import export_csv, export_json, generate_presigned_url, upload_to_s3
from crawlerdemo.worker import run_once


def create_app() -> FastAPI:
    s = get_settings()
    engine = make_engine(s.database_url)
    init_db(engine)

    app = FastAPI(title="CrawlerDemo", version="0.1.0")
    crawl_lock = threading.Lock()
    crawl_state = {
        "is_running": False,
        "last_started_at": None,
        "last_finished_at": None,
        "last_error": None,
    }

    def _run_crawl_job() -> None:
        try:
            run_once()
            crawl_state["last_error"] = None
        except Exception as exc:  # pragma: no cover - runtime error path
            crawl_state["last_error"] = str(exc)
        finally:
            with crawl_lock:
                crawl_state["is_running"] = False
                crawl_state["last_finished_at"] = datetime.now(timezone.utc).isoformat()

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/api/articles")
    def api_articles(limit: int = 50):
        with Session(engine) as session:
            rows = list_recent(session, limit=limit)
        return [
            {
                "id": r.id,
                "source": r.source,
                "canonical_url": r.canonical_url,
                "title": r.title,
                "summary": r.summary,
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
            }
            for r in rows
        ]

    @app.get("/api/crawl-status")
    def crawl_status():
        with crawl_lock:
            return dict(crawl_state)

    # ------------------------------------------------------------------
    # Export endpoints
    # ------------------------------------------------------------------

    @app.get("/api/export/csv")
    def export_csv_endpoint(limit: int = Query(default=10_000, ge=1, le=100_000)):
        """Stream CSV file trực tiếp về client."""
        with Session(engine) as session:
            data, row_count = export_csv(session, limit=limit)
        filename = f"articles_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
        return StreamingResponse(
            iter([data]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Row-Count": str(row_count),
            },
        )

    @app.get("/api/export/json")
    def export_json_endpoint(limit: int = Query(default=10_000, ge=1, le=100_000)):
        """Stream JSON file trực tiếp về client."""
        with Session(engine) as session:
            data, row_count = export_json(session, limit=limit)
        filename = f"articles_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
        return StreamingResponse(
            iter([data]),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Row-Count": str(row_count),
            },
        )

    @app.post("/api/export/s3")
    def export_to_s3(fmt: str = Query(default="csv", pattern="^(csv|json)$"),
                     limit: int = Query(default=10_000, ge=1, le=100_000)):
        """Upload snapshot lên S3 và trả presigned URL để download."""
        if not s.s3_bucket:
            raise HTTPException(
                status_code=503,
                detail="S3 bucket not configured. Set CRAWLER_S3_BUCKET env var.",
            )
        with Session(engine) as session:
            if fmt == "csv":
                data, row_count = export_csv(session, limit=limit)
                content_type = "text/csv"
            else:
                data, row_count = export_json(session, limit=limit)
                content_type = "application/json"

        key = upload_to_s3(
            data=data,
            bucket=s.s3_bucket,
            prefix=s.s3_export_prefix,
            fmt=fmt,
            region=s.s3_region,
            content_type=content_type,
        )
        presigned_url = generate_presigned_url(
            bucket=s.s3_bucket,
            key=key,
            region=s.s3_region,
            expires=s.s3_presigned_url_expires,
        )
        return {
            "ok": True,
            "s3_key": key,
            "row_count": row_count,
            "format": fmt,
            "download_url": presigned_url,
            "expires_in_seconds": s.s3_presigned_url_expires,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/api/sources")
    def api_sources():
        rss = [str(u) for u in s.rss_urls]
        sitemap = [str(u) for u in s.sitemap_urls]
        return {
            "rss": rss,
            "sitemap": sitemap,
            "all": rss + sitemap,
        }

    @app.post("/api/crawl")
    def start_crawl():
        with crawl_lock:
            if crawl_state["is_running"]:
                raise HTTPException(status_code=409, detail="A crawl job is already running.")
            crawl_state["is_running"] = True
            crawl_state["last_started_at"] = datetime.now(timezone.utc).isoformat()
            crawl_state["last_error"] = None
        threading.Thread(target=_run_crawl_job, daemon=True).start()
        return {"ok": True, "message": "Crawl job started."}

    @app.get("/")
    def index(limit: int = 50):
        safe_title = html.escape("CrawlerDemo Dashboard")
        return HTMLResponse(
            f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{safe_title}</title>
    <meta name="description" content="CrawlerDemo Dashboard — monitor crawled articles, trigger crawl jobs, and export data." />
    <style>
      :root {{
        --bg: #0a1020;
        --bg-soft: #111a31;
        --card: #111a2f;
        --text: #ebf2ff;
        --muted: #9eb0d6;
        --line: #253556;
        --brand: #4d8ef7;
        --brand-soft: #1d4b95;
        --ok: #36d399;
        --warn: #fbbf24;
        --error: #ff7a90;
      }}
      * {{
        box-sizing: border-box;
      }}
      body {{
        margin: 0;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
        background: radial-gradient(circle at top right, #1f3870 0%, var(--bg) 46%);
        color: var(--text);
      }}
      .page {{
        max-width: 1180px;
        margin: 0 auto;
        padding: 28px 16px 42px;
      }}
      .topbar {{
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        flex-wrap: wrap;
        gap: 12px;
        margin-bottom: 16px;
      }}
      .page-title {{
        margin: 0;
        font-size: 30px;
        line-height: 1.1;
      }}
      .page-subtitle {{
        margin-top: 6px;
        color: var(--muted);
        font-size: 14px;
      }}
      .layout {{
        display: grid;
        grid-template-columns: 1fr;
        gap: 14px;
      }}
      .card {{
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0));
        border: 1px solid var(--line);
        border-radius: 14px;
        padding: 16px;
        box-shadow: 0 8px 26px rgba(0, 0, 0, 0.24);
      }}
      .btn-export {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 8px 14px;
        border-radius: 10px;
        border: 1px solid var(--line);
        background: #0d1630;
        color: var(--text);
        font-size: 13px;
        cursor: pointer;
        text-decoration: none;
        transition: 0.2s ease;
        white-space: nowrap;
      }}
      .btn-export:hover {{
        border-color: #3a5384;
        background: #132348;
        text-decoration: none;
      }}
      .btn-s3 {{
        border-color: #2d5a2d;
        color: var(--ok);
      }}
      .btn-s3:hover {{
        background: #0f2a0f;
        border-color: var(--ok);
      }}
      .s3-result {{
        background: #0a1f0a;
        border: 1px solid #2d5a2d;
        border-radius: 10px;
        padding: 12px 14px;
        margin-top: 10px;
        display: none;
        font-size: 13px;
        color: var(--ok);
        word-break: break-all;
      }}
      .s3-result a {{
        color: var(--ok);
        font-weight: 600;
      }}
      .s3-result .s3-meta {{
        margin-top: 6px;
        color: var(--muted);
        font-size: 12px;
      }}
      .actions {{
        display: grid;
        grid-template-columns: 140px 1fr auto auto;
        gap: 10px;
        align-items: end;
      }}
      .field {{
        display: flex;
        flex-direction: column;
        gap: 6px;
      }}
      .label {{
        color: var(--muted);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.03em;
      }}
      input,
      button {{
        border-radius: 10px;
        border: 1px solid var(--line);
        background: #0d1630;
        color: var(--text);
        padding: 10px 12px;
        font-size: 14px;
      }}
      input:focus {{
        outline: 2px solid var(--brand-soft);
      }}
      button {{
        cursor: pointer;
        transition: 0.2s ease;
        height: 42px;
      }}
      .btn-primary {{
        background: var(--brand);
        border-color: var(--brand);
        color: #fff;
      }}
      .btn-primary:hover {{
        filter: brightness(1.08);
      }}
      .btn-secondary:hover {{
        border-color: #3a5384;
        background: #132348;
      }}
      .status-pill {{
        border: 1px solid var(--line);
        border-radius: 999px;
        padding: 8px 12px;
        font-size: 13px;
        color: var(--muted);
        background: rgba(255, 255, 255, 0.02);
      }}
      .status-pill.success {{
        color: var(--ok);
      }}
      .status-pill.warning {{
        color: var(--warn);
      }}
      .status-pill.error {{
        color: var(--error);
      }}
      .inline-status {{
        color: var(--muted);
        font-size: 13px;
      }}
      .stats {{
        display: grid;
        gap: 10px;
        grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      }}
      .metric-label {{
        color: var(--muted);
        font-size: 12px;
      }}
      .metric-value {{
        margin-top: 6px;
        font-size: 24px;
        font-weight: 700;
      }}
      .content {{
        display: grid;
        grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
        gap: 14px;
      }}
      .table-card {{
        overflow: auto;
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
        min-width: 760px;
      }}
      th,
      td {{
        padding: 11px 10px;
        border-bottom: 1px solid var(--line);
        text-align: left;
        vertical-align: top;
      }}
      th {{
        color: var(--muted);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }}
      .article-title {{
        font-weight: 600;
        margin-bottom: 4px;
      }}
      .nowrap {{
        white-space: nowrap;
      }}
      .muted {{
        color: var(--muted);
        font-size: 12px;
      }}
      a {{
        color: #7fb5ff;
        text-decoration: none;
      }}
      a:hover {{
        text-decoration: underline;
      }}
      .panel-title {{
        margin: 0 0 8px;
        font-size: 16px;
      }}
      .help-list {{
        margin: 0;
        padding-left: 18px;
        color: var(--muted);
        line-height: 1.6;
      }}
      .source-search {{
        margin: 8px 0 10px;
      }}
      .source-item {{
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 10px;
        margin-bottom: 9px;
        background: #0d1630;
      }}
      .source-type {{
        display: inline-block;
        font-size: 11px;
        color: var(--muted);
        border: 1px solid var(--line);
        padding: 2px 6px;
        border-radius: 999px;
        margin-bottom: 6px;
      }}
      @media (max-width: 980px) {{
        .actions {{
          grid-template-columns: 120px 1fr;
        }}
        .content {{
          grid-template-columns: 1fr;
        }}
      }}
      @media (max-width: 640px) {{
        .page-title {{
          font-size: 24px;
        }}
        .actions {{
          grid-template-columns: 1fr;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="page">
      <div class="topbar">
        <div>
          <h1 class="page-title">Crawler Dashboard</h1>
          <div class="page-subtitle">Track recent crawl results, trigger jobs manually, and explore configured sources.</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <a id="btn-dl-csv" href="/api/export/csv" class="btn-export" title="Download CSV">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            CSV
          </a>
          <a id="btn-dl-json" href="/api/export/json" class="btn-export" title="Download JSON">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            JSON
          </a>
          <button id="btn-s3-csv" class="btn-export btn-s3" title="Upload CSV to S3 &amp; get shareable link">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>
            S3 Link
          </button>
          <div class="status-pill" id="crawl-status-line">Crawler status: Loading...</div>
        </div>
      </div>

      <div class="layout">
        <div class="card">
          <div class="actions">
            <div class="field">
              <label class="label" for="limit">Items limit</label>
              <input id="limit" type="number" min="1" max="500" value="{int(limit)}" />
            </div>
            <div class="field">
              <label class="label" for="q">Search articles</label>
              <input id="q" type="text" placeholder="Search by source, title, or URL..." />
            </div>
            <button id="reload" class="btn-secondary">Refresh data</button>
            <button id="crawl" class="btn-primary">Run crawl now</button>
          </div>
          <div id="status" class="inline-status" style="margin-top:10px;">Ready.</div>
        </div>

        <div class="stats">
          <div class="card">
            <div class="metric-label">Visible items</div>
            <div class="metric-value" id="stat-visible">0</div>
          </div>
          <div class="card">
            <div class="metric-label">Loaded items</div>
            <div class="metric-value" id="stat-loaded">0</div>
          </div>
          <div class="card">
            <div class="metric-label">Detected sources</div>
            <div class="metric-value" id="stat-sources">0</div>
          </div>
          <div class="card">
            <div class="metric-label">Last UI refresh</div>
            <div class="metric-value" id="stat-last">--</div>
          </div>
        </div>

        <div class="content">
          <div class="card table-card">
            <h3 class="panel-title">Recent articles</h3>
            <table>
              <thead>
                <tr>
                  <th class="nowrap">Fetched at</th>
                  <th>Title and URL</th>
                  <th class="nowrap">Source</th>
                </tr>
              </thead>
              <tbody id="rows"></tbody>
            </table>
          </div>

          <div class="sidebar">
            <div class="card" style="margin-bottom:14px;">
              <h3 class="panel-title">Quick guide</h3>
              <ol class="help-list">
                <li>Click <b>Run crawl now</b> to fetch fresh data from all configured feeds.</li>
                <li>Use <b>Search articles</b> to filter by source name, title, or URL.</li>
                <li>Adjust <b>Items limit</b> then click <b>Refresh data</b>.</li>
                <li>Check the status badge to see whether the crawler is running, idle, or failed.</li>
              </ol>
            </div>

            <div class="card">
              <h3 class="panel-title">Configured sources</h3>
              <div class="muted">Search by domain or full URL.</div>
              <input id="source-q" class="source-search" type="text" placeholder="e.g. state.gov, guardian, sitemap" />
              <div id="source-list"></div>
            </div>

            <div class="card" style="margin-top:14px;">
              <h3 class="panel-title">Export &amp; Share via S3</h3>
              <div class="muted" style="margin-bottom:10px;font-size:13px;">Upload snapshot lên S3 và nhận link download (hết hạn sau 1 giờ).</div>
              <button id="btn-s3-csv" class="btn-export btn-s3" style="width:100%;justify-content:center;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>
                Upload CSV → S3 Link
              </button>
              <div id="s3-export-result" class="s3-result"></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <script>
      const $ = (id) => document.getElementById(id);
      const statusEl = $("status");
      const crawlStatusLine = $("crawl-status-line");
      let sourceData = [];

      function fmt(ts) {{
        if (!ts) return "";
        try {{ return new Date(ts).toLocaleString(); }} catch (e) {{ return ts; }}
      }}

      function contains(haystack, needle) {{
        return (haystack || "").toLowerCase().includes((needle || "").toLowerCase());
      }}

      async function load() {{
        const limit = parseInt($("limit").value || "50", 10);
        const q = $("q").value.trim();
        const url = `/api/articles?limit=${{encodeURIComponent(limit)}}`;
        statusEl.textContent = "Loading articles...";
        const t0 = performance.now();

        const resp = await fetch(url, {{ cache: "no-store" }});
        const data = await resp.json();
        const filtered = q
          ? data.filter(x =>
              contains(x.source, q) ||
              contains(x.title, q) ||
              contains(x.canonical_url, q)
            )
          : data;

        const tbody = $("rows");
        tbody.innerHTML = "";
        for (const x of filtered) {{
          const tr = document.createElement("tr");
          const title = x.title || x.canonical_url;
          tr.innerHTML = `
            <td class="muted nowrap">${{fmt(x.fetched_at)}}</td>
            <td>
              <div class="article-title"><a href="${{x.canonical_url}}" target="_blank" rel="noreferrer">${{title}}</a></div>
              <div class="muted">${{x.canonical_url}}</div>
            </td>
            <td class="muted nowrap">${{x.source}}</td>
          `;
          tbody.appendChild(tr);
        }}

        const uniqueSources = new Set(data.map((x) => x.source || "unknown")).size;
        $("stat-visible").textContent = String(filtered.length);
        $("stat-loaded").textContent = String(data.length);
        $("stat-sources").textContent = String(uniqueSources);
        $("stat-last").textContent = fmt(new Date().toISOString());

        const ms = Math.round(performance.now() - t0);
        statusEl.textContent = `Loaded ${{filtered.length}} of ${{data.length}} items in ${{ms}} ms.`;
      }}

      async function loadCrawlStatus() {{
        try {{
          const resp = await fetch("/api/crawl-status", {{ cache: "no-store" }});
          const s = await resp.json();
          let statusText = "";
          let statusClass = "status-pill";
          if (s.last_error) {{
            statusText = `Crawler status: Failed (${{
              s.last_finished_at ? fmt(s.last_finished_at) : "unknown time"
            }})`;
            statusClass += " error";
          }} else if (s.is_running) {{
            statusText = `Crawler status: Running (started ${{
              s.last_started_at ? fmt(s.last_started_at) : "unknown"
            }})`;
            statusClass += " warning";
          }} else {{
            statusText = `Crawler status: Idle (last run ${{
              s.last_finished_at ? fmt(s.last_finished_at) : "not started yet"
            }})`;
            statusClass += " success";
          }}
          crawlStatusLine.textContent = statusText;
          crawlStatusLine.className = statusClass;
          if (s.last_error) {{
            statusEl.textContent = `Last crawl error: ${{s.last_error}}`;
            statusEl.className = "inline-status";
            statusEl.style.color = "var(--error)";
          }} else {{
            statusEl.className = "inline-status";
            statusEl.style.color = "var(--muted)";
          }}
        }} catch (e) {{
          crawlStatusLine.textContent = "Crawler status: Unavailable";
          crawlStatusLine.className = "status-pill error";
        }}
      }}

      async function triggerCrawl() {{
        const btn = $("crawl");
        btn.disabled = true;
        statusEl.textContent = "Sending crawl request...";
        try {{
          const resp = await fetch("/api/crawl", {{ method: "POST" }});
          if (!resp.ok) {{
            const err = await resp.json().catch(() => ({{ detail: "Unknown error" }}));
            throw new Error(err.detail || "Cannot start crawl");
          }}
          statusEl.textContent = "Crawl started. Data will refresh automatically.";
          statusEl.className = "inline-status";
          statusEl.style.color = "var(--ok)";
        }} catch (e) {{
          statusEl.textContent = `Cannot start crawl: ${{e.message}}`;
          statusEl.className = "inline-status";
          statusEl.style.color = "var(--error)";
        }} finally {{
          btn.disabled = false;
          await loadCrawlStatus();
        }}
      }}

      function renderSources(items) {{
        const list = $("source-list");
        list.innerHTML = "";
        if (!items.length) {{
          list.innerHTML = `<div class="muted">No matching source found.</div>`;
          return;
        }}
        for (const it of items) {{
          const div = document.createElement("div");
          div.className = "source-item";
          div.innerHTML = `
            <div class="source-type">${{it.type.toUpperCase()}}</div>
            <div><a href="${{it.url}}" target="_blank" rel="noreferrer">${{it.url}}</a></div>
            <div class="muted">Open link in new tab.</div>
          `;
          list.appendChild(div);
        }}
      }}

      async function loadSources() {{
        try {{
          const resp = await fetch("/api/sources", {{ cache: "no-store" }});
          const payload = await resp.json();
          sourceData = [
            ...payload.rss.map((url) => ({{ type: "rss", url }})),
            ...payload.sitemap.map((url) => ({{ type: "sitemap", url }})),
          ];
          renderSources(sourceData);
        }} catch (e) {{
          $("source-list").innerHTML = `<div class="muted">Cannot load source list.</div>`;
        }}
      }}

      function filterSources() {{
        const q = $("source-q").value.trim().toLowerCase();
        if (!q) {{
          renderSources(sourceData);
          return;
        }}
        renderSources(
          sourceData.filter((x) => x.url.toLowerCase().includes(q) || x.type.includes(q))
        );
      }}

      $("reload").addEventListener("click", load);
      $("crawl").addEventListener("click", triggerCrawl);
      $("q").addEventListener("keydown", (e) => {{ if (e.key === "Enter") load(); }});
      $("limit").addEventListener("keydown", (e) => {{ if (e.key === "Enter") load(); }});
      $("source-q").addEventListener("input", filterSources);

      // S3 export
      async function exportToS3(fmt) {{
        const btn = $("btn-s3-csv");
        const resultEl = $("s3-export-result");
        btn.disabled = true;
        btn.textContent = "Uploading...";
        resultEl.style.display = "none";
        try {{
          const resp = await fetch(`/api/export/s3?fmt=${{fmt}}`, {{ method: "POST" }});
          if (!resp.ok) {{
            const err = await resp.json().catch(() => ({{ detail: "Unknown error" }}));
            throw new Error(err.detail || "Upload failed");
          }}
          const result = await resp.json();
          const expiresMin = Math.round(result.expires_in_seconds / 60);
          resultEl.innerHTML = `
            ✅ Upload thành công — <strong>${{result.row_count}}</strong> articles (${{result.format.toUpperCase()}})<br/>
            <a href="${{result.download_url}}" target="_blank" rel="noreferrer">📥 Download từ S3</a>
            <div class="s3-meta">
              Key: ${{result.s3_key}}<br/>
              Link hết hạn sau ${{expiresMin}} phút · Uploaded: ${{fmt_ts(result.uploaded_at)}}
            </div>
          `;
          resultEl.style.display = "block";
        }} catch (e) {{
          resultEl.innerHTML = `❌ Lỗi: ${{e.message}}`;
          resultEl.style.display = "block";
          resultEl.style.color = "var(--error)";
        }} finally {{
          btn.disabled = false;
          btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg> S3 Link`;
        }}
      }}

      function fmt_ts(ts) {{
        if (!ts) return "";
        try {{ return new Date(ts).toLocaleString(); }} catch(e) {{ return ts; }}
      }}

      $("btn-s3-csv").addEventListener("click", () => exportToS3("csv"));

      load();
      loadCrawlStatus();
      loadSources();
      setInterval(() => {{
        load();
        loadCrawlStatus();
      }}, 15000);
    </script>
  </body>
</html>"""
        )

    return app


app = create_app()

