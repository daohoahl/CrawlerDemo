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

    # S3 export
    s3_bucket: str = ""
    s3_region: str = "ap-southeast-1"
    s3_export_prefix: str = "exports/"
    s3_presigned_url_expires: int = 3600  # 1 hour

    # SQS
    sqs_data_queue_url: str = ""
    # sources
    rss_urls: list[AnyUrl] = [
        # US (official) - U.S. Department of State RSS channels
        "https://www.state.gov/rss/channels/prsreleases.xml",
        "https://www.state.gov/rss/channels/remarks.xml",
        "https://www.state.gov/rss/channels/briefings.xml",

        # Vietnam (official/state) - Government Gazette RSS
        "https://congbao.chinhphu.vn/cac-van-ban-moi-ban-hanh.rss",
    ]
    sitemap_urls: list[AnyUrl] = [
        "https://www.theguardian.com/sitemaps/news.xml",
        # Vietnam Government News (English) - sitemap endpoint (best-effort)
        "https://en.baochinhphu.vn/sitemap.xml",
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

