from __future__ import annotations

import datetime as dt
from typing import Iterable

import feedparser
import httpx
from dateutil import parser as date_parser

from crawlerdemo.db import ArticleIn
from crawlerdemo.normalize import canonicalize_url


def _parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = date_parser.parse(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except Exception:
        return None


def crawl_rss(client: httpx.Client, source_name: str, rss_url: str, limit: int) -> Iterable[ArticleIn]:
    resp = client.get(rss_url)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)

    count = 0
    for entry in parsed.entries:
        if count >= limit:
            break
        link = getattr(entry, "link", None)
        if not link:
            continue

        title = getattr(entry, "title", None)
        summary = getattr(entry, "summary", None) or getattr(entry, "description", None)
        published = _parse_datetime(getattr(entry, "published", None) or getattr(entry, "updated", None))

        yield ArticleIn(
            source=source_name,
            canonical_url=canonicalize_url(link),
            title=title,
            summary=summary,
            published_at=published,
        )
        count += 1

