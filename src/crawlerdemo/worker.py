"""
worker.py — Crawler process that runs on an EC2 ASG instance.

Lifecycle on the host
---------------------
1. systemd (via user_data) starts the Docker container at boot.
2. Container entrypoint → ``python -m crawlerdemo.worker``.
3. This module starts an APScheduler BackgroundScheduler that calls
   :func:`run_once` every ``interval_seconds``.
4. ``max_instances=1`` guarantees that a long-running cycle never overlaps
   with the next trigger *within this process*.
5. Each cycle pulls the configured RSS + sitemap sources, normalises the
   URLs, and ships the resulting ArticleIn batch to SQS Standard.
   When the JSON payload approaches the 256 KB SQS limit, the Claim Check
   Pattern kicks in transparently (see :mod:`crawlerdemo.sqs_client`).

The worker itself holds **no** state — it never touches the database.
All persistence is the Lambda ingester's responsibility.
"""
from __future__ import annotations

import logging
import signal
import time
import uuid
from urllib.parse import urlsplit

from apscheduler.schedulers.background import BackgroundScheduler

from crawlerdemo.config import get_settings
from crawlerdemo.http import make_client
from crawlerdemo.sources import crawl_rss, crawl_sitemap
from crawlerdemo.sqs_client import SqsSender

log = logging.getLogger("crawlerdemo.worker")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _domain(url: str) -> str:
    return urlsplit(url).netloc or "source"


def _crawl_one_source(
    client,
    kind: str,
    url: str,
    sender: SqsSender,
    max_items: int,
    trace_id: str,
) -> None:
    """Fetch a single RSS / sitemap URL and push the batch to SQS."""
    domain = _domain(url)
    source_label = f"{kind}:{domain}"
    try:
        if kind == "rss":
            items = list(crawl_rss(client, source_label, url, max_items))
        else:
            items = list(crawl_sitemap(client, source_label, url, max_items))

        if not items:
            log.info("crawl.empty url=%s", url)
            return

        sent, failed = sender.send_batch(source_label, items, trace_id=trace_id)
        log.info(
            "crawl.done kind=%s url=%s items=%d sent=%d failed=%d",
            kind,
            url,
            len(items),
            sent,
            failed,
        )

    except Exception as exc:
        # One bad source must not abort the whole cycle.
        log.exception("crawl.error kind=%s url=%s error=%s", kind, url, exc)


# ── Public entrypoints ───────────────────────────────────────────────────────


def run_once() -> None:
    """One full crawl pass over every configured source."""
    s = get_settings()
    run_trace = str(uuid.uuid4())
    log.info("run_once.start trace=%s", run_trace)

    if not s.sqs_queue_url:
        log.warning("sqs_queue_url is empty — messages would be dropped; aborting cycle")
        return

    sender = SqsSender(
        queue_url=s.sqs_queue_url,
        region=s.aws_region,
        raw_bucket=s.s3_raw_bucket,
        raw_prefix=s.s3_raw_prefix,
        threshold_bytes=s.claim_check_threshold_bytes,
    )

    with make_client(s.user_agent, s.request_timeout_s) as client:
        for rss_url in map(str, s.rss_urls):
            _crawl_one_source(
                client, "rss", rss_url, sender, s.max_items_per_source, run_trace
            )
        for sm_url in map(str, s.sitemap_urls):
            _crawl_one_source(
                client, "sitemap", sm_url, sender, s.max_items_per_source, run_trace
            )

    log.info("run_once.finish trace=%s", run_trace)


def run_forever() -> None:
    """
    Keep a long-lived APScheduler alive.

    ``max_instances=1`` prevents two overlapping executions within this
    process.  ``coalesce=True`` collapses missed triggers (e.g. after a long
    pause) into a single catch-up run instead of a burst.
    """
    s = get_settings()
    logging.basicConfig(
        level=getattr(logging, s.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if s.schedule_mode == "once":
        run_once()
        return

    scheduler = BackgroundScheduler(
        job_defaults={
            "max_instances": 1,  # Never overlap cycles
            "coalesce": True,    # Collapse missed runs to one catch-up
        }
    )
    scheduler.add_job(
        run_once,
        "interval",
        seconds=s.interval_seconds,
        id="crawl_cycle",
        next_run_time=None,  # first run on next tick
    )
    scheduler.start()
    log.info("scheduler.started interval_s=%d", s.interval_seconds)

    # Graceful shutdown on SIGTERM (used by systemd / container stop)
    stop_event = {"stop": False}

    def _on_signal(signum, _frame):  # pragma: no cover - signal handling
        log.info("signal.received signum=%s, shutting down", signum)
        stop_event["stop"] = True

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    try:
        # Run one cycle immediately so we don't wait a full interval after boot
        run_once()
        while not stop_event["stop"]:
            time.sleep(1)
    finally:
        scheduler.shutdown(wait=True)
        log.info("scheduler.stopped")


if __name__ == "__main__":
    run_forever()
