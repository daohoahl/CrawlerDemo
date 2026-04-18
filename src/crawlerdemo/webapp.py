from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


@dataclass
class WebSettings:
    db_host: str = os.getenv("WEB_DB_HOST", "")
    db_port: int = int(os.getenv("WEB_DB_PORT", "5432"))
    db_name: str = os.getenv("WEB_DB_NAME", "crawlerdb")
    db_user: str = os.getenv("WEB_DB_USER", "crawler")
    db_password: str = os.getenv("WEB_DB_PASSWORD", "")

    @property
    def dsn(self) -> str:
        if not self.db_host or not self.db_password:
            raise RuntimeError(
                "Missing WEB_DB_HOST or WEB_DB_PASSWORD. "
                "Set DB env vars before starting web app."
            )
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={self.db_user} password={self.db_password} sslmode=require"
        )


BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "web_templates"
STATIC_DIR = BASE_DIR / "web_static"

app = FastAPI(title="Crawler Dashboard", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
settings = WebSettings()


def _where_clause(q: str | None, source: str | None) -> tuple[str, dict[str, object]]:
    clauses: list[str] = []
    params: dict[str, object] = {}

    if q:
        clauses.append("(title ILIKE %(q)s OR summary ILIKE %(q)s OR canonical_url ILIKE %(q)s)")
        params["q"] = f"%{q.strip()}%"
    if source:
        clauses.append("source = %(source)s")
        params["source"] = source

    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(clauses), params


def _display_title(
    title: str | None,
    summary: str | None,
    canonical_url: str | None,
) -> str:
    """
    Crawl data often has null title (e.g. sitemap). Build a readable headline for the UI.
    """
    t = (title or "").strip()
    if t:
        return t
    s = (summary or "").strip()
    if s:
        one_line = " ".join(s.split())
        return one_line[:160] + ("…" if len(one_line) > 160 else "")
    url = (canonical_url or "").strip()
    if url:
        p = urlparse(url)
        host = p.netloc or ""
        path = (p.path or "").strip("/")
        bit = f"/{path[:80]}" if path else ""
        if host:
            return f"{host}{bit}" if bit else host
        return url[:120] + ("…" if len(url) > 120 else "")
    return "Untitled"


@app.get("/health")
def health() -> dict[str, str]:
    """
    Liveness for ALB/ASG: must stay HTTP 200 without touching RDS.
    RDS-dependent checks live under /health/ready.
    """
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready() -> dict[str, str]:
    """Returns 200 only when the app can reach PostgreSQL."""
    try:
        with psycopg.connect(settings.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                _ = cur.fetchone()
        return {"status": "ok"}
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=503, detail=f"DB check failed: {exc}") from exc


@app.get("/api/articles")
def list_articles(
    q: str | None = Query(default=None),
    source: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: Literal["fetched_at", "published_at"] = Query(default="fetched_at"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
) -> dict[str, object]:
    offset = (page - 1) * page_size
    order_sql = f"{sort_by} {'ASC' if sort_order == 'asc' else 'DESC'}"
    where_sql, params = _where_clause(q, source)
    params.update({"limit": page_size, "offset": offset})

    query_total = f"SELECT COUNT(*) FROM articles {where_sql}"
    query_rows = f"""
        SELECT id, source, canonical_url, title, summary, published_at, fetched_at
        FROM articles
        {where_sql}
        ORDER BY {order_sql} NULLS LAST
        LIMIT %(limit)s OFFSET %(offset)s
    """

    try:
        with psycopg.connect(settings.dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(query_total, params)
                total = int(cur.fetchone()[0])
                cur.execute(query_rows, params)
                rows = cur.fetchall()
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Query failed: {exc}") from exc

    items = []
    for r in rows:
        title_raw = r[3]
        summary_raw = r[4]
        url_raw = r[2]
        items.append(
            {
                "id": r[0],
                "source": r[1],
                "canonical_url": url_raw,
                "title": title_raw,
                "summary": summary_raw,
                "display_title": _display_title(title_raw, summary_raw, url_raw),
                "published_at": r[5].isoformat() if isinstance(r[5], datetime) else None,
                "fetched_at": r[6].isoformat() if isinstance(r[6], datetime) else None,
            }
        )
    return {"page": page, "page_size": page_size, "total": total, "items": items}


@app.get("/api/stats")
def api_stats() -> dict[str, object]:
    """Dashboard KPIs: totals, freshness, per-source counts."""
    try:
        with psycopg.connect(settings.dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM articles")
                total = int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT source, COUNT(*)::bigint AS c
                    FROM articles
                    GROUP BY source
                    ORDER BY c DESC
                    LIMIT 25
                    """
                )
                sources = [{"source": row[0], "count": int(row[1])} for row in cur.fetchall()]
                cur.execute("SELECT MAX(fetched_at) FROM articles")
                row = cur.fetchone()
                last_fetched = row[0].isoformat() if row and isinstance(row[0], datetime) else None
                cur.execute(
                    """
                    SELECT COUNT(*) FROM articles
                    WHERE fetched_at >= NOW() - INTERVAL '24 hours'
                    """
                )
                fetched_24h = int(cur.fetchone()[0])
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Stats query failed: {exc}") from exc

    return {
        "total": total,
        "fetched_last_24h": fetched_24h,
        "last_fetched_at": last_fetched,
        "sources": sources,
    }


@app.get("/api/sources")
def api_sources() -> dict[str, object]:
    """Distinct source labels for filter dropdown."""
    try:
        with psycopg.connect(settings.dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT source FROM articles ORDER BY source ASC LIMIT 500
                    """
                )
                names = [r[0] for r in cur.fetchall() if r[0]]
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Sources query failed: {exc}") from exc

    return {"items": names}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"settings": asdict(settings)},
    )
