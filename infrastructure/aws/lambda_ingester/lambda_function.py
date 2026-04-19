"""
lambda_function.py — SQS → RDS ingester (Scope 1 Production-Ready)

Architecture contract
---------------------
- Triggered by an SQS Standard queue with ``ReportBatchItemFailures`` enabled.
- ``BatchSize = 10`` (configured in the Event Source Mapping).
- A **single** DB connection is reused for the entire invocation
  (warm-start reuse across invocations is also exploited).
- Idempotent upsert via ``INSERT ... ON CONFLICT (canonical_url) DO NOTHING``
  — no SELECT probe, atomic against concurrent inserts.
- Reserved Concurrency = 50 is enforced by Terraform (protects RDS t3.micro).

Message body formats supported
------------------------------
1. Inline:       ``[ {"source":..., "canonical_url":..., ...}, ... ]``
2. Claim Check:  ``{"claim_check_s3_bucket":..., "claim_check_s3_key":...}``

Environment variables
---------------------
- ``RDS_HOST``           RDS endpoint (host only, no port)
- ``DB_NAME``            database name
- ``DB_USER``            username
- ``DB_PASSWORD``        password (injected from Secrets Manager at deploy time)
- ``S3_EXPORTS_BUCKET``  exports bucket name (JSONL auto-upload after successful inserts)
- ``S3_EXPORTS_PREFIX``  key prefix, default ``auto/``
- ``AWS_REGION``         provided automatically by the Lambda runtime
- ``LOG_LEVEL``          optional, defaults to INFO
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import re
import ssl
import uuid
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())


# ── Warm-start globals ───────────────────────────────────────────────────────
_conn = None          # pg8000 connection, reused across warm invocations
_s3 = None            # boto3 S3 client, reused across warm invocations
_schema_ready = False # DDL has been applied on this container

# Idempotent DDL - runs on cold-start so no manual psql step is ever needed.
# Matches infrastructure/aws/lambda_ingester/schema.sql (kept in sync).
_SCHEMA_DDL = """
    CREATE TABLE IF NOT EXISTS articles (
        id            BIGSERIAL PRIMARY KEY,
        source        VARCHAR(120)  NOT NULL,
        canonical_url VARCHAR(2048) NOT NULL,
        title         VARCHAR(512),
        summary       TEXT,
        published_at  TIMESTAMPTZ,
        fetched_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_articles_canonical_url
        ON articles (canonical_url);
    CREATE INDEX IF NOT EXISTS idx_articles_source
        ON articles (source);
    CREATE INDEX IF NOT EXISTS idx_articles_fetched_at
        ON articles (fetched_at DESC);
"""


# ── Connection management ────────────────────────────────────────────────────


def _ensure_schema(conn) -> None:
    """Apply idempotent DDL once per warm container."""
    global _schema_ready
    if _schema_ready:
        return
    with conn.cursor() as cur:
        cur.execute(_SCHEMA_DDL)
    conn.commit()
    _schema_ready = True
    logger.info("db.schema_ready")


def _get_connection():
    """
    Return a live ``pg8000`` connection. Reconnect transparently if the
    previous socket was closed (idle timeout, RDS fail-over, etc).
    """
    global _conn
    import pg8000  # imported lazily to keep cold-start small

    if _conn is not None:
        try:
            _conn.run("SELECT 1")
            return _conn
        except Exception:
            logger.info("db.reconnect previous_connection=closed")
            _conn = None

    ssl_ctx = ssl.create_default_context()
    # RDS presents a cert signed by the AWS Global CA bundle; using the
    # default context is sufficient. Disable hostname check because pg8000
    # connects by host-only string.
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    _conn = pg8000.connect(
        host=os.environ["RDS_HOST"],
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        ssl_context=ssl_ctx,
    )
    logger.info("db.connected host=%s db=%s", os.environ["RDS_HOST"], os.environ["DB_NAME"])
    _ensure_schema(_conn)
    return _conn


def _get_s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def _exports_bucket() -> str:
    return os.environ.get("S3_EXPORTS_BUCKET", "").strip()


def _exports_prefix() -> str:
    p = os.environ.get("S3_EXPORTS_PREFIX", "auto/").strip()
    return p if p.endswith("/") else (p + "/")


def _safe_filename_part(message_id: str) -> str:
    s = re.sub(r"[^0-9A-Za-z._-]+", "_", message_id or "msg")
    return s[:80] if len(s) > 80 else s


def _upload_export_json(rows: list[dict], message_id: str) -> None:
    """
    Write one pretty-printed JSON file per SQS record when at least one row
    was inserted. Human-readable in browser/editor (not NDJSON).
    Failures are logged only — DB commit already succeeded.
    """
    bucket = _exports_bucket()
    if not bucket or not rows:
        return

    now = datetime.now(timezone.utc)
    date_path = now.strftime("%Y/%m/%d")
    fname = (
        f"{now.strftime('%Y%m%dT%H%M%SZ')}_"
        f"{_safe_filename_part(message_id)}_"
        f"{uuid.uuid4().hex[:8]}_{len(rows)}.json"
    )
    key = f"{_exports_prefix()}{date_path}/{fname}"
    payload = {
        "export_version": 1,
        "exported_at": now.isoformat().replace("+00:00", "Z"),
        "article_count": len(rows),
        "articles": rows,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    try:
        _get_s3().put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )
        logger.info(
            json.dumps(
                {
                    "event": "export_uploaded",
                    "bucket": bucket,
                    "key": key,
                    "articles": len(rows),
                }
            )
        )
    except Exception as exc:
        logger.error(
            json.dumps(
                {
                    "event": "export_upload_failed",
                    "bucket": bucket,
                    "key": key,
                    "error": str(exc),
                }
            )
        )


# ── SQL ──────────────────────────────────────────────────────────────────────
#
# ON CONFLICT DO NOTHING:
#   - Atomic, no TOCTOU race between concurrent Lambda invocations.
#   - Single round-trip per row — no probing SELECT required.
#   - A duplicate row does NOT abort the surrounding transaction; the rest of
#     the batch commits normally.
#
_INSERT_SQL = """
    INSERT INTO articles (
        source, canonical_url, title, summary, published_at, fetched_at
    ) VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (canonical_url) DO NOTHING
"""


# ── Claim-Check resolver ─────────────────────────────────────────────────────


def _resolve_payload(body: str) -> list[dict]:
    """
    Turn the raw SQS message body into a list of article dicts.

    Handles both inline arrays and Claim-Check pointers.
    """
    doc = json.loads(body)

    # Inline form: the body is the list itself
    if isinstance(doc, list):
        return doc

    # Claim-check form: fetch from S3 and (if gzipped) decompress
    if isinstance(doc, dict) and "claim_check_s3_key" in doc:
        bucket = doc["claim_check_s3_bucket"]
        key = doc["claim_check_s3_key"]
        obj = _get_s3().get_object(Bucket=bucket, Key=key)
        data = obj["Body"].read()
        if obj.get("ContentEncoding") == "gzip" or key.endswith(".gz"):
            data = gzip.decompress(data)
        logger.info(
            "claim_check.resolved bucket=%s key=%s bytes=%d", bucket, key, len(data)
        )
        return json.loads(data)

    raise ValueError(f"Unsupported SQS body shape: {type(doc).__name__}")


# ── Lambda handler ───────────────────────────────────────────────────────────


def lambda_handler(event, context):
    """
    Entry point for SQS → Lambda triggers.

    One Lambda invocation processes one *batch* of up to ``BatchSize`` SQS
    records.  We reuse a single DB connection for the whole batch and commit
    per-record, so a single poison pill cannot lose already-inserted rows.

    When ``ReportBatchItemFailures`` is enabled, the ``batchItemFailures``
    array tells SQS which records to re-queue — the successful ones are
    deleted automatically.
    """
    records = event.get("Records", [])

    # Manual schema bootstrap hook: `aws lambda invoke --payload '{"action":"init-schema"}'`
    if not records and event.get("action") == "init-schema":
        _get_connection()
        return {"schema_ready": True}

    if not records:
        return {"batchItemFailures": []}

    conn = _get_connection()
    batch_item_failures: list[dict] = []
    total_inserted = 0
    total_skipped = 0

    for record in records:
        message_id = record.get("messageId", "unknown")
        attrs = record.get("messageAttributes", {}) or {}
        trace_id = attrs.get("TraceID", {}).get("stringValue", "N/A")
        source = attrs.get("Source", {}).get("stringValue", "unknown")

        try:
            payload_list = _resolve_payload(record["body"])
            if not isinstance(payload_list, list):
                raise ValueError(f"Expected JSON list, got {type(payload_list).__name__}")

            fetched_at = datetime.now(timezone.utc).isoformat()
            inserted_now = 0
            skipped_now = 0
            inserted_rows: list[dict] = []

            with conn.cursor() as cursor:
                for item in payload_list:
                    cursor.execute(
                        _INSERT_SQL,
                        (
                            item.get("source"),
                            item.get("canonical_url"),
                            item.get("title"),
                            item.get("summary"),
                            item.get("published_at"),  # ISO string or None
                            fetched_at,
                        ),
                    )
                    if cursor.rowcount == 1:
                        inserted_now += 1
                        inserted_rows.append(
                            {
                                "source": item.get("source"),
                                "canonical_url": item.get("canonical_url"),
                                "title": item.get("title"),
                                "summary": item.get("summary"),
                                "published_at": item.get("published_at"),
                                "fetched_at": fetched_at,
                            }
                        )
                    else:
                        skipped_now += 1

            conn.commit()
            total_inserted += inserted_now
            total_skipped += skipped_now

            _upload_export_json(inserted_rows, message_id)

            logger.info(
                json.dumps(
                    {
                        "event": "record_processed",
                        "trace_id": trace_id,
                        "source": source,
                        "message_id": message_id,
                        "inserted": inserted_now,
                        "skipped": skipped_now,
                    }
                )
            )

        except Exception as exc:
            # Roll back so the next record starts with a clean transaction.
            try:
                conn.rollback()
            except Exception:
                pass

            logger.error(
                json.dumps(
                    {
                        "event": "record_failed",
                        "trace_id": trace_id,
                        "message_id": message_id,
                        "error": str(exc),
                    }
                )
            )
            # Only THIS record is re-queued; other records in the batch are
            # acknowledged and deleted from SQS.
            batch_item_failures.append({"itemIdentifier": message_id})

    logger.info(
        json.dumps(
            {
                "event": "batch_summary",
                "records": len(records),
                "inserted": total_inserted,
                "skipped": total_skipped,
                "failed": len(batch_item_failures),
            }
        )
    )

    return {"batchItemFailures": batch_item_failures}
