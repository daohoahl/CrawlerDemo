"""
sources.sitemap — Parse a ``sitemap.xml`` (or a sitemap index) into
ArticleIn records.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from crawlerdemo.models import ArticleIn
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
    client: httpx.Client,
    source_name: str,
    sitemap_url: str,
    limit: int,
) -> Iterable[ArticleIn]:
    resp = client.get(sitemap_url)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.content, "xml")

    # Handle <sitemapindex> by recursing into the first few children until `limit` is reached
    sitemap_tags = soup.find_all("sitemap")
    if sitemap_tags:
        remaining = limit
        for sm in sitemap_tags:
            if remaining <= 0:
                break
            loc_tag = sm.find("loc")
            loc = loc_tag.text if loc_tag else None
            if not loc:
                continue
            for it in crawl_sitemap(client, source_name, loc, remaining):
                yield it
                remaining -= 1
                if remaining <= 0:
                    break
        return

    # Standard <urlset>
    count = 0
    for u in soup.find_all("url"):
        if count >= limit:
            break
        loc_tag = u.find("loc")
        loc = loc_tag.text if loc_tag else None
        if not loc:
            continue
        lastmod_tag = u.find("lastmod")
        lastmod = _parse_datetime(lastmod_tag.text if lastmod_tag else None)
        yield ArticleIn(
            source=source_name,
            canonical_url=canonicalize_url(loc),
            title=None,
            summary=None,
            published_at=lastmod,
        )
        count += 1
