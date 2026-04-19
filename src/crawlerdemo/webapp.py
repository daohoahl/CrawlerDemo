from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import boto3
import psycopg
from botocore.config import Config
from botocore.exceptions import ClientError
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

logger = logging.getLogger("crawlerdemo.webapp")


def _exports_bucket() -> str:
    return os.getenv("WEB_S3_EXPORTS_BUCKET", "").strip()


def _s3_client():
    region = os.getenv("AWS_DEFAULT_REGION") or os.getenv("AWS_REGION") or "ap-southeast-1"
    cfg = Config(
        connect_timeout=5,
        read_timeout=30,
        retries={"max_attempts": 3, "mode": "standard"},
    )
    return boto3.client("s3", region_name=region, config=cfg)


def _sanitize_s3_prefix(prefix: str) -> str:
    return prefix.replace("..", "")[:500]


def _safe_s3_key(key: str) -> str:
    k = key.strip()
    if not k or len(k) > 1024:
        raise HTTPException(status_code=400, detail="Invalid object key")
    if ".." in k or k.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid object key")
    return k


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _day_bounds_utc(day: str) -> tuple[datetime, datetime]:
    """Inclusive [start, end] for a YYYY-MM-DD calendar day in UTC."""
    d = datetime.strptime(day, "%Y-%m-%d").date()
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1) - timedelta(microseconds=1)
    return start, end


def _where_clause(
    q: str | None,
    source: str | None,
    *,
    fetched_from: str | None,
    fetched_to: str | None,
    published_from: str | None,
    published_to: str | None,
) -> tuple[str, dict[str, object]]:
    clauses: list[str] = []
    params: dict[str, object] = {}

    if q:
        clauses.append("(title ILIKE %(q)s OR summary ILIKE %(q)s OR canonical_url ILIKE %(q)s)")
        params["q"] = f"%{q.strip()}%"
    if source:
        clauses.append("source = %(source)s")
        params["source"] = source

    if fetched_from and _DATE_RE.match(fetched_from.strip()):
        fs, _ = _day_bounds_utc(fetched_from.strip())
        clauses.append("fetched_at >= %(fetched_from_ts)s")
        params["fetched_from_ts"] = fs
    if fetched_to and _DATE_RE.match(fetched_to.strip()):
        _, fe = _day_bounds_utc(fetched_to.strip())
        clauses.append("fetched_at <= %(fetched_to_ts)s")
        params["fetched_to_ts"] = fe
    if published_from and _DATE_RE.match(published_from.strip()):
        ps, _ = _day_bounds_utc(published_from.strip())
        clauses.append("published_at IS NOT NULL AND published_at >= %(published_from_ts)s")
        params["published_from_ts"] = ps
    if published_to and _DATE_RE.match(published_to.strip()):
        _, pe = _day_bounds_utc(published_to.strip())
        clauses.append("published_at IS NOT NULL AND published_at <= %(published_to_ts)s")
        params["published_to_ts"] = pe

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
    fetched_from: str | None = Query(default=None, description="YYYY-MM-DD (UTC day start)"),
    fetched_to: str | None = Query(default=None, description="YYYY-MM-DD (UTC day end, inclusive)"),
    published_from: str | None = Query(default=None, description="YYYY-MM-DD"),
    published_to: str | None = Query(default=None, description="YYYY-MM-DD"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: Literal["fetched_at", "published_at"] = Query(default="fetched_at"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
) -> dict[str, object]:
    offset = (page - 1) * page_size
    order_sql = f"{sort_by} {'ASC' if sort_order == 'asc' else 'DESC'}"
    where_sql, params = _where_clause(
        q,
        source,
        fetched_from=fetched_from,
        fetched_to=fetched_to,
        published_from=published_from,
        published_to=published_to,
    )
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

    items = [_row_to_article(r) for r in rows]
    return {"page": page, "page_size": page_size, "total": total, "items": items}


def _row_to_article(row: tuple[object, ...]) -> dict[str, object]:
    title_raw = row[3]
    summary_raw = row[4]
    url_raw = row[2]
    return {
        "id": row[0],
        "source": row[1],
        "canonical_url": url_raw,
        "title": title_raw,
        "summary": summary_raw,
        "display_title": _display_title(
            str(title_raw) if title_raw is not None else None,
            str(summary_raw) if summary_raw is not None else None,
            str(url_raw) if url_raw is not None else None,
        ),
        "published_at": row[5].isoformat() if isinstance(row[5], datetime) else None,
        "fetched_at": row[6].isoformat() if isinstance(row[6], datetime) else None,
    }


@app.get("/api/articles/{article_id}")
def get_article(article_id: int) -> dict[str, object]:
    """Single article for detail modal."""
    try:
        with psycopg.connect(settings.dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, source, canonical_url, title, summary, published_at, fetched_at
                    FROM articles WHERE id = %(id)s
                    """,
                    {"id": article_id},
                )
                row = cur.fetchone()
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Query failed: {exc}") from exc

    if not row:
        raise HTTPException(status_code=404, detail="Article not found")
    return _row_to_article(row)


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


@app.get("/api/s3/exports")
def s3_list_exports(
    prefix: str = Query(default=""),
    max_keys: int = Query(default=50, ge=1, le=200),
    continuation_token: str | None = Query(default=None),
) -> dict[str, object]:
    """List objects in the exports bucket (CSV/JSON). Requires ListBucket on the instance role."""
    bucket = _exports_bucket()
    if not bucket:
        raise HTTPException(
            status_code=503,
            detail="WEB_S3_EXPORTS_BUCKET is not set (configure on the web container).",
        )
    pre = _sanitize_s3_prefix(prefix)
    kwargs: dict[str, object] = {
        "Bucket": bucket,
        "Prefix": pre,
        "MaxKeys": max_keys,
    }
    if continuation_token:
        kwargs["ContinuationToken"] = continuation_token
    try:
        out = _s3_client().list_objects_v2(**kwargs)
    except ClientError as exc:
        raise HTTPException(status_code=502, detail=f"S3 list failed: {exc}") from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("S3 list_objects_v2 failed")
        raise HTTPException(status_code=502, detail=f"S3 list failed: {exc}") from exc

    items = []
    for obj in out.get("Contents") or []:
        lm = obj.get("LastModified")
        items.append(
            {
                "key": obj["Key"],
                "size": int(obj.get("Size") or 0),
                "last_modified": lm.isoformat() if isinstance(lm, datetime) else None,
            }
        )
    return {
        "bucket": bucket,
        "prefix": pre,
        "items": items,
        "is_truncated": bool(out.get("IsTruncated")),
        "next_continuation_token": out.get("NextContinuationToken"),
    }


@app.get("/api/s3/exports/presign")
def s3_presign_export(
    key: str = Query(..., min_length=1, max_length=1024),
    expires_seconds: int = Query(default=3600, ge=60, le=3600),
) -> dict[str, str]:
    """Presigned GET URL; default expiry 1 hour (max 1 hour)."""
    bucket = _exports_bucket()
    if not bucket:
        raise HTTPException(status_code=503, detail="WEB_S3_EXPORTS_BUCKET is not set.")
    safe_key = _safe_s3_key(key)
    try:
        url = _s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": safe_key},
            ExpiresIn=expires_seconds,
        )
    except ClientError as exc:
        raise HTTPException(status_code=502, detail=f"S3 presign failed: {exc}") from exc
    return {"url": url, "expires_in": str(expires_seconds), "bucket": bucket, "key": safe_key}


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
