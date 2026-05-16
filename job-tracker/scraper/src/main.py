import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

from .ai_filter import filter_jobs
from .db import (
    finish_scrape_run,
    get_client,
    get_jobs_last_n_days,
    get_or_create_company,
    start_scrape_run,
    upsert_jobs,
)
from .email_digest import send_digest
from .models import CompanyConfig, Job, ScraperConfig
from .scrapers import (
    AccionaScraper,
    AlantraScraper,
    BcgScraper,
    BdoSpainScraper,
    CegidTalentSoftScraper,
    DcAdvisoryScraper,
    EyScraper,
    GreenhouseScraper,
    HtmlScraper,
    LeverScraper,
    McKinseyScraper,
    MediobancaScraper,
    MorganStanleyScraper,
    OliverWymanScraper,
    PlaywrightScraper,
    PwcSpainScraper,
    SapSuccessFactorsScraper,
    TalentLinkScraper,
    UbsScraper,
    WorkdayScraper,
)

if TYPE_CHECKING:
    from .scrapers.base import BaseScraper

load_dotenv()

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "companies.yaml"

_SCRAPER_MAP: dict[str, type["BaseScraper"]] = {
    "greenhouse": GreenhouseScraper,
    "lever": LeverScraper,
    "html": HtmlScraper,
    "playwright": PlaywrightScraper,
    "workday": WorkdayScraper,
}


def _resolve_scraper(company: CompanyConfig) -> type["BaseScraper"] | None:
    """Pick the right scraper, auto-upgrading to a specialized one when the URL host gives it away.

    A company configured as ``playwright`` but pointing at ``*.myworkdayjobs.com``
    should use ``WorkdayScraper`` — the API is dramatically more reliable than
    rendering the SPA.
    """
    explicit = _SCRAPER_MAP.get(company.ats)
    if company.careers_url:
        host = (urlparse(company.careers_url).hostname or "").lower()
        if host.endswith("myworkdayjobs.com"):
            return WorkdayScraper
        if host == "www.alantra.com" or host == "alantra.com":
            return AlantraScraper
        if host == "careers.bcg.com":
            return BcgScraper
        if host == "bdo.epreselec.com":
            return BdoSpainScraper
        if host == "www.acciona.com" or host == "acciona.com":
            return AccionaScraper
        if host in ("caixabankcareers.com", "www.caixabankcareers.com", "empleo.es.deloitte.com"):
            return SapSuccessFactorsScraper
        if host == "jobs.ca-cib.com" or host == "jobs.amundi.com":
            return CegidTalentSoftScraper
        if host == "www.dcadvisory.com" or host == "dcadvisory.com":
            return DcAdvisoryScraper
        if host == "eyglobal.yello.co":
            return EyScraper
        if host == "www.mckinsey.com" or host == "mckinsey.com":
            return McKinseyScraper
        if host == "www.mediobanca.com" or host == "mediobanca.com":
            return MediobancaScraper
        if host == "www.morganstanley.com" or host == "morganstanley.com":
            return MorganStanleyScraper
        if host == "careers.marsh.com" and "oliver-wyman" in (urlparse(company.careers_url).path or "").lower():
            return OliverWymanScraper
        if host == "www.pwc.es" or host == "pwc.es":
            return PwcSpainScraper
        if host.endswith(".tal.net"):
            return TalentLinkScraper
        if host == "jobs.ubs.com":
            return UbsScraper
    return explicit


async def _scrape_company(
    company: CompanyConfig,
    default_location_filter: str,
) -> tuple[list[Job], str | None]:
    scraper_cls = _resolve_scraper(company)
    if not scraper_cls:
        return [], f"Unknown ATS '{company.ats}'"

    try:
        scraper = scraper_cls(company, default_location_filter)
        jobs = await scraper.fetch_jobs()
        print(f"  [{company.name}] fetched {len(jobs)} matching job(s)")
        return jobs, None
    except Exception as exc:
        return [], str(exc)


async def run() -> None:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    config = ScraperConfig(**raw)

    db = get_client()
    run_id = start_scrape_run(db)

    all_new: list[tuple[str, Job]] = []
    errors: list[dict] = []

    for company in config.companies:
        print(f"Scraping {company.name} ({company.ats})…")
        jobs, error = await _scrape_company(company, config.default_location_filter)

        if error:
            print(f"  [ERROR] {company.name}: {error}")
            errors.append({"company": company.name, "error": error})
            continue

        company_id = get_or_create_company(db, company.name, company.careers_url, company.ats)
        new_jobs = upsert_jobs(db, company_id, jobs)
        print(f"  [{company.name}] {len(new_jobs)} new job(s) inserted")

        for job in new_jobs:
            all_new.append((company.name, job))

    # Section B candidates: every active job first seen in the last 7 days.
    # Includes today's new jobs by construction.
    seven_day_candidates = get_jobs_last_n_days(db, 7)

    # Defensive: ensure today's new jobs are in the candidate list even under
    # clock skew between the scraper host and Supabase.
    existing_urls = {j.url for _, j in seven_day_candidates}
    for company_name, job in all_new:
        if job.url not in existing_urls:
            seven_day_candidates.append((company_name, job))

    # Single AI filter call over the 7-day window — Section A is derived by
    # intersection, so the same job can't be kept in one section and dropped in
    # the other.
    filtered = await filter_jobs(seven_day_candidates)
    new_urls = {j.url for _, j in all_new}
    section_a = [(c, j) for (c, j) in filtered if j.url in new_urls]
    section_b = filtered

    send_digest(section_a, section_b)
    finish_scrape_run(db, run_id, len(all_new), errors)
    print(
        f"\nDone — {len(all_new)} new job(s) scraped, "
        f"{len(section_a)} kept in Section A, {len(section_b)} kept in Section B."
    )


_TARGET_HOUR_MADRID = 7


def _skip_off_schedule() -> bool:
    """Return True iff SCHEDULED_RUN=1 and Madrid local hour != 07.

    Railway runs the cron at both 05:00 and 06:00 UTC; whichever fires at
    07:00 Europe/Madrid (DST-aware) actually executes the scrape.
    """
    if os.environ.get("SCHEDULED_RUN") != "1":
        return False
    now_madrid = datetime.now(ZoneInfo("Europe/Madrid"))
    if now_madrid.hour == _TARGET_HOUR_MADRID:
        return False
    print(
        f"SCHEDULED_RUN=1 but Madrid hour is {now_madrid.hour:02d} "
        f"(target {_TARGET_HOUR_MADRID:02d}) — skipping."
    )
    return True


def main() -> None:
    if _skip_off_schedule():
        return
    asyncio.run(run())
