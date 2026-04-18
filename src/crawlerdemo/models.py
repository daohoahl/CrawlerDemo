"""
models.py — Plain dataclasses used across the worker layer.

The worker intentionally has **no SQLAlchemy / ORM dependency**: it only
produces messages for SQS. Persisting them into RDS is the Lambda ingester's
sole responsibility.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class ArticleIn:
    """One crawled article, ready to be serialised onto SQS."""

    source: str
    canonical_url: str
    title: Optional[str] = None
    summary: Optional[str] = None
    published_at: Optional[dt.datetime] = None

    def to_json_dict(self) -> dict:
        """JSON-safe dict used as SQS message payload."""
        d = asdict(self)
        if self.published_at is not None:
            d["published_at"] = self.published_at.isoformat()
        # Keep summary under 500 chars so batches of ~100 items fit in 256 KB SQS limit
        if self.summary:
            d["summary"] = self.summary[:500]
        return d
