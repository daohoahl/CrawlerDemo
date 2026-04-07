from __future__ import annotations

import logging
import time
from urllib.parse import urlsplit

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from crawlerdemo.config import get_settings
from crawlerdemo.db import init_db, make_engine, upsert_articles
from crawlerdemo.http import make_client
from crawlerdemo.sources import crawl_rss, crawl_sitemap


def _name_from_url(url: str) -> str:
    p = urlsplit(url)
    return p.netloc or "source"


def run_once() -> None:
    s = get_settings()
    logging.basicConfig(level=getattr(logging, s.log_level.upper(), logging.INFO))
    log = logging.getLogger("crawlerdemo")

    engine = make_engine(s.database_url)
    init_db(engine)

    with make_client(s.user_agent, s.request_timeout_s) as client, Session(engine) as session:
        for rss_url in map(str, s.rss_urls):
            source = f"rss:{_name_from_url(rss_url)}"
            items = list(crawl_rss(client, source, rss_url, s.max_items_per_source))
            ins, skip = upsert_articles(session, items)
            log.info("rss %s inserted=%s skipped=%s", rss_url, ins, skip)

        for sm_url in map(str, s.sitemap_urls):
            source = f"sitemap:{_name_from_url(sm_url)}"
            items = list(crawl_sitemap(client, source, sm_url, s.max_items_per_source))
            ins, skip = upsert_articles(session, items)
            log.info("sitemap %s inserted=%s skipped=%s", sm_url, ins, skip)


def run_forever() -> None:
    s = get_settings()
    logging.basicConfig(level=getattr(logging, s.log_level.upper(), logging.INFO))
    log = logging.getLogger("crawlerdemo")

    if s.schedule_mode == "once":
        run_once()
        return

    scheduler = BackgroundScheduler()
    scheduler.add_job(run_once, "interval", seconds=s.interval_seconds, max_instances=1)
    scheduler.start()
    log.info("scheduler started interval_seconds=%s", s.interval_seconds)

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.shutdown(wait=True)


if __name__ == "__main__":
    run_forever()

