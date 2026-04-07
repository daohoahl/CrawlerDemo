from __future__ import annotations

from typing import Literal

from pydantic import AnyUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CRAWLER_", extra="ignore")

    # database
    database_url: str = "sqlite:///./data/crawler.db"

    # runtime
    log_level: str = "INFO"
    user_agent: str = "crawlerdemo/0.1 (+https://github.com/)"
    request_timeout_s: float = 20.0
    max_items_per_source: int = 100

    # scheduler
    schedule_mode: Literal["once", "interval"] = "interval"
    interval_seconds: int = 1800

    # sources
    rss_urls: list[AnyUrl] = [
        "https://news.ycombinator.com/rss",
        "https://feeds.bbci.co.uk/news/rss.xml",
    ]
    sitemap_urls: list[AnyUrl] = [
        "https://www.theguardian.com/sitemaps/news.xml",
    ]

    @field_validator("rss_urls", "sitemap_urls", mode="before")
    @classmethod
    def _parse_list_from_env(cls, v):
        """
        Allow overriding URLs bằng chuỗi JSON trong env, ví dụ:
        CRAWLER_RSS_URLS='["https://vietstock.vn/rss/..."]'
        """
        if isinstance(v, str):
            import json

            try:
                data = json.loads(v)
            except Exception as exc:  # pragma: no cover - config error path
                raise ValueError(f"Invalid JSON for urls: {exc}") from exc
            return data
        return v


def get_settings() -> Settings:
    return Settings()

