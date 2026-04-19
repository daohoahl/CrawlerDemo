"""
config.py — Centralised runtime configuration.

All values are read from environment variables (prefixed ``CRAWLER_``) or from
an optional ``.env`` file. Keeps the worker 12-factor compliant so the same
Docker image runs unchanged on a developer laptop, an EC2 ASG instance, or a
Lambda function.
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import AnyUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CRAWLER_",
        extra="ignore",
    )

    # ── Runtime ─────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    user_agent: str = "crawlerdemo/1.0 (+https://github.com/)"
    request_timeout_s: float = 20.0
    max_items_per_source: int = 100

    # ── APScheduler ─────────────────────────────────────────────────────────
    # schedule_mode=once  → run a single cycle and exit (useful for EventBridge/cron)
    # schedule_mode=interval → keep the process alive and run every N seconds
    # schedule_mode=idle → process stays up; no scheduled crawl (use dashboard POST /api/crawl)
    schedule_mode: Literal["once", "interval", "idle"] = "interval"
    interval_seconds: int = 1800  # 30 minutes

    # ── AWS (injected by Terraform / instance metadata) ────────────────────
    aws_region: str = "ap-southeast-1"

    # SQS Standard queue URL (ends with /queue-name, NOT .fifo)
    sqs_queue_url: str = ""

    # S3 bucket that holds the raw HTML payloads offloaded via the
    # Claim Check pattern (also used by the Lambda ingester to read them back).
    s3_raw_bucket: str = ""
    s3_raw_prefix: str = "raw/"

    # Threshold above which an SQS message body is considered "too large" and
    # is written to S3 instead. AWS SQS hard limit = 256 KB; we stay well
    # below that (default 200 KB) to keep safety margin for metadata overhead.
    claim_check_threshold_bytes: int = 200 * 1024

    # ── Sources (override via CRAWLER_RSS_URLS='[...]' / CRAWLER_SITEMAP_URLS='[...]') ─
    rss_urls: list[AnyUrl] = [
        "https://www.state.gov/rss/channels/prsreleases.xml",
        "https://www.state.gov/rss/channels/remarks.xml",
        "https://www.state.gov/rss/channels/briefings.xml",
        "https://congbao.chinhphu.vn/cac-van-ban-moi-ban-hanh.rss",
    ]
    sitemap_urls: list[AnyUrl] = [
        "https://www.theguardian.com/sitemaps/news.xml",
        "https://en.baochinhphu.vn/sitemap.xml",
    ]

    @field_validator("rss_urls", "sitemap_urls", mode="before")
    @classmethod
    def _parse_list_from_env(cls, v):
        """Accept either a Python list or a JSON-encoded string from env vars."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception as exc:
                raise ValueError(f"Invalid JSON for URL list: {exc}") from exc
        return v


def get_settings() -> Settings:
    return Settings()
