from __future__ import annotations

import logging
import time
from urllib.parse import urlsplit

from apscheduler.schedulers.background import BackgroundScheduler

from crawlerdemo.config import get_settings
from crawlerdemo.http import make_client
from crawlerdemo.sources import crawl_rss, crawl_sitemap


def _name_from_url(url: str) -> str:
    p = urlsplit(url)
    return p.netloc or "source"


def _encode_article(a) -> dict:
    return {
        "source": a.source,
        "canonical_url": a.canonical_url,
        "title": a.title,
        "summary": a.summary,
        "published_at": a.published_at.isoformat() if a.published_at else None,
    }


def _send_to_sqs(queue_url: str, source: str, items: list) -> tuple[int, int]:
    if not items or not queue_url:
        return 0, 0
    import json
    import boto3
    try:
        # We can send up to 10 messages per batch in SQS, or we can send the entire array as 1 message payload
        # SQS max message payload is 256KB. Sending a batch of articles in one message is highly efficient.
        sqs = boto3.client("sqs", region_name=get_settings().s3_region)
        payload = json.dumps([_encode_article(i) for i in items])
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=payload,
            MessageAttributes={
                "Source": {"DataType": "String", "StringValue": source},
                "Count": {"DataType": "Number", "StringValue": str(len(items))}
            }
        )
        return len(items), 0
    except Exception as exc:
        logging.getLogger("crawlerdemo").error("Failed to send %s to SQS: %s", source, exc)
        return 0, len(items)


def run_once() -> None:
    s = get_settings()
    logging.basicConfig(level=getattr(logging, s.log_level.upper(), logging.INFO))
    log = logging.getLogger("crawlerdemo")

    with make_client(s.user_agent, s.request_timeout_s) as client:
        for rss_url in map(str, s.rss_urls):
            source = f"rss:{_name_from_url(rss_url)}"
            items = list(crawl_rss(client, source, rss_url, s.max_items_per_source))
            if s.sqs_data_queue_url:
                ins, skip = _send_to_sqs(s.sqs_data_queue_url, source, items)
                log.info("rss %s queued=%s dropped=%s", rss_url, ins, skip)
            else:
                log.warning("SQS Queue URL not configured. Dropping %d items from %s", len(items), rss_url)

        for sm_url in map(str, s.sitemap_urls):
            source = f"sitemap:{_name_from_url(sm_url)}"
            items = list(crawl_sitemap(client, source, sm_url, s.max_items_per_source))
            if s.sqs_data_queue_url:
                ins, skip = _send_to_sqs(s.sqs_data_queue_url, source, items)
                log.info("sitemap %s queued=%s dropped=%s", sm_url, ins, skip)
            else:
                log.warning("SQS Queue URL not configured. Dropping %d items from %s", len(items), sm_url)


def run_forever() -> None:
    s = get_settings()
    logging.basicConfig(level=getattr(logging, s.log_level.upper(), logging.INFO))
    log = logging.getLogger("crawlerdemo")

    if s.schedule_mode == "once":
        run_once()
        return

    scheduler = BackgroundScheduler()
    scheduler.add_job(run_once, "interval", seconds=s.interval_seconds, max_instances=1)
    scheduler.start()
    log.info("scheduler started interval_seconds=%s", s.interval_seconds)

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.shutdown(wait=True)


if __name__ == "__main__":
    run_forever()

