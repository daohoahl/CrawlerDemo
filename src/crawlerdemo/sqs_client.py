"""
sqs_client.py — Thin wrapper around boto3 SQS ``send_message`` with built-in
Claim-Check offloading.

Usage
-----
    sender = SqsSender(queue_url, region)
    sender.send_batch(source="rss:state.gov", items=[ArticleIn(...), ...])

Behaviour
---------
- If the JSON-encoded payload is ≤ ``threshold_bytes``, it is sent inline.
- Otherwise it is gzipped, uploaded to S3 (Claim Check), and a small pointer
  message ``{"claim_check_s3_key": "..."}`` is sent on SQS instead.
- The caller never has to worry about the 256 KB SQS limit.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Iterable

import boto3

from crawlerdemo.claim_check import upload_payload
from crawlerdemo.models import ArticleIn

log = logging.getLogger("crawlerdemo.sqs")


class SqsSender:
    def __init__(
        self,
        queue_url: str,
        region: str,
        raw_bucket: str = "",
        raw_prefix: str = "raw/",
        threshold_bytes: int = 200 * 1024,
    ) -> None:
        self.queue_url = queue_url
        self.region = region
        self.raw_bucket = raw_bucket
        self.raw_prefix = raw_prefix
        self.threshold_bytes = threshold_bytes
        self._client = boto3.client("sqs", region_name=region)

    # -- Public API --------------------------------------------------------

    def send_batch(
        self,
        source: str,
        items: Iterable[ArticleIn],
        trace_id: str | None = None,
    ) -> tuple[int, int]:
        """
        Send a list of ArticleIn as ONE SQS message.

        Returns ``(sent_count, failed_count)``.
        """
        items = list(items)
        if not items or not self.queue_url:
            return 0, 0

        trace_id = trace_id or str(uuid.uuid4())
        payload_bytes = json.dumps(
            [a.to_json_dict() for a in items],
            ensure_ascii=False,
        ).encode("utf-8")

        # -- Decide: inline or claim-check?
        use_claim_check = (
            len(payload_bytes) > self.threshold_bytes and bool(self.raw_bucket)
        )

        attrs = {
            "Source": {"DataType": "String", "StringValue": source},
            "Count": {"DataType": "Number", "StringValue": str(len(items))},
            "TraceID": {"DataType": "String", "StringValue": trace_id},
        }

        try:
            if use_claim_check:
                key = upload_payload(
                    payload_bytes, self.raw_bucket, self.raw_prefix, self.region
                )
                body = json.dumps(
                    {
                        "claim_check_s3_bucket": self.raw_bucket,
                        "claim_check_s3_key": key,
                    }
                )
                attrs["ClaimCheck"] = {"DataType": "String", "StringValue": "true"}
            else:
                body = payload_bytes.decode("utf-8")

            self._client.send_message(
                QueueUrl=self.queue_url,
                MessageBody=body,
                MessageAttributes=attrs,
            )
            log.info(
                "sqs.sent source=%s count=%d bytes=%d claim_check=%s trace=%s",
                source,
                len(items),
                len(payload_bytes),
                use_claim_check,
                trace_id,
            )
            return len(items), 0

        except Exception as exc:
            log.error(
                "sqs.send_failed source=%s count=%d trace=%s error=%s",
                source,
                len(items),
                trace_id,
                exc,
            )
            return 0, len(items)
