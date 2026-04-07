from __future__ import annotations

import html

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from crawlerdemo.config import get_settings
from crawlerdemo.db import init_db, list_recent, make_engine


def create_app() -> FastAPI:
    s = get_settings()
    engine = make_engine(s.database_url)
    init_db(engine)

    app = FastAPI(title="CrawlerDemo", version="0.1.0")

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

    @app.get("/")
    def index(limit: int = 50):
        # Simple no-build dashboard. Keep it static HTML + client-side fetch.
        safe_title = html.escape("CrawlerDemo Dashboard")
        return HTMLResponse(
            f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{safe_title}</title>
    <style>
      body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin: 24px; }}
      .row {{ display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }}
      .card {{ border: 1px solid #e5e7eb; border-radius: 12px; padding: 14px; }}
      input, button {{ padding: 8px 10px; border-radius: 10px; border: 1px solid #d1d5db; }}
      button {{ cursor: pointer; background: #111827; color: white; border-color: #111827; }}
      table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
      th, td {{ border-bottom: 1px solid #eee; padding: 10px; vertical-align: top; }}
      th {{ text-align: left; font-size: 12px; color: #374151; }}
      .muted {{ color: #6b7280; font-size: 12px; }}
      a {{ color: #1d4ed8; text-decoration: none; }}
      a:hover {{ text-decoration: underline; }}
      .title {{ font-weight: 600; }}
      .nowrap {{ white-space: nowrap; }}
    </style>
  </head>
  <body>
    <div class="row">
      <div>
        <div class="title">CrawlerDemo</div>
        <div class="muted">Live view from <code>/api/articles</code></div>
      </div>
      <div class="card row">
        <label class="muted">Limit</label>
        <input id="limit" type="number" min="1" max="500" value="{int(limit)}" />
        <label class="muted">Filter (source/title/url)</label>
        <input id="q" type="text" placeholder="e.g. state.gov" size="26" />
        <button id="reload">Reload</button>
        <span id="status" class="muted"></span>
      </div>
    </div>

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

    <script>
      const $ = (id) => document.getElementById(id);
      const statusEl = $("status");

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
        statusEl.textContent = "Loading...";
        const t0 = performance.now();

        const resp = await fetch(url);
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

        const ms = Math.round(performance.now() - t0);
        statusEl.textContent = `Loaded ${{filtered.length}} items in ${{ms}}ms`;
      }}

      $("reload").addEventListener("click", load);
      $("q").addEventListener("keydown", (e) => {{ if (e.key === "Enter") load(); }});

      load();
      setInterval(load, 30000);
    </script>
  </body>
</html>"""
        )

    return app


app = create_app()

