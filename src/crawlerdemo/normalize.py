from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonicalize_url(url: str) -> str:
    """
    Lightweight canonicalization: remove fragment, sort query params, trim trailing slash.
    Avoids aggressive rewriting to reduce false merges.
    """
    parts = urlsplit(url.strip())
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    path = parts.path.rstrip("/") or "/"
    cleaned = urlunsplit((parts.scheme, parts.netloc, path, query, ""))
    return cleaned

