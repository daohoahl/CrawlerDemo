from __future__ import annotations

import json

import typer
from sqlalchemy.orm import Session

from crawlerdemo.config import get_settings
from crawlerdemo.db import init_db, list_recent, make_engine
from crawlerdemo.worker import run_once, run_forever

app = typer.Typer(no_args_is_help=True)


@app.command()
def crawl_once():
    """Crawl all configured sources once."""
    run_once()


@app.command()
def worker():
    """Run scheduled crawler (interval or once via env)."""
    run_forever()


@app.command()
def recent(limit: int = 20):
    """Print recent crawled items as JSON."""
    s = get_settings()
    engine = make_engine(s.database_url)
    init_db(engine)
    with Session(engine) as session:
        rows = list_recent(session, limit=limit)
    for r in rows:
        print(
            json.dumps(
                {
                    "id": r.id,
                    "source": r.source,
                    "canonical_url": r.canonical_url,
                    "title": r.title,
                    "published_at": r.published_at.isoformat() if r.published_at else None,
                    "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    app()

