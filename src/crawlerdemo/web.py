from __future__ import annotations

import html
import threading
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from crawlerdemo.config import get_settings
from crawlerdemo.db import init_db, list_recent, make_engine
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
    <style>
      :root {{
        --bg: #0b1020;
        --card: #121a30;
        --muted: #9fb0d1;
        --text: #eef3ff;
        --accent: #5ba7ff;
        --accent-2: #64f0cc;
        --danger: #ff8ea0;
        --border: #243252;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
        background: radial-gradient(circle at top right, #1a2d5d 0%, var(--bg) 42%);
        color: var(--text);
      }}
      .container {{ max-width: 1080px; margin: 0 auto; padding: 28px 16px 42px; }}
      .header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 10px;
        margin-bottom: 14px;
      }}
      .title {{ font-size: 26px; font-weight: 700; margin: 0; }}
      .subtitle {{ color: var(--muted); margin-top: 4px; font-size: 14px; }}
      .grid {{ display: grid; grid-template-columns: repeat(12, 1fr); gap: 12px; }}
      .card {{
        background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0));
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 14px;
        box-shadow: 0 6px 24px rgba(0,0,0,0.25);
      }}
      .controls {{ grid-column: span 12; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
      .stats {{ grid-column: span 12; display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); }}
      .table-wrap {{ grid-column: span 12; overflow: auto; }}
      .sources-wrap {{ grid-column: span 12; }}
      .guide-wrap {{ grid-column: span 12; }}
      .stat-label {{ color: var(--muted); font-size: 12px; }}
      .stat-value {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
      input, button {{
        border-radius: 10px;
        border: 1px solid var(--border);
        background: #0e162d;
        color: var(--text);
        padding: 10px 12px;
        font-size: 14px;
      }}
      input:focus {{ outline: 2px solid #294c8d; }}
      button {{ cursor: pointer; transition: .2s ease; }}
      button.primary {{ border-color: #3876d4; background: #2d64b6; }}
      button.primary:hover {{ background: #3876d4; }}
      button.ghost:hover {{ border-color: #3b5a95; background: #142247; }}
      .status {{ color: var(--muted); font-size: 13px; }}
      .error {{ color: var(--danger); }}
      .ok {{ color: var(--accent-2); }}
      table {{ width: 100%; border-collapse: collapse; min-width: 780px; }}
      th, td {{ padding: 10px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
      th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
      .muted {{ color: var(--muted); font-size: 12px; }}
      a {{ color: var(--accent); text-decoration: none; }}
      a:hover {{ text-decoration: underline; }}
      .nowrap {{ white-space: nowrap; }}
      .split {{
        display: grid;
        gap: 12px;
        grid-template-columns: 1fr 1fr;
      }}
      .source-item {{
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 10px;
        margin-bottom: 8px;
        background: #0f1934;
      }}
      .source-type {{
        display: inline-block;
        font-size: 11px;
        color: var(--muted);
        border: 1px solid var(--border);
        padding: 2px 6px;
        border-radius: 999px;
        margin-bottom: 6px;
      }}
      .guide-list {{ margin: 0; padding-left: 18px; color: var(--muted); line-height: 1.6; }}
      .mini-title {{ margin: 0 0 8px; font-size: 16px; }}
      @media (max-width: 700px) {{
        .title {{ font-size: 22px; }}
        .split {{ grid-template-columns: 1fr; }}
      }}
    </style>
  </head>
  <body>
    <div class="container">
      <div class="header">
        <div>
          <h1 class="title">Crawler Demo</h1>
          <div class="subtitle">Giao diện theo doi du lieu crawl va kich hoat crawl ngay lap tuc</div>
        </div>
        <div class="status" id="crawl-status-line">Trang thai crawl: ...</div>
      </div>

      <div class="grid">
        <div class="card controls">
          <label class="muted">Limit</label>
          <input id="limit" type="number" min="1" max="500" value="{int(limit)}" />
          <label class="muted">Tim kiem</label>
          <input id="q" type="text" placeholder="source / title / url..." size="26" />
          <button id="reload" class="ghost">Reload</button>
          <button id="crawl" class="primary">Crawl ngay</button>
          <span id="status" class="status"></span>
        </div>

        <div class="stats">
          <div class="card">
            <div class="stat-label">Tong ket qua hien thi</div>
            <div class="stat-value" id="stat-visible">0</div>
          </div>
          <div class="card">
            <div class="stat-label">Tong ket qua da tai</div>
            <div class="stat-value" id="stat-loaded">0</div>
          </div>
          <div class="card">
            <div class="stat-label">Nguon du lieu</div>
            <div class="stat-value" id="stat-sources">0</div>
          </div>
          <div class="card">
            <div class="stat-label">Lan cap nhat gan nhat</div>
            <div class="stat-value" id="stat-last">--</div>
          </div>
        </div>

        <div class="card table-wrap">
          <table>
            <thead>
              <tr>
                <th class="nowrap">Fetched</th>
                <th>Title / URL</th>
                <th class="nowrap">Source</th>
              </tr>
            </thead>
            <tbody id="rows"></tbody>
          </table>
        </div>

        <div class="split">
          <div class="card guide-wrap">
            <h3 class="mini-title">Huong dan dung nhanh</h3>
            <ol class="guide-list">
              <li>Bam <b>Crawl ngay</b> de lay du lieu moi tu cac nguon da cau hinh.</li>
              <li>Nhap tu khoa vao o <b>Tim kiem</b> de loc theo title, source hoac URL.</li>
              <li>Dieu chinh <b>Limit</b> de xem nhieu/it ket qua hon, sau do bam <b>Reload</b>.</li>
              <li>Kiem tra dong <b>Trang thai crawl</b> de biet job dang chay hay da xong.</li>
            </ol>
          </div>

          <div class="card sources-wrap">
            <h3 class="mini-title">Nguon tin ho tro</h3>
            <div class="muted" style="margin-bottom:8px;">Tim nhanh theo domain/URL de huong dan user chon nguon can theo doi.</div>
            <input id="source-q" type="text" placeholder="Tim nguon tin... vd: state.gov, guardian" />
            <div id="source-list" style="margin-top:10px;"></div>
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
        statusEl.textContent = "Dang tai du lieu...";
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
              <div class="title"><a href="${{x.canonical_url}}" target="_blank" rel="noreferrer">${{title}}</a></div>
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
        statusEl.textContent = `Da tai ${{filtered.length}}/${{data.length}} ket qua trong ${{ms}}ms`;
      }}

      async function loadCrawlStatus() {{
        try {{
          const resp = await fetch("/api/crawl-status", {{ cache: "no-store" }});
          const s = await resp.json();
          const statusText = s.is_running
            ? `Dang crawl... (bat dau ${{
                s.last_started_at ? fmt(s.last_started_at) : "unknown"
              }})`
            : `Ranh roi. Lan xong gan nhat: ${{s.last_finished_at ? fmt(s.last_finished_at) : "chua co"}}`;
          crawlStatusLine.textContent = `Trang thai crawl: ${{statusText}}`;
          crawlStatusLine.className = `status ${{s.last_error ? "error" : (s.is_running ? "muted" : "ok")}}`;
          if (s.last_error) {{
            statusEl.textContent = `Loi crawl gan nhat: ${{s.last_error}}`;
            statusEl.className = "status error";
          }} else {{
            statusEl.className = "status";
          }}
        }} catch (e) {{
          crawlStatusLine.textContent = "Khong lay duoc trang thai crawl";
          crawlStatusLine.className = "status error";
        }}
      }}

      async function triggerCrawl() {{
        const btn = $("crawl");
        btn.disabled = true;
        statusEl.textContent = "Dang gui yeu cau crawl...";
        try {{
          const resp = await fetch("/api/crawl", {{ method: "POST" }});
          if (!resp.ok) {{
            const err = await resp.json().catch(() => ({{ detail: "Unknown error" }}));
            throw new Error(err.detail || "Cannot start crawl");
          }}
          statusEl.textContent = "Da bat dau crawl. Du lieu se tu dong cap nhat.";
          statusEl.className = "status ok";
        }} catch (e) {{
          statusEl.textContent = `Khong the bat dau crawl: ${{e.message}}`;
          statusEl.className = "status error";
        }} finally {{
          btn.disabled = false;
          await loadCrawlStatus();
        }}
      }}

      function renderSources(items) {{
        const list = $("source-list");
        list.innerHTML = "";
        if (!items.length) {{
          list.innerHTML = `<div class="muted">Khong tim thay nguon phu hop.</div>`;
          return;
        }}
        for (const it of items) {{
          const div = document.createElement("div");
          div.className = "source-item";
          div.innerHTML = `
            <div class="source-type">${{it.type.toUpperCase()}}</div>
            <div><a href="${{it.url}}" target="_blank" rel="noreferrer">${{it.url}}</a></div>
            <div class="muted">Click vao link de mo nguon goc.</div>
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
          $("source-list").innerHTML = `<div class="muted error">Khong tai duoc danh sach nguon.</div>`;
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

