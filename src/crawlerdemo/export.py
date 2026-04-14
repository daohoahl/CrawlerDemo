"""
export.py — Xuất dữ liệu articles ra CSV/JSON và upload lên S3.

Các hàm chính:
- export_csv(session)        → bytes (UTF-8 CSV)
- export_json(session)       → bytes (UTF-8 JSON)
- upload_to_s3(...)          → s3_key (str)
- generate_presigned_url(...)→ url (str)
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.orm import Session

from crawlerdemo.db import list_recent

log = logging.getLogger("crawlerdemo.export")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ARTICLE_FIELDS = ["id", "source", "canonical_url", "title", "summary", "published_at", "fetched_at"]


def _articles_as_dicts(session: Session, limit: int = 10_000) -> list[dict]:
    rows = list_recent(session, limit=limit)
    result = []
    for r in rows:
        result.append(
            {
                "id": r.id,
                "source": r.source,
                "canonical_url": r.canonical_url,
                "title": r.title or "",
                "summary": r.summary or "",
                "published_at": r.published_at.isoformat() if r.published_at else "",
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else "",
            }
        )
    return result


# ---------------------------------------------------------------------------
# Export — trả về bytes để dùng trực tiếp trong HTTP response hoặc upload S3
# ---------------------------------------------------------------------------


def export_csv(session: Session, limit: int = 10_000) -> tuple[bytes, int]:
    """Trả về (csv_bytes, row_count)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_ARTICLE_FIELDS)
    writer.writeheader()
    rows = _articles_as_dicts(session, limit=limit)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8"), len(rows)


def export_json(session: Session, limit: int = 10_000) -> tuple[bytes, int]:
    """Trả về (json_bytes, row_count)."""
    rows = _articles_as_dicts(session, limit=limit)
    data = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
    return data, len(rows)


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------


def _s3_client(region: str):
    return boto3.client("s3", region_name=region)


def _make_s3_key(prefix: str, fmt: str) -> str:
    """Tạo key theo dạng: exports/2026/04/14/articles_20260414T065400Z.csv"""
    now = datetime.now(timezone.utc)
    date_path = now.strftime("%Y/%m/%d")
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix.rstrip('/')}/{date_path}/articles_{timestamp}.{fmt}"


def upload_to_s3(
    data: bytes,
    bucket: str,
    prefix: str,
    fmt: str,  # "csv" | "json"
    region: str,
    content_type: str,
) -> str:
    """Upload bytes lên S3, trả về s3_key."""
    client = _s3_client(region)
    key = _make_s3_key(prefix, fmt)
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ContentDisposition=f'attachment; filename="articles.{fmt}"',
        )
        log.info("Uploaded s3://%s/%s (%d bytes)", bucket, key, len(data))
        return key
    except (BotoCoreError, ClientError) as exc:
        log.error("S3 upload failed: %s", exc)
        raise


def generate_presigned_url(bucket: str, key: str, region: str, expires: int = 3600) -> str:
    """Tạo presigned URL để download file từ S3 (hết hạn sau `expires` giây)."""
    client = _s3_client(region)
    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires,
        )
        return url
    except (BotoCoreError, ClientError) as exc:
        log.error("Presigned URL generation failed: %s", exc)
        raise
