from __future__ import annotations

import datetime as dt
from typing import Iterable

import httpx
from bs4 import BeautifulSoup
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


def crawl_sitemap(
    client: httpx.Client, source_name: str, sitemap_url: str, limit: int
) -> Iterable[ArticleIn]:
    resp = client.get(sitemap_url)
    resp.raise_for_status()

    # Handle sitemapindex and urlset in a simple way.
    soup = BeautifulSoup(resp.content, "xml")
    sitemap_tags = soup.find_all("sitemap")
    if sitemap_tags:
        # sitemap index: crawl first few child sitemaps until we hit limit
        remaining = limit
        for sm in sitemap_tags:
            loc = sm.find_text("loc")
            if not loc:
                continue
            if remaining <= 0:
                break
            for it in crawl_sitemap(client, source_name, loc, remaining):
                yield it
                remaining -= 1
                if remaining <= 0:
                    break
        return

    url_tags = soup.find_all("url")
    count = 0
    for u in url_tags:
        if count >= limit:
            break
        loc = u.find_text("loc")
        if not loc:
            continue
        lastmod = _parse_datetime(u.find_text("lastmod"))
        yield ArticleIn(
            source=source_name,
            canonical_url=canonicalize_url(loc),
            title=None,
            summary=None,
            published_at=lastmod,
        )
        count += 1

