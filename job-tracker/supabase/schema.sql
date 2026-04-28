-- Job Tracker — Supabase Schema
-- Run this in the Supabase SQL editor (Project → SQL Editor → New query)

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─── Companies ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS companies (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT        NOT NULL UNIQUE,
    careers_url  TEXT,
    ats_platform TEXT        NOT NULL,  -- 'greenhouse' | 'lever' | 'playwright' | 'html'
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Jobs ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS jobs (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id    UUID        NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    external_id   TEXT,                   -- ATS-native job ID (Greenhouse/Lever); null for HTML/Playwright
    title         TEXT        NOT NULL,
    url           TEXT        NOT NULL,
    location      TEXT,
    department    TEXT,
    job_type      TEXT,                   -- 'full-time' | 'internship' | 'part-time' | 'contract'
    description   TEXT,                   -- first ~500 chars of the job description
    is_active     BOOLEAN     NOT NULL DEFAULT TRUE,   -- set to false when a listing disappears
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_jobs_company_url UNIQUE (company_id, url)
);

CREATE INDEX IF NOT EXISTS idx_jobs_company_id    ON jobs (company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen_at ON jobs (first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_is_active     ON jobs (is_active);

-- ─── Scrape runs (lightweight audit log) ─────────────────────────────────────

CREATE TABLE IF NOT EXISTS scrape_runs (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at   TIMESTAMPTZ,
    new_jobs_found INTEGER     NOT NULL DEFAULT 0,
    status         TEXT        NOT NULL DEFAULT 'running',  -- 'running' | 'completed' | 'failed'
    errors         JSONB
);

-- ─── Row Level Security ───────────────────────────────────────────────────────
-- The frontend uses the anon key (public read only).
-- The scraper uses the service_role key (bypasses RLS entirely).

ALTER TABLE companies   ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE scrape_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon read companies"   ON companies   FOR SELECT USING (true);
CREATE POLICY "anon read jobs"        ON jobs        FOR SELECT USING (true);
CREATE POLICY "anon read scrape_runs" ON scrape_runs FOR SELECT USING (true);
