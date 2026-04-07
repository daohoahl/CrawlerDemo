from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy.orm import Session

from crawlerdemo.config import get_settings
from crawlerdemo.db import Article, init_db, list_recent, make_engine


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
    def index():
        # Tiny no-build UI.
        return {
            "service": "crawlerdemo-web",
            "endpoints": ["/health", "/api/articles?limit=50"],
            "note": "Use /api/articles for JSON output.",
        }

    return app


app = create_app()

