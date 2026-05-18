"""Small end-to-end test of the full new pipeline.

Scrapes ONE company (Permira via Greenhouse API — fast, no Playwright),
upserts to DB, runs the AI filter on the new URL delta, persists decisions
to `ai_keep`/`ai_reason`, fetches the 7-day window with the new filter,
and renders the email HTML to `preview_digest.html`.

Does NOT send email via Resend.

Run: uv run python -m src.e2e_small
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

from .ai_filter import filter_jobs
from .db import (
    get_client,
    get_jobs_last_n_days,
    get_or_create_company,
    record_filter_decisions,
    upsert_jobs,
)
from .email_digest import _render_section
from .main import _resolve_scraper
from .models import CompanyConfig, ScraperConfig
import yaml

load_dotenv()

_OUTPUT_HTML = Path(__file__).parent.parent / "preview_digest.html"
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "companies.yaml"

# Tight list of companies that scrape FAST (no Playwright) for the small e2e.
_TEST_COMPANIES = {"Permira"}


async def main() -> None:
    t_start = time.monotonic()

    print(f"E2E small: testing pipeline with companies = {_TEST_COMPANIES}")
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    config = ScraperConfig(**raw)
    targets = [c for c in config.companies if c.name in _TEST_COMPANIES]
    if not targets:
        print(f"No matching companies in {_CONFIG_PATH}")
        return

    db = get_client()

    # Scrape + upsert
    all_new: list[tuple[str, object]] = []
    for company in targets:
        print(f"\n[scrape] {company.name} ({company.ats})")
        scraper_cls = _resolve_scraper(company)
        if not scraper_cls:
            print(f"  no scraper resolved")
            continue
        scraper = scraper_cls(company, config.default_location_filter)
        jobs = await scraper.fetch_jobs()
        print(f"  fetched {len(jobs)} job(s)")
        company_id = get_or_create_company(db, company.name, company.careers_url, company.ats)
        new_jobs = upsert_jobs(db, company_id, jobs)
        print(f"  inserted {len(new_jobs)} new")
        for j in new_jobs:
            all_new.append((company.name, j))

    print(f"\n[pipeline] {len(all_new)} new URL(s) to filter")
    if not all_new:
        print("  nothing new to test against -- DB already has these. Apply DELETE FROM jobs first if you want a fresh test.")
        return

    # AI filter on the URL delta
    print("\n[ai_filter] running...")
    decisions = await filter_jobs(all_new)
    by_url = {d.url: d for d in decisions}
    kept_urls = {d.url for d in decisions if d.keep}
    print(f"  -> {len(kept_urls)}/{len(all_new)} kept")

    print("\n[decisions]")
    for company, job in all_new:
        d = by_url.get(job.url)
        flag = "[KEEP]" if d and d.keep else "[DROP]"
        reason = (d.reason if d else "(missing)")[:70]
        real = "real" if (d and d.is_real) else "passthrough"
        print(f"  {flag} {company:20s} {job.title[:55]}  ({reason}) [{real}]")

    # Persist decisions
    persisted = record_filter_decisions(db, decisions)
    print(f"\n[db] persisted {persisted} real decisions")

    # Fetch 7-day window via the new filter (should match kept_urls if all decisions were real)
    section_b = get_jobs_last_n_days(db, 7)
    print(f"\n[db] get_jobs_last_n_days(7) -> {len(section_b)} jobs (ai_keep IS NOT FALSE)")

    # Build Section A
    section_a = [(c, j) for (c, j) in all_new if j.url in kept_urls]

    # Render HTML
    print("\n[render] writing email HTML preview...")
    section_a_html = _render_section("Nuevos hoy", section_a)
    section_b_html = _render_section("Últimos 7 días", section_b)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Digest preview (small e2e)</title></head>
<body style='background:#f9fafb;padding:40px'>
<div style='font-family:sans-serif;max-width:640px;margin:0 auto;background:white;padding:24px;border-radius:8px'>
    <h2 style='border-bottom:1px solid #e5e7eb;padding-bottom:8px'>Job Tracker (SMALL E2E PREVIEW)</h2>
    {section_a_html}
    {section_b_html}
    <hr style='margin-top:24px;border:none;border-top:1px solid #e5e7eb'>
    <p style='color:#9ca3af;font-size:12px'>Filtrado por IA según config/preferences.md. Madrid (+ London cuando aplica).</p>
</div>
</body></html>"""
    _OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"  written to {_OUTPUT_HTML}")

    elapsed = time.monotonic() - t_start
    print(f"\n=== Total elapsed: {elapsed:.1f}s ===")
    print(f"Section A (new today, kept): {len(section_a)} jobs")
    print(f"Section B (last 7 days, kept incl. NULL): {len(section_b)} jobs")
    print(f"\nOpen {_OUTPUT_HTML.name} in a browser to inspect the email.")


if __name__ == "__main__":
    asyncio.run(main())
