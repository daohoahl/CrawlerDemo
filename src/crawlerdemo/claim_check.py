"""
claim_check.py — Claim Check Pattern helper.

When a message payload approaches the SQS 256 KB limit, we:
  1. Gzip the raw JSON (~ 5-10× smaller),
  2. Upload it to S3 under ``s3://<raw_bucket>/<raw_prefix>YYYY/MM/DD/<uuid>.json.gz``,
  3. Send only the pointer ``{"claim_check_s3_key": "..."}`` on SQS.

The Lambda ingester detects the pointer, downloads the object, decompresses
it, and processes the payload as if it had been inline.
"""
from __future__ import annotations

import gzip
import logging
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError

log = logging.getLogger("crawlerdemo.claim_check")


def upload_payload(
    payload_bytes: bytes,
    bucket: str,
    prefix: str,
    region: str,
) -> str:
    """
    Gzip-compress ``payload_bytes`` and PUT it to S3.
    Returns the S3 object key (NOT a URL).

    Raises if S3 rejects the upload — caller decides whether to fall back to
    an inline SQS message or drop the batch.
    """
    if not bucket:
        raise ValueError("s3_raw_bucket not configured; cannot use claim-check pattern")

    now = datetime.now(timezone.utc)
    date_path = now.strftime("%Y/%m/%d")
    filename = f"{now.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}.json.gz"
    key = f"{prefix.rstrip('/')}/{date_path}/{filename}"

    compressed = gzip.compress(payload_bytes, compresslevel=6)

    s3 = boto3.client("s3", region_name=region)
    try:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=compressed,
            ContentType="application/json",
            ContentEncoding="gzip",
        )
    except (BotoCoreError, ClientError) as exc:
        log.error("claim_check.upload_failed bucket=%s key=%s error=%s", bucket, key, exc)
        raise

    log.info(
        "claim_check.uploaded bucket=%s key=%s original=%d compressed=%d ratio=%.2f",
        bucket,
        key,
        len(payload_bytes),
        len(compressed),
        len(compressed) / max(len(payload_bytes), 1),
    )
    return key


def download_payload(bucket: str, key: str, region: str) -> bytes:
    """
    Inverse of :func:`upload_payload` — downloads and decompresses the object.
    Used by the Lambda ingester when it receives a claim-check message.
    """
    s3 = boto3.client("s3", region_name=region)
    obj = s3.get_object(Bucket=bucket, Key=key)
    body = obj["Body"].read()
    # Auto-decompress when the object was stored with gzip encoding
    if obj.get("ContentEncoding") == "gzip" or key.endswith(".gz"):
        body = gzip.decompress(body)
    return body
