-- =============================================================================
-- schema.sql — RDS PostgreSQL DDL for the Crawler ingestion pipeline.
--
-- Must be applied once after `terraform apply` creates the RDS instance.
-- Run example (from a bastion / SSM session):
--
--     psql "host=<rds-endpoint> user=crawler dbname=crawlerdb" -f schema.sql
--
-- The Lambda ingester relies on:
--   1. The `articles` table existing.
--   2. A UNIQUE constraint on `canonical_url` so that
--      `INSERT ... ON CONFLICT (canonical_url) DO NOTHING` is atomic.
-- =============================================================================

CREATE TABLE IF NOT EXISTS articles (
    id            BIGSERIAL PRIMARY KEY,
    source        VARCHAR(120)  NOT NULL,
    canonical_url VARCHAR(2048) NOT NULL,
    title         VARCHAR(512),
    summary       TEXT,
    published_at  TIMESTAMPTZ,
    fetched_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- UNIQUE INDEX on canonical_url
--   * Backs the ON CONFLICT clause used by the Lambda ingester.
--   * Idempotency at the database layer — no duplicates are possible even
--     under concurrent inserts from many Lambda workers.
CREATE UNIQUE INDEX IF NOT EXISTS uq_articles_canonical_url
    ON articles (canonical_url);

-- Secondary indexes for dashboard / export queries
CREATE INDEX IF NOT EXISTS idx_articles_source     ON articles (source);
CREATE INDEX IF NOT EXISTS idx_articles_fetched_at ON articles (fetched_at DESC);
